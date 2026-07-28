# AI-Assisted PBN Pipeline

This is the only supported product pipeline.

## Active Flow

```text
original photo
-> EXIF correction
-> one saved A3/A4 crop or contain composition
-> provider-safe padded canvas
-> one AI-simplified illustration
-> remove only the recorded provider padding
-> immutable user review image
-> advisory source-quality assessment
-> immutable multiscale boundary-protection map
-> optional user-lassoed/painted Preserve Detail mask
-> hybrid ordinary SLICO + selected source-pixel microregions
-> one protection-aware hierarchical region graph
-> deterministic detail-weighted CIELAB palette
-> physical cleanup and topology-preserving source-edge alignment
-> adaptive gray numbering and protected palette-colour fallback
-> hard validation
-> 300-DPI PNG/PDF export
```

The provider response is stored internally at `ai/provider_output.png`. The safe-area review image is public at `ai/simplified.png`. Local processing never overwrites either image and never calls the provider during PBN retries.

The provider prompt uses the user's requested palette size as an exact fixed-colour contract. It tells the model to select that palette first, replace excess source tones with the closest palette colour, reserve perceptual contrast for recognizable subject features, and simplify background variation first. This is a strong generation instruction rather than a mathematical guarantee: provider antialiasing or blended pixels may still create extra decoded RGB values, so deterministic downstream normalization remains the final palette authority.

## Print Composition

- A3 is the default; A4 is optional.
- Frontend initially matches source orientation; backend fallback is portrait.
- Cover uses a normalized user crop. Contain uses the whole source.
- `prepared/crop_manifest.json` records original dimensions, crop pixels, composition size, provider canvas, and provider content box.
- Final output is 300 DPI with a 10 mm safe margin: A3 `3508x4961`, A4 `2480x3508`, swapped for landscape.
- Template export fits the approved composition inside the safe box and performs no crop.

## Geometry, Palette, and Numbering

1. SLICO creates a 3,000-atom Easy base and a shared 9,450-atom Medium/Hard base. One immutable multiscale protection map is derived from the reviewed image. Without a user mask, this remains the exact pipeline path.
2. In a Preserve Detail selection, four-connected exact-RGB source components replace every touched SLIC atom. A 1.2 mm transition prevents a brush-shaped seam; unsupported component and seam boundaries collapse before density processing. The safety cap is 100,000 microregions.
3. The basic and advanced branches are stitched into one graph and use one requested palette. Advanced palette costs include every immutable source pixel or its exact colour histogram.
4. User-boundary coverage multiplies source evidence by 2.9/5.8/11.6 for Easy/Medium/Hard, capped at one. It can become hard protection only when the source boundary is independently meaningful and effective evidence reaches `0.70`.
5. Region-adjacency merging treats hard protection as a veto, updates additive source-pixel reconstruction statistics and adjacency costs after each deterministic merge, and merges unsupported weak boundaries regardless of density.
6. A profile may reach 110% of its attempt ceiling only when selected, source-supported boundaries block safe merging. Overflow is not rewarded, and forced selected-boundary merges are reported if the limit must still be met.
7. Geometry cleanup enforces only the 0.5 mm2 / 0.5 mm printer floor. Label fit is evaluated later using the actual palette number and never deletes geometry solely for lacking a 4 mm pocket.
8. After candidate compaction, marker-controlled watershed proposes source-edge alignment within 0.6 mm. Printer-floor-sensitive regions are frozen; fixed adjacency anchors and four-connected safe moves preserve region IDs, contacts, components, and holes. Unsafe geometry is rejected rather than published.
9. Palette samples use `sqrt(region_area) x (1 + 2 x protection_score)`. Up to 4-8 perceptually distinct protected colours are reserved without exceeding the requested palette size.
10. Weak unprotected boundaries merge even below a density target. Same-colour adjacency uses a distinct alternative only within bounded source/palette delta E; otherwise the regions merge instead of inventing contrast. If only protected natural-boundary conflicts remain, one deterministic lowest-reconstruction-loss boundary is merged per pass and reported as a protected palette fallback.
11. Labels use discrete printed text heights of 4, 3, 2, and 1 mm and render in RGB `#737373`; contours remain black. Protected regions that cannot hold 1 mm are filled with their assigned paint, capped at 3% of printable content.
12. The per-option `label_plan.json` drives both the preview and final export. Older saved options rebuild it deterministically during finalization.
13. The painted reference is reconstructed from the final map and palette, so it exactly matches the template. Printable outlines trace each shared boundary once to prevent doubled strokes; Preserve Detail runs use 45% more contour approximation to soften raw edge noise without changing the global difficulty profiles.

