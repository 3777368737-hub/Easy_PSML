from __future__ import annotations

from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, StringConstraints, field_validator


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
    title: str = Field(default="", max_length=240)
    summary: str = Field(default="", max_length=1200)
    impact: str = Field(default="", max_length=800)


class ActivityAward(BaseModel):
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


class HealthResponse(BaseModel):
    ok: bool
    database: Literal["ok"]
    version: str
