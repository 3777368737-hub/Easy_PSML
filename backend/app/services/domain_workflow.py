from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.errors import ConflictError, ModelOutputError
from app.schemas import (
    DraftReview,
    EssayBranchCreateRequest,
    EssayOutline,
    EssayProjectCreateRequest,
    EssayProjectDraftRequest,
    EssayProjectResponse,
    ProgramAnalysis,
    ProgramContext,
    StoryCards,
    StoryCardsUpdate,
    StoryInstanceReplyRequest,
    StoryInstanceResponse,
    StoryInstanceStartRequest,
    StoryMessage,
    StoryTurnOutput,
)
from app.services import workflow
from app.services.domain_store import DomainStore, get_domain_store


def _json(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif isinstance(value, list):
        value = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            for item in value
        ]
    return json.dumps(value, ensure_ascii=False, indent=2)


def _story_context(
    profile: Any,
    cards: StoryCards,
    focus: str,
) -> Dict[str, str]:
    experiences = [
        *profile.research_experiences,
        *profile.internships,
        *profile.projects,
    ]
    key_experience = next(
        (
            item.title or item.summary or item.impact
            for item in experiences
            if item.title or item.summary or item.impact
        ),
        "your most representative experience",
    )
    return {
        "target_field": profile.basic_profile.target_field or focus or "target field",
        "degree": profile.basic_profile.target_degree or "Master's",
        "major": profile.basic_profile.major or "current major",
        "key_experience": key_experience,
        "program_focus": focus or "the selected application direction",
        "gap": "the capability you want to strengthen",
        "strength": (
            profile.top_strengths[0]
            if profile.top_strengths
            else (cards.strengths[0] if cards.strengths else "your strongest evidence")
        ),
        "school": focus or "the target program",
        "program": focus or "the target program",
    }


def _format_message(intro: str, questions: List[str]) -> str:
    return workflow._format_story_message(intro, questions)


def _selected_story_payload(
    store: DomainStore,
    owner_id: str,
    story_ids: List[str],
) -> List[Dict[str, Any]]:
    stories: List[Dict[str, Any]] = []
    for story_id in story_ids:
        story = store.get_story(owner_id, story_id)
        stories.append(
            {
                "id": story.id,
                "title": story.title,
                "focus": story.focus,
                "cards": story.cards.model_dump(mode="json"),
            }
        )
    return stories


async def start_story(
    owner_id: str,
    request: StoryInstanceStartRequest,
    *,
    store: Optional[DomainStore] = None,
) -> StoryInstanceResponse:
    domain = store or get_domain_store()
    background = domain.get_background(owner_id, request.background_instance_id)
    application_project = None
    if request.application_project_id:
        application_project = domain.get_application_project(
            owner_id,
            request.application_project_id,
        )
        if application_project.background_instance_id != background.id:
            raise ConflictError(
                "Application project does not belong to the selected background"
            )
    context = _story_context(background.profile, StoryCards(), request.focus)
    messages = [
        {"role": "system", "content": workflow.STORY_START_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Start the first story-mining round for this saved background.\n\n"
                f"Story title: {request.title}\n"
                f"Story focus: {request.focus or '(general experiences)'}\n\n"
                f"Background profile:\n{_json(background.profile)}"
            ),
        },
    ]
    result = await workflow.client.chat_json(
        messages,
        StoryTurnOutput,
        max_tokens=3000,
    )
    questions = workflow._prepare_questions(
        result.questions,
        previous_questions=[],
        round_no=1,
        context=context,
    )
    first_message = StoryMessage(
        role="assistant",
        content=_format_message(result.assistant_message, questions),
    )
    return domain.create_story(
        owner_id,
        background.id,
        request.title,
        application_project_id=(
            application_project.id if application_project else None
        ),
        focus=request.focus,
        messages=[first_message],
        cards=result.cards,
        round_no=1,
        status="interviewing",
    )


