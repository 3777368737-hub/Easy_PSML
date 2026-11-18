const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000').replace(/\/+$/, '');
const CLIENT_ID_KEY = 'gradpilot_client_id';
let memoryClientId = '';

type ApiErrorPayload = {
  detail?: unknown;
  code?: unknown;
  errors?: Array<{ loc?: string; msg?: string }>;
  request_id?: unknown;
};

export class ApiError extends Error {
  status: number;
  code: string;
  requestId: string;

  constructor(message: string, status: number, code = 'request_failed', requestId = '') {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

function randomId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

export function getClientId(): string {
  if (typeof window === 'undefined') return 'server-render-client';
  try {
    const existing = localStorage.getItem(CLIENT_ID_KEY);
    if (existing && /^[A-Za-z0-9._:-]{16,128}$/.test(existing)) {
      memoryClientId = existing;
      return existing;
    }
    const next = `client-${randomId()}`;
    localStorage.setItem(CLIENT_ID_KEY, next);
    memoryClientId = next;
    return next;
  } catch {
    if (!memoryClientId) memoryClientId = `client-${randomId()}`;
    return memoryClientId;
  }
}

function extractErrorMessage(payload: ApiErrorPayload, fallback: string): string {
  if (Array.isArray(payload.errors) && payload.errors.length > 0) {
    const first = payload.errors[0];
    const location = first.loc ? `${first.loc}: ` : '';
    return `${location}${first.msg || fallback}`;
  }
  if (typeof payload.detail === 'string' && payload.detail.trim()) {
    return payload.detail;
  }
  return fallback;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set('X-Client-Id', getClientId());
  headers.set('X-Request-Id', randomId());

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers,
      cache: 'no-store',
    });
  } catch {
    throw new ApiError(
      `网络请求失败：无法连接后端服务（${API_BASE}）。请确认 GradPilot 控制台中的服务正在运行。`,
      0,
      'network_error',
    );
  }

  const raw = await response.text();
  let parsed: ApiErrorPayload = {};
  if (raw) {
    try {
      parsed = JSON.parse(raw) as ApiErrorPayload;
    } catch {
      parsed = { detail: raw };
    }
  }

  if (!response.ok) {
    throw new ApiError(
      extractErrorMessage(parsed, `请求失败：${response.status}`),
      response.status,
      typeof parsed.code === 'string' ? parsed.code : 'request_failed',
      typeof parsed.request_id === 'string' ? parsed.request_id : '',
    );
  }

  if (!raw) return undefined as T;
  try {
    return JSON.parse(raw) as T;
  } catch {
    throw new ApiError('后端返回了无法解析的数据。', response.status, 'invalid_response');
  }
}

export function readableError(error: unknown, fallback = '操作失败'): string {
  if (!(error instanceof Error)) return fallback;
  if (!(error instanceof ApiError)) return error.message || fallback;

  const messages: Record<string, string> = {
    network_error: error.message,
    model_not_configured: '后端尚未配置 DEEPSEEK_API_KEY，请检查 backend/.env。',
    model_auth_failed: '模型服务鉴权失败，请检查 API Key 是否正确或是否过期。',
    model_output_invalid: '模型返回内容不完整，系统已自动重试。请缩短项目要求后再次尝试。',
    model_service_unavailable: '模型服务暂时不可用，请稍后重试。',
    rate_limited: '请求次数过多，请稍后再试。',
    client_id_required: '当前浏览器身份缺失，请刷新页面后重试。',
    client_id_invalid: '当前浏览器身份无效，请清除本站本地存储后刷新。',
    request_validation_failed: error.message,
    not_found: '数据不存在或已失效，请返回上一步重新生成。',
  };
  const friendly = messages[error.code] || error.message || fallback;
  return error.requestId ? `${friendly}（请求编号：${error.requestId}）` : friendly;
}
