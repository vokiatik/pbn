# PBN quality review — 25 September 2026

The earlier changes improved recognizability but were not ready as written. Inspection of the saved cat result found 375 disconnected pieces sharing region IDs, despite a reported island count of zero. The corrected generator produces only Hard output, as requested.

## Defects found and corrected

- Felzenszwalb segmentation joins diagonal neighbours, while painting, numbering and physical measurements require four-connected regions. Atoms are now split before graph merging, region records measure real component counts, and validation rejects disconnected numbered regions.
- Blurring the reviewed flat-colour image created extra boundary bands. A two-colour synthetic circle became 650 four-connected atoms. Analysis now reads source colours directly; the final circle has two regions.
- Reserved and ordinary palette centres could produce duplicate paint colours under different numbers. Palette identities are consolidated before adjacency resolution, including colours below the existing weak-contrast floor. Validation also rejects exact duplicates.
- Boundary alignment forced a one-pixel move even when that exceeded its 0.6 mm limit. It now skips movement at such resolutions.
- Finalization overwrote the saved generation report. It now preserves that report and carries generation diagnostics into the export validation report.

The active local path is reviewed image → cached connected atoms → dynamic region graph → global palette → physical and boundary checks → numbering → Hard preview → printable export. The AI prompt is unchanged. Preserve Detail weights existing source boundaries rather than creating independent processing areas.

## Hard-only product flow

Generation stops at the first valid Hard result. Validation failures may trigger a bounded deterministic retry; no successful alternatives are generated for ranking. Easy and Medium are not generated, registered, offered in the UI, or accepted for export. Successful regeneration removes their stale option folders and replaces old registered PBN files. Existing API paths, status names and Hard file types remain stable; no database migration is required.

## Evidence

The saved 1024 × 1024 reviewed cat image was regenerated without a provider call. Hard completed on its first attempt in approximately 88 seconds:

| Measurement | Hard result |
| --- | ---: |
| Regions | 587 |
| Distinct paint colours | 18 |
| Disconnected regions | 0 |
| Regions below configured physical floor | 0 |
| Unnumbered regions | 0 |
| Protected details using existing prefilled fallback | 33 |
| Mean CIEDE2000 source reconstruction error | 0.81 |

Visual inspection confirms that both cats' eyes, their facial structure, and the blind slats survive. The saved old Medium result had lost the eyes; this is a historical reference rather than an equal-density comparison. The final Hard PNG, template PDF and palette PDF were generated successfully. Local review artifacts are under `storage/local-audit/review-hard/` and are not committed.

## Verification and changed files

The runner and worker suites pass: **68 tests plus 9 subtests**. The structural suite now checks final coloured outputs and templates, physical limits, connected regions, tiny eyes, fingers, stripes, weak shading, flat backgrounds, small contrasting objects, curved and straight boundaries, diagonal contacts, multiple resolutions, deterministic results, Hard-only generation, rejection of legacy export requests, and diagnostic preservation.

`go test ./...`, `npm run build`, `docker compose config --quiet`, and `git diff --check` pass. Vite reports its existing bundle-size advisory.

Core implementation files: `segmentation.py`, `hierarchical_merge.py`, `palette.py`, `regions.py`, `validation.py`, and `pipeline.py` under `pbn/ai_pipeline/`. Hard-only contracts span runner request models, backend AI handlers, worker registration mappings/jobs, and frontend API types, preview controls and status text. Regression tests and the project/API/file-contract documentation were updated alongside them.

## Limits

Dense fur still creates an intricate Hard template. Physical area and average-width checks are useful constraints, not proof that every shape is comfortable to paint. Some small protected details remain prefilled by the existing fallback. The regression suite and one real saved image establish the specific fixes above; a broader photo corpus is still needed to characterize general visual quality. Changes are local and have not been deployed.
