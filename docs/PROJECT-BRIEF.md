# Project Brief

The app converts one uploaded image into one printable paint-by-number template.

## Current Product Flow

1. User uploads a PNG, JPEG, WEBP, HEIC, or HEIF image.
2. Backend creates an `ai` pipeline project, stores the preserved original, and registers it in `project_files`.
3. HEIC/HEIF uploads queue an upload-preview job that creates `generated/upload_preview.jpg`.
4. User can replace the uploaded picture before starting a new run; replacing the picture resets generated outputs and returns the project to `uploaded`.
5. User chooses AI generation settings plus an A3/A4 print composition. The default is A3, source-matched orientation, and an adjustable cover crop; contain is also available.
6. Worker runs `generate_ai_image`.
7. Runner generates one AI-simplified flat-colour illustration, records an advisory local quality assessment, and the worker persists that assessment before registering `ai_simplified` and stopping for review.
8. User can regenerate the AI image or proceed to PBN generation.
9. Worker runs `generate_pbn_options`; runner generates only Hard against the immutable reviewed AI image, stopping at the first valid result.
10. The frontend shows the saved Hard preview.
11. The user clicks Create Hard printable files; only then does `finalize_pbn_option` create or replace the printable exports.
12. The saved Hard result can be exported again without another AI call or segmentation run.

The primary download list is intentionally limited to six user-facing artifacts: the original image, AI-generated image, coloured preview, paint-by-number preview, final PBN template PDF, and colour palette. Secondary registered outputs remain available to the pipeline and API but are not shown in the primary file table.

## Only Supported Pipeline

```text
Original photo
-> EXIF correction and one approved A-series crop/fit
-> padded provider input
-> one detailed AI-simplified flat-colour illustration
-> immutable reviewed safe-area image
-> cached connected source-edge analysis
-> physical-floor region seed and dynamic region-adjacency merging
-> deterministic detail-weighted CIELAB palette
-> physical paintability cleanup and topology-preserving source-edge alignment
-> adaptive gray numbering with protected-detail palette fallback
-> saved Hard preview
-> explicit export action
-> numbered template for the selected option
-> A3/A4 PNG/PDF export at 300 DPI
```

The old direct photo segmentation workflow, V2 printable workflow, V3 graph-first workflow, and step-by-step controls have been removed. Only Hard output is generated and exportable. Existing Easy/Medium records remain readable for compatibility; their option folders are removed after successful regeneration and they are not offered for selection.

## Services

- `frontend/`: React TypeScript SPA built with Vite and MUI.
- `backend/`: Go API for projects, upload validation, file serving, Redis queue insertion, internal worker endpoints, and WebSocket fanout.
- `worker/`: Python Redis job consumer that calls the runner, registers generated files, posts statuses, retries jobs, and publishes events.
- `pbn/runner_app/`: FastAPI runner exposing health, upload preview generation, AI image generation, and PBN continuation.
- `pbn/ai_pipeline/`: AI-assisted image simplification, region tracing, AI-colour palette derivation, minimal cleanup, validation, and export.
- `storage/`: local development storage for uploaded and generated project files.

## Storage Contract

Project files live under:

```text
/storage/projects/{public_id}/
```

Per project:

```text
original/
  original.{png|jpg|jpeg|webp|heic|heif}
generated/
  upload_preview.jpg
pipeline_ai/
  prepared/
    original.{ext}
    cropped_source.png
    ai_input.png
    crop_manifest.json
  ai/
    provider_output.png
    simplified.png
    generation.json
    quality_report.json
    quality_preview.png
  analysis/
    source_atoms.npy
    manifest.json
  regions/
    slico_map.png
    graph_merged_map.png
    cleaned_map.png
    regularized_map.png
    boundary_strength.png
    protection_map.png
    protection_mask.npy
    initial_region_map.png
    region_id_map.npy
    regions.json
    adjacency.json
  palette/
    palette.json
    region_colours.json
    preview.png
  cleanup/
    cleaned_region_map.npy
    cleaned_region_map.png
    cleanup_log.json
    regions.json
  validation/
    report.json
  options/
    options.json
    attempt_reports/
      hard-{attempt}.json
    .attempts/                 # retained only when every option fails
      hard/{attempt}/failure/
        diagnostics.json
        region_id_map.npy
        region_map.png
    hard/
      metadata.json
      label_plan.json
      painted_reference.png
      numbered_template.png
      regions/...
      palette/...
      validation/report.json
  template/
    numbered_template.png
    palette_sheet.png
    palette.json
  export/
    pbn_final.png
    pbn_final_palette.png
    painted_reference.png
    pbn_template.pdf
    palette_sheet.pdf
    export_result.json
  pipeline_result.json
```

