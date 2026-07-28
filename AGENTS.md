# AGENTS.md

Repository-level instructions for Codex working on the Paint-by-Numbers (PBN) web app.

## Working Mode

You are working as a senior full-stack engineer on a production-minded MVP. Prefer small, reviewable changes over large rewrites.

Before coding:

1. Inspect the existing repository structure and relevant files.
2. Read `docs/PROJECT-BRIEF.md` before larger tasks, pipeline changes, or work that touches multiple services.
3. Summarize what you found if the task touches multiple services.
4. Ask clarifying questions when product behavior, API contracts, database schema, file contracts, auth/security, deletion behavior, generated filenames, provider behavior, or worker/runner contracts are ambiguous.
5. For straightforward bug fixes, make the smallest safe fix and explain assumptions.

When implementing:

- Keep files small and focused.
- Prefer explicit types and clear interfaces.
- Avoid hidden magic and broad cross-service rewrites.
- Preserve existing public API contracts unless the task explicitly asks to change them.
- Update docs when behavior changes.
- Do not add production dependencies without a strong reason. Explain why they are needed.
- Do not add another hosted AI/image provider without updating provider configuration, runner errors, docs, and local setup guidance.

## Project Context

This project generates paint-by-number outputs from uploaded images. The current product has one supported workflow: a single AI-assisted pipeline that creates one simplified flat-colour image, derives regions and palette data from it, validates paintability, and exports template/palette files.

Use `docs/PROJECT-BRIEF.md` as the main product and architecture brief. `docs/API.md` and `docs/FILE-CONTRACT.md` define the public service/file contracts.

Core services:

- React + TypeScript frontend, built with Vite and MUI.
- Go HTTP backend using chi, PostgreSQL, Redis, and WebSockets.
- PostgreSQL for project/file/user metadata.
- Redis queue and Redis pub/sub events.
- Python worker that consumes Redis jobs and calls the runner.
- Python FastAPI runner for upload preview generation and AI pipeline execution.
- AI-assisted image simplification via configured OpenAI or Gemini provider.
- OpenCV, PIL/Pillow, pillow-heif, scikit-image, and sklearn for local downstream image processing.
- Docker Compose for local development.

## Repository Layout

```text
frontend/   React TypeScript SPA
backend/    Go HTTP API and WebSocket service
worker/     Python Redis queue consumer
pbn/        Python FastAPI runner and AI pipeline code
docs/       Project and API documentation
storage/    Local development storage
```

Important files:

```text
docs/PROJECT-BRIEF.md
docs/API.md
docs/FILE-CONTRACT.md
docker-compose.yml
frontend/package.json
backend/go.mod
worker/requirements.txt
pbn/requirements.txt
pyproject.toml
```

## Expected Service Responsibilities

### Frontend

- React SPA.
- Uses a client token stored in `localStorage` for upload/run ownership.
- Shows project status, stored errors, output previews, and downloadable files.
- Uses WebSocket updates from the backend/worker flow for progress and file changes.
- Avoids polling unless the existing code already has a deliberate fallback.
- Keeps API basics in `frontend/src/api/client.ts`.
- Does not show every generated runner trace file as a primary UI item unless explicitly requested.

Current preview priority:

```text
upload_preview
original
ai_simplified
ai_palette_preview
ai_numbered_template
ai_final
ai_validation_report
```

### Backend

- Owns projects, client-token checks, DB records, upload validation, and internal worker endpoints.
- Saves uploads using normalized names under `original/original.{ext}`.
- Queues upload preview generation for HEIC/HEIF uploads.
- Provides internal endpoints protected by `INTERNAL_API_SECRET`.
- Records generated files with stable `file_type`, `filename`, path, mime type, and size.
- Publishes/relays project events to the frontend through WebSockets.
- Avoids path traversal risks. Never trust user-provided filenames for storage paths.
- Serves only registered files that resolve under `/storage/projects/{public_id}`.

### Worker

- Reads jobs from the configured Redis queue.
- Handles `generate_upload_preview` and `run_ai_pipeline`.
- Calls the runner, registers public generated files, posts status/error updates, and publishes events.
- Handles failures with clear error messages and status updates.
- Keeps backend, runner, and frontend file metadata contracts aligned.

### Runner

- Exposes `GET /health`.
- Exposes `POST /generate-upload-preview`.
- Exposes `POST /run-ai-pipeline`.
- Reads/writes files under `PROJECTS_DIR`.
- Uses `pillow_heif.register_heif_opener()` for HEIC/HEIF support.
- Selects a configured OpenAI or Gemini provider for AI simplification.
- Keeps downstream region extraction, palette normalization, cleanup, validation, and export deterministic from inputs and settings.
- Returns structured responses with output paths and metrics.

