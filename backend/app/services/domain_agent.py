from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, List, Optional

from app.errors import AppError, UpstreamServiceError
from app.schemas import (
    AgentCapabilityCall,
    AgentConversationMessage,
    AgentPlan,
    BatchCreateRequest,
    DomainAgentRequest,
    DomainCommandResponse,
    EssayBranchCreateRequest,
    EssayProjectDraftRequest,
    ProfilePatchOperation,
    ProgramContext,
    StoryCards,
)
from app.services import batch, domain_workflow, workflow
from app.services.domain_store import DomainStore, get_domain_store
from app.services.prompts import DOMAIN_AGENT_SYSTEM_PROMPT
from app.services.qwen_client import QwenClient


domain_qwen = QwenClient()
CONFIRM_CAPABILITIES = {
    "background.patch",
    "application_project.create",
    "story.create",
    "story.reply",
    "story.patch",
    "project.create",
    "project.patch",
    "project.analyze",
    "project.outline",
    "project.draft",
    "project.review",
    "essay_branch.create",
    "batch.create",
}


def _json(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif isinstance(value, list):
        value = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            for item in value
        ]
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _catalog(domain: DomainStore, owner_id: str) -> Dict[str, Any]:
    snapshot = domain.workspace_snapshot(owner_id)
    persons_by_id = {person.id: person for person in snapshot.persons}
    backgrounds_by_id = {
        background.id: background for background in snapshot.backgrounds
    }
    ready_stories_by_project: Dict[str, int] = {}
    for story in snapshot.stories:
        if story.status == "ready" and story.application_project_id:
            ready_stories_by_project[story.application_project_id] = (
                ready_stories_by_project.get(
                    story.application_project_id,
                    0,
                )
                + 1
            )
    return {
        "workflow_readiness": {
            "has_person": bool(snapshot.persons),
            "has_background": bool(snapshot.backgrounds),
            "has_application_project": bool(snapshot.application_projects),
            "has_ready_story": any(
                story.status == "ready" for story in snapshot.stories
            ),
            "has_essay_project": bool(snapshot.projects),
        },
        "persons": [
            {
                "id": person.id,
                "name": person.display_name,
                "aliases": person.aliases,
            }
            for person in snapshot.persons
        ],
        "backgrounds": [
            {
                "id": background.id,
                "person_id": background.person_id,
                "person_name": (
                    persons_by_id[background.person_id].display_name
                    if background.person_id in persons_by_id
                    else ""
                ),
                "resume_name": background.resume_name,
                "version": background.version,
                "status": background.status,
                "full_name": background.profile.basic_profile.full_name,
                "current_university": (
                    background.profile.basic_profile.current_university
                ),
                "major": background.profile.basic_profile.major,
                "target_field": background.profile.basic_profile.target_field,
            }
            for background in snapshot.backgrounds
        ],
        "application_projects": [
            {
                "id": project.id,
                "background_id": project.background_instance_id,
                "school_name": project.school_name,
                "program_name": project.program_name,
                "program_details_present": bool(
                    project.program_details.strip()
                ),
                "story_count": project.story_count,
                "ready_story_count": ready_stories_by_project.get(
                    project.id,
                    0,
                ),
                "essay_count": project.essay_count,
            }
            for project in snapshot.application_projects
        ],
        "stories": [
            {
                "id": story.id,
                "background_id": story.background_instance_id,
                "application_project_id": story.application_project_id,
                "title": story.title,
                "status": story.status,
                "round_no": story.round_no,
                "focus": story.focus,
            }
            for story in snapshot.stories
        ],
        "projects": [
            {
                "id": project.id,
                "background_id": project.background_instance_id,
                "school_name": project.program.school_name,
                "program_name": project.program.program_name,
                "essay_type": project.program.essay_type,
                "status": project.status,
                "current_step": project.current_step,
                "story_ids": project.story_instance_ids,
                "has_analysis": bool(project.analysis),
                "has_outline": bool(project.outline),
                "has_draft": bool(project.draft),
                "has_review": bool(project.review),
                "background_name": (
                    backgrounds_by_id[
                        project.background_instance_id
                    ].resume_name
                    if project.background_instance_id
                    in backgrounds_by_id
                    else ""
                ),
            }
            for project in snapshot.projects
        ],
    }


def _active_payload(
    domain: DomainStore,
    owner_id: str,
    request: DomainAgentRequest,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if request.active_person_id:
        try:
            payload["person"] = domain.get_person(
                owner_id,
                request.active_person_id,
            ).model_dump(mode="json")
        except AppError:
            pass
    if request.active_background_id:
        try:
            background = domain.get_background(
                owner_id,
                request.active_background_id,
            )
            payload["background"] = background.model_dump(mode="json")
        except AppError:
            pass
    if request.active_application_project_id:
        try:
            payload["application_project"] = domain.get_application_project(
                owner_id,
                request.active_application_project_id,
            ).model_dump(mode="json")
        except AppError:
            pass
    if request.active_story_id:
        try:
            story = domain.get_story(
                owner_id,
                request.active_story_id,
            )
            payload["story"] = {
                "id": story.id,
                "background_instance_id": story.background_instance_id,
                "title": story.title,
                "focus": story.focus,
                "status": story.status,
                "round_no": story.round_no,
                "cards": story.cards.model_dump(mode="json"),
            }
        except AppError:
            pass
    if request.active_project_id:
        try:
            project = domain.get_project(
                owner_id,
                request.active_project_id,
            )
            payload["project"] = {
                "id": project.id,
                "background_instance_id": project.background_instance_id,
                "story_instance_ids": project.story_instance_ids,
                "program": project.program.model_dump(mode="json"),
                "status": project.status,
                "current_step": project.current_step,
            }
        except AppError:
            pass
    return payload


def _messages(
    request: DomainAgentRequest,
    domain: DomainStore,
    owner_id: str,
) -> List[Dict[str, str]]:
    forced_creation = _is_new_essay_intent(request.transcript)
    return [
        {"role": "system", "content": DOMAIN_AGENT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Resolve one command against the GradPilot instance workspace.\n\n"
                f"Forced operation mode:\n{(
                    'create a brand-new essay branch; never patch or reuse an existing essay project'
                    if forced_creation
                    else 'normal; infer create, select, update, or generate from the user command'
                )}\n\n"
                f"Transcript:\n{request.transcript}\n\n"
                f"Recent history:\n{_json(request.history)}\n\n"
                f"Active IDs:\n{_json({
                    'person_id': request.active_person_id,
                    'background_id': request.active_background_id,
                    'application_project_id': request.active_application_project_id,
                    'story_id': request.active_story_id,
                    'project_id': request.active_project_id,
                })}\n\n"
                f"Pending domain action:\n{_json({
                    'capability': request.pending_capability,
                    'arguments': request.pending_arguments,
                    'resolved': request.pending_resolved,
                })}\n\n"
                f"Active instance payload:\n"
                f"{_json(_active_payload(domain, owner_id, request))}\n\n"
                f"Workspace catalog:\n{_json(_catalog(domain, owner_id))}"
            ),
        },
    ]


