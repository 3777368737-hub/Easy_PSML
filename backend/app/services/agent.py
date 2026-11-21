from __future__ import annotations

import json
import re
from typing import AsyncIterator, Dict, List, Optional, Tuple

from app.errors import ModelOutputError
from app.schemas import (
    AgentAction,
    AgentCapabilityCall,
    AgentCommandResponse,
    AgentControl,
    AgentConversationMessage,
    AgentMissingField,
    AgentPageContext,
    AgentPendingAction,
    AgentPlan,
    AgentUiAction,
)
from app.services.agent_capabilities import (
    canonical_workflow_snapshot,
    capability_catalog,
    capability_summary,
    focus_action_for_missing,
    get_capability,
    infer_capability,
    validate_capability,
    validate_ui_actions,
)
from app.services.prompts import VOICE_AGENT_SYSTEM_PROMPT
from app.services.qwen_client import QwenClient
from app.services.store import PendingAgentActionRecord, get_store


qwen_client = QwenClient()
ALLOWED_AGENT_PATHS = {
    "/",
    "/profile",
    "/program",
    "/story",
    "/result",
    "/batch",
    "/library",
}
MAX_ACTIONS = 3
MAX_AGENT_MESSAGE_CHARS = 160
AGENT_STREAM_MAX_TOKENS = 1200
PROFILE_CONTROL_FIELDS = {
    "full-name": "full_name",
    "current-university": "current_university",
    "major": "major",
    "gpa": "gpa",
    "graduation-year": "graduation_year",
    "english-score": "english_test_score",
    "target-degree": "target_degree",
    "target-field": "target_field",
    "target-country": "target_country",
    "research-experience": "research_experience",
    "internship-experience": "internship_experience",
    "project-experience": "project_experience",
    "activities-awards": "activities_awards",
    "motivation-text": "motivation_text",
    "career-goal": "career_goal",
}
PROGRAM_CONTROL_FIELDS = {
    "program-school_name": "school_name",
    "program-program_name": "program_name",
    "program-essay_type": "essay_type",
    "program-word_limit": "word_limit",
    "program-prompt_text": "prompt_text",
    "program-program_details": "program_details",
}


def _json(value: object) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif isinstance(value, list):
        value = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            for item in value
        ]
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _control_lookup(
    context: AgentPageContext,
) -> Tuple[Dict[str, AgentControl], Dict[str, AgentControl]]:
    by_id = {control.id: control for control in context.controls}
    by_key = {control.key: control for control in context.controls}
    return by_id, by_key


def _resolve_control(
    action: AgentAction,
    by_id: Dict[str, AgentControl],
    by_key: Dict[str, AgentControl],
) -> Optional[AgentControl]:
    if action.target_id and action.target_id in by_id:
        return by_id[action.target_id]
    if action.target_key and action.target_key in by_key:
        return by_key[action.target_key]
    return None


def _normalize_fill_value(control: AgentControl, value: str) -> Optional[str]:
    cleaned = value.strip()
    if control.kind == "select":
        for option in control.options:
            if cleaned == option.value:
                return option.value
        for option in control.options:
            if cleaned.casefold() in {
                option.label.casefold(),
                option.value.casefold(),
            }:
                return option.value
        return None
    if control.kind == "checkbox":
        lowered = cleaned.casefold()
        if lowered in {"true", "1", "yes", "on", "是", "选中"}:
            return "true"
        if lowered in {"false", "0", "no", "off", "否", "取消"}:
            return "false"
        return None
    if control.kind == "number":
        if not cleaned:
            return None
        try:
            numeric = float(cleaned)
        except ValueError:
            return None
        if control.min_value is not None and numeric < control.min_value:
            return None
        if control.max_value is not None and numeric > control.max_value:
            return None
    max_length = (
        control.max_length
        if control.max_length is not None and control.max_length > 0
        else 12000 if control.kind == "textarea" else 2000
    )
    if len(cleaned) > max_length:
        return None
    return cleaned


