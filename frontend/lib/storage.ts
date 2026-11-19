export const STORAGE_KEYS = {
  profileDraft: "gradpilot_profile_draft",
  profile: "gradpilot_profile",
  programForm: "gradpilot_program_form",
  analysis: "gradpilot_analysis",
  storySession: "gradpilot_story_session",
  resultSnapshot: "gradpilot_result_snapshot",
  legacyHistory: "gradpilot_history",
} as const;

export function saveState(key: string, value: unknown): boolean {
  if (typeof window === "undefined") return false;
  try {
    localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

export function loadState<T>(key: string): T | null {
  if (typeof window === "undefined") return null;
  let raw: string | null;
  try {
    raw = localStorage.getItem(key);
  } catch {
    return null;
  }
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    try {
      localStorage.removeItem(key);
    } catch {
      // Ignore storage cleanup failures.
    }
    return null;
  }
}

export function removeState(key: string): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.removeItem(key);
  } catch {
    // Storage can be unavailable in restricted browser contexts.
  }
}

export function clearDownstreamState(): void {
  removeState(STORAGE_KEYS.analysis);
  removeState(STORAGE_KEYS.programForm);
  removeState(STORAGE_KEYS.storySession);
  removeState(STORAGE_KEYS.resultSnapshot);
}
