# 实例化工作流

## 目标

GradPilot 的 PS/ML 生成不再把一次申请绑定成一个 `profile_id`。系统现在保存可复用的领域实例：

```text
Person
  ├─ BackgroundInstance（简历/背景快照）
  │    └─ ApplicationProject（学校/专业）
  │         ├─ StoryInstance A
  │         ├─ StoryInstance B
  │         └─ EssayProject PS / ML
```

一个人可以有多份简历背景；一个背景可以记录多个学校/专业申请项目；故事必须同时绑定背景和申请项目；一个申请项目可以生成 PS 和 ML 两份独立文书。装配工作台通过三表拖拽建立并校验这条链路。

## 数据结构

| 实体 | 用途 | 关键关系 |
| --- | --- | --- |
| `persons` | 人物身份 | 一个人可以有多份背景 |
| `person_aliases` | 人物语音别名 | 只用于解析，不作为主键 |
| `backgrounds` | 可命名、可选择的简历背景 | 绑定 `person_id`，同一人物下简历名唯一 |
| `background_versions` | 背景不可变版本 | 修改背景时新增版本，不覆盖旧数据 |
| `application_projects` | 学校/专业申请项目 | 绑定一份背景，可包含多个故事和文书分支 |
| `stories` | 项目针对性故事实例 | 同时绑定背景和申请项目，禁止跨链路装配 |
| `story_versions` | 故事消息、轮次和素材卡版本 | 三轮访谈过程中持续保存 |
| `essay_projects` | 一份学校/专业/PS 或 ML 的文书项目 | 绑定背景，并可引用多个故事 |
| `project_artifacts` | 文书大纲和草稿版本 | 每次生成新增版本 |

项目状态包括：`created`、`analyzed`、`outlined`、`drafted`、`reviewed`、`stale`。背景或已引用故事发生变化时，已有项目保留历史产物，但当前状态标记为 `stale`，需要重新分析或生成。

装配工作台把数据分成三张来源表：人物背景、申请项目、已挖掘故事。拖拽时，项目必须属于当前背景，故事必须同时属于该背景和申请项目；不匹配的链路在前端和服务端都会被阻止。每个申请项目可以配置 PS、ML、目标字数和语气，支持单分支生成，也支持一键提交全部未生成分支到持久化批量任务。

## 旧数据兼容

原有 `profiles`、`analyses`、`sessions` 和 `artifacts` 仍然保留。每次旧接口保存 profile 时，系统会同步创建一个默认人物和背景实例：

```text
legacy profile -> person + default background + background version
```

原始简历文件保存在数据库同级的 `resumes/` 目录，数据库保存文件名、SHA-256 和归属路径。
`GET /api/backgrounds/{background_id}/resume` 会再次校验 `owner_id` 后下载文件。
旧会话会在首次加载工作区时尽量映射为故事实例；已达到 `ready` 的旧会话会继续映射为文书项目，
其分析、大纲、草稿和审核内容保留。

旧批量接口只传 `profile_id` 时继续走原有执行路径；新批量接口传 `background_instance_id` 时走实例执行路径。

## API

### 实例查询和创建

- `GET /api/workspace`
- `POST /api/persons`
- `GET /api/persons`
- `PATCH /api/backgrounds/{background_id}`
- `PATCH /api/backgrounds/{background_id}/profile`
- `POST /api/application-projects`
- `GET /api/application-projects`
- `PATCH /api/application-projects/{project_id}`
- `POST /api/application-projects/{project_id}/essays`
- `POST /api/story-instances/start`
- `GET /api/story-instances/{story_id}`
- `PATCH /api/story-instances/{story_id}`
- `POST /api/story-instances/{story_id}/reply`
- `POST /api/agent/domain`

背景通过现有 `POST /api/profile/extract` 创建；新请求可以带：

```json
{
  "person_id": "...",
  "resume_name": "科研简历",
  "background_instance_id": null
}
```

文件仍然由用户在浏览器中选择，语音不能代替文件选择。

### 文书项目

- `POST /api/essay-projects`
- `GET /api/essay-projects`
- `GET /api/essay-projects/{project_id}`
- `PATCH /api/essay-projects/{project_id}`
- `POST /api/essay-projects/{project_id}/analyze`
- `POST /api/essay-projects/{project_id}/outline`
- `POST /api/essay-projects/{project_id}/draft`
- `POST /api/essay-projects/{project_id}/review`

一个文书项目只处理一种申请文书类型（PS 或 ML）。同一个背景和一个故事集合可以被多个文书项目引用，但每个项目拥有独立的项目分析、大纲、草稿和审核记录。

## 语音实例 Agent

旧语音 Agent 继续处理当前页面的表单控件。新增 `POST /api/agent/domain` 处理跨实例命令：

```text
ASR 文本
  -> Qwen 识别意图和参数
  -> 服务端按 owner_id 解析人物、背景、故事、文书项目
  -> 歧义时返回候选
  -> 结构化校验和确认
  -> 调用实例领域服务
  -> 写入版本并返回真实 ID
```

支持的领域操作包括：

- 创建/选择人物
- 选择人物下的简历背景
- 通过结构化 Patch 修改背景信息
- 基于背景创建故事、继续三轮访谈
- 修改故事素材卡
- 创建文书项目并选择故事
- 修改项目学校、专业、题目、字数和故事集合
- 执行项目分析、大纲、草稿和审核
- 创建批量任务

语音不会直接接受模型生成的任意数据库 ID。它发送的是人物名、简历名、故事名等查询条件，服务端在 `owner_id` 范围内解析并做归属校验。当前页面 Agent 的导航和表单能力仍然保留，但跨人物、跨背景的选择走领域 Agent。

## 运行边界

- 当前仍使用单进程 FastAPI worker 和 SQLite。
- 批量方向数量不设固定产品上限，但大量方向仍串行执行。
- 当前无正式登录和跨设备同步，`X-Client-Id` 只是匿名工作区标识。
- 真实语音和 Qwen 意图识别需要配置 `QWEN_API_KEY` 或 `DASHSCOPE_API_KEY`。
- 真实模型输出质量仍需要用实际项目题目和真实背景做验收，模拟测试只能验证结构、状态和安全边界。
