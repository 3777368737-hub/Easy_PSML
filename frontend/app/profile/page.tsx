'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiFetch, readableError } from '@/lib/api';
import { clearDownstreamState, loadState, saveState, STORAGE_KEYS } from '@/lib/storage';
import type {
  ActivityAward,
  ExperienceItem,
  ProfileData,
  ProfileResponse,
} from '@/lib/types';

type ProfileForm = {
  full_name: string;
  current_university: string;
  major: string;
  gpa: string;
  graduation_year: string;
  english_test_score: string;
  target_degree: string;
  target_field: string;
  target_country: string;
  research_experience: string;
  internship_experience: string;
  project_experience: string;
  activities_awards: string;
  motivation_text: string;
  career_goal: string;
};

type ProfileFieldErrors = Partial<Record<keyof ProfileForm | 'experience', string>>;

const initialForm: ProfileForm = {
  full_name: '',
  current_university: '',
  major: '',
  gpa: '',
  graduation_year: '',
  english_test_score: '',
  target_degree: "Master's",
  target_field: '',
  target_country: '',
  research_experience: '',
  internship_experience: '',
  project_experience: '',
  activities_awards: '',
  motivation_text: '',
  career_goal: '',
};

function safeText(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function mergeText(current: string, incoming: unknown): string {
  return safeText(incoming) || current;
}

function formatExperienceList(list: ExperienceItem[] | undefined): string {
  if (!Array.isArray(list)) return '';
  return list
    .map((item) => [safeText(item.title), safeText(item.summary), safeText(item.impact)].filter(Boolean).join(' | '))
    .filter(Boolean)
    .join('\n');
}

function formatActivities(list: ActivityAward[] | undefined): string {
  if (!Array.isArray(list)) return '';
  return list
    .map((item) => [safeText(item.title), safeText(item.summary)].filter(Boolean).join(' | '))
    .filter(Boolean)
    .join('\n');
}

function applyProfileToForm(current: ProfileForm, profile: ProfileData): ProfileForm {
  const basic = profile.basic_profile;
  return {
    ...current,
    full_name: mergeText(current.full_name, basic.full_name),
    current_university: mergeText(current.current_university, basic.current_university),
    major: mergeText(current.major, basic.major),
    gpa: mergeText(current.gpa, basic.gpa),
    graduation_year: mergeText(current.graduation_year, basic.graduation_year),
    english_test_score: mergeText(current.english_test_score, basic.english_test_score),
    target_degree: mergeText(current.target_degree, basic.target_degree),
    target_field: mergeText(current.target_field, basic.target_field),
    target_country: mergeText(current.target_country, basic.target_country),
    research_experience: mergeText(current.research_experience, formatExperienceList(profile.research_experiences)),
    internship_experience: mergeText(current.internship_experience, formatExperienceList(profile.internships)),
    project_experience: mergeText(current.project_experience, formatExperienceList(profile.projects)),
    activities_awards: mergeText(current.activities_awards, formatActivities(profile.activities_awards)),
    motivation_text: mergeText(current.motivation_text, profile.motivation_summary),
    career_goal: mergeText(current.career_goal, profile.career_goal),
  };
}

function toFormData(form: ProfileForm, file: File | null, strictProfile: boolean): FormData {
  const data = new FormData();
  Object.entries(form).forEach(([key, value]) => data.append(key, value));
  if (file) data.append('resume_file', file);
  data.append('strict_profile', strictProfile ? 'true' : 'false');
  return data;
}

export default function ProfilePage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [parsingResume, setParsingResume] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [fieldErrors, setFieldErrors] = useState<ProfileFieldErrors>({});
  const [file, setFile] = useState<File | null>(null);
  const [form, setForm] = useState<ProfileForm>(initialForm);

  useEffect(() => {
    const saved = loadState<ProfileResponse>(STORAGE_KEYS.profile);
    // Browser storage is unavailable during server rendering, so hydration must initialize it.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (saved?.profile) setForm((current) => applyProfileToForm(current, saved.profile));
  }, []);

  function update(name: keyof ProfileForm, value: string) {
    setForm((current) => ({ ...current, [name]: value }));
    setFieldErrors((current) => ({
      ...current,
      [name]: undefined,
      ...(['research_experience', 'internship_experience', 'project_experience', 'activities_awards'].includes(name)
        ? { experience: undefined }
        : {}),
    }));
  }

  function validateFile(selected: File | null): string {
    if (!selected) return '请先选择简历文件。';
    if (selected.size > 10 * 1024 * 1024) return '简历文件不能超过 10 MB。';
    const suffix = selected.name.toLowerCase().split('.').pop();
    if (!suffix || !['txt', 'md', 'pdf', 'docx'].includes(suffix)) {
      return '仅支持 txt、md、pdf、docx 格式。';
    }
    return '';
  }

  function validateRequiredFields(): ProfileFieldErrors {
    const next: ProfileFieldErrors = {};
    if (!form.full_name.trim()) next.full_name = '请填写姓名。';
    if (!form.current_university.trim()) next.current_university = '请填写当前学校。';
    if (!form.major.trim()) next.major = '请填写当前专业。';
    if (!form.target_degree.trim()) next.target_degree = '请选择目标学位。';
    if (!form.target_field.trim()) next.target_field = '请填写目标专业方向。';
    if (!form.target_country.trim()) next.target_country = '请填写目标国家/地区。';
    const hasExperience = [
      form.research_experience,
      form.internship_experience,
      form.project_experience,
      form.activities_awards,
    ].some((value) => value.trim().length > 0);
    if (!file && !hasExperience) {
      next.experience = '请上传简历，或至少填写一项科研、实习、项目或活动经历。';
    }
    return next;
  }

  function focusFirstError(errors: ProfileFieldErrors) {
    const fieldIds: Array<[keyof ProfileFieldErrors, string]> = [
      ['full_name', 'full-name'],
      ['current_university', 'current-university'],
      ['major', 'major'],
      ['target_degree', 'target-degree'],
      ['target_field', 'target-field'],
      ['target_country', 'target-country'],
      ['experience', 'research-experience'],
    ];
    const first = fieldIds.find(([key]) => errors[key]);
    if (first) document.getElementById(first[1])?.focus();
  }

  async function parseResume() {
    const fileError = validateFile(file);
    if (fileError) {
      setError(fileError);
      return;
    }

    setParsingResume(true);
    setError('');
    setNotice('');
    try {
      const result = await apiFetch<ProfileResponse>('/api/profile/extract', {
        method: 'POST',
        body: toFormData(form, file, false),
      });
      clearDownstreamState();
      setForm((current) => applyProfileToForm(current, result.profile));
      setFieldErrors({});
      saveState(STORAGE_KEYS.profile, result);
      setNotice('简历解析完成，已回填。请核对内容后继续。');
    } catch (err) {
      setError(readableError(err, '简历解析失败'));
    } finally {
      setParsingResume(false);
    }
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const fileError = file ? validateFile(file) : '';
    if (fileError) {
      setError(fileError);
      return;
    }
    const validationErrors = validateRequiredFields();
    if (Object.keys(validationErrors).length > 0) {
      setFieldErrors(validationErrors);
      setError('请补全标记为“必填”的信息后再继续。');
      setNotice('');
      focusFirstError(validationErrors);
      return;
    }

    setLoading(true);
    setError('');
    setFieldErrors({});
    setNotice('');
    try {
      const result = await apiFetch<ProfileResponse>('/api/profile/extract', {
        method: 'POST',
        body: toFormData(form, file, true),
      });
      clearDownstreamState();
      saveState(STORAGE_KEYS.profile, result);
      router.push('/program');
    } catch (err) {
      setError(readableError(err, '提交背景信息失败'));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="section">
      <div className="container">
        <div className="card">
          <div className="kicker">第 1 步</div>
          <h1 className="section-title">填写申请者背景</h1>
          {error ? <p className="notice" role="alert">{error}</p> : null}
          {notice ? <p className="notice success" role="status">{notice}</p> : null}

          <form onSubmit={handleSubmit} noValidate>
            <p className="muted">科研、实习、项目、活动经历至少填写一项，或上传可解析的简历。</p>
            <div className="field">
              <label htmlFor="resume-file">
                上传简历（txt / pdf / docx，最大 10 MB）
                <span className="optional-mark">选填</span>
              </label>
              <input
                id="resume-file"
                type="file"
                accept=".txt,.md,.pdf,.docx"
                onChange={(event) => {
                  setFile(event.target.files?.[0] || null);
                  setFieldErrors((current) => ({ ...current, experience: undefined }));
                }}
              />
              {file ? <p className="muted">已选择文件：{file.name}</p> : null}
            </div>

            <div className="form-footer" style={{ justifyContent: 'flex-start', marginTop: 0, marginBottom: 12 }}>
              <button
                className="btn-secondary"
                type="button"
                onClick={parseResume}
                disabled={parsingResume || loading || !file}
              >
                {parsingResume ? '正在解析简历...' : '一键解析简历并回填'}
              </button>
            </div>

            <div className="grid-2">
              <div className="field">
                <label htmlFor="full-name">姓名<span className="required-mark">必填</span></label>
                <input
                  id="full-name"
                  required
                  aria-invalid={Boolean(fieldErrors.full_name)}
                  value={form.full_name}
                  onChange={(event) => update('full_name', event.target.value)}
                />
                {fieldErrors.full_name ? <p className="field-error">{fieldErrors.full_name}</p> : null}
              </div>
              <div className="field">
                <label htmlFor="current-university">当前学校<span className="required-mark">必填</span></label>
                <input
                  id="current-university"
                  required
                  aria-invalid={Boolean(fieldErrors.current_university)}
                  value={form.current_university}
                  onChange={(event) => update('current_university', event.target.value)}
                />
                {fieldErrors.current_university ? <p className="field-error">{fieldErrors.current_university}</p> : null}
              </div>
              <div className="field">
                <label htmlFor="major">当前专业<span className="required-mark">必填</span></label>
                <input
                  id="major"
                  required
                  aria-invalid={Boolean(fieldErrors.major)}
                  value={form.major}
                  onChange={(event) => update('major', event.target.value)}
                />
                {fieldErrors.major ? <p className="field-error">{fieldErrors.major}</p> : null}
              </div>
              <div className="field">
                <label htmlFor="gpa">GPA<span className="optional-mark">选填</span></label>
                <input id="gpa" value={form.gpa} onChange={(event) => update('gpa', event.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="graduation-year">毕业年份<span className="optional-mark">选填</span></label>
                <input id="graduation-year" value={form.graduation_year} onChange={(event) => update('graduation_year', event.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="english-score">语言考试成绩<span className="optional-mark">选填</span></label>
                <input id="english-score" value={form.english_test_score} onChange={(event) => update('english_test_score', event.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="target-degree">目标学位<span className="required-mark">必填</span></label>
                <select
                  id="target-degree"
                  required
                  aria-invalid={Boolean(fieldErrors.target_degree)}
                  value={form.target_degree}
                  onChange={(event) => update('target_degree', event.target.value)}
                >
                  <option value="Master's">{"Master's"}</option>
                  <option value="PhD">PhD</option>
                  <option value="Certificate">Certificate</option>
                  <option value="Other">Other</option>
                </select>
                {fieldErrors.target_degree ? <p className="field-error">{fieldErrors.target_degree}</p> : null}
              </div>
              <div className="field">
                <label htmlFor="target-field">目标专业方向<span className="required-mark">必填</span></label>
                <input
                  id="target-field"
                  required
                  aria-invalid={Boolean(fieldErrors.target_field)}
                  value={form.target_field}
                  onChange={(event) => update('target_field', event.target.value)}
                />
                {fieldErrors.target_field ? <p className="field-error">{fieldErrors.target_field}</p> : null}
              </div>
              <div className="field">
                <label htmlFor="target-country">目标国家/地区<span className="required-mark">必填</span></label>
                <input
                  id="target-country"
                  required
                  aria-invalid={Boolean(fieldErrors.target_country)}
                  value={form.target_country}
                  onChange={(event) => update('target_country', event.target.value)}
                />
                {fieldErrors.target_country ? <p className="field-error">{fieldErrors.target_country}</p> : null}
              </div>
            </div>

            <div className="field">
              <label htmlFor="research-experience">科研经历<span className="optional-mark">选填</span></label>
              <textarea id="research-experience" value={form.research_experience} onChange={(event) => update('research_experience', event.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="internship-experience">实习经历<span className="optional-mark">选填</span></label>
              <textarea id="internship-experience" value={form.internship_experience} onChange={(event) => update('internship_experience', event.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="project-experience">项目经历<span className="optional-mark">选填</span></label>
              <textarea id="project-experience" value={form.project_experience} onChange={(event) => update('project_experience', event.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="activities-awards">活动 / 奖项<span className="optional-mark">选填</span></label>
              <textarea id="activities-awards" value={form.activities_awards} onChange={(event) => update('activities_awards', event.target.value)} />
            </div>
            {fieldErrors.experience ? <p className="field-error">{fieldErrors.experience}</p> : null}
            <div className="field">
              <label htmlFor="motivation-text">申请动机<span className="optional-mark">选填</span></label>
              <textarea id="motivation-text" value={form.motivation_text} onChange={(event) => update('motivation_text', event.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="career-goal">职业目标<span className="optional-mark">选填</span></label>
              <textarea id="career-goal" value={form.career_goal} onChange={(event) => update('career_goal', event.target.value)} />
            </div>

            <div className="form-footer">
              <button className="btn" type="submit" disabled={loading || parsingResume}>
                {loading ? '正在生成申请画像...' : '继续：目标项目分析'}
              </button>
            </div>
          </form>
        </div>
      </div>
    </main>
  );
}
