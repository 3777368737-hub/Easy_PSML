import { ApiError, apiFetch } from "@/lib/api";
import { loadState, STORAGE_KEYS } from "@/lib/storage";
import type {
  AnalysisResponse,
  ProfileResponse,
  SessionSnapshot,
  StorySessionState,
} from "@/lib/types";

export type AgentControlKind =
  | "text"
  | "textarea"
  | "select"
  | "number"
  | "checkbox"
  | "file"
  | "button"
  | "link";

export type AgentRisk = "safe" | "confirm" | "blocked";
export type AgentActionType = "fill" | "focus" | "click" | "navigate";
export type AgentIntent =
  | "fill_form"
  | "navigate"
  | "operate"
  | "answer"
  | "clarify"
  | "unsupported";

export type AgentControl = {
  id: string;
  key: string;
  kind: AgentControlKind;
  label: string;
  scope: string;
  value: string;
  placeholder: string;
  required: boolean;
  disabled: boolean;
  risk: AgentRisk;
  min_value?: number | null;
  max_value?: number | null;
  max_length?: number | null;
  options: Array<{ value: string; label: string }>;
  capability?: string | null;
};

export type AgentWorkflowStep = {
  key: string;
  path: string;
  title: string;
  summary: string;
  fields: string[];
};

export type AgentWorkflowState = {
  has_profile: boolean;
  has_program_analysis: boolean;
  has_story: boolean;
  story_status: "not_started" | "interviewing" | "ready";
  has_outline: boolean;
  has_draft: boolean;
};

export type AgentWorkflowIds = {
  profile_id: string;
  analysis_id: string;
  application_project_id: string;
  session_id: string;
  batch_id: string;
};

export type AgentPageContext = {
  path: string;
  title: string;
  stage: string;
  summary: string;
  focused_control_key: string;
  controls: AgentControl[];
  workflow: AgentWorkflowStep[];
  boundaries: string[];
  state: AgentWorkflowState;
  ids: AgentWorkflowIds;
  page_data: Record<string, unknown>;
};

export type AgentAction = {
  type: AgentActionType;
  target_id?: string | null;
  target_key?: string | null;
  value?: string | null;
  path?: string | null;
  reason: string;
  risk: AgentRisk;
};

export type AgentCommandResponse = {
  transcript: string;
  message: string;
  intent: AgentIntent;
  actions: AgentAction[];
  needs_confirmation: boolean;
  source: "voice" | "text";
  status:
    | "answered"
    | "needs_input"
    | "ready"
    | "confirmation_required";
  capability: AgentCapabilityCall | null;
  ui_actions: AgentUiAction[];
  missing_fields: AgentMissingField[];
  next_field: string | null;
  pending_action: AgentPendingAction | null;
};

export type AgentCapabilityCall = {
  name: string;
  arguments: Record<string, unknown>;
};

export type AgentUiAction = {
  type: "fill" | "focus" | "navigate" | "open_section";
  target_key?: string | null;
  value?: string | null;
  path?: string | null;
  section?: string | null;
  reason: string;
};

export type AgentMissingField = {
  key: string;
  label: string;
  target_key?: string | null;
};

export type AgentPendingAction = {
  id: string;
  capability: string;
  arguments: Record<string, unknown>;
  missing_fields: AgentMissingField[];
  status: "collecting" | "prepared";
  summary: string;
  expires_at: string;
};

export type AgentActionCommitResponse = {
  action_id: string;
  capability: string;
  arguments: Record<string, unknown>;
  status: "ready" | "needs_input";
  missing_fields: AgentMissingField[];
};

export type AgentStreamEvent =
  | { type: "transcript_delta"; text: string }
  | { type: "message_delta"; text: string }
  | { type: "message_reset" }
  | { type: "final"; response: AgentCommandResponse };

export type AgentConversationMessage = {
  role: "user" | "assistant" | "system";
  content: string;
};

export const AGENT_WORKFLOW: AgentWorkflowStep[] = [
  {
    key: "profile",
    path: "/profile",
    title: "背景资料",
    summary:
      "收集姓名、学校、专业、目标学位/方向/国家，以及可选经历、动机和职业目标。必填项完成后才能继续。",
    fields: [
      "full-name",
      "current-university",
      "major",
      "gpa",
      "graduation-year",
      "english-score",
      "target-degree",
      "target-field",
      "target-country",
      "research-experience",
      "internship-experience",
      "project-experience",
      "activities-awards",
      "motivation-text",
      "career-goal",
    ],
  },
  {
    key: "program",
    path: "/program",
    title: "项目分析",
    summary:
      "填写学校、项目、文书类型、字数上限、题目和可选官网资料，然后进行项目分析。",
    fields: [
      "program-school_name",
      "program-program_name",
      "program-essay_type",
      "program-word_limit",
      "program-prompt_text",
      "program-program_details",
    ],
  },
  {
    key: "story",
    path: "/story",
    title: "故事访谈",
    summary:
      "围绕当前三个问题回答故事细节；回答会更新故事素材卡，三轮完成后进入结果页。",
    fields: ["story-answer"],
  },
  {
    key: "result",
    path: "/result",
    title: "文书编辑",
    summary:
      "生成中文大纲、英文草稿、审核草稿并按修改意见重写；可切换版本和历史会话。",
    fields: ["revision-instruction"],
  },
  {
    key: "batch",
    path: "/batch",
    title: "批量生成",
    summary:
      "复用已完成背景，为任意数量的学校/项目方向配置 PS 或 ML，并创建批量任务。",
    fields: [
      "batch-tone",
      "动态方向学校名称",
      "动态方向项目名称",
      "动态项目资料",
      "动态文书类型",
      "动态字数上限",
      "动态文书题目",
    ],
  },
  {
    key: "library",
    path: "/library",
    title: "装配工作台",
    summary:
      "将人物背景、申请项目和已挖掘故事拖拽装配为文书链路。",
    fields: [
      "人物名称",
      "简历名称",
      "故事名称",
      "背景实例",
      "故事实例",
      "文书项目",
    ],
  },
];

