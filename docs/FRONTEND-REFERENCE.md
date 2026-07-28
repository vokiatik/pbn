# Frontend Reference

The frontend exposes one workflow: AI-assisted photo-to-PBN generation.

## Routes

- `/upload`: upload an image and create an `ai` project.
- `/projects`: list non-deleted projects.
- `/projects/:publicId`: configure and run the AI pipeline, inspect generated outputs, and download files.

## Primary Files

- `frontend/src/App.tsx`: app shell and routes.
- `frontend/src/api/client.ts`: API types, client token handling, API calls, preview/download URL builders.
- `frontend/src/pages/UploadPage.tsx`: upload validation and project creation.
- `frontend/src/pages/RequestsListPage.tsx`: project list and status phase labels.
- `frontend/src/pages/ProjectDetailsPage.tsx`: AI settings, option generation, explicit difficulty selection, WebSocket handling, previews, and file table.
- `frontend/src/components/Details/ProjectFilesTable.tsx`: public artifact list.

## Detail Page Behavior

- Default settings are provider `openai`, category `illustration`, empty AI guidance, palette size 24, fit mode `cover`, and 1024 x 1024 output.
- Category is selected from Portrait, Pet, Landscape, Architecture, Still life, or Illustration / other. Each option explains which image subjects it covers.
- Preserve and Simplify accept removable category-specific suggestion chips and free-entry custom values. Changing category changes the available suggestions without clearing selected values.
- Additional guidance remains optional and includes concise writing guidance plus an example; its maximum length is 1000 characters.
- Users can generate an AI image from `uploaded` or `ai_failed`.
- Users can review `ai_simplified`, regenerate it, or generate saved Easy, Medium, and Hard options from `ai_image_ready`.
- Only valid options are shown; no option is preselected. Selecting one queues final exports, and saved options can be selected again later.
- The page connects to `/ws?project_id={publicId}` and filters events by `project_id`.
- Status updates come from WebSocket events and project reloads.
- When an event includes files, the page reloads project details to get canonical backend file IDs.
- Failed AI runs show `error_message` from the project after reload.

## Preview Priority

The main output panel currently shows the first available file in this order:

1. `upload_preview`
2. `original`
3. `ai_simplified`
4. `ai_palette_preview`
5. `ai_numbered_template`
6. `ai_final`
7. `ai_validation_report`

The file table lists all public artifact types from [FILE-CONTRACT.md](FILE-CONTRACT.md).

## Removed Frontend Workflows

- Step-by-step V1 project page.
- V2 printable workflow page and multi-stage review controls.
- V3 graph-first workflow page and object controls.
- Candidate comparison and selection screens.
