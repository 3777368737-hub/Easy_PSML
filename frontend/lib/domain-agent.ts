import { apiFetch } from "@/lib/api";
import { loadState, saveState, STORAGE_KEYS } from "@/lib/storage";
import type {
  AgentCapabilityCall,
  AgentConversationMessage,
  AgentIntent,
} from "@/lib/voice-agent";

export type DomainAgentResponse = {
  transcript: string;
  message: string;
  intent: AgentIntent;
  status:
    | "answered"
    | "needs_input"
    | "confirmation_required"
    | "executed";
  capability: AgentCapabilityCall | null;
  arguments: Record<string, unknown>;
  resolved: Record<string, unknown>;
  result: Record<string, unknown>;
  needs_confirmation: boolean;
  source: "voice" | "text";
};

export type DomainNavigationTarget = {
  path: string;
  focusKey?: string;
  section?: string;
};

export function domainContextFromStorage() {
  return {
    active_person_id:
      loadState<string>(STORAGE_KEYS.activePersonId) || "",
    active_background_id:
      loadState<string>(STORAGE_KEYS.activeBackgroundId) || "",
    active_application_project_id:
      loadState<string>(STORAGE_KEYS.activeApplicationProjectId) || "",
    active_story_id:
      loadState<string>(STORAGE_KEYS.activeStoryId) || "",
    active_project_id:
      loadState<string>(STORAGE_KEYS.activeProjectId) || "",
  };
}

export async function sendDomainCommand(
  transcript: string,
  history: AgentConversationMessage[],
  options: {
    confirmed?: boolean;
    source?: "voice" | "text";
    pending?: DomainAgentResponse | null;
  } = {},
): Promise<DomainAgentResponse> {
  return apiFetch<DomainAgentResponse>("/api/agent/domain", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      transcript,
      history: history.slice(-8),
      ...domainContextFromStorage(),
      pending_capability: options.pending?.capability?.name || null,
      pending_arguments: options.pending?.arguments || {},
      pending_resolved: options.pending?.resolved || {},
      confirmed: options.confirmed || false,
      source: options.source || "text",
    }),
  });
}

export function applyDomainResolved(
  resolved: Record<string, unknown>,
): void {
  const personId = resolved.person_id;
  const backgroundId = resolved.background_id;
  const storyId = resolved.story_id;
  const applicationProjectId = resolved.application_project_id;
  const projectId = resolved.project_id;
  const batchId = resolved.batch_id;
  if (typeof personId === "string" && personId) {
    saveState(STORAGE_KEYS.activePersonId, personId);
  }
  if (typeof backgroundId === "string" && backgroundId) {
    saveState(STORAGE_KEYS.activeBackgroundId, backgroundId);
  }
  if (typeof storyId === "string" && storyId) {
    saveState(STORAGE_KEYS.activeStoryId, storyId);
  }
  if (
    typeof applicationProjectId === "string" &&
    applicationProjectId
  ) {
    saveState(
      STORAGE_KEYS.activeApplicationProjectId,
      applicationProjectId,
    );
  }
  if (typeof projectId === "string" && projectId) {
    saveState(STORAGE_KEYS.activeProjectId, projectId);
  }
  if (typeof batchId === "string" && batchId) {
    saveState(STORAGE_KEYS.batchId, batchId);
  }
  window.dispatchEvent(new CustomEvent("gradpilot:workspace-changed"));
}

const PROFILE_PATCH_FOCUS: Record<string, string> = {
  "basic_profile.full_name": "full-name",
  "basic_profile.current_university": "current-university",
  "basic_profile.major": "major",
  "basic_profile.gpa": "gpa",
  "basic_profile.graduation_year": "graduation-year",
  "basic_profile.english_test_score": "english-score",
  "basic_profile.target_degree": "target-degree",
  "basic_profile.target_field": "target-field",
  "basic_profile.target_country": "target-country",
  motivation_summary: "motivation-text",
  career_goal: "career-goal",
  research_experiences: "research-experience",
  internships: "internship-experience",
  projects: "project-experience",
  activities_awards: "activities-awards",
};

function profilePatchFocus(
  response: DomainAgentResponse,
): string | undefined {
  const operations = response.arguments.operations;
  if (!Array.isArray(operations)) return undefined;
  for (const operation of operations) {
    if (!operation || typeof operation !== "object") continue;
    const path = (operation as Record<string, unknown>).path;
    if (typeof path !== "string") continue;
    const direct = PROFILE_PATCH_FOCUS[path];
    if (direct) return direct;
    const prefix = path.split(".")[0];
    const fallback = PROFILE_PATCH_FOCUS[prefix];
    if (fallback) return fallback;
  }
  return undefined;
}

function firstCandidateFocus(
  response: DomainAgentResponse,
  prefix: "background" | "application-project" | "story",
): string | undefined {
  const candidates = response.resolved.candidates;
  if (!Array.isArray(candidates)) return undefined;
  for (const candidate of candidates) {
    if (!candidate || typeof candidate !== "object") continue;
    const id = (candidate as Record<string, unknown>).id;
    if (typeof id === "string" && id) {
      return `${prefix}-${id}`;
    }
  }
  return undefined;
}