export const AGENT_BOUNDARIES = [
  "文件上传不能由语音自动完成，只能聚焦文件选择框并提示用户手动选择。",
  "不得编造用户的姓名、学校、经历、成绩、项目或文书事实。",
  "提交表单、发送访谈回答、生成大纲/草稿、审核和批量生成必须由用户二次确认。",
  "清空历史等不可恢复操作必须由用户明确确认。",
  "只能操作当前页面清单中的控件，跨页面时只能跳转到项目内已登记路径。",
  "不为用户代填密码、API Key、证件号或其他敏感凭据。",
];

const PAGE_META: Record<
  string,
  { stage: string; title: string; summary: string }
> = {
  "/": {
    stage: "overview",
    title: "工作台",
    summary: "查看当前申请进度并继续下一步。",
  },
  "/profile": {
    stage: "profile",
    title: "背景资料",
    summary: "填写申请画像，保存草稿或继续到项目分析/批量生成。",
  },
  "/program": {
    stage: "program",
    title: "项目分析",
    summary: "填写当前目标项目与文书要求，并运行项目分析。",
  },
  "/story": {
    stage: "story",
    title: "故事访谈",
    summary: "回答故事访谈问题并查看已整理的故事素材。",
  },
  "/result": {
    stage: "result",
    title: "文书编辑",
    summary: "生成、查看、审核和修改当前文书。",
  },
  "/batch": {
    stage: "batch",
    title: "批量生成",
    summary: "配置多个申请方向并管理批量生成任务。",
  },
  "/library": {
    stage: "library",
    title: "申请项目",
    summary: "管理背景、申请项目、故事和文书分支。",
  },
};

const PENDING_FOCUS_KEY = "gradpilot_agent_pending_focus";
const AGENT_UNDO_KEY = "gradpilot_agent_undo_stack";
const SAFE_BUTTON_PATTERN =
  /返回|上一页|下一步|进入|前往|去生成结果|查看|切换|加载|保存草稿|添加|移除|刷新|重新连接|打开|关闭|展开|收起/;
const CONFIRM_BUTTON_PATTERN =
  /提交|开始|生成|分析|发送|继续|解析|重试|批量|重写|审核|确认|删除|清空/;

function normalizeText(value: string | null | undefined, limit = 240): string {
  return (value || "").replace(/\s+/g, " ").trim().slice(0, limit);
}

function truncateValue(value: string, limit = 1600): string {
  if (value.length <= limit) return value;
  return `${value.slice(0, limit)}...`;
}

function isVisible(element: HTMLElement): boolean {
  if (element.hidden || element.getAttribute("aria-hidden") === "true") {
    return false;
  }
  if (element.closest("[data-agent-ignore='true']")) return false;
  return element.getClientRects().length > 0;
}

function labelFor(element: HTMLElement): string {
  const ariaLabel = normalizeText(element.getAttribute("aria-label"));
  if (ariaLabel) return ariaLabel;
  if (element instanceof HTMLInputElement && element.id) {
    const label = document.querySelector<HTMLLabelElement>(
      `label[for="${CSS.escape(element.id)}"]`,
    );
    if (label) return normalizeText(label.textContent, 240);
  }
  if (
    (element instanceof HTMLTextAreaElement ||
      element instanceof HTMLSelectElement) &&
    element.id
  ) {
    const label = document.querySelector<HTMLLabelElement>(
      `label[for="${CSS.escape(element.id)}"]`,
    );
    if (label) return normalizeText(label.textContent, 240);
  }
  const wrappingLabel = element.closest("label");
  if (wrappingLabel) return normalizeText(wrappingLabel.textContent, 240);
  const field = element.closest(".field");
  const fieldLabel = field?.querySelector("label");
  if (fieldLabel) return normalizeText(fieldLabel.textContent, 240);
  const text = normalizeText(
    element instanceof HTMLInputElement ? element.placeholder : element.textContent,
  );
  return text || element.id || element.tagName.toLowerCase();
}

function scopeFor(element: HTMLElement): string {
  const container = element.closest(".card, .upload-panel, form");
  const heading = container?.querySelector("h1, h2, h3");
  return normalizeText(heading?.textContent, 240);
}

