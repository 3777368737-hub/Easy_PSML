from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from app.errors import ConflictError, ModelOutputError, NotFoundError
from app.schemas import (
    BasicProfile,
    DraftRequest,
    DraftResponse,
    DraftReview,
    EssayOutline,
    OutlineResponse,
    ProgramAnalysis,
    ProgramAnalyzeRequest,
    ProgramAnalyzeResponse,
    ReviewResponse,
    StoryCards,
    StoryCardsUpdate,
    StoryMessage,
    StoryResponse,
    StoryTurnOutput,
    ProfileData,
)
from app.services.deepseek_client import DeepSeekClient
from app.services.prompts import (
    DRAFT_SYSTEM_PROMPT,
    OUTLINE_SYSTEM_PROMPT,
    PROFILE_SYSTEM_PROMPT,
    PROGRAM_SYSTEM_PROMPT,
    REVIEW_SYSTEM_PROMPT,
    STORY_FINAL_SYSTEM_PROMPT,
    STORY_REPLY_SYSTEM_PROMPT,
    STORY_START_SYSTEM_PROMPT,
)
from app.services.store import (
    AnalysisRecord,
    ProfileRecord,
    SessionRecord,
    get_store,
)


client = DeepSeekClient()
CJK_PATTERN = re.compile(r"[\u3400-\u9fff]")


def _pretty_json(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, indent=2)


def _normalize_question(question: str) -> str:
    normalized = question.strip().lower().replace("？", "?")
    normalized = re.sub(r"\s+", "", normalized)
    normalized = re.sub(r"^[1-9][\.\)\u3001\uff09]", "", normalized)
    return re.sub(r"[\?\!\,\，\。\：\:；;、\-\_\(\)\[\]【】]", "", normalized)


def _question_similarity(left: str, right: str) -> float:
    normalized_left = _normalize_question(left)
    normalized_right = _normalize_question(right)
    if not normalized_left or not normalized_right:
        return 0.0
    return SequenceMatcher(None, normalized_left, normalized_right).ratio()


def _extract_asked_questions(messages: List[StoryMessage]) -> List[str]:
    questions: List[str] = []
    for message in messages:
        if message.role != "assistant":
            continue
        for line in message.content.splitlines():
            match = re.match(r"^\d+[\.\)\u3001\uff09]\s*(.+)$", line.strip())
            if match:
                questions.append(match.group(1).strip())
    return questions


