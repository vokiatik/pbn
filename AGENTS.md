# AGENTS.md

Repository-level instructions for Codex working on the Paint-by-Numbers (PBN) web app.

## Working mode

You are working as a senior full-stack engineer on a production-minded MVP. Prefer small, reviewable changes over large rewrites.

Before coding:

1. Inspect the existing repository structure and relevant files.
2. Read `docs/PROJECT-BRIEF.md` before larger tasks, pipeline changes, or work that touches multiple services.
3. Summarize what you found if the task touches multiple services.
4. Ask clarifying questions when product behavior, API contracts, database schema, file contracts, auth/security, deletion behavior, generated filenames, or worker/runner contracts are ambiguous.
5. For straightforward bug fixes, make the smallest safe fix and explain assumptions.

When implementing:

- Keep files small and focused.
- Prefer explicit types and clear interfaces.
- Avoid hidden magic and broad cross-service rewrites.
- Preserve existing public API contracts unless the task explicitly asks to change them.
- Update docs when behavior changes.
- Do not add production dependencies without a strong reason. Explain why they are needed.
- Do not introduce cloud AI dependencies for the PBN image-processing pipeline.

## Project context

This project is an offline Paint-by-Numbers generator. A user uploads an image, the system processes it through eight steps, shows previews, and produces printable outputs.

Use `docs/PROJECT-BRIEF.md` as the main product and architecture brief. The root `README.md` may contain older pipeline or generated-file details; when docs conflict, verify against the current code and update docs as part of the change when appropriate.

Core services:

- React + TypeScript frontend, built with Vite and MUI.
- Go HTTP backend using chi, PostgreSQL, Redis, and WebSockets.
- PostgreSQL for project/file/user metadata.
- Redis queue and Redis pub/sub events.
- Python worker that consumes Redis jobs and calls the runner.
- Python FastAPI runner for image-processing steps.
- SAM2, OpenCV, PIL/Pillow, pillow-heif, scikit-image, and sklearn clustering.
- Docker Compose for local development.

Important constraint: image processing should work offline. Do not add cloud AI or hosted image-processing dependencies to the PBN pipeline.

## Repository layout

Primary directories:

```text
frontend/   React TypeScript SPA
backend/    Go HTTP API and WebSocket service
worker/     Python Redis queue consumer
pbn/        Python FastAPI runner and image-processing code
docs/       Project and API documentation
storage/    Local development storage
```

Important files:

```text
docs/PROJECT-BRIEF.md
docs/API.md
docker-compose.yml
frontend/package.json
backend/go.mod
worker/requirements.txt
pbn/requirements.txt
pyproject.toml
```

## Expected service responsibilities

### Frontend

- React SPA.
- Uses a client token stored in `localStorage` for project ownership/authorization.
- Shows project status, current step, files, and one main preview image per step.
- Uses WebSocket updates from the backend/worker flow for progress and file changes.
- Avoid polling unless the existing code already has a deliberate fallback.
- Preview behavior should be intuitive:
  - Initial upload shows `upload_preview.jpg` when available.
  - Step 1 completion shows `step1_overlay`.
  - Step 2 completion shows `step2_smoothed`.
  - Step 3 completion shows `step3_palette_image` or `step3_palette_preview`.
  - Step 4 completion shows `step4_raw_region_color_image`.
  - Step 5 completion shows `step5_border_cleaned_preview`.
  - Step 6 completion shows `step6_final_region_color_image`.
  - Step 7 completion shows `step7_pbn_template` and exposes `step7_palette_sheet`.
  - Step 8 completion shows `pbn_final` and exposes `pbn_final_palette`.
- When a step completes, update active state from events and project state, not stale local assumptions.
- Keep API basics in a small client module. Put feature-specific API logic in hooks/services.
- Do not show every generated backend file as a primary UI item unless explicitly requested.

### Backend

- Go HTTP server.
- Owns projects, auth/client-token checks, DB records, upload validation, and internal worker endpoints.
- Saves uploads in the project directory using normalized names like `original.{ext}`.
- Calls runner preview generation for HEIC/HEIF uploads when needed.
- Provides internal endpoints protected by `INTERNAL_API_SECRET`.
- Records generated files with stable `file_type`, `filename`, path, mime type, and size.
- Publishes/relays project events to the frontend through WebSockets.
- Avoid path traversal risks. Never trust user-provided filenames for storage paths.

### Worker

