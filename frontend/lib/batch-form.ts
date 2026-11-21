import type { BatchDirectionInput, EssayType } from '@/lib/types';

export const ESSAY_TYPES: EssayType[] = ['Personal Statement', 'Motivation Letter'];

export type EssayForm = { enabled: boolean; word_limit: string; prompt_text: string };
export type DirectionForm = {
  id: string;
  school_name: string;
  program_name: string;
  program_details: string;
  application_project_id: string;
  story_instance_ids: string[];
  essays: Record<EssayType, EssayForm>;
};

export function newDirection(): DirectionForm {
  return {
    id: crypto.randomUUID(),
    school_name: '',
    program_name: '',
    program_details: '',
    application_project_id: '',
    story_instance_ids: [],
    essays: {
      'Personal Statement': { enabled: true, word_limit: '800', prompt_text: '' },
      'Motivation Letter': { enabled: true, word_limit: '500', prompt_text: '' },
    },
  };
}

export function essayLabel(type: EssayType): string {
  return type === 'Personal Statement' ? 'PS · Personal Statement' : 'ML · Motivation Letter';
}

export function validateDirections(forms: DirectionForm[]): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!forms.length) {
    errors.directions = '请至少添加 1 个申请方向。';
  }
  for (const form of forms) {
    if (!form.school_name.trim() || form.school_name.trim().length > 200) {
      errors[`${form.id}-school`] = '请填写学校名称，最多 200 个字符。';
    }
    if (!form.program_name.trim() || form.program_name.trim().length > 200) {
      errors[`${form.id}-program`] = '请填写项目名称 / 专业方向，最多 200 个字符。';
    }
    if (form.program_details.trim().length > 30000) {
      errors[`${form.id}-details`] = '项目资料最多 30000 个字符。';
    }
    if (form.story_instance_ids.length && !form.application_project_id) {
      errors[`${form.id}-stories`] = '选择故事后必须绑定对应的申请项目。';
    }
    if (!ESSAY_TYPES.some((type) => form.essays[type].enabled)) {
      errors[`${form.id}-types`] = '每个方向至少选择一种文书。';
    }
    for (const type of ESSAY_TYPES) {
      const essay = form.essays[type];
      if (!essay.enabled) continue;
      const prefix = `${form.id}-${type === 'Personal Statement' ? 'ps' : 'ml'}`;
      const words = Number(essay.word_limit);
      if (!Number.isInteger(words) || words < 100 || words > 5000) {
        errors[`${prefix}-words`] = '字数必须是 100 到 5000 之间的整数。';
      }
      if (essay.prompt_text.trim().length < 10 || essay.prompt_text.trim().length > 20000) {
        errors[`${prefix}-prompt`] = '请填写 10 到 20000 个字符的题目或具体要求。';
      }
    }
  }
  return errors;
}

export function directionInputs(forms: DirectionForm[]): BatchDirectionInput[] {
  return forms.map((form) => ({
    school_name: form.school_name.trim(),
    program_name: form.program_name.trim(),
    program_details: form.program_details.trim(),
    application_project_id: form.application_project_id || undefined,
    story_instance_ids: form.story_instance_ids || [],
    essays: ESSAY_TYPES.filter((type) => form.essays[type].enabled).map((type) => ({
      essay_type: type,
      word_limit: Number(form.essays[type].word_limit),
      prompt_text: form.essays[type].prompt_text.trim(),
    })),
  }));
}
