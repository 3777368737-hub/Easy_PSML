# GradPilot PRD（开发交付版 v1.2）

## 1. 文档信息
- 产品：GradPilot（研究生申请文书助手）
- 版本：v1.2（可靠性增强版）
- 更新时间：2026-11-18
- 平台：Web（Next.js 前端 + FastAPI 后端）

## 2. 目标与范围
### 2.1 目标
- 让用户在一个闭环流程中完成：背景采集 → 项目分析 → 故事挖掘 → 文书生成与重写。
- 支持历史记录回看与复用，降低重复劳动。

### 2.2 范围（In Scope）
- 四步流程页面与状态流转
- 简历上传解析
- 项目分析
- 3问一轮故事挖掘
- 中文大纲 + 英文草稿 + 修改重写
- SQLite 历史记录与大纲/草稿版本
- 匿名浏览器身份隔离
- 草稿审核

### 2.3 非范围（Out of Scope）
- 正式账号与跨设备同步（当前使用浏览器匿名标识）
- 支付与权限分层

## 3. 用户故事
1. 作为申请者，我希望上传简历后自动回填信息，减少手动输入。
2. 作为申请者，我希望输入目标项目后获得可执行的写作策略。
3. 作为申请者，我希望 AI 提问更有针对性且不重复。
4. 作为申请者，我希望先看中文大纲，再生成英文草稿。
5. 作为申请者，我希望对不满意草稿输入修改意见并重写。
6. 作为申请者，我希望保留每次生成结果并可随时加载历史版本。

## 4. 业务流程与状态机
### 4.1 主流程
1. 首页 `/`
2. 第1步 `/profile`
3. 第2步 `/program`
4. 第3步 `/story`
5. 第4步 `/result`

### 4.2 状态机（简化）
- IDLE
- PROFILE_READY
- ANALYSIS_READY
- STORY_READY
- OUTLINE_READY
- DRAFT_READY

### 4.3 关键状态约束
1. `profile_id` 不存在，不可提交项目分析。
2. `analysis_id` 不存在，不可启动故事会话。
3. `session_id` 不存在，不可生成大纲/草稿。
4. 新一轮 profile 解析后，必须清空下游状态。
5. analysis 必须属于提交的 profile。
6. 完成三轮访谈后才可生成大纲和草稿。
7. 每次大纲或草稿生成必须创建不可覆盖的版本。

## 5. 页面与交互需求
### 5.1 首页
- 展示价值主张、流程、立即开始入口、三张特性卡片。
- 标题支持两行展示，移动端自适应。

### 5.2 第1步 背景信息
- 上传简历（txt/pdf/docx）
- 一键解析并回填
- 手动补充并提交
- 必填：姓名、当前学校、当前专业、目标学位、目标专业方向、目标国家/地区。
- 简历与科研/实习/项目/活动经历至少提供一项。
- 选填：GPA、毕业年份、语言成绩、申请动机、职业目标。

### 5.3 第2步 项目分析
- 输入学校/项目/文书类型/字数/题目要求
- 可粘贴项目官网、课程和教授方向等事实资料
- 输出关注点、优势、短板、建议
- 必填：学校、项目、文书类型、字数上限、文书题目或具体要求。
- 选填：项目官网资料、课程和教授方向。

### 5.4 第3步 故事挖掘
- 每轮 3 个个性化问题
- 回答后更新结构化卡片
- 会话与 profile+analysis 强绑定

### 5.5 第4步 结果生成
- 生成中文大纲
- 生成英文草稿
- 输入修改意见重写草稿
- 查看草稿审核结果
- 加载历史大纲或草稿版本
- 展示并加载历史记录

## 6. API 清单
- GET `/health`
- POST `/api/profile/extract`
- POST `/api/program/analyze`
- POST `/api/story/start`
- POST `/api/story/reply`
- POST `/api/essay/outline`
- POST `/api/essay/draft`
- POST `/api/review/run`
- GET `/api/session/{session_id}`
- GET `/api/history`
- DELETE `/api/history`

## 7. 数据存储
- 服务端 SQLite 保存 profile、project context、analysis、session、artifact versions。
- 浏览器保存匿名 `X-Client-Id` 和当前流程缓存。
- 所有业务接口按匿名客户端身份隔离。

前端缓存键：
- `gradpilot_profile`
- `gradpilot_program_form`
- `gradpilot_analysis`
- `gradpilot_story_session`
- `gradpilot_result_snapshot`
- `gradpilot_client_id`

## 8. 错误处理
- 非 2xx：展示安全错误信息和请求编号。
- 模型 JSON 被截断、非法或不符合 Schema 时自动重试。
- 重试失败返回 `502 model_output_invalid`，不向客户端暴露原始解析异常。
- 资源不存在或不属于当前客户端统一返回 `404`。
- 模型调用按客户端限流。

## 9. 埋点建议
- home_start_click
- profile_resume_parse_success
- program_analyze_success
- story_reply_submit
- outline_generate_click
- draft_generate_click
- draft_rewrite_click
- history_load_click

## 10. 性能与验收
- 首屏可交互 < 3s（良好网络）
- 草稿生成成功率 > 95%
- 项目分析与草稿使用原始学校、项目、文书类型、题目和字数要求
- 后端重启后历史会话仍可恢复
- 大纲和草稿版本不可相互覆盖
- 任意客户端不能读取其他客户端的数据
- 新一轮开始后无旧分析/旧故事残留
- 历史记录可创建、加载、清空
