"use client";

import { apiWebSocketUrl } from "@/lib/api";
import type {
  AgentConversationMessage,
  AgentPageContext,
} from "@/lib/voice-agent";

export type RealtimeVoiceEvent =
  | { type: "connecting"; attempt: number }
  | {
      type: "ready";
      model: string;
      maxSentenceSilenceMs: number;
      sampleRate: number;
    }
  | {
      type: "transcript";
      sentenceId: number;
      text: string;
      sentenceBegin: boolean;
      sentenceEnd: boolean;
      beginTime: number | null;
      endTime: number | null;
    }
  | { type: "finishing" }
  | { type: "finished" }
  | { type: "reconnecting"; attempt: number; delayMs: number }
  | {
      type: "error";
      code: string;
      message: string;
      recoverable: boolean;
    };

type RealtimeVoiceOptions = {
  stream: MediaStream;
  getContext: () => AgentPageContext;
  getHistory: () => AgentConversationMessage[];
  onEvent: (event: RealtimeVoiceEvent) => void;
  onLevel: (level: number) => void;
};

type PcmCapture = {
  sampleRate: number;
  setActive: (active: boolean) => void;
  stop: () => Promise<void>;
};

type UpstreamMessage = {
  type?: string;
  model?: string;
  sample_rate?: number;
  max_sentence_silence_ms?: number;
  sentence_id?: number;
  text?: string;
  sentence_begin?: boolean;
  sentence_end?: boolean;
  begin_time?: number | null;
  end_time?: number | null;
  code?: string;
  message?: string;
};

const FATAL_ERROR_CODES = new Set([
  "qwen_not_configured",
  "qwen_auth_failed",
  "client_id_required",
  "client_id_invalid",
  "rate_limited",
]);

function pcm16FromFloat32(samples: Float32Array): ArrayBuffer {
  const pcm = new Int16Array(samples.length);
  for (let index = 0; index < samples.length; index += 1) {
    const value = Math.max(-1, Math.min(1, samples[index]));
    pcm[index] = value < 0 ? value * 0x8000 : value * 0x7fff;
  }
  return pcm.buffer;
}

async function createPcmCapture(
  stream: MediaStream,
  onChunk: (chunk: ArrayBuffer) => void,
  onLevel: (level: number) => void,
): Promise<PcmCapture> {
  let audioContext: AudioContext;
  try {
    audioContext = new AudioContext({
      sampleRate: 16000,
      latencyHint: "interactive",
    });
  } catch {
    audioContext = new AudioContext({ latencyHint: "interactive" });
  }
  if (audioContext.state === "suspended") {
    await audioContext.resume();
  }

  const source = audioContext.createMediaStreamSource(stream);
  const analyser = audioContext.createAnalyser();
  analyser.fftSize = 512;
  analyser.smoothingTimeConstant = 0.82;
  source.connect(analyser);

  const samples = new Uint8Array(analyser.fftSize);
  let animationFrame = 0;
  let active = false;
  let smoothedLevel = 0;
  const updateLevel = () => {
    analyser.getByteTimeDomainData(samples);
    let sumSquares = 0;
    for (const sample of samples) {
      const normalized = (sample - 128) / 128;
      sumSquares += normalized * normalized;
    }
    const rms = Math.sqrt(sumSquares / samples.length);
    const targetLevel = Math.min(1, Math.pow(rms * 6.5, 0.68));
    smoothedLevel += (targetLevel - smoothedLevel) * 0.28;
    onLevel(active ? smoothedLevel : 0);
    animationFrame = requestAnimationFrame(updateLevel);
  };
  updateLevel();

  const muteGain = audioContext.createGain();
  muteGain.gain.value = 0;
  muteGain.connect(audioContext.destination);
  analyser.connect(muteGain);

  let workletNode: AudioWorkletNode | null = null;
  let processorNode: ScriptProcessorNode | null = null;
  try {
    await audioContext.audioWorklet.addModule("/voice-pcm-worklet.js");
    workletNode = new AudioWorkletNode(
      audioContext,
      "gradpilot-pcm-worklet",
      {
        processorOptions: {
          frameSamples: Math.max(320, Math.round(audioContext.sampleRate / 10)),
        },
      },
    );
    workletNode.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
      if (active && event.data.byteLength) onChunk(event.data);
    };
    source.connect(workletNode);
    workletNode.connect(muteGain);
  } catch {
    processorNode = audioContext.createScriptProcessor(2048, 1, 1);
    processorNode.onaudioprocess = (event) => {
      if (!active) return;
      onChunk(pcm16FromFloat32(event.inputBuffer.getChannelData(0)));
    };
    source.connect(processorNode);
    processorNode.connect(muteGain);
  }

  const resume = () => {
    if (audioContext.state === "suspended") void audioContext.resume();
  };
  document.addEventListener("visibilitychange", resume);

  return {
    sampleRate: audioContext.sampleRate,
    setActive(nextActive) {
      active = nextActive;
      workletNode?.port.postMessage({ type: "active", value: nextActive });
      if (!nextActive) onLevel(0);
    },
    async stop() {
      active = false;
      cancelAnimationFrame(animationFrame);
      document.removeEventListener("visibilitychange", resume);
      workletNode?.port.postMessage({ type: "active", value: false });
      if (workletNode) workletNode.port.onmessage = null;
      if (processorNode) processorNode.onaudioprocess = null;
      source.disconnect();
      analyser.disconnect();
      workletNode?.disconnect();
      processorNode?.disconnect();
      muteGain.disconnect();
      stream.getTracks().forEach((track) => track.stop());
      if (audioContext.state !== "closed") await audioContext.close();
    },
  };
}

