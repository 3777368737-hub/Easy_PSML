from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from app.schemas import (
    AgentCapabilityCall,
    AgentMissingField,
    AgentPageContext,
    AgentUiAction,
)
from app.services.store import SQLiteStore, get_store


ALLOWED_PATHS = {
    "/",
    "/profile",
    "/program",
    "/story",
    "/result",
    "/batch",
    "/library",
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


@dataclass(frozen=True)
class CapabilitySpec:
    key: str
    label: str
    description: str
    path: str
    requires_confirmation: bool = False
    argument_hints: str = ""


CAPABILITIES: Dict[str, CapabilitySpec] = {
    "app.navigate": CapabilitySpec(
        "app.navigate",
        "页面跳转",
        "跳转到 GradPilot 的已有业务页面。",
        "*",
        argument_hints='{"path": "/profile|/program|/story|/result|/batch"}',
    ),
    "profile.parse_resume": CapabilitySpec(
        "profile.parse_resume",
        "解析简历",
        "解析用户已经选择的简历并回填背景信息，不负责选择文件。",
        "/profile",
    ),
    "profile.save_draft": CapabilitySpec(
        "profile.save_draft",
        "保存背景草稿",
        "把当前背景表单保存到浏览器草稿。",
        "/profile",
    ),
    "profile.continue_program": CapabilitySpec(
        "profile.continue_program",
        "保存背景并进入项目分析",
        "验证背景必填项、生成申请画像并进入项目分析。",
        "/profile",
        requires_confirmation=True,
    ),
    "profile.continue_batch": CapabilitySpec(
        "profile.continue_batch",
        "保存背景并进入批量生成",
        "验证背景必填项、生成申请画像并进入批量生成。",
        "/profile",
        requires_confirmation=True,
    ),
    "program.analyze": CapabilitySpec(
        "program.analyze",
        "开始项目分析",
        "使用当前项目表单和背景信息执行项目分析。",
        "/program",
        requires_confirmation=True,
    ),
    "program.continue_story": CapabilitySpec(
        "program.continue_story",
        "进入故事挖掘",
        "在项目分析完成后进入故事挖掘。",
        "/program",
    ),
    "story.answer": CapabilitySpec(
        "story.answer",
        "提交故事访谈回答",
        "提交当前故事访谈的一轮回答并获取下一轮问题。",
        "/story",
        requires_confirmation=True,
        argument_hints='{"answer": "用户本轮回答文本"}',
    ),
    "story.reload": CapabilitySpec(
        "story.reload",
        "重新连接故事访谈",
        "重新加载故事页面并同步当前会话。",
        "/story",
    ),
    "story.continue_result": CapabilitySpec(
        "story.continue_result",
        "进入文书工作台",
        "在三轮故事访谈完成后进入结果生成页面。",
        "/story",
    ),
    "essay.outline": CapabilitySpec(
        "essay.outline",
        "生成中文大纲",
        "为当前已完成访谈的故事会话生成新版中文大纲。",
        "/result",
        requires_confirmation=True,
    ),
    "essay.draft": CapabilitySpec(
        "essay.draft",
        "生成英文草稿",
        "根据当前故事会话生成新版英文草稿。",
        "/result",
        requires_confirmation=True,
    ),
    "essay.rewrite": CapabilitySpec(
        "essay.rewrite",
        "按意见重写草稿",
        "使用用户提供的修改意见重写英文草稿。",
        "/result",
        requires_confirmation=True,
        argument_hints='{"instruction": "修改意见"}',
    ),
    "essay.review": CapabilitySpec(
        "essay.review",
        "审核草稿",
        "审核当前英文草稿。",
        "/result",
        requires_confirmation=True,
    ),
    "project.analyze": CapabilitySpec(
        "project.analyze",
        "实例项目分析",
        "为当前实例文书项目生成项目分析。",
        "/result",
        requires_confirmation=True,
    ),
    "project.outline": CapabilitySpec(
        "project.outline",
        "实例项目大纲",
        "为当前实例文书项目生成中文大纲。",
        "/result",
        requires_confirmation=True,
    ),
    "project.draft": CapabilitySpec(
        "project.draft",
        "实例项目草稿",
        "为当前实例文书项目生成英文草稿。",
        "/result",
        requires_confirmation=True,
    ),
    "project.rewrite": CapabilitySpec(
        "project.rewrite",
        "实例项目重写",
        "按修改意见重写当前实例文书项目草稿。",
        "/result",
        requires_confirmation=True,
    ),
    "project.review": CapabilitySpec(
        "project.review",
        "实例项目审核",
        "审核当前实例文书项目草稿。",
        "/result",
        requires_confirmation=True,
    ),
    "result.switch_tab": CapabilitySpec(
        "result.switch_tab",
        "切换文书视图",
        "在大纲和草稿视图之间切换。",
        "/result",
        argument_hints='{"tab": "outline|draft"}',
    ),
    "result.load_version": CapabilitySpec(
        "result.load_version",
        "查看历史版本",
        "查看当前会话中的指定大纲或草稿版本。",
        "/result",
        argument_hints='{"version_id": "版本 ID"}',
    ),
    "result.restore_current": CapabilitySpec(
        "result.restore_current",
        "返回当前版本",
        "退出历史版本查看并回到当前文书版本。",
        "/result",
    ),
    "essay.download": CapabilitySpec(
        "essay.download",
        "下载草稿",
        "下载当前可见的英文草稿。",
        "/result",
    ),
    "essay.copy": CapabilitySpec(
        "essay.copy",
        "复制草稿",
        "把当前可见的英文草稿复制到剪贴板。",
        "/result",
    ),
    "history.load": CapabilitySpec(
        "history.load",
        "加载历史申请",
        "加载当前用户的指定历史会话。",
        "/result",
        argument_hints='{"session_id": "历史会话 ID"}',
    ),
    "history.clear": CapabilitySpec(
        "history.clear",
        "清空历史",
        "清空当前用户的全部申请记录和本地流程缓存。",
        "/result",
        requires_confirmation=True,
    ),
    "batch.add_direction": CapabilitySpec(
        "batch.add_direction",
        "添加申请方向",
        "在批量生成页面添加一个申请方向。",
        "/batch",
    ),
    "batch.remove_direction": CapabilitySpec(
        "batch.remove_direction",
        "移除申请方向",
        "移除指定序号的申请方向。",
        "/batch",
        argument_hints='{"index": "从 0 开始的序号"}',
    ),
    "batch.clear_stories": CapabilitySpec(
        "batch.clear_stories",
        "清除方向故事",
        "清除当前申请方向选择的故事实例。",
        "/batch",
    ),
    "batch.select": CapabilitySpec(
        "batch.select",
        "选择批量任务",
        "查看指定的已保存批量任务。",
        "/batch",
        argument_hints='{"batch_id": "批量任务 ID"}',
    ),
    "batch.create": CapabilitySpec(
        "batch.create",
        "开始批量生成",
        "提交当前所有方向并创建批量文书生成任务。",
        "/batch",
        requires_confirmation=True,
    ),
    "batch.retry": CapabilitySpec(
        "batch.retry",
        "重试失败项",
        "重试当前批量任务中失败的文书。",
        "/batch",
        requires_confirmation=True,
    ),
    "batch.refresh": CapabilitySpec(
        "batch.refresh",
        "刷新批量任务",
        "重新读取当前用户的批量任务列表和进度。",
        "/batch",
    ),
    "batch.download_all": CapabilitySpec(
        "batch.download_all",
        "下载已完成文书",
        "把当前批次已完成的草稿合并下载为 Markdown。",
        "/batch",
    ),
    "batch.download_item": CapabilitySpec(
        "batch.download_item",
        "下载单篇文书",
        "下载指定批量任务项目中的文书。",
        "/batch",
        argument_hints='{"item_id": "批次项目 ID"}',
    ),
    "batch.open_result": CapabilitySpec(
        "batch.open_result",
        "打开批量文书",
        "加载指定批量项目对应的工作台并继续修改。",
        "/batch",
        argument_hints='{"item_id": "批次项目 ID"}',
    ),
    "library.person.create": CapabilitySpec(
        "library.person.create",
        "新增人物",
        "在申请项目页创建新人物。",
        "/library",
        requires_confirmation=True,
    ),
    "library.background.extract": CapabilitySpec(
        "library.background.extract",
        "提取简历背景",
        "从用户已经选择的简历文件提取背景信息。",
        "/library",
        requires_confirmation=True,
    ),
    "library.application_project.create": CapabilitySpec(
        "library.application_project.create",
        "记录申请项目",
        "为当前背景记录学校和专业项目。",
        "/library",
        requires_confirmation=True,
    ),
    "library.story.create": CapabilitySpec(
        "library.story.create",
        "开始故事访谈",
        "为当前申请项目创建并绑定故事访谈。",
        "/library",
        requires_confirmation=True,
    ),
    "library.story.reply": CapabilitySpec(
        "library.story.reply",
        "提交故事回答",
        "提交申请项目页中的当前故事访谈回答。",
        "/library",
        requires_confirmation=True,
    ),
    "library.generate_all": CapabilitySpec(
        "library.generate_all",
        "生成全部文书",
        "为当前装配画布内的全部文书分支提交生成任务。",
        "/library",
        requires_confirmation=True,
    ),
    "agent.cancel_pending": CapabilitySpec(
        "agent.cancel_pending",
        "取消待执行操作",
        "取消当前等待补充信息或确认的 Agent 操作。",
        "*",
    ),
    "agent.confirm_pending": CapabilitySpec(
        "agent.confirm_pending",
        "确认待执行操作",
        "在用户明确确认后提交当前待执行操作。",
        "*",
        argument_hints='{"action_id": "待执行操作 ID"}',
    ),
    "agent.undo_last_edit": CapabilitySpec(
        "agent.undo_last_edit",
        "撤销上次填写",
        "撤销最近一次由语音 Agent 写入的页面字段。",
        "*",
    ),
}

CAPABILITY_REQUIREMENTS: Dict[str, str] = {
    "profile.parse_resume": "页面中存在已选择且格式合法的简历文件。",
    "profile.continue_program": (
        "姓名、当前学校、当前专业、目标学位、目标专业方向、目标国家/地区，"
        "并且至少一项经历或已选择简历。"
    ),
    "profile.continue_batch": (
        "与进入项目分析相同的完整背景信息。"
    ),
    "program.analyze": (
        "已保存背景信息，以及学校、项目、文书类型、100-5000 字数、"
        "至少 10 字符的文书题目。"
    ),
    "program.continue_story": "存在且属于当前背景信息的项目分析。",
    "story.answer": "访谈中的故事会话和非空本轮回答。",
    "story.continue_result": "已完成三轮故事访谈且状态为 ready。",
    "essay.outline": "已完成访谈的故事会话。",
    "essay.draft": "已完成访谈的故事会话。",
    "essay.rewrite": "已有草稿和非空修改意见。",
    "essay.review": "已有英文草稿。",
    "essay.download": "已有可下载草稿。",
    "essay.copy": "已有可复制草稿。",
    "result.load_version": "当前会话中存在指定版本。",
    "history.load": "存在且属于当前用户的指定历史会话。",
    "batch.create": (
        "已保存背景信息；每个方向有学校和项目；至少一种文书；"
        "每种已启用文书有 100-5000 字数及至少 10 字符题目。"
    ),
    "batch.retry": "存在包含失败项目的批量任务。",
    "batch.remove_direction": "至少保留一个申请方向且索引有效。",
    "batch.open_result": "指定批次项目已完成并具有会话。",
}


def capability_catalog() -> List[Dict[str, Any]]:
    return [
        {
            "name": spec.key,
            "label": spec.label,
            "description": spec.description,
            "page": spec.path,
            "requires_confirmation": spec.requires_confirmation,
            "argument_hints": spec.argument_hints,
            "requirements": CAPABILITY_REQUIREMENTS.get(spec.key, ""),
        }
        for spec in CAPABILITIES.values()
    ]


def canonical_workflow_snapshot(
    owner_id: str,
    context: AgentPageContext,
    *,
    store: Optional[SQLiteStore] = None,
) -> Dict[str, Any]:
    db = store or get_store()
    profile = (
        db.get_profile(context.ids.profile_id, owner_id)
        if context.ids.profile_id
        else None
    )
    analysis = (
        db.get_analysis(context.ids.analysis_id, owner_id)
        if context.ids.analysis_id
        else None
    )
    session = (
        db.get_session(context.ids.session_id, owner_id)
        if context.ids.session_id
        else None
    )
    batch = (
        db.get_batch(context.ids.batch_id, owner_id)
        if context.ids.batch_id
        else None
    )
    history = db.list_history(owner_id)[:10]
    batches = db.list_batches(owner_id)[:10]
    return {
        "profile_id": profile.id if profile else "",
        "analysis_id": analysis.id if analysis else "",
        "analysis_matches_profile": bool(
            profile
            and analysis
            and analysis.profile_id == profile.id
        ),
        "session_id": session.id if session else "",
        "session_status": session.status if session else "not_started",
        "session_round": session.round_no if session else 0,
        "has_outline": bool(session and session.outline),
        "has_draft": bool(session and session.draft),
        "has_review": bool(session and session.review),
        "batch_id": batch.id if batch else "",
        "batch_status": batch.status if batch else "not_selected",
        "batch_item_count": len(batch.items) if batch else 0,
        "history_sessions": [
            {
                "session_id": item.session_id,
                "program": item.program_label,
                "status": item.status,
                "has_outline": item.has_outline,
                "has_draft": item.has_draft,
            }
            for item in history
        ],
        "recent_batches": [
            {
                "batch_id": item.id,
                "status": item.status,
                "item_count": len(item.items),
            }
            for item in batches
        ],
    }


def get_capability(name: str) -> Optional[CapabilitySpec]:
    return CAPABILITIES.get(name)


def infer_capability(
    transcript: str,
    context: AgentPageContext,
) -> Optional[AgentCapabilityCall]:
    text = re.sub(r"\s+", "", transcript.casefold())
    if not text:
        return None
    if any(
        word in text
        for word in (
            "取消操作",
            "取消刚才",
            "算了",
            "不要执行",
            "不用了",
            "不执行",
            "停止",
        )
    ):
        return AgentCapabilityCall(name="agent.cancel_pending", arguments={})
    if text in {
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
    }:
        return AgentCapabilityCall(name="agent.confirm_pending", arguments={})
    if text in {"撤销", "撤销刚才", "撤回刚才", "改回上一项", "恢复刚才"}:
        return AgentCapabilityCall(name="agent.undo_last_edit", arguments={})
    route_aliases = {
        "/profile": ("背景资料", "背景信息", "个人信息", "申请画像"),
        "/program": ("项目分析", "目标项目"),
        "/story": ("故事访谈", "故事挖掘", "访谈"),
        "/result": ("文书编辑", "文书工作台", "结果页", "生成结果"),
        "/batch": ("批量生成", "批量任务"),
        "/library": (
            "申请项目",
            "项目总览",
            "装配工作台",
            "实例库",
            "人物库",
            "背景库",
            "故事库",
        ),
    }
    if any(word in text for word in ("打开", "进入", "跳到", "前往", "去")):
        for path, aliases in route_aliases.items():
            if path != context.path and any(alias in text for alias in aliases):
                return AgentCapabilityCall(
                    name="app.navigate",
                    arguments={"path": path},
                )

    if context.path == "/profile":
        if "批量" in text:
            return AgentCapabilityCall(name="profile.continue_batch", arguments={})
        if "解析" in text and any(word in text for word in ("简历", "文件")):
            return AgentCapabilityCall(name="profile.parse_resume", arguments={})
        if "上传" in text and "简历" in text:
            return AgentCapabilityCall(name="profile.parse_resume", arguments={})
        if any(word in text for word in ("保存草稿", "存草稿")):
            return AgentCapabilityCall(name="profile.save_draft", arguments={})
        if any(word in text for word in ("继续", "提交", "下一步", "保存")):
            return AgentCapabilityCall(name="profile.continue_program", arguments={})
    if context.path == "/program":
        if any(word in text for word in ("分析", "开始", "继续", "提交")):
            return AgentCapabilityCall(name="program.analyze", arguments={})
        if any(word in text for word in ("故事", "访谈", "下一步")):
            return AgentCapabilityCall(name="program.continue_story", arguments={})
    if context.path == "/story":
        if any(word in text for word in ("进入结果", "生成结果", "下一步")):
            return AgentCapabilityCall(name="story.continue_result", arguments={})
        if any(word in text for word in ("回答", "发送", "提交")):
            return AgentCapabilityCall(name="story.answer", arguments={})
    if context.path == "/result":
        if "清空" in text and "历史" in text:
            return AgentCapabilityCall(name="history.clear", arguments={})
        if "审核" in text or "检查草稿" in text:
            return AgentCapabilityCall(name="essay.review", arguments={})
        if any(word in text for word in ("重写", "修改草稿", "按意见")) or (
            "修改" in text and "草稿" in text
        ):
            return AgentCapabilityCall(name="essay.rewrite", arguments={})
        if "大纲" in text:
            return AgentCapabilityCall(name="essay.outline", arguments={})
        if "草稿" in text or "正文" in text:
            return AgentCapabilityCall(name="essay.draft", arguments={})
    if context.path == "/batch":
        if "重试" in text:
            return AgentCapabilityCall(name="batch.retry", arguments={})
        if "刷新" in text:
            return AgentCapabilityCall(name="batch.refresh", arguments={})
        if "下载" in text:
            return AgentCapabilityCall(name="batch.download_all", arguments={})
        if any(word in text for word in ("开始", "生成", "提交", "创建")):
            return AgentCapabilityCall(name="batch.create", arguments={})
        if "添加" in text and "方向" in text:
            return AgentCapabilityCall(name="batch.add_direction", arguments={})
        if "删除" in text and "方向" in text:
            return AgentCapabilityCall(name="batch.remove_direction", arguments={})
    if context.path == "/library":
        if "新增" in text and "人物" in text:
            return AgentCapabilityCall(name="library.person.create", arguments={})
        if any(word in text for word in ("提取背景", "解析简历", "提取简历")):
            return AgentCapabilityCall(
                name="library.background.extract",
                arguments={},
            )
        if (
            any(word in text for word in ("记录项目", "添加项目", "创建项目"))
            and "故事" not in text
        ):
            return AgentCapabilityCall(
                name="library.application_project.create",
                arguments={},
            )
        if "故事" in text and any(
            word in text for word in ("开始", "创建", "挖掘", "新增")
        ):
            return AgentCapabilityCall(
                name="library.story.create",
                arguments={},
            )
        if "故事" in text and any(
            word in text for word in ("回答", "提交", "发送")
        ):
            return AgentCapabilityCall(
                name="library.story.reply",
                arguments={},
            )
        if "生成全部" in text or ("生成" in text and "全部文书" in text):
            return AgentCapabilityCall(
                name="library.generate_all",
                arguments={},
            )
    return None


def validate_ui_actions(
    context: AgentPageContext,
    actions: Sequence[AgentUiAction],
) -> List[AgentUiAction]:
    controls = {control.key: control for control in context.controls}
    valid: List[AgentUiAction] = []
    for action in actions[:6]:
        if action.type == "navigate":
            if action.path in ALLOWED_PATHS:
                valid.append(action)
            continue
        if action.type == "open_section":
            valid.append(action)
            continue
        if not action.target_key or action.target_key not in controls:
            continue
        control = controls[action.target_key]
        if control.disabled:
            continue
        if action.type == "fill" and control.kind not in {
            "text",
            "textarea",
            "select",
            "number",
            "checkbox",
        }:
            continue
        if action.type == "fill":
            normalized = _normalize_fill_value(control, action.value or "")
            if normalized is None:
                continue
            valid.append(action.model_copy(update={"value": normalized}))
            continue
        valid.append(action)
    return valid


def _normalize_fill_value(control: Any, value: str) -> Optional[str]:
    cleaned = value.strip()
    if control.kind == "select":
        compact = re.sub(r"\s+", "", cleaned.casefold())
        alias = SELECT_VALUE_ALIASES.get(control.key, {}).get(compact)
        if alias is not None:
            return alias
        for option in control.options:
            if cleaned == option.value:
                return option.value
            label = re.sub(r"\s+", "", option.label.casefold())
            option_value = re.sub(r"\s+", "", option.value.casefold())
            if compact in {label, option_value}:
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
        if control.max_length and control.max_length > 0
        else 12000 if control.kind == "textarea" else 2000
    )
    if len(cleaned) > max_length:
        return None
    return cleaned