`pipeline_result.json`, quality reports, label plans, `.npy` files, stage images, cleanup logs, and adjacency/region internals are trace artifacts. Failed searches retain `.attempts/` with the last intermediate map and structured stage diagnostics until the next search replaces them. The worker registers only the public file types listed below.

## Public File Types

- `original`: stored upload.
- `upload_preview`: browser-safe preview for HEIC/HEIF uploads.
- `ai_simplified`: AI-generated flat-colour illustration.
- `ai_region_map`: visual initial region map.
- `ai_palette_preview`: final palette reconstruction preview.
- `ai_validation_report`: JSON validation report.
- `ai_numbered_template`: numbered template image.
- `ai_palette_sheet`: palette sheet image.
- `ai_painted_reference`: reference reconstructed from the final region map and palette.
- `ai_final`: printable template PNG.
- `ai_final_palette`: printable palette PNG.
- `ai_template_pdf`: printable template PDF.
- `ai_palette_pdf`: printable palette PDF.

## Statuses

- `uploaded`
- `upload_preview_processing`
- `upload_preview_queued`
- `ai_queued` / `ai_processing` for legacy one-shot runner jobs.
- `ai_image_queued`
- `ai_image_processing`
- `ai_image_ready`
- `pbn_queued`
- `pbn_processing`
- `pbn_options_queued`
- `pbn_options_processing`
- `pbn_options_ready`
- `pbn_selection_queued`
- `pbn_selection_processing`
- `pbn_selection_failed`
- `pbn_failed`
- `ai_completed`
- `ai_failed`
- `deleted`

The frontend allows initial AI image generation from `uploaded` or `ai_failed`, regeneration from review/completed/failure states, and PBN continuation after `ai_image_ready`. Advisory `ai_quality` warnings never disable regeneration or continuation. Failed AI image runs store `ai_failed`; failed continuation runs store `pbn_failed` and direct the user to regenerate a simpler AI image.

## Settings

`POST /api/projects/{public_id}/run` accepts:

- `provider`: `openai`, `gpt`, or `gemini`.
- `category`: frontend selection of `portrait`, `pet`, `landscape`, `architecture`, `still_life`, or `illustration`; default `illustration`. The API retains a string value for compatibility.
- `target_palette_size`: integer 8-40, default 24. The image-provider prompt treats this as an exact fixed-palette contract, remaps extra source tones to the closest selected colour, and spends palette contrast on subject-defining features before background variation. Image models can still emit accidental blended or antialiased pixels, so deterministic downstream palette normalization remains authoritative.
- `preserve_elements`: string list assembled from optional category-specific suggestions and user-entered values.
- `simplify_elements`: string list assembled from optional category-specific suggestions and user-entered values.
- `prompt_guidance`: optional user guidance appended to the AI prompt, max 1000 characters. The frontend explains how to write concise, image-specific guidance.
- `page_size`: `a3` or `a4`, default `a3`.
- `orientation`: `portrait` or `landscape`; frontend initially matches the source, backend fallback is portrait.
- `fit_mode`: `cover` or `contain`, default `cover`.
- `crop`: normalized `{x,y,width,height}` for cover, or `null` for contain.

Settings are persisted in `projects.ai_settings` when AI generation is queued. `/proceed` has no settings body and always uses that saved composition and palette request. Replacing the source clears the saved settings. Output dimensions are derived internally from A3/A4 at 300 DPI with a 10 mm safe margin.

## Preserve Detail Selection

After the reviewed AI image is ready, the user may lasso filled Preserve Detail areas, refine them with 1%, 3%, or 6% paint/erase brushes, and use undo/redo. White pixels emphasize source-supported boundaries in the selected area. All pixels use the same connected source graph. Selections above 40% show a performance warning but remain valid.

The backend stores the exact-size normalized mask and manifest under `pipeline_ai/input/`. Editing it is owner-only and idle-state-only. A mask change intentionally invalidates options and final exports and returns the project to `ai_image_ready`; replacing the source or reviewed AI image clears it.

