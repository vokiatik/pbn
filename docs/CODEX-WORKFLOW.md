# CODEX-WORKFLOW.md

Use this file as reusable task guidance for Codex sessions on the PBN project.

## Start-of-task prompt template

Use this when asking Codex to work on the project:

```text
You are working in my Paint-by-Numbers repository.

First read AGENTS.md and PROJECT-BRIEF.md.
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

## Good task examples

### Frontend preview bug

```text
Fix the frontend bug where the preview image updates one step late.
Use WebSocket/project file updates as the source of truth.
Do not add polling unless there is already an intentional fallback.
Keep the preview-selection logic isolated in a small helper or hook.
```

### Worker event bug

```text
Fix the worker/backend event flow so the frontend receives an update when a step creates a new preview file.
Inspect the backend internal file registration endpoint, worker step completion logic, and WebSocket event publishing.
Keep file metadata consistent.
```

### HEIC upload preview

```text
Make HEIC/HEIF uploads show a browser-safe upload preview.
Backend should store original.{ext}, call runner /generate-upload-preview when needed, register upload_preview.jpg, and notify the frontend.
Do not remove support for png/jpg/jpeg/webp.
```

### Step 6 PDF margin/fit work

```text
Update Step 6 PDF export so fit mode is configurable.
Supported modes should include contain, cover/crop, and stretch only if already agreed.
Default should avoid unwanted print margins when cover is selected.
Keep backward compatibility with existing step parameters where possible.
```

## Planning checklist for bigger tasks

Before coding bigger changes, Codex should produce a short plan covering:

1. Relevant files/services inspected.
2. Existing contract found.
3. Proposed changes by service.
4. Risks or ambiguous decisions.
5. Checks that will be run.

Do not produce a long architecture essay. Keep the plan actionable.

## Review checklist

Before handing work back, Codex should verify:

- Does the UI receive status/file updates without manual refresh?
- Does the selected preview correspond to the latest completed step?
- Did file names stay aligned across services?
- Did `file_type` values stay stable and meaningful?
- Does the backend still protect internal endpoints?
- Are errors clear enough for debugging?
- Were relevant tests/builds/typechecks run?
- If checks were skipped, is the reason specific?

## Suggested repo docs to maintain later

Consider adding these only when the repo is ready:

```text
docs/file-contract.md       # generated files and file_type mapping
docs/pipeline.md            # step inputs/outputs and parameters
docs/local-dev.md           # exact local run/debug commands
docs/frontend-state.md      # project status, active step, preview selection, WS events
docs/troubleshooting.md     # common runner/worker/backend failures
```

Do not create heavy documentation too early. Add these docs when they prevent repeated mistakes.
