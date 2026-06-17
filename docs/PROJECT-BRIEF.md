# PROJECT-BRIEF.md

Project brief for the Paint-by-Numbers (PBN) web app.

## Product idea

The app converts an uploaded image into a printable Paint-by-Numbers template.

The user flow:

1. User uploads a photo/image.
2. Backend creates a project and stores the original image.
3. System generates an upload preview, especially for formats like HEIC/HEIF.
4. User runs or continues a six-step processing pipeline.
5. The app shows a clear preview for the latest completed step.
6. Final result is a printable PDF, currently targeting A3 output.

The app should feel production-minded even while it is an MVP: clear service boundaries, stable contracts, queue-based background work, reliable status updates, and recoverable errors.

## MVP scope

In scope:

- Upload image.
- Create project.
- Store original as `original.{ext}`.
- Generate upload preview.
- Run steps 1-6.
- Show live progress and latest preview.
- Store generated files as project files.
- Download final PDF.
- Support HEIC/HEIF input.
- Docker-based local development.

Out of scope for now:

- Payments.
- Cloud AI processing.
- User account system beyond current client-token ownership model.
- Public gallery/social sharing.
- Advanced editing UI for manual region correction.

## Architecture

Services:

```text
frontend  -> backend API / WebSocket
backend   -> PostgreSQL, Redis, internal worker API coordination
worker    -> Redis queue consumer, runner caller, backend internal status/file updates
runner    -> FastAPI image-processing service
storage   -> /storage/projects/{public_id}
```

Primary technologies:

- React frontend
- Go backend
- PostgreSQL
- Redis queue and pub/sub
- Python worker
- Python FastAPI runner
- Docker Compose
- SAM2 / OpenCV / PIL / scikit-image / sklearn

## Processing pipeline

### Step 1: SAM2 segmentation

Goal: find meaningful objects/segments in the uploaded image.

Typical parameters:

- `points_per_side`
- `pred_iou_thresh`
- `stability_score_thresh`
- `min_mask_region_area`
- `min_area_ratio`
- `max_area_ratio`
- `dedupe_iou`

Outputs may include:

- `segments.json`
- `step1_overlay.png`

### Step 2: Smooth segments

Goal: simplify noisy areas inside objects while preserving important details.

Techniques may include:

- LAB color clustering
- object-wise smoothing
- small-object cleanup
- hole cleanup

Outputs may include:

- `local_map.png`
- `step2_overlay.png`

### Step 3: Global palette

Goal: create a shared paint palette for the whole image.

Typical target:

- cheap/simple: around 20 colors
- standard: around 24 colors
- detailed: around 30 colors

Outputs may include:

- `palette.json`
- `palette_sheet.png`
- `label_map.png`

### Step 4: Regions cleanup

Goal: convert the color map into printable connected regions.

Important visual constraints:

- remove tiny islands
- merge regions that are too small for numbers
- avoid conflicts between adjacent same-label regions where needed
- preserve readable boundaries

Outputs may include:

- `region_map.png`
- `edges.png`
- `regions.json`

### Step 5: Template generation

Goal: generate printable line art and numbered regions.

Outputs may include:

- `template.png`
- `template_numbers.png`

### Step 6: PDF export

Goal: export final printable PDF.

Current target:

- A3 page
- default dimensions: 29.7 x 42 cm
- image can use a fit/crop mode depending on parameters
- avoid unwanted margins when crop/cover mode is selected

Output:

- `pbn_final.pdf`

## UX expectations

The frontend should not require manual refresh after a step completes.

Expected preview progression:

```text
upload -> upload_preview.jpg or original preview
step 1 -> step1_overlay.png
step 2 -> step2_overlay.png
step 3 -> palette_sheet.png or agreed visual preview
step 4 -> region_map.png or agreed visual preview
step 5 -> template_numbers.png
step 6 -> final PDF download
```

Step UI behavior:

- Show completed steps as completed.
- Show running step as active/running.
- After completion, move active step to the next step.
- Do not show a completed step's image one step late.
- Prefer WebSocket events over polling.

## Known pain points / priorities

These are recurring problems to be careful with:

1. Images/previews not updating reliably after step completion.
2. Frontend sometimes shows a step image one step late.
3. Too many backend-generated files appear in UI instead of one useful preview per step.
4. HEIC uploads need preview conversion.
5. Runner and backend can disagree about original file naming.
6. Step 4-6 are more fragile than step 1-3 and need better error reporting.
7. Worker must publish events when preview/step files are generated.
8. File metadata must stay consistent across backend, worker, runner, and frontend.

## Design principles

- Make each step independently debuggable.
- Keep generated outputs visible and traceable.
- Prefer clear file contracts over clever auto-discovery.
- Keep UI state derived from project status + events, not guesswork.
- Keep defaults safe and printable.
- Optimize later; correctness and debuggability come first.