def _compact_text(value: str) -> str:
    return re.sub(r"[\s，。！？、,.!?;；:：]+", "", value.casefold())


def _clean_answer(value: str) -> str:
    cleaned = re.sub(
        r"^(?:嗯+|呃+|那个|就是|我说|回答是|答案是)[，,\s]*",
        "",
        value.strip(),
        flags=re.IGNORECASE,
    )
    return cleaned.strip("，。！？、,.!?;；:：\"'“”‘’")


def _is_new_essay_intent(transcript: str) -> bool:
    text = _compact_text(transcript)
    creation = any(
        word in text
        for word in (
            "创建",
            "新建",
            "新增",
            "从头",
            "另做",
            "新写",
            "开始写",
            "做一篇",
            "写一篇",
            "来一篇",
        )
    )
    essay = any(
        word in text
        for word in ("文书", "个人陈述", "动机信", "ps", "ml")
    )
    modification = any(
        word in text for word in ("修改", "更新", "改一下", "重写")
    )
    return creation and essay and not modification


def _resolved_pending_arguments(request: DomainAgentRequest) -> Dict[str, Any]:
    arguments = dict(request.pending_arguments)
    resolved = request.pending_resolved
    mappings = {
        "person_id": "person_id",
        "background_id": "background_instance_id",
        "application_project_id": "application_project_id",
        "project_id": "project_id",
        "batch_id": "batch_id",
    }
    for source, target in mappings.items():
        value = resolved.get(source)
        if isinstance(value, str) and value:
            arguments.setdefault(target, value)
    story_id = resolved.get("story_id")
    if isinstance(story_id, str) and story_id:
        args_story_ids = arguments.get("story_instance_ids")
        if not isinstance(args_story_ids, list) or not args_story_ids:
            arguments["story_instance_ids"] = [story_id]
    return arguments


def _new_essay_plan(transcript: str) -> Optional[AgentPlan]:
    if not _is_new_essay_intent(transcript):
        return None
    text = _compact_text(transcript)
    generate_after_create = any(
        word in text
        for word in ("并生成", "直接生成", "生成结果", "出稿", "生成草稿")
    )
    return AgentPlan(
        message=(
            "开始创建一篇新文书。我会依次确认人物背景、申请项目、"
            "已完成故事、PS/ML 类型和题目；项目官网资料可选。"
        ),
        intent="operate",
        capability=AgentCapabilityCall(
            name="essay_branch.create",
            arguments={
                "generate_after_create": generate_after_create,
            },
        ),
        needs_confirmation=True,
    )


def _pending_plan(request: DomainAgentRequest) -> Optional[AgentPlan]:
    capability = request.pending_capability
    if not capability:
        return None
    arguments = _resolved_pending_arguments(request)
    if request.confirmed:
        return AgentPlan(
            message="正在执行已确认的操作。",
            intent="operate",
            capability=AgentCapabilityCall(
                name=capability,
                arguments=arguments,
            ),
            needs_confirmation=True,
        )
    if _is_new_essay_intent(request.transcript) and capability != "essay_branch.create":
        return None
    answer = _clean_answer(request.transcript)
    if not answer:
        return None
    if re.match(
        r"^(?:创建|新建|添加|选择|切换|修改|更新|删除|打开|进入|"
        r"生成|分析|审核|重写|开始|暂停|继续|重做|记录|挖掘)",
        _compact_text(answer),
    ):
        return None

    if capability == "essay_branch.create":
        if not (
            arguments.get("background_instance_id")
            or arguments.get("background_id")
            or arguments.get("background_query")
            or request.active_background_id
        ):
            arguments["background_query"] = answer
        elif not (
            arguments.get("application_project_id")
            or arguments.get("application_project_query")
            or request.active_application_project_id
        ):
            arguments["application_project_query"] = answer
        elif not arguments.get("story_titles") and not arguments.get(
            "story_instance_ids"
        ):
            arguments["story_titles"] = [answer]
        elif not arguments.get("essay_type"):
            text = _compact_text(answer)
            if text in {"ps", "personalstatement", "个人陈述"}:
                arguments["essay_type"] = "Personal Statement"
            elif text in {"ml", "motivationletter", "动机信"}:
                arguments["essay_type"] = "Motivation Letter"
            else:
                arguments["essay_type"] = answer
        elif not arguments.get("prompt_text"):
            arguments["prompt_text"] = answer
        else:
            return None
        return AgentPlan(
            message="已记录这一步，继续补齐创建文书所需信息。",
            intent="operate",
            capability=AgentCapabilityCall(
                name=capability,
                arguments=arguments,
            ),
            needs_confirmation=True,
        )

    if capability == "application_project.create":
        if not (
            arguments.get("background_instance_id")
            or arguments.get("background_query")
            or request.active_background_id
        ):
            arguments["background_query"] = answer
        elif not arguments.get("school_name"):
            arguments["school_name"] = answer
        elif not arguments.get("program_name"):
            arguments["program_name"] = answer
        else:
            return None
        return AgentPlan(
            message="已记录申请项目信息。",
            intent="operate",
            capability=AgentCapabilityCall(
                name=capability,
                arguments=arguments,
            ),
            needs_confirmation=True,
        )

    if capability == "story.create":
        if not (
            arguments.get("application_project_id")
            or arguments.get("application_project_query")
            or request.active_application_project_id
        ):
            arguments["application_project_query"] = answer
        elif not arguments.get("title"):
            arguments["title"] = answer
        else:
            return None
        return AgentPlan(
            message="已记录故事信息。",
            intent="operate",
            capability=AgentCapabilityCall(
                name=capability,
                arguments=arguments,
            ),
            needs_confirmation=True,
        )
    return None


