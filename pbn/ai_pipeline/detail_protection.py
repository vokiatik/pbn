from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage
from skimage import color

from .print_spec import PrintSpec
from .regions import build_region_records


TRANSITION_MM = 1.2
DIFFICULTY_MULTIPLIERS = {"easy": 2.9, "medium": 5.8, "hard": 11.6}
CONTOUR_SMOOTHING_FACTOR = 1.45
MEANINGFUL_SOURCE_DELTA_E = 2.0
MEANINGFUL_BOUNDARY_EVIDENCE = 0.20
HARD_PROTECTION_EVIDENCE = 0.70


@dataclass(frozen=True)
class DetailProtection:
    mask: np.ndarray
    weight: np.ndarray
    coverage_percent: float
    sha256: str
    transition_source_pixels: int


def detail_contour_tolerance(base_tolerance_mm: float) -> float:
    """Slightly smooth printed contours only when detail protection is active."""
    return base_tolerance_mm * CONTOUR_SMOOTHING_FACTOR


def load_detail_protection(
    pipeline_root: Path,
    source_shape: tuple[int, int],
    print_spec: PrintSpec,
) -> DetailProtection | None:
    path = pipeline_root / "input" / "detail_protection.png"
    if not path.is_file():
        return None
    payload = path.read_bytes()
    with Image.open(path) as image:
        gray = np.asarray(image.convert("L"), dtype=np.uint8)
    if gray.shape != source_shape:
        raise ValueError("detail protection dimensions do not match the reviewed AI image")
    mask = gray >= 128
    mm_per_pixel = source_mm_per_pixel(source_shape, print_spec)
    transition_pixels = max(1, int(np.floor(TRANSITION_MM / max(mm_per_pixel, 1e-9))))
    outside_distance = ndimage.distance_transform_edt(~mask)
    weight = np.clip(1.0 - outside_distance / float(transition_pixels + 1), 0.0, 1.0)
    weight[mask] = 1.0
    return DetailProtection(
        mask=mask,
        weight=weight.astype(np.float32),
        coverage_percent=round(100.0 * float(mask.mean()), 6),
        sha256=hashlib.sha256(payload).hexdigest(),
        transition_source_pixels=transition_pixels,
    )


def source_mm_per_pixel(shape: tuple[int, int], print_spec: PrintSpec) -> float:
    height, width = shape
    content_width, content_height = print_spec.content_mm
    scale = min(content_width / max(1, width), content_height / max(1, height))
    return float(scale)


def advanced_zone(label_map: np.ndarray, protection: DetailProtection) -> np.ndarray:
    expanded = protection.weight > 0
    touched = np.unique(label_map[expanded])
    touched = touched[touched > 0]
    return np.isin(label_map, touched)


