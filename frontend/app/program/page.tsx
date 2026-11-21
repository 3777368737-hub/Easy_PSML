"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiFetch, readableError } from "@/lib/api";
import { loadState, removeState, saveState, STORAGE_KEYS } from "@/lib/storage";
import type {
  AnalysisResponse,
  ProfileResponse,
  ProgramFormState,
} from "@/lib/types";

const defaultForm: ProgramFormState = {
  school_name: "",
  program_name: "",
  essay_type: "Personal Statement",
  word_limit: "800",
  prompt_text: "",
  program_details: "",
};

type ProgramFieldErrors = Partial<Record<keyof ProgramFormState, string>>;

export default function ProgramPage() {
  const router = useRouter();
  const [profile, setProfile] = useState<ProfileResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<ProgramFieldErrors>({});
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [form, setForm] = useState<ProgramFormState>(defaultForm);

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    const currentProfile = loadState<ProfileResponse>(STORAGE_KEYS.profile);
    setProfile(currentProfile);

    if (!currentProfile?.profile_id) {
      setAnalysis(null);
      return;
    }

    const savedForm = loadState<ProgramFormState>(STORAGE_KEYS.programForm);
    if (savedForm)
      setForm({
        ...defaultForm,
        ...savedForm,
        program_details: savedForm.program_details || "",
      });

    const savedAnalysis = loadState<AnalysisResponse>(STORAGE_KEYS.analysis);
    if (
      savedAnalysis?.profile_id === currentProfile.profile_id &&
      savedAnalysis.program
    ) {
      setAnalysis(savedAnalysis);
      setForm({
        school_name: savedAnalysis.program.school_name,
        program_name: savedAnalysis.program.program_name,
        essay_type: savedAnalysis.program.essay_type,
        word_limit: String(savedAnalysis.program.word_limit),
        prompt_text: savedAnalysis.program.prompt_text,
        program_details: savedAnalysis.program.program_details || "",
      });
    } else {
      setAnalysis(null);
    }
  }, []);
  /* eslint-enable react-hooks/set-state-in-effect */

  function update(name: keyof ProgramFormState, value: string) {
    setForm((current) => ({ ...current, [name]: value }));
    setAnalysis(null);
    setFieldErrors((current) => ({ ...current, [name]: undefined }));
  }

  function validateForm(): ProgramFieldErrors {
    const next: ProgramFieldErrors = {};
    if (!profile?.profile_id)
      next.school_name = "请先完成第 1 步：背景信息填写。";
    if (!form.school_name.trim()) next.school_name = "请填写学校名称。";
    if (!form.program_name.trim()) next.program_name = "请填写项目名称。";
    if (!form.essay_type.trim()) next.essay_type = "请选择文书类型。";
    if (!form.prompt_text.trim() || form.prompt_text.trim().length < 10) {
      next.prompt_text = "请填写至少 10 个字符的文书题目或具体要求。";
    }
    const wordLimit = Number(form.word_limit);
    if (!Number.isInteger(wordLimit) || wordLimit < 100 || wordLimit > 5000) {
      next.word_limit = "字数上限必须是 100 到 5000 之间的整数。";
    }
    return next;
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const validationErrors = validateForm();
    if (Object.keys(validationErrors).length > 0 || !profile) {
      setFieldErrors(validationErrors);
      setError("请补全标记为“必填”的信息后再开始分析。");
      const firstField = Object.keys(validationErrors)[0];
      if (firstField) document.getElementById(`program-${firstField}`)?.focus();
      return;
    }

    setLoading(true);
    setError("");
    setFieldErrors({});
    try {
      const result = await apiFetch<AnalysisResponse>("/api/program/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          profile_id: profile.profile_id,
          school_name: form.school_name.trim(),
          program_name: form.program_name.trim(),
          essay_type: form.essay_type,
          word_limit: Number(form.word_limit),
          prompt_text: form.prompt_text.trim(),
          program_details: form.program_details.trim(),
        }),
      });
      setAnalysis(result);
      saveState(STORAGE_KEYS.analysis, result);
      saveState(STORAGE_KEYS.programForm, form);
      removeState(STORAGE_KEYS.storySession);
      removeState(STORAGE_KEYS.resultSnapshot);
    } catch (err) {
      setError(readableError(err, "项目分析失败"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="section">
      <div className="container">
        <div className="page-intro">
          <div className="kicker">FIND YOUR FIT</div>
          <h1 className="section-title">找到你与项目的连接。</h1>
          <p className="muted">把项目要求和文书题目，转成具体的写作策略。</p>
          <p className="muted">
            申请多个方向？
            <Link className="text-link" href="/batch">
              复用当前背景，批量生成 PS 与 ML
            </Link>
          </p>
        </div>
        <div className="program-layout">
          <div className="card">
            <h2 className="form-section-title">目标项目</h2>
            <p className="section-help">粘贴官方要求，让分析更有依据。</p>
            {!profile ? (
              <p className="notice" role="alert">
                请先完成背景信息页。
                <Link className="text-link" href="/profile">
                  填写背景信息
                </Link>
              </p>
            ) : null}
            {error ? (
              <p className="notice" role="alert">
                {error}
              </p>
            ) : null}

            <form onSubmit={handleSubmit} noValidate>
              <div className="grid-2">
                <div className="field">
                  <label htmlFor="program-school_name">
                    学校名称<span className="required-mark">必填</span>
                  </label>
                  <input
                    id="program-school_name"
                    placeholder="例如：HKUST"
                    required
                    aria-invalid={Boolean(fieldErrors.school_name)}
                    value={form.school_name}
                    onChange={(event) =>
                      update("school_name", event.target.value)
                    }
                  />
                  {fieldErrors.school_name ? (
                    <p className="field-error">{fieldErrors.school_name}</p>
                  ) : null}
                </div>
                <div className="field">
                  <label htmlFor="program-program_name">
                    项目名称<span className="required-mark">必填</span>
                  </label>
                  <input
                    id="program-program_name"
                    placeholder="例如：MSc in Data-Driven Modeling"
                    required
                    aria-invalid={Boolean(fieldErrors.program_name)}
                    value={form.program_name}
                    onChange={(event) =>
                      update("program_name", event.target.value)
                    }
                  />
                  {fieldErrors.program_name ? (
                    <p className="field-error">{fieldErrors.program_name}</p>
                  ) : null}
                </div>
                <div className="field">
                  <label htmlFor="program-essay_type">
                    文书类型<span className="required-mark">必填</span>
                  </label>
                  <select
                    id="program-essay_type"
                    required
                    aria-invalid={Boolean(fieldErrors.essay_type)}
                    value={form.essay_type}
                    onChange={(event) =>
                      update("essay_type", event.target.value)
                    }
                  >
                    <option value="Personal Statement">
                      Personal Statement
                    </option>
                    <option value="Motivation Letter">Motivation Letter</option>
                  </select>
                  {fieldErrors.essay_type ? (
                    <p className="field-error">{fieldErrors.essay_type}</p>
                  ) : null}
                </div>
                <div className="field">
                  <label htmlFor="program-word_limit">
                    字数上限<span className="required-mark">必填</span>
                  </label>
                  <input
                    id="program-word_limit"
                    type="number"
                    min={100}
                    max={5000}
                    step={1}
                    required
                    aria-invalid={Boolean(fieldErrors.word_limit)}
                    value={form.word_limit}
                    onChange={(event) =>
                      update("word_limit", event.target.value)
                    }
                  />
                  {fieldErrors.word_limit ? (
                    <p className="field-error">{fieldErrors.word_limit}</p>
                  ) : null}
                </div>
              </div>
              <div className="field">
                <label htmlFor="program-prompt_text">
                  文书题目 / 具体要求<span className="required-mark">必填</span>
                </label>
                <textarea
                  id="program-prompt_text"
                  placeholder="粘贴学校的文书题目或具体要求（至少 10 个字符）。"
                  required
                  aria-invalid={Boolean(fieldErrors.prompt_text)}
                  value={form.prompt_text}
                  onChange={(event) =>
                    update("prompt_text", event.target.value)
                  }
                />
                {fieldErrors.prompt_text ? (
                  <p className="field-error">{fieldErrors.prompt_text}</p>
                ) : null}
              </div>
              <div className="field">
                <label htmlFor="program-program_details">
                  项目官网资料 / 课程与教授方向
                  <span className="optional-mark">选填</span>
                </label>
                <textarea
                  id="program-program_details"
                  value={form.program_details}
                  onChange={(event) =>
                    update("program_details", event.target.value)
                  }
                  placeholder="可粘贴官网课程要求、项目培养目标、教授研究方向等，系统会优先依据这些信息分析。"
                />
              </div>
              {loading ? (
                <p className="busy-status" role="status">
                  <span className="spinner" />
                  正在结合你的背景分析项目，请稍候…
                </p>
              ) : null}
              <div className="form-footer">
                <button
                  className="btn-secondary"
                  type="button"
                  data-agent-capability="app.navigate"
                  data-agent-arg-path="/profile"
                  onClick={() => router.push("/profile")}
                >
                  返回上一页
                </button>
                <button
                  className="btn"
                  type="submit"
                  data-agent-capability="program.analyze"
                  disabled={loading || !profile}
                >
                  {loading ? "正在分析..." : "开始项目分析"}
                </button>
              </div>
            </form>
          </div>
          <aside className="guide-card">
            <h2>什么资料最有帮助？</h2>
            <ul>
              <li>学校发布的文书题目</li>
              <li>字数限制与内容要求</li>
              <li>课程设置和培养目标</li>
              <li>与你相关的研究方向</li>
            </ul>
            <div className="tip-divider">
              <h3>使用官网原文</h3>
              <p>直接粘贴文字内容。仅填写网址不会自动读取网页。</p>
            </div>
            <p>修改项目资料后，请重新分析，以确保写作策略与当前输入一致。</p>
          </aside>
        </div>

        {analysis ? (
          <div className="card" style={{ marginTop: 16 }}>
            <h2 className="section-title">
              {analysis.program.school_name} · {analysis.program.program_name}
            </h2>
            <p className="muted">
              {analysis.program.essay_type} · 目标字数{" "}
              {analysis.program.word_limit}
            </p>
            <div className="analysis-grid">
              <div className="mini-card">
                <h3>项目关注点</h3>
                <ul className="list">
                  {analysis.analysis.program_focus.map((item, index) => (
                    <li key={`${item}-${index}`}>{item}</li>
                  ))}
                </ul>
              </div>
              <div className="mini-card">
                <h3>匹配优势</h3>
                <ul className="list">
                  {analysis.analysis.matched_strengths.map((item, index) => (
                    <li key={`${item}-${index}`}>{item}</li>
                  ))}
                </ul>
              </div>
              <div className="mini-card">
                <h3>潜在短板</h3>
                <ul className="list">
                  {analysis.analysis.potential_gaps.map((item, index) => (
                    <li key={`${item}-${index}`}>{item}</li>
                  ))}
                </ul>
              </div>
              <div className="mini-card">
                <h3>写作建议</h3>
                <ul className="list">
                  {analysis.analysis.writing_suggestions.map((item, index) => (
                    <li key={`${item}-${index}`}>{item}</li>
                  ))}
                </ul>
              </div>
              <div className="mini-card">
                <h3>建议结构</h3>
                <ul className="list">
                  {analysis.analysis.recommended_structure.map(
                    (item, index) => (
                      <li key={`${item}-${index}`}>{item}</li>
                    ),
                  )}
                </ul>
              </div>
              <div className="mini-card">
                <h3>避免表达</h3>
                <ul className="list">
                  {analysis.analysis.avoid_phrases.length ? (
                    analysis.analysis.avoid_phrases.map((item, index) => (
                      <li key={`${item}-${index}`}>{item}</li>
                    ))
                  ) : (
                    <li className="muted">暂无</li>
                  )}
                </ul>
              </div>
            </div>
            <div className="form-footer">
              <button
                className="btn"
                type="button"
                data-agent-capability="program.continue_story"
                onClick={() => router.push("/story")}
              >
                进入故事挖掘
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </main>
  );
}