def _missing(
    key: str,
    label: str,
    target_key: Optional[str] = None,
) -> AgentMissingField:
    return AgentMissingField(key=key, label=label, target_key=target_key)


def _control_value(
    context: AgentPageContext,
    *,
    key: str = "",
    label: str = "",
) -> str:
    for control in context.controls:
        if key and control.key == key:
            return str(control.value).strip()
        if label and label in control.label:
            return str(control.value).strip()
    return ""


def _profile_form(context: AgentPageContext) -> Dict[str, Any]:
    value = context.page_data.get("profile_form")
    return value if isinstance(value, dict) else {}


def _program_form(context: AgentPageContext) -> Dict[str, Any]:
    value = context.page_data.get("program_form")
    return value if isinstance(value, dict) else {}


def _batch_form(context: AgentPageContext) -> Dict[str, Any]:
    value = context.page_data.get("batch_form")
    return value if isinstance(value, dict) else {}


def _profile_missing(context: AgentPageContext) -> List[AgentMissingField]:
    form = _profile_form(context)
    requirements = [
        ("full_name", "姓名", "full-name"),
        ("current_university", "当前学校", "current-university"),
        ("major", "当前专业", "major"),
        ("target_degree", "目标学位", "target-degree"),
        ("target_field", "目标专业方向", "target-field"),
        ("target_country", "目标国家/地区", "target-country"),
    ]
    missing = [
        _missing(key, label, target)
        for key, label, target in requirements
        if not str(form.get(key) or "").strip()
    ]
    has_experience = any(
        str(form.get(key) or "").strip()
        for key in (
            "research_experience",
            "internship_experience",
            "project_experience",
            "activities_awards",
        )
    )
    if not has_experience and not bool(context.page_data.get("resume_selected")):
        missing.append(
            _missing(
                "experience",
                "至少一项经历或已选择的简历文件",
                "research-experience",
            )
        )
    return missing


