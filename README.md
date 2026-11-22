# GradPilot

GradPilot 是一个面向研究生申请文书制作的全流程工作台。项目使用
Next.js 前端、FastAPI 后端、SQLite 持久化和多模型协作，支持从人物背景、
简历素材、申请项目、故事挖掘，到中文大纲、英文草稿、审核修订，以及
DOCX/PDF 导出的完整流程。

项目仓库：`https://github.com/3777368737-hub/Easy_PSML`

> 当前版本是可持续开发的内部 MVP，不是默认具备正式多租户安全能力的生产系统。
> 当前使用浏览器生成的匿名 `X-Client-Id` 隔离数据，不替代正式登录和鉴权。

## 目录

- [核心能力](#核心能力)
- [百炼 GLM 开通说明](#百炼-glm-开通说明)
- [系统架构](#系统架构)
- [快速启动](#快速启动)
- [环境变量](#环境变量)
- [使用流程](#使用流程)
- [文书导出](#文书导出)
- [项目结构](#项目结构)
- [后端模块](#后端模块)
- [API 概览](#api-概览)
- [数据与状态模型](#数据与状态模型)
- [测试与验证](#测试与验证)
- [部署说明](#部署说明)
- [常见问题](#常见问题)
- [安全与隐私](#安全与隐私)

## 核心能力

### 1. 人物与背景管理

- 一个申请人可以拥有多个具名简历背景。
- 每个背景可绑定多个学校和项目申请。
- 历史单简历流程仍保留兼容，并会自动同步到人物/背景实例模型。

### 2. 申请项目与故事素材

- 申请项目保存学校、项目、项目说明、故事和文书分支。
- 故事通过三轮对话式挖掘整理为动机、核心经历、成果、优势、职业目标和
  项目匹配等结构化卡片。
- 故事必须属于当前背景和申请项目，不能拖入不匹配的文书分支。

### 3. 文书制作

每篇文书拥有独立上下文：

- Personal Statement
- Motivation Letter
- 文书题目和字数限制
- 项目分析
- 中文大纲
- 英文草稿
- 草稿审核
- 历史版本

### 4. 批量生成

- 支持任意数量申请方向。
- 每个方向可选择 PS、ML 或两者。
- 每篇文书可以单独配置题目、字数和故事素材。
- 任务持久化到 SQLite，页面关闭后仍可由后端工作线程继续处理。
- 支持进度查看、单项失败和重试。

### 5. 纯语音与文字 Agent

- 实时 ASR 使用 WebSocket 持续接收麦克风音频。
- Agent 可以填写字段、聚焦控件、切换页面、打开区块和调用现有业务能力。
- Agent 不直接执行任意 DOM 操作，而是通过服务端能力注册表校验页面、
  必填字段、资源归属和确认级别。
- 提交、生成、审核和删除等操作要求二次确认。

### 6. DOCX/PDF 文书导出

- 用户在结果页先选择 `DOCX` 或 `PDF`。
- 后端调用阿里云百炼中的 `ZHIPU/GLM-5.3-Flash` 整理文书标题和段落排版。
- 后端使用 `python-docx` 和 `ReportLab` 生成真正的 Word/PDF 文件。
- 生成成功后浏览器自动下载文件。
- 调用期间展示等待进度条。
- 支持导出当前草稿和历史草稿版本。
- GLM 未开通、不可用或返回异常时，自动切换到标准排版，避免阻断下载。

## 百炼 GLM 开通说明

### 为什么需要先开通

`QWEN_API_KEY` 或 `DASHSCOPE_API_KEY` 是阿里云百炼的访问凭证，但 API Key
本身不等于某个模型的调用授权。调用智谱模型
`ZHIPU/GLM-5.3-Flash` 前，必须先在阿里云百炼控制台完成该模型的产品开通。

模型页面：

```text
https://bailian.console.aliyun.com/cn-beijing/model/market/detail/ZHIPU%2FGLM-5.3-Flash
```

操作步骤：

1. 登录阿里云百炼控制台，并确认区域与服务站点正确。
2. 搜索并打开 `ZHIPU/GLM-5.3-Flash` 模型详情。
3. 按页面提示开通模型或确认当前账号已获得调用权限。
4. 确认当前 `QWEN_API_KEY` 属于同一个百炼账号、区域和业务空间。
5. 重新启动后端，让新配置生效。

本项目复用现有 Qwen Key，不需要为 GLM 单独创建另一套 Key，配置如下：

```env
QWEN_API_KEY=sk-your-dashscope-key
DOCUMENT_EXPORT_MODEL=ZHIPU/GLM-5.3-Flash
DOCUMENT_EXPORT_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

如果模型尚未开通，百炼通常会返回类似错误：

```text
The product is not activated, please confirm that you have activated
products and try again after activation.
```

此时 GradPilot 仍会使用标准排版生成文件，并在前端提示“模型服务当前不可用或
尚未开通”。要使用 GLM 增强排版，必须先在百炼控制台完成开通。

### 模型如何参与文件生成

`ZHIPU/GLM-5.3-Flash` 通过百炼 OpenAI 兼容接口调用：

```text
POST /chat/completions
model = ZHIPU/GLM-5.3-Flash
```

Chat Completions 模型不会直接返回可下载的 PDF 二进制。GradPilot 采用两层流程：

1. GLM 读取已有英文草稿，只整理标题、元数据和段落结构，不改写正文。
2. 后端把结构化结果渲染为 `.docx` 或 `.pdf`。

这样既能实际调用 GLM，又能保证文件格式有效、中文不乱码、正文不被擅自改写。

## 系统架构

```text
浏览器
  |
  |-- Next.js / React
  |     |-- 页面表单与工作台
  |     |-- 实时语音控件
  |     |-- Agent 能力执行
  |     `-- DOCX/PDF 下载
  |
  |-- FastAPI
        |-- 人物、背景、申请项目和故事
        |-- 文书分析、大纲、草稿和审核
        |-- 批量任务工作线程
        |-- 语音 ASR WebSocket
        |-- Agent 能力注册与确认令牌
        |-- GLM 文书排版
        `-- DOCX/PDF 文件渲染
              |
              `-- SQLite
```

模型分工：

- `DeepSeek`：文书分析、大纲、草稿、审核等主要生成任务。
- `Qwen ASR`：实时语音识别。
- `Qwen Intent`：文字和语音 Agent 意图理解。
- `ZHIPU/GLM-5.3-Flash`：文书导出的结构和排版整理。

## 快速启动

### 环境要求

- Windows PowerShell
- Python `3.13`
- Node.js `22`
- npm `10`
- DeepSeek API Key
- 阿里云百炼 Qwen/DashScope API Key
- 如需 GLM 排版：已开通 `ZHIPU/GLM-5.3-Flash`

### 1. 安装后端

```powershell
cd D:\5051_project\pro-main
python -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

### 2. 安装前端

```powershell
cd frontend
npm ci
cd ..
```

### 3. 配置环境变量

```powershell
Copy-Item backend\.env.example backend\.env
Copy-Item frontend\.env.example frontend\.env.local
```

然后编辑 `backend\.env`，至少填写：

```env
DEEPSEEK_API_KEY=sk-your-key
QWEN_API_KEY=sk-your-dashscope-key
```

### 4. 启动

推荐使用项目控制台：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-GradPilot.ps1
```

控制台快捷键：

- `S`：启动或检查服务
- `T`：停止服务
- `R`：重启服务
- `B`：打开浏览器
- `L`：查看最近日志
- `Q`：停止服务并退出

默认地址：

- 前端：`http://127.0.0.1:3000`
- 后端：`http://127.0.0.1:8000`
- 健康检查：`http://127.0.0.1:8000/health`
- OpenAPI：`http://127.0.0.1:8000/docs`

也可以手动启动：

```powershell
# 终端 1
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 终端 2
cd frontend
npm run dev -- --hostname 127.0.0.1 --port 3000
```

## 环境变量

### 后端必填

| 变量 | 说明 |
| --- | --- |
| `DEEPSEEK_API_KEY` | 文书分析、大纲、草稿和审核 |
| `QWEN_API_KEY` | Qwen ASR、Agent 和 GLM 导出共用的百炼 Key |

也支持通过 `DASHSCOPE_API_KEY` 提供百炼 Key：

```env
DASHSCOPE_API_KEY=sk-your-dashscope-key
```

### DeepSeek

| 变量 | 默认值 |
| --- | --- |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | `deepseek-chat` |
| `DEEPSEEK_TEMPERATURE` | `0.25` |
| `DEEPSEEK_TIMEOUT_SECONDS` | `120` |
| `DEEPSEEK_MAX_RETRIES` | `2` |

### Qwen 与实时语音

| 变量 | 默认值 |
| --- | --- |
| `QWEN_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `QWEN_INTENT_MODEL` | `qwen-plus-latest` |
| `QWEN_ASR_MODEL` | `qwen-audio-3.1-asr-flash-streaming` |
| `QWEN_ASR_FILE_MODEL` | `qwen-audio-3.1-asr-flash` |
| `QWEN_ASR_VAD_MODEL` | `near_meeting_16k` |
| `QWEN_ASR_MAX_SENTENCE_SILENCE_MS` | `1200` |
| `QWEN_ASR_LANGUAGE` | `zh` |
| `VOICE_MAX_AUDIO_BYTES` | `6291456` |

### DOCX/PDF 导出

| 变量 | 默认值 |
| --- | --- |
| `DOCUMENT_EXPORT_MODEL` | `ZHIPU/GLM-5.3-Flash` |
| `DOCUMENT_EXPORT_BASE_URL` | 与 `QWEN_BASE_URL` 相同 |
| `DOCUMENT_EXPORT_TIMEOUT_SECONDS` | `120` |
| `DOCUMENT_EXPORT_MAX_RETRIES` | `1` |
| `DOCUMENT_EXPORT_MAX_TOKENS` | `7000` |

### 数据与服务

| 变量 | 默认值 |
| --- | --- |
| `DATABASE_PATH` | `data/gradpilot.db` |
| `APP_CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` |
| `MAX_UPLOAD_BYTES` | `10485760` |
| `MAX_RESUME_TEXT_CHARS` | `60000` |
| `MAX_RESUME_PAGES` | `30` |
| `MODEL_CALLS_PER_WINDOW` | `40` |
| `MODEL_RATE_WINDOW_SECONDS` | `600` |

### 前端

```env
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

所有 API Key 只能放在后端。不要创建 `NEXT_PUBLIC_*` 形式的密钥变量。

## 使用流程

### 推荐流程

```text
人物
  -> 简历背景
  -> 申请项目
  -> 故事挖掘
  -> 文书分支
  -> 项目分析
  -> 中文大纲
  -> 英文草稿
  -> 审核与修订
  -> DOCX/PDF 导出
```

### 操作步骤

1. 在 `/profile` 创建人物并保存简历背景。
2. 在 `/library` 创建学校和项目，绑定已完成故事。
3. 为项目创建 PS 或 ML 文书分支。
4. 在 `/result` 依次执行项目分析、大纲、草稿和审核。
5. 选择 `DOCX` 或 `PDF`，点击“生成并下载”。
6. 在 `/batch` 可以一次生成多个学校、项目和文书方向。

### 纯语音使用

页面右下角语音控件支持持续识别。用户可以直接说：

- “帮我创建一个新人物”
- “打开张三的科研简历”
- “创建一个申请项目”
- “继续说下一步”
- “生成中文大纲”
- “选择第二个故事”
- “下载当前文书”

Agent 会根据当前页面结构和业务状态判断下一步。缺少必要前置信息时，它会先
询问缺失字段，而不是直接执行不完整的生成操作。

## 文书导出

### 前端体验

- 结果页提供分段式 `DOCX / PDF` 选择。
- 点击后显示不确定进度条和模型处理状态。
- 文件由后端直接作为附件返回并自动下载。
- 历史版本可以独立导出。
- 失败状态只在导出区域显示，不清空当前草稿或页面内容。

### 后端接口

项目文书：

```http
POST /api/essay-projects/{project_id}/export
Content-Type: application/json
X-Client-Id: client-id

{
  "format": "docx",
  "artifact_version_id": "optional-draft-version-id"
}
```

旧版会话文书：

```http
POST /api/session/{session_id}/export
Content-Type: application/json
X-Client-Id: client-id

{
  "format": "pdf"
}
```

`format` 支持：

- `doc`：生成现代 Word `.docx` 文件
- `docx`：生成 `.docx` 文件
- `pdf`：生成 `.pdf` 文件

响应头：

- `Content-Type`：正确标识 DOCX 或 PDF
- `Content-Disposition`：下载文件名
- `X-Document-Formatting`：`glm` 或 `fallback`

### 降级规则

以下情况会使用标准排版：

- 未配置 Qwen/DashScope Key
- GLM 产品未开通
- 模型鉴权失败
- 模型超时或限流
- 模型返回无效 JSON
- 模型改动正文比例过大

标准排版仍使用已有草稿原文，不会因为模型失败而丢失文书。

## 项目结构

```text
pro-main/
├─ backend/
│  ├─ app/
│  │  ├─ main.py                     FastAPI 应用、路由和异常处理
│  │  ├─ config.py                   环境变量和运行配置
│  │  ├─ schemas.py                  Pydantic 请求/响应模型
│  │  ├─ errors.py                   业务错误类型
│  │  ├─ rate_limit.py               模型调用限流
│  │  └─ services/
│  │     ├─ workflow.py              旧版文书工作流
│  │     ├─ domain_workflow.py       人物/背景/故事/项目工作流
│  │     ├─ domain_store.py          实例域 SQLite 仓储
│  │     ├─ store.py                 旧版会话和兼容数据仓储
│  │     ├─ domain_agent.py          领域 Agent
│  │     ├─ agent.py                 Agent 执行与语音转写
│  │     ├─ agent_capabilities.py    页面能力注册、校验和确认
│  │     ├─ realtime_asr.py          实时语音 WebSocket 转发
│  │     ├─ qwen_client.py           Qwen 多模态和结构化调用
│  │     ├─ deepseek_client.py       DeepSeek 结构化调用
│  │     ├─ document_export.py       GLM 排版和 DOCX/PDF 渲染
│  │     ├─ batch.py                 持久化批量任务
│  │     └─ resume_parser.py         简历文件文本提取
│  ├─ tests/                         后端单元与 API 测试
│  ├─ requirements.txt
│  └─ .env.example
├─ frontend/
│  ├─ app/
│  │  ├─ page.tsx                    首页
│  │  ├─ profile/page.tsx            人物与背景
│  │  ├─ library/page.tsx            项目、故事和文书装配工作台
│  │  ├─ story/page.tsx              故事挖掘
│  │  ├─ program/page.tsx            申请项目输入
│  │  ├─ result/page.tsx             分析、大纲、草稿、审核和导出
│  │  └─ batch/page.tsx              批量生成
│  ├─ components/
│  │  ├─ app-shell.tsx               全局导航
│  │  ├─ voice-input-button.tsx      浮动语音控件
│  │  ├─ document-export-controls.tsx 格式选择和下载状态
│  │  └─ icon.tsx                    图标系统
│  ├─ lib/
│  │  ├─ api.ts                      API 与文件下载客户端
│  │  ├─ types.ts                    前端领域类型
│  │  ├─ voice-agent.ts              语音交互和页面能力执行
│  │  ├─ realtime-voice.ts           实时音频连接
│  │  └─ storage.ts                  浏览器本地状态
│  └─ package.json
├─ docs/                             设计、PRD 和语音/批量说明
├─ examples/                         示例数据
├─ render.yaml                       Render 后端部署配置
├─ Start-GradPilot.ps1               Windows 一键控制台
└─ README.md
```

## 后端模块

### 数据存储

- 单节点 SQLite。
- 人物、背景、故事、申请项目、文书项目和产物版本分别持久化。
- 简历原文件按匿名 owner 隔离保存。
- 旧版 `profiles`、`analyses`、`sessions` 数据会兼容同步。

### 模型客户端

- 模型返回必须通过 Pydantic Schema 校验。
- JSON 截断、空响应和格式错误会重试。
- 失败时返回受控业务错误，不把上游原始敏感内容直接传给前端。
- 所有模型调用共享按 owner 计的调用窗口限制。

### Agent

- 页面通过 `data-agent-capability` 暴露稳定的业务能力。
- 后端只允许注册表中的能力，不接受任意 JavaScript 或 DOM 选择器。
- 操作令牌包含页面上下文、参数摘要和一次性确认信息。
- 资源创建和修改仍走正常业务 API 与所有权检查。

### 批量任务

- 任务和阶段结果持久化在 SQLite。
- 后端启动时恢复未完成任务。
- 当前使用进程内工作线程，应只运行单个 Uvicorn worker。

## API 概览

| 模块 | 主要接口 |
| --- | --- |
| 健康检查 | `GET /health` |
| 人物 | `POST/GET /api/persons` |
| 背景 | `POST/GET/PATCH /api/backgrounds` |
| 申请项目 | `POST/GET/PATCH /api/application-projects` |
| 故事 | `POST /api/story-instances/start` |
| 故事回答 | `POST /api/story-instances/{id}/reply` |
| 文书项目 | `POST/GET/PATCH /api/essay-projects` |
| 项目分析 | `POST /api/essay-projects/{id}/analyze` |
| 大纲 | `POST /api/essay-projects/{id}/outline` |
| 草稿 | `POST /api/essay-projects/{id}/draft` |
| 审核 | `POST /api/essay-projects/{id}/review` |
| 项目导出 | `POST /api/essay-projects/{id}/export` |
| 旧会话导出 | `POST /api/session/{id}/export` |
| 文字 Agent | `POST /api/agent/text` |
| 领域 Agent | `POST /api/agent/domain` |
| 实时语音 | `WS /api/agent/voice/realtime` |
| 批量任务 | `POST/GET /api/batches` |

完整请求和响应模型可在 `/docs` 查看。

## 数据与状态模型

```text
Person
  └─ BackgroundInstance
       └─ ApplicationProject
            ├─ StoryInstance
            └─ EssayProject
                 ├─ Analysis
                 ├─ Outline
                 ├─ Draft
                 ├─ Review
                 └─ ArtifactVersions
```

关键约束：

- 故事必须属于当前背景。
- 绑定到申请项目的故事必须属于同一申请项目。
- 只有完成三轮挖掘的故事才能进入项目。
- 修改文书题目、项目信息或故事绑定后，已有分析和草稿会标记为过期。
- 每个项目可独立拥有 PS 和 ML 分支。

## 测试与验证

后端：

```powershell
cd backend
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

前端：

```powershell
cd frontend
npm run lint
npm run typecheck
npm run check:agent
npm run build
```

导出测试覆盖：

- DOCX 文件头、文件解析和标题内容
- PDF 文件头和多页解析
- GLM 正常路径
- GLM 不可用时的标准排版降级
- 非法格式
- 未生成草稿
- 跨 owner 访问

## 部署说明

### 后端

`render.yaml` 提供 FastAPI 后端和持久化磁盘配置：

- 构建：`pip install -r requirements.txt`
- 启动：`uvicorn app.main:app`
- 数据盘：`/var/data`
- 健康检查：`/health`

必须在部署平台配置：

- `DEEPSEEK_API_KEY`
- `QWEN_API_KEY` 或 `DASHSCOPE_API_KEY`
- `APP_CORS_ORIGINS`
- 如需正式前端域名，补充对应 CORS Origin

### 前端

前端需要单独部署，并设置：

```env
NEXT_PUBLIC_API_BASE_URL=https://your-backend.example.com
```

### 单实例限制

当前批量任务使用进程内工作线程，SQLite 也是单节点存储。不要在没有改造任务锁
和数据库的情况下启动多个 Uvicorn worker 或多实例并发写入。

## 常见问题

### 1. 有 Qwen API Key，但 GLM 仍然返回 not activated

API Key 只负责身份认证，不代表账号已经开通该模型。请到百炼控制台开通
`ZHIPU/GLM-5.3-Flash`，并确认 Key、区域、业务空间属于同一账号。

### 2. 文件可以下载，但 `X-Document-Formatting` 是 `fallback`

说明文件已用标准排版成功生成，但 GLM 调用没有成功。检查：

- 模型是否已开通
- Key 是否有效
- 百炼账户是否有余额或额度
- `DOCUMENT_EXPORT_BASE_URL` 是否正确
- `DOCUMENT_EXPORT_MODEL` 是否仍为 `ZHIPU/GLM-5.3-Flash`

### 3. 文件生成很慢

首次调用可能经过模型排队。前端会持续显示等待条。默认超时为 120 秒，可通过
`DOCUMENT_EXPORT_TIMEOUT_SECONDS` 调整。

### 4. PDF 中文乱码

当前 PDF 使用 ReportLab 内置的 `STSong-Light` CID 字体。请确认
`reportlab` 已通过 `requirements.txt` 安装，并重新启动后端。

### 5. 语音没有响应

- 检查浏览器麦克风权限
- 使用 `localhost` 或 `127.0.0.1` 访问
- 检查 `QWEN_API_KEY`
- 检查 `/api/agent/voice/realtime` WebSocket 是否可连接
- 查看后端日志中的 ASR 错误

### 6. 后端返回 429

默认每个匿名 owner 在 10 分钟内最多发起 40 次模型请求。可调整
`MODEL_CALLS_PER_WINDOW`，但不建议在生产环境取消限制。

## 安全与隐私

- `backend/.env` 已被忽略，不能提交到 Git。
- API Key 不能放入前端代码或 `NEXT_PUBLIC_*` 变量。
- `X-Client-Id` 不是正式认证，只能用于当前 MVP 的数据隔离。
- 正式接收真实申请资料前，应增加账号登录、服务端鉴权、审计日志、数据删除
  政策、数据库备份和更严格的限流。
- 简历原文件不应通过公开 URL 暴露。
- Agent 只能执行注册过的业务能力，不能接受任意脚本或选择器。

## 相关文档

- [实例工作流](docs/instance-workflow.md)
- [批量生成](docs/batch-generation.md)
- [语音 Agent](docs/voice-agent.md)
- [产品需求](docs/PRD.md)
- [设计审查](docs/DESIGN_AUDIT_ZH.md)

## License

本仓库为 source-available 的专有许可项目，具体条款见 `LICENSE`。
