from __future__ import annotations

from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator


Identifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=8, max_length=128),
]
ShortText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=240),
]
ParagraphText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1200),
]


class BasicProfile(BaseModel):
    full_name: str = Field(default="", max_length=120)
    current_university: str = Field(default="", max_length=200)
    major: str = Field(default="", max_length=200)
    gpa: str = Field(default="", max_length=80)
    graduation_year: str = Field(default="", max_length=40)
    english_test_score: str = Field(default="", max_length=160)
    target_degree: str = Field(default="Master's", max_length=120)
    target_field: str = Field(default="", max_length=200)
    target_country: str = Field(default="", max_length=160)


class ExperienceItem(BaseModel):
    id: str = Field(default="", max_length=128)
    title: str = Field(default="", max_length=240)
    summary: str = Field(default="", max_length=1200)
    impact: str = Field(default="", max_length=800)


class ActivityAward(BaseModel):
    id: str = Field(default="", max_length=128)
    title: str = Field(default="", max_length=240)
    summary: str = Field(default="", max_length=800)


class ProfileData(BaseModel):
    basic_profile: BasicProfile = Field(default_factory=BasicProfile)
    motivation_summary: str = Field(default="", max_length=1600)
    career_goal: str = Field(default="", max_length=1200)
    research_experiences: List[ExperienceItem] = Field(default_factory=list, max_length=10)
    internships: List[ExperienceItem] = Field(default_factory=list, max_length=10)
    projects: List[ExperienceItem] = Field(default_factory=list, max_length=10)
    activities_awards: List[ActivityAward] = Field(default_factory=list, max_length=10)
    top_strengths: List[ShortText] = Field(default_factory=list, max_length=5)
    suggested_focus_experiences: List[ShortText] = Field(default_factory=list, max_length=5)


class ProgramContext(BaseModel):
    school_name: str = Field(min_length=1, max_length=200)
    program_name: str = Field(min_length=1, max_length=200)
    essay_type: str = Field(default="Personal Statement", min_length=1, max_length=120)
    word_limit: int = Field(default=800, ge=100, le=5000)
    prompt_text: str = Field(default="", max_length=20000)
    program_details: str = Field(default="", max_length=30000)

    @field_validator(
        "school_name",
        "program_name",
        "essay_type",
        "prompt_text",
        "program_details",
    )
    @classmethod
    def strip_strings(cls, value: str) -> str:
        return value.strip()


class ProgramAnalysis(BaseModel):
    program_focus: List[ShortText] = Field(min_length=1, max_length=5)
    matched_strengths: List[ShortText] = Field(min_length=1, max_length=5)
    potential_gaps: List[ShortText] = Field(min_length=1, max_length=5)
    writing_suggestions: List[ShortText] = Field(min_length=1, max_length=5)
    recommended_structure: List[ShortText] = Field(min_length=1, max_length=5)
    avoid_phrases: List[ShortText] = Field(default_factory=list, max_length=5)


class StoryCards(BaseModel):
    motivation: List[ShortText] = Field(default_factory=list, max_length=5)
    core_experience: List[ShortText] = Field(default_factory=list, max_length=5)
    contribution_impact: List[ShortText] = Field(default_factory=list, max_length=5)
    strengths: List[ShortText] = Field(default_factory=list, max_length=5)
    career_goal: List[ShortText] = Field(default_factory=list, max_length=5)
    program_fit: List[ShortText] = Field(default_factory=list, max_length=5)


class StoryTurnOutput(BaseModel):
    assistant_message: str = Field(min_length=1, max_length=1200)
    questions: List[ShortText] = Field(min_length=3, max_length=3)
    cards: StoryCards = Field(default_factory=StoryCards)


class StoryCardsUpdate(BaseModel):
    cards: StoryCards


class StoryMessage(BaseModel):
    role: Literal["assistant", "user"]
    content: str = Field(min_length=1, max_length=12000)


class OutlineParagraph(BaseModel):
    heading: str = Field(min_length=1, max_length=160)
    goal: ParagraphText
    key_content: ParagraphText
    use_this_experience: ParagraphText
    what_to_highlight: ParagraphText


