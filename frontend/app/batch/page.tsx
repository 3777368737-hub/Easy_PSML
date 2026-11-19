'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ApiError, apiFetch, readableError } from '@/lib/api';
import {
  directionInputs, ESSAY_TYPES, essayLabel, MAX_DIRECTIONS, newDirection,
  validateDirections, type DirectionForm, type EssayForm,
} from '@/lib/batch-form';
import { loadState, removeState, saveState, STORAGE_KEYS } from '@/lib/storage';
import type {
  BatchItem, BatchRequest, BatchResponse, BatchTone, EssayType,
  ProfileResponse, SessionSnapshot, StorySessionState,
} from '@/lib/types';

const statusLabels: Record<BatchResponse['status'], string> = {
  pending: '排队中', running: '生成中', completed: '全部完成',
  partial_failed: '部分完成，部分失败', failed: '生成失败',
};
const stageLabels: Record<BatchItem['stage'], string> = {
  pending: '等待生成', analysis: '正在分析项目', outline: '正在生成中文大纲',
  draft: '正在生成英文草稿', completed: '已完成', failed: '生成失败',
};

function isActive(batch: BatchResponse | null): boolean {
  return batch?.status === 'pending' || batch?.status === 'running';
}

function downloadText(text: string, filename: string, markdown = false) {
  const url = URL.createObjectURL(new Blob([text], {
    type: markdown ? 'text/markdown;charset=utf-8' : 'text/plain;charset=utf-8',
  }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename.replace(/[<>:"/\\|?*\x00-\x1f]/g, '_');
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function FieldError({ id, errors }: { id: string; errors: Record<string, string> }) {
  return errors[id] ? <p className="field-error" id={`${id}-error`}>{errors[id]}</p> : null;
}

export default function BatchPage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [profile, setProfile] = useState<ProfileResponse | null>(null);
  const [directions, setDirections] = useState<DirectionForm[]>([]);
  const [tone, setTone] = useState<BatchTone>('balanced');
  const [batch, setBatch] = useState<BatchResponse | null>(null);
  const [history, setHistory] = useState<BatchResponse[]>([]);
  const [pendingRequest, setPendingRequest] = useState<BatchRequest | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [pollError, setPollError] = useState('');
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const actionLock = useRef(false);
  const selectionVersion = useRef(0);

  // Initialize browser storage only after server rendering and hydration.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    let cancelled = false;
    const currentProfile = loadState<ProfileResponse>(STORAGE_KEYS.profile);
    setProfile(currentProfile);
    const saved = loadState<{ profile_id: string; directions: DirectionForm[]; tone: BatchTone }>(STORAGE_KEYS.batchForm);
    if (saved?.profile_id === currentProfile?.profile_id && saved?.directions?.length) {
      setDirections(saved.directions);
      setTone(saved.tone);
    } else {
      setDirections([newDirection()]);
    }
    const submitted = loadState<BatchRequest>(STORAGE_KEYS.batchSubmission);
    if (submitted?.profile_id === currentProfile?.profile_id) setPendingRequest(submitted);
    setReady(true);
    const version = ++selectionVersion.current;
    void apiFetch<BatchResponse[]>('/api/batches').then((items) => {
      if (cancelled) return;
      if (version !== selectionVersion.current) return;
      setHistory(items);
      const savedId = loadState<string>(STORAGE_KEYS.batchId);
      setBatch(items.find((item) => item.id === savedId) || items[0] || null);
    }).catch((err) => {
      if (!cancelled) setError(readableError(err, '加载批量任务失败'));
    });
    return () => { cancelled = true; };
  }, []);
  /* eslint-enable react-hooks/set-state-in-effect */

  useEffect(() => {
    if (ready && profile) saveState(STORAGE_KEYS.batchForm, { profile_id: profile.profile_id, directions, tone });
  }, [ready, profile, directions, tone]);

  const batchActive = isActive(batch);
  // Keep the active job fresh even while the user reads an older batch.
  const activeBatchId = history.find(isActive)?.id || (batchActive ? batch?.id : undefined);
  useEffect(() => {
    if (!activeBatchId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await apiFetch<BatchResponse>(`/api/batches/${activeBatchId}`);
        if (cancelled) return;
        setBatch((current) => current?.id === next.id ? next : current);
        setHistory((items) => items.map((item) => item.id === next.id ? next : item));
        setPollError('');
        if (!isActive(next)) return;
      } catch (err) {
        if (cancelled) return;
        setPollError(readableError(err, '进度刷新失败，将继续尝试连接'));
        if (err instanceof ApiError && err.status === 404) {
          setBatch((current) => current?.id === activeBatchId ? null : current);
          setHistory((items) => items.filter((item) => item.id !== activeBatchId));
          return;
        }
      }
      timer = setTimeout(() => { void poll(); }, 2500);
    }
    timer = setTimeout(() => { void poll(); }, 1500);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [activeBatchId]);

  function selectBatch(next: BatchResponse) {
    selectionVersion.current += 1;
    setBatch(next);
    setPollError('');
    saveState(STORAGE_KEYS.batchId, next.id);
  }

  function updateDirection(id: string, changes: Partial<DirectionForm>) {
    setDirections((items) => items.map((item) => item.id === id ? { ...item, ...changes } : item));
    setFieldErrors({});
  }

  function updateEssay(direction: DirectionForm, type: EssayType, changes: Partial<EssayForm>) {
    updateDirection(direction.id, { essays: { ...direction.essays, [type]: { ...direction.essays[type], ...changes } } });
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!profile || actionLock.current) return;
    if (!pendingRequest) {
      const errors = validateDirections(directions);
      setFieldErrors(errors);
      if (Object.keys(errors).length) {
        setError('请检查方向和文书要求，再开始批量生成。');
        document.getElementById(Object.keys(errors)[0])?.focus();
        return;
      }
    }
    const request = pendingRequest || {
      profile_id: profile.profile_id, request_id: crypto.randomUUID(),
      tone, directions: directionInputs(directions),
    } satisfies BatchRequest;
    // Retry an uncertain response with the same persisted request identifier.
    saveState(STORAGE_KEYS.batchSubmission, request);
    setPendingRequest(request);
    actionLock.current = true;
    setBusy(true);
    setError('');
    try {
      const next = await apiFetch<BatchResponse>('/api/batches', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request),
      });
      selectBatch(next);
      setHistory((items) => [next, ...items.filter((item) => item.id !== next.id)]);
      setPendingRequest(null);
      removeState(STORAGE_KEYS.batchSubmission);
    } catch (err) {
      setError(readableError(err, '创建批量任务失败'));
      if (err instanceof ApiError && err.status >= 400 && err.status < 500) {
        setPendingRequest(null);
        removeState(STORAGE_KEYS.batchSubmission);
      }
    } finally {
      actionLock.current = false;
      setBusy(false);
    }
  }

  async function retryFailed() {
    if (!batch || actionLock.current) return;
    actionLock.current = true;
    setBusy(true);
    setError('');
    try {
      const next = await apiFetch<BatchResponse>(`/api/batches/${batch.id}/retry`, { method: 'POST' });
      selectBatch(next);
      setHistory((items) => items.map((item) => item.id === next.id ? next : item));
    } catch (err) {
      setError(readableError(err, '重试失败'));
    } finally {
      actionLock.current = false;
      setBusy(false);
    }
  }

  async function openResult(item: BatchItem) {
    if (!item.session_id || actionLock.current) return;
    actionLock.current = true;
    setBusy(true);
    setError('');
    try {
      const next = await apiFetch<SessionSnapshot>(`/api/session/${item.session_id}`);
      saveState(STORAGE_KEYS.storySession, {
        session_id: next.session_id, profile_id: next.profile_id, analysis_id: next.analysis_id,
        cards: next.cards, messages: next.messages, round_no: next.round_no, status: next.status,
      } satisfies StorySessionState);
      saveState(STORAGE_KEYS.resultSnapshot, next);
      router.push('/result');
    } catch (err) {
      setError(readableError(err, '打开文书失败'));
    } finally {
      actionLock.current = false;
      setBusy(false);
    }
  }

  async function refreshHistory() {
    if (actionLock.current) return;
    actionLock.current = true;
    setBusy(true);
    setError('');
    try {
      const items = await apiFetch<BatchResponse[]>('/api/batches');
      setHistory(items);
      const current = items.find((item) => item.id === batch?.id) || items[0];
      if (current) selectBatch(current);
      else setBatch(null);
    } catch (err) {
      setError(readableError(err, '刷新任务失败'));
    } finally {
      actionLock.current = false;
      setBusy(false);
    }
  }

  const completed = batch?.items.filter((item) => item.status === 'completed' && item.draft) || [];
  const failed = batch?.items.filter((item) => item.status === 'failed') || [];
  const total = directions.reduce((count, direction) => count + ESSAY_TYPES.filter((type) => direction.essays[type].enabled).length, 0);
  const anotherActive = history.some(isActive);
  const formLocked = busy || Boolean(pendingRequest);

  return (
    <main className="section">
      <div className="container batch-stack">
        <section className="card">
          <div className="kicker">一份背景 · 多个方向</div>
          <h1 className="section-title">批量生成 PS 与 ML</h1>
          <p className="muted">为每个申请方向独立分析项目、生成中文大纲和英文草稿。可同时生成两类文书，完成后继续修改或下载。</p>
          <p className="notice">批量模式直接使用已录入的个人资料，跳过故事问答。请先补充真实经历、申请动机和职业目标，生成后核对初稿。</p>
          {!ready ? <p role="status">正在加载个人资料与任务…</p> : profile ? (
            <p className="batch-profile">当前背景：<strong>{profile.profile.basic_profile.full_name || '申请者'}</strong> · {profile.profile.basic_profile.current_university} · {profile.profile.basic_profile.major} <Link href="/profile">编辑背景 →</Link></p>
          ) : <p className="notice"><Link href="/profile">先录入个人信息 →</Link>，完成后选择“继续：批量生成”。已有批量任务仍可在下方查看。</p>}
          {error ? <p className="notice" role="alert">{error}</p> : null}
          {pendingRequest ? <p className="notice" role="status">上次提交结果尚未确认。点击“确认上次提交”将使用原任务编号重新查询或提交，避免重复生成。</p> : null}
          {profile ? (
            <form onSubmit={submit} noValidate>
              <fieldset className="batch-fieldset" disabled={formLocked}>
                <legend className="sr-only">申请方向与文书要求</legend>
                <div className="field">
                  <label htmlFor="batch-tone">统一写作语气</label>
                  <select id="batch-tone" value={tone} onChange={(event) => setTone(event.target.value as BatchTone)}>
                    <option value="balanced">均衡自然</option><option value="authentic">真实个人化</option>
                    <option value="academic">学术严谨</option><option value="concise">简洁直接</option>
                  </select>
                </div>
                <FieldError id="directions" errors={fieldErrors} />
                <div className="batch-stack">
                  {directions.map((direction, index) => (
                    <fieldset className="batch-direction" key={direction.id}>
                      <legend>方向 {index + 1}</legend>
                      <div className="batch-heading">
                        <p className="muted">分别填写这个方向的 PS 和 ML 要求。</p>
                        <button type="button" className="btn-secondary" disabled={directions.length <= 1} onClick={() => setDirections((items) => items.filter((item) => item.id !== direction.id))}>移除方向 {index + 1}</button>
                      </div>
                      <div className="grid-2">
                        <div className="field">
                          <label htmlFor={`${direction.id}-school`}>学校名称<span className="required-mark">必填</span></label>
                          <input id={`${direction.id}-school`} required maxLength={200} value={direction.school_name} aria-invalid={Boolean(fieldErrors[`${direction.id}-school`])} onChange={(event) => updateDirection(direction.id, { school_name: event.target.value })} />
                          <FieldError id={`${direction.id}-school`} errors={fieldErrors} />
                        </div>
                        <div className="field">
                          <label htmlFor={`${direction.id}-program`}>项目名称 / 专业方向<span className="required-mark">必填</span></label>
                          <input id={`${direction.id}-program`} required maxLength={200} placeholder="例如 MSc Data Science" value={direction.program_name} aria-invalid={Boolean(fieldErrors[`${direction.id}-program`])} onChange={(event) => updateDirection(direction.id, { program_name: event.target.value })} />
                          <FieldError id={`${direction.id}-program`} errors={fieldErrors} />
                        </div>
                      </div>
                      <div className="field">
                        <label htmlFor={`${direction.id}-details`}>项目官网资料 / 课程与研究方向<span className="optional-mark">选填</span></label>
                        <textarea id={`${direction.id}-details`} maxLength={30000} value={direction.program_details} onChange={(event) => updateDirection(direction.id, { program_details: event.target.value })} placeholder="粘贴已核实的项目资料，帮助文书写出具体的匹配理由。" />
                        <FieldError id={`${direction.id}-details`} errors={fieldErrors} />
                      </div>
                      <div id={`${direction.id}-types`} tabIndex={-1}><FieldError id={`${direction.id}-types`} errors={fieldErrors} /></div>
                      <div className="grid-2">
                        {ESSAY_TYPES.map((type) => {
                          const essay = direction.essays[type];
                          const prefix = `${direction.id}-${type === 'Personal Statement' ? 'ps' : 'ml'}`;
                          return (
                            <div className="batch-essay" key={type}>
                              <label className="batch-checkbox"><input type="checkbox" checked={essay.enabled} onChange={(event) => updateEssay(direction, type, { enabled: event.target.checked })} />{essayLabel(type)}</label>
                              {essay.enabled ? <>
                                <div className="field">
                                  <label htmlFor={`${prefix}-words`}>目标字数<span className="required-mark">必填</span></label>
                                  <input id={`${prefix}-words`} type="number" min={100} max={5000} step={1} required value={essay.word_limit} aria-invalid={Boolean(fieldErrors[`${prefix}-words`])} onChange={(event) => updateEssay(direction, type, { word_limit: event.target.value })} />
                                  <FieldError id={`${prefix}-words`} errors={fieldErrors} />
                                </div>
                                <div className="field">
                                  <label htmlFor={`${prefix}-prompt`}>文书题目 / 具体要求<span className="required-mark">必填</span></label>
                                  <textarea id={`${prefix}-prompt`} required minLength={10} maxLength={20000} value={essay.prompt_text} aria-invalid={Boolean(fieldErrors[`${prefix}-prompt`])} onChange={(event) => updateEssay(direction, type, { prompt_text: event.target.value })} placeholder={type === 'Personal Statement' ? '填写 PS 题目，或说明希望呈现的经历、成长与目标。' : '填写 ML 题目，或说明申请动机、项目匹配与职业计划。'} />
                                  <FieldError id={`${prefix}-prompt`} errors={fieldErrors} />
                                </div>
                              </> : <p className="muted">这个方向不生成此类文书。</p>}
                            </div>
                          );
                        })}
                      </div>
                    </fieldset>
                  ))}
                </div>
                <div className="actions">
                  <button className="btn-secondary" type="button" disabled={directions.length >= MAX_DIRECTIONS} onClick={() => setDirections((items) => [...items, newDirection()])}>+ 添加方向（{directions.length}/{MAX_DIRECTIONS}）</button>
                </div>
              </fieldset>
              <div className="form-footer batch-heading">
                <span className="muted">共 {directions.length} 个方向、{total} 篇文书。逐篇生成，耗时随篇数和字数增加。</span>
                <button className="btn" type="submit" disabled={busy || !ready || (!pendingRequest && anotherActive)}>{busy ? '正在处理…' : pendingRequest ? '确认上次提交' : `开始批量生成 ${total} 篇`}</button>
              </div>
              {anotherActive ? <p className="muted">当前有任务正在处理，完成后可提交下一批。</p> : null}
            </form>
          ) : null}
        </section>

        <section className="card" aria-labelledby="batch-results-title">
          <div className="batch-heading">
            <h2 className="section-title" id="batch-results-title">批量任务与结果</h2>
            <button className="btn-secondary" type="button" disabled={busy || !ready} onClick={() => { void refreshHistory(); }}>刷新任务</button>
          </div>
          {history.length ? <div className="field">
            <label htmlFor="batch-history">查看已保存的批次</label>
            <select id="batch-history" value={batch?.id || ''} disabled={busy} onChange={(event) => { const next = history.find((item) => item.id === event.target.value); if (next) selectBatch(next); }}>
              {history.map((item) => <option key={item.id} value={item.id}>{new Date(item.created_at).toLocaleString('zh-CN')} · {item.items[0]?.program.school_name} · {item.items.length} 篇 · {statusLabels[item.status]}</option>)}
            </select>
          </div> : <p className="muted">还没有批量任务。填写方向后，一次提交即可开始生成。</p>}
          {batch ? <>
            <div className="batch-heading">
              <p role="status" aria-live="polite"><span className="badge">{statusLabels[batch.status]}</span> 已完成 {completed.length}/{batch.items.length} 篇{failed.length ? `，失败 ${failed.length} 篇` : ''}</p>
              <div className="actions">
                {failed.length && !batchActive ? <button className="btn-secondary" type="button" disabled={busy || anotherActive} onClick={() => { void retryFailed(); }}>仅重试失败项（{failed.length}）</button> : null}
                <button className="btn-secondary" type="button" disabled={!completed.length} onClick={() => downloadText(completed.map((item) => `## 方向 ${item.direction_index + 1} · ${item.program.school_name} · ${item.program.program_name}\n\n### ${item.program.essay_type}\n\n${item.draft}`).join('\n\n---\n\n'), `GradPilot-${batch.id.slice(0, 8)}.md`, true)}>下载已完成文书（合并 Markdown）</button>
              </div>
            </div>
            <progress className="batch-progress" aria-label="文书完成进度" max={batch.items.length} value={completed.length} />
            {batchActive ? <p className="muted">后台正在逐篇处理，进度自动刷新。关闭或刷新页面后，可在同一浏览器重新查看。</p> : null}
            {pollError ? <p className="notice" role="alert">{pollError}</p> : null}
            <div className="batch-stack">
              {batch.items.map((item) => <article className="batch-output" key={item.id}>
                <div className="batch-heading">
                  <div><h3>方向 {item.direction_index + 1} · {item.program.school_name} · {item.program.program_name}</h3><p className="muted">{item.program.essay_type} · 目标 {item.program.word_limit} 词</p></div>
                  <span className={`badge batch-status-${item.status}`}>{stageLabels[item.stage]}</span>
                </div>
                {item.status === 'failed' ? <p className="notice" role="alert">{readableError(new ApiError(item.error_message || '生成失败，请重试。', 502, item.error_code || 'internal_error'))}</p> : null}
                {item.status === 'completed' && item.draft ? <>
                  <details><summary>预览英文草稿（{item.draft.trim().split(/\s+/).length} 词）</summary><div className="batch-draft">{item.draft}</div></details>
                  <div className="actions"><button className="btn-secondary" type="button" onClick={() => downloadText(item.draft || '', `${item.direction_index + 1}-${item.program.school_name}-${item.program.program_name}-${item.program.essay_type}.txt`)}>下载这篇文书</button><button className="btn" type="button" disabled={busy} onClick={() => { void openResult(item); }}>查看大纲 / 继续修改</button></div>
                </> : null}
              </article>)}
            </div>
          </> : null}
        </section>
      </div>
    </main>
  );
}