def _first_non_empty(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _first_from_experiences(items: List[Any]) -> str:
    for item in items:
        if isinstance(item, str) and item.strip():
            return item.strip()
        if hasattr(item, "title"):
            text = _first_non_empty(item.title, item.summary, item.impact)
            if text:
                return text
    return ""


def _story_context(
    profile: ProfileRecord,
    analysis: AnalysisRecord,
    cards: StoryCards,
) -> Dict[str, str]:
    data = profile.profile
    basic = data.basic_profile
    key_experience = _first_non_empty(
        _first_from_experiences(data.suggested_focus_experiences),
        _first_from_experiences(data.projects),
        _first_from_experiences(data.internships),
        _first_from_experiences(data.research_experiences),
        _first_non_empty(*cards.core_experience),
    )
    return {
        "target_field": _first_non_empty(basic.target_field, data.career_goal)
        or "目标方向",
        "degree": _first_non_empty(basic.target_degree) or "Master's",
        "major": _first_non_empty(basic.major) or "当前专业",
        "key_experience": key_experience or "你最能代表自己的经历",
        "program_focus": _first_non_empty(*analysis.analysis.program_focus)
        or "项目最看重的能力",
        "gap": _first_non_empty(*analysis.analysis.potential_gaps)
        or "希望补齐的能力",
        "strength": _first_non_empty(
            *data.top_strengths,
            *cards.strengths,
        )
        or "当前最突出的优势",
        "school": analysis.program.school_name,
        "program": analysis.program.program_name,
    }


def _fallback_questions(
    round_no: int,
    context: Dict[str, str],
    previous_questions: List[str],
    last_user_message: str,
) -> List[str]:
    hint = " ".join(last_user_message.split())[:40]
    candidates_by_round = {
        1: [
            f"你最想申请{context['target_field']}的哪个方向？",
            f"“{context['key_experience']}”中你做了什么？",
            f"你最想突出哪项优势（如{context['strength']}）？",
            f"为什么选择{context['school']}的这个项目？",
            f"你希望毕业后解决什么问题？",
        ],
        2: [
            f"“{hint or context['key_experience']}”的结果数据是什么？",
            f"这段经历怎样匹配{context['program_focus']}？",
            "你遇到的最大困难是什么？",
            "你当时做过哪个关键决定？",
            "谁从你的行动中直接受益？",
        ],
        3: [
            f"你准备如何补齐“{context['gap']}”？",
            f"{context['major']}背景如何帮助这个目标？",
            "一句话概括你的成长转折。",
            "哪段经历最能证明你的长期目标？",
            f"你能为{context['program']}带来什么独特视角？",
        ],
    }

    selected: List[str] = []
    for candidate in candidates_by_round.get(round_no, candidates_by_round[3]):
        if candidate in selected:
            continue
        if any(_question_similarity(candidate, previous) >= 0.72 for previous in previous_questions):
            continue
        selected.append(candidate)
        if len(selected) == 3:
            break
    generic_candidates = [
        "哪段经历最能证明你的目标？",
        "你做过最具体的行动是什么？",
        "这个结果为什么重要？",
        "你从这段经历学到什么？",
        "你希望招生官记住哪一点？",
    ]
    for candidate in generic_candidates:
        if len(selected) == 3:
            break
        if any(_question_similarity(candidate, previous) >= 0.72 for previous in previous_questions):
            continue
        if candidate not in selected:
            selected.append(candidate)
    return selected


def _prepare_questions(
    questions: List[str],
    previous_questions: List[str],
    round_no: int,
    context: Dict[str, str],
    last_user_message: str = "",
) -> List[str]:
    cleaned = [" ".join(question.split()).strip() for question in questions]
    valid = (
        len(cleaned) == 3
        and all(CJK_PATTERN.search(question) for question in cleaned)
        and len({_normalize_question(question) for question in cleaned}) == 3
        and all(
            _question_similarity(question, previous) < 0.72
            for question in cleaned
            for previous in previous_questions
        )
    )
    if valid:
        return cleaned
    return _fallback_questions(round_no, context, previous_questions, last_user_message)


def _format_story_message(intro: str, questions: List[str]) -> str:
    cleaned_intro = " ".join(intro.split()).strip()
    if not CJK_PATTERN.search(cleaned_intro):
        cleaned_intro = "我会继续围绕你的目标项目和已有经历做追问。"
    numbered = "\n".join(
        f"{index}. {question}" for index, question in enumerate(questions, start=1)
    )
    return f"{cleaned_intro}\n{numbered}"


def _story_response(
    session: SessionRecord,
    questions: Optional[List[str]] = None,
) -> StoryResponse:
    return StoryResponse(
        session_id=session.id,
        profile_id=session.profile_id,
        analysis_id=session.analysis_id,
        assistant_message=session.messages[-1].content,
        questions=questions or [],
        cards=session.cards,
        round_no=session.round_no,
        status=session.status,
    )


def _merge_manual_profile(profile: ProfileData, payload: Dict[str, Any]) -> ProfileData:
    merged = profile.model_copy(deep=True)
    basic_fields = {
        "full_name": "full_name",
        "current_university": "current_university",
        "major": "major",
        "gpa": "gpa",
        "graduation_year": "graduation_year",
        "english_test_score": "english_test_score",
        "target_degree": "target_degree",
        "target_field": "target_field",
        "target_country": "target_country",
    }
    for payload_key, profile_key in basic_fields.items():
        current = getattr(merged.basic_profile, profile_key)
        fallback = str(payload.get(payload_key) or "").strip()
        if not current and fallback:
            setattr(merged.basic_profile, profile_key, fallback)
    if not merged.basic_profile.target_degree:
        merged.basic_profile.target_degree = "Master's"
    return merged


def _session_bundle(
    owner_id: str, session_id: str
) -> Tuple[SessionRecord, ProfileRecord, AnalysisRecord]:
    store = get_store()
    session = store.require_session(session_id, owner_id)
    profile = store.require_profile(session.profile_id, owner_id)
    analysis = store.require_analysis(session.analysis_id, owner_id)
    if analysis.profile_id != profile.id:
        raise ConflictError("Session profile and analysis do not match")
    return session, profile, analysis


async def extract_profile_from_input(
    owner_id: str,
    payload: Dict[str, Any],
) -> ProfileRecord:
    messages = [
        {"role": "system", "content": PROFILE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Extract the graduate-application profile from the raw input below.\n\n"
                f"{_pretty_json(payload)}"
            ),
        },
    ]
    profile = await client.chat_json(
        messages,
        ProfileData,
        max_tokens=4500,
    )
    profile = _merge_manual_profile(profile, payload)
    return get_store().save_profile(owner_id, profile)