def _program_missing(context: AgentPageContext) -> List[AgentMissingField]:
    form = _program_form(context)
    missing: List[AgentMissingField] = []
    if not context.ids.profile_id:
        missing.append(_missing("profile_id", "已保存的背景信息", "program-school_name"))
    for key, label in (
        ("school_name", "学校名称"),
        ("program_name", "项目名称"),
        ("essay_type", "文书类型"),
        ("prompt_text", "文书题目或具体要求"),
    ):
        if not str(form.get(key) or "").strip():
            missing.append(_missing(key, label, f"program-{key}"))
    prompt = str(form.get("prompt_text") or "").strip()
    if prompt and len(prompt) < 10:
        missing.append(
            _missing("prompt_text", "至少 10 个字符的文书题目", "program-prompt_text")
        )
    try:
        word_limit = int(form.get("word_limit") or 0)
    except (TypeError, ValueError):
        word_limit = 0
    if word_limit < 100 or word_limit > 5000:
        missing.append(
            _missing("word_limit", "100 到 5000 的字数上限", "program-word_limit")
        )
    return missing


def _batch_missing(
    context: AgentPageContext,
    store: SQLiteStore,
    owner_id: str,
) -> List[AgentMissingField]:
    form = _batch_form(context)
    directions = form.get("directions")
    if not isinstance(directions, list) or not directions:
        return [_missing("directions", "至少一个申请方向", "batch-tone")]
    missing: List[AgentMissingField] = []
    for direction_index, direction in enumerate(directions):
        if not isinstance(direction, dict):
            continue
        direction_id = str(direction.get("id") or direction_index)
        if not str(direction.get("school_name") or "").strip():
            missing.append(
                _missing(
                    f"directions.{direction_index}.school_name",
                    f"方向 {direction_index + 1} 的学校名称",
                    f"{direction_id}-school",
                )
            )
        if not str(direction.get("program_name") or "").strip():
            missing.append(
                _missing(
                    f"directions.{direction_index}.program_name",
                    f"方向 {direction_index + 1} 的项目名称",
                    f"{direction_id}-program",
                )
            )
        essays = direction.get("essays")
        if not isinstance(essays, dict):
            missing.append(
                _missing(
                    f"directions.{direction_index}.essays",
                    f"方向 {direction_index + 1} 的文书类型",
                    f"{direction_id}-types",
                )
            )
            continue
        enabled = 0
        for essay_type, essay in essays.items():
            if not isinstance(essay, dict) or not essay.get("enabled"):
                continue
            enabled += 1
            prefix = "ps" if essay_type == "Personal Statement" else "ml"
            try:
                words = int(essay.get("word_limit") or 0)
            except (TypeError, ValueError):
                words = 0
            if words < 100 or words > 5000:
                missing.append(
                    _missing(
                        f"directions.{direction_index}.{prefix}.word_limit",
                        f"方向 {direction_index + 1} 的目标字数",
                        f"{direction_id}-{prefix}-words",
                    )
                )
            prompt = str(essay.get("prompt_text") or "").strip()
            if len(prompt) < 10:
                missing.append(
                    _missing(
                        f"directions.{direction_index}.{prefix}.prompt_text",
                        f"方向 {direction_index + 1} 的文书题目",
                        f"{direction_id}-{prefix}-prompt",
                    )
                )
        if not enabled:
            missing.append(
                _missing(
                    f"directions.{direction_index}.essays.enabled",
                    f"方向 {direction_index + 1} 至少一种文书",
                    f"{direction_id}-types",
                )
            )
    if (
        not context.ids.profile_id
        or store.get_profile(context.ids.profile_id, owner_id) is None
    ):
        missing.insert(0, _missing("profile_id", "已保存的背景信息", "batch-tone"))
    return missing


