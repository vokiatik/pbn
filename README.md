# Paint-by-Number Web Platform

This app converts an uploaded photo into one printable paint-by-number result through an AI-assisted workflow with an image review step.

```text
React frontend
-> Go backend API / WebSocket
-> Redis queue
-> Python worker
-> FastAPI runner
-> generated files in shared storage
```

The only supported workflow is the AI pipeline. Legacy step-by-step segmentation, V2 printable, and V3 graph-first workflows have been removed. The app generates one saved Hard preview, followed by explicit creation of its printable files.

## Product Flow

1. Upload a PNG, JPEG, WEBP, HEIC, or HEIF image.
2. Backend creates an `ai` project, stores `original/original.{ext}`, and registers the original file.
3. For HEIC/HEIF uploads, backend queues browser-safe preview generation.
4. User chooses AI settings and starts AI image generation.
5. Worker consumes `generate_ai_image`, calls the runner, registers `ai_simplified`, and stops for review.
6. User can regenerate the AI image or generate the saved Hard PBN preview.
7. User clicks Create Hard printable files to export that saved result.
7. Worker consumes `continue_ai_pipeline`, derives regions/templates from the reviewed AI image, registers public artifacts, and publishes WebSocket events.
8. Frontend shows status, output previews, and downloadable files.

## AI Pipeline

```text
original photo
-> prepared AI input
-> one AI-simplified flat-colour illustration
-> connected region extraction
-> AI-colour palette tracing
-> minimal paintability metadata/cleanup
-> validation report
-> numbered template
-> PDF export
```

The system generates one AI image per run. That image is the visual source of truth: downstream regions protect structural boundaries, derive a bounded paint palette, and reconstruct the painted reference exactly from the final region map and assigned colours.

## Configuration

The app can start without AI credentials. Running generation requires one fully configured provider. Supported providers are `openai` and `gemini`; `gpt` is accepted as an API alias for `openai`.

```text
AI_SIMPLIFICATION_PROVIDER=openai
OPENAI_API_KEY=
OPENAI_IMAGE_MODEL=
OPENAI_IMAGE_QUALITY=low
OPENAI_IMAGE_MODERATION=low
GOOGLE_API_KEY=
GOOGLE_IMAGE_MODEL=
AI_REQUEST_TIMEOUT_SECONDS=180
AI_MAX_RETRIES=2
PBN_OPTION_MAX_ATTEMPTS=5
```

`OPENAI_IMAGE_MODERATION` accepts `low` (the default, less restrictive filtering) or `auto` (standard filtering). Moderation blocks still return OpenAI's coarse stage and category details so the UI can suggest whether to revise the prompt/input image or regenerate.

`PBN_OPTION_MAX_ATTEMPTS` limits deterministic local attempts for Hard, including the initial attempt. Values are clamped to `1-5`; generation stops at the first valid result. Retries never make another AI provider call or change the requested palette. The reviewed image is analyzed once into cached connected source regions. Hard starts with a density ceiling of 650 regions. Printed number labels choose the largest fitting 4, 3, 2, or 1 mm height. Set `PBN_DEBUG_IMAGES=1` to retain internal stage images.

If the requested/default provider is not configured but exactly one other provider is configured, the runner uses the configured provider. Otherwise generation fails with a configuration error.

## Run Locally

For `pbn.zichka.com` on Coolify with Cloudflare Tunnel, use the standalone
[`docker-compose.production.yml`](docker-compose.production.yml) and follow
[`docs/PRODUCTION.md`](docs/PRODUCTION.md). Production runtime variables are
listed in [`deploy/.env.example`](deploy/.env.example).

Copy `.env.example` to `.env`, add provider credentials if you want to run generation, then start the stack:

```bash
docker compose up --build
```

Endpoints:

- Frontend: http://localhost:5173
- Backend API: http://localhost:8080
- Runner: http://localhost:8081
- WebSocket: ws://localhost:8080/ws

## Core API

- `POST /api/projects`
- `POST /api/projects/{public_id}/run`
- `POST /api/projects/{public_id}/proceed`
- `POST /api/projects/{public_id}/select-pbn`
- `GET /api/projects`
- `GET /api/projects/{public_id}`
- `DELETE /api/projects/{public_id}`
- `GET /api/projects/{public_id}/files/{file_id}/preview`
- `GET /api/projects/{public_id}/files/{file_id}/download`
- `GET /ws`

See [docs/API.md](docs/API.md) and [docs/FILE-CONTRACT.md](docs/FILE-CONTRACT.md) for the detailed service contract.

## Useful Checks

```bash
cd frontend && npm run build
cd backend && go test ./...
docker compose config
```

Python runner and worker checks are currently focused tests/import checks under `pbn/tests/` and `worker/tests/`.