- Python Redis queue consumer.
- Reads jobs from the configured Redis queue.
- Calls the runner for each step.
- Posts status/progress and generated file metadata back to the backend internal API.
- Publishes progress/completion events so the frontend updates without manual refresh.
- Handles step failure with clear error messages and status updates.
- Keeps backend, runner, and frontend file metadata contracts aligned.

### Runner

- Python FastAPI service.
- Exposes `POST /run-step/{step}` for steps 1..8.
- Exposes `POST /generate-upload-preview` for upload preview generation.
- Reads/writes files under `PROJECTS_DIR`.
- Uses `pillow_heif.register_heif_opener()` for HEIC/HEIF support.
- Step functions should be deterministic from input files + parameters.
- Returns structured responses with generated file metadata.

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
step1_objects/overlay.png
step1_objects/metadata.json
step1_objects/step1_result.json
step2_smooth/step2_smoothed.png
step2_smooth/step2_result.json
step3_palette/palette.json
step3_palette/label_map.npy
step3_palette/step3_palette_image.png
step3_palette/palette_preview.png
step3_palette/step3_result.json
step4_raw_regions/label_map_raw.npy
step4_raw_regions/raw_region_map.npy
step4_raw_regions/step4_raw_region_color_image.png
step4_raw_regions/step4_result.json
step5_border_cleanup/label_map_border_cleaned.npy
step5_border_cleanup/object_map.npy
step5_border_cleanup/step5_border_cleaned_preview.png
step5_border_cleanup/step5_result.json
step6_island_cleanup/region_map.npy
step6_island_cleanup/regions.json
step6_island_cleanup/step6_final_region_color_image.png
step6_island_cleanup/step6_result.json
step7_template/step7_pbn_template.png
step7_template/step7_palette_sheet.png
step7_template/step7_result.json
step8_pdf/pbn_final.png
step8_pdf/pbn_final_palette.png
step8_pdf/step8_pbn_template_A3_preview.pdf
step8_pdf/step8_palette_sheet_A3.pdf
step8_pdf/step8_result.json
```

Do not randomly rename these files. If a rename is necessary, update backend file metadata, frontend preview selection, worker registration, runner outputs, and docs together.

## Pipeline contract

The app has eight sequential processing steps:

1. SAM2 segmentation
2. Smooth segments / object-wise color simplification
3. Global palette clustering
4. Raw region creation from the Step 3 palette label map
5. Object-guided border smoothing / de-zippering
6. Micro-island cleanup and final region-map creation
7. Template generation with boundaries, numbers, and palette sheet
8. Printable PDF/export outputs

Current visual goals:

- Avoid tiny regions that cannot contain readable numbers.
- Avoid jagged or overly angular borders.
- Avoid crushed black shadows.
- Preserve important details like faces, fingers, and recognizable subject features.
- Prefer clean cartoon-like simplification when it improves printability.
- Keep the default palette around 20-30 colors unless the task says otherwise.
- Keep step outputs independently debuggable and traceable.

## Current environment conventions

Common local environment values used by this project:

```text
HTTP_PORT=8080
POSTGRES_DSN=postgres://pbn:pbn@127.0.0.1:5433/pbn?sslmode=disable
REDIS_ADDR=localhost:6379
REDIS_PORT=6379
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
SAM2_CHECKPOINT=/app/checkpoints/sam2.1_hiera_base_plus.pt
SAM2_MODEL_CFG=configs/sam2.1/sam2.1_hiera_b+.yaml
```

Do not hardcode local-only values into production code. Use environment variables.

## Testing and verification

First discover the repo's actual commands from `README.md`, `package.json`, `go.mod`, `pyproject.toml`, `requirements.txt`, `Makefile`, and Docker files.

Known useful checks:

- Frontend: `npm run build` from `frontend/`.
- Backend: `go test ./...` from `backend/`.
- Docker/service wiring: `docker compose config` and, when needed, `docker compose up --build`.
- Worker/runner: Python import checks, focused pytest if tests exist, or run the relevant FastAPI/step function path with safe sample data if available.

When relevant, run the smallest useful checks. If a check cannot be run, say exactly why and what should be run manually.

## Database and migrations

- Do not edit the database schema casually.
- If schema changes are required, add a migration and update repository code together.
- Preserve existing data where possible.
- Keep project/file status transitions explicit and auditable.
- Keep internal endpoints protected by `INTERNAL_API_SECRET`.

## Security and privacy

- Do not log tokens, internal secrets, full private paths, or sensitive user data.
- Validate uploaded files by type and size.
- Avoid path traversal risks.
- Never trust user-provided filenames for storage paths.
- Be careful with deletion behavior for project files.
- Do not weaken client-token ownership checks or internal API authentication.

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
