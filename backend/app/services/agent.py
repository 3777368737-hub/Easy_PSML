from __future__ import annotations

import json
import re
from typing import AsyncIterator, Dict, List, Optional, Tuple

from app.errors import ModelOutputError, UpstreamServiceError
from app.schemas import (
    AgentAction,
    AgentCapabilityCall,
    AgentCommandResponse,
    AgentControl,
    AgentConversationMessage,
    AgentMissingField,
    AgentPageContext,
    AgentPendingAction,
    AgentPlan,
    AgentUiAction,
)
from app.services.agent_capabilities import (
    canonical_workflow_snapshot,
    capability_catalog,
    capability_summary,
    focus_action_for_missing,
    get_capability,
    infer_capability,
    validate_capability,
    validate_ui_actions,
)
from app.services.prompts import VOICE_AGENT_SYSTEM_PROMPT
from app.services.qwen_client import QwenClient
from app.services.store import PendingAgentActionRecord, get_store


qwen_client = QwenClient()
ALLOWED_AGENT_PATHS = {
    "/",
    "/profile",
    "/program",
    "/story",
    "/result",
    "/batch",
    "/library",
}
MAX_ACTIONS = 3
MAX_AGENT_MESSAGE_CHARS = 160
AGENT_STREAM_MAX_TOKENS = 1200
PROFILE_CONTROL_FIELDS = {
    "full-name": "full_name",
    "current-university": "current_university",
    "major": "major",
    "gpa": "gpa",
    "graduation-year": "graduation_year",
    "english-score": "english_test_score",
    "target-degree": "target_degree",
    "target-field": "target_field",
    "target-country": "target_country",
    "research-experience": "research_experience",
    "internship-experience": "internship_experience",
    "project-experience": "project_experience",
    "activities-awards": "activities_awards",
    "motivation-text": "motivation_text",
    "career-goal": "career_goal",
}
PROGRAM_CONTROL_FIELDS = {
    "program-school_name": "school_name",
    "program-program_name": "program_name",
    "program-essay_type": "essay_type",
    "program-word_limit": "word_limit",
    "program-prompt_text": "prompt_text",
    "program-program_details": "program_details",
}
FILLABLE_CONTROL_KINDS = {"text", "textarea", "select", "number", "checkbox"}
CONFIRM_COMMANDS = {
    "确认",
    "确认执行",
    "确定",
    "确定执行",
    "执行",
    "开始吧",
    "执行吧",
    "可以",
    "可以执行",
    "好的",
    "好",
    "没问题",
    "是的",
    "对",
}
CANCEL_COMMANDS = {
    "取消",
    "取消操作",
    "不要",
    "不要执行",
    "不用了",
    "不执行",
    "算了",
    "停止",
}
REPEAT_PATTERN = re.compile(
    r"再说(?:一遍|一次)?|重新说(?:一遍|一次)?|重复(?:一遍|一次)?|"
    r"没听清|没听懂|你说什么|刚才说什么"
)
HELP_PATTERN = re.compile(
    r"怎么办|怎么操作|下一步(?:做什么|干什么|是什么)?|帮帮我|帮助|"
    r"你能做什么|不会填|不知道"
)
NOISE_TOKENS = {
    "嗯",
    "嗯嗯",
    "啊",
    "呃",
    "额",
    "那个",
    "就是",
    "然后",
    "喂",
}
ORDINAL_VALUES = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}
FIELD_ALIASES = {
    "full-name": ("姓名", "名字", "申请人姓名"),
    "current-university": ("当前学校", "本科学校", "学校"),
    "major": ("当前专业", "本科专业", "专业"),
    "gpa": ("gpa", "绩点", "平均分"),
    "graduation-year": ("毕业年份", "毕业时间", "哪年毕业"),
    "english-score": ("语言成绩", "英语成绩", "雅思", "托福"),
    "target-degree": ("目标学位", "申请学位", "学位"),
    "target-field": ("目标专业", "申请方向", "目标方向", "专业方向"),
    "target-country": ("目标国家", "国家地区", "国家", "地区"),
    "research-experience": ("科研经历", "研究经历", "科研"),
    "internship-experience": ("实习经历", "实习"),
    "project-experience": ("项目经历", "项目经验"),
    "activities-awards": ("活动奖项", "活动", "奖项"),
    "motivation-text": ("申请动机", "动机"),
    "career-goal": ("职业目标", "未来目标", "职业规划"),
    "program-school_name": ("学校名称", "申请学校", "学校"),
    "program-program_name": ("项目名称", "申请项目", "专业项目"),
    "program-essay_type": ("文书类型", "ps", "ml"),
    "program-word_limit": ("字数上限", "目标字数", "字数"),
    "program-prompt_text": ("文书题目", "题目", "具体要求"),
    "program-program_details": ("项目官网资料", "项目资料", "官网资料"),
    "story-answer": ("访谈回答", "本轮回答", "回答"),
    "revision-instruction": ("修改意见", "调整意见", "修改要求"),
}
SELECT_VALUE_ALIASES = {
    "target-degree": {
        "硕士": "Master's",
        "研究生": "Master's",
        "博士": "PhD",
        "phd": "PhD",
        "证书": "Certificate",
        "其他": "Other",
    },
    "program-essay_type": {
        "个人陈述": "Personal Statement",
        "ps": "Personal Statement",
        "动机信": "Motivation Letter",
        "ml": "Motivation Letter",
    },
}


def _json(value: object) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif isinstance(value, list):
        value = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            for item in value
        ]
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _control_lookup(
    context: AgentPageContext,
) -> Tuple[Dict[str, AgentControl], Dict[str, AgentControl]]:
    by_id = {control.id: control for control in context.controls}
    by_key = {control.key: control for control in context.controls}
    return by_id, by_key