async def continue_story(
    owner_id: str,
    story_id: str,
    request: StoryInstanceReplyRequest,
    *,
    store: Optional[DomainStore] = None,
) -> StoryInstanceResponse:
    domain = store or get_domain_store()
    story = domain.get_story(owner_id, story_id)
    if story.status == "ready":
        raise ConflictError("The story interview is already complete")
    background = domain.get_background(owner_id, story.background_instance_id)
    previous_questions = workflow._extract_asked_questions(story.messages)
    user_turn = StoryMessage(role="user", content=request.user_message)
    conversation = "\n".join(
        f"{message.role.upper()}: {message.content}" for message in story.messages
    )
    context = _story_context(background.profile, story.cards, story.focus)

    if story.round_no >= 3:
        result = await workflow.client.chat_json(
            [
                {"role": "system", "content": workflow.STORY_FINAL_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Consolidate the interview facts into the final story cards.\n\n"
                        f"Story title: {story.title}\n"
                        f"Story focus: {story.focus or '(general experiences)'}\n\n"
                        f"Current cards:\n{_json(story.cards)}\n\n"
                        f"Conversation:\n{conversation}\n\n"
                        f"Latest applicant answer:\n{request.user_message}"
                    ),
                },
            ],
            StoryCardsUpdate,
            max_tokens=2500,
        )
        closing = StoryMessage(
            role="assistant",
            content=(
                "三轮故事挖掘已完成，核心素材已经整理好。"
                "\n接下来可以在文书工作台中选择这个故事生成文书。"
            ),
        )
        return domain.save_story_state(
            owner_id,
            story.id,
            messages=[*story.messages, user_turn, closing],
            cards=result.cards,
            round_no=story.round_no,
            status="ready",
        )

    previous_text = "\n".join(f"- {question}" for question in previous_questions)
    result = await workflow.client.chat_json(
        [
            {"role": "system", "content": workflow.STORY_REPLY_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Continue the interview for one more round.\n\n"
                    f"Story title: {story.title}\n"
                    f"Story focus: {story.focus or '(general experiences)'}\n"
                    f"Previously asked questions:\n{previous_text or '(none)'}\n\n"
                    f"Current cards:\n{_json(story.cards)}\n\n"
                    f"Background profile:\n{_json(background.profile)}\n\n"
                    f"Conversation:\n{conversation}\n\n"
                    f"Latest applicant answer:\n{request.user_message}"
                ),
            },
        ],
        StoryTurnOutput,
        max_tokens=3000,
    )
    questions = workflow._prepare_questions(
        result.questions,
        previous_questions=previous_questions,
        round_no=story.round_no + 1,
        context=context,
        last_user_message=request.user_message,
    )
    assistant_turn = StoryMessage(
        role="assistant",
        content=_format_message(result.assistant_message, questions),
    )
    return domain.save_story_state(
        owner_id,
        story.id,
        messages=[*story.messages, user_turn, assistant_turn],
        cards=result.cards,
        round_no=story.round_no + 1,
        status="interviewing",
    )


async def analyze_project(
    owner_id: str,
    project_id: str,
    *,
    store: Optional[DomainStore] = None,
) -> EssayProjectResponse:
    domain = store or get_domain_store()
    project = domain.get_project(owner_id, project_id)
    background = domain.get_background(owner_id, project.background_instance_id)
    stories = _selected_story_payload(
        domain,
        owner_id,
        project.story_instance_ids,
    )
    messages = [
        {"role": "system", "content": workflow.PROGRAM_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Create a concise essay strategy for this background and target.\n\n"
                f"Applicant profile:\n{_json(background.profile)}\n\n"
                f"Selected stories:\n{_json(stories)}\n\n"
                f"Program context:\n{_json(project.program)}"
            ),
        },
    ]
    analysis = await workflow.client.chat_json(
        messages,
        ProgramAnalysis,
        max_tokens=5000,
    )
    return domain.save_project(
        owner_id,
        project.id,
        analysis=analysis,
        outline=project.outline,
        draft=project.draft,
        review=project.review,
        status="analyzed",
        current_step="analysis",
    )


async def generate_outline(
    owner_id: str,
    project_id: str,
    *,
    store: Optional[DomainStore] = None,
) -> EssayProjectResponse:
    domain = store or get_domain_store()
    project = domain.get_project(owner_id, project_id)
    if project.analysis is None:
        project = await analyze_project(owner_id, project_id, store=domain)
    background = domain.get_background(owner_id, project.background_instance_id)
    stories = _selected_story_payload(
        domain,
        owner_id,
        project.story_instance_ids,
    )
    messages = [
        {"role": "system", "content": workflow.OUTLINE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Create the essay outline in Simplified Chinese.\n\n"
                f"Program context:\n{_json(project.program)}\n\n"
                f"Profile:\n{_json(background.profile)}\n\n"
                f"Program analysis:\n{_json(project.analysis)}\n\n"
                f"Selected stories:\n{_json(stories)}"
            ),
        },
    ]
    outline = await workflow.client.chat_json(
        messages,
        EssayOutline,
        max_tokens=4000,
    )
    version = domain.add_project_artifact(
        owner_id,
        project.id,
        "outline",
        outline=outline,
        metadata={
            "word_limit": project.program.word_limit,
            "story_instance_ids": project.story_instance_ids,
        },
    )
    project = domain.save_project(
        owner_id,
        project.id,
        analysis=project.analysis,
        outline=outline,
        draft=project.draft,
        review=project.review,
        status="outlined",
        current_step="outline",
    )
    project.versions.insert(
        0,
        version,
    )
    return project


