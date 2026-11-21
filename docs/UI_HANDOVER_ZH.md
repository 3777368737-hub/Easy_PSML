# GradPilot 前端 / UI 改版交接

本次基于你提供的 Easy_PSML-main.zip 修改真实 Next.js 前端，保留原有 FastAPI、DeepSeek 调用及数据模型。未新增 UI 依赖，未改变 API URL、请求字段或返回数据结构。

## 先怎样使用

如果已有正常运行的项目：备份原来的 `frontend`，再合并本包的 `frontend/app`、`frontend/components` 与 `frontend/lib/storage.ts`。保留你自己的 `.env.local` 和后端配置。包内 `docs/UI_HANDOVER_ZH.md`、`docs/UI_TEST_RESULTS.md` 和 `examples/ui` 可一起交给组员。

如果从本 ZIP 重新运行，在项目根目录打开 PowerShell，先按原 README 安装依赖：

```powershell
python -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
Copy-Item backend\.env.example backend\.env
# 用编辑器在 backend/.env 中填写 DEEPSEEK_API_KEY；不要将真实密钥交到 Canvas。
cd frontend
npm ci
npm run dev
```

另开一个 PowerShell，在项目根目录运行：

```powershell
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

浏览器打开 http://localhost:3000 。如已经使用原项目控制台，也可继续运行根目录 `Start-GradPilot.ps1`。推荐使用仓库原定 Node.js 22 / npm 10 与 Python 3.13+。本次验证环境是 Node.js 24.22.3 / npm 11.9.0 与 Python 3.12，构建及测试均通过，但未替你们验证 Node 22 / Python 3.13 环境。

只启动前端即可查看页面、填写表单和保存表单草稿。简历解析、项目分析、访谈、文书生成和历史数据需要后端及有效 API Key。

## 页面改动

| 页面 | 主要改动 |
| --- | --- |
| 首页 `/` | 申请工作台布局、品牌视觉、文书结构示意、四步流程入口 |
| 背景 `/profile` | 上传区域、基本信息/申请方向/经历/动机分组、示例提示、写作指导栏、保存表单草稿、底部操作栏 |
| 项目 `/program` | 分组表单、官网资料填写指导、分析卡片、缺少背景时返回入口；修改输入后隐藏旧分析以免误用 |
| 访谈 `/story` | 当前轮次条、对话作者、素材库、自动滚动、输入字符计数、Ctrl/Cmd+Enter 发送、失败重新连接入口 |
| 结果 `/result` | 中文/英文视图、阅读式排版、空状态、英文词数、复制/下载、历史版本返回当前版本 |
| 装配工作台 `/library` | 人物背景、申请项目、故事三表拖拽装配，链路校验、整网/单链路生成和语气修正 |
| 全局 | 侧栏高亮、步骤导航、移动端布局、焦点样式、跳过导航、状态播报、减少动画偏好 |

历史版本展示修正：选择只包含大纲的版本后，不会把当前草稿混进该历史版本；历史版本禁止直接重写，需返回当前版本。词数按空白分隔计算，是界面参考值，不等同于所有学校的计数规则。

## 文件职责与维护

| 文件 | 职责 |
| --- | --- |
| `frontend/components/app-shell.tsx` | 侧栏、面包屑、四步骤导航、全局页脚 |
| `frontend/components/icon.tsx` | 项目内部 SVG 图标，避免额外图标库 |
| `frontend/app/globals.css` | 色彩变量、组件样式、响应式断点、焦点与动画设置 |
| `frontend/app/layout.tsx` | 共享外壳、页面元信息 |
| `frontend/app/page.tsx` | 首页内容与流程入口 |
| `frontend/app/profile/page.tsx` | 背景表单和草稿保存 |
| `frontend/app/program/page.tsx` | 项目输入与分析展示 |
| `frontend/app/story/page.tsx` | 访谈与素材展示 |
| `frontend/app/result/page.tsx` | 大纲、草稿、审核、版本、历史 |
| `frontend/lib/storage.ts` | 新增 `gradpilot_profile_draft` 存储键 |

改主色：修改 globals.css 的 `--primary`、`--primary-dark`、`--mint`。改某页文案：修改对应 page.tsx。改 API 逻辑仍由 `frontend/lib/api.ts` 和后端负责；本次没有修改这两个接口层。

表单草稿只存于当前浏览器 localStorage，不包括上传文件，也不代表 AI 已提取完成。用户须点击“保存表单草稿”，未保存的修改不是自动保存。解析成功或正式提交成功会清掉旧表单草稿，防止旧值覆盖新的解析结果。

## 如何解释你的贡献

可参考下面的表述，并按你实际理解、修改和验证过的内容调整：

> 负责 GradPilot 的前端/UI 改版与交互整合：统一五个页面的工作台布局与视觉规范；重组背景和项目表单；完善访谈、文书和历史版本界面；实现本地表单草稿、快捷发送、复制与字数统计；验证输入错误、离线提示和移动布局，并编写交接文档。开发中使用 AI 辅助生成与检查代码。

不要将本次工作描述为重新实现模型、数据库或后端；这些来自你提供的原项目。不要声称已经完成真实 API 全流程测试；参见测试记录。

## 交接给组员时实际做一次

1. 让另一位成员按 README 独立启动前后端。
2. 让他修改首页一句文案或 CSS 主色，确认能找到正确文件。
3. 用 `examples/ui/cases.json` 的两组虚构输入跑完整流程；每组完成三轮访谈，生成大纲和草稿，再修改一次。
4. 检查版本切换、返回当前版本、复制、下载和历史恢复，保存实际输出。
5. 记录真实遇到的问题和解决方法，作为课程要求的 handover lesson。

## 对照老师提交要求

这份包是前端任务交付，包含完整原项目与改版代码、示例输入、UI 测试记录；不是已经补齐全部课程材料的最终 `project2.zip`。小组还应完成：

- README 顶部的真实成员、学号、各人贡献表；正文不超过 500 词。
- 配置真实 API 后，两组代表性完整 AI 输出及至少一个失败案例。
- 实际交接记录；不能把建议步骤当成已经发生的合作事实。
- 6 分钟演示使用的 PDF/PPTX/独立 HTML slides。
- 核查复用项目与 AI 辅助的 credits，不打包密钥、数据库、node_modules 或 .venv。

PDF 中的团队提交日期是 2026-11-23，课堂展示日期是 2026-11-24。
