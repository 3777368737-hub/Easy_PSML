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
  } = {},
): Promise<DomainAgentResponse> {
  return apiFetch<DomainAgentResponse>("/api/agent/domain", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      transcript,
      history: history.slice(-8),
      ...domainContextFromStorage(),
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