class EssayOutline(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    paragraphs: List[OutlineParagraph] = Field(min_length=4, max_length=5)


class DraftReview(BaseModel):
    strengths: List[ShortText] = Field(min_length=1, max_length=6)
    weaknesses: List[ShortText] = Field(min_length=1, max_length=6)
    template_like_phrases: List[ShortText] = Field(default_factory=list, max_length=10)
    suggested_details_to_add: List[ShortText] = Field(default_factory=list, max_length=8)
    adaptation_tip: str = Field(min_length=1, max_length=1200)


class ProfileResponse(BaseModel):
    profile_id: Identifier
    profile: ProfileData
    person_id: Optional[Identifier] = None
    background_instance_id: Optional[Identifier] = None
    background_version: Optional[int] = Field(default=None, ge=1)


class PersonCreateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    aliases: List[ShortText] = Field(default_factory=list, max_length=20)

    @field_validator("display_name")
    @classmethod
    def strip_display_name(cls, value: str) -> str:
        return value.strip()


class PersonResponse(BaseModel):
    id: Identifier
    display_name: str
    aliases: List[str] = Field(default_factory=list)
    background_count: int = Field(default=0, ge=0)
    story_count: int = Field(default=0, ge=0)
    created_at: str
    updated_at: str


class BackgroundInstanceResponse(BaseModel):
    id: Identifier
    person_id: Identifier
    resume_name: str
    source_filename: str = ""
    source_sha256: str = ""
    status: Literal["draft", "extracted", "confirmed", "archived"]
    version: int = Field(ge=1)
    profile: ProfileData
    legacy_profile_id: Optional[Identifier] = None
    created_at: str
    updated_at: str


class BackgroundRenameRequest(BaseModel):
    resume_name: str = Field(min_length=1, max_length=160)

    @field_validator("resume_name")
    @classmethod
    def strip_resume_name(cls, value: str) -> str:
        return value.strip()


class ProfilePatchOperation(BaseModel):
    op: Literal["set", "append", "remove", "clear"]
    path: str = Field(min_length=1, max_length=200)
    item_id: Optional[str] = Field(default=None, max_length=128)
    index: Optional[int] = Field(default=None, ge=0)
    value: Optional[Any] = None


class BackgroundPatchRequest(BaseModel):
    base_version: Optional[int] = Field(default=None, ge=1)
    operations: List[ProfilePatchOperation] = Field(min_length=1, max_length=50)


class ApplicationProjectCreateRequest(BaseModel):
    background_instance_id: Identifier
    school_name: str = Field(min_length=1, max_length=200)
    program_name: str = Field(min_length=1, max_length=200)
    program_details: str = Field(default="", max_length=30000)

    @field_validator("school_name", "program_name", "program_details")
    @classmethod
    def strip_application_project_strings(cls, value: str) -> str:
        return value.strip()


class ApplicationProjectPatchRequest(BaseModel):
    school_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    program_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    program_details: Optional[str] = Field(default=None, max_length=30000)


class ApplicationProjectResponse(BaseModel):
    id: Identifier
    background_instance_id: Identifier
    person_id: Identifier
    school_name: str
    program_name: str
    program_details: str = ""
    status: Literal["active", "archived"] = "active"
    story_count: int = Field(default=0, ge=0)
    essay_count: int = Field(default=0, ge=0)
    created_at: str
    updated_at: str


class StoryInstanceResponse(BaseModel):
    id: Identifier
    background_instance_id: Identifier
    application_project_id: Optional[Identifier] = None
    title: str
    focus: str = ""
    status: Literal["interviewing", "ready", "archived"]
    round_no: int = Field(ge=1, le=3)
    cards: StoryCards
    messages: List[StoryMessage] = Field(default_factory=list)
    version: int = Field(ge=1)
    created_at: str
    updated_at: str


class StoryInstanceStartRequest(BaseModel):
    background_instance_id: Identifier
    application_project_id: Identifier
    title: str = Field(min_length=1, max_length=160)
    focus: str = Field(default="", max_length=1200)

    @field_validator("title", "focus")
    @classmethod
    def strip_story_fields(cls, value: str) -> str:
        return value.strip()


class StoryInstanceReplyRequest(BaseModel):
    user_message: str = Field(min_length=1, max_length=4000)

    @field_validator("user_message")
    @classmethod
    def strip_story_reply(cls, value: str) -> str:
        return value.strip()


class StoryInstancePatchRequest(BaseModel):
    cards: StoryCards
    base_version: Optional[int] = Field(default=None, ge=1)


class EssayProjectArtifactVersion(BaseModel):
    id: Identifier
    project_id: Identifier
    artifact_type: Literal["outline", "draft"]
    version_no: int = Field(ge=1)
    created_at: str
    outline: Optional[EssayOutline] = None
    draft: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EssayProjectCreateRequest(BaseModel):
    background_instance_id: Identifier
    story_instance_ids: List[Identifier] = Field(default_factory=list)
    school_name: str = Field(min_length=1, max_length=200)
    program_name: str = Field(min_length=1, max_length=200)
    essay_type: str = Field(default="Personal Statement", min_length=1, max_length=120)
    word_limit: int = Field(default=800, ge=100, le=5000)
    prompt_text: str = Field(min_length=10, max_length=20000)
    program_details: str = Field(default="", max_length=30000)

    @field_validator(
        "school_name",
        "program_name",
        "essay_type",
        "prompt_text",
        "program_details",
    )
    @classmethod
    def strip_project_strings(cls, value: str) -> str:
        return value.strip()

    @field_validator("story_instance_ids")
    @classmethod
    def unique_story_ids(cls, value: List[str]) -> List[str]:
        if len(set(value)) != len(value):
            raise ValueError("story_instance_ids must be unique")
        return value

    def to_program_context(self) -> ProgramContext:
        return ProgramContext(
            school_name=self.school_name,
            program_name=self.program_name,
            essay_type=self.essay_type,
            word_limit=self.word_limit,
            prompt_text=self.prompt_text,
            program_details=self.program_details,
        )


class EssayBranchCreateRequest(BaseModel):
    application_project_id: Identifier
    essay_type: Literal["Personal Statement", "Motivation Letter"]
    word_limit: int = Field(default=800, ge=100, le=5000)
    prompt_text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=10, max_length=20000)
    ]
    story_instance_ids: List[Identifier] = Field(default_factory=list)
    tone: Literal["balanced", "authentic", "academic", "concise"] = "balanced"

    @field_validator("story_instance_ids")
    @classmethod
    def unique_branch_story_ids(cls, value: List[str]) -> List[str]:
        if len(set(value)) != len(value):
            raise ValueError("story_instance_ids must be unique")
        return value