## Pipeline Contract

The app has one sequential AI pipeline:

1. Prepare source image and write `pipeline_ai/prepared/ai_input.png`.
2. Generate one AI-simplified illustration at `pipeline_ai/ai/simplified.png`.
3. Extract connected regions.
4. Normalize region colours to the target paint palette.
5. Clean region maps for paintability.
6. Validate template inputs.
7. Render numbered template and palette sheet.
8. Export printable PNG/PDF outputs.

Do not reintroduce legacy step-by-step, V2, V3, candidate, or review-gate flows unless the task explicitly asks for a coordinated product/API change.

## File and Storage Contract

Use `docs/FILE-CONTRACT.md` as the source of truth for generated files and public `file_type` values.

Public file types:

```text
original
upload_preview
ai_simplified
ai_region_map
ai_palette_preview
ai_validation_report
ai_numbered_template
ai_palette_sheet
ai_painted_reference
ai_final
ai_final_palette
ai_template_pdf
ai_palette_pdf
```

Do not randomly rename these files. If a rename is necessary, update backend file metadata, frontend preview/file selection, worker registration, runner outputs, and docs together.

## Current Environment Conventions

```text
HTTP_PORT=8080
POSTGRES_DSN=postgres://pbn:pbn@postgres:5432/pbn?sslmode=disable
REDIS_ADDR=redis:6379
REDIS_DB=0
REDIS_QUEUE_NAME=pbn:jobs
REDIS_EVENTS_CHANNEL=pbn:events
QUEUE_MAX_SIZE=20
WORKER_CONCURRENCY=3
MAX_ACTIVE_PROJECTS_PER_CLIENT=2
INTERNAL_API_SECRET=local-dev-secret
STORAGE_ROOT=/storage
PROJECTS_DIR=/storage/projects
BACKEND_INTERNAL_BASE=http://backend:8080/api/internal
PYTHON_RUNNER_BASE_URL=http://pbn:8081
AI_SIMPLIFICATION_PROVIDER=openai
OPENAI_API_KEY=
OPENAI_IMAGE_MODEL=
GOOGLE_API_KEY=
GOOGLE_IMAGE_MODEL=
AI_REQUEST_TIMEOUT_SECONDS=180
AI_MAX_RETRIES=2
```

Do not hardcode local-only values into production code. Use environment variables.

## Testing and Verification

First discover the repo's actual commands from `README.md`, `package.json`, `go.mod`, `pyproject.toml`, `requirements.txt`, and Docker files.

Known useful checks:

- Frontend: `npm run build` from `frontend/`.
- Backend: `go test ./...` from `backend/`.
- Docker/service wiring: `docker compose config`.
- Worker/runner: focused pytest/import checks when dependencies are available.

When relevant, run the smallest useful checks. If a check cannot be run, say exactly why and what should be run manually.

## Database and Migrations

- Do not edit the database schema casually.
- If schema changes are required, add a migration and update repository code together.
- Preserve existing data where possible.
- Keep project/file status transitions explicit and auditable.
- Keep internal endpoints protected by `INTERNAL_API_SECRET`.

## Security and Privacy

- Do not log tokens, internal secrets, provider API keys, full private paths, or sensitive user data.
- Validate uploaded files by type and size.
- Avoid path traversal risks.
- Never trust user-provided filenames for storage paths.
- Be careful with deletion behavior for project files.
- Do not weaken client-token ownership checks or internal API authentication.

## Repo Hygiene

- Do not commit local runtime data under `storage/`.
- Do not commit `.cache/`, `.venv/`, `__pycache__/`, `frontend/node_modules/`, `frontend/dist/`, or `frontend/tsconfig.tsbuildinfo`.
- Keep sample configuration in `.env.example`; keep real secrets in local `.env`.

## Code Review Checklist

Before finishing a task, review your own diff:

- Does the change solve the requested problem with minimal scope?
- Are frontend/backend/worker/runner contracts still aligned?
- Are file names and `file_type` values consistent?
- Are WebSocket/progress updates handled without stale UI state?
- Are errors visible and useful?
- Did you avoid unrelated dependencies or provider changes?
- Did you run relevant checks or clearly state why not?

## Done Response Format

When you finish, report:

1. What changed.
2. Files changed.
3. Commands/checks run.
4. Any assumptions or follow-up risks.
