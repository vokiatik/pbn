# Paint-by-Number Web Platform

This repository now includes a full local web platform around the existing Python paint-by-number algorithm.

Architecture:

React frontend
-> Go backend API
-> Redis queue
-> Python worker (reuses existing pipeline)
-> Generated files in shared storage

## Services

- frontend: React + TypeScript SPA (React Router + MUI)
- backend: Go REST API + WebSocket + Redis pub/sub fanout
- postgres: permanent storage
- redis: queue, live status, pub/sub
- worker: Python queue consumer that runs the existing pipeline in `main.py`


## Existing Processing Pipeline Reused

Worker now calls the fixed-palette pipeline entry point:
- `PBNPipeline(...).run(...)` in `pbn/pipeline.py`

Known processing stages:
1. Loading image
2. Resizing image
3. Edge-preserving smoothing
4. Converting RGB to CIELAB
5. SLIC superpixel segmentation
6. Palette matching in LAB
7. Connected component cleanup
8. Contour extraction + number placement
9. Rendering outputs
10. Exporting files

Generated files detected and persisted:
- `colored_preview.png`
- `pbn_outline.png`
- `pbn_numbered.png`
- `pbn_vector.svg`
- `palette.json`
- `regions.json`
- `final_print.pdf`

## Storage Layout

Per project:

`/storage/projects/{public_id}/original/{filename}`

`/storage/projects/{public_id}/generated/*`

In Docker Compose this maps to volume `storage_data`.

## Status Lifecycle

- uploaded
- queued
- processing
- completed
- failed
- deleted

Final status is stored in PostgreSQL. Live updates and notifications use Redis + WebSocket.

## Queue and Limits

- Redis queue key: `pbn:jobs`
- max queue size: 20 (`QUEUE_MAX_SIZE`)
- worker concurrency: 3 by default (`WORKER_CONCURRENCY`)
- max active projects per client token: 2 (`MAX_ACTIVE_PROJECTS_PER_CLIENT`)

## Run Locally (Docker Compose)

Requirements:
- Docker
- Docker Compose

Start:

```bash
docker compose up --build
```

Endpoints:
- frontend: http://localhost:5173
- backend API: http://localhost:8080
- websocket: ws://localhost:8080/ws

Stop:

```bash
docker compose down
```

## API

Full endpoint documentation is in:
- `docs/API.md`

Core endpoints:
- `POST /api/projects`
- `GET /api/projects`
- `GET /api/projects/{public_id}`
- `DELETE /api/projects/{public_id}`
- `GET /api/projects/{public_id}/files/{file_id}/preview`
- `GET /api/projects/{public_id}/files/{file_id}/download`
- `POST /api/users/resolve`
- `POST /api/users`
- `POST /api/projects/{public_id}/attach-user`
- `GET /ws`

## Optional User Info Before Download

Frontend supports this flow:
1. User clicks Download.
2. If project has no user, ask for email.
3. If email exists, attach existing user.
4. If not, ask username + phone, create user, attach.
5. Continue download.

Skip is allowed.

## Local Development Without Docker (Optional)

You can still run the original CLI pipeline directly:

```bash
python main.py input/photo.jpg --out output --colors 32 --size 2200
```

The web platform integration uses the same Python code path through the worker.

## Automatic Fixed-Palette PBN Pipeline

This project now also includes a local automatic pipeline using a fixed 20-color palette and YAML configuration.

Run:

```bash
python generate_pbn.py input.jpg --config config.yaml --out output_folder
```

Generated files:

- `colored_preview.png`
- `pbn_outline.png`
- `pbn_numbered.png`
- `pbn_vector.svg`
- `palette.json`
- `final_print.pdf`

The command runs fully local and does not use cloud APIs.
