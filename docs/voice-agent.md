# GradPilot 语音填写 Agent

## 目标

语音 Agent 让用户通过语音完成 GradPilot 中的表单填写、字段定位、页面跳转，
并在满足边界时执行下一步按钮。它不是让模型直接操作浏览器，而是执行一条受控的
UI 动作流水线：

1. 浏览器持续发送 16 kHz PCM 音频到后端 WebSocket。
2. 后端代理 `qwen-audio-3.1-asr-flash-streaming`，实时转发中间字幕。
3. 模型 VAD 判定当前句结束后，前端自动将最终识别文本提交给 Agent。
4. Qwen 意图模型根据当前页面、控件清单和流程状态返回结构化动作。
5. 后端校验控件、路径、禁用状态和动作风险。
6. 服务端能力注册表校验前置状态、必填项、页面按钮和确认级别。
7. 前端通过稳定 `data-agent-capability` 语义 ID 执行真实页面逻辑。
8. 麦克风和识别会话不会因静音、Agent 回复或页面切换而自动关闭。

## Qwen 配置

在 `backend/.env` 中配置：

```env
QWEN_API_KEY=your_dashscope_api_key
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_ASR_MODEL=qwen-audio-3.1-asr-flash-streaming
QWEN_ASR_FILE_MODEL=qwen-audio-3.1-asr-flash
QWEN_ASR_WS_URL=
QWEN_ASR_VAD_MODEL=near_meeting_16k
QWEN_ASR_MAX_SENTENCE_SILENCE_MS=1200
QWEN_INTENT_MODEL=qwen-plus-latest
QWEN_ASR_LANGUAGE=zh
VOICE_MAX_AUDIO_BYTES=6291456
```

也支持使用 `DASHSCOPE_API_KEY` 作为 `QWEN_API_KEY` 的后备变量。

`QWEN_BASE_URL` 必须是包含 `/compatible-mode/v1` 的完整兼容接口根地址。
如果当前阿里云账号使用业务空间专属域名，请替换为控制台给出的域名，例如：

```env
QWEN_BASE_URL=https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
```

实时识别默认从 `QWEN_BASE_URL` 的主机名推导
`wss://{host}/api-ws/v1/inference`。如需单独覆盖，可配置 `QWEN_ASR_WS_URL`。

美国地域不支持 Qwen ASR 的 OpenAI 兼容模式，需要按阿里云文档选择可用地域。

## 后端接口

### `POST /api/agent/domain`

用于操作可复用实例，而不是只操作当前页面控件。请求包含语音文本、最近对话和当前活动的
`person/background/application-project/story/project` ID。服务端会在当前 `owner_id`
范围内解析人物、简历背景、申请项目、故事和文书分支，歧义时返回候选，不会直接采信模型编造的 ID。

```json
{
  "transcript": "用张三科研简历的科研故事，修改港大 DS 项目第二段草稿",
  "active_person_id": "",
  "active_background_id": "",
  "active_application_project_id": "",
  "active_story_id": "",
  "active_project_id": "",
  "confirmed": false,
  "source": "voice"
}
```

领域 Agent 支持人物和背景选择、背景字段 Patch、故事创建/回答/素材修改、文书项目创建和字段修改、
项目分析、大纲、草稿、审核以及批量任务创建。生成、保存、提交回答和批量创建等操作仍需要明确确认。
返回结果中的真实人物、背景、故事和项目 ID 会写回浏览器活动上下文。

### `POST /api/agent/text`

用于文字输入和无麦克风时的降级操作。

```json
{
  "transcript": "把学校填成香港科技大学",
  "context": {},
  "history": []
}
```

### `POST /api/agent/voice`

`multipart/form-data` 字段：

- `audio`: 浏览器录音，支持 Qwen ASR 的常见音频格式。
- `context`: `AgentPageContext` JSON。
- `history`: 最近几轮对话 JSON。

两个接口返回相同的结构化动作：

