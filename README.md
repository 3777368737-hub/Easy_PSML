# GradPilot

GradPilot is a graduate-application essay workflow with a Next.js frontend and
a FastAPI backend.

Repository: `Easy_PSML`

## Project Status

This is an internal MVP intended for continued development, not a
production-ready multi-tenant service. Data is stored in single-node SQLite,
and browser access is scoped by an anonymous client identifier rather than a
formal user account.

## Requirements

- Node.js 22+
- Python 3.13+
- A DeepSeek API key
- A DashScope/Qwen API key for voice input and UI commands

## Configuration

Create `backend/.env` from `backend/.env.example` and set at least:

```env
DEEPSEEK_API_KEY=sk-your-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
QWEN_API_KEY=sk-your-dashscope-key
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_ASR_MODEL=qwen-audio-3.1-asr-flash-streaming
QWEN_ASR_FILE_MODEL=qwen-audio-3.1-asr-flash
QWEN_ASR_VAD_MODEL=near_meeting_16k
QWEN_ASR_MAX_SENTENCE_SILENCE_MS=1200
QWEN_INTENT_MODEL=qwen-plus-latest
APP_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
DATABASE_PATH=data/gradpilot.db
```

The API key is backend-only. Never place it in a `NEXT_PUBLIC_*` variable.

Voice commands use Qwen ASR plus a Qwen intent model. Configure
`QWEN_API_KEY` or `DASHSCOPE_API_KEY`; both keys remain backend-only.

The frontend reads `NEXT_PUBLIC_API_BASE_URL` and defaults to
`http://127.0.0.1:8000`. To override it for a remote API, create
`frontend/.env.local` from `frontend/.env.example`.

## Install

```powershell
python -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
cd frontend
npm ci
```

## Run

Run the GradPilot control center:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-GradPilot.ps1
```

The controller starts both services in one visible terminal and supports:

- `S`: start or check services
- `T`: stop services
- `R`: restart services
- `B`: open the browser
- `L`: show recent service logs
- `Q`: stop services and quit

Local URLs:

- Frontend: `http://localhost:3000`
- Backend: `http://127.0.0.1:8000`
- Health: `http://127.0.0.1:8000/health`

## Verify

```powershell
cd backend
.venv\Scripts\python.exe -m unittest discover -s tests -v

cd ..\frontend
npm run lint
npm run typecheck
npm run check:agent
npm run build
```

The same checks run in GitHub Actions for pushes to `main` and pull requests.

## Deployment Notes

`render.yaml` configures only the FastAPI backend and mounts a persistent disk
for SQLite. A production frontend deployment must be configured separately
with `NEXT_PUBLIC_API_BASE_URL` pointing at the backend's public HTTPS URL.

## Security Model

- `X-Client-Id` is an anonymous bearer-style identifier stored in browser
  local storage. It is not authentication.
- A public deployment should add authenticated accounts, a server-side rate
  limit that cannot be bypassed by changing the header, and a data retention
  policy before accepting real applicant data.
- `backend/.env` contains the DeepSeek API key and must never be committed,
  copied into a release bundle, or included in a repository upload.

## Data Model

- SQLite persists profiles, complete project context, analyses, sessions, and
  immutable outline/draft versions.
- Each browser receives an anonymous `X-Client-Id`; APIs only return resources
  owned by that client.
- Resume files are size-limited and parsed outside the FastAPI event loop.
- Raw resume text is not returned to or stored by the frontend.
- LLM JSON is schema-validated, checked for truncation, and retried before a
  safe error is returned.

## Required Inputs

- Profile: name, current university, current major, target degree, target
  field, target country, and either a resume or at least one experience.
- Program: school, program, essay type, word limit, and the essay prompt or
  specific requirements.
- GPA, graduation year, language score, motivation, career goal, and program
  website notes are optional.

## Instance Workflow

The assembly workbench at `/library` separates a person, a named resume
background, application projects, project-bound stories, and PS/ML branches:

```text
Person -> Background instances -> Application projects
                                      -> Stories
                                      -> PS / ML branches
```

A person can own multiple named resume backgrounds. A background can contain
multiple school/program application projects. Every three-round story is bound
to both its background and application project, and cannot be dragged to a
mismatched branch. Each application project can produce independent PS and ML
branches with their own prompt, tone, analysis, outline, draft, review, and
versions.

The existing single-profile flow remains available for backward compatibility.
Legacy profile saves create a default person/background mapping automatically.
See [the instance workflow design](docs/instance-workflow.md).

## Batch Generation

After saving a profile, choose the batch-generation action or open `/batch`.
Add any number of school/program directions and select PS, ML, or both for each
direction. Each essay has its own prompt and word limit. One submission
generates independent Chinese outlines and English drafts, with progress,
failed-item retry, TXT downloads, a combined Markdown download, and links to
the existing revision flow.

Batch generation can use a named background directly or select completed story
instances for each direction. When no story is selected it uses the complete
background and skips the interview. When stories are selected they are included
as evidence for the generated outline and draft.
Jobs persist in SQLite and continue after the page closes; unfinished work is
recovered when the backend restarts. Run a single backend process (no multiple
Uvicorn workers) for the current in-process queue. Each client can have one
active batch; model limits are checked for each generation stage.

See [the step-by-step implementation and rationale](docs/batch-generation.md).

## Voice Agent

The floating voice control keeps a duplex WebSocket open with
`qwen-audio-3.1-asr-flash-streaming`. It sends 16 kHz PCM continuously, refreshes
the chat transcript as recognition changes, and submits the current sentence to
the Agent after the configured VAD silence threshold. Recognition and the
microphone stay active until the user stops them. The agent can fill fields,
focus inputs, navigate between workflow stages, prepare button clicks, and
operate person/background/story/essay-project instances through the domain
Agent.
Submission, generation, review, sending, and destructive actions require an
explicit second confirmation.

The Agent uses a server-owned capability registry instead of arbitrary DOM clicks.
It validates workflow IDs, required fields, page-specific controls, confirmation
level, and ownership before creating a one-time action token. The browser executes
the selected capability against the existing React page handler through stable
`data-agent-capability` IDs.

See [the voice agent design and configuration](docs/voice-agent.md).

## License

This repository is public and source-available under a proprietary license.
See `LICENSE`.
