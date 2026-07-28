# API

The public API supports one pipeline version: `ai`.

## Public Endpoints

### `POST /api/projects`

Create an AI pipeline project from an uploaded image.

Headers:

- `X-Client-Token`: optional client ownership token. The frontend stores this in `localStorage`. If omitted, backend uses `anonymous`.

Multipart form fields:

- `file`: required PNG, JPEG, WEBP, HEIC, or HEIF upload.
- `pipeline_version`: optional; must be `ai` when supplied.

Response:

```json
{
  "project_id": "abc123",
  "status": "uploaded",
  "pipeline_version": "ai"
}
```

The backend stores the original at `original/original.{ext}`. For HEIC/HEIF uploads, it queues a `generate_upload_preview` worker job.

### `PUT /api/projects/{public_id}/image`

Replace the source image for an existing project. Requires `X-Client-Token` matching the browser that created the project.

Multipart form fields:

- `file`: required PNG, JPEG, WEBP, HEIC, or HEIF upload.

This resets the project status to `uploaded`, clears stored AI settings/crop, errors, and completion time, and replaces registered public files with the new `original` record. Previous generated outputs are no longer registered; the user must run generation again for the new picture. Replacements are rejected while preview, AI image, or PBN processing is active.

Response:

```json
{
  "project_id": "abc123",
  "status": "uploaded",
  "pipeline_version": "ai",
  "files": []
}
```

### `POST /api/projects/{public_id}/run`

Queue AI image generation. Requires `X-Client-Token` matching the browser that created the project. This endpoint stops after registering `ai_simplified`; the user must call `proceed` after reviewing the AI image.

Request:

```json
{
  "settings": {
    "provider": "openai",
    "category": "portrait",
    "target_palette_size": 24,
    "preserve_elements": ["eyes", "face"],
    "simplify_elements": ["background clutter"],
    "prompt_guidance": "Make the background simpler and keep the face recognizable.",
    "page_size": "a3",
    "orientation": "landscape",
    "fit_mode": "cover",
    "crop": {"x": 0.08, "y": 0.0, "width": 0.84, "height": 1.0}
  }
}
```

Validation/defaults:

- `provider`: `openai`, `gpt`, or `gemini`; `gpt` is normalized to `openai`.
- `category`: defaults to `illustration`.
- `target_palette_size`: 8-40, default 24.
- `prompt_guidance`: optional, max 1000 characters.
- `page_size`: `a3` or `a4`, default `a3`.
- `orientation`: `portrait` or `landscape`, backend fallback `portrait`.
- `fit_mode`: `cover` or `contain`, default `cover`.
- `crop`: normalized rectangle inside the EXIF-corrected source for cover; contain stores `null`.

The normalized settings are saved to `projects.ai_settings` before the job is queued. Provider canvas and final 300-DPI output dimensions are derived internally.

Can run when the project status is `uploaded`, `ai_failed`, `ai_image_ready`, `pbn_failed`, or `ai_completed`. Calls from `ai_image_ready`, `pbn_failed`, or `ai_completed` are treated as regeneration: stale downstream PBN file records are removed, stale downstream pipeline folders are cleared, and the latest `ai_simplified` is replaced when the worker completes.

Response:

```json
{
  "project_id": "abc123",
  "status": "ai_image_queued"
}
```

### `POST /api/projects/{public_id}/proceed`

Queue PBN generation from the reviewed `ai_simplified` image. Requires `X-Client-Token` matching the browser that created the project.

The endpoint accepts no settings body. It uses the exact settings saved by `/run` and queues generation of saved Easy, Medium, and Hard PBN options. It does not select or export a difficulty. Existing reviewed projects without saved settings must regenerate their AI image first. No AI provider call is made during proceed.

Can run only when the project status is `ai_image_ready` or `pbn_failed`.

When a Preserve Detail mask exists, the runner uses source-pixel microregions only in the filled selected area and keeps the normal SLIC path elsewhere. Meaningful selected boundaries receive difficulty-scaled minimum protection in addition to the normal evidence multiplier. This is local deterministic processing and does not make another provider call.

Response:

```json
{
  "project_id": "abc123",
  "status": "pbn_options_queued"
}
```

### `POST /api/projects/{public_id}/select-pbn`

Explicitly select one saved valid option and queue its printable PNG/PDF exports. Requires the matching `X-Client-Token`.

```json
{"difficulty":"easy"}
```

`difficulty` must be `easy`, `medium`, or `hard` and must exist in `project.pbn_options`. The saved region map is reused; no AI or segmentation work is repeated. The endpoint is available from `pbn_options_ready`, `ai_completed`, or `pbn_selection_failed`.

### Preserve Detail mask

These owner-protected endpoints manage the binary mask attached to the current reviewed `ai_simplified` image:

- `GET /api/projects/{public_id}/detail-protection` returns mask metadata or `{"exists":false}`.
- `GET /api/projects/{public_id}/detail-protection/mask` returns the normalized PNG.
- `PUT /api/projects/{public_id}/detail-protection` accepts an `image/png` body up to 4 MiB.
- `DELETE /api/projects/{public_id}/detail-protection` clears the mask.

The PNG must exactly match the reviewed image dimensions. The backend normalizes it to 8-bit binary pixels and stores it under a fixed server path; white selects advanced processing and black keeps normal processing. Metadata includes dimensions, coverage percentage, SHA-256, update time, and `large_selection`, which becomes true above 40% coverage.

Mask changes are allowed only while the project is idle and a reviewed AI image exists. Saving or deleting a mask invalidates existing PBN options and exports, clears the selected difficulty, and returns the project to `ai_image_ready`. Replacing the source or regenerating the reviewed AI image clears the mask.

### `GET /api/projects`

List non-deleted projects.

Query params:

- `page`: default 1.
- `page_size`: default 10, max 100.

Response:

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 10,
  "total_pages": 0
}
```

### `GET /api/projects/{public_id}`

Get a project and registered files.

Response:

```json
{
  "project": {
    "public_id": "abc123",
    "pipeline_version": "ai",
    "status": "ai_image_ready",
    "ai_settings": {
      "page_size": "a3",
      "orientation": "landscape",
      "fit_mode": "cover",
      "crop": {"x": 0.08, "y": 0.0, "width": 0.84, "height": 1.0},
      "target_palette_size": 24
    },
    "ai_quality": {
      "status": "warn",
      "codes": ["region_complexity"],
      "message": "The AI image may lose fine detail during conversion. You can continue or regenerate with larger, flatter colour areas.",
      "metrics": {
        "mean_delta_e_00": 2.5,
        "p90_delta_e_00": 6.2,
        "estimated_region_count": 1279,
        "micro_detail_area_percent": 0
      }
    },
    "pbn_options": [
      {"difficulty":"easy","status":"valid","region_count":340,"palette_size":24,"prefilled_detail_count":8,"prefilled_area_percent":0.4,"adaptive_label_count":17,"minimum_label_font_pt":3.5,"region_budget_overflow_percent":0,"protected_boundary_retention":0.94,"protected_mean_delta_e_00":5.7,"protected_p90_delta_e_00":12.1,"advanced_area_percent":6.4,"selected_boundary_retention":0.91,"selected_prefilled_detail_count":3,"selected_forced_merge_count":0,"palette_protected_forced_merge_count":0,"protection_overflow_percent":0}
    ],
    "selected_pbn_difficulty": "easy",
    "error_message": null,
    "files_count": 13
  },
  "files": []
}
```

`error_message` is included when a workflow failure has a stored detail.

`ai_quality` is an advisory assessment of the reviewed AI image. Its status is `pass` or `warn`; warning codes are `palette_mismatch`, `micro_detail_density`, and `region_complexity`. Older projects may return an empty object. New PBN option fidelity and adaptive-numbering fields are optional for backward compatibility. `palette_protected_forced_merge_count` reports last-resort natural protected-boundary merges required to keep the exact requested palette; detailed affected-pair records are retained in the option fidelity metrics.

### `DELETE /api/projects/{public_id}`

Soft-delete a project. The database status becomes `deleted`; files are not removed from disk by this endpoint.

Response:

```json
{
  "status": "deleted"
}
```

### File Serving

- `GET /api/projects/{public_id}/files/{file_id}/preview`: inline file response.
- `GET /api/projects/{public_id}/files/{file_id}/download`: attachment response.

The backend serves only registered project files whose absolute path resolves under `/storage/projects/{public_id}`.

### Users

- `POST /api/users/resolve`
- `POST /api/users`
- `POST /api/projects/{public_id}/attach-user`

These endpoints support the projects list/user attachment UI and are not part of the image-processing pipeline.

### WebSocket

- `GET /ws`

The frontend connects to `/ws?project_id={public_id}` and filters events by `project_id`.

## Internal Worker Endpoints

Internal endpoints require `X-Internal-Secret`.

### `POST /api/internal/projects/{id}/status`

Request:

```json
{
  "status": "ai_image_processing",
  "progress": 25,
  "stage": "generating_ai_image",
  "message": "AI image generation started",
  "error_message": ""
}
```

`stage` is optional and is forwarded to WebSocket subscribers for live progress display. `ai_completed`, `ai_failed`, `pbn_failed`, and `failed` mark the project completed. Failed statuses store an error detail; queued/processing/ready/completed statuses clear prior errors.

### `POST /api/internal/projects/{id}/files`

Request:

```json
{
  "files": [
    {
      "file_type": "ai_final",
      "filename": "pbn_final.png",
      "file_path": "/storage/projects/abc123/pipeline_ai/export/pbn_final.png",
      "mime_type": "image/png",
      "size_bytes": 12345
    }
  ]
}
```

The backend preserves the original file record, deduplicates by `file_type`, replaces the project's file list, then returns canonical DB records with IDs.

### `POST /api/internal/projects/{id}/ai-quality`

Persists the runner's advisory assessment before the worker publishes `ai_image_ready`.

```json
{
  "quality": {
    "status": "warn",
    "codes": ["micro_detail_density"],
    "message": "The AI image may lose fine detail during conversion.",
    "metrics": {
      "mean_delta_e_00": 0,
      "p90_delta_e_00": 0,
      "estimated_region_count": 0,
      "micro_detail_area_percent": 4.2
    }
  }
}
```

Regenerating or replacing the source clears stale `ai_quality` data.

## Worker and Runner Contracts

Worker job types:

- `generate_upload_preview`
- `generate_ai_image`
- `continue_ai_pipeline`
- `generate_pbn_options`
- `finalize_pbn_option`
- `run_ai_pipeline` legacy one-shot job

Runner endpoints:

- `GET /health`
- `POST /generate-upload-preview`
- `POST /generate-ai-image`
- `POST /continue-ai-pipeline`
- `POST /finalize-pbn-option`
- `POST /run-ai-pipeline`

Provider errors:

- `424`: provider configuration error.
- `502`: provider request/response error.
- `500`: unexpected runner failure.

## WebSocket Events

Events are JSON objects relayed from Redis pub/sub. Current event types include:

- `status_changed`
- `upload_preview_processing`
- `upload_preview_completed`
- `upload_preview_failed`
- `ai_status_changed`
- `ai_image_ready`
- `ai_completed`
- `ai_failed`
- `pbn_failed`

Events may include `status`, `stage`, `value`, `progress`, `message`, `files`, `ai_quality`, and `runner_result`. The `ai_image_ready` event includes the assessment that was persisted for the project.