class EssayProjectDraftRequest(BaseModel):
    tone: Literal["balanced", "authentic", "academic", "concise"] = "balanced"
    target_length: Optional[int] = Field(default=None, ge=100, le=5000)
    revision_instruction: str = Field(default="", max_length=4000)

    @field_validator("revision_instruction")
    @classmethod
    def strip_project_instruction(cls, value: str) -> str:
        return value.strip()


class EssayProjectPatchRequest(BaseModel):
    school_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    program_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    essay_type: Optional[str] = Field(default=None, min_length=1, max_length=120)
    word_limit: Optional[int] = Field(default=None, ge=100, le=5000)
    prompt_text: Optional[str] = Field(default=None, min_length=10, max_length=20000)
    program_details: Optional[str] = Field(default=None, max_length=30000)
    story_instance_ids: Optional[List[Identifier]] = None

    @field_validator(
        "school_name",
        "program_name",
        "essay_type",
        "prompt_text",
        "program_details",
    )
    @classmethod
    def strip_project_patch_strings(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value is not None else None

    @field_validator("story_instance_ids")
    @classmethod
    def unique_project_story_ids(
        cls,
        value: Optional[List[str]],
    ) -> Optional[List[str]]:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("story_instance_ids must be unique")
        return value


class EssayProjectResponse(BaseModel):
    id: Identifier
    person_id: Identifier
    background_instance_id: Identifier
    application_project_id: Optional[Identifier] = None
    story_instance_ids: List[Identifier] = Field(default_factory=list)
    program: ProgramContext
    analysis: Optional[ProgramAnalysis] = None
    outline: Optional[EssayOutline] = None
    draft: Optional[str] = None
    review: Optional[DraftReview] = None
    status: Literal[
        "created",
        "analyzed",
        "outlined",
        "drafted",
        "reviewed",
        "stale",
        "archived",
    ]
    current_step: Literal[
        "created",
        "analysis",
        "outline",
        "draft",
        "review",
        "completed",
    ] = "created"
    versions: List[EssayProjectArtifactVersion] = Field(default_factory=list)
    created_at: str
    updated_at: str


class WorkspaceSnapshotResponse(BaseModel):
    persons: List[PersonResponse] = Field(default_factory=list)
    backgrounds: List[BackgroundInstanceResponse] = Field(default_factory=list)
    application_projects: List[ApplicationProjectResponse] = Field(default_factory=list)
    stories: List[StoryInstanceResponse] = Field(default_factory=list)
    projects: List[EssayProjectResponse] = Field(default_factory=list)


class ProgramAnalyzeRequest(BaseModel):
    profile_id: Identifier
    school_name: str = Field(min_length=1, max_length=200)
    program_name: str = Field(min_length=1, max_length=200)
    essay_type: str = Field(default="Personal Statement", min_length=1, max_length=120)
    word_limit: int = Field(default=800, ge=100, le=5000)
    prompt_text: str = Field(min_length=10, max_length=20000)
    program_details: str = Field(default="", max_length=30000)

    @field_validator(
        "school_name",
        "program_name",
        "essay_type",
        "prompt_text",
        "program_details",
    )
    @classmethod
    def strip_strings(cls, value: str) -> str:
        return value.strip()

    @field_validator("prompt_text")
    @classmethod
    def validate_prompt_text(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 10:
            raise ValueError("prompt_text must contain at least 10 characters")
        return cleaned

    def to_context(self) -> ProgramContext:
        return ProgramContext(
            school_name=self.school_name,
            program_name=self.program_name,
            essay_type=self.essay_type,
            word_limit=self.word_limit,
            prompt_text=self.prompt_text,
            program_details=self.program_details,
        )


class ProgramAnalyzeResponse(BaseModel):
    analysis_id: Identifier
    profile_id: Identifier
    program: ProgramContext
    analysis: ProgramAnalysis


class StoryStartRequest(BaseModel):
    profile_id: Identifier
    analysis_id: Identifier


class StoryReplyRequest(BaseModel):
    session_id: Identifier
    user_message: str = Field(min_length=1, max_length=4000)

    @field_validator("user_message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        return value.strip()


class StoryResponse(BaseModel):
    session_id: Identifier
    profile_id: Identifier
    analysis_id: Identifier
    assistant_message: str
    questions: List[ShortText] = Field(default_factory=list, max_length=3)
    cards: StoryCards
    round_no: int = Field(ge=1, le=3)
    status: Literal["interviewing", "ready"]


class OutlineRequest(BaseModel):
    session_id: Identifier


class OutlineResponse(BaseModel):
    session_id: Identifier
    version: int = Field(ge=1)
    outline: EssayOutline


class DraftRequest(BaseModel):
    session_id: Identifier
    tone: Literal["balanced", "authentic", "academic", "concise"] = "balanced"
    target_length: Optional[int] = Field(default=None, ge=100, le=5000)
    revision_instruction: str = Field(default="", max_length=4000)

    @field_validator("revision_instruction")
    @classmethod
    def strip_instruction(cls, value: str) -> str:
        return value.strip()


class DraftResponse(BaseModel):
    session_id: Identifier
    version: int = Field(ge=1)
    draft: str = Field(min_length=1)
    paragraph_labels: List[str] = Field(default_factory=list)
    target_length: int = Field(ge=100, le=5000)


class ReviewRequest(BaseModel):
    session_id: Identifier


class ReviewResponse(BaseModel):
    session_id: Identifier
    review: DraftReview


class ArtifactVersion(BaseModel):
    id: Identifier
    session_id: Identifier
    artifact_type: Literal["outline", "draft"]
    version_no: int = Field(ge=1)
    created_at: str
    outline: Optional[EssayOutline] = None
    draft: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SessionSnapshotResponse(BaseModel):
    session_id: Identifier
    profile_id: Identifier
    analysis_id: Identifier
    program: ProgramContext
    profile: ProfileData
    analysis: ProgramAnalysis
    cards: StoryCards
    messages: List[StoryMessage]
    outline: Optional[EssayOutline] = None
    draft: Optional[str] = None
    review: Optional[DraftReview] = None
    round_no: int = Field(ge=1, le=3)
    status: Literal["interviewing", "ready"]
    versions: List[ArtifactVersion] = Field(default_factory=list)


class HistoryItem(BaseModel):
    session_id: Identifier
    profile_id: Identifier
    applicant: str
    program_label: str
    created_at: str
    updated_at: str
    round_no: int = Field(ge=1, le=3)
    status: Literal["interviewing", "ready"]
    has_outline: bool
    has_draft: bool
    draft_preview: str = ""


class DeleteHistoryResponse(BaseModel):
    deleted: int = Field(ge=0)


AgentControlKind = Literal[
    "text",
    "textarea",
    "select",
    "number",
    "checkbox",
    "file",
    "button",
    "link",
]
AgentActionType = Literal["fill", "focus", "click", "navigate"]
AgentIntent = Literal[
    "fill_form",
    "navigate",
    "operate",
    "answer",
    "clarify",
    "unsupported",
]
AgentRisk = Literal["safe", "confirm", "blocked"]
AgentUiActionType = Literal["fill", "focus", "navigate", "open_section"]
AgentResponseStatus = Literal[
    "answered",
    "needs_input",
    "ready",
    "confirmation_required",
]


class AgentControlOption(BaseModel):
    value: str = Field(max_length=240)
    label: str = Field(max_length=240)


class AgentControl(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    key: str = Field(min_length=1, max_length=180)
    kind: AgentControlKind
    label: str = Field(min_length=1, max_length=240)
    scope: str = Field(default="", max_length=240)
    value: str = Field(default="", max_length=1600)
    placeholder: str = Field(default="", max_length=400)
    required: bool = False
    disabled: bool = False
    risk: AgentRisk = "safe"
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    max_length: Optional[int] = Field(default=None, ge=0, le=50000)
    options: List[AgentControlOption] = Field(default_factory=list, max_length=100)
    capability: Optional[str] = Field(default=None, max_length=120)

    @field_validator("id", "key", "label", "scope", "placeholder")
    @classmethod
    def strip_control_strings(cls, value: str) -> str:
        return value.strip()


class AgentWorkflowStep(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    path: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(default="", max_length=500)
    fields: List[str] = Field(default_factory=list, max_length=40)


class AgentWorkflowState(BaseModel):
    has_profile: bool = False
    has_program_analysis: bool = False
    has_story: bool = False
    story_status: Literal["not_started", "interviewing", "ready"] = "not_started"
    has_outline: bool = False
    has_draft: bool = False


class AgentWorkflowIds(BaseModel):
    profile_id: str = Field(default="", max_length=128)
    analysis_id: str = Field(default="", max_length=128)
    application_project_id: str = Field(default="", max_length=128)
    session_id: str = Field(default="", max_length=128)
    batch_id: str = Field(default="", max_length=128)


class AgentPageContext(BaseModel):
    path: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=240)
    stage: str = Field(min_length=1, max_length=80)
    summary: str = Field(default="", max_length=1000)
    focused_control_key: str = Field(default="", max_length=180)
    controls: List[AgentControl] = Field(default_factory=list, max_length=120)
    workflow: List[AgentWorkflowStep] = Field(default_factory=list, max_length=10)
    boundaries: List[Annotated[str, StringConstraints(max_length=500)]] = Field(
        default_factory=list,
        max_length=20,
    )
    state: AgentWorkflowState = Field(default_factory=AgentWorkflowState)
    ids: AgentWorkflowIds = Field(default_factory=AgentWorkflowIds)
    page_data: Dict[str, Any] = Field(default_factory=dict)


class AgentConversationMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str = Field(min_length=1, max_length=1200)


class AgentTextCommandRequest(BaseModel):
    transcript: str = Field(min_length=1, max_length=4000)
    context: AgentPageContext
    history: List[AgentConversationMessage] = Field(default_factory=list, max_length=8)
    source: Literal["voice", "text"] = "text"

    @field_validator("transcript")
    @classmethod
    def strip_transcript(cls, value: str) -> str:
        return value.strip()


class AgentAction(BaseModel):
    type: AgentActionType
    target_id: Optional[str] = Field(default=None, max_length=80)
    target_key: Optional[str] = Field(default=None, max_length=180)
    value: Optional[str] = Field(default=None, max_length=12000)
    path: Optional[str] = Field(default=None, max_length=160)
    reason: str = Field(default="", max_length=300)
    risk: AgentRisk = "safe"


class AgentCapabilityCall(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    arguments: Dict[str, Any] = Field(default_factory=dict)


class AgentUiAction(BaseModel):
    type: AgentUiActionType
    target_key: Optional[str] = Field(default=None, max_length=180)
    value: Optional[str] = Field(default=None, max_length=12000)
    path: Optional[str] = Field(default=None, max_length=160)
    section: Optional[str] = Field(default=None, max_length=180)
    reason: str = Field(default="", max_length=300)


class AgentMissingField(BaseModel):
    key: str = Field(min_length=1, max_length=180)
    label: str = Field(min_length=1, max_length=240)
    target_key: Optional[str] = Field(default=None, max_length=180)


class AgentPendingAction(BaseModel):
    id: str = Field(min_length=8, max_length=128)
    capability: str = Field(min_length=1, max_length=120)
    arguments: Dict[str, Any] = Field(default_factory=dict)
    missing_fields: List[AgentMissingField] = Field(default_factory=list, max_length=20)
    status: Literal["collecting", "prepared"] = "collecting"
    summary: str = Field(default="", max_length=1000)
    expires_at: str = Field(min_length=1, max_length=80)


class AgentPlan(BaseModel):
    message: str = Field(min_length=1, max_length=800)
    intent: AgentIntent
    actions: List[AgentAction] = Field(default_factory=list, max_length=4)
    capability: Optional[AgentCapabilityCall] = None
    ui_actions: List[AgentUiAction] = Field(default_factory=list, max_length=6)
    missing_fields: List[AgentMissingField] = Field(default_factory=list, max_length=20)
    next_field: Optional[str] = Field(default=None, max_length=180)
    needs_confirmation: bool = False


class AgentCommandResponse(AgentPlan):
    transcript: str = Field(min_length=1, max_length=4000)
    source: Literal["voice", "text"]
    status: AgentResponseStatus = "answered"
    pending_action: Optional[AgentPendingAction] = None


class AgentActionCommitRequest(BaseModel):
    context: AgentPageContext


class AgentActionCommitResponse(BaseModel):
    action_id: str
    capability: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    status: Literal["ready", "needs_input"] = "ready"
    missing_fields: List[AgentMissingField] = Field(default_factory=list)


class AgentActionCancelResponse(BaseModel):
    cancelled: bool


class DomainAgentRequest(BaseModel):
    transcript: str = Field(min_length=1, max_length=4000)
    history: List[AgentConversationMessage] = Field(default_factory=list, max_length=8)
    active_person_id: str = Field(default="", max_length=128)
    active_background_id: str = Field(default="", max_length=128)
    active_application_project_id: str = Field(default="", max_length=128)
    active_story_id: str = Field(default="", max_length=128)
    active_project_id: str = Field(default="", max_length=128)
    pending_capability: Optional[str] = Field(default=None, max_length=120)
    pending_arguments: Dict[str, Any] = Field(default_factory=dict)
    pending_resolved: Dict[str, Any] = Field(default_factory=dict)
    pending_missing_fields: List[AgentMissingField] = Field(
        default_factory=list,
        max_length=20,
    )
    pending_next_field: Optional[str] = Field(default=None, max_length=120)
    allow_stored_person: bool = False
    allow_stored_background: bool = False
    allow_stored_application_project: bool = False
    allow_stored_story: bool = False
    allow_stored_project: bool = False
    confirmed: bool = False
    source: Literal["voice", "text"] = "text"

    @field_validator("transcript")
    @classmethod
    def strip_domain_transcript(cls, value: str) -> str:
        return value.strip()


class DomainCommandResponse(BaseModel):
    transcript: str
    message: str
    intent: AgentIntent
    status: Literal["answered", "needs_input", "confirmation_required", "executed"]
    capability: Optional[AgentCapabilityCall] = None
    arguments: Dict[str, Any] = Field(default_factory=dict)
    resolved: Dict[str, Any] = Field(default_factory=dict)
    result: Dict[str, Any] = Field(default_factory=dict)
    missing_fields: List[AgentMissingField] = Field(default_factory=list)
    next_field: Optional[str] = Field(default=None, max_length=120)
    needs_confirmation: bool = False
    source: Literal["voice", "text"] = "text"


class HealthResponse(BaseModel):
    ok: bool
    database: Literal["ok"]
    version: str


class BatchEssayRequest(BaseModel):
    essay_type: Literal["Personal Statement", "Motivation Letter"]
    word_limit: int = Field(default=800, ge=100, le=5000)
    tone: Optional[
        Literal["balanced", "authentic", "academic", "concise"]
    ] = None
    prompt_text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=10, max_length=20000)
    ]


class BatchDirectionRequest(BaseModel):
    application_project_id: Optional[Identifier] = None
    school_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    program_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    program_details: str = Field(default="", max_length=30000)
    essays: List[BatchEssayRequest] = Field(min_length=1, max_length=2)
    story_instance_ids: List[Identifier] = Field(default_factory=list)

    @field_validator("program_details")
    @classmethod
    def clean_details(cls, value: str) -> str:
        return value.strip()

    @field_validator("essays")
    @classmethod
    def unique_essay_types(cls, value: List[BatchEssayRequest]) -> List[BatchEssayRequest]:
        if len({essay.essay_type for essay in value}) != len(value):
            raise ValueError("Each direction must have unique essay types")
        return value

    @field_validator("story_instance_ids")
    @classmethod
    def unique_story_ids(cls, value: List[str]) -> List[str]:
        if len(set(value)) != len(value):
            raise ValueError("Each direction must have unique story instances")
        return value


class BatchCreateRequest(BaseModel):
    profile_id: Optional[Identifier] = None
    background_instance_id: Optional[Identifier] = None
    request_id: Identifier
    tone: Literal["balanced", "authentic", "academic", "concise"] = "balanced"
    directions: List[BatchDirectionRequest] = Field(min_length=1)

    @model_validator(mode="after")
    def require_profile_or_background(self) -> "BatchCreateRequest":
        if not self.profile_id and not self.background_instance_id:
            raise ValueError("profile_id or background_instance_id is required")
        return self


class BatchItemResponse(BaseModel):
    id: Identifier
    direction_index: int = Field(ge=0)
    program: ProgramContext
    status: Literal["pending", "running", "completed", "failed"]
    stage: Literal["pending", "analysis", "outline", "draft", "completed", "failed"]
    session_id: Optional[Identifier] = None
    project_id: Optional[Identifier] = None
    application_project_id: Optional[Identifier] = None
    background_instance_id: Optional[Identifier] = None
    story_instance_ids: List[Identifier] = Field(default_factory=list)
    tone: Literal["balanced", "authentic", "academic", "concise"] = "balanced"
    draft: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class BatchResponse(BaseModel):
    id: Identifier
    profile_id: Identifier
    background_instance_id: Optional[Identifier] = None
    execution_mode: Literal["legacy", "instance"] = "legacy"
    tone: Literal["balanced", "authentic", "academic", "concise"]
    status: Literal["pending", "running", "completed", "partial_failed", "failed"]
    created_at: str
    updated_at: str
    items: List[BatchItemResponse]