function controlKey(element: HTMLElement, kind: AgentControlKind, index: number) {
  return normalizeText(
    element.dataset.agentKey ||
      element.id ||
      element.getAttribute("name") ||
      `${kind}-${index}`,
    180,
  );
}

function controlKind(element: HTMLElement): AgentControlKind | null {
  if (element.tagName === "SUMMARY") return "button";
  if (element instanceof HTMLTextAreaElement) return "textarea";
  if (element instanceof HTMLSelectElement) return "select";
  if (element instanceof HTMLButtonElement) return "button";
  if (element instanceof HTMLAnchorElement) return "link";
  if (!(element instanceof HTMLInputElement)) return null;
  if (element.type === "number") return "number";
  if (element.type === "checkbox") return "checkbox";
  if (element.type === "file") return "file";
  if (["button", "submit", "reset"].includes(element.type)) return "button";
  if (["hidden", "image"].includes(element.type)) return null;
  return "text";
}

function controlValue(element: HTMLElement, kind: AgentControlKind): string {
  if (kind === "button" || kind === "link") return "";
  if (element instanceof HTMLInputElement) {
    if (element.type === "checkbox") return element.checked ? "true" : "false";
    if (element.type === "file") {
      return truncateValue(
        Array.from(element.files || [])
          .map((file) => file.name)
          .join(", "),
        400,
      );
    }
    return truncateValue(element.value);
  }
  if (
    element instanceof HTMLTextAreaElement ||
    element instanceof HTMLSelectElement
  ) {
    return truncateValue(element.value);
  }
  return "";
}

function controlRisk(
  element: HTMLElement,
  kind: AgentControlKind,
): AgentRisk {
  const explicit = element.dataset.agentRisk;
  if (explicit === "safe" || explicit === "confirm" || explicit === "blocked") {
    return explicit;
  }
  if (kind === "link") return "safe";
  if (kind !== "button") return "safe";
  const label = labelFor(element);
  if (CONFIRM_BUTTON_PATTERN.test(label) && !SAFE_BUTTON_PATTERN.test(label)) {
    return "confirm";
  }
  return "safe";
}

function optionsFor(element: HTMLElement): Array<{ value: string; label: string }> {
  if (!(element instanceof HTMLSelectElement)) return [];
  return Array.from(element.options)
    .slice(0, 100)
    .map((option) => ({
      value: normalizeText(option.value, 240),
      label: normalizeText(option.textContent, 240),
    }));
}