def _sanitize_actions(
    plan: AgentPlan,
    context: AgentPageContext,
) -> Tuple[List[AgentAction], bool]:
    by_id, by_key = _control_lookup(context)
    actions: List[AgentAction] = []
    needs_confirmation = plan.needs_confirmation

    for action in plan.actions:
        if len(actions) >= MAX_ACTIONS:
            break

        if action.type == "navigate":
            if not action.path or action.path not in ALLOWED_AGENT_PATHS:
                continue
            target_key = action.target_key.strip() if action.target_key else None
            actions.append(
                AgentAction(
                    type="navigate",
                    target_key=target_key,
                    path=action.path,
                    reason=action.reason,
                    risk="safe",
                )
            )
            continue

        control = _resolve_control(action, by_id, by_key)
        if control is None or control.disabled:
            continue

        if action.type == "focus":
            actions.append(
                AgentAction(
                    type="focus",
                    target_id=control.id,
                    target_key=control.key,
                    reason=action.reason,
                    risk="safe",
                )
            )
            continue

        if action.type == "fill":
            if control.kind not in {
                "text",
                "textarea",
                "select",
                "number",
                "checkbox",
            }:
                continue
            if action.value is None:
                continue
            normalized = _normalize_fill_value(control, action.value)
            if normalized is None:
                continue
            actions.append(
                AgentAction(
                    type="fill",
                    target_id=control.id,
                    target_key=control.key,
                    value=normalized,
                    reason=action.reason,
                    risk="safe",
                )
            )
            continue

        if action.type == "click":
            if control.kind not in {"button", "link"} or control.risk == "blocked":
                continue
            risk = "confirm" if control.risk == "confirm" else "safe"
            if risk == "confirm":
                needs_confirmation = True
            actions.append(
                AgentAction(
                    type="click",
                    target_id=control.id,
                    target_key=control.key,
                    reason=action.reason,
                    risk=risk,
                )
            )

    return actions, needs_confirmation


async def transcribe_audio(audio: bytes, media_type: str) -> str:
    return await qwen_client.transcribe(audio, media_type)


async def transcribe_audio_stream(
    audio: bytes, media_type: str
) -> AsyncIterator[str]:
    async for delta in qwen_client.stream_transcribe(audio, media_type):
        yield delta


def _agent_messages(
    owner_id: str,
    transcript: str,
    context: AgentPageContext,
    history: List[AgentConversationMessage],
) -> List[Dict[str, str]]:
    pending = get_store().get_pending_agent_action(owner_id)
    canonical_state = canonical_workflow_snapshot(owner_id, context)
    return [
        {"role": "system", "content": VOICE_AGENT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Resolve the user's command against the current GradPilot page.\n\n"
                f"User transcript:\n{transcript.strip()}\n\n"
                f"Recent assistant/user history:\n{_json(history)}\n\n"
                f"Active pending action:\n"
                f"{_json(pending_action_schema(pending)) if pending else 'null'}\n\n"
                f"Available capabilities:\n{_json(capability_catalog())}\n\n"
                f"Canonical workflow state:\n{_json(canonical_state)}\n\n"
                f"Current page, semantic controls, and unsaved page data:\n"
                f"{_json(context)}"
            ),
        },
    ]


def pending_action_schema(
    pending: PendingAgentActionRecord,
) -> AgentPendingAction:
    return AgentPendingAction(
        id=pending.id,
        capability=pending.capability,
        arguments=pending.arguments,
        missing_fields=[
            AgentMissingField.model_validate(item)
            for item in pending.missing_fields
        ],
        status="prepared" if pending.status == "prepared" else "collecting",
        summary=pending.summary,
        expires_at=pending.expires_at,
    )


def _dedupe_ui_actions(actions: List[AgentUiAction]) -> List[AgentUiAction]:
    seen: set[tuple[str, str | None, str | None, str | None]] = set()
    result: List[AgentUiAction] = []
    for action in actions:
        key = (action.type, action.target_key, action.path, action.section)
        if key in seen:
            continue
        seen.add(key)
        result.append(action)
    return result[:6]


