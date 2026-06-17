# AGENTS.md

Repository-level instructions for Codex working on the Paint-by-Numbers (PBN) web app.

## Working mode

You are working as a senior full-stack engineer on a production-minded MVP. Prefer small, reviewable changes over large rewrites.

Before coding:

1. Inspect the existing repository structure and relevant files.
2. Summarize what you found if the task touches multiple services.
3. Ask clarifying questions when product behavior, API contracts, database schema, or file contracts are ambiguous.
4. Do not guess around destructive behavior, auth/security, storage deletion, generated file names, or worker/runner contracts.
5. For straightforward bug fixes, make the smallest safe fix and explain assumptions.

When implementing:

- Keep files small and focused.
- Prefer explicit types and clear interfaces.
- Avoid hidden magic and broad cross-service rewrites.
- Preserve existing public API contracts unless the task explicitly asks to change them.
- Update docs when behavior changes.
- Do not add production dependencies without a strong reason. Explain why they are needed.

## Project context

Read `PROJECT-BRIEF.md` before starting larger tasks.

This project is an offline Paint-by-Numbers generator. A user uploads an image, the system processes it through six steps, shows previews, and produces a printable PDF.

Core services:

- React frontend
- Go HTTP backend
- PostgreSQL
- Redis queue and Redis pub/sub events
- Python worker
- Python FastAPI runner for image-processing steps
- SAM2, OpenCV, PIL/Pillow, scikit-image, sklearn clustering
- Docker Compose for local development

Important constraint: this app should work offline for image processing. Do not introduce cloud AI dependencies for the PBN pipeline.

## Expected service responsibilities

### Frontend

- React SPA.
- Uses a client token stored in `localStorage` for project ownership/authorization.
- Shows project status, current step, files, and one main preview image per step.
- Uses WebSocket updates from the backend/worker flow for progress and file changes.
- Avoid polling unless the existing code already has a deliberate fallback.
- Preview behavior should be intuitive:
  - Initial upload shows `upload_preview.jpg` when available.
  - Step 1 completion shows `step1_overlay.png`.
  - Step 2 completion shows `step2_overlay.png`.
  - Step 3 completion shows `palette_sheet.png` or another agreed main preview.
  - Step 4 completion shows `region_map.png` or agreed preview.
  - Step 5 completion shows `template_numbers.png` or agreed preview.
  - Step 6 completion exposes `pbn_final.pdf` for download.
- When a step completes, update active state from events, not from stale local assumptions.
- Keep API basics in a small client module. Put feature-specific API logic in hooks/services.

### Backend

- Go HTTP server.
- Owns projects, auth/client-token checks, DB records, upload validation, and internal worker endpoints.
- Saves uploads in the project directory using normalized names like `original.{ext}`.
- Calls runner preview generation for HEIC/HEIF uploads when needed.
- Provides internal endpoints protected by `INTERNAL_API_SECRET`.
- Records generated files with stable `file_type`, `filename`, path, mime type, and size.
- Publishes/relays project events to the frontend through WebSockets.

### Worker

- Python Redis queue consumer.
- Reads jobs from the configured Redis queue.
- Calls the runner for each step.
- Posts status/progress and generated file metadata back to the backend internal API.
- Publishes progress/completion events so the frontend updates without manual refresh.
- Should handle step failure with clear error messages and status updates.

### Runner

- Python FastAPI service.
- Exposes `POST /run-step/{step}` for steps 1..6.
- Exposes `POST /generate-upload-preview` for upload preview generation.
- Reads/writes files under `PROJECTS_DIR`.
- Uses `pillow_heif.register_heif_opener()` for HEIC/HEIF support.
- Step functions should be deterministic from input files + parameters.
- Return structured responses with generated file metadata.

## File and storage contract

Project directory:

```text
/storage/projects/{public_id}
```

Expected original image names:

```text
original.png
original.jpg
original.jpeg
original.webp
original.heic
original.heif
```

Known/generated files:

```text
upload_preview.jpg
segments.json
step1_overlay.png
local_map.png
step2_overlay.png
palette.json
palette_sheet.png
label_map.png
region_map.png
edges.png
regions.json
template.png
template_numbers.png
pbn_final.pdf
```

Do not randomly rename these files. If a rename is necessary, update backend file metadata, frontend preview selection, worker registration, and docs together.

## Pipeline contract

The app has six sequential processing steps:

1. SAM2 segmentation
2. Smooth segments / object-wise color simplification
3. Global palette clustering
4. Region cleanup and merge/conflict solving
5. Template generation with boundaries and numbers
6. Printable PDF export

Current visual goals:

- Avoid tiny regions that cannot contain readable numbers.
- Avoid jagged/overly angular borders.
- Avoid crushed black shadows.
- Preserve important details like faces, fingers, and recognizable subject features.
- Prefer clean cartoon-like simplification when it improves printability.
- Keep default palette around 20-30 colors unless task says otherwise.

## Current environment conventions

Common local environment values used by this project:

```text
HTTP_PORT=8080
POSTGRES_DSN=postgres://pbn:pbn@127.0.0.1:5433/pbn?sslmode=disable
REDIS_ADDR=localhost:6379
REDIS_DB=0
REDIS_QUEUE_NAME=pbn:jobs
INTERNAL_API_SECRET=local-dev-secret
PROJECTS_DIR=/storage/projects
SAM2_CHECKPOINT=/app/checkpoints/sam2.1_hiera_base_plus.pt
SAM2_MODEL_CFG=configs/sam2.1/sam2.1_hiera_b+.yaml
```

Do not hardcode local-only values into production code. Use environment variables.

## Testing and verification

First discover the repo's actual commands from `README`, `package.json`, `go.mod`, `pyproject.toml`, `requirements.txt`, `Makefile`, and Docker files.

When relevant, run the smallest useful checks:

- Frontend: typecheck/build/lint if scripts exist.
- Backend: `go test ./...` if applicable.
- Worker/runner: Python import checks, focused pytest if tests exist, or run the relevant FastAPI/step function path with safe sample data if available.
- Docker: validate Compose/service changes when the task touches service wiring.

If a check cannot be run, say exactly why and what should be run manually.

## Database and migrations

- Do not edit the database schema casually.
- If schema changes are required, add a migration and update repository code together.
- Preserve existing data where possible.
- Keep project/file status transitions explicit and auditable.

## Security and privacy

- Do not log tokens, internal secrets, full user private paths, or sensitive data.
- Keep internal endpoints protected by `INTERNAL_API_SECRET`.
- Validate uploaded files by type and size.
- Avoid path traversal risks. Never trust user-provided filenames for storage paths.
- Be careful with deletion behavior for project files.

## Code review checklist

Before finishing a task, review your own diff:

- Does the change solve the requested problem with minimal scope?
- Are frontend/backend/worker/runner contracts still aligned?
- Are file names and `file_type` values consistent?
- Are WebSocket/progress updates handled without stale UI state?
- Are errors visible and useful?
- Did you avoid introducing cloud services or unnecessary dependencies?
- Did you run relevant checks or clearly state why not?

## Done response format

When you finish, report:

1. What changed.
2. Files changed.
3. Commands/checks run.
4. Any assumptions or follow-up risks.