export function domainNavigationTarget(
  response: DomainAgentResponse,
): DomainNavigationTarget {
  const capability = response.capability?.name || "";
  if (capability === "background.patch") {
    return {
      path: "/profile",
      focusKey: profilePatchFocus(response) || "full-name",
    };
  }
  if (capability === "background.select") {
    return { path: "/profile", focusKey: "full-name" };
  }
  if (capability === "person.create" || capability === "person.select") {
    return {
      path: "/library",
      section: "background-source-form",
      focusKey: "workbench-new-person-name",
    };
  }
  if (capability === "application_project.create") {
    const backgroundMissing = !response.resolved.background_id;
    const candidateFocus = firstCandidateFocus(response, "background");
    return {
      path: "/library",
      section: backgroundMissing && !candidateFocus
        ? "background-source-form"
        : backgroundMissing
          ? undefined
          : "application-project-form",
      focusKey: backgroundMissing
        ? candidateFocus || "workbench-new-person-name"
        : "workbench-school",
    };
  }
  if (capability === "application_project.select") {
    const projectId = response.resolved.application_project_id;
    return {
      path: "/library",
      focusKey:
        typeof projectId === "string" && projectId
          ? `application-project-${projectId}`
          : "workbench-school",
    };
  }
  if (capability === "story.create") {
    if (!response.resolved.application_project_id) {
      const candidateFocus = firstCandidateFocus(
        response,
        "application-project",
      );
      if (candidateFocus) {
        return { path: "/library", focusKey: candidateFocus };
      }
    }
    return {
      path: "/library",
      section: "story-source-form",
      focusKey: "workbench-story-title",
    };
  }
  if (capability === "story.reply") {
    return { path: "/library", focusKey: "workbench-story-reply" };
  }
  if (capability === "story.select" || capability === "story.patch") {
    const storyId = response.resolved.story_id;
    return {
      path: "/library",
      focusKey:
        typeof storyId === "string" && storyId
          ? `story-${storyId}`
          : "workbench-story-title",
    };
  }
  if (capability === "essay_branch.create") {
    if (response.status === "executed") return { path: "/result" };
    const backgroundMissing = !response.resolved.background_id;
    const projectMissing = !response.resolved.application_project_id;
    const storyMissing =
      !response.resolved.story_id &&
      !response.arguments.story_instance_ids &&
      !response.arguments.story_titles;
    if (backgroundMissing) {
      const candidateFocus = firstCandidateFocus(response, "background");
      return {
        path: "/library",
        section: candidateFocus ? undefined : "background-source-form",
        focusKey: candidateFocus || "workbench-new-person-name",
      };
    }
    if (projectMissing) {
      const candidateFocus = firstCandidateFocus(
        response,
        "application-project",
      );
      return {
        path: "/library",
        section: candidateFocus ? undefined : "application-project-form",
        focusKey: candidateFocus || "workbench-school",
      };
    }
    if (storyMissing) {
      const candidateFocus = firstCandidateFocus(response, "story");
      return {
        path: "/library",
        section: candidateFocus ? undefined : "story-source-form",
        focusKey: candidateFocus || "workbench-story-project",
      };
    }
    return { path: "/library" };
  }
  if (capability.startsWith("project.")) {
    return {
      path: "/result",
      focusKey:
        capability === "project.draft"
          ? "project-revision-instruction"
          : undefined,
    };
  }
  if (capability === "batch.create") {
    return { path: "/batch", focusKey: "batch-tone" };
  }
  return { path: "/library" };
}

export function shouldUseDomainAgent(
  transcript: string,
  pathname: string,
): boolean {
  const text = transcript.replace(/\s+/g, "");
  if (
    /^(?:打开|进入|跳到|前往|去|确认|确定|取消|不要|不用|停止|重复|再说|没听清|没听懂|帮我|怎么办|下一项|上一项|跳过|撤销)/.test(
      text,
    )
  ) {
    return false;
  }
  if (
    /(?:创建|新建|新增|从头|做一篇|写一篇|来一篇)/.test(text) &&
    /(?:文书|个人陈述|动机信|ps|ml)/i.test(text) &&
    !/(?:修改|更新|重写)/.test(text)
  ) {
    return true;
  }
  if (
    /(?:新建|添加|上传|记录|挖掘|开始)(?:人物|背景|简历|项目|学校|故事)/.test(
      text,
    )
  ) {
    return false;
  }
  if (
    /^(?:提交|保存|执行)(?:新增|添加|新建|记录|开始)?(?:人物|背景|简历|项目|学校|故事)/.test(
      text,
    )
  ) {
    return false;
  }
  if (pathname === "/library") {
    if (
      /(?:分析|大纲|草稿|审核|重写|生成)/.test(text) &&
      /(?:文书|PS|ML|项目|当前)/i.test(text) &&
      !/生成全部/.test(text)
    ) {
      return true;
    }
    return (
      /(?:新建|创建|记录|绑定|挖掘|选择|切换|修改|删除|开始|继续|暂停|恢复).*(?:人物|背景|申请项目|学校项目|故事|文书项目|批量任务)/.test(
        text,
      ) ||
      /(?:人物|背景|简历|申请项目|学校项目|故事|文书项目|批量任务).*(?:新建|创建|记录|绑定|选择|切换|修改|删除|开始|继续|暂停|恢复)/.test(
        text,
      ) ||
      /(?:的|这份|那份).{0,12}(?:简历|背景)/.test(text)
    );
  }
  if (
    [
      "人物",
      "装配工作台",
      "申请项目",
      "装配链路",
      "背景实例",
      "故事实例",
      "文书项目",
      "实例库",
      "装配工作台",
      "批量任务",
      "选择背景",
      "选择故事",
      "继续上次",
      "修改经历",
      "修改项目",
    ].some((keyword) => text.includes(keyword))
  ) {
    return true;
  }
  return /(?:的|这份|那份).{0,12}(?:简历|背景)/.test(text);
}