def _projected_context(
    context: AgentPageContext,
    actions: List[AgentUiAction],
) -> AgentPageContext:
    projected = context.model_copy(deep=True)
    for action in actions:
        if action.type != "fill" or not action.target_key or action.value is None:
            continue
        key = action.target_key
        value = action.value
        for control in projected.controls:
            if control.key == key:
                control.value = value
                break
        profile_form = projected.page_data.get("profile_form")
        if isinstance(profile_form, dict) and key in PROFILE_CONTROL_FIELDS:
            profile_form[PROFILE_CONTROL_FIELDS[key]] = value
        program_form = projected.page_data.get("program_form")
        if isinstance(program_form, dict) and key in PROGRAM_CONTROL_FIELDS:
            program_form[PROGRAM_CONTROL_FIELDS[key]] = value
        if key == "story-answer":
            projected.page_data["story_answer"] = value
        if key == "revision-instruction":
            projected.page_data["revision_instruction"] = value
        batch_form = projected.page_data.get("batch_form")
        if isinstance(batch_form, dict):
            directions = batch_form.get("directions")
            if not isinstance(directions, list):
                continue
            for direction in directions:
                if not isinstance(direction, dict):
                    continue
                direction_id = str(direction.get("id") or "")
                if not direction_id or not key.startswith(f"{direction_id}-"):
                    continue
                suffix = key[len(direction_id) + 1 :]
                if suffix == "school":
                    direction["school_name"] = value
                elif suffix == "program":
                    direction["program_name"] = value
                elif suffix == "details":
                    direction["program_details"] = value
                elif suffix.endswith("-words") or suffix.endswith("-prompt"):
                    essay_type = (
                        "Personal Statement"
                        if suffix.startswith("ps-")
                        else "Motivation Letter"
                    )
                    essays = direction.get("essays")
                    if isinstance(essays, dict):
                        essay = essays.get(essay_type)
                        if isinstance(essay, dict):
                            essay[
                                "word_limit"
                                if suffix.endswith("-words")
                                else "prompt_text"
                            ] = value
                break
    return projected


def _missing_message(
    capability: str,
    missing: List[AgentMissingField],
) -> str:
    spec = get_capability(capability)
    action_label = spec.label if spec else "当前操作"
    labels = "、".join(field.label for field in missing[:4])
    suffix = "等" if len(missing) > 4 else ""
    return f"{action_label}还不能执行，需要补充：{labels}{suffix}。"