export class RealtimeVoiceSession {
  private readonly stream: MediaStream;
  private readonly getContext: () => AgentPageContext;
  private readonly getHistory: () => AgentConversationMessage[];
  private readonly onEvent: (event: RealtimeVoiceEvent) => void;
  private readonly onLevel: (level: number) => void;
  private socket: WebSocket | null = null;
  private capture: PcmCapture | null = null;
  private ready = false;
  private active = false;
  private intentionalStop = false;
  private reconnectAttempt = 0;
  private reconnectTimer: number | null = null;
  private finishTimer: number | null = null;
  private finished = false;

  constructor(options: RealtimeVoiceOptions) {
    this.stream = options.stream;
    this.getContext = options.getContext;
    this.getHistory = options.getHistory;
    this.onEvent = options.onEvent;
    this.onLevel = options.onLevel;
  }

  async start(): Promise<void> {
    if (this.capture) return;
    this.capture = await createPcmCapture(
      this.stream,
      (chunk) => this.sendAudio(chunk),
      this.onLevel,
    );
    this.active = true;
    this.stream.getAudioTracks()[0]?.addEventListener(
      "ended",
      () => {
        if (!this.intentionalStop) {
          this.intentionalStop = true;
          this.active = false;
          this.onEvent({
            type: "error",
            code: "microphone_unavailable",
            message: "Microphone track ended",
            recoverable: false,
          });
          this.socket?.close(1001, "microphone ended");
          void this.finishSession();
        }
      },
      { once: true },
    );
    this.connect(0);
  }

  async stop(): Promise<void> {
    if (this.intentionalStop) return;
    this.intentionalStop = true;
    this.active = false;
    this.clearReconnectTimer();
    this.capture?.setActive(false);
    const socket = this.socket;
    if (socket?.readyState === WebSocket.OPEN && this.ready) {
      socket.send(JSON.stringify({ type: "stop" }));
      this.finishTimer = window.setTimeout(() => {
        socket.close(1000, "voice session stopped");
        void this.cleanupCapture();
      }, 6000);
      return;
    }
    socket?.close(1000, "voice session stopped");
    await this.finishSession();
  }

  async destroy(): Promise<void> {
    this.intentionalStop = true;
    this.active = false;
    this.clearReconnectTimer();
    if (this.finishTimer !== null) {
      window.clearTimeout(this.finishTimer);
      this.finishTimer = null;
    }
    this.socket?.close(1000, "voice component unmounted");
    this.socket = null;
    await this.cleanupCapture();
  }

