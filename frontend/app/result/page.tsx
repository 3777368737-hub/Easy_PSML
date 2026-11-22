"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import Icon from "@/components/icon";
import DocumentExportControls from "@/components/document-export-controls";
import { useRouter } from "next/navigation";
import { apiFetch, readableError } from "@/lib/api";
import { loadState, removeState, saveState, STORAGE_KEYS } from "@/lib/storage";
import type {
  AnalysisResponse,
  ArtifactVersion,
  EssayProject,
  HistoryItem,
  ProfileResponse,
  ProgramFormState,
  SessionSnapshot,
  StorySessionState,
} from "@/lib/types";

const tabs = ["大纲", "草稿"] as const;

function cacheSnapshotContext(next: SessionSnapshot) {
  saveState(STORAGE_KEYS.profile, {
    profile_id: next.profile_id,
    profile: next.profile,
  } satisfies ProfileResponse);
  saveState(STORAGE_KEYS.analysis, {
    analysis_id: next.analysis_id,
    profile_id: next.profile_id,
    program: next.program,
    analysis: next.analysis,
  } satisfies AnalysisResponse);
  saveState(STORAGE_KEYS.programForm, {
    school_name: next.program.school_name,
    program_name: next.program.program_name,
    essay_type: next.program.essay_type,
    word_limit: String(next.program.word_limit),
    prompt_text: next.program.prompt_text,
    program_details: next.program.program_details || "",
  } satisfies ProgramFormState);
}

