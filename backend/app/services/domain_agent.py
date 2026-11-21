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
    return {
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
            }
            for background in snapshot.backgrounds
        ],
        "application_projects": [
            {
                "id": project.id,
                "background_id": project.background_instance_id,
                "school_name": project.school_name,
                "program_name": project.program_name,
                "story_count": project.story_count,
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
                "story_ids": project.story_instance_ids,
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
    return [
        {"role": "system", "content": DOMAIN_AGENT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Resolve one command against the GradPilot instance workspace.\n\n"
                f"Transcript:\n{request.transcript}\n\n"
                f"Recent history:\n{_json(request.history)}\n\n"
                f"Active IDs:\n{_json({
                    'person_id': request.active_person_id,
                    'background_id': request.active_background_id,
                    'application_project_id': request.active_application_project_id,
                    'story_id': request.active_story_id,
                    'project_id': request.active_project_id,
                })}\n\n"
                f"Active instance payload:\n"
                f"{_json(_active_payload(domain, owner_id, request))}\n\n"
                f"Workspace catalog:\n{_json(_catalog(domain, owner_id))}"
            ),
        },
    ]


async def _plan(
    request: DomainAgentRequest,
    domain: DomainStore,
    owner_id: str,
) -> AgentPlan:
    try:
        return await domain_qwen.chat_json(
            _messages(request, domain, owner_id),
            AgentPlan,
            max_tokens=1800,
        )
    except UpstreamServiceError:
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
    if len(candidates) == 1:
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
    candidates = domain.resolve_backgrounds(
        owner_id,
        query,
        person_id=person_id,
    ) if query else domain.list_backgrounds(owner_id, person_id)
    if len(candidates) == 1:
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
    candidates = domain.resolve_application_projects(
        owner_id,
        query,
        background_id=background_id,
    )
    if len(candidates) == 1:
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
    candidates = domain.resolve_stories(
        owner_id,
        query,
        background_id=background_id,
        application_project_id=application_project_id,
    )
    if len(candidates) == 1:
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
    candidates = domain.resolve_projects(
        owner_id,
        query,
        background_id=background_id,
    )
    if len(candidates) == 1:
        return candidates[0], candidates
    return None, candidates


def _needs_input(
    request: DomainAgentRequest,
    plan: AgentPlan,
    message: str,
    candidates: Any = None,
) -> DomainCommandResponse:
    return DomainCommandResponse(
        transcript=request.transcript,
        message=message,
        intent=plan.intent,
        status="needs_input",
        capability=plan.capability,
        arguments=plan.capability.arguments if plan.capability else {},
        resolved={"candidates": candidates} if candidates is not None else {},
        source=request.source,
    )


def _confirmation(
    request: DomainAgentRequest,
    plan: AgentPlan,
    resolved: Dict[str, Any],
) -> DomainCommandResponse:
    capability = plan.capability
    return DomainCommandResponse(
        transcript=request.transcript,
        message=plan.message or "请确认执行这个操作。",
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
                return _needs_input(request, plan, "请指定申请项目使用的背景。", candidates)
            school_name = str(args.get("school_name") or "").strip()
            program_name = str(args.get("program_name") or "").strip()
            if not school_name or not program_name:
                return _needs_input(request, plan, "请补充学校和专业项目名称。")
            resolved.update(
                {
                    "person_id": background.person_id,
                    "background_id": background.id,
                }
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
                    f"{application_project.program_name}"
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
                return _needs_input(request, plan, "请先指定故事绑定的人物。", candidates)
            background, candidates = _background(
                domain, owner_id, request, args, person.id
            )
            if background is None:
                return _needs_input(request, plan, "请先指定故事绑定的背景。", candidates)
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
                    "故事必须绑定一个具体申请项目，请指定学校或专业项目。",
                    candidates,
                )
            title = str(args.get("title") or "").strip()
            if not title:
                return _needs_input(request, plan, "请给这段故事起一个名称。")
            resolved.update(
                {
                    "person_id": person.id,
                    "background_id": background.id,
                    "application_project_id": application_project.id,
                }
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
                message=f"已开始故事：{created.title}",
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
            background, candidates = _background(
                domain, owner_id, request, args, person.id if person else None
            )
            if background is None:
                return _needs_input(request, plan, "请先指定故事所属的背景。", candidates)
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
                return _needs_input(request, plan, "请先提供这轮故事回答。")
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
                message=f"已保存故事回答，当前第 {updated.round_no}/3 轮。",
                intent=plan.intent,
                status="executed",
                capability=call,
                arguments=args,
                resolved=resolved,
                result={"story": updated.model_dump(mode="json")},
                source=request.source,
            )

        if name == "essay_branch.create":
            application_project, candidates = _application_project(
                domain,
                owner_id,
                request,
                args,
            )
            if application_project is None:
                return _needs_input(request, plan, "请指定学校和专业项目。", candidates)
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
                    )
                story_ids.append(matches[0].id)
            if not story_ids:
                return _needs_input(
                    request,
                    plan,
                    "请至少选择一个属于该申请项目的已完成故事。",
                )
            essay_type = str(args.get("essay_type") or "").strip()
            if essay_type not in {"Personal Statement", "Motivation Letter"}:
                return _needs_input(request, plan, "请选择 PS 或 ML。")
            prompt_text = str(args.get("prompt_text") or "").strip()
            if len(prompt_text) < 10:
                return _needs_input(request, plan, "请补充至少 10 个字符的文书题目。")
            resolved.update(
                {
                    "person_id": application_project.person_id,
                    "background_id": application_project.background_instance_id,
                    "application_project_id": application_project.id,
                }
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
            return DomainCommandResponse(
                transcript=request.transcript,
                message=f"已创建 {essay_type} 文书分支。",
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
            return DomainCommandResponse(
                transcript=request.transcript,
                message=f"{name.split('.')[-1]} 已完成。",
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