function numericAttribute(element: HTMLElement, name: string): number | null {
  const raw = element.getAttribute(name);
  if (raw === null || raw.trim() === "") return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

function maxLengthFor(element: HTMLElement): number | null {
  if (
    element instanceof HTMLInputElement ||
    element instanceof HTMLTextAreaElement
  ) {
    return element.maxLength > 0 ? element.maxLength : null;
  }
  return null;
}

function workflowState(): AgentWorkflowState {
  const profile = loadState<ProfileResponse>(STORAGE_KEYS.profile);
  const analysis = loadState<AnalysisResponse>(STORAGE_KEYS.analysis);
  const story = loadState<StorySessionState>(STORAGE_KEYS.storySession);
  const snapshot = loadState<SessionSnapshot>(STORAGE_KEYS.resultSnapshot);
  const storyStatus =
    story?.status === "ready" || snapshot?.status === "ready"
      ? "ready"
      : story?.session_id || snapshot?.session_id
        ? "interviewing"
        : "not_started";
  return {
    has_profile: Boolean(profile?.profile_id),
    has_program_analysis: Boolean(
      analysis?.analysis_id &&
        (!profile?.profile_id || analysis.profile_id === profile.profile_id),
    ),
    has_story: Boolean(story?.session_id || snapshot?.session_id),
    story_status: storyStatus,
    has_outline: Boolean(snapshot?.outline),
    has_draft: Boolean(snapshot?.draft),
  };
}

function workflowIds(): AgentWorkflowIds {
  const profile = loadState<ProfileResponse>(STORAGE_KEYS.profile);
  const analysis = loadState<AnalysisResponse>(STORAGE_KEYS.analysis);
  const story = loadState<StorySessionState>(STORAGE_KEYS.storySession);
  const snapshot = loadState<SessionSnapshot>(STORAGE_KEYS.resultSnapshot);
  return {
    profile_id: profile?.profile_id || "",
    analysis_id: analysis?.analysis_id || "",
    application_project_id:
      loadState<string>(STORAGE_KEYS.activeApplicationProjectId) || "",
    session_id: story?.session_id || snapshot?.session_id || "",
    batch_id: loadState<string>(STORAGE_KEYS.batchId) || "",
  };
}

function compactBatchForm(
  value: Record<string, unknown> | null,
): Record<string, unknown> | null {
  if (!value || !Array.isArray(value.directions)) return value;
  return {
    profile_id:
      typeof value.profile_id === "string" ? value.profile_id : "",
    tone: typeof value.tone === "string" ? value.tone : "balanced",
    directions: value.directions.map((item) => {
      const direction =
        item && typeof item === "object"
          ? (item as Record<string, unknown>)
          : {};
      const rawEssays =
        direction.essays && typeof direction.essays === "object"
          ? (direction.essays as Record<string, unknown>)
          : {};
      const essays: Record<string, unknown> = {};
      for (const type of ["Personal Statement", "Motivation Letter"]) {
        const rawEssay = rawEssays[type];
        const essay =
          rawEssay && typeof rawEssay === "object"
            ? (rawEssay as Record<string, unknown>)
            : {};
        essays[type] = {
          enabled: Boolean(essay.enabled),
          word_limit:
            typeof essay.word_limit === "string" ? essay.word_limit : "",
          prompt_text:
            typeof essay.prompt_text === "string"
              ? essay.prompt_text.slice(0, 1200)
              : "",
        };
      }
      return {
        id: typeof direction.id === "string" ? direction.id : "",
        school_name:
          typeof direction.school_name === "string"
            ? direction.school_name
            : "",
        program_name:
          typeof direction.program_name === "string"
            ? direction.program_name
            : "",
        program_details:
          typeof direction.program_details === "string"
            ? direction.program_details.slice(0, 1200)
            : "",
        essays,
      };
    }),
  };
}

export function capturePageContext(): AgentPageContext {
  const pathname = window.location.pathname.replace(/\/$/, "") || "/";
  const meta = PAGE_META[pathname] || {
    stage: "unknown",
    title: document.title,
    summary: "",
  };
  const root =
    document.querySelector<HTMLElement>("main") ||
    document.getElementById("main-content");
  const elements = root
    ? Array.from(
        root.querySelectorAll<HTMLElement>(
          "input, textarea, select, button, summary, a[href]",
        ),
      )
    : [];
  const controls: AgentControl[] = [];

  elements.forEach((element) => {
    if (controls.length >= 120 || !isVisible(element)) return;
    if (
      element instanceof HTMLAnchorElement &&
      !element.getAttribute("href")?.startsWith("/")
    ) {
      return;
    }
    const kind = controlKind(element);
    if (!kind) return;
    const index = controls.length;
    const id = `agent-control-${index}`;
    element.dataset.agentControlId = id;
    const disabled =
      element instanceof HTMLButtonElement ||
      element instanceof HTMLInputElement ||
      element instanceof HTMLTextAreaElement ||
      element instanceof HTMLSelectElement
        ? element.disabled
        : element.getAttribute("aria-disabled") === "true";
    controls.push({
      id,
      key: controlKey(element, kind, index),
      kind,
      label: labelFor(element),
      scope: scopeFor(element),
      value: controlValue(element, kind),
      placeholder: truncateValue(
        element.getAttribute("placeholder") || "",
        400,
      ),
      required:
        element.getAttribute("aria-required") === "true" ||
        element.hasAttribute("required"),
      disabled,
      risk: controlRisk(element, kind),
      min_value: numericAttribute(element, "min"),
      max_value: numericAttribute(element, "max"),
      max_length: maxLengthFor(element),
      options: optionsFor(element),
      capability: element.dataset.agentCapability || null,
    });
  });

  const heading = root?.querySelector("h1");
  const values = Object.fromEntries(
    controls.map((control) => [control.key, control.value]),
  );
  const profileForm = {
    full_name: values["full-name"] || "",
    current_university: values["current-university"] || "",
    major: values["major"] || "",
    gpa: values["gpa"] || "",
    graduation_year: values["graduation-year"] || "",
    english_test_score: values["english-score"] || "",
    target_degree: values["target-degree"] || "",
    target_field: values["target-field"] || "",
    target_country: values["target-country"] || "",
    research_experience: values["research-experience"] || "",
    internship_experience: values["internship-experience"] || "",
    project_experience: values["project-experience"] || "",
    activities_awards: values["activities-awards"] || "",
    motivation_text: values["motivation-text"] || "",
    career_goal: values["career-goal"] || "",
  };
  const programForm = {
    school_name: values["program-school_name"] || "",
    program_name: values["program-program_name"] || "",
    essay_type: values["program-essay_type"] || "",
    word_limit: values["program-word_limit"] || "",
    prompt_text: values["program-prompt_text"] || "",
    program_details: values["program-program_details"] || "",
  };
  const ids = workflowIds();
  const story = loadState<StorySessionState>(STORAGE_KEYS.storySession);
  const snapshot = loadState<SessionSnapshot>(STORAGE_KEYS.resultSnapshot);
  return {
    path: pathname,
    title: normalizeText(heading?.textContent) || meta.title,
    stage: meta.stage,
    summary: meta.summary,
    focused_control_key:
      controls.find(
        (control) =>
          document.activeElement?.getAttribute("data-agent-control-id") ===
          control.id,
      )?.key || "",
    controls,
    workflow: AGENT_WORKFLOW,
    boundaries: AGENT_BOUNDARIES,
    state: workflowState(),
    ids,
    page_data: {
      profile_form: profileForm,
      program_form: programForm,
      resume_selected: controls.some(
        (control) => control.kind === "file" && Boolean(control.value),
      ),
      resume_name:
        controls.find(
          (control) => control.kind === "file" && Boolean(control.value),
        )?.value || "",
      story_answer: values["story-answer"] || "",
      library_story_reply: values["workbench-story-reply"] || "",
      revision_instruction: values["revision-instruction"] || "",
      batch_form: compactBatchForm(
        loadState<Record<string, unknown>>(STORAGE_KEYS.batchForm),
      ),
      story_round_no: story?.round_no || snapshot?.round_no || 0,
      story_status:
        story?.status || snapshot?.status || "not_started",
      has_outline: Boolean(snapshot?.outline),
      has_draft: Boolean(snapshot?.draft),
      has_review: Boolean(snapshot?.review),
    },
  };
}

function findControl(targetId?: string | null): HTMLElement | null {
  if (!targetId) return null;
  return document.querySelector<HTMLElement>(
    `[data-agent-control-id="${CSS.escape(targetId)}"]`,
  );
}

type AgentUndoEntry = {
  key: string;
  previousValue: string;
  nextValue: string;
};

let undoingAgentEdit = false;

function readUndoStack(): AgentUndoEntry[] {
  try {
    const parsed = JSON.parse(sessionStorage.getItem(AGENT_UNDO_KEY) || "[]");
    return Array.isArray(parsed) ? parsed.slice(-20) : [];
  } catch {
    return [];
  }
}

function writeUndoStack(entries: AgentUndoEntry[]) {
  try {
    sessionStorage.setItem(AGENT_UNDO_KEY, JSON.stringify(entries.slice(-20)));
  } catch {
    // The current page can still continue without persisted undo history.
  }
}

function recordAgentEdit(key: string, previousValue: string, nextValue: string) {
  if (undoingAgentEdit || !key || previousValue === nextValue) return;
  writeUndoStack([
    ...readUndoStack(),
    { key, previousValue, nextValue },
  ]);
}

function findControlByKey(key: string): HTMLElement | null {
  const context = capturePageContext();
  const control = context.controls.find((item) => item.key === key);
  return findControl(control?.id);
}

export function undoLastAgentEdit(): {
  ok: boolean;
  message: string;
} {
  const stack = readUndoStack();
  const entry = stack.pop();
  if (!entry) {
    return { ok: false, message: "当前没有可以撤销的语音填写。" };
  }
  const element = findControlByKey(entry.key);
  if (!element) {
    writeUndoStack(stack);
    return {
      ok: false,
      message: "上一次修改不在当前页面，无法直接撤销。",
    };
  }
  undoingAgentEdit = true;
  const restored = fillControl(element, entry.previousValue);
  undoingAgentEdit = false;
  if (!restored) {
    return { ok: false, message: "这个字段无法自动撤销。" };
  }
  writeUndoStack(stack);
  flashAndFocus(element);
  return { ok: true, message: "已撤销上一次语音填写。" };
}

function flashAndFocus(element: HTMLElement) {
  element.scrollIntoView({ behavior: "smooth", block: "center" });
  window.setTimeout(() => {
    element.focus({ preventScroll: true });
    element.classList.remove("agent-control-highlight");
    void element.offsetWidth;
    element.classList.add("agent-control-highlight");
    window.setTimeout(() => {
      element.classList.remove("agent-control-highlight");
    }, 1800);
  }, 120);
}

function setNativeValue(
  element: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement,
  value: string,
) {
  const prototype =
    element instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : element instanceof HTMLSelectElement
        ? HTMLSelectElement.prototype
        : HTMLInputElement.prototype;
  const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
  descriptor?.set?.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
  element.dispatchEvent(new Event("change", { bubbles: true }));
}

function fillControl(element: HTMLElement, value: string): boolean {
  const boundedValue =
    (element instanceof HTMLInputElement ||
      element instanceof HTMLTextAreaElement) &&
    element.maxLength > 0
      ? value.slice(0, element.maxLength)
      : value;
  if (element instanceof HTMLInputElement) {
    if (element.type === "file") return false;
    if (element.type === "checkbox") {
      const checked = boundedValue === "true";
      const descriptor = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "checked",
      );
      descriptor?.set?.call(element, checked);
      element.dispatchEvent(new Event("input", { bubbles: true }));
      element.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    }
    setNativeValue(element, boundedValue);
    return true;
  }
  if (
    element instanceof HTMLTextAreaElement ||
    element instanceof HTMLSelectElement
  ) {
    setNativeValue(element, boundedValue);
    return true;
  }
  return false;
}

