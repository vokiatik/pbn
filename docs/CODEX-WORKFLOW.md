# Codex Workflow

Use this file as reusable task guidance for Codex sessions on the PBN project.

## Start-of-Task Prompt Template

```text
You are working in my Paint-by-Numbers repository.

First read AGENTS.md and docs/PROJECT-BRIEF.md.
Then inspect the relevant files before changing anything.

Task:
[describe the problem]

Constraints:
- Keep changes small and production-minded.
- Do not rewrite unrelated code.
- Preserve backend/worker/runner/frontend contracts unless the task explicitly requires changing them.
- Ask questions before coding if behavior or contracts are ambiguous.
- After implementation, run the relevant checks and summarize what changed.
```

## Good Task Examples

### Frontend Output Refresh Bug

```text
Fix the frontend bug where generated AI outputs do not appear after completion.
Use WebSocket events and a project reload to get canonical backend file IDs.
Do not add polling unless there is already an intentional fallback.
Keep preview/file selection logic isolated.
```

### Worker File Registration Bug

```text
Fix the worker/backend event flow so the frontend receives registered AI artifacts after a run.
Inspect worker/worker_app/constants.py, worker/worker_app/file_detection.py, backend internal file registration, and WebSocket event publishing.
Keep file_type values consistent with docs/FILE-CONTRACT.md.
```

### HEIC Upload Preview

```text
Make HEIC/HEIF uploads show a browser-safe upload preview.
Backend should store original/original.{ext}, queue generate_upload_preview, runner should write generated/upload_preview.jpg, worker should register upload_preview, and frontend should show it.
Do not remove support for png/jpg/jpeg/webp.
```

### AI Provider Configuration

```text
Improve AI provider configuration errors.
Inspect pbn/ai_pipeline/config.py, provider_factory.py, runner_app/ai_service.py, and worker/worker_app/runner_client.py.
The app should start without credentials, but generation should fail clearly when no provider is configured.
```

## Planning Checklist For Bigger Tasks

Before coding bigger changes, produce a short plan covering:

1. Relevant files/services inspected.
2. Existing contract found.
3. Proposed changes by service.
4. Risks or ambiguous decisions.
5. Checks that will be run.

Keep the plan actionable. Avoid long architecture essays.

## Review Checklist

Before handing work back, verify:

- Does the UI receive status/file updates without manual refresh?
- Do public file names and `file_type` values match [FILE-CONTRACT.md](FILE-CONTRACT.md)?
- Does the backend still protect internal endpoints with `X-Internal-Secret`?
- Does file serving still reject registered paths outside the project directory?
- Are provider and runner errors visible in `project.error_message` after reload?
- Were relevant tests/builds/typechecks run?
- If checks were skipped, is the reason specific?

## Suggested Repo Docs To Maintain

- `docs/PROJECT-BRIEF.md`: product and architecture source of truth.
- `docs/API.md`: public/internal API contract.
- `docs/FILE-CONTRACT.md`: generated files and public `file_type` mapping.
- `docs/AI-PBN-PIPELINE-PLAN.md`: active AI pipeline implementation map.
- `docs/FRONTEND-REFERENCE.md`: frontend routes, state, and output behavior.
- `docs/FRONTEND-LOOK-PROMPT.md`: visual reference prompt.