def _resolve_control(
    action: AgentAction,
    by_id: Dict[str, AgentControl],
    by_key: Dict[str, AgentControl],
) -> Optional[AgentControl]:
    if action.target_id and action.target_id in by_id:
        return by_id[action.target_id]
    if action.target_key and action.target_key in by_key:
        return by_key[action.target_key]
    return None


def _normalize_fill_value(control: AgentControl, value: str) -> Optional[str]:
    cleaned = value.strip()
    if control.kind == "select":
        alias = SELECT_VALUE_ALIASES.get(
            control.key,
            SELECT_VALUE_ALIASES.get(
                "program-essay_type"
                if control.key.endswith("-type")
                else "",
                {},
            ),
        ).get(_normalized_command(cleaned))
        if alias is not None:
            return alias
        for option in control.options:
            if cleaned == option.value:
                return option.value
        for option in control.options:
            normalized_option = {
                _normalized_command(option.label),
                _normalized_command(option.value),
            }
            if _normalized_command(cleaned) in normalized_option:
                return option.value
        for option in control.options:
            option_text = _normalized_command(
                f"{option.label}{option.value}"
            )
            if _normalized_command(cleaned) in option_text:
                return option.value
        return None
    if control.kind == "checkbox":
        lowered = cleaned.casefold()
        if lowered in {"true", "1", "yes", "on", "是", "选中"}:
            return "true"
        if lowered in {"false", "0", "no", "off", "否", "取消"}:
            return "false"
        return None
    if control.kind == "number":
        if not cleaned:
            return None
        try:
            numeric = float(cleaned)
        except ValueError:
            return None
        if control.min_value is not None and numeric < control.min_value:
            return None
        if control.max_value is not None and numeric > control.max_value:
            return None
    max_length = (
        control.max_length
        if control.max_length is not None and control.max_length > 0
        else 12000 if control.kind == "textarea" else 2000
    )
    if len(cleaned) > max_length:
        return None
    return cleaned


def _normalized_command(value: str) -> str:
    return re.sub(
        r"[\s，。！？、,.!?;；:：\"'“”‘’（）()\[\]【】]+",
        "",
        value.casefold(),
    )