def _merge_plan_with_pending(
    plan: AgentPlan,
    request: DomainAgentRequest,
) -> AgentPlan:
    if (
        not request.pending_capability
        or plan.capability is None
        or plan.capability.name != request.pending_capability
    ):
        return plan
    arguments = {
        **_resolved_pending_arguments(request),
        **plan.capability.arguments,
    }
    return plan.model_copy(
        update={
            "capability": AgentCapabilityCall(
                name=plan.capability.name,
                arguments=arguments,
            )
        }
    )


async def _plan(
    request: DomainAgentRequest,
    domain: DomainStore,
    owner_id: str,
) -> AgentPlan:
    if request.confirmed:
        confirmed = _pending_plan(request)
        if confirmed is not None:
            return confirmed
    new_essay_intent = _is_new_essay_intent(request.transcript)
    if not new_essay_intent:
        pending = _pending_plan(request)
        if pending is not None:
            return pending
    try:
        plan = await domain_qwen.chat_json(
            _messages(request, domain, owner_id),
            AgentPlan,
            max_tokens=1800,
        )
        if new_essay_intent:
            if (
                plan.capability is not None
                and plan.capability.name == "essay_branch.create"
            ):
                return plan
            return _new_essay_plan(request.transcript) or plan
        return _merge_plan_with_pending(plan, request)
    except UpstreamServiceError:
        if new_essay_intent:
            return _new_essay_plan(request.transcript) or AgentPlan(
                message="开始创建一篇新文书。",
                intent="operate",
                capability=AgentCapabilityCall(
                    name="essay_branch.create",
                    arguments={},
                ),
                needs_confirmation=True,
            )
        fallback = _fallback_plan(request.transcript)
        if fallback is not None:
            return fallback
        return AgentPlan(
            message="当前无法解析这条装配指令，请换一种说法，或先在装配工作台完成操作。",
            intent="clarify",
        )


def _fallback_plan(transcript: str) -> Optional[AgentPlan]:
    text = re.sub(r"\s+", "", transcript)
    match = re.match(r"(?:新建|创建)人物(?:叫|为|：)?(.+)", transcript)
    if match:
        return AgentPlan(
            message="请确认创建这个人物。",
            intent="operate",
            capability=AgentCapabilityCall(
                name="person.create",
                arguments={"display_name": match.group(1).strip()},
            ),
            needs_confirmation=True,
        )
    if "暂停" in text:
        return AgentPlan(
            message="当前状态已经保存在装配工作台中，可以继续处理。",
            intent="answer",
            capability=AgentCapabilityCall(
                name="workflow.pause",
                arguments={},
            ),
        )
    return None


def _person(
    domain: DomainStore,
    owner_id: str,
    request: DomainAgentRequest,
    args: Dict[str, Any],
):
    query = str(
        args.get("person_query")
        or args.get("person")
        or args.get("person_name")
        or ""
    ).strip()
    person_id = str(
        args.get("person_id")
        or ("" if query else request.active_person_id)
        or ""
    )
    if person_id:
        return domain.get_person(owner_id, person_id), []
    candidates = domain.resolve_persons(owner_id, query) if query else []
    if query and len(candidates) == 1:
        return candidates[0], candidates
    return None, candidates


def _background(
    domain: DomainStore,
    owner_id: str,
    request: DomainAgentRequest,
    args: Dict[str, Any],
    person_id: Optional[str] = None,
):
    query = str(
        args.get("resume_name")
        or args.get("background_query")
        or args.get("resume")
        or ""
    ).strip()
    background_id = str(
        args.get("background_instance_id")
        or args.get("background_id")
        or ("" if query else request.active_background_id)
        or ""
    )
    if background_id:
        candidate = domain.get_background(owner_id, background_id)
        if person_id and candidate.person_id != person_id:
            return None, domain.list_backgrounds(owner_id, person_id)
        return candidate, []
    candidates = (
        domain.resolve_backgrounds(
            owner_id,
            query,
            person_id=person_id,
        )
        if query
        else domain.list_backgrounds(owner_id, person_id)
    )
    if query and len(candidates) == 1:
        return candidates[0], candidates
    return None, candidates


def _application_project(
    domain: DomainStore,
    owner_id: str,
    request: DomainAgentRequest,
    args: Dict[str, Any],
    background_id: Optional[str] = None,
):
    query = str(
        args.get("application_project_query")
        or args.get("application_project")
        or args.get("project_query")
        or ""
    ).strip()
    project_id = str(
        args.get("application_project_id")
        or ("" if query else request.active_application_project_id)
        or ""
    )
    if project_id:
        candidate = domain.get_application_project(owner_id, project_id)
        if background_id and candidate.background_instance_id != background_id:
            return None, domain.list_application_projects(
                owner_id,
                background_id,
            )
        return candidate, []
    candidates = (
        domain.resolve_application_projects(
            owner_id,
            query,
            background_id=background_id,
        )
        if query
        else domain.list_application_projects(owner_id, background_id)
    )
    if query and len(candidates) == 1:
        return candidates[0], candidates
    return None, candidates


