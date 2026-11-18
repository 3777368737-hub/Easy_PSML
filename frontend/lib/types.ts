export type BasicProfile = {
  full_name: string;
  current_university: string;
  major: string;
  gpa: string;
  graduation_year: string;
  english_test_score: string;
  target_degree: string;
  target_field: string;
  target_country: string;
};

export type ExperienceItem = {
  title: string;
  summary: string;
  impact: string;
};

export type ActivityAward = {
  title: string;
  summary: string;
};

export type ProfileData = {
  basic_profile: BasicProfile;
  motivation_summary: string;
  career_goal: string;
  research_experiences: ExperienceItem[];
  internships: ExperienceItem[];
  projects: ExperienceItem[];
  activities_awards: ActivityAward[];
  top_strengths: string[];
  suggested_focus_experiences: string[];
};

export type ProfileResponse = {
  profile_id: string;
  profile: ProfileData;
};

export type ProgramContext = {
  school_name: string;
  program_name: string;
  essay_type: string;
  word_limit: number;
  prompt_text: string;
  program_details: string;
};

export type ProgramAnalysis = {
  program_focus: string[];
  matched_strengths: string[];
  potential_gaps: string[];
  writing_suggestions: string[];
  recommended_structure: string[];
  avoid_phrases: string[];
};

export type AnalysisResponse = {
  analysis_id: string;
  profile_id: string;
  program: ProgramContext;
  analysis: ProgramAnalysis;
};

export type StoryCards = {
  motivation: string[];
  core_experience: string[];
  contribution_impact: string[];
  strengths: string[];
  career_goal: string[];
  program_fit: string[];
};

export type StoryMessage = {
  role: 'assistant' | 'user';
  content: string;
};

export type StoryResponse = {
  session_id: string;
  profile_id: string;
  analysis_id: string;
  assistant_message: string;
  questions: string[];
  cards: StoryCards;
  round_no: number;
  status: 'interviewing' | 'ready';
};

export type OutlineParagraph = {
  heading: string;
  goal: string;
  key_content: string;
  use_this_experience: string;
  what_to_highlight: string;
};

export type EssayOutline = {
  title: string;
  paragraphs: OutlineParagraph[];
};

export type DraftReview = {
  strengths: string[];
  weaknesses: string[];
  template_like_phrases: string[];
  suggested_details_to_add: string[];
  adaptation_tip: string;
};

export type ArtifactVersion = {
  id: string;
  session_id: string;
  artifact_type: 'outline' | 'draft';
  version_no: number;
  created_at: string;
  outline?: EssayOutline;
  draft?: string;
  metadata: Record<string, unknown>;
};

export type SessionSnapshot = {
  session_id: string;
  profile_id: string;
  analysis_id: string;
  program: ProgramContext;
  profile: ProfileData;
  analysis: ProgramAnalysis;
  cards: StoryCards;
  messages: StoryMessage[];
  outline?: EssayOutline;
  draft?: string;
  review?: DraftReview;
  round_no: number;
  status: 'interviewing' | 'ready';
  versions: ArtifactVersion[];
};

export type HistoryItem = {
  session_id: string;
  profile_id: string;
  applicant: string;
  program_label: string;
  created_at: string;
  updated_at: string;
  round_no: number;
  status: 'interviewing' | 'ready';
  has_outline: boolean;
  has_draft: boolean;
  draft_preview: string;
};

export type ProgramFormState = {
  school_name: string;
  program_name: string;
  essay_type: string;
  word_limit: string;
  prompt_text: string;
  program_details: string;
};

export type StorySessionState = {
  session_id: string;
  cards: StoryCards;
  messages: StoryMessage[];
  profile_id: string;
  analysis_id: string;
  round_no: number;
  status: 'interviewing' | 'ready';
};
