# Paint-by-Numbers Photo Converter

This project converts a realistic photo into a high-quality paint-by-number template while preserving composition and key details.

It is designed to avoid the common failure mode of:
- too much blur, where important color differences disappear
- too little cleanup, where thousands of tiny unpaintable regions remain

The pipeline combines edge-aware smoothing, superpixels, LAB-space palette clustering, region-graph merging, and morphological cleanup.

## Command
c:/Users/admin/pbn/.venv/Scripts/python.exe main.py input/photo.jpg --out output/ultra_small_pixels --colors 32 --size 2200 --detail-level 1.0 --superpixel-area-px 320 --superpixels-min 12000 --superpixels-max 40000 --min-region-area 24 --edge-threshold 0.14 --lab-merge-threshold 16 --cleanup-passes 0 --preserve-detail-regions --superpixel-shape adaptive (square) 
## Project Structure

```text
main.py
pbn/
  __init__.py
  config.py
  io.py
  preprocess.py
  edges.py
  superpixels.py
  palette.py
  region_graph.py
  merge.py
  render.py
  pdf_export.py
  utils.py
requirements.txt
README.md
```

## Install

```bash
pip install -r requirements.txt
```

## CLI

```bash
python main.py input/photo.jpg --out output --colors 32 --size 4000 --min-region-area 80 --pdf
```

Main options:
- `--colors`: target palette size, default `32`
- `--size`: output longest side in pixels, default `4000`
- `--detail-level`: detail preservation from `0.0` to `1.0`, default `0.6`
- `--superpixel-area-px`: target average superpixel area; smaller values produce finer detail
- `--superpixel-shape`: `square`, `adaptive`, or `very-adaptive` to control region geometry
- `--superpixels-min`, `--superpixels-max`: control SLIC granularity for fine structures
- `--min-region-area`: minimum paintable region area in pixels; if omitted, default is computed from image area
- `--edge-threshold`: max average boundary edge strength for non-tiny merges
- `--lab-merge-threshold`: max LAB distance for non-tiny merges
- `--preserve-detail-regions`: strongly protect high-importance regions from merges, enabled by default
- `--pdf`: export 2-page PDF output
- `--importance-mask`: optional grayscale mask for detail-preservation guidance

## Outputs

The script creates:
- `preview_color.png`: simplified color preview with final palette
- `pbn_lines.png`: white background, thin black boundaries, region numbers
- `palette.png`: swatches with number, RGB, HEX
- `palette.json`: palette list with number, RGB, HEX, LAB
- `regions.json`: region metadata with region id, color number, area, centroid, bbox, and label skip info
- `paint_by_numbers.pdf` when `--pdf` is enabled:
  - page 1: numbered template
  - page 2: palette and instructions

## Algorithm Overview

1. Preprocessing
- Resize while preserving aspect ratio.
- Convert to LAB.
- Lift shadows by nonlinear remap of the L-channel to prevent black blobs.
- Apply edge-preserving denoising with bilateral filtering and optional guided filtering or anisotropic diffusion when available.
- Avoid Gaussian blur as the main smoother.

2. Edge map
- Compute a multi-scale edge map from fine and coarse Canny plus Sobel 3x3 and 5x5.
- Normalize to `[0, 1]`.
- Use edge map in merge decisions to avoid crossing strong boundaries.

3. Superpixels
- Segment with SLIC, typically from 6000 to 30000 segments depending on image area, detail level, and `--superpixel-area-px`.
- Use `--superpixel-shape square` for compact, blockier SLIC regions.
- Use `--superpixel-shape adaptive` for irregular edge-following regions (Felzenszwalb graph segmentation).
- Use `--superpixel-shape very-adaptive` for even more irregular edge-following regions.
- Compute per-superpixel mean LAB, mean RGB, area, neighbors, and shared-boundary edge strength.

4. Palette creation in LAB
- Cluster superpixel mean LAB colors with MiniBatchKMeans.
- Use superpixel area as weight so coherent surfaces influence the palette more than tiny noise.

5. Initial assignment
- Assign each superpixel to the nearest palette color in LAB distance.

6. Region graph and safe merges
- Build connected regions of same-color neighboring superpixels.
- Tiny regions are merged only when conditions are safe:
  - below minimum area
  - meaningful shared border
  - color distance not too large
  - low enough edge strength across shared border
- Merge target uses weighted score:

```text
score =
  LAB_distance * 1.0
  + edge_strength * 2.5
  - shared_border_ratio * 1.5
  + palette_penalty_if_color_changes
```

- Strong-edge crossing is blocked except for extremely tiny regions.
- `--detail-level` raises superpixel density and strengthens edge barriers, so fine features are less likely to collapse.

7. Importance-aware behavior
- If no mask is provided, importance is estimated from face detections if available, high edge-density zones, and a central bias.
- Important areas use smaller local minimum region area and stricter edge thresholds.
- Background merges more aggressively.

8. Morphological cleanup and rendering
- Remove one-pixel artifacts with a majority filter when enabled.
- Keep outlines thin.
- Place numbers via distance transform interior maxima.
- Skip labels for tiny regions and record that in `regions.json`.

## Why LAB Color Space

LAB better matches perceptual color distance than RGB. A Euclidean distance in LAB is more aligned with what humans see as a color difference, so palette assignment and merge gating are more reliable.

## Why Superpixels

Superpixels preserve local boundaries and dramatically reduce graph complexity. Operating at superpixel level avoids noisy pixel-level decisions while keeping meaningful object edges.

## Why Edge-Aware Merging Beats Global Smoothing

Global smoothing can erase boundaries needed for paintable segmentation. Edge-aware merging keeps semantic boundaries by checking edge strength along shared region borders before merging.

## Tuning Guide

- Too many tiny fragments:
  - lower `--detail-level`
  - increase `--superpixel-area-px`
  - lower `--superpixels-max`
  - increase `--min-region-area`
  - decrease `--colors`
  - increase `--merge-iterations`
- Important detail lost:
  - increase `--detail-level`
  - decrease `--superpixel-area-px`
  - increase `--superpixels-max`
  - increase `--colors`
  - reduce `--min-region-area`
  - lower `--edge-threshold` so merges avoid crossing boundaries
- Too many similar shades:
  - reduce `--colors`
  - increase `--lab-merge-threshold` slightly

## Common Failure Modes and Fixes

- Faces get oversimplified:
  - increase `--detail-level`, for example `0.8` to `1.0`
  - provide `--importance-mask` emphasizing face, eyes, and mouth
  - increase `--colors`
- Background remains too noisy:
  - increase `--min-region-area`
  - decrease `--colors`
- Regions with no number text:
  - decrease `--min-number-area`
  - keep `line_width` small to preserve interior space