export function executeAgentAction(
  action: AgentAction,
  navigate: (path: string) => void,
  options: { confirmed?: boolean } = {},
): { ok: boolean; message: string } {
  if (action.type === "navigate") {
    if (!action.path) return { ok: false, message: "跳转路径缺失。" };
    if (action.target_key) {
      sessionStorage.setItem(PENDING_FOCUS_KEY, action.target_key);
    }
    if (action.path === window.location.pathname.replace(/\/$/, "") ||
      action.path === window.location.pathname) {
      void restorePendingAgentFocus();
    } else {
      navigate(action.path);
    }
    return { ok: true, message: "已跳转到目标页面。" };
  }

  const element = findControl(action.target_id);
  if (!element) {
    return { ok: false, message: "当前页面没有找到目标控件。" };
  }

  if (action.type === "focus") {
    flashAndFocus(element);
    return { ok: true, message: "已定位到目标输入框。" };
  }

    if (action.type === "fill") {
      if (action.value === null || action.value === undefined) {
        return { ok: false, message: "缺少需要填写的内容。" };
      }
      const previousValue =
        element instanceof HTMLInputElement &&
        element.type === "checkbox"
          ? element.checked
            ? "true"
            : "false"
          : element instanceof HTMLInputElement ||
              element instanceof HTMLTextAreaElement ||
              element instanceof HTMLSelectElement
            ? element.value
            : "";
      const filled = fillControl(element, action.value);
      if (filled) {
        recordAgentEdit(
          action.target_key || action.target_id || "",
          previousValue,
          action.value,
        );
        flashAndFocus(element);
      }
    return filled
      ? { ok: true, message: "已填写并定位到目标输入框。" }
      : { ok: false, message: "该控件不能通过语音直接填写。" };
  }

  if (action.type === "click") {
    if (action.risk === "confirm" && !options.confirmed) {
      return { ok: false, message: "该操作需要确认。" };
    }
    flashAndFocus(element);
    element.click();
    return { ok: true, message: "已执行按钮操作。" };
  }

  return { ok: false, message: "不支持的 Agent 动作。" };
}