def boundary_selection_coverage(
    label_map: np.ndarray,
    weight: np.ndarray,
) -> dict[tuple[int, int], float]:
    maximum = int(label_map.max()) + 1
    totals: dict[tuple[int, int], float] = {}
    counts: dict[tuple[int, int], int] = {}
    for left, right, left_weight, right_weight in (
        (label_map[:, :-1], label_map[:, 1:], weight[:, :-1], weight[:, 1:]),
        (label_map[:-1, :], label_map[1:, :], weight[:-1, :], weight[1:, :]),
    ):
        changed = (left != right) & (left > 0) & (right > 0)
        if not changed.any():
            continue
        low = np.minimum(left[changed], right[changed]).astype(np.int64)
        high = np.maximum(left[changed], right[changed]).astype(np.int64)
        encoded = low * maximum + high
        values = np.maximum(left_weight[changed], right_weight[changed]).astype(np.float64)
        unique, inverse = np.unique(encoded, return_inverse=True)
        sums = np.bincount(inverse, weights=values)
        sizes = np.bincount(inverse)
        for code, total, count in zip(unique, sums, sizes, strict=True):
            pair = (int(code // maximum), int(code % maximum))
            totals[pair] = totals.get(pair, 0.0) + float(total)
            counts[pair] = counts.get(pair, 0) + int(count)
    return {pair: totals[pair] / max(1, counts[pair]) for pair in totals}


def apply_difficulty_protection(
    source_rgb: np.ndarray,
    label_map: np.ndarray,
    boundary_evidence: dict[tuple[int, int], float],
    selection_coverage: dict[tuple[int, int], float],
    difficulty: str,
) -> tuple[
    dict[tuple[int, int], float],
    dict[int, float],
    set[int],
    set[tuple[int, int]],
    dict[str, object],
]:
    multiplier = DIFFICULTY_MULTIPLIERS[difficulty]
    records = build_region_records(label_map, source_rgb, {})
    region_rgb = np.asarray([record.representative_color for record in records], dtype=np.uint8)
    region_lab_values = color.rgb2lab(region_rgb[:, None, :].astype(np.float64) / 255.0)[:, 0, :]
    region_lab = {record.region_id: region_lab_values[index] for index, record in enumerate(records)}
    effective = dict(boundary_evidence)
    region_scores: dict[int, float] = {}
    hard_ids: set[int] = set()
    hard_pair_ids: set[tuple[int, int]] = set()
    selected_pairs = 0
    hard_pairs = 0
    evidence_floor_applied_pairs = 0
    for pair, coverage in selection_coverage.items():
        if coverage <= 0 or pair[0] not in region_lab or pair[1] not in region_lab:
            continue
        source_delta = float(
            color.deltaE_ciede2000(region_lab[pair[0]][None, :], region_lab[pair[1]][None, :])[0]
        )
        original = float(boundary_evidence.get(pair, 0.0))
        meaningful = source_delta >= MEANINGFUL_SOURCE_DELTA_E or original >= MEANINGFUL_BOUNDARY_EVIDENCE
        if not meaningful:
            continue
        selected_pairs += 1
        weighted_coverage = float(np.clip(coverage, 0.0, 1.0))
        multiplied = original * (1.0 + (multiplier - 1.0) * weighted_coverage)
        selected_floor = min(
            HARD_PROTECTION_EVIDENCE,
            MEANINGFUL_BOUNDARY_EVIDENCE * multiplier * weighted_coverage,
        )
        evidence_floor_applied_pairs += int(selected_floor > multiplied)
        value = min(1.0, max(multiplied, selected_floor))
        effective[pair] = value
        region_scores[pair[0]] = max(region_scores.get(pair[0], 0.0), value)
        region_scores[pair[1]] = max(region_scores.get(pair[1], 0.0), value)
        if value >= HARD_PROTECTION_EVIDENCE:
            hard_ids.update(pair)
            hard_pair_ids.add(pair)
            hard_pairs += 1
    return effective, region_scores, hard_ids, hard_pair_ids, {
        "difficulty_multiplier": multiplier,
        "selected_meaningful_boundary_count": selected_pairs,
        "hard_selected_boundary_count": hard_pairs,
        "evidence_floor_applied_boundary_count": evidence_floor_applied_pairs,
    }


def meaningful_selected_pairs(
    source_rgb: np.ndarray,
    label_map: np.ndarray,
    boundary_evidence: dict[tuple[int, int], float],
    selection_coverage: dict[tuple[int, int], float],
) -> set[tuple[int, int]]:
    records = build_region_records(label_map, source_rgb, {})
    rgb = np.asarray([record.representative_color for record in records], dtype=np.uint8)
    labs = color.rgb2lab(rgb[:, None, :].astype(np.float64) / 255.0)[:, 0, :]
    lab_by_id = {record.region_id: labs[index] for index, record in enumerate(records)}
    result: set[tuple[int, int]] = set()
    for pair, coverage in selection_coverage.items():
        if coverage <= 0 or pair[0] not in lab_by_id or pair[1] not in lab_by_id:
            continue
        delta = float(color.deltaE_ciede2000(lab_by_id[pair[0]][None, :], lab_by_id[pair[1]][None, :])[0])
        if delta >= MEANINGFUL_SOURCE_DELTA_E or boundary_evidence.get(pair, 0.0) >= MEANINGFUL_BOUNDARY_EVIDENCE:
            result.add(pair)
    return result


def selected_boundary_mask(
    label_map: np.ndarray,
    meaningful_pairs: set[tuple[int, int]],
) -> np.ndarray:
    result = np.zeros(label_map.shape, dtype=bool)
    for left, right, left_target, right_target in (
        (label_map[:, :-1], label_map[:, 1:], result[:, :-1], result[:, 1:]),
        (label_map[:-1, :], label_map[1:, :], result[:-1, :], result[1:, :]),
    ):
        changed = (left != right) & (left > 0) & (right > 0)
        if not changed.any():
            continue
        coordinates = np.argwhere(changed)
        for y, x in coordinates:
            pair = (min(int(left[y, x]), int(right[y, x])), max(int(left[y, x]), int(right[y, x])))
            if pair in meaningful_pairs:
                left_target[y, x] = True
                right_target[y, x] = True
    return result


def write_protection_trace(path: Path, protection: DetailProtection, metrics: dict[str, object]) -> None:
    payload = {
        "sha256": protection.sha256,
        "coverage_percent": protection.coverage_percent,
        "transition_mm": TRANSITION_MM,
        "transition_source_pixels": protection.transition_source_pixels,
        **metrics,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