def _story(
    domain: DomainStore,
    owner_id: str,
    request: DomainAgentRequest,
    args: Dict[str, Any],
    background_id: Optional[str] = None,
    application_project_id: Optional[str] = None,
):
    query = str(
        args.get("story_title")
        or args.get("story_query")
        or args.get("title")
        or ""
    ).strip()
    story_id = str(
        args.get("story_instance_id")
        or args.get("story_id")
        or ("" if query else request.active_story_id)
        or ""
    )
    if story_id:
        candidate = domain.get_story(owner_id, story_id)
        if background_id and candidate.background_instance_id != background_id:
            return None, domain.list_stories(
                owner_id,
                background_id,
                application_project_id,
            )
        if (
            application_project_id
            and candidate.application_project_id != application_project_id
        ):
            return None, domain.list_stories(
                owner_id,
                background_id,
                application_project_id,
            )
        return candidate, []
    candidates = (
        domain.resolve_stories(
            owner_id,
            query,
            background_id=background_id,
            application_project_id=application_project_id,
        )
        if query
        else domain.list_stories(
            owner_id,
            background_id,
            application_project_id,
        )
    )
    if query and len(candidates) == 1:
        return candidates[0], candidates
    return None, candidates


def _project(
    domain: DomainStore,
    owner_id: str,
    request: DomainAgentRequest,
    args: Dict[str, Any],
    background_id: Optional[str] = None,
):
    query = str(
        args.get("project_query")
        or args.get("program_name")
        or args.get("project")
        or ""
    ).strip()
    project_id = str(
        args.get("project_id")
        or ("" if query else request.active_project_id)
        or ""
    )
    if project_id:
        candidate = domain.get_project(owner_id, project_id)
        if background_id and candidate.background_instance_id != background_id:
            return None, domain.list_projects(
                owner_id,
                background_id=background_id,
            )
        return candidate, []
    candidates = (
        domain.resolve_projects(
            owner_id,
            query,
            background_id=background_id,
        )
        if query
        else domain.list_projects(owner_id, background_id=background_id)
    )
    if query and len(candidates) == 1:
        return candidates[0], candidates
    return None, candidates


def _needs_input(
    request: DomainAgentRequest,
    plan: AgentPlan,
    message: str,
    candidates: Any = None,
    resolved: Optional[Dict[str, Any]] = None,
) -> DomainCommandResponse:
    candidate_text = ""
    if isinstance(candidates, list) and candidates:
        labels: List[str] = []
        for candidate in candidates[:6]:
            if hasattr(candidate, "model_dump"):
                candidate = candidate.model_dump(mode="json")
            if not isinstance(candidate, dict):
                continue
            label = (
                candidate.get("display_name")
                or candidate.get("resume_name")
                or candidate.get("title")
                or " · ".join(
                    item
                    for item in (
                        candidate.get("school_name"),
                        candidate.get("program_name"),
                    )
                    if item
                )
            )
            if label and label not in labels:
                labels.append(str(label))
        if labels:
            candidate_text = " 可选：" + "；".join(labels) + "。"
    resolved_payload = {
        key: value
        for key, value in {
            "person_id": request.active_person_id,
            "background_id": request.active_background_id,
            "application_project_id": request.active_application_project_id,
            "story_id": request.active_story_id,
            "project_id": request.active_project_id,
            **request.pending_resolved,
            **(resolved or {}),
        }.items()
        if value
    }
    if candidates is not None:
        resolved_payload["candidates"] = candidates
    return DomainCommandResponse(
        transcript=request.transcript,
        message=f"{message}{candidate_text}",
        intent=plan.intent,
        status="needs_input",
        capability=plan.capability,
        arguments=plan.capability.arguments if plan.capability else {},
        resolved=resolved_payload,
        source=request.source,
    )


def _confirmation(
    request: DomainAgentRequest,
    plan: AgentPlan,
    resolved: Dict[str, Any],
) -> DomainCommandResponse:
    capability = plan.capability
    confirmations = {
        "background.patch": "将更新这份背景并生成新版本。",
        "application_project.create": "将把学校项目绑定到当前背景并保存。",
        "story.create": "将创建故事访谈并绑定当前申请项目。",
        "story.reply": "将提交本轮故事回答并进入下一轮。",
        "essay_branch.create": "前置信息已齐全，将创建并保存这篇新文书。",
        "project.analyze": "将分析当前文书项目。",
        "project.outline": "将生成并保存新版中文大纲。",
        "project.draft": "将生成并保存新版英文草稿。",
        "project.review": "将审核当前英文草稿。",
        "batch.create": "将创建批量文书生成任务。",
    }
    operation = confirmations.get(
        capability.name if capability else "",
        "将执行当前操作。",
    )
    if (
        capability is not None
        and capability.name == "essay_branch.create"
        and capability.arguments.get("generate_after_create")
    ):
        operation = (
            "前置信息已齐全，将创建新文书，并继续生成项目分析、"
            "中文大纲和英文草稿。"
        )
    return DomainCommandResponse(
        transcript=request.transcript,
        message=f"{operation} 请说“确认”执行，或说“取消”。",
        intent=plan.intent,
        status="confirmation_required",
        capability=capability,
        arguments=capability.arguments if capability else {},
        resolved=resolved,
        needs_confirmation=True,
        source=request.source,
    )