async def generate_draft(
    owner_id: str,
    project_id: str,
    request: EssayProjectDraftRequest,
    *,
    store: Optional[DomainStore] = None,
) -> EssayProjectResponse:
    domain = store or get_domain_store()
    project = domain.get_project(owner_id, project_id)
    if project.outline is None:
        project = await generate_outline(owner_id, project_id, store=domain)
    background = domain.get_background(owner_id, project.background_instance_id)
    stories = _selected_story_payload(
        domain,
        owner_id,
        project.story_instance_ids,
    )
    target_length = request.target_length or project.program.word_limit
    revision = ""
    if request.revision_instruction:
        if not project.draft:
            raise ConflictError("Generate an initial draft before requesting a revision")
        revision = (
            "\nRevise the current draft according to the instruction below. "
            "Preserve supported facts and the requested essay prompt.\n"
            f"Current draft:\n{project.draft}\n\n"
            f"Revision instruction:\n{request.revision_instruction}"
        )
    messages = [
        {"role": "system", "content": workflow.DRAFT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Write a {request.tone} response of approximately {target_length} words.\n\n"
                f"Program context:\n{_json(project.program)}\n\n"
                f"Profile:\n{_json(background.profile)}\n\n"
                f"Program analysis:\n{_json(project.analysis)}\n\n"
                f"Selected stories:\n{_json(stories)}\n\n"
                f"Outline:\n{_json(project.outline)}\n"
                f"{revision}"
            ),
        },
    ]
    max_tokens = min(max(target_length * 3 + 500, 1800), 6000)
    draft = await workflow.client.chat_text(messages, max_tokens=max_tokens)
    if len(draft.split()) < max(80, int(target_length * 0.35)):
        raise ModelOutputError(
            "The generated draft was materially shorter than requested. Please retry."
        )
    labels = [paragraph.heading for paragraph in project.outline.paragraphs]
    domain.add_project_artifact(
        owner_id,
        project.id,
        "draft",
        draft=draft,
        metadata={
            "tone": request.tone,
            "target_length": target_length,
            "revision_instruction": request.revision_instruction,
            "paragraph_labels": labels,
            "story_instance_ids": project.story_instance_ids,
        },
    )
    return domain.save_project(
        owner_id,
        project.id,
        analysis=project.analysis,
        outline=project.outline,
        draft=draft,
        review=project.review,
        status="drafted",
        current_step="draft",
    )


async def review_project(
    owner_id: str,
    project_id: str,
    *,
    store: Optional[DomainStore] = None,
) -> EssayProjectResponse:
    domain = store or get_domain_store()
    project = domain.get_project(owner_id, project_id)
    if not project.draft:
        raise ConflictError("Generate a draft before running a review")
    background = domain.get_background(owner_id, project.background_instance_id)
    stories = _selected_story_payload(
        domain,
        owner_id,
        project.story_instance_ids,
    )
    messages = [
        {"role": "system", "content": workflow.REVIEW_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Review the essay draft.\n\n"
                f"Program context:\n{_json(project.program)}\n\n"
                f"Profile:\n{_json(background.profile)}\n\n"
                f"Program analysis:\n{_json(project.analysis)}\n\n"
                f"Selected stories:\n{_json(stories)}\n\n"
                f"Draft:\n{project.draft}"
            ),
        },
    ]
    review = await workflow.client.chat_json(
        messages,
        DraftReview,
        max_tokens=3000,
    )
    return domain.save_project(
        owner_id,
        project.id,
        analysis=project.analysis,
        outline=project.outline,
        draft=project.draft,
        review=review,
        status="reviewed",
        current_step="review",
    )


async def build_project(
    owner_id: str,
    request: EssayProjectCreateRequest,
    *,
    store: Optional[DomainStore] = None,
) -> EssayProjectResponse:
    domain = store or get_domain_store()
    project = domain.create_project(
        owner_id,
        request.background_instance_id,
        request.story_instance_ids,
        request.to_program_context(),
    )
    project = await analyze_project(owner_id, project.id, store=domain)
    project = await generate_outline(owner_id, project.id, store=domain)
    return await generate_draft(
        owner_id,
        project.id,
        EssayProjectDraftRequest(),
        store=domain,
    )


async def create_application_essay_branch(
    owner_id: str,
    request: EssayBranchCreateRequest,
    *,
    store: Optional[DomainStore] = None,
) -> EssayProjectResponse:
    domain = store or get_domain_store()
    application_project = domain.get_application_project(
        owner_id,
        request.application_project_id,
    )
    existing = [
        project
        for project in domain.list_projects(
            owner_id,
            background_id=application_project.background_instance_id,
        )
        if project.application_project_id == application_project.id
        and project.program.essay_type == request.essay_type
        and project.status != "archived"
    ]
    if existing:
        raise ConflictError(
            f"This application project already has a {request.essay_type} branch"
        )
    program = ProgramContext(
        school_name=application_project.school_name,
        program_name=application_project.program_name,
        essay_type=request.essay_type,
        word_limit=request.word_limit,
        prompt_text=request.prompt_text,
        program_details=application_project.program_details,
    )
    return domain.create_project(
        owner_id,
        application_project.background_instance_id,
        request.story_instance_ids,
        program,
        application_project_id=application_project.id,
    )
