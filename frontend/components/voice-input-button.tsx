"use client";

import Icon from "@/components/icon";
import { ApiError, apiFetch, apiStreamFetch, readableError } from "@/lib/api";
import {
  RealtimeVoiceSession,
  type RealtimeVoiceEvent,
} from "@/lib/realtime-voice";
import {
  agentHistoryForRequest,
  capturePageContext,
  consumeAgentStream,
  executeAgentCapability,
  executeAgentUiActions,
  focusInitialVoiceControl,
  restorePendingAgentFocus,
  type AgentStreamEvent,
  type AgentActionCommitResponse,
  type AgentCommandResponse,
  type AgentPendingAction,
} from "@/lib/voice-agent";
import {
  applyDomainResolved,
  sendDomainCommand,
  shouldUseDomainAgent,
  type DomainAgentResponse,
} from "@/lib/domain-agent";
import { loadState, saveState, STORAGE_KEYS } from "@/lib/storage";
import { usePathname, useRouter } from "next/navigation";
import type {
  CSSProperties,
  FormEvent,
  PointerEvent as ReactPointerEvent,
} from "react";
import { useEffect, useRef, useState } from "react";

type VoiceState = "idle" | "requesting" | "listening" | "uploading" | "error";
type VoiceButtonPosition = { x: number; y: number };
type DragGesture = {
  pointerId: number;
  startX: number;
  startY: number;
  originX: number;
  originY: number;
  moved: boolean;
};
type AgentLogMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
};
type LiveUtterance = {
  sentenceId: number;
  logId: string;
  text: string;
};

const BAR_PROFILE = [
  0.32, 0.46, 0.62, 0.8, 1, 0.8, 0.62, 0.46, 0.32,
] as const;
const DRAG_MARGIN = 8;
const DRAG_THRESHOLD = 4;
const PAGE_LABELS: Record<string, string> = {
  "/": "工作台",
  "/profile": "背景资料",
  "/program": "项目分析",
  "/story": "故事访谈",
  "/result": "文书编辑",
  "/batch": "批量生成",
  "/library": "申请项目",
};

function clampPosition(
  position: VoiceButtonPosition,
  width: number,
  height: number,
): VoiceButtonPosition {
  const maxX = Math.max(DRAG_MARGIN, window.innerWidth - width - DRAG_MARGIN);
  const maxY = Math.max(DRAG_MARGIN, window.innerHeight - height - DRAG_MARGIN);
  return {
    x: Math.min(maxX, Math.max(DRAG_MARGIN, position.x)),
    y: Math.min(maxY, Math.max(DRAG_MARGIN, position.y)),
  };
}

function colorForLevel(level: number): string {
  if (level < 0.36) return "#76dca4";
  if (level < 0.5) return "#b9e56f";
  if (level < 0.64) return "#f0d256";
  if (level < 0.8) return "#f2a052";
  return "#ef6b60";
}