## User-Selected Difficulty Options

PBN continuation runs a bounded deterministic density search and never selects a user-facing difficulty. Easy prefers a mid-range simplified result near 375 regions; Medium and Hard preserve meaningful boundaries toward their nominal budgets. The search coordinates candidates so consecutive displayed difficulties remain at least 10% distinct and never creates artificial splits.

| Profile | Region budget | Initial superpixels | Merge delta E00 | Contour tolerance |
| --- | ---: | ---: | ---: | ---: |
| Easy | 500 | 3,000 | 1.5 | 0.25 mm |
| Medium | 750 | 9,450 | 0 | 0.15 mm |
| Hard | 1,050 | 9,450 | 0 | 0.10 mm |

Easy uses its simplified geometry base; Medium and Hard share an immutable high-detail base. Attempt targets are ceilings, not quotas. Palette topology first removes every unsupported weak boundary, then merges the lowest reconstruction-loss boundaries only while above the ceiling. Adjacent groups receive distinct paints only when the reviewed image and requested palette can support that contrast faithfully.

At most five attempts per difficulty are run, including the initial attempt. Density targets are Easy `375, 350, 400, 325, 425`, Medium `750, 700, 650, 600, 550`, and Hard `1050, 975, 900, 825, 750`. These remain nominal ceilings. If the first valid Medium and Hard results are not 10% distinct, later Medium attempts deterministically bracket the compaction input between observed too-dense and sufficiently sparse results; validation still rejects excessive fidelity loss. Search stops when a best possible valid triplet exists. If no triplet passes, the largest valid distinct subset is saved. Final files are written only after explicit user selection.

## Hard Validation

- Palette size does not exceed the requested target.
- Every region is mapped and no unprotected same-colour adjacent pair remains.
- No protected boundary is merged unless an exact-palette conflict has exhausted faithful recolouring and ordinary merges; every such last-resort merge is reported and remains subject to protected-boundary retention validation. No indistinguishable adjacent colour remains.
- Region count is at most 110% of the selected profile budget and displayed difficulties remain at least 10% distinct.
- Protected-boundary recall is at least 90% with a two-pixel tolerance.
- Protected-detail mean delta E00 is at most 8 and p90 is at most 15.
- Every non-prefilled region has a printed label height of at least 1 mm; protected prefill occupies at most 3% of printable content.
- Every region obeys the 0.5 mm2 / 0.5 mm printer floor.
- Unprotected weak boundaries with source delta E below 2 never use paint contrast of delta E 5 or greater.
- Mean reconstruction delta E is at most 6, and selected Medium/Hard fidelity does not worsen by more than 0.25 from the preceding difficulty.
- Template dimensions match the selected page, safe margins are intact, and no second crop occurs.
- Painted reference, region map, palette, and template mapping are consistent.
- Source-edge alignment stays within 0.6 mm, preserves topology and the printer floor, does not reduce boundary support, and adds at most 0.05 source-median reconstruction delta E.

Global reconstruction delta E is a hard candidate guard and a coordinated triplet-selection constraint.

## Advisory Source Quality

The runner assesses the reviewed image at a maximum dimension of 768 px with deterministic SLICO and target-palette reconstruction. It records mean and p90 delta E00, estimated connected-region count, and micro-detail area. It returns `warn` for palette mismatch, more than 3% micro-detail area, or more than 1,155 estimated regions. The warning is persisted to `projects.ai_quality`, shown beneath the reviewed image, and never disables regeneration or continuation.

## Product and Contract Rules

- `/run` persists normalized settings in `projects.ai_settings` and clears stale quality data.
- `/proceed` accepts no replacement settings, uses the saved settings, and generates options only.
- `/select-pbn` exports one saved valid option without another AI or segmentation run.
- Replacing the source clears saved settings, crop, and quality data.
- Legacy reviewed projects without settings must regenerate before continuation.
- Completed legacy downloads remain registered.
- Existing final filenames and public `file_type` values remain stable; difficulty preview types are additive.
- New runner traces use internal identifier `ai-topology-v2`; the public pipeline value remains `ai`.
- Legacy direct, V2/V3, and step-by-step workflows remain removed.