async def analyze_program(
    owner_id: str,
    request: ProgramAnalyzeRequest,
) -> ProgramAnalyzeResponse:
    store = get_store()
    profile = store.require_profile(request.profile_id, owner_id)
    context = request.to_context()
    messages = [
        {"role": "system", "content": PROGRAM_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Create a concise essay strategy from the profile and program context.\n\n"
                f"Applicant profile:\n{_pretty_json(profile.profile)}\n\n"
                f"Program context:\n{_pretty_json(context)}"
            ),
        },
    ]
    analysis = await client.chat_json(
        messages,
        ProgramAnalysis,
        max_tokens=5000,
    )
    record = store.save_analysis(owner_id, profile.id, context, analysis)
    return ProgramAnalyzeResponse(
        analysis_id=record.id,
        profile_id=record.profile_id,
        program=record.program,
        analysis=record.analysis,
    )


async def start_story_session(
    owner_id: str,
    profile_id: str,
    analysis_id: str,
) -> StoryResponse:
    store = get_store()
    profile = store.require_profile(profile_id, owner_id)
    analysis = store.require_analysis(analysis_id, owner_id)
    if analysis.profile_id != profile.id:
        raise ConflictError("Analysis does not belong to the selected profile")

    messages = [
        {"role": "system", "content": STORY_START_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Start the first story-mining round.\n\n"
                f"Profile:\n{_pretty_json(profile.profile)}\n\n"
                f"Program context:\n{_pretty_json(analysis.program)}\n\n"
                f"Program analysis:\n{_pretty_json(analysis.analysis)}"
            ),
        },
    ]
    result = await client.chat_json(
        messages,
        StoryTurnOutput,
        max_tokens=3000,
    )
    context = _story_context(profile, analysis, result.cards)
    questions = _prepare_questions(
        result.questions,
        previous_questions=[],
        round_no=1,
        context=context,
    )
    first_message = StoryMessage(
        role="assistant",
        content=_format_story_message(result.assistant_message, questions),
    )
    session = store.create_session(
        owner_id=owner_id,
        profile_id=profile.id,
        analysis_id=analysis.id,
        messages=[first_message],
        cards=result.cards,
        round_no=1,
        status="interviewing",
    )
    return _story_response(session, questions)


async def continue_story_session(
    owner_id: str,
    session_id: str,
    user_message: str,
) -> StoryResponse:
    store = get_store()
    session, profile, analysis = _session_bundle(owner_id, session_id)
    if session.status == "ready":
        raise ConflictError("The story interview is already complete")

    previous_questions = _extract_asked_questions(session.messages)
    user_turn = StoryMessage(role="user", content=user_message.strip())
    conversation = "\n".join(
        f"{message.role.upper()}: {message.content}" for message in session.messages
    )

    if session.round_no >= 3:
        messages = [
            {"role": "system", "content": STORY_FINAL_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Consolidate the interview facts into the final story cards.\n\n"
                    f"Current cards:\n{_pretty_json(session.cards)}\n\n"
                    f"Conversation:\n{conversation}\n\n"
                    f"Latest applicant answer:\n{user_message}"
                ),
            },
        ]
        result = await client.chat_json(
            messages,
            StoryCardsUpdate,
            max_tokens=2500,
        )
        closing = StoryMessage(
            role="assistant",
            content=(
                "三轮故事挖掘已完成，核心素材已经整理好。"
                "\n接下来可以生成中文大纲和英文草稿。"
            ),
        )
        session.messages = [*session.messages, user_turn, closing]
        session.cards = result.cards
        session.status = "ready"
        session = store.save_session(session)
        return _story_response(session)

    previous_text = "\n".join(f"- {question}" for question in previous_questions)
    messages = [
        {"role": "system", "content": STORY_REPLY_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Continue the interview for one more round.\n\n"
                f"Previously asked questions:\n{previous_text or '(none)'}\n\n"
                f"Current cards:\n{_pretty_json(session.cards)}\n\n"
                f"Profile:\n{_pretty_json(profile.profile)}\n\n"
                f"Program context:\n{_pretty_json(analysis.program)}\n\n"
                f"Program analysis:\n{_pretty_json(analysis.analysis)}\n\n"
                f"Conversation:\n{conversation}\n\n"
                f"Latest applicant answer:\n{user_message}"
            ),
        },
    ]
    result = await client.chat_json(
        messages,
        StoryTurnOutput,
        max_tokens=3000,
    )
    context = _story_context(profile, analysis, result.cards)
    questions = _prepare_questions(
        result.questions,
        previous_questions=previous_questions,
        round_no=session.round_no + 1,
        context=context,
        last_user_message=user_message,
    )
    assistant_turn = StoryMessage(
        role="assistant",
        content=_format_story_message(result.assistant_message, questions),
    )
    session.messages = [*session.messages, user_turn, assistant_turn]
    session.cards = result.cards
    session.round_no += 1
    session = store.save_session(session)
    return _story_response(session, questions)


