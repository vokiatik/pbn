# File Contract

This app stores local runtime files under `/storage/projects/{public_id}`. Backend file preview/download endpoints only serve registered files whose absolute path resolves under that project directory.

## Project Layout

```text
/storage/projects/{public_id}/
  original/
    original.{png|jpg|jpeg|webp|heic|heif}
  generated/
    upload_preview.jpg
  pipeline_ai/
    analysis/
      source_atoms.npy
      manifest.json
    input/
      detail_protection.png
      detail_protection.json
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
    options/
      options.json
      attempt_reports/hard-{attempt}.json
      .attempts/hard/{attempt}/failure/diagnostics.json
      .attempts/hard/{attempt}/failure/region_id_map.npy
      .attempts/hard/{attempt}/failure/region_map.png
      hard/label_plan.json
      hard/regions/detail_protection.png
      hard/regions/detail_protection.json
      hard/regions/selected_source_edges.png
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

## Public File Types

These are the file records the worker registers with the backend.

| file_type | Relative path | Purpose |
| --- | --- | --- |
| `original` | `original/original.{ext}` | Preserved upload. |
| `upload_preview` | `generated/upload_preview.jpg` | Browser-safe preview for HEIC/HEIF uploads. |
| `ai_simplified` | `pipeline_ai/ai/simplified.png` | AI-generated flat-colour illustration shown for review before PBN continuation. |
| `ai_region_map` | `pipeline_ai/regions/initial_region_map.png` | Visual region extraction output. |
| `ai_palette_preview` | `pipeline_ai/palette/preview.png` | Final palette reconstruction from the validated region map. |
| `ai_validation_report` | `pipeline_ai/validation/report.json` | Validation metrics and issues. |
| `ai_numbered_template` | `pipeline_ai/template/numbered_template.png` | Numbered template before page fitting. |
| `ai_palette_sheet` | `pipeline_ai/template/palette_sheet.png` | Palette sheet image. |
| `ai_painted_reference` | `pipeline_ai/export/painted_reference.png` | Painted reference reconstructed exactly from the final region map and palette. |
| `ai_final` | `pipeline_ai/export/pbn_final.png` | Printable template PNG. |
| `ai_final_palette` | `pipeline_ai/export/pbn_final_palette.png` | Printable palette PNG. |
| `ai_template_pdf` | `pipeline_ai/export/pbn_template.pdf` | Printable template PDF. |
| `ai_palette_pdf` | `pipeline_ai/export/palette_sheet.pdf` | Printable palette PDF. |
| `ai_hard_painted_preview` | `pipeline_ai/options/hard/painted_reference.png` | Saved Hard coloured preview. |
| `ai_hard_template_preview` | `pipeline_ai/options/hard/numbered_template.png` | Saved Hard template preview. |

## Frontend File List

Easy and Medium preview types are historical only. New jobs register only Hard previews, and successful regeneration removes stale option folders and unregisters previous PBN outputs before publishing the new Hard files.

The project details page groups the registered outputs into these user-facing downloads:

| Display name | Download file type | Preview file type |
| --- | --- | --- |
| Original image | `original` | `upload_preview` when available; otherwise `original` |
| AI-generated image | `ai_simplified` | `ai_simplified` |
| Coloured preview | `ai_painted_reference` | `ai_painted_reference` |
| Paint-by-number preview | `ai_final` | `ai_final` |
| Final PBN template | `ai_template_pdf` | `ai_template_pdf` |
| Colour palette | `ai_palette_pdf` | `ai_final_palette`, falling back to `ai_palette_sheet` or `ai_palette_pdf` |

Other registered outputs are secondary pipeline artifacts and are not shown in the primary file table. Their stored filenames and `file_type` values remain unchanged.

## Internal Trace Files

The runner also writes trace files such as `crop_manifest.json`, internal `provider_output.png`, `generation.json`, `quality_report.json`, the quality reconstruction preview, cached `analysis/source_atoms.npy` and its SHA-256 manifest, `boundary_strength.png`, protection/stage maps, merge and cleanup logs, per-option metadata and `label_plan.json`, `regions.json`, `adjacency.json`, `.npy` maps, `export_result.json`, and `pipeline_result.json`. `input/detail_protection.png` is the exact-size binary user mask; its JSON manifest records dimensions, coverage, SHA-256, and update time. Selected options retain the selected source-edge trace, stage counts, physical-floor merge count, region-area summaries, boundary complexity, stage timings, selected-boundary retention, and forced-merge counts. With `PBN_DEBUG_IMAGES=1`, selected options also retain eight internal stage images in `debug/`. Alignment traces record the requested and selected snap radius, changed pixels, boundary length, source-edge support, reconstruction change, and topology result. `options/options.json` records bounded search settings, validation metrics, rejection reasons, and selected attempt; `options/attempt_reports/` retains each lightweight validation report. After a successful search, rejected attempts are removed. When every option fails, `options/.attempts/` is retained until the next search and contains the last intermediate region map plus structured failure diagnostics. Invalid options never become public previews or exports.

## Update Rules

When changing a public filename or `file_type`, update all of these together:

- runner output path in `pbn/ai_pipeline/`
- worker mapping in `worker/worker_app/constants.py`
- frontend preview/file list logic
- backend docs/API expectations
- this file

Avoid registering every trace file by default. Public files should be stable, meaningful outputs the user can inspect or download. During the AI image review step, only `original`, optional `upload_preview`, and the current `ai_simplified` need to be registered; downstream PBN artifacts are registered after proceed succeeds.

The Preserve Detail mask is deliberately internal and is served only by its owner-protected mask endpoint. It is cleared when the source or reviewed AI image is replaced. A mask update removes downstream option/export folders and root result manifests before a new continuation.