async def _response_from_plan(
    owner_id: str,
    plan: AgentPlan,
    transcript: str,
    context: AgentPageContext,
    source: str,
) -> AgentCommandResponse:
    legacy_actions, _ = _sanitize_actions(plan, context)
    ui_actions = validate_ui_actions(context, plan.ui_actions)
    store = get_store()
    existing_pending = store.get_pending_agent_action(owner_id)
    capability = plan.capability or infer_capability(transcript, context)
    if capability is None and existing_pending is not None:
        capability = AgentCapabilityCall(
            name=existing_pending.capability,
            arguments=existing_pending.arguments,
        )
    elif capability is not None and existing_pending is not None:
        if existing_pending.capability == capability.name:
            capability = AgentCapabilityCall(
                name=capability.name,
                arguments={**existing_pending.arguments, **capability.arguments},
            )

    if capability is not None and capability.name == "agent.cancel_pending":
        store.cancel_pending_agent_action(owner_id)
        existing_pending = None
        capability = None

    status = "answered"
    pending_action: Optional[PendingAgentActionRecord] = None
    missing: List[AgentMissingField] = []
    needs_confirmation = False
    validation_context = _projected_context(context, ui_actions)

    confirmation_handled = False
    if capability is not None and capability.name == "agent.confirm_pending":
        if existing_pending is not None and existing_pending.status == "prepared":
            status = "ready"
            capability = AgentCapabilityCall(
                name="agent.confirm_pending",
                arguments={"action_id": existing_pending.id},
            )
            pending_action = existing_pending
            confirmation_handled = True
        elif existing_pending is not None:
            capability = AgentCapabilityCall(
                name=existing_pending.capability,
                arguments=existing_pending.arguments,
            )
        else:
            status = "needs_input"
            missing = [
                AgentMissingField(
                    key="action_id",
                    label="等待确认的 Agent 操作",
                )
            ]
            capability = None
            confirmation_handled = True

    if capability is not None and not confirmation_handled:
        spec = get_capability(capability.name)
        if spec is None:
            missing = [AgentMissingField(
                key="capability",
                label="当前页面支持的操作",
            )]
            status = "needs_input"
        else:
            missing = validate_capability(
                owner_id,
                validation_context,
                capability,
                store=store,
            )
            if missing:
                status = "needs_input"
                pending_action = store.upsert_pending_agent_action(
                    owner_id,
                    capability.name,
                    capability.arguments,
                    [item.model_dump(mode="json") for item in missing],
                    "collecting",
                    capability_summary(capability.name, capability.arguments),
                )
            elif spec.requires_confirmation:
                status = "confirmation_required"
                needs_confirmation = True
                pending_action = store.upsert_pending_agent_action(
                    owner_id,
                    capability.name,
                    capability.arguments,
                    [],
                    "prepared",
                    capability_summary(capability.name, capability.arguments),
                )
            else:
                status = "ready"
                if existing_pending is not None:
                    store.cancel_pending_agent_action(
                        owner_id,
                        existing_pending.id,
                    )

    if status == "needs_input":
        focus = focus_action_for_missing(missing)
        if focus is not None:
            ui_actions = _dedupe_ui_actions([*ui_actions, focus])

    effective_missing = missing or plan.missing_fields
    next_field = (
        effective_missing[0].target_key
        if effective_missing
        else plan.next_field
    )
    message = re.sub(r"\s+", " ", plan.message).strip()
    if status == "needs_input" and missing:
        message = _missing_message(
            capability.name if capability else "",
            missing,
        )
    if len(message) > MAX_AGENT_MESSAGE_CHARS:
        message = f"{message[: MAX_AGENT_MESSAGE_CHARS - 3].rstrip()}..."
    return AgentCommandResponse(
        transcript=transcript.strip(),
        message=message,
        intent=plan.intent,
        actions=legacy_actions,
        capability=capability,
        ui_actions=ui_actions,
        missing_fields=effective_missing,
        next_field=next_field,
        needs_confirmation=needs_confirmation,
        source="voice" if source == "voice" else "text",
        status=status,
        pending_action=(
            pending_action_schema(pending_action)
            if pending_action
            else None
        ),
    )


async def run_agent_command(
    owner_id: str,
    transcript: str,
    context: AgentPageContext,
    history: List[AgentConversationMessage],
    *,
    source: str,
) -> AgentCommandResponse:
    messages = _agent_messages(owner_id, transcript, context, history)
    plan = await qwen_client.chat_json(messages, AgentPlan, max_tokens=1800)
    return await _response_from_plan(
        owner_id,
        plan,
        transcript,
        context,
        source,
    )


async def stream_agent_command(
    owner_id: str,
    transcript: str,
    context: AgentPageContext,
    history: List[AgentConversationMessage],
    *,
    source: str,
) -> AsyncIterator[Tuple[str, object]]:
    messages = _agent_messages(owner_id, transcript, context, history)
    plan: Optional[AgentPlan] = None
    async for event in qwen_client.stream_chat_json(
        messages,
        AgentPlan,
        max_tokens=AGENT_STREAM_MAX_TOKENS,
    ):
        if event.reset_message:
            yield "message_reset", None
        if event.message_delta:
            yield "message_delta", event.message_delta
        if event.result is not None:
            plan = event.result

    if plan is None:
        raise ModelOutputError(
            "Qwen stream finished without a validated agent plan"
        )
    yield "final", await _response_from_plan(
        owner_id,
        plan,
        transcript,
        context,
        source,
    )