async def generate_outline(owner_id: str, session_id: str) -> OutlineResponse:
    store = get_store()
    session, profile, analysis = _session_bundle(owner_id, session_id)
    if session.status != "ready":
        raise ConflictError("Complete all three story-mining rounds first")

    conversation = "\n".join(
        f"{message.role.upper()}: {message.content}" for message in session.messages
    )
    messages = [
        {"role": "system", "content": OUTLINE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Create the essay outline in Simplified Chinese.\n\n"
                f"Program context:\n{_pretty_json(analysis.program)}\n\n"
                f"Profile:\n{_pretty_json(profile.profile)}\n\n"
                f"Program analysis:\n{_pretty_json(analysis.analysis)}\n\n"
                f"Story cards:\n{_pretty_json(session.cards)}\n\n"
                f"Interview:\n{conversation}"
            ),
        },
    ]
    outline = await client.chat_json(
        messages,
        EssayOutline,
        max_tokens=4000,
    )
    version = store.add_artifact(
        owner_id,
        session.id,
        "outline",
        outline=outline,
        metadata={"word_limit": analysis.program.word_limit},
    )
    session.outline = outline
    store.save_session(session)
    return OutlineResponse(
        session_id=session.id,
        version=version.version_no,
        outline=outline,
    )


async def generate_draft(
    owner_id: str,
    request: DraftRequest,
) -> DraftResponse:
    store = get_store()
    session, profile, analysis = _session_bundle(owner_id, request.session_id)
    if session.status != "ready":
        raise ConflictError("Complete all three story-mining rounds first")

    if request.revision_instruction and not session.draft:
        raise ConflictError("Generate an initial draft before requesting a revision")

    outline = session.outline
    if outline is None:
        outline_result = await generate_outline(owner_id, session.id)
        outline = outline_result.outline
        session = store.require_session(session.id, owner_id)

    target_length = request.target_length or analysis.program.word_limit
    revision_block = ""
    if request.revision_instruction:
        revision_block = (
            "\nRevise the current draft according to the instruction below. "
            "Preserve supported facts and the requested essay prompt.\n"
            f"Current draft:\n{session.draft}\n\n"
            f"Revision instruction:\n{request.revision_instruction}\n"
        )

    messages = [
        {"role": "system", "content": DRAFT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Write a {request.tone} response of approximately {target_length} words.\n\n"
                f"Program context:\n{_pretty_json(analysis.program)}\n\n"
                f"Profile:\n{_pretty_json(profile.profile)}\n\n"
                f"Program analysis:\n{_pretty_json(analysis.analysis)}\n\n"
                f"Story cards:\n{_pretty_json(session.cards)}\n\n"
                f"Outline:\n{_pretty_json(outline)}\n"
                f"{revision_block}"
            ),
        },
    ]
    max_tokens = min(max(target_length * 3 + 500, 1800), 6000)
    draft = await client.chat_text(messages, max_tokens=max_tokens)
    if len(draft.split()) < max(80, int(target_length * 0.35)):
        raise ModelOutputError(
            "The generated draft was materially shorter than requested. Please retry."
        )

    labels = [paragraph.heading for paragraph in outline.paragraphs]
    version = store.add_artifact(
        owner_id,
        session.id,
        "draft",
        draft=draft,
        metadata={
            "tone": request.tone,
            "target_length": target_length,
            "revision_instruction": request.revision_instruction,
            "paragraph_labels": labels,
        },
    )
    session.draft = draft
    store.save_session(session)
    return DraftResponse(
        session_id=session.id,
        version=version.version_no,
        draft=draft,
        paragraph_labels=labels,
        target_length=target_length,
    )


async def review_draft(owner_id: str, session_id: str) -> ReviewResponse:
    store = get_store()
    session, profile, analysis = _session_bundle(owner_id, session_id)
    if not session.draft:
        raise ConflictError("Generate a draft before running a review")

    messages = [
        {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Review the essay draft.\n\n"
                f"Program context:\n{_pretty_json(analysis.program)}\n\n"
                f"Profile:\n{_pretty_json(profile.profile)}\n\n"
                f"Program analysis:\n{_pretty_json(analysis.analysis)}\n\n"
                f"Draft:\n{session.draft}"
            ),
        },
    ]
    review = await client.chat_json(
        messages,
        DraftReview,
        max_tokens=3000,
    )
    session.review = review
    store.save_session(session)
    return ReviewResponse(session_id=session.id, review=review)