export async function executeAgentUiActions(
  actions: AgentUiAction[],
  navigate: (path: string) => void,
): Promise<{ ok: boolean; message: string }> {
  for (const action of actions) {
    if (action.type === "navigate") {
      if (!action.path) {
        return { ok: false, message: "跳转路径缺失。" };
      }
      navigate(action.path);
      await new Promise((resolve) => window.setTimeout(resolve, 120));
      continue;
    }
    if (action.type === "open_section") {
      const sectionKey = action.section || action.target_key;
      if (sectionKey) {
        const section =
          document.getElementById(sectionKey) ||
          document.querySelector<HTMLElement>(
            `[data-agent-section="${CSS.escape(sectionKey)}"]`,
          );
        if (section instanceof HTMLDetailsElement) {
          section.open = true;
        } else if (section?.getAttribute("aria-expanded") === "false") {
          section.click();
        }
        section?.scrollIntoView({ behavior: "smooth", block: "start" });
        await new Promise((resolve) => window.setTimeout(resolve, 100));
        const firstField =
          section?.querySelector<HTMLElement>("[data-agent-autofocus='true']") ||
          section?.querySelector<HTMLElement>(
            "input:not([type='file']), textarea, select",
          );
        if (firstField) flashAndFocus(firstField);
      }
      continue;
    }
    const context = capturePageContext();
    const control = context.controls.find(
      (item) => item.key === action.target_key,
    );
    const element = findControl(control?.id);
    if (!control || !element) {
      return { ok: false, message: "当前页面没有找到目标字段。" };
    }
    if (action.type === "focus") {
      flashAndFocus(element);
      continue;
    }
    if (action.type === "fill") {
      if (action.value === null || action.value === undefined) {
        return { ok: false, message: "缺少需要填写的内容。" };
      }
      const previousValue =
        element instanceof HTMLInputElement &&
        element.type === "checkbox"
          ? element.checked
            ? "true"
            : "false"
          : element instanceof HTMLInputElement ||
              element instanceof HTMLTextAreaElement ||
              element instanceof HTMLSelectElement
            ? element.value
            : "";
      if (!fillControl(element, action.value)) {
        return { ok: false, message: "该字段不能由 Agent 填写。" };
      }
      recordAgentEdit(
        control.key,
        previousValue,
        action.value,
      );
      flashAndFocus(element);
      await new Promise((resolve) => window.setTimeout(resolve, 80));
    }
  }
  return { ok: true, message: "页面操作已执行。" };
}

const CAPABILITY_PATHS: Record<string, string> = {
  "profile.parse_resume": "/profile",
  "profile.save_draft": "/profile",
  "profile.continue_program": "/profile",
  "profile.continue_batch": "/profile",
  "program.analyze": "/program",
  "program.continue_story": "/program",
  "story.answer": "/story",
  "story.reload": "/story",
  "story.continue_result": "/story",
  "essay.outline": "/result",
  "essay.draft": "/result",
  "essay.rewrite": "/result",
  "essay.review": "/result",
  "project.analyze": "/result",
  "project.outline": "/result",
  "project.draft": "/result",
  "project.rewrite": "/result",
  "project.review": "/result",
  "result.switch_tab": "/result",
  "result.load_version": "/result",
  "result.restore_current": "/result",
  "essay.download": "/result",
  "essay.copy": "/result",
  "history.load": "/result",
  "history.clear": "/result",
  "batch.add_direction": "/batch",
  "batch.remove_direction": "/batch",
  "batch.clear_stories": "/batch",
  "batch.select": "/batch",
  "batch.create": "/batch",
  "batch.retry": "/batch",
  "batch.refresh": "/batch",
  "batch.download_all": "/batch",
  "batch.download_item": "/batch",
  "batch.open_result": "/batch",
  "library.person.create": "/library",
  "library.background.extract": "/library",
  "library.application_project.create": "/library",
  "library.story.create": "/library",
  "library.story.reply": "/library",
  "library.generate_all": "/library",
};