function createLogId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `agent-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

type VoiceInputButtonProps = {
  onLevelChange?: (level: number) => void;
  onListeningChange?: (listening: boolean) => void;
};

export default function VoiceInputButton({
  onLevelChange,
  onListeningChange,
}: VoiceInputButtonProps) {
  const router = useRouter();
  const pathname = usePathname()?.replace(/\/$/, "") || "/";
  const dragHandleRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const recordButtonRef = useRef<HTMLButtonElement>(null);
  const cleanupRef = useRef<(() => void) | null>(null);
  const realtimeSessionRef = useRef<RealtimeVoiceSession | null>(null);
  const dragGestureRef = useRef<DragGesture | null>(null);
  const positionRef = useRef<VoiceButtonPosition | null>(null);
  const suppressClickRef = useRef(false);
  const mountedRef = useRef(true);
  const logBoxRef = useRef<HTMLDivElement>(null);
  const logMessagesRef = useRef<AgentLogMessage[]>([]);
  const agentQueueRef = useRef<string[]>([]);
  const agentRunningRef = useRef(false);
  const liveUtteranceRef = useRef<LiveUtterance | null>(null);
  const completedSentenceIdsRef = useRef(new Set<number>());
  const fatalRealtimeErrorRef = useRef(false);
  const skipInitialHistorySaveRef = useRef(true);
  const introPromptedRef = useRef(false);
  const speechActiveRef = useRef(false);
  const speechEnabledRef = useRef(true);
  const speakFeedbackRef = useRef<(message: string) => void>(() => undefined);
  const lastEmptyPromptRef = useRef(0);
  const lastPathnameRef = useRef(pathname);
  const lastPageStatusRef = useRef("");
  const [position, setPosition] = useState<VoiceButtonPosition | null>(null);
  const [dragging, setDragging] = useState(false);
  const [state, setState] = useState<VoiceState>("idle");
  const [statusMessage, setStatusMessage] = useState("打开语音输入");
  const [panelOpen, setPanelOpen] = useState(false);
  const [commandInput, setCommandInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [pendingAction, setPendingAction] =
    useState<AgentPendingAction | null>(null);
  const [domainPending, setDomainPending] =
    useState<DomainAgentResponse | null>(null);
  const [domainPendingTranscript, setDomainPendingTranscript] = useState("");
  const [logMessages, setLogMessages] = useState<AgentLogMessage[]>([]);
  const [speechEnabled, setSpeechEnabled] = useState(true);

  useEffect(() => {
    mountedRef.current = true;
    const element = dragHandleRef.current;
    const savedPosition = loadState<VoiceButtonPosition>(
      STORAGE_KEYS.voiceButtonPosition,
    );
    if (
      element &&
      savedPosition &&
      Number.isFinite(savedPosition.x) &&
      Number.isFinite(savedPosition.y)
    ) {
      const rect = element.getBoundingClientRect();
      const nextPosition = clampPosition(
        savedPosition,
        rect.width,
        rect.height,
      );
      positionRef.current = nextPosition;
      setPosition(nextPosition);
    }

    const savedHistory = loadState<AgentLogMessage[]>(
      STORAGE_KEYS.agentHistory,
    );
    if (Array.isArray(savedHistory)) {
      const restoredHistory = savedHistory.slice(-80);
      logMessagesRef.current = restoredHistory;
      setLogMessages(restoredHistory);
    }
    const savedSpeechEnabled = loadState<boolean>(
      STORAGE_KEYS.voiceSpeechEnabled,
    );
    const nextSpeechEnabled = savedSpeechEnabled ?? true;
    speechEnabledRef.current = nextSpeechEnabled;
    setSpeechEnabled(nextSpeechEnabled);

    const keepInViewport = () => {
      const currentElement = dragHandleRef.current;
      const currentPosition = positionRef.current;
      if (!currentElement || !currentPosition) return;
      const rect = currentElement.getBoundingClientRect();
      const nextPosition = clampPosition(
        currentPosition,
        rect.width,
        rect.height,
      );
      positionRef.current = nextPosition;
      setPosition(nextPosition);
    };
    window.addEventListener("resize", keepInViewport);

    return () => {
      mountedRef.current = false;
      window.removeEventListener("resize", keepInViewport);
      cleanupRef.current?.();
      cleanupRef.current = null;
      window.speechSynthesis?.cancel();
    };
  }, []);

  useEffect(() => {
    if (skipInitialHistorySaveRef.current) {
      skipInitialHistorySaveRef.current = false;
      return;
    }
    saveState(STORAGE_KEYS.agentHistory, logMessages.slice(-80));
  }, [logMessages]);

  useEffect(() => {
    const box = logBoxRef.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [logMessages, busy, pendingAction]);

  useEffect(() => {
    const pathChanged = lastPathnameRef.current !== pathname;
    lastPathnameRef.current = pathname;
    const timer = window.setTimeout(() => {
      setPendingAction(null);
      void restorePendingAgentFocus();
      if (pathChanged && realtimeSessionRef.current) {
        const label = focusInitialVoiceControl();
        speakFeedbackRef.current(
          label
            ? `已进入${PAGE_LABELS[pathname] || "新页面"}。当前请填写“${label}”。`
            : `已进入${PAGE_LABELS[pathname] || "新页面"}。请说出下一步操作。`,
        );
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [pathname]);

  useEffect(() => {
    const root = document.getElementById("main-content");
    if (!root) return;
    let timer = 0;
    const observer = new MutationObserver(() => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        if (!realtimeSessionRef.current) return;
        const messages = Array.from(
          root.querySelectorAll<HTMLElement>('[role="alert"], [role="status"]'),
        )
          .map((element) => element.textContent?.replace(/\s+/g, " ").trim() || "")
          .filter(
            (message) =>
              message &&
              message !== lastPageStatusRef.current &&
              !/^(?:正在|加载中)/.test(message),
          );
        const latest = messages.at(-1);
        if (!latest) return;
        lastPageStatusRef.current = latest;
        speakFeedbackRef.current(latest);
      }, 160);
    });
    observer.observe(root, {
      childList: true,
      characterData: true,
      subtree: true,
    });
    return () => {
      window.clearTimeout(timer);
      observer.disconnect();
    };
  }, []);

  useEffect(() => {
    if (!panelOpen) return;
    let cancelled = false;
    void apiFetch<AgentPendingAction | null>("/api/agent/actions/current")
      .then((pending) => {
        if (!cancelled) setPendingAction(pending);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [panelOpen, pathname]);

  function appendLog(
    role: AgentLogMessage["role"],
    content: string,
  ): void {
    const cleaned = content.trim();
    if (!cleaned) return;
    const next = [
      ...logMessagesRef.current.slice(-79),
      { id: createLogId(), role, content: cleaned },
    ];
    logMessagesRef.current = next;
    setLogMessages(next);
  }

  function insertLog(
    role: AgentLogMessage["role"],
    content = "",
  ): string {
    const id = createLogId();
    const next = [
      ...logMessagesRef.current.slice(-79),
      { id, role, content },
    ];
    logMessagesRef.current = next;
    setLogMessages(next);
    return id;
  }

  function replaceLog(id: string, content: string): void {
    const next = logMessagesRef.current.map((message) =>
      message.id === id ? { ...message, content } : message,
    );
    logMessagesRef.current = next;
    setLogMessages(next);
  }

  function resumeInputAfterSpeech() {
    speechActiveRef.current = false;
    realtimeSessionRef.current?.setInputActive(true);
  }

  function speakFeedback(message: string) {
    const text = message.trim();
    if (
      !speechEnabledRef.current ||
      !text ||
      typeof window === "undefined" ||
      !("speechSynthesis" in window)
    ) {
      return;
    }
    window.speechSynthesis.cancel();
    speechActiveRef.current = true;
    realtimeSessionRef.current?.setInputActive(false);
    const utterance = new SpeechSynthesisUtterance(
      text.replace(/\s+/g, " ").slice(0, 320),
    );
    utterance.lang = "zh-CN";
    utterance.rate = 1.04;
    utterance.pitch = 1;
    let finished = false;
    let fallbackTimer = 0;
    const finish = () => {
      if (finished) return;
      finished = true;
      window.clearTimeout(fallbackTimer);
      resumeInputAfterSpeech();
    };
    utterance.onend = finish;
    utterance.onerror = finish;
    fallbackTimer = window.setTimeout(
      finish,
      Math.min(15000, 1800 + utterance.text.length * 90),
    );
    try {
      window.speechSynthesis.speak(utterance);
    } catch {
      finish();
    }
  }

  function setSpeechFeedbackEnabled(enabled: boolean) {
    speechEnabledRef.current = enabled;
    setSpeechEnabled(enabled);
    saveState(STORAGE_KEYS.voiceSpeechEnabled, enabled);
    if (!enabled) {
      window.speechSynthesis?.cancel();
      resumeInputAfterSpeech();
    }
  }

  speakFeedbackRef.current = speakFeedback;

  function setVisualLevel(level: number) {
    const clampedLevel = Math.min(1, Math.max(0, level));
    const levelValue = clampedLevel.toFixed(3);
    [buttonRef.current, recordButtonRef.current].forEach((surface) => {
      surface?.style.setProperty("--voice-level", levelValue);
    });

    const button = buttonRef.current;
    if (button) {
      const pulseTime = performance.now() / 95;
      const bars = button.querySelectorAll<HTMLElement>(".voice-input-bar");
      BAR_PROFILE.forEach((profile, index) => {
        const motion = 0.94 + Math.sin(pulseTime + index * 0.92) * 0.06;
        const idleLevel = 0.16 + profile * 0.14;
        const barLevel = Math.min(
          1,
          idleLevel + Math.sqrt(clampedLevel) * profile * motion * 0.82,
        );
        const bar = bars[index];
        bar?.style.setProperty("--bar-scale", barLevel.toFixed(3));
        bar?.style.setProperty("--bar-color", colorForLevel(barLevel));
      });
    }

    const recordBars =
      recordButtonRef.current?.querySelectorAll<HTMLElement>(
        ".voice-agent-bars span",
      );
    recordBars?.forEach((bar, index) => {
      const profile = BAR_PROFILE[index] ?? 0.5;
      const scale = Math.min(1, 0.32 + Math.sqrt(clampedLevel) * profile * 1.2);
      bar.style.setProperty("--agent-bar-scale", scale.toFixed(3));
    });
    onLevelChange?.(clampedLevel);
  }

  function handleRealtimeTranscript(
    event: Extract<RealtimeVoiceEvent, { type: "transcript" }>,
  ) {
    if (
      event.sentenceEnd &&
      completedSentenceIdsRef.current.has(event.sentenceId)
    ) {
      return;
    }
    const text = event.text.trim();
    if (!text) {
      if (
        event.sentenceEnd &&
        Date.now() - lastEmptyPromptRef.current > 4000
      ) {
        lastEmptyPromptRef.current = Date.now();
        const message = "没有听清，请再说一遍当前内容。";
        setStatusMessage(message);
        speakFeedback(message);
      }
      return;
    }
    let live = liveUtteranceRef.current;
    if (!live || live.sentenceId !== event.sentenceId) {
      live = {
        sentenceId: event.sentenceId,
        logId: insertLog("user", text),
        text,
      };
      liveUtteranceRef.current = live;
    } else if (text !== live.text) {
      live.text = text;
      replaceLog(live.logId, text);
    }
    setState("listening");
    setStatusMessage("正在实时识别，停顿后自动发送");

    if (event.sentenceEnd) {
      completedSentenceIdsRef.current.add(event.sentenceId);
      liveUtteranceRef.current = null;
      if (text) enqueueAgentTranscript(text);
    }
  }

  function handleRealtimeEvent(event: RealtimeVoiceEvent) {
    if (event.type === "connecting") {
      setState("requesting");
      setStatusMessage(
        event.attempt
          ? "正在重新连接实时语音识别"
          : "正在连接实时语音识别",
      );
      return;
    }
    if (event.type === "reconnecting") {
      setState("requesting");
      setStatusMessage("语音连接中断，麦克风保持开启并正在重连");
      return;
    }
    if (event.type === "ready") {
      fatalRealtimeErrorRef.current = false;
      completedSentenceIdsRef.current.clear();
      setState("listening");
      setStatusMessage(
        `持续聆听中，停顿约 ${Math.max(
          0.2,
          event.maxSentenceSilenceMs / 1000,
        ).toFixed(1)} 秒后自动发送`,
      );
      onListeningChange?.(true);
      if (!introPromptedRef.current) {
        introPromptedRef.current = true;
        window.setTimeout(() => {
          const label = focusInitialVoiceControl();
          speakFeedback(
            label
              ? `语音已开启。当前请填写“${label}”，直接说出内容即可。`
              : "语音已开启。请说出下一步操作。",
          );
        }, 120);
      }
      return;
    }
    if (event.type === "transcript") {
      handleRealtimeTranscript(event);
      onListeningChange?.(true);
      return;
    }
    if (event.type === "finishing") {
      setState("uploading");
      setStatusMessage("正在结束当前句并提交");
      return;
    }
    if (event.type === "finished") {
      realtimeSessionRef.current = null;
      cleanupRef.current = null;
      liveUtteranceRef.current = null;
      introPromptedRef.current = false;
      setVisualLevel(0);
      onListeningChange?.(false);
      if (fatalRealtimeErrorRef.current) return;
      setState("idle");
      setStatusMessage("打开持续语音识别");
      return;
    }
    if (event.type === "error") {
      const message =
        event.code === "qwen_not_configured"
          ? "后端尚未配置 Qwen API Key"
          : event.code === "qwen_auth_failed"
            ? "Qwen 实时语音鉴权失败"
            : event.code === "microphone_unavailable"
              ? "麦克风已断开"
              : event.code === "rate_limited"
                ? "实时语音请求过于频繁"
                : "实时语音识别暂时不可用";
      if (!event.recoverable) {
        fatalRealtimeErrorRef.current = true;
        setVisualLevel(0);
        onListeningChange?.(false);
        setState("error");
        setStatusMessage(message);
        appendLog("system", `${message}，可以在下方直接输入指令。`);
        speakFeedback(`${message}。请检查麦克风权限后重新打开语音。`);
      } else {
        setState("requesting");
        setStatusMessage("实时语音连接波动，正在自动恢复");
      }
    }
  }

  function enqueueAgentTranscript(transcript: string) {
    const cleaned = transcript.trim();
    if (!cleaned) return;
    agentQueueRef.current.push(cleaned);
    void processAgentQueue();
  }

  async function processAgentQueue() {
    if (agentRunningRef.current) return;
    agentRunningRef.current = true;
    try {
      while (agentQueueRef.current.length) {
        const transcript = agentQueueRef.current.shift();
        if (!transcript) continue;
        setBusy(true);
        await submitRecognizedTranscript(transcript);
      }
    } finally {
      agentRunningRef.current = false;
      if (mountedRef.current) {
        setBusy(false);
        if (realtimeSessionRef.current) {
          setState("listening");
          setStatusMessage("持续聆听中，随时可以继续说");
        }
      }
    }
  }

  function stopListening() {
    const session = realtimeSessionRef.current;
    if (!session) {
      setState("idle");
      setStatusMessage("打开持续语音识别");
      return;
    }
    setState("uploading");
    setStatusMessage("正在结束当前句");
    onListeningChange?.(false);
    void session.stop();
  }

  async function startListening() {
    if (realtimeSessionRef.current) {
      stopListening();
      return;
    }
    setPanelOpen(true);
    if (
      !navigator.mediaDevices?.getUserMedia ||
      !window.AudioContext ||
      !window.WebSocket
    ) {
      setState("error");
      setStatusMessage("当前浏览器不支持实时语音识别");
      appendLog(
        "system",
        "当前浏览器不支持实时语音识别，可以在下方直接输入指令。",
      );
      return;
    }

    setState("requesting");
    setStatusMessage("正在请求麦克风权限");
    let stream: MediaStream | null = null;

    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          autoGainControl: true,
          echoCancellation: true,
          noiseSuppression: true,
          channelCount: 1,
        },
      });
      if (!mountedRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }

      fatalRealtimeErrorRef.current = false;
      completedSentenceIdsRef.current.clear();
      liveUtteranceRef.current = null;
      const session = new RealtimeVoiceSession({
        stream,
        getContext: capturePageContext,
        getHistory: () => agentHistoryForRequest(logMessagesRef.current),
        onEvent: handleRealtimeEvent,
        onLevel: setVisualLevel,
      });
      realtimeSessionRef.current = session;
      cleanupRef.current = () => {
        void session.destroy();
      };
      await session.start();
    } catch (error) {
      stream?.getTracks().forEach((track) => track.stop());
      const failedSession = realtimeSessionRef.current;
      if (failedSession) void failedSession.destroy();
      realtimeSessionRef.current = null;
      cleanupRef.current = null;
      if (!mountedRef.current) return;
      const permissionDenied =
        error instanceof DOMException &&
        (error.name === "NotAllowedError" || error.name === "SecurityError");
      const message = permissionDenied
        ? "麦克风权限未开启"
        : "无法启动实时语音识别";
      setVisualLevel(0);
      setState("error");
      setStatusMessage(message);
      appendLog("system", `${message}，可以在下方直接输入指令。`);
      speakFeedback(`${message}。请检查浏览器权限后重试。`);
    }
  }

  async function streamAgentCommand(
    response: Response,
    onTranscript: (text: string) => void,
    onMessage: (text: string) => void,
    onReset: () => void,
  ): Promise<AgentCommandResponse> {
    let finalResponse: AgentCommandResponse | null = null;
    const handleEvent = (event: AgentStreamEvent) => {
      if (event.type === "transcript_delta") {
        onTranscript(event.text);
      } else if (event.type === "message_delta") {
        onMessage(event.text);
      } else if (event.type === "message_reset") {
        onReset();
      } else {
        finalResponse = event.response;
      }
    };
    await consumeAgentStream(response, handleEvent);
    if (!finalResponse) {
      throw new ApiError("流式响应意外结束", 502, "invalid_response");
    }
    return finalResponse;
  }

  async function submitRecognizedTranscript(transcript: string) {
    const normalizedCommand = transcript.replace(/\s+/g, "");
    if (/关闭语音播报|不要朗读|别读了|停止播报/.test(normalizedCommand)) {
      setSpeechFeedbackEnabled(false);
      appendLog("system", "已关闭语音播报。");
      return;
    }
    if (/打开语音播报|开启语音播报|开始朗读/.test(normalizedCommand)) {
      setSpeechFeedbackEnabled(true);
      appendLog("system", "已开启语音播报。");
      speakFeedback("语音播报已开启。");
      return;
    }
    if (/停止聆听|关闭麦克风/.test(normalizedCommand)) {
      appendLog("system", "已停止持续语音识别。");
      stopListening();
      return;
    }
    if (/关闭语音助手|退出语音/.test(normalizedCommand)) {
      appendLog("system", "已关闭语音助手。");
      stopListening();
      setPanelOpen(false);
      return;
    }
    if (domainPending) {
      if (/重复|再说|没听清|没听懂|你说什么/.test(transcript)) {
        appendLog("assistant", domainPending.message);
        speakFeedback(domainPending.message);
        return;
      }
      if (/怎么办|下一步|帮帮我/.test(transcript)) {
        const message = `${domainPending.message} 请继续补充信息，或说“取消”。`;
        appendLog("assistant", message);
        speakFeedback(message);
        return;
      }
      if (/确认|确定|执行|继续|好的|可以|是的|没问题/.test(transcript)) {
        await confirmDomainAction();
        return;
      }
      if (/取消|不要|不用|停止|算了|不执行/.test(transcript)) {
        cancelDomainAction();
        return;
      }
    }
    if (shouldUseDomainAgent(transcript, pathname)) {
      await submitDomainTranscript(transcript, "voice", false);
      return;
    }
    const context = capturePageContext();
    const history = agentHistoryForRequest(logMessagesRef.current);
    let assistantMessage = "";
    let assistantLogId = "";

    try {
      setStatusMessage("Agent 正在处理，麦克风继续实时聆听");
      const response = await apiStreamFetch("/api/agent/text/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          transcript,
          context,
          history,
          source: "voice",
        }),
      });
      const finalResponse = await streamAgentCommand(
        response,
        () => undefined,
        (delta) => {
          assistantMessage += delta;
          if (!assistantLogId) {
            assistantLogId = insertLog("assistant", assistantMessage);
          } else {
            replaceLog(assistantLogId, assistantMessage);
          }
          setStatusMessage("正在生成精简回复");
        },
        () => {
          assistantMessage = "";
          if (assistantLogId) replaceLog(assistantLogId, "");
        },
      );
      await handleAgentResponse(finalResponse, assistantLogId);
    } catch (error) {
      appendLog(
        "system",
        readableError(error, "语音指令执行失败，可以继续说话或改用文字。"),
      );
      speakFeedback(
        readableError(error, "语音指令执行失败，请再说一次。"),
      );
    }
  }

  async function submitDomainTranscript(
    transcript: string,
    source: "voice" | "text",
    confirmed: boolean,
  ) {
    try {
      setStatusMessage("正在解析人物、背景、故事和文书项目");
      const response = await sendDomainCommand(
        transcript,
        agentHistoryForRequest(logMessagesRef.current),
        { confirmed, source },
      );
      appendLog("assistant", response.message);
      speakFeedback(response.message);
      applyDomainResolved(response.resolved);
      if (response.status === "confirmation_required") {
        setDomainPending(response);
        setDomainPendingTranscript(transcript);
        return;
      }
      setDomainPending(null);
      setDomainPendingTranscript("");
      if (response.status === "executed") {
        const resolvedBatch = response.resolved.batch_id;
        router.push(
          typeof resolvedBatch === "string" && resolvedBatch
            ? "/batch"
            : "/library",
        );
      }
    } catch (error) {
      const message = readableError(
        error,
        "实例操作失败，请检查人物和背景名称。",
      );
      appendLog(
        "system",
        message,
      );
      speakFeedback(message);
    }
  }

  async function handleAgentResponse(
    response: AgentCommandResponse,
    assistantLogId = "",
  ): Promise<void> {
    if (assistantLogId) {
      replaceLog(assistantLogId, response.message);
    } else {
      appendLog("assistant", response.message);
    }
    speakFeedback(response.message);
    setPendingAction(response.pending_action);

    if (response.ui_actions.length) {
      const uiResult = await executeAgentUiActions(
        response.ui_actions,
        (path) => router.push(path),
      );
      if (!uiResult.ok) appendLog("system", uiResult.message);
    }

    if (
      response.status === "ready" &&
      response.capability &&
      response.capability.name !== "agent.cancel_pending"
    ) {
      const result = await executeAgentCapability(
        response.capability.name,
        response.capability.arguments,
        (path) => router.push(path),
      );
      if (!result.ok) {
        appendLog("system", result.message);
      } else if (response.capability.name === "agent.confirm_pending") {
        setPendingAction(null);
      }
    }
  }

  async function submitTextCommand(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const transcript = commandInput.trim();
    if (!transcript || busy) return;

    setBusy(true);
    setCommandInput("");
    const history = agentHistoryForRequest(logMessagesRef.current);
    appendLog("user", transcript);
    if (domainPending) {
      if (/确认|执行|继续/.test(transcript)) {
        await confirmDomainAction();
        setBusy(false);
        return;
      }
      if (/取消|不要|停止/.test(transcript)) {
        cancelDomainAction();
        setBusy(false);
        return;
      }
    }
    if (shouldUseDomainAgent(transcript, pathname)) {
      await submitDomainTranscript(transcript, "text", false);
      setBusy(false);
      return;
    }
    const context = capturePageContext();
    let assistantMessage = "";
    let assistantLogId = "";
    try {
      const response = await apiStreamFetch("/api/agent/text/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ transcript, context, history }),
      });
      const finalResponse = await streamAgentCommand(
        response,
        () => undefined,
        (delta) => {
          assistantMessage += delta;
          if (!assistantLogId) {
            assistantLogId = insertLog("assistant", assistantMessage);
          } else {
            replaceLog(assistantLogId, assistantMessage);
          }
        },
        () => {
          assistantMessage = "";
          if (assistantLogId) replaceLog(assistantLogId, "");
        },
      );
      await handleAgentResponse(finalResponse, assistantLogId);
    } catch (error) {
      const message = readableError(error, "文字指令执行失败。");
      appendLog("system", message);
      speakFeedback(message);
    } finally {
      setBusy(false);
      if (realtimeSessionRef.current) {
        setState("listening");
        setStatusMessage("持续聆听中，随时可以继续说");
      }
    }
  }

  async function confirmPendingAction() {
    if (!pendingAction || pendingAction.status !== "prepared") return;
    setBusy(true);
    setStatusMessage("正在校验并执行已确认操作");
    try {
      const result = await apiFetch<AgentActionCommitResponse>(
        `/api/agent/actions/${pendingAction.id}/commit`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ context: capturePageContext() }),
        },
      );
      if (result.status === "needs_input") {
        setPendingAction({
          ...pendingAction,
          status: "collecting",
          arguments: result.arguments,
          missing_fields: result.missing_fields,
        });
        appendLog(
          "system",
          `执行前仍需补充：${result.missing_fields
            .map((field) => field.label)
            .join("、")}。`,
        );
        return;
      }
      setPendingAction(null);
      const execution = await executeAgentCapability(
        result.capability,
        result.arguments,
        (path) => router.push(path),
      );
      appendLog(
        "system",
        execution.ok ? "已确认并在页面中执行操作。" : execution.message,
      );
    } catch (error) {
      const message = readableError(error, "确认执行失败。");
      appendLog("system", message);
      speakFeedback(message);
    } finally {
      setBusy(false);
      if (realtimeSessionRef.current) {
        setState("listening");
        setStatusMessage("持续聆听中，随时可以继续说");
      }
    }
  }

  async function cancelPendingAction() {
    if (!pendingAction) return;
    const actionId = pendingAction.id;
    setPendingAction(null);
    try {
      await apiFetch(`/api/agent/actions/${actionId}`, { method: "DELETE" });
      appendLog("system", "已取消待执行操作。");
    } catch (error) {
      const message = readableError(error, "取消操作失败。");
      appendLog("system", message);
      speakFeedback(message);
    }
  }

  function cancelDomainAction() {
    setDomainPending(null);
    setDomainPendingTranscript("");
    appendLog("system", "已取消实例操作。");
    speakFeedback("已取消实例操作。");
  }

  async function confirmDomainAction() {
    if (!domainPending || !domainPendingTranscript) return;
    setBusy(true);
    try {
      await submitDomainTranscript(
        domainPendingTranscript,
        domainPending.source,
        true,
      );
    } finally {
      setBusy(false);
    }
  }

  function beginDrag(event: ReactPointerEvent<HTMLDivElement>) {
    if (!event.isPrimary || event.button !== 0 || panelOpen) return;
    const rect = event.currentTarget.getBoundingClientRect();
    dragGestureRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: rect.left,
      originY: rect.top,
      moved: false,
    };
    suppressClickRef.current = false;
  }

  function moveDrag(event: ReactPointerEvent<HTMLDivElement>) {
    const gesture = dragGestureRef.current;
    const element = dragHandleRef.current;
    if (!gesture || !element || gesture.pointerId !== event.pointerId) return;

    const deltaX = event.clientX - gesture.startX;
    const deltaY = event.clientY - gesture.startY;
    if (!gesture.moved && Math.hypot(deltaX, deltaY) < DRAG_THRESHOLD) return;
    if (!gesture.moved) {
      gesture.moved = true;
      setDragging(true);
      event.currentTarget.setPointerCapture(event.pointerId);
    }
    event.preventDefault();

    const rect = element.getBoundingClientRect();
    const nextPosition = clampPosition(
      {
        x: gesture.originX + deltaX,
        y: gesture.originY + deltaY,
      },
      rect.width,
      rect.height,
    );
    positionRef.current = nextPosition;
    setPosition(nextPosition);
  }

  function endDrag(event: ReactPointerEvent<HTMLDivElement>) {
    const gesture = dragGestureRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    if (gesture.moved) {
      suppressClickRef.current = true;
      if (positionRef.current) {
        saveState(STORAGE_KEYS.voiceButtonPosition, positionRef.current);
      }
    }
    dragGestureRef.current = null;
    setDragging(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  function cancelDrag(event: ReactPointerEvent<HTMLDivElement>) {
    const gesture = dragGestureRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    suppressClickRef.current = gesture.moved;
    dragGestureRef.current = null;
    setDragging(false);
  }

  const listening = state === "listening";
  const activeState =
    state === "requesting" || state === "uploading" ? "requesting" : state;
  const positionStyle = position
    ? ({
        left: position.x,
        top: position.y,
        right: "auto",
        bottom: "auto",
      } satisfies CSSProperties)
    : undefined;

  return (
    <>
      {panelOpen ? (
        <section
          className="voice-agent-panel"
          data-agent-ignore="true"
          aria-label="GradPilot 语音操作助手"
        >
          <header className="voice-agent-header">
            <div className="voice-agent-heading">
              <span className="voice-agent-mark">
                <Icon name="spark" size={18} />
              </span>
              <div>
                <span className="voice-agent-kicker">GRADPILOT COMMAND</span>
                <h2>语音操作记录</h2>
              </div>
            </div>
            <div className="voice-agent-header-actions">
              <span className="voice-agent-page">
                {PAGE_LABELS[pathname] || "当前页面"}
              </span>
              <button
                type="button"
                className="voice-agent-icon-button"
                aria-label={speechEnabled ? "关闭语音播报" : "开启语音播报"}
                aria-pressed={speechEnabled}
                title={speechEnabled ? "关闭语音播报" : "开启语音播报"}
                onClick={() => setSpeechFeedbackEnabled(!speechEnabled)}
              >
                <Icon
                  name={speechEnabled ? "volume" : "volume-off"}
                  size={17}
                />
              </button>
              <button
                type="button"
                className="voice-agent-icon-button"
                aria-label="关闭语音操作助手"
                title="关闭"
                onClick={() => {
                  if (realtimeSessionRef.current) stopListening();
                  window.speechSynthesis?.cancel();
                  speechActiveRef.current = false;
                  setPanelOpen(false);
                }}
              >
                ×
              </button>
            </div>
          </header>

          <div className="voice-agent-status" role="status" aria-live="polite">
            <span
              className={`voice-agent-status-dot is-${activeState}`}
              aria-hidden="true"
            />
            <span>{statusMessage}</span>
            <span className="voice-agent-status-spacer" />
            <span>
              {listening
                ? busy
                  ? "识别中 · Agent 处理中"
                  : "持续识别"
                : busy
                  ? "处理中"
                  : "就绪"}
            </span>
          </div>

          <div
            ref={logBoxRef}
            className="voice-agent-log"
            role="log"
            aria-live="polite"
            aria-busy={busy}
          >
            {!logMessages.length ? (
              <div className="voice-agent-empty">
                <Icon name="chat" size={24} />
                <strong>打开后持续聆听，不需要重复点击</strong>
                <p>说话内容会实时显示，停顿后自动交给 Agent；再次点击麦克风才会停止。</p>
              </div>
            ) : null}
            {logMessages.map((message) => (
              <article
                key={message.id}
                className={`voice-agent-message is-${message.role}`}
              >
                <span>
                  {message.role === "user"
                    ? "你"
                    : message.role === "assistant"
                      ? "GradPilot"
                      : "系统"}
                </span>
                <p>{message.content}</p>
              </article>
            ))}
            {busy ? (
              <p className="voice-agent-working" role="status">
                <span className="spinner" />
                Agent 正在处理，实时语音识别仍在继续…
              </p>
            ) : null}
          </div>

          {pendingAction ? (
            <div className="voice-agent-confirm" role="alert">
              <div>
                <strong>
                  {pendingAction.status === "prepared"
                    ? "需要确认"
                    : "等待补充信息"}
                </strong>
                <p>{pendingAction.summary}</p>
                {pendingAction.missing_fields.length ? (
                  <p>
                    缺少：{pendingAction.missing_fields
                      .map((field) => field.label)
                      .join("、")}
                  </p>
                ) : null}
              </div>
              <div className="voice-agent-confirm-actions">
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => void cancelPendingAction()}
                >
                  取消
                </button>
                {pendingAction.status === "prepared" ? (
                  <button
                    type="button"
                    className="btn"
                    onClick={() => void confirmPendingAction()}
                  >
                    确认执行
                  </button>
                ) : null}
              </div>
            </div>
          ) : null}

          {domainPending ? (
            <div className="voice-agent-confirm" role="alert">
              <div>
                <strong>实例操作需要确认</strong>
                <p>{domainPending.message}</p>
                {domainPending.capability ? (
                  <p>
                    操作：{domainPending.capability.name}
                    {Object.keys(domainPending.arguments).length
                      ? ` · ${JSON.stringify(domainPending.arguments)}`
                      : ""}
                  </p>
                ) : null}
              </div>
              <div className="voice-agent-confirm-actions">
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={cancelDomainAction}
                >
                  取消
                </button>
                <button
                  type="button"
                  className="btn"
                  onClick={() => void confirmDomainAction()}
                >
                  确认执行
                </button>
              </div>
            </div>
          ) : null}

          <form className="voice-agent-composer" onSubmit={submitTextCommand}>
            <label className="sr-only" htmlFor="voice-agent-command">
              输入文字指令
            </label>
            <textarea
              id="voice-agent-command"
              value={commandInput}
              onChange={(event) => setCommandInput(event.target.value)}
              placeholder="也可以直接输入指令"
              maxLength={4000}
              disabled={busy}
              onKeyDown={(event) => {
                if (
                  (event.ctrlKey || event.metaKey) &&
                  event.key === "Enter" &&
                  !event.nativeEvent.isComposing
                ) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
            />
            <button
              type="submit"
              className="voice-agent-send"
              disabled={busy || !commandInput.trim()}
            >
              执行
            </button>
          </form>

          <footer className="voice-agent-footer">
            <button
              ref={recordButtonRef}
              type="button"
              className={`voice-agent-record is-${activeState}`}
              onClick={() => void startListening()}
              aria-label={
                listening ? "停止持续语音识别" : "开始持续语音识别"
              }
              aria-pressed={listening}
            >
              <span className="voice-agent-record-orbit" aria-hidden="true" />
              <span className="voice-agent-bars" aria-hidden="true">
                {BAR_PROFILE.map((profile, index) => (
                  <span
                    key={index}
                    style={
                      {
                        "--agent-bar": profile,
                        "--agent-bar-scale": 0.32 + profile * 0.2,
                      } as CSSProperties
                    }
                  />
                ))}
              </span>
            </button>
            <div className="voice-agent-footer-copy">
              <strong>
                {listening ? "持续聆听中" : "点击后持续工作"}
              </strong>
              <span>
                {listening
                  ? "停顿自动发送，麦克风不会自动关闭"
                  : "实时识别、自动断句、自动提交 Agent"}
              </span>
            </div>
            <button
              type="button"
              className="voice-agent-clear"
              onClick={() => {
                if (pendingAction) {
                  void apiFetch(`/api/agent/actions/${pendingAction.id}`, {
                    method: "DELETE",
                  });
                }
                logMessagesRef.current = [];
                setLogMessages([]);
                setPendingAction(null);
                setDomainPending(null);
                setDomainPendingTranscript("");
              }}
            >
              清空记录
            </button>
          </footer>
        </section>
      ) : (
        <div
          ref={dragHandleRef}
          className={`voice-input-drag-handle ${dragging ? "is-dragging" : ""}`}
          style={positionStyle}
          onPointerDown={beginDrag}
          onPointerMove={moveDrag}
          onPointerUp={endDrag}
          onPointerCancel={cancelDrag}
        >
          <button
            ref={buttonRef}
            type="button"
            className={`voice-input-button is-${activeState}`}
            onClick={() => {
              if (suppressClickRef.current) {
                suppressClickRef.current = false;
                return;
              }
              setPanelOpen(true);
              void startListening();
            }}
            aria-label={statusMessage}
            aria-pressed={listening}
            title={statusMessage}
          >
            <span className="voice-input-orbit" aria-hidden="true" />
            <span className="voice-input-core">
              <span className="voice-input-bars" aria-hidden="true">
                {BAR_PROFILE.map((_, index) => (
                  <span
                    className="voice-input-bar"
                    key={index}
                    style={
                      {
                        "--bar-scale": `${0.16 + BAR_PROFILE[index] * 0.14}`,
                        "--bar-delay": `${-Math.abs(index - 4) * 0.09}s`,
                      } as CSSProperties
                    }
                  />
                ))}
              </span>
            </span>
            <span className="voice-input-dot" aria-hidden="true" />
            <span className="sr-only" role="status" aria-live="polite">
              {statusMessage}
            </span>
          </button>
        </div>
      )}
    </>
  );
}
