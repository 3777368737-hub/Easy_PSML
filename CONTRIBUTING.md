# Contributing

## Development setup

Follow the installation and configuration steps in `README.md`.
Use Node.js 22 and Python 3.13.

## Before submitting changes

Run the complete verification suite:

```powershell
cd backend
.venv\Scripts\python.exe -m unittest discover -s tests -v

cd ..\frontend
npm ci
npm run lint
npm run typecheck
npm run build
```

Keep secrets out of the repository. Environment files must be created from
the checked-in `.env.example` files and must never be committed.

## Change scope

- Keep backend API contracts synchronized with `frontend/lib/types.ts`.
- Add or update tests when changing workflow, persistence, validation, or
  ownership behavior.
- Avoid committing generated directories, local databases, logs, editor
  metadata, or dependency installations.