function capabilityCandidates(name: string): HTMLElement[] {
  return Array.from(
    document.querySelectorAll<HTMLElement>(
      `[data-agent-capability="${CSS.escape(name)}"]`,
    ),
  );
}

function capabilityForArguments(
  name: string,
  args: Record<string, unknown>,
): HTMLElement | null {
  const candidates = capabilityCandidates(name);
  return (
    candidates.find((candidate) => {
      if (
        candidate instanceof HTMLButtonElement ||
        candidate instanceof HTMLInputElement
      ) {
        if (candidate.disabled) return false;
      }
      if (candidate.getAttribute("aria-disabled") === "true") return false;
      return Object.entries(args).every(([key, value]) => {
        if (value === null || value === undefined || typeof value === "object") {
          return true;
        }
        const dataKey = `agentArg${key
          .split("_")
          .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
          .join("")}`;
        const expected = String(value);
        return (
          candidate.dataset[dataKey] === undefined ||
          candidate.dataset[dataKey] === expected
        );
      });
    }) || null
  );
}

function fillSemanticControl(key: string, value: string): boolean {
  const context = capturePageContext();
  const control = context.controls.find((item) => item.key === key);
  const element = findControl(control?.id);
  if (!element) return false;
  const previousValue =
    element instanceof HTMLInputElement && element.type === "checkbox"
      ? element.checked
        ? "true"
        : "false"
      : element instanceof HTMLInputElement ||
          element instanceof HTMLTextAreaElement ||
          element instanceof HTMLSelectElement
        ? element.value
        : "";
  const filled = fillControl(element, value);
  if (filled) recordAgentEdit(key, previousValue, value);
  return filled;
}

export async function executeAgentCapability(
  name: string,
  args: Record<string, unknown>,
  navigate: (path: string) => void,
): Promise<{ ok: boolean; message: string }> {
  if (name === "agent.undo_last_edit") {
    return undoLastAgentEdit();
  }
  if (name === "app.navigate") {
    const path = String(args.path || "");
    if (!path.startsWith("/")) {
      return { ok: false, message: "目标页面路径无效。" };
    }
    navigate(path);
    return { ok: true, message: "已跳转到目标页面。" };
  }
  if (name === "agent.cancel_pending") {
    return { ok: true, message: "已取消待执行操作。" };
  }
  if (name === "agent.confirm_pending") {
    const actionId = String(args.action_id || "");
    if (!actionId) {
      return { ok: false, message: "待确认操作已失效。" };
    }
    const result = await apiFetch<AgentActionCommitResponse>(
      `/api/agent/actions/${actionId}/commit`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ context: capturePageContext() }),
      },
    );
    if (result.status === "needs_input") {
      return {
        ok: false,
        message: `仍需补充：${result.missing_fields
          .map((field) => field.label)
          .join("、")}`,
      };
    }
    return executeAgentCapability(
      result.capability,
      result.arguments,
      navigate,
    );
  }
  if (name === "batch.select" && typeof args.batch_id === "string") {
    const element = document.getElementById("batch-history");
    if (element instanceof HTMLSelectElement) {
      setNativeValue(element, args.batch_id);
      return { ok: true, message: "已切换批量任务。" };
    }
  }
  if (name === "story.answer" && typeof args.answer === "string") {
    fillSemanticControl("story-answer", args.answer);
    await new Promise((resolve) => window.setTimeout(resolve, 100));
  }
  if (
    name === "library.story.reply" &&
    typeof args.answer === "string"
  ) {
    fillSemanticControl("workbench-story-reply", args.answer);
    await new Promise((resolve) => window.setTimeout(resolve, 100));
  }
  if (name === "essay.rewrite" && typeof args.instruction === "string") {
    fillSemanticControl("revision-instruction", args.instruction);
    await new Promise((resolve) => window.setTimeout(resolve, 100));
  }

  const expectedPath = CAPABILITY_PATHS[name];
  const currentPath = window.location.pathname.replace(/\/$/, "") || "/";
  if (expectedPath && expectedPath !== currentPath) {
    navigate(expectedPath);
  }

  let target: HTMLElement | null = null;
  for (let attempt = 0; attempt < 40; attempt += 1) {
    target = capabilityForArguments(name, args);
    if (target) break;
    await new Promise((resolve) => window.setTimeout(resolve, 100));
  }
  if (!target) {
    return {
      ok: false,
      message: "目标功能当前不可用，可能缺少前置条件或页面仍在加载。",
    };
  }

  target.scrollIntoView({ behavior: "smooth", block: "center" });
  window.setTimeout(() => target?.focus({ preventScroll: true }), 80);
  document.documentElement.dataset.agentExecuting = name;
  target.click();
  window.setTimeout(() => {
    delete document.documentElement.dataset.agentExecuting;
  }, 500);
  return { ok: true, message: "已在页面中执行目标操作。" };
}