def _clean_spoken_value(value: str, kind: str = "text") -> str:
    cleaned = value.strip()
    if kind == "textarea":
        cleaned = re.sub(
            r"^(?:嗯+|呃+|额+|我说|回答是|答案是)[，,\s]*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
    else:
        cleaned = re.sub(
            r"^(?:嗯+|呃+|额+|那个|就是|然后|我说|我叫|我的名字是|"
            r"回答是|答案是)[，,\s]*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
    cleaned = re.sub(r"(?:谢谢|可以吗|好吗)$", "", cleaned).strip()
    return cleaned.strip("，。！？、,.!?;；:：\"'“”‘’")


def _is_noise_transcript(value: str) -> bool:
    normalized = _normalized_command(value)
    return (
        not normalized
        or normalized in NOISE_TOKENS
        or re.fullmatch(r"(?:嗯|啊|呃|额|那个|就是|然后)+", normalized)
        is not None
    )


def _control_is_editable(control: AgentControl) -> bool:
    return (
        control.kind in FILLABLE_CONTROL_KINDS
        and not control.disabled
        and control.risk != "blocked"
    )


def _control_for_key(
    context: AgentPageContext,
    key: str,
) -> Optional[AgentControl]:
    if not key:
        return None
    for control in context.controls:
        if control.key == key and _control_is_editable(control):
            return control
    return None


def _pending_missing_fields(
    pending: Optional[PendingAgentActionRecord],
) -> List[AgentMissingField]:
    if pending is None:
        return []
    fields: List[AgentMissingField] = []
    for item in pending.missing_fields:
        try:
            fields.append(AgentMissingField.model_validate(item))
        except ValueError:
            continue
    return fields


def _first_pending_control(
    context: AgentPageContext,
    pending: Optional[PendingAgentActionRecord],
) -> Optional[AgentControl]:
    if pending is not None:
        for field in _pending_missing_fields(pending):
            control = _control_for_key(context, field.target_key or "")
            if control is not None:
                return control
    focused = _control_for_key(context, context.focused_control_key)
    if focused is not None:
        return focused
    required = next(
        (
            control
            for control in context.controls
            if _control_is_editable(control)
            and control.required
            and not str(control.value).strip()
        ),
        None,
    )
    if required is not None:
        return required
    return next(
        (
            control
            for control in context.controls
            if _control_is_editable(control) and not str(control.value).strip()
        ),
        None,
    )


def _next_editable_control(
    context: AgentPageContext,
    after_key: str,
    *,
    empty_only: bool = False,
) -> Optional[AgentControl]:
    editable = [
        control
        for control in context.controls
        if _control_is_editable(control)
    ]
    current = next(
        (control for control in editable if control.key == after_key),
        None,
    )
    start = next(
        (
            index + 1
            for index, control in enumerate(editable)
            if control.key == after_key
        ),
        len(editable),
    )
    following = editable[start:]
    if current is not None and current.scope:
        following = [
            control
            for control in following
            if not control.scope or control.scope == current.scope
        ]
    if empty_only:
        required = next(
            (
                control
                for control in following
                if control.required and not str(control.value).strip()
            ),
            None,
        )
        if required is not None:
            return required
        return next(
            (
                control
                for control in following
                if not str(control.value).strip()
            ),
            None,
        )
    return following[0] if following else None


def _previous_editable_control(
    context: AgentPageContext,
    before_key: str,
) -> Optional[AgentControl]:
    editable = [
        control for control in context.controls if _control_is_editable(control)
    ]
    current = next(
        (control for control in editable if control.key == before_key),
        None,
    )
    for index, control in enumerate(editable):
        if control.key == before_key:
            candidates = editable[:index]
            if current is not None and current.scope:
                candidates = [
                    item
                    for item in candidates
                    if not item.scope or item.scope == current.scope
                ]
            return candidates[-1] if candidates else None
    return editable[-1] if editable else None


def _focus_ui_action(control: AgentControl, reason: str) -> AgentUiAction:
    return AgentUiAction(
        type="focus",
        target_key=control.key,
        reason=reason,
    )


def _capability_label(name: str) -> str:
    spec = get_capability(name)
    return spec.label if spec is not None else "当前操作"


def _current_step_prompt(
    context: AgentPageContext,
    pending: Optional[PendingAgentActionRecord],
    history: List[AgentConversationMessage],
) -> str:
    missing = _pending_missing_fields(pending)
    if pending is not None and missing:
        labels = "、".join(field.label for field in missing[:3])
        return f"请继续补充：{labels}。请直接说出第一项内容。"
    if pending is not None and pending.status == "prepared":
        return (
            f"请确认是否执行“{_capability_label(pending.capability)}”。"
            "请说“确认”或“取消”。"
        )
    control = _first_pending_control(context, pending)
    if control is not None:
        return f"当前请填写“{control.label}”。直接说出内容即可。"
    for message in reversed(history):
        if message.role == "assistant" and message.content.strip():
            return message.content.strip()[:150]
    return context.summary or f"当前在“{context.title}”页面。请说明你想继续的步骤。"


def _ordinal_from_transcript(value: str) -> Optional[int]:
    normalized = _normalized_command(value)
    match = re.search(r"第([一二两三四五六七八九十\d]+)(?:个|项|条|号)?", normalized)
    if match is None:
        return None
    raw = match.group(1)
    if raw.isdigit():
        return int(raw)
    return ORDINAL_VALUES.get(raw)


def _resolve_option_control(
    context: AgentPageContext,
    pending: Optional[PendingAgentActionRecord],
) -> Optional[AgentControl]:
    current = _first_pending_control(context, pending)
    if current is not None and current.kind == "select" and current.options:
        return current
    selects = [
        control
        for control in context.controls
        if _control_is_editable(control)
        and control.kind == "select"
        and control.options
    ]
    return selects[0] if len(selects) == 1 else None


def _chinese_number(value: str) -> Optional[int]:
    if value.isdigit():
        return int(value)
    digits = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    units = {"十": 10, "百": 100, "千": 1000}
    total = 0
    current = 0
    for char in value:
        if char in digits:
            current = digits[char]
        elif char in units:
            unit = units[char]
            total += (current or 1) * unit
            current = 0
        else:
            return None
    return total + current


def _pending_arguments_with_value(
    pending: Optional[PendingAgentActionRecord],
    target_key: str,
    value: str,
) -> Dict[str, object]:
    if pending is None:
        return {}
    arguments = dict(pending.arguments)
    if pending.capability == "story.answer" and target_key == "story-answer":
        arguments["answer"] = value
    elif (
        pending.capability == "library.story.reply"
        and target_key == "workbench-story-reply"
    ):
        arguments["answer"] = value
    elif (
        pending.capability == "essay.rewrite"
        and target_key == "revision-instruction"
    ):
        arguments["instruction"] = value
    elif (
        pending.capability == "project.rewrite"
        and target_key == "revision-instruction"
    ):
        arguments["revision_instruction"] = value
    return arguments


def _fill_plan(
    *,
    control: AgentControl,
    value: str,
    context: AgentPageContext,
    pending: Optional[PendingAgentActionRecord],
) -> AgentPlan:
    cleaned = _clean_spoken_value(value, control.kind)
    if control.kind == "number" and not re.fullmatch(r"\d+(?:\.\d+)?", cleaned):
        numeric = _chinese_number(cleaned)
        if numeric is not None:
            cleaned = str(numeric)
    normalized = _normalize_fill_value(control, cleaned)
    if normalized is None:
        if control.kind == "select" and control.options:
            choices = "、".join(
                f"{index + 1}. {option.label}"
                for index, option in enumerate(control.options)
                if option.value
            )
            message = f"“{cleaned}”不在“{control.label}”的选项中。可选：{choices}。"
        elif control.kind == "number":
            message = (
                f"“{control.label}”需要"
                f"{control.min_value if control.min_value is not None else ''}"
                f"到{control.max_value if control.max_value is not None else ''}"
                "之间的数字。请重新说一次。"
            )
        else:
            message = f"“{cleaned}”不能作为“{control.label}”的值，请重新说一次。"
        return AgentPlan(
            message=message[:800],
            intent="clarify",
            ui_actions=[_focus_ui_action(control, "重新填写当前字段")],
        )

    next_control = _next_editable_control(
        context,
        control.key,
        empty_only=True,
    )
    ui_actions = [
        AgentUiAction(
            type="fill",
            target_key=control.key,
            value=normalized,
            reason=f"填写{control.label}",
        )
    ]
    if next_control is not None:
        ui_actions.append(_focus_ui_action(next_control, "继续填写下一项"))
        message = (
            f"已填写“{control.label}”。下一步请填写“{next_control.label}”，"
            "直接说出内容即可。"
        )
    else:
        message = f"已填写“{control.label}”。"

    capability = None
    if pending is not None:
        capability = AgentCapabilityCall(
            name=pending.capability,
            arguments=_pending_arguments_with_value(
                pending,
                control.key,
                normalized,
            ),
        )
    return AgentPlan(
        message=message,
        intent="fill_form",
        capability=capability,
        ui_actions=ui_actions,
        next_field=next_control.key if next_control is not None else None,
    )


def _control_aliases(control: AgentControl) -> List[str]:
    aliases = [
        control.label,
        control.key.replace("-", " "),
        *FIELD_ALIASES.get(control.key, ()),
    ]
    cleaned: List[str] = []
    for alias in aliases:
        normalized = _normalized_command(alias)
        if normalized and normalized not in cleaned:
            cleaned.append(normalized)
    return sorted(cleaned, key=len, reverse=True)


def _labeled_value_plan(
    transcript: str,
    context: AgentPageContext,
    pending: Optional[PendingAgentActionRecord],
) -> Optional[AgentPlan]:
    normalized = _normalized_command(transcript)
    normalized = re.sub(r"^(?:请|帮我|麻烦|然后)", "", normalized)
    trailing_action = ""
    trailing_match = re.search(
        r"(?:然后|并且|并|再)(?:开始|提交|保存|生成|分析|发送|审核|下一步).*$",
        normalized,
    )
    if trailing_match is not None:
        trailing_action = normalized[trailing_match.start() :]
        normalized = normalized[: trailing_match.start()]
    candidates: List[tuple[int, AgentControl, str]] = []
    for control in context.controls:
        if not _control_is_editable(control):
            continue
        for alias in _control_aliases(control):
            pattern = re.compile(
                rf"^(?:把|将)?{re.escape(alias)}"
                r"(?:改成|改为|设为|设置为|填成|填写为|写成|叫做|叫|是|为)?"
                r"(.+)$"
            )
            match = pattern.match(normalized)
            if match is None:
                continue
            value = match.group(1).strip()
            value = re.sub(
                r"^(?:改成|改为|设为|设置为|填成|填写为|写成|是|为)",
                "",
                value,
            )
            if value:
                candidates.append((len(alias), control, value))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    longest = candidates[0][0]
    best = [item for item in candidates if item[0] == longest]
    controls = {item[1].key for item in best}
    if len(controls) > 1:
        current = _first_pending_control(context, pending)
        if current is not None:
            best = [item for item in best if item[1].key == current.key]
        if len({item[1].key for item in best}) != 1:
            labels = "、".join(sorted({item[1].label for item in best}))
            return AgentPlan(
                message=f"这个说法会匹配多个字段：{labels}。请说出完整字段名称。",
                intent="clarify",
            )
    _, control, value = best[0]
    plan = _fill_plan(
        control=control,
        value=value,
        context=context,
        pending=pending,
    )
    if trailing_action:
        inferred = infer_capability(trailing_action, context)
        if inferred is not None:
            plan = plan.model_copy(update={"capability": inferred})
    return plan


def _correction_plan(
    transcript: str,
    context: AgentPageContext,
    pending: Optional[PendingAgentActionRecord],
) -> Optional[AgentPlan]:
    control = _first_pending_control(context, pending)
    if control is None:
        return None
    value = None
    match = re.search(
        r"(?:改成|改为|设为|设置为|填成|填写为|写成|纠正为|应该是)"
        r"[，,\s]*(.+)$",
        transcript,
    )
    if match is not None:
        value = match.group(1).strip()
    elif "不是" in transcript:
        value = transcript.rsplit("是", 1)[-1].strip()
    if not value:
        return None
    return _fill_plan(
        control=control,
        value=value,
        context=context,
        pending=pending,
    )


def _deterministic_agent_plan(
    transcript: str,
    context: AgentPageContext,
    history: List[AgentConversationMessage],
    pending: Optional[PendingAgentActionRecord],
    *,
    allow_recovery: bool,
) -> Optional[AgentPlan]:
    normalized = _normalized_command(transcript)
    if _is_noise_transcript(transcript):
        return AgentPlan(
            message=f"没有听清，请再说一遍。{_current_step_prompt(context, pending, history)}",
            intent="clarify",
        )
    if REPEAT_PATTERN.search(normalized):
        return AgentPlan(
            message=_current_step_prompt(context, pending, history),
            intent="answer",
        )
    if (
        normalized in CANCEL_COMMANDS
        or normalized in {"取消刚才的操作", "不要这个"}
        or re.fullmatch(r"(?:取消|不用了|算了|不要执行)(?:谢谢)?", normalized)
    ):
        if pending is None:
            return AgentPlan(
                message="当前没有等待确认或补充的操作。",
                intent="answer",
            )
        return AgentPlan(
            message="已取消当前待执行操作。",
            intent="operate",
            capability=AgentCapabilityCall(
                name="agent.cancel_pending",
                arguments={},
            ),
        )
    if (
        normalized in CONFIRM_COMMANDS
        or re.fullmatch(
            r"(?:好的?|可以|没问题|是的|对)?确认(?:执行|开始)?",
            normalized,
        )
        or re.fullmatch(
            r"(?:好的?|可以|没问题|是的|对)(?:执行|开始)?",
            normalized,
        )
    ):
        if pending is None:
            return AgentPlan(
                message="当前没有等待确认的操作。",
                intent="clarify",
            )
        return AgentPlan(
            message="正在校验并执行已确认操作。",
            intent="operate",
            capability=AgentCapabilityCall(
                name="agent.confirm_pending",
                arguments={},
            ),
        )
    if normalized in {"撤销", "撤销刚才", "撤回刚才", "改回上一项", "恢复刚才"}:
        return AgentPlan(
            message="正在撤销上一次通过语音填写的内容。",
            intent="operate",
            capability=AgentCapabilityCall(
                name="agent.undo_last_edit",
                arguments={},
            ),
        )
    if len(normalized) <= 16 and HELP_PATTERN.search(normalized):
        return AgentPlan(
            message=_current_step_prompt(context, pending, history),
            intent="answer",
        )
    if re.match(r"^(?:提交|保存|执行)", normalized):
        inferred = infer_capability(normalized, context)
        if inferred is not None:
            return AgentPlan(
                message="正在检查并准备执行这个操作。",
                intent="operate",
                capability=inferred,
            )

    current = _first_pending_control(context, pending)
    if context.path == "/library":
        library_sections = (
            (
                ("background-source-form",),
                ("新建人物", "添加人物", "新建背景", "添加背景", "上传简历"),
                "已打开人物与背景录入区。请按提示填写人物和简历名称。",
            ),
            (
                ("application-project-form",),
                (
                    "新建项目",
                    "添加项目",
                    "记录学校",
                    "添加学校",
                    "申请项目表单",
                ),
                "已打开申请项目录入区。请说学校和项目名称。",
            ),
            (
                ("story-source-form",),
                ("新建故事", "添加故事", "挖掘故事", "开始故事"),
                "已打开故事录入区。请选择申请项目并说故事名称。",
            ),
        )
        for section_keys, phrases, message in library_sections:
            if (
                any(phrase in normalized for phrase in phrases)
                and not re.match(r"^(?:确认|提交|执行|保存)", normalized)
            ):
                return AgentPlan(
                    message=message,
                    intent="navigate",
                    ui_actions=[
                        AgentUiAction(
                            type="open_section",
                            target_key=section_key,
                            section=section_key,
                            reason="展开语音下一步所需的表单",
                        )
                        for section_key in section_keys
                    ],
                )
    if (
        context.path == "/profile"
        and normalized in {"跳过简历", "不用简历", "没有简历", "手动填写"}
    ):
        manual = _control_for_key(context, "full-name") or current
        message = (
            "可以不上传文件。请直接说姓名，然后按提示逐项补充学校、专业、"
            "目标和经历。"
        )
        return AgentPlan(
            message=message,
            intent="answer",
            ui_actions=(
                [_focus_ui_action(manual, "开始手动填写背景")]
                if manual is not None
                else []
            ),
            next_field=manual.key if manual is not None else None,
        )
    if (
        pending is not None
        and pending.capability
        in {"profile.parse_resume", "library.background.extract"}
        and not bool(context.page_data.get("resume_selected"))
    ):
        message = (
            "浏览器不允许语音直接选择本地文件。"
            "请在文件框中选择 TXT、MD、PDF 或 DOCX；"
            "如果不需要文件，可以说“跳过简历”后逐项口述背景。"
        )
        return AgentPlan(
            message=message,
            intent="clarify",
        )
    if normalized in {"不对", "错了", "不是", "重新填写", "重新填", "重来"}:
        if current is not None:
            return AgentPlan(
                message=f"请重新说“{current.label}”的内容。",
                intent="clarify",
                ui_actions=[
                    _focus_ui_action(current, "重新填写当前字段")
                ],
            )
    if normalized in {"上一项", "上一个", "上一个字段"} and current is not None:
        previous = _previous_editable_control(context, current.key)
        if previous is not None:
            return AgentPlan(
                message=f"已定位到“{previous.label}”。请直接说出内容。",
                intent="navigate",
                ui_actions=[_focus_ui_action(previous, "返回上一项")],
                next_field=previous.key,
            )
    if normalized in {"下一项", "下一个", "下一个字段"} and current is not None:
        following = _next_editable_control(context, current.key)
        if following is not None:
            return AgentPlan(
                message=f"已定位到“{following.label}”。请直接说出内容。",
                intent="navigate",
                ui_actions=[_focus_ui_action(following, "进入下一项")],
                next_field=following.key,
            )
    if normalized.startswith("跳过") and current is not None:
        if current.required:
            return AgentPlan(
                message=f"“{current.label}”是必填项，不能跳过。请直接说出内容。",
                intent="clarify",
                ui_actions=[_focus_ui_action(current, "继续填写必填项")],
            )
        following = _next_editable_control(context, current.key)
        if following is not None:
            return AgentPlan(
                message=f"已跳过“{current.label}”，现在请填写“{following.label}”。",
                intent="navigate",
                ui_actions=[_focus_ui_action(following, "跳过可选项")],
                next_field=following.key,
            )
    if (
        normalized in {"清空当前字段", "清空这一项", "删除当前内容"}
        and current is not None
    ):
        return _fill_plan(
            control=current,
            value="",
            context=context,
            pending=pending,
        )

    ordinal = _ordinal_from_transcript(transcript)
    if ordinal is not None:
        option_control = _resolve_option_control(context, pending)
        if option_control is not None:
            options = [
                option for option in option_control.options if option.value
            ]
            if 1 <= ordinal <= len(options):
                option = options[ordinal - 1]
                return _fill_plan(
                    control=option_control,
                    value=option.value,
                    context=context,
                    pending=pending,
                )
            return AgentPlan(
                message=(
                    f"“{option_control.label}”只有 {len(options)} 个有效选项。"
                    "请重新说序号。"
                ),
                intent="clarify",
                ui_actions=[
                    _focus_ui_action(option_control, "重新选择选项")
                ],
            )

    if pending is not None:
        labeled = _labeled_value_plan(transcript, context, pending)
        if labeled is not None:
            return labeled
        correction = _correction_plan(transcript, context, pending)
        if correction is not None:
            return correction

    if (
        pending is not None
        and pending.status == "collecting"
        and current is not None
        and not re.match(
            r"^(?:打开|进入|跳到|前往|去|开始|提交|保存|生成|分析|发送|审核|"
            r"重写|下载|复制|清空|删除|刷新|重试|暂停|继续|停止|关闭)",
            normalized,
        )
    ):
        return _fill_plan(
            control=current,
            value=transcript,
            context=context,
            pending=pending,
        )

    if not allow_recovery:
        return None

    labeled = _labeled_value_plan(transcript, context, pending)
    if labeled is not None:
        return labeled
    correction = _correction_plan(transcript, context, pending)
    if correction is not None:
        return correction
    inferred = infer_capability(transcript, context)
    if inferred is not None:
        return AgentPlan(
            message="正在处理这条指令。",
            intent="operate",
            capability=inferred,
        )
    focused = _control_for_key(context, context.focused_control_key)
    if focused is not None and not re.match(
        r"^(?:打开|进入|跳到|前往|去|确认|取消|重复|再说|帮我|开始|"
        r"提交|保存|生成|分析|发送|审核|重写|下载|复制|清空|删除|刷新|重试)",
        normalized,
    ):
        return _fill_plan(
            control=focused,
            value=transcript,
            context=context,
            pending=pending,
        )
    return AgentPlan(
        message=(
            "没有理解这条指令。"
            f"{_current_step_prompt(context, pending, history)}"
            "也可以说“重复”听当前要求，或说“打开项目”切换页面。"
        ),
        intent="clarify",
    )


def _sanitize_actions(
    plan: AgentPlan,
    context: AgentPageContext,
) -> Tuple[List[AgentAction], bool]:
    by_id, by_key = _control_lookup(context)
    actions: List[AgentAction] = []
    needs_confirmation = plan.needs_confirmation

    for action in plan.actions:
        if len(actions) >= MAX_ACTIONS:
            break

        if action.type == "navigate":
            if not action.path or action.path not in ALLOWED_AGENT_PATHS:
                continue
            target_key = action.target_key.strip() if action.target_key else None
            actions.append(
                AgentAction(
                    type="navigate",
                    target_key=target_key,
                    path=action.path,
                    reason=action.reason,
                    risk="safe",
                )
            )
            continue

        control = _resolve_control(action, by_id, by_key)
        if control is None or control.disabled:
            continue

        if action.type == "focus":
            actions.append(
                AgentAction(
                    type="focus",
                    target_id=control.id,
                    target_key=control.key,
                    reason=action.reason,
                    risk="safe",
                )
            )
            continue

        if action.type == "fill":
            if control.kind not in {
                "text",
                "textarea",
                "select",
                "number",
                "checkbox",
            }:
                continue
            if action.value is None:
                continue
            normalized = _normalize_fill_value(control, action.value)
            if normalized is None:
                continue
            actions.append(
                AgentAction(
                    type="fill",
                    target_id=control.id,
                    target_key=control.key,
                    value=normalized,
                    reason=action.reason,
                    risk="safe",
                )
            )
            continue

        if action.type == "click":
            if control.kind not in {"button", "link"} or control.risk == "blocked":
                continue
            risk = "confirm" if control.risk == "confirm" else "safe"
            if risk == "confirm":
                needs_confirmation = True
            actions.append(
                AgentAction(
                    type="click",
                    target_id=control.id,
                    target_key=control.key,
                    reason=action.reason,
                    risk=risk,
                )
            )

    return actions, needs_confirmation


async def transcribe_audio(audio: bytes, media_type: str) -> str:
    return await qwen_client.transcribe(audio, media_type)


async def transcribe_audio_stream(
    audio: bytes, media_type: str
) -> AsyncIterator[str]:
    async for delta in qwen_client.stream_transcribe(audio, media_type):
        yield delta


def _agent_messages(
    owner_id: str,
    transcript: str,
    context: AgentPageContext,
    history: List[AgentConversationMessage],
) -> List[Dict[str, str]]:
    pending = _pending_for_context(
        get_store().get_pending_agent_action(owner_id),
        context,
    )
    canonical_state = canonical_workflow_snapshot(owner_id, context)
    return [
        {"role": "system", "content": VOICE_AGENT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Resolve the user's command against the current GradPilot page.\n\n"
                f"User transcript:\n{transcript.strip()}\n\n"
                f"Recent assistant/user history:\n{_json(history)}\n\n"
                f"Active pending action:\n"
                f"{_json(pending_action_schema(pending)) if pending else 'null'}\n\n"
                f"Available capabilities:\n{_json(capability_catalog())}\n\n"
                f"Canonical workflow state:\n{_json(canonical_state)}\n\n"
                f"Current page, semantic controls, and unsaved page data:\n"
                f"{_json(context)}"
            ),
        },
    ]


def pending_action_schema(
    pending: PendingAgentActionRecord,
) -> AgentPendingAction:
    return AgentPendingAction(
        id=pending.id,
        capability=pending.capability,
        arguments=pending.arguments,
        missing_fields=[
            AgentMissingField.model_validate(item)
            for item in pending.missing_fields
        ],
        status="prepared" if pending.status == "prepared" else "collecting",
        summary=pending.summary,
        expires_at=pending.expires_at,
    )


def _pending_for_context(
    pending: Optional[PendingAgentActionRecord],
    context: AgentPageContext,
) -> Optional[PendingAgentActionRecord]:
    if pending is None:
        return None
    spec = get_capability(pending.capability)
    if (
        spec is not None
        and spec.path != "*"
        and context.path != spec.path
    ):
        return None
    return pending


def _dedupe_ui_actions(actions: List[AgentUiAction]) -> List[AgentUiAction]:
    seen: set[tuple[str, str | None, str | None, str | None]] = set()
    result: List[AgentUiAction] = []
    for action in actions:
        key = (action.type, action.target_key, action.path, action.section)
        if key in seen:
            continue
        seen.add(key)
        result.append(action)
    return result[:6]


def _projected_context(
    context: AgentPageContext,
    actions: List[AgentUiAction],
) -> AgentPageContext:
    projected = context.model_copy(deep=True)
    for action in actions:
        if action.type != "fill" or not action.target_key or action.value is None:
            continue
        key = action.target_key
        value = action.value
        for control in projected.controls:
            if control.key == key:
                control.value = value
                break
        profile_form = projected.page_data.get("profile_form")
        if isinstance(profile_form, dict) and key in PROFILE_CONTROL_FIELDS:
            profile_form[PROFILE_CONTROL_FIELDS[key]] = value
        program_form = projected.page_data.get("program_form")
        if isinstance(program_form, dict) and key in PROGRAM_CONTROL_FIELDS:
            program_form[PROGRAM_CONTROL_FIELDS[key]] = value
        if key == "story-answer":
            projected.page_data["story_answer"] = value
        if key == "workbench-story-reply":
            projected.page_data["library_story_reply"] = value
        if key == "revision-instruction":
            projected.page_data["revision_instruction"] = value
        batch_form = projected.page_data.get("batch_form")
        if isinstance(batch_form, dict):
            directions = batch_form.get("directions")
            if not isinstance(directions, list):
                continue
            for direction in directions:
                if not isinstance(direction, dict):
                    continue
                direction_id = str(direction.get("id") or "")
                if not direction_id or not key.startswith(f"{direction_id}-"):
                    continue
                suffix = key[len(direction_id) + 1 :]
                if suffix == "school":
                    direction["school_name"] = value
                elif suffix == "program":
                    direction["program_name"] = value
                elif suffix == "details":
                    direction["program_details"] = value
                elif suffix.endswith("-words") or suffix.endswith("-prompt"):
                    essay_type = (
                        "Personal Statement"
                        if suffix.startswith("ps-")
                        else "Motivation Letter"
                    )
                    essays = direction.get("essays")
                    if isinstance(essays, dict):
                        essay = essays.get(essay_type)
                        if isinstance(essay, dict):
                            essay[
                                "word_limit"
                                if suffix.endswith("-words")
                                else "prompt_text"
                            ] = value
                break
    return projected


def _with_next_focus(
    context: AgentPageContext,
    actions: List[AgentUiAction],
) -> List[AgentUiAction]:
    fills = [action for action in actions if action.type == "fill"]
    has_focus = any(action.type == "focus" for action in actions)
    if len(fills) != 1 or has_focus or not fills[0].target_key:
        return actions
    projected = _projected_context(context, actions)
    next_control = _next_editable_control(
        projected,
        fills[0].target_key,
        empty_only=True,
    )
    if next_control is None:
        return actions
    return [
        *actions,
        _focus_ui_action(next_control, "继续填写下一项"),
    ]


def _missing_message(
    capability: str,
    missing: List[AgentMissingField],
) -> str:
    spec = get_capability(capability)
    action_label = spec.label if spec else "当前操作"
    labels = "、".join(field.label for field in missing[:4])
    suffix = "等" if len(missing) > 4 else ""
    return f"{action_label}还不能执行，需要补充：{labels}{suffix}。"


async def _response_from_plan(
    owner_id: str,
    plan: AgentPlan,
    transcript: str,
    context: AgentPageContext,
    source: str,
) -> AgentCommandResponse:
    legacy_actions, _ = _sanitize_actions(plan, context)
    ui_actions = _with_next_focus(
        context,
        validate_ui_actions(context, plan.ui_actions),
    )
    store = get_store()
    existing_pending = _pending_for_context(
        store.get_pending_agent_action(owner_id),
        context,
    )
    capability = plan.capability or infer_capability(transcript, context)
    if capability is None and existing_pending is not None:
        capability = AgentCapabilityCall(
            name=existing_pending.capability,
            arguments=existing_pending.arguments,
        )
    elif capability is not None and existing_pending is not None:
        if existing_pending.capability == capability.name:
            capability = AgentCapabilityCall(
                name=capability.name,
                arguments={**existing_pending.arguments, **capability.arguments},
            )

    if capability is not None and capability.name == "agent.cancel_pending":
        store.cancel_pending_agent_action(owner_id)
        existing_pending = None
        capability = None

    status = "answered"
    pending_action: Optional[PendingAgentActionRecord] = None
    missing: List[AgentMissingField] = []
    needs_confirmation = False
    validation_context = _projected_context(context, ui_actions)

    confirmation_handled = False
    if capability is not None and capability.name == "agent.confirm_pending":
        if existing_pending is not None and existing_pending.status == "prepared":
            status = "ready"
            capability = AgentCapabilityCall(
                name="agent.confirm_pending",
                arguments={"action_id": existing_pending.id},
            )
            pending_action = existing_pending
            confirmation_handled = True
        elif existing_pending is not None:
            capability = AgentCapabilityCall(
                name=existing_pending.capability,
                arguments=existing_pending.arguments,
            )
        else:
            status = "needs_input"
            missing = [
                AgentMissingField(
                    key="action_id",
                    label="等待确认的 Agent 操作",
                )
            ]
            capability = None
            confirmation_handled = True

    if capability is not None and not confirmation_handled:
        spec = get_capability(capability.name)
        if spec is None:
            missing = [AgentMissingField(
                key="capability",
                label="当前页面支持的操作",
            )]
            status = "needs_input"
        else:
            missing = validate_capability(
                owner_id,
                validation_context,
                capability,
                store=store,
            )
            if missing:
                status = "needs_input"
                pending_action = store.upsert_pending_agent_action(
                    owner_id,
                    capability.name,
                    capability.arguments,
                    [item.model_dump(mode="json") for item in missing],
                    "collecting",
                    capability_summary(capability.name, capability.arguments),
                )
            elif spec.requires_confirmation:
                status = "confirmation_required"
                needs_confirmation = True
                pending_action = store.upsert_pending_agent_action(
                    owner_id,
                    capability.name,
                    capability.arguments,
                    [],
                    "prepared",
                    capability_summary(capability.name, capability.arguments),
                )
            else:
                status = "ready"
                if existing_pending is not None:
                    store.cancel_pending_agent_action(
                        owner_id,
                        existing_pending.id,
                    )

    if status == "needs_input":
        focus = focus_action_for_missing(missing)
        if focus is not None:
            ui_actions = _dedupe_ui_actions([*ui_actions, focus])

    effective_missing = missing or plan.missing_fields
    next_field = (
        effective_missing[0].target_key
        if effective_missing
        else plan.next_field
    )
    message = re.sub(r"\s+", " ", plan.message).strip()
    if status == "needs_input" and missing:
        file_missing = any(
            field.key in {"resume", "resume_file"} for field in missing
        )
        if capability is not None and (
            capability.name in {
                "profile.parse_resume",
                "library.background.extract",
            }
            and file_missing
        ):
            message = (
                "浏览器不能通过语音选择本地文件。请手动选择简历文件；"
                "背景页也可以跳过文件后逐项口述经历。"
            )
        else:
            message = _missing_message(
                capability.name if capability else "",
                missing,
            )
    elif status in {"answered", "ready"}:
        next_focus = next(
            (action for action in ui_actions if action.type == "focus"),
            None,
        )
        next_control = _control_for_key(
            context,
            next_focus.target_key if next_focus else "",
        )
        if next_control is not None and next_control.label not in message:
            message = (
                f"{message.rstrip('。')}。"
                f"下一步请填写“{next_control.label}”。"
            )
    if len(message) > MAX_AGENT_MESSAGE_CHARS:
        message = f"{message[: MAX_AGENT_MESSAGE_CHARS - 3].rstrip()}..."
    return AgentCommandResponse(
        transcript=transcript.strip(),
        message=message,
        intent=plan.intent,
        actions=legacy_actions,
        capability=capability,
        ui_actions=ui_actions,
        missing_fields=effective_missing,
        next_field=next_field,
        needs_confirmation=needs_confirmation,
        source="voice" if source == "voice" else "text",
        status=status,
        pending_action=(
            pending_action_schema(pending_action)
            if pending_action
            else None
        ),
    )


async def run_agent_command(
    owner_id: str,
    transcript: str,
    context: AgentPageContext,
    history: List[AgentConversationMessage],
    *,
    source: str,
) -> AgentCommandResponse:
    pending = _pending_for_context(
        get_store().get_pending_agent_action(owner_id),
        context,
    )
    deterministic = _deterministic_agent_plan(
        transcript,
        context,
        history,
        pending,
        allow_recovery=False,
    )
    if deterministic is not None:
        return await _response_from_plan(
            owner_id,
            deterministic,
            transcript,
            context,
            source,
        )
    messages = _agent_messages(owner_id, transcript, context, history)
    try:
        plan = await qwen_client.chat_json(
            messages,
            AgentPlan,
            max_tokens=1800,
        )
    except (ModelOutputError, UpstreamServiceError):
        plan = _deterministic_agent_plan(
            transcript,
            context,
            history,
            pending,
            allow_recovery=True,
        )
        if plan is None:
            raise
    return await _response_from_plan(
        owner_id,
        plan,
        transcript,
        context,
        source,
    )


async def stream_agent_command(
    owner_id: str,
    transcript: str,
    context: AgentPageContext,
    history: List[AgentConversationMessage],
    *,
    source: str,
) -> AsyncIterator[Tuple[str, object]]:
    pending = _pending_for_context(
        get_store().get_pending_agent_action(owner_id),
        context,
    )
    deterministic = _deterministic_agent_plan(
        transcript,
        context,
        history,
        pending,
        allow_recovery=False,
    )
    if deterministic is not None:
        yield "message_delta", deterministic.message
        yield "final", await _response_from_plan(
            owner_id,
            deterministic,
            transcript,
            context,
            source,
        )
        return

    messages = _agent_messages(owner_id, transcript, context, history)
    plan: Optional[AgentPlan] = None
    try:
        async for event in qwen_client.stream_chat_json(
            messages,
            AgentPlan,
            max_tokens=AGENT_STREAM_MAX_TOKENS,
        ):
            if event.reset_message:
                yield "message_reset", None
            if event.message_delta:
                yield "message_delta", event.message_delta
            if event.result is not None:
                plan = event.result
    except (ModelOutputError, UpstreamServiceError):
        plan = _deterministic_agent_plan(
            transcript,
            context,
            history,
            pending,
            allow_recovery=True,
        )
        if plan is None:
            raise
        yield "message_reset", None
        yield "message_delta", plan.message

    if plan is None:
        raise ModelOutputError(
            "Qwen stream finished without a validated agent plan"
        )
    yield "final", await _response_from_plan(
        owner_id,
        plan,
        transcript,
        context,
        source,
    )