def focus_action_for_missing(
    missing: Sequence[AgentMissingField],
) -> Optional[AgentUiAction]:
    for field in missing:
        if field.target_key:
            return AgentUiAction(
                type="focus",
                target_key=field.target_key,
                reason=f"补充{field.label}",
            )
    return None


def validate_capability(
    owner_id: str,
    context: AgentPageContext,
    call: AgentCapabilityCall,
    *,
    store: Optional[SQLiteStore] = None,
) -> List[AgentMissingField]:
    spec = get_capability(call.name)
    if spec is None:
        return [_missing("capability", "当前页面不支持该能力")]
    if spec.path != "*":
        if context.path != spec.path:
            return [_missing("page", f"请先进入 {spec.path} 页面")]
        matching_controls = [
            control
            for control in context.controls
            if control.capability == call.name
        ]
        if not matching_controls:
            return [_missing("operation", "当前页面中可用的操作按钮")]
        field_validated_actions = {
            "profile.parse_resume",
            "library.person.create",
            "library.background.extract",
            "library.application_project.create",
            "library.story.create",
            "library.story.reply",
        }
        if (
            call.name not in field_validated_actions
            and not any(not control.disabled for control in matching_controls)
        ):
            return [_missing("operation", "当前页面中可用的操作按钮")]

    db = store or get_store()
    args = call.arguments
    if call.name == "app.navigate":
        path = str(args.get("path") or "")
        if path not in ALLOWED_PATHS:
            return [_missing("path", "有效的页面路径")]
        return []
    if call.name == "agent.cancel_pending":
        return []
    if call.name == "agent.confirm_pending":
        pending = db.get_pending_agent_action(owner_id)
        if pending is None or pending.status != "prepared":
            return [_missing("action_id", "等待确认的 Agent 操作")]
        return []
    if call.name.startswith("profile."):
        if call.name == "profile.save_draft":
            return []
        if call.name == "profile.parse_resume":
            if not bool(context.page_data.get("resume_selected")):
                return [_missing("resume", "已选择的简历文件", "resume-file")]
            filename = str(context.page_data.get("resume_name") or "").lower()
            suffix = filename.rsplit(".", 1)[-1] if "." in filename else ""
            if suffix not in {"txt", "md", "pdf", "docx"}:
                return [_missing("resume", "TXT、MD、PDF 或 DOCX 简历", "resume-file")]
            return []
        return _profile_missing(context)
    if call.name == "program.analyze":
        missing = _program_missing(context)
        if context.ids.profile_id and db.get_profile(context.ids.profile_id, owner_id) is None:
            missing.insert(0, _missing("profile_id", "有效的背景信息", "program-school_name"))
        return missing
    if call.name == "program.continue_story":
        if not context.ids.analysis_id:
            return [_missing("analysis_id", "已完成的项目分析", "program-submit")]
        analysis = db.get_analysis(context.ids.analysis_id, owner_id)
        if analysis is None:
            return [_missing("analysis_id", "有效且属于当前用户的项目分析", "program-submit")]
        if context.ids.profile_id and analysis.profile_id != context.ids.profile_id:
            return [_missing("analysis_id", "与当前背景匹配的项目分析", "program-submit")]
        return []
    if call.name.startswith("story."):
        if not context.ids.session_id:
            return [_missing("session_id", "已开始的故事访谈", "story-answer")]
        session = db.get_session(context.ids.session_id, owner_id)
        if session is None:
            return [_missing("session_id", "有效且属于当前用户的故事会话", "story-answer")]
        if call.name == "story.answer":
            answer = str(args.get("answer") or context.page_data.get("story_answer") or "").strip()
            if not answer:
                return [_missing("answer", "本轮访谈回答", "story-answer")]
            if session.status != "interviewing":
                return [_missing("session_id", "仍在访谈中的故事会话", "story-answer")]
        if call.name == "story.continue_result" and session.status != "ready":
            return [_missing("story_round", "完成三轮故事访谈", "story-answer")]
        return []
    if call.name.startswith("essay.") or call.name.startswith("result.") or call.name.startswith("history."):
        if call.name in {"history.clear"}:
            return []
        if call.name == "history.load":
            session_id = str(args.get("session_id") or "")
            if not session_id or db.get_session(session_id, owner_id) is None:
                return [_missing("session_id", "有效的历史会话")]
            return []
        if not context.ids.session_id:
            return [_missing("session_id", "可用故事会话", "revision-instruction")]
        session = db.get_session(context.ids.session_id, owner_id)
        if session is None:
            return [_missing("session_id", "有效且属于当前用户的故事会话", "revision-instruction")]
        if call.name in {"essay.outline", "essay.draft", "essay.rewrite", "essay.review"} and session.status != "ready":
            return [_missing("story_round", "完成三轮故事访谈", "revision-instruction")]
        if call.name == "essay.rewrite":
            instruction = str(
                args.get("instruction")
                or context.page_data.get("revision_instruction")
                or ""
            ).strip()
            if not instruction:
                return [_missing("instruction", "修改意见", "revision-instruction")]
            if not session.draft:
                return [_missing("draft", "已生成的英文草稿", "revision-instruction")]
        if call.name == "essay.review" and not session.draft:
            return [_missing("draft", "已生成的英文草稿", "revision-instruction")]
        if call.name in {"essay.download", "essay.copy"} and not (
            session.draft or context.page_data.get("selected_artifact_draft")
        ):
            return [_missing("draft", "可下载或复制的英文草稿")]
        if call.name == "result.switch_tab" and str(args.get("tab") or "") not in {
            "outline",
            "draft",
        }:
            return [_missing("tab", "大纲或草稿视图")]
        if call.name == "result.load_version":
            version_id = str(args.get("version_id") or "")
            snapshot = db.session_snapshot(session.id, owner_id)
            if not version_id or not any(item.id == version_id for item in snapshot.versions):
                return [_missing("version_id", "当前会话中的有效文书版本")]
        return []
    if call.name.startswith("batch."):
        if call.name == "batch.add_direction":
            return []
        if call.name == "batch.create":
            missing = _batch_missing(context, db, owner_id)
            return missing
        if call.name == "batch.retry":
            batch_id = str(args.get("batch_id") or context.ids.batch_id)
            batch = db.get_batch(batch_id, owner_id) if batch_id else None
            if batch is None:
                return [_missing("batch_id", "有效的批量任务")]
            if batch.status not in {"failed", "partial_failed"}:
                return [_missing("batch_status", "包含失败项目的批量任务")]
            return []
        if call.name == "batch.select":
            batch_id = str(args.get("batch_id") or "")
            if not batch_id or db.get_batch(batch_id, owner_id) is None:
                return [_missing("batch_id", "有效的批量任务")]
            return []
        if call.name in {"batch.download_all", "batch.download_item", "batch.open_result"} and not (
            args.get("batch_id") or context.ids.batch_id
        ):
            return [_missing("batch_id", "当前批量任务")]
        if call.name == "batch.download_all":
            batch_id = str(args.get("batch_id") or context.ids.batch_id)
            batch = db.get_batch(batch_id, owner_id) if batch_id else None
            if batch is None:
                return [_missing("batch_id", "有效的批量任务")]
            if not any(
                item.status == "completed" and item.draft
                for item in batch.items
            ):
                return [_missing("completed_items", "已完成的文书")]
        if call.name in {"batch.download_item", "batch.open_result"}:
            item_id = str(args.get("item_id") or "")
            batch_id = str(args.get("batch_id") or context.ids.batch_id)
            batch = db.get_batch(batch_id, owner_id) if batch_id else None
            if batch is None or not any(item.id == item_id for item in batch.items):
                return [_missing("item_id", "有效的批量文书项目")]
        if call.name == "batch.remove_direction":
            try:
                index = int(args.get("index"))
            except (TypeError, ValueError):
                return [_missing("index", "要移除的方向序号")]
            directions = _batch_form(context).get("directions")
            if not isinstance(directions, list) or index < 0 or index >= len(directions):
                return [_missing("index", "有效的方向序号")]
            if len(directions) <= 1:
                return [_missing("directions", "至少保留一个申请方向")]
        return []
    if call.name.startswith("library."):
        if call.name == "library.person.create":
            if not _control_value(context, label="新人物姓名"):
                return [_missing("display_name", "新人物姓名")]
            return []
        if call.name == "library.background.extract":
            missing = []
            if not _control_value(context, key="workbench-person"):
                missing.append(_missing("person_id", "已选择的人物"))
            if not _control_value(context, key="workbench-resume-name"):
                missing.append(_missing("resume_name", "简历名称"))
            if not bool(context.page_data.get("resume_selected")):
                missing.append(_missing("resume", "已选择的简历文件"))
            return missing
        if call.name == "library.application_project.create":
            missing = []
            if not _control_value(context, key="workbench-background"):
                missing.append(_missing("background_id", "人物背景"))
            if not _control_value(context, key="workbench-school"):
                missing.append(_missing("school_name", "学校名称"))
            if not _control_value(context, key="workbench-program"):
                missing.append(_missing("program_name", "专业或项目名称"))
            return missing
        if call.name == "library.story.create":
            missing = []
            if not _control_value(context, key="workbench-story-project"):
                missing.append(_missing("application_project_id", "申请项目"))
            if not _control_value(context, key="workbench-story-title"):
                missing.append(_missing("title", "故事名称"))
            return missing
        if call.name == "library.story.reply":
            answer = str(
                call.arguments.get("answer")
                or context.page_data.get("library_story_reply")
                or ""
            ).strip()
            if not answer:
                return [_missing("answer", "本轮故事回答")]
        return []
    return []


def prepare_missing_for_capability(
    owner_id: str,
    context: AgentPageContext,
    capability: str,
    arguments: Dict[str, Any],
) -> List[AgentMissingField]:
    return validate_capability(
        owner_id,
        context,
        AgentCapabilityCall(name=capability, arguments=arguments),
    )


def capability_summary(
    capability: str,
    arguments: Dict[str, Any],
) -> str:
    spec = get_capability(capability)
    label = spec.label if spec else capability
    if capability == "app.navigate":
        return f"将跳转到 {arguments.get('path', '目标页面')}"
    if capability == "story.answer":
        answer = str(arguments.get("answer") or "")
        return f"将提交本轮回答：{answer[:80]}"
    if capability == "essay.rewrite":
        instruction = str(arguments.get("instruction") or "")
        return f"将按修改意见重写草稿：{instruction[:80]}"
    if spec and spec.requires_confirmation:
        return f"即将执行“{label}”。参数：{arguments or '使用当前页面数据'}"
    return f"将执行“{label}”。"