export default function ResultPage() {
  const router = useRouter();
  const [session, setSession] = useState<StorySessionState | null>(null);
  const [snapshot, setSnapshot] = useState<SessionSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<(typeof tabs)[number]>("大纲");
  const [revisionInstruction, setRevisionInstruction] = useState("");
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [copyStatus, setCopyStatus] = useState("");
  const [selectedArtifact, setSelectedArtifact] =
    useState<ArtifactVersion | null>(null);
  const [activeProject, setActiveProject] = useState<EssayProject | null>(
    null,
  );

  const fetchSnapshot = useCallback(
    async (sessionId: string): Promise<SessionSnapshot | null> => {
      setLoading(true);
      setError("");
      try {
        const next = await apiFetch<SessionSnapshot>(
          `/api/session/${sessionId}`,
        );
        setSnapshot(next);
        cacheSnapshotContext(next);
        saveState(STORAGE_KEYS.resultSnapshot, next);
        return next;
      } catch (err) {
        setError(readableError(err, "加载会话信息失败"));
        return null;
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  const refreshHistory = useCallback(async () => {
    try {
      const items = await apiFetch<HistoryItem[]>("/api/history");
      setHistory(items);
    } catch (err) {
      setError((current) => current || readableError(err, "加载历史记录失败"));
    }
  }, []);

  const fetchActiveProject = useCallback(async (projectId: string) => {
    setLoading(true);
    setError("");
    try {
      const project = await apiFetch<EssayProject>(
        `/api/essay-projects/${projectId}`,
      );
      setActiveProject(project);
      saveState(STORAGE_KEYS.activeProjectId, project.id);
      return project;
    } catch (err) {
      setError(readableError(err, "加载文书项目失败"));
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const activeProjectId = loadState<string>(STORAGE_KEYS.activeProjectId);
    if (activeProjectId) {
      void fetchActiveProject(activeProjectId);
      void refreshHistory();
      removeState(STORAGE_KEYS.legacyHistory);
      return;
    }
    const savedSession = loadState<StorySessionState>(
      STORAGE_KEYS.storySession,
    );
    setSession(savedSession);
    if (savedSession?.session_id) {
      void fetchSnapshot(savedSession.session_id);
    } else {
      setError("还没有可用的故事会话，请先完成故事挖掘。");
    }
    void refreshHistory();
    removeState(STORAGE_KEYS.legacyHistory);
  }, [fetchActiveProject, fetchSnapshot, refreshHistory]);

  async function generateOutline() {
    if (!session?.session_id || snapshot?.status !== "ready") return;
    setLoading(true);
    setError("");
    try {
      await apiFetch("/api/essay/outline", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: session.session_id }),
      });
      await fetchSnapshot(session.session_id);
      await refreshHistory();
      setSelectedArtifact(null);
      setActiveTab("大纲");
    } catch (err) {
      setError(readableError(err, "生成大纲失败"));
    } finally {
      setLoading(false);
    }
  }

  async function generateDraft(rewrite = false) {
    if (!session?.session_id || !snapshot) return;
    if (rewrite && !revisionInstruction.trim()) {
      setError("请先输入修改意见。");
      return;
    }

    setLoading(true);
    setError("");
    try {
      await apiFetch("/api/essay/draft", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: session.session_id,
          tone: "balanced",
          target_length: snapshot.program.word_limit,
          revision_instruction: rewrite ? revisionInstruction.trim() : "",
        }),
      });
      await fetchSnapshot(session.session_id);
      await refreshHistory();
      setSelectedArtifact(null);
      setRevisionInstruction("");
      setActiveTab("草稿");
    } catch (err) {
      setError(readableError(err, "生成草稿失败"));
    } finally {
      setLoading(false);
    }
  }

  async function runReview() {
    if (!session?.session_id || !snapshot?.draft) return;
    setLoading(true);
    setError("");
    try {
      await apiFetch("/api/review/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: session.session_id }),
      });
      await fetchSnapshot(session.session_id);
      setActiveTab("草稿");
    } catch (err) {
      setError(readableError(err, "审核草稿失败"));
    } finally {
      setLoading(false);
    }
  }

  async function runProjectAction(
    action: "analyze" | "outline" | "draft" | "review",
    rewrite = false,
  ) {
    if (!activeProject) return;
    if (rewrite && !revisionInstruction.trim()) {
      setError("请先输入修改意见。");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const project = await apiFetch<EssayProject>(
        `/api/essay-projects/${activeProject.id}/${action}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: action === "draft"
            ? JSON.stringify({
                tone: "balanced",
                target_length: activeProject.program.word_limit,
                revision_instruction: rewrite
                  ? revisionInstruction.trim()
                  : "",
              })
            : undefined,
        },
      );
      setActiveProject(project);
      if (rewrite) setRevisionInstruction("");
    } catch (err) {
      setError(readableError(err, "文书项目操作失败"));
    } finally {
      setLoading(false);
    }
  }

  async function loadRecord(item: HistoryItem) {
    setLoading(true);
    setError("");
    try {
      setActiveProject(null);
      removeState(STORAGE_KEYS.activeProjectId);
      removeState(STORAGE_KEYS.activeStoryId);
      const next = await apiFetch<SessionSnapshot>(
        `/api/session/${item.session_id}`,
      );
      setSession({
        session_id: next.session_id,
        cards: next.cards,
        messages: next.messages,
        profile_id: next.profile_id,
        analysis_id: next.analysis_id,
        round_no: next.round_no,
        status: next.status,
      });
      setSnapshot(next);
      cacheSnapshotContext(next);
      saveState(STORAGE_KEYS.storySession, {
        session_id: next.session_id,
        cards: next.cards,
        messages: next.messages,
        profile_id: next.profile_id,
        analysis_id: next.analysis_id,
        round_no: next.round_no,
        status: next.status,
      } satisfies StorySessionState);
      setSelectedArtifact(null);
      setActiveTab(next.draft ? "草稿" : "大纲");
    } catch (err) {
      setError(readableError(err, "加载历史记录失败"));
    } finally {
      setLoading(false);
    }
  }

  async function clearHistory() {
    const agentAlreadyConfirmed =
      document.documentElement.dataset.agentExecuting === "history.clear";
    if (
      !agentAlreadyConfirmed &&
      !window.confirm("确认清空当前浏览器的全部申请记录？此操作不可恢复。")
    )
      return;
    setLoading(true);
    try {
      await apiFetch("/api/history", { method: "DELETE" });
      setHistory([]);
      setSnapshot(null);
      setSession(null);
      removeState(STORAGE_KEYS.storySession);
      removeState(STORAGE_KEYS.resultSnapshot);
      removeState(STORAGE_KEYS.profile);
      removeState(STORAGE_KEYS.profileDraft);
      removeState(STORAGE_KEYS.analysis);
      removeState(STORAGE_KEYS.programForm);
      removeState(STORAGE_KEYS.batchForm);
      removeState(STORAGE_KEYS.batchSubmission);
      removeState(STORAGE_KEYS.batchId);
      removeState(STORAGE_KEYS.activeProjectId);
      removeState(STORAGE_KEYS.activeStoryId);
      removeState(STORAGE_KEYS.activePersonId);
      removeState(STORAGE_KEYS.activeBackgroundId);
      setActiveProject(null);
    } catch (err) {
      setError(readableError(err, "清空历史失败"));
    } finally {
      setLoading(false);
    }
  }

  const visibleOutline = selectedArtifact
    ? selectedArtifact.outline
    : snapshot?.outline;
  const visibleDraft = selectedArtifact
    ? selectedArtifact.draft
    : snapshot?.draft;
  async function copyDraft() {
    if (!visibleDraft) return;
    try {
      await navigator.clipboard.writeText(visibleDraft);
      setCopyStatus("草稿已复制。");
    } catch {
      const textarea = document.createElement("textarea");
      textarea.value = visibleDraft;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      const copied = document.execCommand("copy");
      textarea.remove();
      setCopyStatus(
        copied
          ? "草稿已复制。"
          : "复制失败，请使用“下载草稿”保存内容。",
      );
    }
  }
  const wordCount =
    visibleDraft?.trim().split(/\s+/).filter(Boolean).length || 0;
  const hasHistory = useMemo(() => history.length > 0, [history]);
  const canGenerate = snapshot?.status === "ready";

  async function copyProjectDraft() {
    if (!activeProject?.draft) return;
    try {
      await navigator.clipboard.writeText(activeProject.draft);
      setCopyStatus("草稿已复制。");
    } catch {
      setCopyStatus("复制失败，请下载草稿。");
    }
  }

  if (activeProject) {
    const projectWordCount =
      activeProject.draft?.trim().split(/\s+/).filter(Boolean).length || 0;
    return (
      <main className="section">
        <div className="container">
          <div className="card">
            <div className="kicker">INSTANCE WRITING PROJECT</div>
            <h1 className="section-title">
              {activeProject.program.school_name} ·{" "}
              {activeProject.program.program_name}
            </h1>
            <p className="muted">
              {activeProject.program.essay_type} · 目标{" "}
              {activeProject.program.word_limit} 词 · 已引用{" "}
              {activeProject.story_instance_ids.length} 个故事实例
            </p>
            {activeProject.status === "stale" ? (
              <p className="notice">
                背景或故事素材已更新，请重新执行项目分析和后续生成。
              </p>
            ) : null}
            {error ? <p className="notice" role="alert">{error}</p> : null}
            {loading ? (
              <p className="busy-status" role="status">
                <span className="spinner" /> 正在处理文书项目…
              </p>
            ) : null}
            <div className="actions">
              <button
                className="btn-secondary"
                type="button"
                data-agent-capability="project.analyze"
                disabled={loading}
                onClick={() => void runProjectAction("analyze")}
              >
                项目分析
              </button>
              <button
                className="btn-secondary"
                type="button"
                data-agent-capability="project.outline"
                disabled={loading}
                onClick={() => void runProjectAction("outline")}
              >
                生成中文大纲
              </button>
              <button
                className="btn"
                type="button"
                data-agent-capability="project.draft"
                disabled={loading}
                onClick={() => void runProjectAction("draft")}
              >
                生成英文草稿
              </button>
              <button
                className="btn-secondary"
                type="button"
                data-agent-capability="project.review"
                disabled={loading || !activeProject.draft}
                onClick={() => void runProjectAction("review")}
              >
                审核草稿
              </button>
            </div>
          </div>

          {activeProject.analysis ? (
            <div className="card" style={{ marginTop: 16 }}>
              <h2 className="section-title">项目分析</h2>
              <div className="analysis-grid">
                <div className="mini-card">
                  <h3>项目关注点</h3>
                  <ul className="list">
                    {activeProject.analysis.program_focus.map((item, index) => (
                      <li key={`${item}-${index}`}>{item}</li>
                    ))}
                  </ul>
                </div>
                <div className="mini-card">
                  <h3>匹配优势</h3>
                  <ul className="list">
                    {activeProject.analysis.matched_strengths.map(
                      (item, index) => (
                        <li key={`${item}-${index}`}>{item}</li>
                      ),
                    )}
                  </ul>
                </div>
                <div className="mini-card">
                  <h3>写作建议</h3>
                  <ul className="list">
                    {activeProject.analysis.writing_suggestions.map(
                      (item, index) => (
                        <li key={`${item}-${index}`}>{item}</li>
                      ),
                    )}
                  </ul>
                </div>
              </div>
            </div>
          ) : null}

          {activeProject.outline ? (
            <div className="card" style={{ marginTop: 16 }}>
              <h2 className="section-title">{activeProject.outline.title}</h2>
              {activeProject.outline.paragraphs.map((paragraph, index) => (
                <div className="mini-card" key={`${paragraph.heading}-${index}`}>
                  <h3>{paragraph.heading}</h3>
                  <p><strong>目标：</strong>{paragraph.goal}</p>
                  <p><strong>核心内容：</strong>{paragraph.key_content}</p>
                  <p>
                    <strong>使用经历：</strong>
                    {paragraph.use_this_experience}
                  </p>
                  <p>
                    <strong>重点突出：</strong>
                    {paragraph.what_to_highlight}
                  </p>
                </div>
              ))}
            </div>
          ) : null}

          <div className="card" style={{ marginTop: 16 }}>
            <h2 className="section-title">英文草稿</h2>
            {activeProject.draft ? (
              <>
                <div className="document-meta">
                  <span>APPLICATION ESSAY</span>
                  <span>
                    {projectWordCount} 词 / 目标{" "}
                    {activeProject.program.word_limit} 词
                  </span>
                </div>
                <pre className="code-block">{activeProject.draft}</pre>
                <div className="actions">
                  <DocumentExportControls
                    key={`project-export-${activeProject.id}`}
                    endpoint={`/api/essay-projects/${activeProject.id}/export`}
                    disabled={loading}
                  />
                  <button
                    className="btn-secondary"
                    type="button"
                    data-agent-capability="essay.copy"
                    onClick={() => void copyProjectDraft()}
                  >
                    复制草稿
                  </button>
                </div>
              </>
            ) : (
              <p className="muted">尚未生成草稿。</p>
            )}
            <p className="muted" role="status">{copyStatus}</p>
            <div className="field revision-panel">
              <label htmlFor="project-revision-instruction">
                对草稿的修改意见
              </label>
              <textarea
                id="project-revision-instruction"
                value={revisionInstruction}
                onChange={(event) =>
                  setRevisionInstruction(event.target.value)
                }
                disabled={loading || !activeProject.draft}
                maxLength={4000}
                placeholder="例如：压缩第二段，并加强项目匹配。"
              />
            </div>
            <button
              className="btn-secondary"
              type="button"
              data-agent-capability="project.rewrite"
              disabled={
                loading ||
                !activeProject.draft ||
                !revisionInstruction.trim()
              }
              onClick={() => void runProjectAction("draft", true)}
            >
              按意见重写草稿
            </button>
          </div>

          {activeProject.review ? (
            <div className="card" style={{ marginTop: 16 }}>
              <h2 className="section-title">草稿审核</h2>
              <p><strong>优势：</strong>{activeProject.review.strengths.join("；")}</p>
              <p><strong>问题：</strong>{activeProject.review.weaknesses.join("；")}</p>
              <p>
                <strong>调整建议：</strong>
                {activeProject.review.adaptation_tip}
              </p>
            </div>
          ) : null}

          <div className="form-footer" style={{ marginTop: 16 }}>
            <button
              className="btn-secondary"
              type="button"
              data-agent-capability="app.navigate"
              data-agent-arg-path="/library"
              onClick={() => router.push("/library")}
            >
              返回装配工作台
            </button>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="section">
      <div className="container">
        <div className="card">
          <div className="kicker">YOUR WRITING STUDIO</div>
          <h1 className="section-title">让故事，成为你的申请文书。</h1>
          {snapshot ? (
            <p className="muted">
              {snapshot.program.school_name} · {snapshot.program.program_name} ·{" "}
              {snapshot.program.essay_type} · 目标 {snapshot.program.word_limit}{" "}
              词
            </p>
          ) : (
            <p className="muted">先生成中文大纲，再生成英文草稿。</p>
          )}
          {snapshot?.status === "interviewing" ? (
            <p className="notice">请先完成三轮故事挖掘，再生成大纲和草稿。</p>
          ) : null}
          {error ? (
            <p className="notice" role="alert">
              {error}
            </p>
          ) : null}
          {loading ? (
            <p className="busy-status" role="status">
              <span className="spinner" />
              正在处理，请稍候。完成后内容会自动更新。
            </p>
          ) : null}
          <div className="actions">
            <button
              className="btn-secondary"
              type="button"
              data-agent-capability="essay.outline"
              onClick={generateOutline}
              disabled={loading || !canGenerate}
            >
              生成中文大纲
            </button>
            <button
              className="btn"
              type="button"
              data-agent-capability="essay.draft"
              onClick={() => generateDraft(false)}
              disabled={loading || !canGenerate}
            >
              {loading ? "处理中..." : "生成英文草稿"}
            </button>
          </div>
        </div>

        <div className="card" style={{ marginTop: 16 }}>
          <div className="document-toolbar">
            <div className="tabs" role="group" aria-label="切换文书内容">
              {tabs.map((tab) => (
                <button
                  key={tab}
                  type="button"
                  className={`tab ${activeTab === tab ? "active" : ""}`}
                  aria-pressed={activeTab === tab}
                  data-agent-capability="result.switch_tab"
                  data-agent-arg-tab={tab === "大纲" ? "outline" : "draft"}
                  onClick={() => {
                    setActiveTab(tab);
                    setCopyStatus("");
                  }}
                >
                  {tab === "大纲" ? "中文大纲" : "英文草稿"}
                </button>
              ))}
            </div>
            <span className="badge">
              {selectedArtifact
                ? `历史版本 v${selectedArtifact.version_no}`
                : "当前版本"}
            </span>
          </div>

          {selectedArtifact ? (
            <p className="notice success">
              正在查看历史版本 v{selectedArtifact.version_no}。{" "}
              <button
                type="button"
                className="btn-secondary"
                data-agent-capability="result.restore_current"
                onClick={() => {
                  setSelectedArtifact(null);
                  setCopyStatus("");
                }}
              >
                返回当前版本
              </button>
            </p>
          ) : null}
          {!snapshot && !loading ? (
            <div className="empty-state">
              <span className="icon-tile">
                <Icon name="file" />
              </span>
              <h3>你的文书将从这里开始</h3>
              <p>完成故事挖掘后，即可把真实经历整理成大纲和草稿。</p>
              <Link href="/story" className="btn-secondary">
                前往故事挖掘
              </Link>
            </div>
          ) : null}
          {snapshot && activeTab === "大纲" && !visibleOutline ? (
            <div className="empty-state">
              <h3>先搭建叙事结构</h3>
              <p>
                {selectedArtifact
                  ? "此历史版本仅包含英文草稿，请切换到英文草稿或返回当前版本。"
                  : "点击上方“生成中文大纲”，梳理段落目标、核心经历与重点。"}
              </p>
            </div>
          ) : null}

          {activeTab === "大纲" && visibleOutline ? (
            <div>
              <h3>{visibleOutline.title || "文书大纲"}</h3>
              {visibleOutline.paragraphs.map((paragraph, index) => (
                <div
                  key={`${paragraph.heading}-${index}`}
                  className="mini-card"
                  style={{ marginBottom: 12 }}
                >
                  <h4>{paragraph.heading}</h4>
                  <p>
                    <strong>目标：</strong>
                    {paragraph.goal}
                  </p>
                  <p>
                    <strong>核心内容：</strong>
                    {paragraph.key_content}
                  </p>
                  <p>
                    <strong>可使用经历：</strong>
                    {paragraph.use_this_experience}
                  </p>
                  <p>
                    <strong>重点突出：</strong>
                    {paragraph.what_to_highlight}
                  </p>
                </div>
              ))}
            </div>
          ) : null}

          {activeTab === "草稿" ? (
            <div>
              {visibleDraft ? (
                <>
                  <div className="document-meta">
                    <span>PERSONAL APPLICATION ESSAY</span>
                    <span>
                      {wordCount} 词
                      {snapshot
                        ? ` / 目标 ${snapshot.program.word_limit} 词`
                        : ""}
                    </span>
                  </div>
                  <pre className="code-block">{visibleDraft}</pre>
                  <DocumentExportControls
                    key={`session-export-${snapshot?.session_id || "current"}-${
                      selectedArtifact?.id || "current"
                    }`}
                    endpoint={`/api/session/${snapshot?.session_id}/export`}
                    artifactVersionId={
                      selectedArtifact?.draft ? selectedArtifact.id : undefined
                    }
                    disabled={loading}
                  />
                </>
              ) : (
                <p className="muted">尚未生成草稿。</p>
              )}
              {visibleDraft ? (
                <div className="actions">
                  <button
                    className="btn-secondary"
                    type="button"
                    data-agent-capability="essay.copy"
                    onClick={copyDraft}
                  >
                    复制草稿
                  </button>
                  <button
                    className="btn-secondary"
                    type="button"
                    data-agent-capability="essay.review"
                    onClick={runReview}
                    disabled={loading || !!selectedArtifact}
                  >
                    审核当前草稿
                  </button>
                </div>
              ) : null}
              <p className="muted" role="status">
                {copyStatus}
              </p>
              <div className="field revision-panel">
                <label htmlFor="revision-instruction">对草稿的修改意见</label>
                <textarea
                  id="revision-instruction"
                  maxLength={4000}
                  disabled={loading || !!selectedArtifact || !snapshot?.draft}
                  value={revisionInstruction}
                  onChange={(event) =>
                    setRevisionInstruction(event.target.value)
                  }
                  placeholder="例如：加强开头故事感，突出产品思维，并压缩第二段。"
                />
              </div>
              <div className="form-footer">
                <button
                  className="btn-secondary"
                  type="button"
                  data-agent-capability="essay.rewrite"
                  onClick={() => generateDraft(true)}
                  disabled={
                    loading ||
                    !!selectedArtifact ||
                    !snapshot?.draft ||
                    !revisionInstruction.trim()
                  }
                >
                  按意见重写草稿
                </button>
              </div>
              {snapshot?.review ? (
                <div className="mini-card">
                  <h3>草稿审核</h3>
                  <p>
                    <strong>优势：</strong>
                    {snapshot.review.strengths.join("；")}
                  </p>
                  <p>
                    <strong>问题：</strong>
                    {snapshot.review.weaknesses.join("；")}
                  </p>
                  <p>
                    <strong>模板化表达：</strong>
                    {snapshot.review.template_like_phrases.join("；") ||
                      "未发现明显问题"}
                  </p>
                  <p>
                    <strong>建议补充：</strong>
                    {snapshot.review.suggested_details_to_add.join("；")}
                  </p>
                  <p>
                    <strong>调整建议：</strong>
                    {snapshot.review.adaptation_tip}
                  </p>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>

        {snapshot?.versions.length ? (
          <div className="card" style={{ marginTop: 16 }}>
            <h2 className="section-title">当前会话版本</h2>
            <div className="cards-stack">
              {snapshot.versions.map((version) => (
                <div key={version.id} className="mini-card">
                  <div className="version-row">
                    <span>
                      {version.artifact_type === "outline" ? "大纲" : "草稿"} v
                      {version.version_no} ·{" "}
                      {new Date(version.created_at).toLocaleString("zh-CN")}
                    </span>
                    <button
                      className="btn-secondary"
                      type="button"
                      data-agent-capability="result.load_version"
                      data-agent-arg-version-id={version.id}
                      onClick={() => {
                        setSelectedArtifact(version);
                        setCopyStatus("");
                        setActiveTab(
                          version.artifact_type === "outline" ? "大纲" : "草稿",
                        );
                      }}
                    >
                      查看此版本
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        <div className="card" style={{ marginTop: 16 }}>
          <div className="history-heading">
            <h2 style={{ margin: 0 }}>历史记录</h2>
            {hasHistory ? (
              <button
                className="btn-secondary"
                type="button"
                data-agent-capability="history.clear"
                onClick={clearHistory}
                disabled={loading}
              >
                清空全部历史
              </button>
            ) : null}
          </div>
          {!hasHistory ? (
            <p className="muted">还没有历史记录。完成故事挖掘后会自动保存。</p>
          ) : null}
          {history.map((item) => (
            <div
              key={item.session_id}
              className="mini-card"
              style={{ marginTop: 12 }}
            >
              <p style={{ margin: 0, fontWeight: 700 }}>{item.program_label}</p>
              <p className="muted" style={{ margin: "6px 0 10px" }}>
                {item.applicant} ·{" "}
                {item.status === "ready"
                  ? "可生成"
                  : `第 ${item.round_no}/3 轮`}{" "}
                · {new Date(item.updated_at).toLocaleString("zh-CN")}
              </p>
              {item.draft_preview ? (
                <p className="muted">{item.draft_preview}...</p>
              ) : null}
              <button
                className="btn-secondary"
                type="button"
                data-agent-capability="history.load"
                data-agent-arg-session-id={item.session_id}
                onClick={() => loadRecord(item)}
                disabled={loading}
              >
                加载这次记录
              </button>
            </div>
          ))}
        </div>

        <div className="form-footer" style={{ marginTop: 16 }}>
          <button
            className="btn-secondary"
            type="button"
            data-agent-capability="app.navigate"
            data-agent-arg-path="/story"
            onClick={() => router.push("/story")}
          >
            返回故事挖掘
          </button>
        </div>
      </div>
    </main>
  );
}