export async function restorePendingAgentFocus(): Promise<boolean> {
  const targetKey = sessionStorage.getItem(PENDING_FOCUS_KEY);
  if (!targetKey) return false;

  for (let attempt = 0; attempt < 10; attempt += 1) {
    const context = capturePageContext();
    const control = context.controls.find((item) => item.key === targetKey);
    if (control) {
      const element = findControl(control.id);
      if (element) {
        sessionStorage.removeItem(PENDING_FOCUS_KEY);
        flashAndFocus(element);
        return true;
      }
    }
    await new Promise((resolve) => window.setTimeout(resolve, 150));
  }
  sessionStorage.removeItem(PENDING_FOCUS_KEY);
  return false;
}

export function focusInitialVoiceControl(): string | null {
  const context = capturePageContext();
  const editable = context.controls.filter(
    (control) =>
      !control.disabled &&
      control.risk !== "blocked" &&
      ["text", "textarea", "select", "number"].includes(control.kind),
  );
  const current = editable.find(
    (control) => control.key === context.focused_control_key,
  );
  const control =
    current ||
    editable.find(
      (item) => item.required && !item.value.trim(),
    ) ||
    editable.find((item) => !item.value.trim());
  if (!control) return null;
  const element = findControl(control.id);
  if (!element) return null;
  flashAndFocus(element);
  return control.label;
}

export function agentHistoryForRequest(
  messages: Array<{ role: "user" | "assistant" | "system"; content: string }>,
): AgentConversationMessage[] {
  return messages.slice(-6).map((message) => ({
    role: message.role,
    content: message.content.slice(0, 1200),
  }));
}

export async function consumeAgentStream(
  response: Response,
  onEvent: (event: AgentStreamEvent) => void,
): Promise<void> {
  if (!response.body) {
    throw new ApiError("流式响应不可用", response.status, "invalid_response");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const parseBlock = (block: string) => {
    let eventName = "message";
    const dataLines: string[] = [];
    for (const rawLine of block.split("\n")) {
      const line = rawLine.replace(/\r$/, "");
      if (!line || line.startsWith(":")) continue;
      if (line.startsWith("event:")) eventName = line.slice(6).trim();
      if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
    }
    if (!dataLines.length) return;

    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
    } catch {
      throw new ApiError(
        "流式响应格式无效",
        response.status,
        "invalid_response",
      );
    }

    if (eventName === "transcript_delta") {
      if (typeof payload.text === "string" && payload.text) {
        onEvent({ type: "transcript_delta", text: payload.text });
      }
      return;
    }
    if (eventName === "message_delta") {
      if (typeof payload.text === "string" && payload.text) {
        onEvent({ type: "message_delta", text: payload.text });
      }
      return;
    }
    if (eventName === "message_reset") {
      onEvent({ type: "message_reset" });
      return;
    }
    if (eventName === "error") {
      throw new ApiError(
        typeof payload.message === "string"
          ? payload.message
          : "语音助手请求失败",
        typeof payload.status === "number" ? payload.status : response.status,
        typeof payload.code === "string" ? payload.code : "request_failed",
      );
    }
    if (eventName === "final") {
      if (
        typeof payload.transcript !== "string" ||
        typeof payload.message !== "string" ||
        !Array.isArray(payload.actions)
      ) {
        throw new ApiError(
          "最终响应格式无效",
          response.status,
          "invalid_response",
        );
      }
      onEvent({
        type: "final",
        response: {
          ...(payload as AgentCommandResponse),
          status:
            typeof payload.status === "string"
              ? (payload.status as AgentCommandResponse["status"])
              : "answered",
          capability:
            payload.capability &&
            typeof payload.capability === "object"
              ? (payload.capability as AgentCapabilityCall)
              : null,
          ui_actions: Array.isArray(payload.ui_actions)
            ? (payload.ui_actions as AgentUiAction[])
            : [],
          missing_fields: Array.isArray(payload.missing_fields)
            ? (payload.missing_fields as AgentMissingField[])
            : [],
          next_field:
            typeof payload.next_field === "string"
              ? payload.next_field
              : null,
          pending_action:
            payload.pending_action &&
            typeof payload.pending_action === "object"
              ? (payload.pending_action as AgentPendingAction)
              : null,
        },
      });
    }
  };

  let completed = false;
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let separator = buffer.indexOf("\n\n");
      while (separator >= 0) {
        const block = buffer.slice(0, separator);
        buffer = buffer.slice(separator + 2);
        if (block.trim()) parseBlock(block);
        separator = buffer.indexOf("\n\n");
      }
      if (done) break;
    }
    if (buffer.trim()) parseBlock(buffer);
    completed = true;
  } finally {
    if (!completed) {
      await reader.cancel().catch(() => undefined);
    }
    reader.releaseLock();
  }
}