The runner analyzes the reviewed image once into connected colour-edge regions and caches that analysis by image hash. The mask changes edge evidence only where a boundary exists in the reviewed image; it does not cut out an isolated processing zone or introduce a lasso border. Hard uses this shared structural graph. A selected boundary receives the Hard evidence boost and may use up to 10% density overflow. A meaningful feature still must satisfy the physical printer floor and global palette constraints.

The unified graph uses immutable source-pixel Lab statistics and additive requested-palette reconstruction costs. Dynamic merge priorities combine reconstruction loss with source boundary contrast and are recomputed after each merge; natural boundaries have graded costs rather than a hard veto. Regions below the physical area or width floor are resolved in this graph before the final cleanup check. Hard starts with a density ceiling of 650 regions and retries only if validation fails. If faithful recolouring cannot resolve a palette conflict, the runner merges a deterministic lowest-loss boundary and records the fallback without exceeding the requested palette size.

Structural analysis reads the reviewed colours without adding blur bands, then splits diagonal-only contacts into separate four-connected regions before measuring or merging them. Palette centres that export to the same RGB colour, or differ by less than the existing 2 Delta-E weak-contrast floor, share one paint identity before adjacency resolution. Validation measures actual connected components and rejects disconnected numbered regions and duplicate paint colours. Boundary alignment skips movement when one source pixel would exceed the physical snap limit.

## Configuration

```text
HTTP_PORT=8080
POSTGRES_DSN=postgres://pbn:pbn@postgres:5432/pbn?sslmode=disable
REDIS_ADDR=redis:6379
REDIS_DB=0
REDIS_QUEUE_NAME=pbn:jobs
REDIS_EVENTS_CHANNEL=pbn:events
QUEUE_MAX_SIZE=20
MAX_ACTIVE_PROJECTS_PER_CLIENT=2
STORAGE_ROOT=/storage
PUBLIC_ID_LENGTH=12
INTERNAL_API_SECRET=local-dev-secret
BACKEND_INTERNAL_BASE=http://backend:8080/api/internal
PYTHON_RUNNER_BASE_URL=http://pbn:8081
PROJECTS_DIR=/storage/projects
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

`OPENAI_IMAGE_MODERATION` accepts `low` or `auto` and defaults to `low`. When OpenAI returns a `moderation_blocked` error, the runner preserves the optional coarse moderation stage, public categories, and request ID; the worker stores an actionable user-facing error and does not retry the unchanged request.

`PBN_OPTION_MAX_ATTEMPTS` defaults to five and is clamped to `1-5`. It counts the initial local attempt and never triggers another provider request.

`PBN_DEBUG_IMAGES=1` retains eight per-option debug images under `options/{difficulty}/debug/`, from the reviewed source and connected atoms through the graph, palette, final preview, and template. Validation reports include region counts by stage, physical-floor merge counts, region area and boundary complexity summaries, and stage timings. Debug files are internal traces.

After density and palette compaction, every option candidate is aligned to multiscale Lab edges from the immutable reviewed AI image within a maximum 0.6 mm corridor. Regions close enough to the printer floor to be endangered by the move are frozen and cannot gain or lose pixels. The alignment keeps fixed contacts for every adjacency and applies only topology-safe four-connected pixel moves. Individual proposals are rejected if they change topology, violate the printer floor, reduce edge support, or worsen source-median reconstruction beyond the allowed tolerance. When all optional proposals are rejected but the pre-alignment map remains printable, the runner keeps that map and records alignment as skipped; an invalid baseline still fails with structured diagnostics. Template export traces every shared boundary once so neighbouring regions cannot create doubled strokes.

Do not hardcode local-only values into production code. Use environment variables.

## Data and Security Notes

- Backend stores uploads with normalized names and does not trust user-provided filenames for storage paths.
- File preview/download resolves registered paths and rejects paths outside `/storage/projects/{public_id}`.
- Internal worker endpoints require `X-Internal-Secret`.
- The internal topology implementation identifies new runner results as `ai-topology-v2`; the public project pipeline value remains `ai`.
- Client ownership uses `X-Client-Token` from localStorage for uploads and run requests.
- Local runtime folders, generated project files, build caches, and TypeScript build info should not be committed.
