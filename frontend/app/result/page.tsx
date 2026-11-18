'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiFetch, readableError } from '@/lib/api';
import { loadState, removeState, saveState, STORAGE_KEYS } from '@/lib/storage';
import type {
  AnalysisResponse,
  ArtifactVersion,
  HistoryItem,
  ProfileResponse,
  ProgramFormState,
  SessionSnapshot,
  StorySessionState,
} from '@/lib/types';

const tabs = ['大纲', '草稿'] as const;

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
    program_details: next.program.program_details || '',
  } satisfies ProgramFormState);
}

export default function ResultPage() {
  const router = useRouter();
  const [session, setSession] = useState<StorySessionState | null>(null);
  const [snapshot, setSnapshot] = useState<SessionSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [activeTab, setActiveTab] = useState<(typeof tabs)[number]>('大纲');
  const [revisionInstruction, setRevisionInstruction] = useState('');
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [selectedArtifact, setSelectedArtifact] = useState<ArtifactVersion | null>(null);

  const fetchSnapshot = useCallback(async (sessionId: string): Promise<SessionSnapshot | null> => {
    setLoading(true);
    setError('');
    try {
      const next = await apiFetch<SessionSnapshot>(`/api/session/${sessionId}`);
      setSnapshot(next);
      cacheSnapshotContext(next);
      saveState(STORAGE_KEYS.resultSnapshot, next);
      return next;
    } catch (err) {
      setError(readableError(err, '加载会话信息失败'));
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const refreshHistory = useCallback(async () => {
    try {
      const items = await apiFetch<HistoryItem[]>('/api/history');
      setHistory(items);
    } catch (err) {
      setError((current) => current || readableError(err, '加载历史记录失败'));
    }
  }, []);

  useEffect(() => {
    const savedSession = loadState<StorySessionState>(STORAGE_KEYS.storySession);
    setSession(savedSession);
    if (savedSession?.session_id) {
      void fetchSnapshot(savedSession.session_id);
    } else {
      setError('还没有可用的故事会话，请先完成故事挖掘。');
    }
    void refreshHistory();
    removeState(STORAGE_KEYS.legacyHistory);
  }, [fetchSnapshot, refreshHistory]);

  async function generateOutline() {
    if (!session?.session_id || snapshot?.status !== 'ready') return;
    setLoading(true);
    setError('');
    try {
      await apiFetch('/api/essay/outline', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: session.session_id }),
      });
      await fetchSnapshot(session.session_id);
      await refreshHistory();
      setSelectedArtifact(null);
      setActiveTab('大纲');
    } catch (err) {
      setError(readableError(err, '生成大纲失败'));
    } finally {
      setLoading(false);
    }
  }

  async function generateDraft(rewrite = false) {
    if (!session?.session_id || !snapshot) return;
    if (rewrite && !revisionInstruction.trim()) {
      setError('请先输入修改意见。');
      return;
    }

    setLoading(true);
    setError('');
    try {
      await apiFetch('/api/essay/draft', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: session.session_id,
          tone: 'balanced',
          target_length: snapshot.program.word_limit,
          revision_instruction: rewrite ? revisionInstruction.trim() : '',
        }),
      });
      await fetchSnapshot(session.session_id);
      await refreshHistory();
      setSelectedArtifact(null);
      setRevisionInstruction('');
      setActiveTab('草稿');
    } catch (err) {
      setError(readableError(err, '生成草稿失败'));
    } finally {
      setLoading(false);
    }
  }

  async function runReview() {
    if (!session?.session_id || !snapshot?.draft) return;
    setLoading(true);
    setError('');
    try {
      await apiFetch('/api/review/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: session.session_id }),
      });
      await fetchSnapshot(session.session_id);
      setActiveTab('草稿');
    } catch (err) {
      setError(readableError(err, '审核草稿失败'));
    } finally {
      setLoading(false);
    }
  }

  async function loadRecord(item: HistoryItem) {
    setLoading(true);
    setError('');
    try {
      const next = await apiFetch<SessionSnapshot>(`/api/session/${item.session_id}`);
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
      setActiveTab(next.draft ? '草稿' : '大纲');
    } catch (err) {
      setError(readableError(err, '加载历史记录失败'));
    } finally {
      setLoading(false);
    }
  }

  async function clearHistory() {
    if (!window.confirm('确认清空当前浏览器的全部申请记录？此操作不可恢复。')) return;
    setLoading(true);
    try {
      await apiFetch('/api/history', { method: 'DELETE' });
      setHistory([]);
      setSnapshot(null);
      setSession(null);
      removeState(STORAGE_KEYS.storySession);
      removeState(STORAGE_KEYS.resultSnapshot);
      removeState(STORAGE_KEYS.profile);
      removeState(STORAGE_KEYS.analysis);
      removeState(STORAGE_KEYS.programForm);
    } catch (err) {
      setError(readableError(err, '清空历史失败'));
    } finally {
      setLoading(false);
    }
  }

  function downloadDraft() {
    const draft = selectedArtifact?.draft || snapshot?.draft;
    if (!draft) return;
    const blob = new Blob([draft], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `gradpilot-draft-${selectedArtifact?.version_no || 'latest'}.txt`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  const visibleOutline = selectedArtifact?.outline || snapshot?.outline;
  const visibleDraft = selectedArtifact?.draft || snapshot?.draft;
  const hasHistory = useMemo(() => history.length > 0, [history]);
  const canGenerate = snapshot?.status === 'ready';

  return (
    <main className="section">
      <div className="container">
        <div className="card">
          <div className="kicker">第 4 步</div>
          <h1 className="section-title">生成中文大纲与英文草稿</h1>
          {snapshot ? (
            <p className="muted">
              {snapshot.program.school_name} · {snapshot.program.program_name} · {snapshot.program.essay_type} · 目标 {snapshot.program.word_limit} 词
            </p>
          ) : (
            <p className="muted">先生成中文大纲，再生成英文草稿。</p>
          )}
          {snapshot?.status === 'interviewing' ? (
            <p className="notice">请先完成三轮故事挖掘，再生成大纲和草稿。</p>
          ) : null}
          {error ? <p className="notice" role="alert">{error}</p> : null}
          <div className="actions">
            <button className="btn-secondary" type="button" onClick={generateOutline} disabled={loading || !canGenerate}>
              生成中文大纲
            </button>
            <button className="btn" type="button" onClick={() => generateDraft(false)} disabled={loading || !canGenerate}>
              {loading ? '处理中...' : '生成英文草稿'}
            </button>
          </div>
        </div>

        <div className="card" style={{ marginTop: 16 }}>
          <div className="tabs">
            {tabs.map((tab) => (
              <button
                key={tab}
                type="button"
                className={`tab ${activeTab === tab ? 'active' : ''}`}
                onClick={() => setActiveTab(tab)}
              >
                {tab}
              </button>
            ))}
          </div>

          {selectedArtifact ? (
            <p className="notice success">
              正在查看历史版本 v{selectedArtifact.version_no}。生成新内容前会回到当前版本。
            </p>
          ) : null}
          {!snapshot && !loading ? <p className="muted">暂无已生成内容。</p> : null}

          {activeTab === '大纲' && visibleOutline ? (
            <div>
              <h3>{visibleOutline.title || '文书大纲'}</h3>
              {visibleOutline.paragraphs.map((paragraph, index) => (
                <div key={`${paragraph.heading}-${index}`} className="mini-card" style={{ marginBottom: 12 }}>
                  <h4>{paragraph.heading}</h4>
                  <p><strong>目标：</strong>{paragraph.goal}</p>
                  <p><strong>核心内容：</strong>{paragraph.key_content}</p>
                  <p><strong>可使用经历：</strong>{paragraph.use_this_experience}</p>
                  <p><strong>重点突出：</strong>{paragraph.what_to_highlight}</p>
                </div>
              ))}
            </div>
          ) : null}

          {activeTab === '草稿' ? (
            <div>
              {visibleDraft ? <pre className="code-block">{visibleDraft}</pre> : <p className="muted">尚未生成草稿。</p>}
              {visibleDraft ? (
                <div className="actions">
                  <button className="btn-secondary" type="button" onClick={downloadDraft}>下载草稿</button>
                  <button className="btn-secondary" type="button" onClick={runReview} disabled={loading || !!selectedArtifact}>
                    审核当前草稿
                  </button>
                </div>
              ) : null}
              <div className="field" style={{ marginTop: 12 }}>
                <label htmlFor="revision-instruction">对草稿的修改意见</label>
                <textarea
                  id="revision-instruction"
                  value={revisionInstruction}
                  onChange={(event) => setRevisionInstruction(event.target.value)}
                  placeholder="例如：加强开头故事感，突出产品思维，并压缩第二段。"
                />
              </div>
              <div className="form-footer">
                <button
                  className="btn-secondary"
                  type="button"
                  onClick={() => generateDraft(true)}
                  disabled={loading || !snapshot?.draft || !revisionInstruction.trim()}
                >
                  按意见重写草稿
                </button>
              </div>
              {snapshot?.review ? (
                <div className="mini-card">
                  <h3>草稿审核</h3>
                  <p><strong>优势：</strong>{snapshot.review.strengths.join('；')}</p>
                  <p><strong>问题：</strong>{snapshot.review.weaknesses.join('；')}</p>
                  <p><strong>模板化表达：</strong>{snapshot.review.template_like_phrases.join('；') || '未发现明显问题'}</p>
                  <p><strong>建议补充：</strong>{snapshot.review.suggested_details_to_add.join('；')}</p>
                  <p><strong>调整建议：</strong>{snapshot.review.adaptation_tip}</p>
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
                  <div className="form-footer" style={{ margin: 0, justifyContent: 'space-between', alignItems: 'center' }}>
                    <span>
                      {version.artifact_type === 'outline' ? '大纲' : '草稿'} v{version.version_no} · {new Date(version.created_at).toLocaleString('zh-CN')}
                    </span>
                    <button
                      className="btn-secondary"
                      type="button"
                      onClick={() => {
                        setSelectedArtifact(version);
                        setActiveTab(version.artifact_type === 'outline' ? '大纲' : '草稿');
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
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
            <h2 style={{ margin: 0 }}>历史记录</h2>
            {hasHistory ? (
              <button className="btn-secondary" type="button" onClick={clearHistory} disabled={loading}>
                清空全部历史
              </button>
            ) : null}
          </div>
          {!hasHistory ? <p className="muted">还没有历史记录。完成故事挖掘后会自动保存。</p> : null}
          {history.map((item) => (
            <div key={item.session_id} className="mini-card" style={{ marginTop: 12 }}>
              <p style={{ margin: 0, fontWeight: 700 }}>{item.program_label}</p>
              <p className="muted" style={{ margin: '6px 0 10px' }}>
                {item.applicant} · {item.status === 'ready' ? '可生成' : `第 ${item.round_no}/3 轮`} · {new Date(item.updated_at).toLocaleString('zh-CN')}
              </p>
              {item.draft_preview ? <p className="muted">{item.draft_preview}...</p> : null}
              <button className="btn-secondary" type="button" onClick={() => loadRecord(item)}>
                加载这次记录
              </button>
            </div>
          ))}
        </div>

        <div className="form-footer" style={{ marginTop: 16 }}>
          <button className="btn-secondary" type="button" onClick={() => router.push('/story')}>
            返回故事挖掘
          </button>
        </div>
      </div>
    </main>
  );
}