```json
{
  "transcript": "把学校填成香港科技大学",
  "message": "已将学校名称填写为“香港科技大学”。",
  "intent": "fill_form",
  "actions": [
    {
      "type": "fill",
      "target_id": "agent-control-0",
      "target_key": "program-school_name",
      "value": "香港科技大学",
      "reason": "用户要求填写学校名称",
      "risk": "safe"
    }
  ],
  "needs_confirmation": false,
  "source": "voice"
}
```

### `WS /api/agent/voice/realtime`

浏览器建立 WebSocket 后先发送：

```json
{
  "type": "start",
  "context": {},
  "history": [],
  "sample_rate": 16000
}
```

后端启动流式任务后返回 `asr_ready`。此后浏览器只发送二进制 PCM 帧。识别中间结果
通过 `transcript` 事件持续刷新同一个用户气泡，`sentence_end=true` 时自动提交
Agent。用户停止时发送：

```json
{"type": "stop"}
```

后端发送 `finish-task`，继续接收当前句的最终结果，然后返回 `asr_finished`。

### Agent 能力协议

`qwen-plus-latest` 只返回一个领域能力和结构化参数，不再返回任意 DOM 点击：

```json
{
  "message": "项目分析还不能执行，需要补充项目名称和文书题目。",
  "intent": "operate",
  "capability": {
    "name": "program.analyze",
    "arguments": {}
  },
  "ui_actions": [],
  "missing_fields": [],
  "next_field": "program-program_name",
  "needs_confirmation": false
}
```

服务端维护完整能力目录，包括背景信息、项目分析、故事访谈、文书生成、
版本与历史、批量任务和页面跳转。每项能力包含所属页面、参数提示、确认要求和
必要条件。

核心边界由确定性代码执行，而不是只依赖提示词：

- 当前页面必须存在对应语义能力按钮。
- 已保存资源必须存在并属于当前 `X-Client-Id`。
- 项目分析、故事会话、草稿和历史之间的归属关系必须一致。
- 背景、项目、批量方向及文书字段按真实 API 限制校验。
- `ui_actions` 只能填写当前页面可编辑控件或跳转到白名单页面。

待补全或待确认操作会保存到 SQLite，有效期 15 分钟。用户刷新页面后仍会恢复。
确认接口会重新读取当前页面状态，校验失败则退回 `needs_input`，不会执行旧参数。
确认令牌只能提交一次。

### 语义页面能力

页面按钮使用稳定能力 ID，例如：

```html
<button data-agent-capability="program.analyze">开始项目分析</button>
<button data-agent-capability="essay.draft">生成英文草稿</button>
```

Agent 执行时仍然调用页面原有 React handler，因此 API、浏览器缓存、页面提示和状态
流转不会出现两套实现。文件选择必须由用户完成，Agent 只能定位文件输入框。

## 前端控件感知

核心实现位于 `frontend/lib/voice-agent.ts`。

每次发送命令前，前端扫描当前 `<main>` 中的：

- `input`
- `textarea`
- `select`
- `button`
- `a[href]`

清单只包含模型操作所需的精简信息：

- 临时控件 ID
- 稳定字段键，例如 `program-school_name`
- 控件类型和标签
- 当前值、占位文本和下拉选项
- 必填、禁用和风险级别
- 所在页面与流程状态

`AgentPageContext` 同时包含全部五个业务阶段、字段目录和操作边界。因此模型即使
需要前往另一页，也只会返回受控的 `navigate` 动作，并在跳转后按 `target_key`
定位目标字段。

## 风险边界

- `safe`: 聚焦、填写、切换标签、查看历史版本、页面跳转。
- `confirm`: 提交表单、发送访谈回答、生成大纲/草稿、审核、批量生成、重试。
- `blocked`: 服务端拒绝执行，例如不可填写或不在当前控件清单中的目标。
- 文件选择不能由模型伪造，只能定位到文件输入框，由用户手动选择。
- 模型不能返回 JavaScript、任意 DOM 选择器或外部 URL。
- 跨页跳转只允许 `/`、`/profile`、`/program`、`/story`、`/result`、`/batch`。
- 动作最多执行三个，避免一个语音误判触发大范围操作。

