"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Icon from "@/components/icon";
import { useRouter } from "next/navigation";
import { ApiError, apiFetch, readableError } from "@/lib/api";
import { loadState, removeState, saveState, STORAGE_KEYS } from "@/lib/storage";
import type {
  AnalysisResponse,
  ProfileResponse,
  SessionSnapshot,
  StoryCards,
  StoryMessage,
  StoryResponse,
  StorySessionState,
} from "@/lib/types";

const emptyCards: StoryCards = {
  motivation: [],
  core_experience: [],
  contribution_impact: [],
  strengths: [],
  career_goal: [],
  program_fit: [],
};

const cardLabelMap: Record<keyof StoryCards, string> = {
  motivation: "申请动机",
  core_experience: "核心经历",
  contribution_impact: "贡献与影响",
  strengths: "能力优势",
  career_goal: "职业目标",
  program_fit: "项目匹配",
};

export default function StoryPage() {
  const router = useRouter();
  const startRequested = useRef(false);
  const chatBox = useRef<HTMLDivElement>(null);
  const [profile, setProfile] = useState<ProfileResponse | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [sessionId, setSessionId] = useState("");
  const [cards, setCards] = useState<StoryCards>(emptyCards);
  const [messages, setMessages] = useState<StoryMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [roundNo, setRoundNo] = useState(1);
  const [status, setStatus] = useState<"interviewing" | "ready">(
    "interviewing",
  );

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    const currentProfile = loadState<ProfileResponse>(STORAGE_KEYS.profile);
    const currentAnalysis = loadState<AnalysisResponse>(STORAGE_KEYS.analysis);
    setProfile(currentProfile);
    setAnalysis(currentAnalysis);

    if (
      !currentProfile?.profile_id ||
      !currentAnalysis?.analysis_id ||
      currentAnalysis.profile_id !== currentProfile.profile_id
    ) {
      setError("请先完成背景信息和目标项目分析。");
      return;
    }
    const profileId = currentProfile.profile_id;
    const analysisId = currentAnalysis.analysis_id;

    const saved = loadState<StorySessionState>(STORAGE_KEYS.storySession);
    if (
      saved?.profile_id === profileId &&
      saved.analysis_id === analysisId &&
      saved.session_id
    ) {
      const savedSessionId = saved.session_id;
      setSessionId(savedSessionId);
      setCards(saved.cards || emptyCards);
      setMessages(saved.messages || []);
      setRoundNo(saved.round_no || 1);
      setStatus(
        saved.status || (saved.round_no >= 4 ? "ready" : "interviewing"),
      );
      startRequested.current = true;

      async function reconcileSession() {
        setLoading(true);
        try {
          const snapshot = await apiFetch<SessionSnapshot>(
            `/api/session/${savedSessionId}`,
          );
          setCards(snapshot.cards);
          setMessages(snapshot.messages);
          setRoundNo(snapshot.round_no);
          setStatus(snapshot.status);
          saveState(STORAGE_KEYS.storySession, {
            session_id: snapshot.session_id,
            cards: snapshot.cards,
            messages: snapshot.messages,
            profile_id: snapshot.profile_id,
            analysis_id: snapshot.analysis_id,
            round_no: snapshot.round_no,
            status: snapshot.status,
          } satisfies StorySessionState);
        } catch (err) {
          if (err instanceof ApiError && err.status === 404) {
            removeState(STORAGE_KEYS.storySession);
            setSessionId("");
            setCards(emptyCards);
            setMessages([]);
            setRoundNo(1);
            setStatus("interviewing");
          }
          setError(readableError(err, "同步故事会话失败"));
        } finally {
          setLoading(false);
        }
      }
      void reconcileSession();
      return;
    }

    if (startRequested.current) return;
    startRequested.current = true;

    async function startSession() {
      setLoading(true);
      setError("");
      try {
        const result = await apiFetch<StoryResponse>("/api/story/start", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            profile_id: profileId,
            analysis_id: analysisId,
          }),
        });
        const initialMessages: StoryMessage[] = [
          { role: "assistant", content: result.assistant_message },
        ];
        setSessionId(result.session_id);
        setCards(result.cards);
        setMessages(initialMessages);
        setRoundNo(result.round_no);
        setStatus(result.status);
        saveState(STORAGE_KEYS.storySession, {
          session_id: result.session_id,
          cards: result.cards,
          messages: initialMessages,
          profile_id: result.profile_id,
          analysis_id: result.analysis_id,
          round_no: result.round_no,
          status: result.status,
        } satisfies StorySessionState);
      } catch (err) {
        setError(readableError(err, "故事会话启动失败"));
      } finally {
        setLoading(false);
      }
    }

    void startSession();
  }, []);
  /* eslint-enable react-hooks/set-state-in-effect */

  useEffect(() => {
    if (chatBox.current)
      chatBox.current.scrollTop = chatBox.current.scrollHeight;
  }, [messages, loading]);

  const cardEntries = useMemo(
    () =>
      (Object.keys(cardLabelMap) as Array<keyof StoryCards>).map((key) => ({
        key,
        label: cardLabelMap[key],
        values: cards[key] || [],
      })),
    [cards],
  );

  async function sendReply() {
    if (
      loading ||
      status === "ready" ||
      !input.trim() ||
      !sessionId ||
      !profile ||
      !analysis
    )
      return;
    const currentUserMessage = input.trim();
    const previousMessages = messages;
    const updatedMessages: StoryMessage[] = [
      ...messages,
      { role: "user", content: currentUserMessage },
    ];

    setLoading(true);
    setError("");
    setMessages(updatedMessages);
    setInput("");
    try {
      const result = await apiFetch<StoryResponse>("/api/story/reply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          user_message: currentUserMessage,
        }),
      });
      const finalMessages: StoryMessage[] = [
        ...updatedMessages,
        { role: "assistant", content: result.assistant_message },
      ];
      setMessages(finalMessages);
      setCards(result.cards);
      setRoundNo(result.round_no);
      setStatus(result.status);
      saveState(STORAGE_KEYS.storySession, {
        session_id: result.session_id,
        cards: result.cards,
        messages: finalMessages,
        profile_id: profile.profile_id,
        analysis_id: analysis.analysis_id,
        round_no: result.round_no,
        status: result.status,
      } satisfies StorySessionState);
    } catch (err) {
      setMessages(previousMessages);
      setInput(currentUserMessage);
      setError(readableError(err, "发送回答失败"));
    } finally {
      setLoading(false);
    }
  }

  const completed = status === "ready";

  return (
    <main className="section">
      <div className="container">
        <div className="page-intro">
          <div className="kicker">MAKE IT PERSONAL</div>
          <h1 className="section-title">每个故事，都藏在细节里。</h1>
          <p className="muted">
            每轮 3
            个个性化短问题。每题一句话或关键词即可，系统会自动提炼成文书素材。
          </p>
          <div
            className="round-progress"
            aria-label={`访谈进度：${completed ? "已完成" : `第 ${roundNo} 轮，共 3 轮`}`}
          >
            {[1, 2, 3].map((n) => (
              <span
                key={n}
                className={completed || n <= roundNo ? "filled" : ""}
              />
            ))}
            {completed ? "访谈完成" : `第 ${roundNo} / 3 轮`}
          </div>
          {error ? (
            <p className="notice" role="alert">
              {error}
            </p>
          ) : null}
        </div>

        <div className="chat-layout" style={{ marginTop: 16 }}>
          <div className="card chat-panel">
            <div className="chat-toolbar">
              <h2>与 GradPilot 对话</h2>
              <span className="badge">
                {completed ? "故事已整理" : "引导式访谈"}
              </span>
            </div>
            <div
              className="chat-box"
              ref={chatBox}
              role="log"
              aria-label="故事访谈记录"
              aria-live="polite"
              aria-busy={loading}
            >
              {messages.map((message, index) => (
                <div
                  key={`${message.role}-${index}`}
                  className={`message ${message.role}`}
                >
                  <span className="message-author">
                    {message.role === "assistant" ? "GRADPILOT" : "你"}
                  </span>
                  {message.content}
                </div>
              ))}
              {loading ? (
                <p className="busy-status" role="status">
                  <span className="spinner" />
                  {messages.length
                    ? "正在梳理你的回答…"
                    : "正在准备你的访谈问题…"}
                </p>
              ) : null}
              {!messages.length && !loading ? (
                <div className="empty-state">
                  <Icon name="chat" size={30} />
                  <h3>准备好分享你的经历了吗？</h3>
                  <p>完成背景与项目分析后，AI 将提出与你相关的问题。</p>
                  {error && profile && analysis ? (
                    <button
                      className="btn-secondary"
                      type="button"
                      onClick={() => window.location.reload()}
                    >
                      重新连接访谈
                    </button>
                  ) : null}
                </div>
              ) : null}
            </div>
            <div className="chat-input">
              <label className="sr-only" htmlFor="story-answer">
                回答当前问题
              </label>
              <textarea
                id="story-answer"
                maxLength={4000}
                onKeyDown={(event) => {
                  if (
                    (event.ctrlKey || event.metaKey) &&
                    event.key === "Enter" &&
                    !event.nativeEvent.isComposing
                  ) {
                    event.preventDefault();
                    void sendReply();
                  }
                }}
                value={input}
                onChange={(event) => setInput(event.target.value)}
                disabled={completed || loading}
                placeholder="可直接短答：按 1/2/3 回答，每题一句话或关键词即可。"
              />
            </div>
            <div className="composer-hint">
              Ctrl / ⌘ + Enter 发送 · {input.length} / 4000 字符
            </div>
            {completed ? (
              <p className="notice success">已完成 3 轮提问，可以生成结果。</p>
            ) : null}
            <div className="form-footer">
              <button
                className="btn-secondary"
                type="button"
                onClick={() => router.push("/program")}
              >
                返回上一页
              </button>
              <button
                className="btn-secondary"
                type="button"
                onClick={() => router.push("/result")}
                disabled={!completed}
              >
                去生成结果
              </button>
              <button
                className="btn"
                type="button"
                onClick={sendReply}
                disabled={completed || loading || !input.trim() || !sessionId}
              >
                {loading ? "发送中..." : "发送回答"}
              </button>
            </div>
          </div>

          <div className="cards-stack">
            <h2 className="material-heading">
              <Icon name="book" /> 你的故事素材库
            </h2>
            {cardEntries.map(({ key, label, values }) => (
              <div key={key} className="mini-card">
                <h3>{label}</h3>
                <ul className="list">
                  {values.length ? (
                    values.map((item, index) => (
                      <li key={`${item}-${index}`}>{item}</li>
                    ))
                  ) : (
                    <li className="muted">回答后会在这里整理相关素材。</li>
                  )}
                </ul>
              </div>
            ))}
          </div>
        </div>
      </div>
    </main>
  );
}
