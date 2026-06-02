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

No algorithm rewrite was introduced.

Worker calls the existing entry point:
- `run(config: PipelineConfig)` in `main.py`

Known processing stages detected from existing logs:
1. Loading + preprocessing image
2. Building edge map
3. Superpixel segmentation
4. Palette clustering + initial assignment
5. Importance map + safe region merging
6. Raster cleanup + previews
7. Line art + numbers + metadata
8. Saving outputs

Generated files detected and persisted:
- `preview_color.png`
- `pbn_lines.png`
- `palette.png`
- `palette.json`
- `regions.json`
- optional `paint_by_numbers.pdf`

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