async def run_domain_command(
    owner_id: str,
    request: DomainAgentRequest,
) -> DomainCommandResponse:
    domain = get_domain_store()
    plan = await _plan(request, domain, owner_id)
    if plan.capability is None:
        return DomainCommandResponse(
            transcript=request.transcript,
            message=plan.message,
            intent=plan.intent,
            status="answered",
            source=request.source,
        )

    call = plan.capability
    name = call.name
    args = call.arguments
    resolved: Dict[str, Any] = {}
    person = None
    background = None
    story = None
    project = None

    try:
        if name == "person.create":
            display_name = str(args.get("display_name") or "").strip()
            if not display_name:
                return _needs_input(request, plan, "请先告诉我新人物叫什么。")
            if not request.confirmed:
                return _confirmation(request, plan, {})
            created = domain.create_person(owner_id, display_name)
            return DomainCommandResponse(
                transcript=request.transcript,
                message=f"已创建人物：{created.display_name}",
                intent=plan.intent,
                status="executed",
                capability=call,
                arguments=args,
                resolved={"person_id": created.id},
                result={"person": created.model_dump(mode="json")},
                source=request.source,
            )

        if name in {"person.select", "background.select"}:
            person, candidates = _person(domain, owner_id, request, args)
            if person is None:
                return _needs_input(
                    request,
                    plan,
                    "找到多个人物或找不到人物，请补充人物姓名。",
                    [item.model_dump(mode="json") for item in candidates],
                )
            resolved["person_id"] = person.id
            if name == "person.select":
                return DomainCommandResponse(
                    transcript=request.transcript,
                    message=f"已切换到人物：{person.display_name}",
                    intent=plan.intent,
                    status="executed",
                    capability=call,
                    arguments=args,
                    resolved=resolved,
                    source=request.source,
                )
            background, candidates = _background(
                domain, owner_id, request, args, person.id
            )
            if background is None:
                available_backgrounds = domain.list_backgrounds(owner_id)
                if not available_backgrounds:
                    return _needs_input(
                        request,
                        plan,
                        (
                            "当前还没有可用于创建文书的人物背景。"
                            "请说“创建背景”，我会转到背景资料并逐项收集；"
                            "背景完成后才能继续申请项目、故事和文书。"
                        ),
                    )
                return _needs_input(
                    request,
                    plan,
                    "请说明要使用这个人的哪份简历背景。",
                    [item.model_dump(mode="json") for item in candidates],
                )
            resolved["background_id"] = background.id
            return DomainCommandResponse(
                transcript=request.transcript,
                message=f"已切换到背景：{background.resume_name}",
                intent=plan.intent,
                status="executed",
                capability=call,
                arguments=args,
                resolved=resolved,
                result={"background": background.model_dump(mode="json")},
                source=request.source,
            )

        if name == "background.patch":
            person, candidates = _person(domain, owner_id, request, args)
            if person is None:
                return _needs_input(request, plan, "请指定要修改的人物。", candidates)
            background, candidates = _background(
                domain, owner_id, request, args, person.id
            )
            if background is None:
                return _needs_input(request, plan, "请指定要修改的简历背景。", candidates)
            resolved["person_id"] = person.id
            resolved["background_id"] = background.id
            if not request.confirmed:
                return _confirmation(request, plan, resolved)
            raw_operations = args.get("operations") or []
            if not isinstance(raw_operations, list) or not raw_operations:
                return _needs_input(request, plan, "请说明要修改哪个背景字段。")
            operations = [
                ProfilePatchOperation.model_validate(item)
                for item in raw_operations
            ]
            patched = domain.patch_background(
                owner_id,
                background.id,
                operations,
                base_version=(
                    int(args["base_version"])
                    if args.get("base_version") is not None
                    else None
                ),
            )
            return DomainCommandResponse(
                transcript=request.transcript,
                message="背景实例已保存，相关旧文书已标记为需要重新生成。",
                intent=plan.intent,
                status="executed",
                capability=call,
                arguments=args,
                resolved=resolved,
                result={"background": patched.model_dump(mode="json")},
                source=request.source,
            )

        if name == "application_project.create":
            background, candidates = _background(domain, owner_id, request, args)
            if background is None:
                return _needs_input(
                    request,
                    plan,
                    (
                        "创建申请项目前，请先选择人物背景。"
                        "选定后还需要一次说清学校名称和专业项目名称；"
                        "项目官网资料可选，可以留空。"
                    ),
                    candidates,
                )
            resolved.update(
                {
                    "person_id": background.person_id,
                    "background_id": background.id,
                }
            )
            school_name = str(args.get("school_name") or "").strip()
            program_name = str(args.get("program_name") or "").strip()
            if not school_name or not program_name:
                missing = []
                if not school_name:
                    missing.append("学校名称")
                if not program_name:
                    missing.append("专业项目名称")
                return _needs_input(
                    request,
                    plan,
                    (
                        f"背景已确定为“{background.resume_name}”。"
                        f"请补充{'和'.join(missing)}。"
                        "项目官网资料不是必填项。"
                    ),
                    resolved=resolved,
                )
            if not request.confirmed:
                return _confirmation(request, plan, resolved)
            application_project = domain.create_application_project(
                owner_id,
                background.id,
                school_name,
                program_name,
                str(args.get("program_details") or ""),
            )
            resolved["application_project_id"] = application_project.id
            return DomainCommandResponse(
                transcript=request.transcript,
                message=(
                    f"已记录申请项目：{application_project.school_name} · "
                    f"{application_project.program_name}。"
                    "下一步可以创建故事访谈，或直接创建文书。"
                ),
                intent=plan.intent,
                status="executed",
                capability=call,
                arguments=args,
                resolved=resolved,
                result={
                    "application_project": application_project.model_dump(
                        mode="json"
                    )
                },
                source=request.source,
            )

        if name == "application_project.select":
            background, candidates = _background(domain, owner_id, request, args)
            if background is None:
                return _needs_input(request, plan, "请指定申请项目所属背景。", candidates)
            application_project, candidates = _application_project(
                domain,
                owner_id,
                request,
                args,
                background.id,
            )
            if application_project is None:
                return _needs_input(request, plan, "请指定学校和专业项目。", candidates)
            return DomainCommandResponse(
                transcript=request.transcript,
                message=(
                    f"已切换到申请项目：{application_project.school_name} · "
                    f"{application_project.program_name}"
                ),
                intent=plan.intent,
                status="executed",
                capability=call,
                arguments=args,
                resolved={
                    "person_id": background.person_id,
                    "background_id": background.id,
                    "application_project_id": application_project.id,
                },
                result={
                    "application_project": application_project.model_dump(
                        mode="json"
                    )
                },
                source=request.source,
            )

        if name == "story.create":
            person, candidates = _person(domain, owner_id, request, args)
            if person is None:
                return _needs_input(
                    request,
                    plan,
                    (
                        "创建故事前，请先指定人物。"
                        "之后还需要选择申请项目和故事名称。"
                    ),
                    candidates,
                    resolved=resolved,
                )
            resolved["person_id"] = person.id
            background, candidates = _background(
                domain, owner_id, request, args, person.id
            )
            if background is None:
                return _needs_input(
                    request,
                    plan,
                    (
                        f"人物已确定为“{person.display_name}”。"
                        "请选择这份人物下的背景。"
                    ),
                    candidates,
                    resolved=resolved,
                )
            resolved.update(
                {
                    "person_id": person.id,
                    "background_id": background.id,
                }
            )
            application_project, candidates = _application_project(
                domain,
                owner_id,
                request,
                args,
                background.id,
            )
            if application_project is None:
                return _needs_input(
                    request,
                    plan,
                    (
                        f"背景已确定为“{background.resume_name}”。"
                        "故事必须绑定一个具体申请项目，请选择学校或专业项目；"
                        "随后还需要故事名称。"
                    ),
                    candidates,
                    resolved=resolved,
                )
            resolved["application_project_id"] = application_project.id
            title = str(args.get("title") or "").strip()
            if not title:
                return _needs_input(
                    request,
                    plan,
                    (
                        f"申请项目已确定为“{application_project.school_name} · "
                        f"{application_project.program_name}”。"
                        "最后请给这段故事起一个名称。"
                    ),
                    resolved=resolved,
                )
            if not request.confirmed:
                return _confirmation(request, plan, resolved)
            created = await domain_workflow.start_story(
                owner_id,
                domain_workflow.StoryInstanceStartRequest(
                    background_instance_id=background.id,
                    application_project_id=application_project.id,
                    title=title,
                    focus=str(args.get("focus") or ""),
                ),
                store=domain,
            )
            resolved["story_id"] = created.id
            return DomainCommandResponse(
                transcript=request.transcript,
                message=(
                    f"已开始故事：{created.title}。"
                    "现在可以回答本轮三个问题。"
                ),
                intent=plan.intent,
                status="executed",
                capability=call,
                arguments=args,
                resolved=resolved,
                result={"story": created.model_dump(mode="json")},
                source=request.source,
            )

        if name in {"story.select", "story.reply", "story.patch"}:
            person, candidates = _person(domain, owner_id, request, args)
            if person is None:
                person = None
            else:
                resolved["person_id"] = person.id
            background, candidates = _background(
                domain, owner_id, request, args, person.id if person else None
            )
            if background is None:
                return _needs_input(
                    request,
                    plan,
                    "请先指定故事所属的背景。",
                    candidates,
                    resolved=resolved,
                )
            resolved["background_id"] = background.id
            application_project, candidates = _application_project(
                domain,
                owner_id,
                request,
                args,
                background.id,
            )
            story, candidates = _story(
                domain,
                owner_id,
                request,
                args,
                background.id,
                application_project.id if application_project else None,
            )
            if story is None:
                return _needs_input(request, plan, "请指定要使用的故事。", candidates)
            resolved.update(
                {
                    "person_id": person.id if person else background.person_id,
                    "background_id": background.id,
                    "application_project_id": (
                        story.application_project_id
                        or (
                            application_project.id
                            if application_project
                            else None
                        )
                    ),
                    "story_id": story.id,
                }
            )
            if name == "story.select":
                return DomainCommandResponse(
                    transcript=request.transcript,
                    message=f"已切换到故事：{story.title}",
                    intent=plan.intent,
                    status="executed",
                    capability=call,
                    arguments=args,
                    resolved=resolved,
                    result={"story": story.model_dump(mode="json")},
                    source=request.source,
                )
            if name == "story.patch":
                if not request.confirmed:
                    return _confirmation(request, plan, resolved)
                if not isinstance(args.get("cards"), dict):
                    return _needs_input(request, plan, "请提供要保存的故事素材卡。")
                patched = domain.patch_story_cards(
                    owner_id,
                    story.id,
                    StoryCards.model_validate(args.get("cards") or {}),
                    base_version=(
                        int(args["base_version"])
                        if args.get("base_version") is not None
                        else None
                    ),
                )
                return DomainCommandResponse(
                    transcript=request.transcript,
                    message="故事素材已保存，引用它的文书项目已标记为需要重生成。",
                    intent=plan.intent,
                    status="executed",
                    capability=call,
                    arguments=args,
                    resolved=resolved,
                    result={"story": patched.model_dump(mode="json")},
                    source=request.source,
                )
            answer = str(args.get("answer") or "").strip()
            if not answer:
                return _needs_input(
                    request,
                    plan,
                    "请先提供这轮故事回答。",
                    resolved=resolved,
                )
            if not request.confirmed:
                return _confirmation(request, plan, resolved)
            updated = await domain_workflow.continue_story(
                owner_id,
                story.id,
                domain_workflow.StoryInstanceReplyRequest(user_message=answer),
                store=domain,
            )
            return DomainCommandResponse(
                transcript=request.transcript,
                message=(
                    f"已保存故事回答，当前第 {updated.round_no}/3 轮。"
                    + (
                        "故事已完成，可以创建文书。"
                        if updated.status == "ready"
                        else "请继续回答下一轮问题。"
                    )
                ),
                intent=plan.intent,
                status="executed",
                capability=call,
                arguments=args,
                resolved=resolved,
                result={"story": updated.model_dump(mode="json")},
                source=request.source,
            )

        if name == "essay_branch.create":
            background, candidates = _background(
                domain,
                owner_id,
                request,
                args,
            )
            if background is None:
                return _needs_input(
                    request,
                    plan,
                    (
                        "创建新文书前，请先选择人物背景。"
                        "背景确定后，才能选择该背景下的申请项目。"
                        "之后还需要已完成故事、PS/ML 类型和文书题目。"
                    ),
                    candidates,
                    resolved=resolved,
                )
            resolved.update(
                {
                    "person_id": background.person_id,
                    "background_id": background.id,
                }
            )
            application_project, candidates = _application_project(
                domain,
                owner_id,
                request,
                args,
                background.id,
            )
            if application_project is None:
                return _needs_input(
                    request,
                    plan,
                    (
                        f"背景已确定为“{background.resume_name}”。"
                        "请选择该背景下用于这篇新文书的申请项目。"
                        "之后还需要已完成故事、PS/ML 类型和文书题目；"
                        "项目官网资料可选，可以留空。"
                    ),
                    candidates,
                    resolved=resolved,
                )
            resolved["application_project_id"] = application_project.id
            story_titles = args.get("story_titles") or []
            story_ids: List[str] = []
            for title in story_titles:
                matches = domain.resolve_stories(
                    owner_id,
                    str(title),
                    background_id=application_project.background_instance_id,
                    application_project_id=application_project.id,
                )
                if len(matches) != 1:
                    return _needs_input(
                        request,
                        plan,
                        f"故事“{title}”无法唯一匹配项目链路。",
                        [item.model_dump(mode="json") for item in matches],
                        resolved=resolved,
                    )
                if matches[0].status != "ready":
                    return _needs_input(
                        request,
                        plan,
                        (
                            f"故事“{matches[0].title}”还在第 "
                            f"{matches[0].round_no}/3 轮访谈，不能用于文书。"
                            "请先完成这个故事，或者选择另一个已完成故事。"
                        ),
                        domain.list_stories(
                            owner_id,
                            application_project.background_instance_id,
                            application_project.id,
                        ),
                        resolved=resolved,
                    )
                story_ids.append(matches[0].id)
            if not story_ids:
                return _needs_input(
                    request,
                    plan,
                    (
                        f"申请项目已确定为“{application_project.school_name} · "
                        f"{application_project.program_name}”。"
                        "请选择一个属于该项目的已完成故事。"
                        "选定后还需要 PS/ML 类型和文书题目。"
                    ),
                    domain.list_stories(
                        owner_id,
                        application_project.background_instance_id,
                        application_project.id,
                    ),
                    resolved=resolved,
                )
            resolved["story_ids"] = story_ids
            if len(story_ids) == 1:
                resolved["story_id"] = story_ids[0]
            essay_type = str(args.get("essay_type") or "").strip()
            if essay_type not in {"Personal Statement", "Motivation Letter"}:
                return _needs_input(
                    request,
                    plan,
                    (
                        "故事前置条件已满足。"
                        "请选择这篇新文书是 Personal Statement（PS）"
                        "还是 Motivation Letter（ML）。"
                        "之后只需要再提供文书题目。"
                    ),
                    resolved=resolved,
                )
            prompt_text = str(args.get("prompt_text") or "").strip()
            if len(prompt_text) < 10:
                return _needs_input(
                    request,
                    plan,
                    (
                        f"已选择 {essay_type}。"
                        "请提供至少 10 个字符的文书题目。"
                        "字数默认 800，项目官网资料可选，均无需额外补充。"
                    ),
                    resolved=resolved,
                )
            if not request.confirmed:
                return _confirmation(request, plan, resolved)
            branch = await domain_workflow.create_application_essay_branch(
                owner_id,
                EssayBranchCreateRequest(
                    application_project_id=application_project.id,
                    essay_type=essay_type,
                    word_limit=int(args.get("word_limit") or 800),
                    prompt_text=prompt_text,
                    story_instance_ids=story_ids,
                    tone=str(args.get("tone") or "balanced"),
                ),
                store=domain,
            )
            resolved["project_id"] = branch.id
            generated = bool(args.get("generate_after_create"))
            if generated:
                branch = await domain_workflow.analyze_project(
                    owner_id,
                    branch.id,
                    store=domain,
                )
                branch = await domain_workflow.generate_outline(
                    owner_id,
                    branch.id,
                    store=domain,
                )
                branch = await domain_workflow.generate_draft(
                    owner_id,
                    branch.id,
                    EssayProjectDraftRequest(),
                    store=domain,
                )
            return DomainCommandResponse(
                transcript=request.transcript,
                message=(
                    (
                        f"已创建 {essay_type} 新文书，并生成英文草稿。"
                        "可以继续审核或修改。"
                    )
                    if generated
                    else (
                        f"已创建 {essay_type} 新文书。"
                        "下一步可以生成分析、中文大纲和英文草稿。"
                    )
                ),
                intent=plan.intent,
                status="executed",
                capability=call,
                arguments=args,
                resolved=resolved,
                result={"project": branch.model_dump(mode="json")},
                source=request.source,
            )

        if name == "project.create":
            background, candidates = _background(
                domain, owner_id, request, args
            )
            if background is None:
                return _needs_input(request, plan, "请先指定文书项目使用的背景。", candidates)
            story_titles = args.get("story_titles") or []
            selected_stories = []
            for title in story_titles:
                candidates = domain.resolve_stories(
                    owner_id,
                    str(title),
                    background_id=background.id,
                )
                if len(candidates) != 1:
                    return _needs_input(
                        request,
                        plan,
                        f"故事“{title}”无法唯一匹配，请重新指定。",
                        [item.model_dump(mode="json") for item in candidates],
                    )
                selected_stories.append(candidates[0])
            required = (
                "school_name",
                "program_name",
                "prompt_text",
            )
            if any(not str(args.get(key) or "").strip() for key in required):
                return _needs_input(
                    request,
                    plan,
                    "请补充学校、项目和文书题目。",
                )
            resolved.update(
                {
                    "person_id": background.person_id,
                    "background_id": background.id,
                    "story_ids": [item.id for item in selected_stories],
                }
            )
            if not request.confirmed:
                return _confirmation(request, plan, resolved)
            project = domain.create_project(
                owner_id,
                background.id,
                [item.id for item in selected_stories],
                ProgramContext(
                    school_name=str(args["school_name"]),
                    program_name=str(args["program_name"]),
                    essay_type=str(
                        args.get("essay_type") or "Personal Statement"
                    ),
                    word_limit=int(args.get("word_limit") or 800),
                    prompt_text=str(args["prompt_text"]),
                    program_details=str(args.get("program_details") or ""),
                ),
            )
            resolved["project_id"] = project.id
            return DomainCommandResponse(
                transcript=request.transcript,
                message="文书项目已创建，可以选择项目分析或批量生成。",
                intent=plan.intent,
                status="executed",
                capability=call,
                arguments=args,
                resolved=resolved,
                result={"project": project.model_dump(mode="json")},
                source=request.source,
            )

        if name.startswith("project."):
            project, candidates = _project(domain, owner_id, request, args)
            if project is None:
                return _needs_input(request, plan, "请指定要操作的文书项目。", candidates)
            resolved["project_id"] = project.id
            if not request.confirmed:
                return _confirmation(request, plan, resolved)
            if name == "project.patch":
                story_ids = None
                if args.get("story_titles") is not None:
                    story_ids = []
                    for title in args.get("story_titles") or []:
                        matches = domain.resolve_stories(
                            owner_id,
                            str(title),
                            background_id=project.background_instance_id,
                        )
                        if len(matches) != 1:
                            return _needs_input(
                                request,
                                plan,
                                f"故事“{title}”无法唯一匹配。",
                                [item.model_dump(mode="json") for item in matches],
                            )
                        story_ids.append(matches[0].id)
                updated = domain.patch_project(
                    owner_id,
                    project.id,
                    changes=dict(args.get("changes") or {}),
                    story_instance_ids=story_ids,
                )
            elif name == "project.analyze":
                updated = await domain_workflow.analyze_project(
                    owner_id, project.id, store=domain
                )
            elif name == "project.outline":
                updated = await domain_workflow.generate_outline(
                    owner_id, project.id, store=domain
                )
            elif name == "project.draft":
                updated = await domain_workflow.generate_draft(
                    owner_id,
                    project.id,
                    EssayProjectDraftRequest(
                        revision_instruction=str(
                            args.get("revision_instruction") or ""
                        )
                    ),
                    store=domain,
                )
            elif name == "project.review":
                updated = await domain_workflow.review_project(
                    owner_id, project.id, store=domain
                )
            else:
                return _needs_input(request, plan, "不支持这个文书项目操作。")
            next_messages = {
                "project.analyze": (
                    "项目分析已完成。下一步可以生成中文大纲。"
                ),
                "project.outline": (
                    "中文大纲已生成。下一步可以生成英文草稿。"
                ),
                "project.draft": (
                    "英文草稿已生成。可以审核草稿，或继续说修改意见重写。"
                ),
                "project.review": (
                    "草稿审核已完成。可以按审核意见继续修改。"
                ),
                "project.patch": (
                    "文书项目信息已更新。请确认是否需要重新分析或生成。"
                ),
            }
            return DomainCommandResponse(
                transcript=request.transcript,
                message=next_messages.get(name, "文书项目操作已完成。"),
                intent=plan.intent,
                status="executed",
                capability=call,
                arguments=args,
                resolved=resolved,
                result={"project": updated.model_dump(mode="json")},
                source=request.source,
            )

        if name == "batch.create":
            background, candidates = _background(domain, owner_id, request, args)
            if background is None:
                return _needs_input(request, plan, "请先指定批量任务使用的背景。", candidates)
            resolved.update(
                {
                    "person_id": background.person_id,
                    "background_id": background.id,
                }
            )
            if not request.confirmed:
                return _confirmation(request, plan, resolved)
            directions = args.get("directions") or []
            if not directions:
                return _needs_input(request, plan, "请至少提供一个学校和项目方向。")
            prepared_directions = []
            for raw_direction in directions:
                if not isinstance(raw_direction, dict):
                    return _needs_input(request, plan, "批量方向格式无效。")
                direction = dict(raw_direction)
                story_titles = direction.pop("story_titles", []) or []
                story_ids = list(direction.get("story_instance_ids") or [])
                for title in story_titles:
                    matches = domain.resolve_stories(
                        owner_id,
                        str(title),
                        background_id=background.id,
                    )
                    if len(matches) != 1:
                        return _needs_input(
                            request,
                            plan,
                            f"故事“{title}”无法唯一匹配。",
                            [item.model_dump(mode="json") for item in matches],
                        )
                    story_ids.append(matches[0].id)
                direction["story_instance_ids"] = list(dict.fromkeys(story_ids))
                prepared_directions.append(direction)
            request_id = str(args.get("request_id") or uuid.uuid4())
            payload = {
                "background_instance_id": background.id,
                "request_id": request_id,
                "tone": str(args.get("tone") or "balanced"),
                "directions": prepared_directions,
            }
            created = batch.create_batch(
                owner_id,
                BatchCreateRequest.model_validate(payload),
            )
            resolved["batch_id"] = created.id
            return DomainCommandResponse(
                transcript=request.transcript,
                message=f"已创建批量任务，共 {len(created.items)} 篇文书。",
                intent=plan.intent,
                status="executed",
                capability=call,
                arguments=args,
                resolved=resolved,
                result={"batch": created.model_dump(mode="json")},
                source=request.source,
            )

        if name in {"workflow.pause", "workflow.resume"}:
            return DomainCommandResponse(
                transcript=request.transcript,
                message=(
                    "当前装配状态已保存在服务端，可以稍后在装配工作台继续。"
                    if name == "workflow.pause"
                    else "当前实例已恢复，可以继续下一步。"
                ),
                intent=plan.intent,
                status="executed",
                capability=call,
                arguments=args,
                resolved={
                    key: value
                    for key, value in {
                        "person_id": request.active_person_id,
                        "background_id": request.active_background_id,
                        "application_project_id": (
                            request.active_application_project_id
                        ),
                        "story_id": request.active_story_id,
                        "project_id": request.active_project_id,
                    }.items()
                    if value
                },
                source=request.source,
            )

        return _needs_input(request, plan, "当前装配工作台不支持这个操作。")
    except (AppError, ValueError) as exc:
        return DomainCommandResponse(
            transcript=request.transcript,
            message=getattr(exc, "message", str(exc)),
            intent=plan.intent,
            status="needs_input",
            capability=call,
            arguments=args,
            resolved=resolved,
            source=request.source,
        )