服务端 `backend/app/services/agent.py` 会再次验证模型结果，不依赖模型自行遵守
边界。即使模型返回不存在的控件、外部路径或禁用按钮，动作也会被丢弃。

## 页面扩展

普通输入框和按钮只要位于页面 `<main>` 中即可自动被扫描。需要更稳定语义或显式
风险时，可以给元素添加：

```html
<input
  id="program-school_name"
  data-agent-key="program-school_name"
  data-agent-risk="safe"
/>

<button
  data-agent-key="program-submit"
  data-agent-risk="confirm"
>
  开始项目分析
</button>
```

新增业务阶段时，还需要同步更新：

1. `frontend/lib/voice-agent.ts` 中的 `AGENT_WORKFLOW`。
2. `PAGE_META` 中的页面摘要。
3. 后端 `ALLOWED_AGENT_PATHS`。
4. 相关 API 测试。

## 隐私与运行限制

- 录音只随当前请求发送到后端和 Qwen，不写入项目数据库。
- 当前页面字段值会发送给 Qwen 用于意图判断，因此应避免在输入框中填写 API Key、
  密码或证件号。
- 实时会话持续发送 PCM，不创建上传文件；旧文件上传接口仍保留用于兼容。
- VAD 默认使用 `near_meeting_16k`，静音断句阈值为 1200 ms，可通过环境变量调整。
- 语音记录保存在浏览器本地存储中，可在右侧面板中清空。
- Qwen 未配置或调用失败时，右侧面板仍可直接输入文字指令。

## 验证

```powershell
cd backend
.venv\Scripts\python.exe -m unittest discover -s tests -v

cd ..\frontend
npm run lint
npm run typecheck
npm run check:agent
npm run build
```

## 变更记录

### 2026-11-20

完成 GradPilot 语音填写 Agent 的首版闭环：

- 接入 Qwen3-ASR-Flash，支持浏览器 MediaRecorder 录音上传和文字指令降级。
- 接入可配置 Qwen 意图模型，配置项包括 API Key、兼容接口地址、ASR 模型和意图模型。
- 增加 `/api/agent/text` 与 `/api/agent/voice` 接口。
- 前端自动感知当前页面输入框、下拉框、按钮和链接，并向模型提供精简后的控件清单。
- 支持填写字段、聚焦控件、跨页面跳转，以及跳转后按稳定字段键自动聚焦。
- 增加服务端动作白名单，校验控件存在性、禁用状态、下拉选项、数字范围和文本长度。
- 增加提交、生成、发送、审核和不可恢复操作的二次确认。
- 增加右侧可滚动语音操作记录面板、本地历史记录、清空记录和文字输入降级。
- 增加启动脚本 Qwen Key 检查、Render 环境变量和前端 API 地址配置。

主要新增文件：

- `backend/app/services/agent.py`
- `backend/app/services/qwen_client.py`
- `backend/tests/test_agent.py`
- `frontend/lib/voice-agent.ts`
- `frontend/components/voice-input-button.tsx`
- `frontend/app/icon.svg`

主要修改文件：

- `backend/app/config.py`
- `backend/app/main.py`
- `backend/app/schemas.py`
- `backend/app/services/prompts.py`
- `frontend/lib/api.ts`
- `frontend/lib/storage.ts`
- `frontend/app/globals.css`
- `Start-GradPilot.ps1`
- `README.md`
- `render.yaml`

验证结果：

- 后端单元测试 32 项通过。
- `npm run lint` 通过。
- `npm run typecheck` 通过。
- `npm run build` 通过。
- 真实 Chrome MediaRecorder 录音、Qwen ASR、意图识别和字段回填已联调通过。
- 已验证跨页跳转后自动聚焦，以及提交类按钮在用户确认前不会发起请求。
- 已检查桌面和 390 px 手机视口，面板无横向溢出。
