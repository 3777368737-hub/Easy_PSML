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

## Configuration

Create `backend/.env` from `backend/.env.example` and set at least:

```env
DEEPSEEK_API_KEY=sk-your-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
APP_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
DATABASE_PATH=data/gradpilot.db
```

The API key is backend-only. Never place it in a `NEXT_PUBLIC_*` variable.

The frontend reads `NEXT_PUBLIC_API_BASE_URL` and defaults to
`http://localhost:8000`. To override it for a remote API, create
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

## License

This repository is public and source-available under a proprietary license.
See `LICENSE`.