  private connect(delayMs: number): void {
    if (!this.active || this.intentionalStop) return;
    this.clearReconnectTimer();
    this.onEvent({
      type: delayMs ? "reconnecting" : "connecting",
      attempt: this.reconnectAttempt,
      delayMs,
    });

    const openSocket = () => {
      if (!this.active || this.intentionalStop) return;
      const socket = new WebSocket(
        apiWebSocketUrl("/api/agent/voice/realtime"),
      );
      socket.binaryType = "arraybuffer";
      this.socket = socket;
      this.ready = false;

      socket.onopen = () => {
        socket.send(
          JSON.stringify({
            type: "start",
            context: this.getContext(),
            history: this.getHistory(),
            sample_rate: this.capture?.sampleRate || 16000,
          }),
        );
      };
      socket.onmessage = (event) => {
        this.handleMessage(event.data);
      };
      socket.onerror = () => {
        this.ready = false;
        this.capture?.setActive(false);
      };
      socket.onclose = () => {
        this.ready = false;
        this.capture?.setActive(false);
        if (this.socket === socket) this.socket = null;
        if (this.intentionalStop) {
          void this.finishSession();
          return;
        }
        this.reconnectAttempt += 1;
        this.connect(Math.min(8000, 700 * 2 ** (this.reconnectAttempt - 1)));
      };
    };

    if (delayMs > 0) {
      this.reconnectTimer = window.setTimeout(openSocket, delayMs);
    } else {
      openSocket();
    }
  }

  private handleMessage(raw: string): void {
    let message: UpstreamMessage;
    try {
      message = JSON.parse(raw) as UpstreamMessage;
    } catch {
      return;
    }

    if (message.type === "asr_ready") {
      this.ready = true;
      this.reconnectAttempt = 0;
      this.capture?.setActive(true);
      this.onEvent({
        type: "ready",
        model: message.model || "",
        maxSentenceSilenceMs: Number(message.max_sentence_silence_ms || 1200),
        sampleRate: Number(message.sample_rate || this.capture?.sampleRate || 16000),
      });
      return;
    }
    if (message.type === "transcript") {
      this.onEvent({
        type: "transcript",
        sentenceId: Number(message.sentence_id || 0),
        text: message.text || "",
        sentenceBegin: Boolean(message.sentence_begin),
        sentenceEnd: Boolean(message.sentence_end),
        beginTime:
          typeof message.begin_time === "number" ? message.begin_time : null,
        endTime:
          typeof message.end_time === "number" ? message.end_time : null,
      });
      return;
    }
    if (message.type === "asr_finishing") {
      this.onEvent({ type: "finishing" });
      return;
    }
    if (message.type === "asr_finished") {
      this.ready = false;
      this.intentionalStop = true;
      this.socket?.close(1000, "ASR task finished");
      void this.finishSession();
      return;
    }
    if (message.type === "asr_error") {
      this.ready = false;
      this.capture?.setActive(false);
      const code = message.code || "asr_session_failed";
      const recoverable = !FATAL_ERROR_CODES.has(code);
      this.onEvent({
        type: "error",
        code,
        message: message.message || "Realtime ASR failed",
        recoverable,
      });
      if (!recoverable) {
        this.intentionalStop = true;
        this.socket?.close(1001, "ASR configuration error");
        void this.finishSession();
      }
    }
  }

  private sendAudio(chunk: ArrayBuffer): void {
    if (
      !this.ready ||
      this.socket?.readyState !== WebSocket.OPEN ||
      chunk.byteLength === 0
    ) {
      return;
    }
    this.socket.send(chunk);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private async finishSession(): Promise<void> {
    if (this.finished) return;
    this.finished = true;
    if (this.finishTimer !== null) {
      window.clearTimeout(this.finishTimer);
      this.finishTimer = null;
    }
    await this.cleanupCapture();
    this.onEvent({ type: "finished" });
  }

  private async cleanupCapture(): Promise<void> {
    const capture = this.capture;
    this.capture = null;
    if (capture) await capture.stop();
  }
}
