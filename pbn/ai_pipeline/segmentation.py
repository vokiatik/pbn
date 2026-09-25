from __future__ import annotations

import hashlib
import heapq
import json
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage
from skimage import color, segmentation
from skimage.measure import label as label_connected_components

from .io_utils import atomic_write_json, save_label_map_png, save_rgb
from .models import ProcessingDiagnosticError
from .print_spec import PrintSpec
from .regions import build_adjacency, build_region_records, record_to_dict


HARD_PROTECTION_THRESHOLD = 0.70
BUDGET_OVERFLOW_FACTOR = 1.10
PRINTER_FLOOR_AREA_MM2 = 0.5
PRINTER_FLOOR_WIDTH_MM = 0.5
BOUNDARY_SNAP_MAX_MM = 0.6
EASY_EDGE_SCALES = (1.4, 2.8)
DETAIL_EDGE_SCALES = (0.7, 1.4, 2.8)


@dataclass(frozen=True)
class RetryProfile:
    name: str
    region_budget: int
    merge_delta_e: float
    contour_tolerance_mm: float
    minimum_regions: int = 0
    initial_superpixel_count: int | None = None
    segmentation_budget: int | None = None
    boundary_edge_scales: tuple[float, ...] = DETAIL_EDGE_SCALES
    boundary_snap_mm: float = BOUNDARY_SNAP_MAX_MM

    @property
    def initial_superpixels(self) -> int:
        if self.initial_superpixel_count is not None:
            return self.initial_superpixel_count
        return max(1000, min(3000, self.region_budget * 4))


def retry_profiles(print_spec: PrintSpec) -> list[RetryProfile]:
    del print_spec
    return [
        RetryProfile(
            "easy",
            500,
            1.5,
            0.25,
            minimum_regions=250,
            initial_superpixel_count=3000,
            segmentation_budget=1400,
            boundary_edge_scales=EASY_EDGE_SCALES,
        ),
        RetryProfile(
            "medium",
            750,
            0.0,
            0.15,
            minimum_regions=450,
            initial_superpixel_count=9450,
            segmentation_budget=9450,
        ),
        RetryProfile(
            "hard",
            1050,
            0.0,
            0.10,
            minimum_regions=700,
            initial_superpixel_count=9450,
            segmentation_budget=9450,
        ),
    ]


def segment_paint_regions(
    illustration_path: Path,
    output_dir: Path,
    print_spec: PrintSpec,
    profile: RetryProfile,
    min_area_mm2: float = PRINTER_FLOOR_AREA_MM2,
    min_width_mm: float = PRINTER_FLOOR_WIDTH_MM,
    min_label_pocket_mm: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, list[dict[str, object]]]:
    labels, rgb = create_slic_atoms(illustration_path, profile)
    graph_merged, protected_edge_mask, graph_log = _merge_region_graph(
        rgb,
        labels,
        profile.segmentation_budget or profile.region_budget,
        profile.merge_delta_e,
    )
    cleaned, cleanup_log = _enforce_physical_constraints(
        rgb,
        graph_merged,
        print_spec,
        protected_edge_mask,
        min_area_mm2=min_area_mm2,
        min_width_mm=min_width_mm,
        min_label_pocket_mm=min_label_pocket_mm,
    )
    edge_strength = _source_edge_strength(rgb, profile.boundary_edge_scales)
    final_adjacency, final_shared = _adjacency_with_shared_boundary(cleaned)
    final_boundary_protection = _boundary_protection_scores(
        rgb,
        cleaned,
        final_adjacency,
        final_shared,
    )
    protected_edge_mask = _protected_edge_mask(cleaned, final_boundary_protection)
    final_protection = _region_protection_scores(rgb, cleaned)
    protected_ids = _region_ids_touching_mask(cleaned, protected_edge_mask)
    protected_ids.update(
        region_id
        for region_id, score in final_protection.items()
        if score >= HARD_PROTECTION_THRESHOLD
    )
    geometry_log = [*graph_log, *cleanup_log]
    geometry_log.append(
        {
            "operation": "protection_summary",
            "protection_threshold": HARD_PROTECTION_THRESHOLD,
            "protected_region_count": len(protected_ids),
            "protected_region_ids": sorted(protected_ids),
            "prefilled_detail_region_ids": [],
            "region_protection_scores": {str(key): round(value, 6) for key, value in final_protection.items()},
        }
    )

    adjacency = build_adjacency(cleaned)
    records = build_region_records(cleaned, rgb, adjacency)
    output_dir.mkdir(parents=True, exist_ok=True)
    np.save(output_dir / "region_id_map.npy", cleaned)
    np.save(output_dir / "protection_mask.npy", protected_edge_mask.astype(np.uint8))
    save_label_map_png(labels, output_dir / "slico_map.png")
    save_label_map_png(graph_merged, output_dir / "graph_merged_map.png")
    save_label_map_png(cleaned, output_dir / "cleaned_map.png")
    save_label_map_png(cleaned, output_dir / "regularized_map.png")
    save_label_map_png(cleaned, output_dir / "initial_region_map.png")
    edge_preview = np.rint(np.clip(edge_strength, 0.0, 1.0) * 255.0).astype(np.uint8)
    save_rgb(output_dir / "boundary_strength.png", np.repeat(edge_preview[..., None], 3, axis=2))
    protection_rgb = np.where(protected_edge_mask[..., None], np.asarray([220, 45, 45], dtype=np.uint8), 255)
    save_rgb(output_dir / "protection_map.png", protection_rgb)
    atomic_write_json(output_dir / "regions.json", [record_to_dict(record) for record in records])
    atomic_write_json(
        output_dir / "adjacency.json",
        {str(region_id): sorted(neighbours) for region_id, neighbours in adjacency.items()},
    )
    atomic_write_json(output_dir / "merge_log.json", geometry_log)
    return cleaned, rgb, geometry_log


def create_slic_atoms(
    illustration_path: Path,
    profile: RetryProfile,
) -> tuple[np.ndarray, np.ndarray]:
    """Return the immutable raw SLIC atoms used by the hybrid geometry path."""
    with Image.open(illustration_path) as image:
        rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)

    labels = segmentation.slic(
        rgb,
        n_segments=profile.initial_superpixels,
        compactness=10.0,
        sigma=0.6,
        start_label=1,
        enforce_connectivity=True,
        slic_zero=True,
        convert2lab=True,
        channel_axis=-1,
    ).astype(np.int32)
    return labels, rgb


def create_structural_atoms(
    illustration_path: Path,
    analysis_dir: Path,
    print_spec: PrintSpec | None = None,
) -> tuple[np.ndarray, np.ndarray, dict[str, object]]:
    """Cache connected, source-edge-guided atoms independently of PBN settings.

    Felzenszwalb's local graph criterion follows the actual colour boundaries of
    the reviewed illustration. In particular, a small high-contrast mark is not
    forced to share a regular SLIC tile with its surroundings.
    """
    with Image.open(illustration_path) as image:
        rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    mm_per_pixel = _source_mm_per_pixel(rgb.shape[:2], print_spec or PrintSpec())
    atom_floor_pixels = max(1, int(np.ceil(0.5 / mm_per_pixel**2)))
    digest = hashlib.sha256(rgb.tobytes()).hexdigest()
    manifest_path = analysis_dir / "manifest.json"
    labels_path = analysis_dir / "source_atoms.npy"
    if manifest_path.is_file() and labels_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (isinstance(manifest, dict)
                    and manifest.get("source_sha256") == digest and manifest.get("version") == 7
                    and manifest.get("atom_floor_pixels") == atom_floor_pixels):
                labels = np.load(labels_path, allow_pickle=False)
                if labels.shape == rgb.shape[:2]:
                    return labels, rgb, {**manifest, "cache_hit": True}
        except (ValueError, OSError, json.JSONDecodeError):
            pass
    start = time.perf_counter()
    # The reviewed image already defines colour boundaries. Blurring it here
    # creates extra bands along those boundaries, often joined diagonally.
    # Analyze the source directly and leave paintability merges to the graph.
    labels = segmentation.felzenszwalb(
        rgb,
        scale=400.0,
        sigma=0.0,
        min_size=atom_floor_pixels,
        channel_axis=-1,
    ).astype(np.int32) + 1
    # Felzenszwalb uses diagonal neighbours. Every paint region must instead
    # have one four-connected component so its area, width and number apply
    # to a single paintable shape. Split before graph costs are calculated.
    labels = label_connected_components(labels, connectivity=1, background=0).astype(np.int32)
    analysis_dir.mkdir(parents=True, exist_ok=True)
    np.save(labels_path, labels)
    manifest = {
        "version": 7,
        "source_sha256": digest,
        "atom_floor_pixels": atom_floor_pixels,
        "initial_region_count": int(labels.max()),
        "analysis_seconds": round(time.perf_counter() - start, 3),
    }
    atomic_write_json(manifest_path, manifest)
    return labels, rgb, {**manifest, "cache_hit": False}


def _merge_region_graph(
    rgb: np.ndarray,
    label_map: np.ndarray,
    region_budget: int,
    merge_delta_e: float,
) -> tuple[np.ndarray, np.ndarray, list[dict[str, object]]]:
    lab = color.rgb2lab(rgb)
    max_label = int(label_map.max())
    area = np.bincount(label_map.ravel(), minlength=max_label + 1).astype(np.float64)
    sums = np.zeros((max_label + 1, 3), dtype=np.float64)
    for channel in range(3):
        sums[:, channel] = np.bincount(
            label_map.ravel(),
            weights=lab[..., channel].ravel(),
            minlength=max_label + 1,
        )

    adjacency, shared = _adjacency_with_shared_boundary(label_map)
    protection = _boundary_protection_scores(rgb, label_map, adjacency, shared)
    protected_edge_mask = _protected_edge_mask(label_map, protection)
    parent = np.arange(max_label + 1, dtype=np.int32)
    active = np.ones(max_label + 1, dtype=bool)
    active[0] = False
    versions = np.zeros(max_label + 1, dtype=np.int32)
    heap: list[tuple[float, int, int, int, int]] = []

    def mean(region_id: int) -> np.ndarray:
        return sums[region_id] / max(area[region_id], 1.0)

    def score(left: int, right: int) -> float:
        delta = float(color.deltaE_ciede2000(mean(left)[None, :], mean(right)[None, :])[0])
        boundary = shared.get(_pair(left, right), 1)
        contact = min(1.0, boundary / max(1.0, np.sqrt(min(area[left], area[right]))))
        edge_protection = protection.get(_pair(left, right), 0.0)
        return delta / (1.0 + 0.35 * contact) + 12.0 * edge_protection

    def push(left: int, right: int) -> None:
        if left == right or not active[left] or not active[right]:
            return
        a, b = _pair(left, right)
        heapq.heappush(heap, (score(a, b), a, b, int(versions[a]), int(versions[b])))

    for left, neighbours in adjacency.items():
        for right in neighbours:
            if left < right:
                push(left, right)

    region_count = max_label
    budget_limit = int(np.ceil(region_budget * BUDGET_OVERFLOW_FACTOR))
    protected_vetoes = 0
    merge_count = 0
    merge_reason_counts = {"perceptual_similarity": 0, "budget_pressure": 0}
    maximum_merged_protection_score = 0.0
    while heap:
        edge_score, left, right, left_version, right_version = heapq.heappop(heap)
        if not active[left] or not active[right]:
            continue
        if versions[left] != left_version or versions[right] != right_version:
            continue
        pair = _pair(left, right)
        if protection.get(pair, 0.0) >= HARD_PROTECTION_THRESHOLD:
            protected_vetoes += 1
            continue
        if edge_score > merge_delta_e and region_count <= budget_limit:
            break

        merge_reason = "budget_pressure" if region_count > budget_limit else "perceptual_similarity"
        merge_reason_counts[merge_reason] += 1
        maximum_merged_protection_score = max(
            maximum_merged_protection_score,
            protection.get(pair, 0.0),
        )

        if area[left] > area[right] or (area[left] == area[right] and left < right):
            target, source = left, right
        else:
            target, source = right, left
        parent[source] = target
        active[source] = False
        area[target] += area[source]
        sums[target] += sums[source]
        versions[target] += 1

        source_neighbours = set(adjacency.get(source, set()))
        target_neighbours = set(adjacency.get(target, set()))
        combined = (source_neighbours | target_neighbours) - {source, target}
        adjacency[target] = combined
        adjacency[source] = set()
        for neighbour in combined:
            adjacency[neighbour].discard(source)
            adjacency[neighbour].discard(target)
            adjacency[neighbour].add(target)
            target_pair = _pair(target, neighbour)
            source_pair = _pair(source, neighbour)
            shared[target_pair] = shared.get(target_pair, 0) + shared.get(source_pair, 0)
            protection[target_pair] = max(
                protection.get(target_pair, 0.0),
                protection.get(source_pair, 0.0),
            )
            push(target, neighbour)
        region_count -= 1
        merge_count += 1

    roots = np.arange(max_label + 1, dtype=np.int32)
    for region_id in range(1, max_label + 1):
        root = int(region_id)
        while parent[root] != root:
            root = int(parent[root])
        roots[region_id] = root
    merged = _compact_labels(roots[label_map])
    graph_log = [
        {
            "operation": "graph_merge_summary",
            "initial_region_count": max_label,
            "final_region_count": int(np.unique(merged[merged > 0]).size),
            "requested_region_budget": region_budget,
            "allowed_region_budget": budget_limit,
            "budget_overflow_percent": round(
                max(0.0, 100.0 * (int(np.unique(merged[merged > 0]).size) - region_budget) / max(1, region_budget)),
                6,
            ),
            "merge_count": merge_count,
            "merge_reason_counts": merge_reason_counts,
            "maximum_merged_protection_score": round(maximum_merged_protection_score, 6),
            "protected_merge_veto_count": protected_vetoes,
            "budget_overflow": int(np.unique(merged[merged > 0]).size) > region_budget,
            "hard_protection_threshold": HARD_PROTECTION_THRESHOLD,
        }
    ]
    return merged, protected_edge_mask, graph_log


def _enforce_physical_constraints(
    rgb: np.ndarray,
    label_map: np.ndarray,
    print_spec: PrintSpec,
    protected_edge_mask: np.ndarray,
    min_area_mm2: float,
    min_width_mm: float,
    min_label_pocket_mm: float,
) -> tuple[np.ndarray, list[dict[str, object]]]:
    cleaned = label_map.copy()
    modifications: list[dict[str, object]] = []
    page_width, page_height = print_spec.page_px
    margin = int(round(print_spec.margin_mm / 25.4 * print_spec.dpi))
    scale = min(
        (page_width - 2 * margin) / cleaned.shape[1],
        (page_height - 2 * margin) / cleaned.shape[0],
    )
    mm_per_pixel = scale * 25.4 / print_spec.dpi
    pixel_area_mm2 = mm_per_pixel**2

    for _ in range(50):
        adjacency = build_adjacency(cleaned)
        records = build_region_records(cleaned, rgb, adjacency)
        protection_by_id = _region_protection_scores(rgb, cleaned)
        hard_protected_ids = _region_ids_touching_mask(cleaned, protected_edge_mask)
        boundary_protection = _boundary_protection_scores(
            rgb,
            cleaned,
            adjacency,
            _adjacency_with_shared_boundary(cleaned)[1],
        )
        for pair in _protected_pairs_from_mask(cleaned, protected_edge_mask):
            boundary_protection[pair] = 1.0
        record_by_id = {record.region_id: record for record in records}
        pocket_by_id = {
            record.region_id: _label_pocket_mm(cleaned, record.region_id, record.bbox, mm_per_pixel)
            for record in records
        }
        invalid = [
            record
            for record in records
            if record.area * pixel_area_mm2 < min_area_mm2
            or record.estimated_thickness * mm_per_pixel < min_width_mm
        ]
        retained_protected: set[int] = set()
        for record in sorted(invalid, key=lambda item: (-protection_by_id.get(item.region_id, 0.0), item.area, item.region_id)):
            area_mm2 = record.area * pixel_area_mm2
            width_mm = record.estimated_thickness * mm_per_pixel
            is_protected = (
                record.region_id in hard_protected_ids
                or protection_by_id.get(record.region_id, 0.0) >= HARD_PROTECTION_THRESHOLD
            )
            if not is_protected or area_mm2 < PRINTER_FLOOR_AREA_MM2 or width_mm < PRINTER_FLOOR_WIDTH_MM:
                continue
            retained_protected.add(record.region_id)
        if not invalid:
            break

        remap = np.arange(int(cleaned.max()) + 1, dtype=np.int32)
        changed = False
        for record in sorted(invalid, key=lambda item: (item.area, item.region_id)):
            if remap[record.region_id] != record.region_id:
                continue
            area_mm2 = record.area * pixel_area_mm2
            width_mm = record.estimated_thickness * mm_per_pixel
            if (
                record.region_id in retained_protected
            ):
                continue
            neighbours = [record_by_id[n] for n in record.neighbours if n in record_by_id]
            candidates = [
                neighbour
                for neighbour in neighbours
                if remap[neighbour.region_id] == neighbour.region_id
                and (neighbour.area > record.area
                or (neighbour.area == record.area and neighbour.region_id < record.region_id)
                )
                and boundary_protection.get(_pair(record.region_id, neighbour.region_id), 0.0) < HARD_PROTECTION_THRESHOLD
            ]
            expand_source = False
            if not candidates:
                candidates = [
                    neighbour
                    for neighbour in neighbours
                    if remap[neighbour.region_id] == neighbour.region_id
                    and (
                        area_mm2 < PRINTER_FLOOR_AREA_MM2
                        or width_mm < PRINTER_FLOOR_WIDTH_MM
                        or boundary_protection.get(_pair(record.region_id, neighbour.region_id), 0.0) < HARD_PROTECTION_THRESHOLD
                    )
                ]
                expand_source = bool(candidates)
            if not candidates:
                continue
            source_lab = color.rgb2lab(np.asarray(record.representative_color, dtype=np.uint8)[None, None, :] / 255.0)[0, 0]

            def candidate_score(candidate) -> tuple[float, int]:
                candidate_lab = color.rgb2lab(np.asarray(candidate.representative_color, dtype=np.uint8)[None, None, :] / 255.0)[0, 0]
                delta = float(color.deltaE_ciede2000(source_lab[None, :], candidate_lab[None, :])[0])
                normalized_delta = min(1.0, delta / 20.0)
                edge = boundary_protection.get(_pair(record.region_id, candidate.region_id), 0.0)
                topology_loss = 1.0 if len(record.neighbours) <= 2 else 0.0
                merged_area = max(1, record.area + candidate.area)
                shape_loss = min(1.0, abs(record.area - candidate.area) / merged_area)
                loss = 0.45 * normalized_delta + 0.30 * edge + 0.15 * topology_loss + 0.10 * shape_loss
                return loss, -candidate.area

            target = min(candidates, key=candidate_score)
            if expand_source:
                remap[target.region_id] = record.region_id
                merged_region_id, target_region_id = target.region_id, record.region_id
            else:
                remap[record.region_id] = target.region_id
                merged_region_id, target_region_id = record.region_id, target.region_id
            modifications.append(
                {
                    "operation": "expanded_unpaintable_region" if expand_source else "merged_unpaintable_region",
                    "region_id": merged_region_id,
                    "target_region_id": target_region_id,
                    "area_pixels": record.area,
                    "area_mm2": area_mm2,
                    "estimated_width_mm": record.estimated_thickness * mm_per_pixel,
                    "label_pocket_mm": pocket_by_id[record.region_id],
                    "protection_score": protection_by_id.get(record.region_id, 0.0),
                    "crossed_protected_boundary": boundary_protection.get(
                        _pair(record.region_id, target.region_id),
                        0.0,
                    ) >= HARD_PROTECTION_THRESHOLD,
                    "reason": (
                        "below_printer_floor"
                        if area_mm2 < PRINTER_FLOOR_AREA_MM2 or width_mm < PRINTER_FLOOR_WIDTH_MM
                        else "ordinary_region_below_paintability_limits"
                    ),
                }
            )
            changed = True
        if not changed:
            break
        for region_id in range(1, len(remap)):
            seen: set[int] = set()
            target = region_id
            while remap[target] != target and target not in seen:
                seen.add(target)
                target = int(remap[target])
            remap[region_id] = target
        cleaned = _compact_labels(remap[cleaned])
    return cleaned, modifications


def region_boundary_evidence(rgb: np.ndarray, label_map: np.ndarray) -> dict[tuple[int, int], float]:
    """Return deterministic multiscale evidence for every current region boundary."""
    adjacency, shared = _adjacency_with_shared_boundary(label_map)
    return _boundary_protection_scores(rgb, label_map, adjacency, shared)


def _align_boundaries_to_source(
    rgb: np.ndarray,
    label_map: np.ndarray,
    print_spec: PrintSpec,
    edge_scales: tuple[float, ...],
    maximum_snap_mm: float = BOUNDARY_SNAP_MAX_MM,
    min_area_mm2: float = PRINTER_FLOOR_AREA_MM2,
    min_width_mm: float = PRINTER_FLOOR_WIDTH_MM,
    prepared_edge_strength: np.ndarray | None = None,
    prepared_source_lab: np.ndarray | None = None,
) -> tuple[np.ndarray, dict[str, object], np.ndarray]:
    """Snap boundaries to source evidence without changing the region topology."""
    source_edge_strength = (
        prepared_edge_strength
        if prepared_edge_strength is not None
        else _source_edge_strength(rgb, edge_scales)
    )
    original = label_map.astype(np.int32, copy=True)
    original_boundary = _boundary_mask(original)
    mm_per_pixel = _source_mm_per_pixel(original.shape, print_spec)
    maximum_radius = max(0, int(np.floor(maximum_snap_mm / max(mm_per_pixel, 1e-9))))
    baseline_alignment = _boundary_alignment_score(source_edge_strength, original_boundary)
    source_lab = (
        prepared_source_lab
        if prepared_source_lab is not None
        else color.rgb2lab(rgb.astype(np.float64) / 255.0)
    )
    median_lut = _region_median_lab_lut(source_lab, original)
    baseline_reconstruction = _region_reconstruction_delta_e(source_lab, original, median_lut)
    original_pairs, anchors = _adjacency_pairs_and_anchors(original, source_edge_strength)
    original_components = _component_counts(original)
    original_ids = set(int(value) for value in np.unique(original) if int(value) > 0)
    floor_sensitive_ids = _printer_floor_sensitive_region_ids(
        original,
        rgb,
        print_spec,
        min_area_mm2,
        min_width_mm,
        maximum_radius,
    )
    baseline_floor_violations = _printer_floor_violations(
        original,
        rgb,
        print_spec,
        min_area_mm2,
        min_width_mm,
    )
    accepted: list[tuple[np.ndarray, dict[str, object]]] = []
    rejected: list[dict[str, object]] = []

    for radius in range(maximum_radius, 0, -1):
        proposal = _watershed_boundary_proposal(
            original,
            source_edge_strength,
            radius,
            anchors,
            floor_sensitive_ids,
        )
        candidate, projection_passes = _project_watershed_proposal(
            original,
            proposal,
            source_lab,
            median_lut,
            original_pairs,
            floor_sensitive_ids,
        )
        changed_mask = candidate != original
        changed_count = int(np.count_nonzero(changed_mask))
        candidate_boundary = _boundary_mask(candidate)
        alignment = _boundary_alignment_score(source_edge_strength, candidate_boundary)
        reconstruction = _region_reconstruction_delta_e(source_lab, candidate, median_lut)
        affected_ids = {
            int(value)
            for value in np.unique(np.concatenate((original[changed_mask], candidate[changed_mask])))
            if int(value) > 0
        }
        reasons: list[str] = []
        candidate_pairs = _adjacency_pairs(candidate)
        active_ids = set(int(value) for value in np.unique(candidate) if int(value) > 0)
        topology_preserved = (
            active_ids == original_ids
            and candidate_pairs == original_pairs
            and _component_counts(candidate) == original_components
            and _hole_counts(candidate, affected_ids) == _hole_counts(original, affected_ids)
        )
        if not topology_preserved:
            reasons.append("topology_changed")
        printer_floor_violations = _printer_floor_violations(
            candidate,
            rgb,
            print_spec,
            min_area_mm2,
            min_width_mm,
        )
        if printer_floor_violations:
            reasons.append("printer_floor_violated")
        if alignment + 1e-9 < baseline_alignment:
            reasons.append("source_edge_support_decreased")
        if reconstruction > baseline_reconstruction + 0.05 + 1e-9:
            reasons.append("geometry_reconstruction_worsened")
        if changed_count == 0 and not np.array_equal(proposal, original):
            reasons.append("no_safe_beneficial_movement")

        metrics = {
            "radius_source_pixels": radius,
            "actual_snap_radius_mm": round(radius * mm_per_pixel, 6),
            "changed_pixel_count": changed_count,
            "changed_pixel_percent": round(100.0 * changed_count / max(1, original.size), 6),
            "boundary_length_before": _boundary_length(original),
            "boundary_length_after": _boundary_length(candidate),
            "source_edge_support_before": round(baseline_alignment, 6),
            "source_edge_support_after": round(alignment, 6),
            "source_edge_alignment_gain": round(alignment - baseline_alignment, 6),
            "geometry_reconstruction_delta_e_before": round(baseline_reconstruction, 6),
            "geometry_reconstruction_delta_e_after": round(reconstruction, 6),
            "geometry_reconstruction_delta_e_change": round(reconstruction - baseline_reconstruction, 6),
            "topology_preserved": topology_preserved,
            "projection_passes": projection_passes,
            "printer_floor_frozen_region_count": len(floor_sensitive_ids),
            "printer_floor_violations": printer_floor_violations,
            "rejection_reasons": reasons,
        }
        if reasons:
            rejected.append(metrics)
        else:
            accepted.append((candidate, metrics))

    if not accepted:
        if not baseline_floor_violations:
            baseline_boundary_length = _boundary_length(original)
            log = {
                "operation": "source_edge_alignment_summary",
                "status": "skipped",
                "reason": "below_source_pixel_size" if maximum_radius == 0 else "all_snap_proposals_rejected",
                "requested_snap_radius_mm": maximum_snap_mm,
                "maximum_radius_source_pixels": maximum_radius,
                "edge_scales_source_pixels": list(edge_scales),
                "radius_source_pixels": 0,
                "actual_snap_radius_mm": 0.0,
                "changed_pixel_count": 0,
                "changed_pixel_percent": 0.0,
                "boundary_length_before": baseline_boundary_length,
                "boundary_length_after": baseline_boundary_length,
                "source_edge_support_before": round(baseline_alignment, 6),
                "source_edge_support_after": round(baseline_alignment, 6),
                "source_edge_alignment_gain": 0.0,
                "geometry_reconstruction_delta_e_before": round(baseline_reconstruction, 6),
                "geometry_reconstruction_delta_e_after": round(baseline_reconstruction, 6),
                "geometry_reconstruction_delta_e_change": 0.0,
                "topology_preserved": True,
                "projection_passes": 0,
                "printer_floor_frozen_region_count": len(floor_sensitive_ids),
                "printer_floor_violations": [],
                "rejection_reasons": [],
                "evaluated_radius_count": maximum_radius,
                "rejected_radius_count": len(rejected),
                "rejected_radii": rejected,
            }
            return original, log, source_edge_strength

        reason_codes = sorted(
            {
                str(reason)
                for item in rejected
                for reason in item.get("rejection_reasons", [])
            }
        )
        affected_region_ids = sorted(
            {
                int(violation["region_id"])
                for violation in baseline_floor_violations
                if isinstance(violation, dict) and isinstance(violation.get("region_id"), int)
            }
        )
        raise ProcessingDiagnosticError(
            "source-edge alignment could not preserve topology and printability"
            + (f": {', '.join(reason_codes)}" if reason_codes else ""),
            {
                "total_region_count": len(original_ids),
                "affected_region_ids": affected_region_ids,
                "baseline_printer_floor_violations": baseline_floor_violations,
                "rejected_radius_count": len(rejected),
                "rejected_radii": rejected,
            },
            diagnostic_region_map=original,
        )

    selected, selected_metrics = max(
        accepted,
        key=lambda item: (
            float(item[1]["source_edge_support_after"]),
            -float(item[1]["geometry_reconstruction_delta_e_after"]),
            -int(item[1]["changed_pixel_count"]),
        ),
    )
    log = {
        "operation": "source_edge_alignment_summary",
        "status": "pass",
        "requested_snap_radius_mm": maximum_snap_mm,
        "maximum_radius_source_pixels": maximum_radius,
        "edge_scales_source_pixels": list(edge_scales),
        **selected_metrics,
        "evaluated_radius_count": maximum_radius,
        "rejected_radius_count": len(rejected),
        "rejected_radii": rejected,
    }
    return selected, log, source_edge_strength


def _source_edge_strength(rgb: np.ndarray, edge_scales: tuple[float, ...]) -> np.ndarray:
    lab = color.rgb2lab(rgb.astype(np.float64) / 255.0).astype(np.float32)
    normalized: list[np.ndarray] = []
    for sigma in edge_scales:
        smoothed = cv2.GaussianBlur(lab, (0, 0), float(sigma)) if sigma > 0 else lab
        gx = cv2.Scharr(smoothed, cv2.CV_32F, 1, 0)
        gy = cv2.Scharr(smoothed, cv2.CV_32F, 0, 1)
        magnitude = np.sqrt(np.sum(gx * gx + gy * gy, axis=2))
        scale = float(np.percentile(magnitude, 99.5))
        normalized.append(np.clip(magnitude / max(scale, 1e-9), 0.0, 1.0))
    if not normalized:
        return np.zeros(rgb.shape[:2], dtype=np.float32)
    stack = np.stack(normalized, axis=0)
    return (0.5 * np.max(stack, axis=0) + 0.5 * np.median(stack, axis=0)).astype(np.float32)


def _watershed_boundary_proposal(
    label_map: np.ndarray,
    edge_strength: np.ndarray,
    radius: int,
    anchors: list[tuple[int, int, int]],
    frozen_region_ids: set[int],
) -> np.ndarray:
    boundary = _boundary_mask(label_map)
    distance = ndimage.distance_transform_edt(~boundary)
    movable = distance <= radius
    if frozen_region_ids:
        movable[np.isin(label_map, np.fromiter(sorted(frozen_region_ids), dtype=np.int32))] = False
    for orientation, y, x in anchors:
        movable[y, x] = False
        if orientation == 0:
            movable[y, x + 1] = False
        else:
            movable[y + 1, x] = False
    markers = label_map.copy()
    markers[movable] = 0
    marker_counts = np.bincount(markers.ravel(), minlength=int(label_map.max()) + 1)
    objects = ndimage.find_objects(label_map)
    for region_id, region_slice in enumerate(objects, start=1):
        if region_slice is None or marker_counts[region_id] > 0:
            continue
        local_mask = label_map[region_slice] == region_id
        local_distance = np.where(local_mask, distance[region_slice], -1.0)
        local_y, local_x = np.unravel_index(int(np.argmax(local_distance)), local_distance.shape)
        y = int(region_slice[0].start or 0) + int(local_y)
        x = int(region_slice[1].start or 0) + int(local_x)
        markers[y, x] = region_id
    return segmentation.watershed(
        edge_strength,
        markers=markers,
        mask=np.ones(label_map.shape, dtype=bool),
        watershed_line=False,
    ).astype(np.int32)


def _project_watershed_proposal(
    original: np.ndarray,
    proposal: np.ndarray,
    source_lab: np.ndarray,
    median_lut: np.ndarray,
    allowed_pairs: set[tuple[int, int]],
    frozen_region_ids: set[int],
    maximum_passes: int = 8,
) -> tuple[np.ndarray, int]:
    candidate = original.copy()
    coords = np.argwhere(proposal != original)
    if not len(coords):
        return candidate, 0
    yy, xx = coords[:, 0], coords[:, 1]
    source_values = source_lab[yy, xx]
    original_error = color.deltaE_ciede2000(source_values, median_lut[original[yy, xx]])
    target_error = color.deltaE_ciede2000(source_values, median_lut[proposal[yy, xx]])
    benefit = original_error - target_error
    order = np.lexsort((xx, yy, -benefit))
    ordered = coords[order]
    completed_passes = 0
    for pass_index in range(maximum_passes):
        changed = 0
        iterable = ordered if pass_index % 2 == 0 else ordered[::-1]
        for y_value, x_value in iterable:
            y, x = int(y_value), int(x_value)
            target = int(proposal[y, x])
            source = int(candidate[y, x])
            if (
                source == target
                or source in frozen_region_ids
                or target in frozen_region_ids
                or _pair(source, target) not in allowed_pairs
            ):
                continue
            if _is_topology_safe_relabel(candidate, y, x, target, allowed_pairs):
                candidate[y, x] = target
                changed += 1
        completed_passes += 1
        if not changed:
            break
    return candidate, completed_passes


def _is_topology_safe_relabel(
    label_map: np.ndarray,
    y: int,
    x: int,
    target: int,
    allowed_pairs: set[tuple[int, int]],
) -> bool:
    top, bottom = max(0, y - 1), min(label_map.shape[0], y + 2)
    left, right = max(0, x - 1), min(label_map.shape[1], x + 2)
    local = label_map[top:bottom, left:right]
    local_y, local_x = y - top, x - left
    source = int(label_map[y, x])
    target_is_connected = False
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        yy, xx = local_y + dy, local_x + dx
        if not (0 <= yy < local.shape[0] and 0 <= xx < local.shape[1]):
            continue
        neighbour = int(local[yy, xx])
        if neighbour == target:
            target_is_connected = True
        elif _pair(target, neighbour) not in allowed_pairs:
            return False
    if not target_is_connected:
        return False
    source_mask = (local == source).astype(np.uint8)
    source_mask[local_y, local_x] = 0
    component_count, _ = cv2.connectedComponents(source_mask, connectivity=4)
    return component_count <= 2


def _adjacency_pairs_and_anchors(
    label_map: np.ndarray,
    edge_strength: np.ndarray,
) -> tuple[set[tuple[int, int]], list[tuple[int, int, int]]]:
    maximum = int(label_map.max()) + 1
    keys_parts: list[np.ndarray] = []
    scores_parts: list[np.ndarray] = []
    orientations: list[np.ndarray] = []
    ys_parts: list[np.ndarray] = []
    xs_parts: list[np.ndarray] = []
    for orientation, (left, right) in enumerate(
        ((label_map[:, :-1], label_map[:, 1:]), (label_map[:-1, :], label_map[1:, :]))
    ):
        ys, xs = np.nonzero(left != right)
        if not len(ys):
            continue
        low = np.minimum(left[ys, xs], right[ys, xs]).astype(np.int64)
        high = np.maximum(left[ys, xs], right[ys, xs]).astype(np.int64)
        keys_parts.append(low * maximum + high)
        if orientation == 0:
            scores = np.maximum(edge_strength[ys, xs], edge_strength[ys, xs + 1])
        else:
            scores = np.maximum(edge_strength[ys, xs], edge_strength[ys + 1, xs])
        scores_parts.append(scores)
        orientations.append(np.full(len(ys), orientation, dtype=np.int8))
        ys_parts.append(ys.astype(np.int32))
        xs_parts.append(xs.astype(np.int32))
    if not keys_parts:
        return set(), []
    keys = np.concatenate(keys_parts)
    scores = np.concatenate(scores_parts)
    orientation_values = np.concatenate(orientations)
    ys = np.concatenate(ys_parts)
    xs = np.concatenate(xs_parts)
    order = np.lexsort((orientation_values, xs, ys, -scores, keys))
    sorted_keys = keys[order]
    first = np.r_[True, sorted_keys[1:] != sorted_keys[:-1]]
    selected = order[first]
    pairs = {
        (int(key // maximum), int(key % maximum))
        for key in sorted_keys[first]
    }
    anchors = [
        (int(orientation_values[index]), int(ys[index]), int(xs[index]))
        for index in selected
    ]
    return pairs, anchors


def _adjacency_pairs(label_map: np.ndarray) -> set[tuple[int, int]]:
    return {
        _pair(region_id, neighbour)
        for region_id, neighbours in build_adjacency(label_map).items()
        for neighbour in neighbours
        if region_id < neighbour
    }


def _boundary_mask(label_map: np.ndarray) -> np.ndarray:
    boundary = np.zeros(label_map.shape, dtype=bool)
    horizontal = label_map[:, 1:] != label_map[:, :-1]
    boundary[:, 1:] |= horizontal
    boundary[:, :-1] |= horizontal
    vertical = label_map[1:, :] != label_map[:-1, :]
    boundary[1:, :] |= vertical
    boundary[:-1, :] |= vertical
    return boundary


def _boundary_alignment_score(edge_strength: np.ndarray, boundary_mask: np.ndarray) -> float:
    return float(np.mean(edge_strength[boundary_mask])) if np.any(boundary_mask) else 1.0


def _boundary_length(label_map: np.ndarray) -> int:
    return int(
        np.count_nonzero(label_map[:, 1:] != label_map[:, :-1])
        + np.count_nonzero(label_map[1:, :] != label_map[:-1, :])
    )


def _source_mm_per_pixel(shape: tuple[int, int], print_spec: PrintSpec) -> float:
    page_width, page_height = print_spec.page_px
    margin = int(round(print_spec.margin_mm / 25.4 * print_spec.dpi))
    scale = min((page_width - 2 * margin) / shape[1], (page_height - 2 * margin) / shape[0])
    return scale * 25.4 / print_spec.dpi


def _region_median_lab_lut(source_lab: np.ndarray, label_map: np.ndarray) -> np.ndarray:
    result = np.zeros((int(label_map.max()) + 1, 3), dtype=np.float64)
    for region_id, region_slice in enumerate(ndimage.find_objects(label_map), start=1):
        if region_slice is None:
            continue
        mask = label_map[region_slice] == region_id
        result[region_id] = np.median(source_lab[region_slice][mask], axis=0)
    return result


def _region_reconstruction_delta_e(
    source_lab: np.ndarray,
    label_map: np.ndarray,
    median_lut: np.ndarray,
) -> float:
    return float(np.mean(color.deltaE_ciede2000(source_lab, median_lut[label_map])))


def _component_counts(label_map: np.ndarray) -> dict[int, int]:
    component_map = label_connected_components(label_map, connectivity=1, background=0)
    component_ids, first_indices = np.unique(component_map.ravel(), return_index=True)
    source_ids = label_map.ravel()[first_indices]
    counts = np.bincount(source_ids[component_ids > 0], minlength=int(label_map.max()) + 1)
    return {region_id: int(counts[region_id]) for region_id in range(1, len(counts))}


def _hole_counts(label_map: np.ndarray, region_ids: set[int]) -> dict[int, int]:
    if not region_ids:
        return {}
    objects = ndimage.find_objects(label_map)
    result: dict[int, int] = {}
    structure = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=np.uint8)
    for region_id in sorted(region_ids):
        region_slice = objects[region_id - 1] if region_id <= len(objects) else None
        if region_slice is None:
            result[region_id] = -1
            continue
        mask = label_map[region_slice] == region_id
        holes = ndimage.binary_fill_holes(mask) & ~mask
        _, count = ndimage.label(holes, structure=structure)
        result[region_id] = int(count)
    return result


def _meets_printer_floor(
    label_map: np.ndarray,
    rgb: np.ndarray,
    print_spec: PrintSpec,
    min_area_mm2: float,
    min_width_mm: float,
) -> bool:
    return not _printer_floor_violations(
        label_map,
        rgb,
        print_spec,
        min_area_mm2,
        min_width_mm,
    )


def _printer_floor_violations(
    label_map: np.ndarray,
    rgb: np.ndarray,
    print_spec: PrintSpec,
    min_area_mm2: float,
    min_width_mm: float,
) -> list[dict[str, object]]:
    mm_per_pixel = _source_mm_per_pixel(label_map.shape, print_spec)
    records = build_region_records(label_map, rgb, build_adjacency(label_map))
    violations: list[dict[str, object]] = []
    for record in records:
        area_mm2 = record.area * mm_per_pixel**2
        width_mm = record.estimated_thickness * mm_per_pixel
        area_failed = area_mm2 + 1e-9 < min_area_mm2
        width_failed = width_mm + 1e-9 < min_width_mm
        if not area_failed and not width_failed:
            continue
        violations.append(
            {
                "region_id": record.region_id,
                "area_pixels": record.area,
                "area_mm2": round(area_mm2, 8),
                "estimated_width_mm": round(width_mm, 8),
                "area_failed": area_failed,
                "width_failed": width_failed,
            }
        )
    return violations


def _printer_floor_sensitive_region_ids(
    label_map: np.ndarray,
    rgb: np.ndarray,
    print_spec: PrintSpec,
    min_area_mm2: float,
    min_width_mm: float,
    maximum_radius: int,
) -> set[int]:
    mm_per_pixel = _source_mm_per_pixel(label_map.shape, print_spec)
    records = build_region_records(label_map, rgb, build_adjacency(label_map))
    result: set[int] = set()
    for record in records:
        conservative_area_pixels = max(0, record.area - record.perimeter * maximum_radius)
        conservative_width_pixels = max(0.0, record.estimated_thickness - 2.0 * maximum_radius)
        if (
            conservative_area_pixels * mm_per_pixel**2 < min_area_mm2
            or conservative_width_pixels * mm_per_pixel < min_width_mm
        ):
            result.add(record.region_id)
    return result


def _prefilled_detail_ids(
    label_map: np.ndarray,
    print_spec: PrintSpec,
    protection_by_id: dict[int, float],
    min_area_mm2: float,
    min_width_mm: float,
    min_label_pocket_mm: float,
) -> set[int]:
    page_width, page_height = print_spec.page_px
    margin = int(round(print_spec.margin_mm / 25.4 * print_spec.dpi))
    scale = min((page_width - 2 * margin) / label_map.shape[1], (page_height - 2 * margin) / label_map.shape[0])
    mm_per_pixel = scale * 25.4 / print_spec.dpi
    records = build_region_records(label_map, np.zeros((*label_map.shape, 3), dtype=np.uint8), build_adjacency(label_map))
    eligible: list[tuple[float, int, int]] = []
    for record in records:
        area_mm2 = record.area * mm_per_pixel**2
        width_mm = record.estimated_thickness * mm_per_pixel
        pocket_mm = _label_pocket_mm(label_map, record.region_id, record.bbox, mm_per_pixel)
        violates_standard = area_mm2 < min_area_mm2 or width_mm < min_width_mm or pocket_mm < min_label_pocket_mm
        if violates_standard and protection_by_id.get(record.region_id, 0.0) >= 0.70 and area_mm2 >= 0.5 and width_mm >= 0.5:
            eligible.append((protection_by_id.get(record.region_id, 0.0), record.area, record.region_id))
    result: set[int] = set()
    pixel_budget = int(round(label_map.size * 0.01))
    used = 0
    for _, area_pixels, region_id in sorted(eligible, key=lambda item: (-item[0], item[1], item[2])):
        if used + area_pixels <= pixel_budget:
            result.add(region_id)
            used += area_pixels
    return result


def _protected_edge_mask(
    label_map: np.ndarray,
    protection: dict[tuple[int, int], float],
) -> np.ndarray:
    mask = np.zeros(label_map.shape, dtype=bool)
    for y, x in np.argwhere(label_map[:, 1:] != label_map[:, :-1]):
        if protection.get(_pair(int(label_map[y, x]), int(label_map[y, x + 1])), 0.0) >= HARD_PROTECTION_THRESHOLD:
            mask[y, x] = True
            mask[y, x + 1] = True
    for y, x in np.argwhere(label_map[1:, :] != label_map[:-1, :]):
        if protection.get(_pair(int(label_map[y, x]), int(label_map[y + 1, x])), 0.0) >= HARD_PROTECTION_THRESHOLD:
            mask[y, x] = True
            mask[y + 1, x] = True
    return mask


def _protected_pairs_from_mask(
    label_map: np.ndarray,
    protected_edge_mask: np.ndarray,
) -> set[tuple[int, int]]:
    result: set[tuple[int, int]] = set()
    horizontal = label_map[:, 1:] != label_map[:, :-1]
    horizontal &= protected_edge_mask[:, 1:] | protected_edge_mask[:, :-1]
    for left, right in zip(label_map[:, :-1][horizontal], label_map[:, 1:][horizontal], strict=False):
        if left and right:
            result.add(_pair(int(left), int(right)))
    vertical = label_map[1:, :] != label_map[:-1, :]
    vertical &= protected_edge_mask[1:, :] | protected_edge_mask[:-1, :]
    for top, bottom in zip(label_map[:-1, :][vertical], label_map[1:, :][vertical], strict=False):
        if top and bottom:
            result.add(_pair(int(top), int(bottom)))
    return result


def _region_ids_touching_mask(label_map: np.ndarray, protected_edge_mask: np.ndarray) -> set[int]:
    if not np.any(protected_edge_mask):
        return set()
    return {int(value) for value in np.unique(label_map[protected_edge_mask]) if int(value) > 0}


def _region_protection_scores(rgb: np.ndarray, label_map: np.ndarray) -> dict[int, float]:
    adjacency, shared = _adjacency_with_shared_boundary(label_map)
    edge_scores = _boundary_protection_scores(rgb, label_map, adjacency, shared)
    result: dict[int, float] = {}
    for region_id, neighbours in adjacency.items():
        values = [(edge_scores.get(_pair(region_id, neighbour), 0.0), shared.get(_pair(region_id, neighbour), 1)) for neighbour in neighbours]
        if not values:
            result[region_id] = 0.0
            continue
        maximum = max(value for value, _ in values)
        weighted = sum(value * length for value, length in values) / max(1, sum(length for _, length in values))
        result[region_id] = min(1.0, 0.60 * maximum + 0.40 * weighted)
    return result


def _boundary_protection_scores(
    rgb: np.ndarray,
    label_map: np.ndarray,
    adjacency: dict[int, set[int]],
    shared: dict[tuple[int, int], int],
) -> dict[tuple[int, int], float]:
    lab = color.rgb2lab(rgb.astype(np.float64) / 255.0)
    max_label = int(label_map.max())
    area = np.bincount(label_map.ravel(), minlength=max_label + 1).astype(np.float64)
    means = np.zeros((max_label + 1, 3), dtype=np.float64)
    for channel in range(3):
        means[:, channel] = np.bincount(label_map.ravel(), weights=lab[..., channel].ravel(), minlength=max_label + 1)
    means[1:] /= np.maximum(area[1:, None], 1.0)

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
    gradients: list[np.ndarray] = []
    for sigma in (0.0, 1.0, 2.0):
        sample = gray if sigma == 0 else cv2.GaussianBlur(gray, (0, 0), sigma)
        gx = cv2.Sobel(sample, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(sample, cv2.CV_32F, 0, 1, ksize=3)
        gradients.append(np.sqrt(gx * gx + gy * gy))

    boundary_pixels: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for y, x in np.argwhere(label_map[:, 1:] != label_map[:, :-1]):
        key = _pair(int(label_map[y, x]), int(label_map[y, x + 1]))
        boundary_pixels.setdefault(key, []).append((int(y), int(x)))
    for y, x in np.argwhere(label_map[1:, :] != label_map[:-1, :]):
        key = _pair(int(label_map[y, x]), int(label_map[y + 1, x]))
        boundary_pixels.setdefault(key, []).append((int(y), int(x)))

    scores: dict[tuple[int, int], float] = {}
    for key, length in shared.items():
        left, right = key
        delta = float(color.deltaE_ciede2000(means[left][None, :], means[right][None, :])[0])
        contrast = float(np.clip((delta - 2.0) / 10.0, 0.0, 1.0))
        coords = boundary_pixels.get(key, [])
        if coords:
            scale_support = []
            yy = np.asarray([point[0] for point in coords], dtype=np.intp)
            xx = np.asarray([point[1] for point in coords], dtype=np.intp)
            for gradient in gradients:
                scale_support.append(float(np.clip(np.median(gradient[yy, xx]) / 0.18, 0.0, 1.0)))
            persistence = min(scale_support)
        else:
            persistence = 0.0
        contact = min(1.0, length / max(1.0, 2.5 * np.sqrt(min(area[left], area[right]))))
        structural = contact
        topology = 1.0 if min(len(adjacency.get(left, set())), len(adjacency.get(right, set()))) <= 2 else (0.5 if min(len(adjacency.get(left, set())), len(adjacency.get(right, set()))) == 3 else 0.0)
        density = min(1.0, (len(adjacency.get(left, set())) + len(adjacency.get(right, set()))) / 16.0)
        irregularity = 1.0 - contact
        texture = 0.5 * density + 0.5 * irregularity
        scores[key] = float(np.clip(0.35 * contrast + 0.25 * persistence + 0.20 * structural + 0.20 * topology - 0.25 * texture, 0.0, 1.0))
    return scores


def _label_pocket_mm(
    label_map: np.ndarray,
    region_id: int,
    bbox: tuple[int, int, int, int],
    mm_per_pixel: float,
) -> float:
    left, top, right, bottom = bbox
    mask = (label_map[top:bottom, left:right] == region_id).astype(np.uint8)
    padded = np.pad(mask, 1, mode="constant", constant_values=0)
    radius = float(cv2.distanceTransform(padded, cv2.DIST_L2, 5).max())
    return max(0.0, (2.0 * radius - 1.0) * mm_per_pixel)


def _adjacency_with_shared_boundary(label_map: np.ndarray) -> tuple[dict[int, set[int]], dict[tuple[int, int], int]]:
    adjacency = build_adjacency(label_map)
    shared: dict[tuple[int, int], int] = {}
    for left, right in (
        (label_map[:, :-1], label_map[:, 1:]),
        (label_map[:-1, :], label_map[1:, :]),
    ):
        mask = left != right
        pairs = np.stack([left[mask], right[mask]], axis=1)
        if not len(pairs):
            continue
        pairs.sort(axis=1)
        unique, counts = np.unique(pairs, axis=0, return_counts=True)
        for pair, count in zip(unique, counts, strict=False):
            if pair[0] and pair[1]:
                key = (int(pair[0]), int(pair[1]))
                shared[key] = shared.get(key, 0) + int(count)
    return adjacency, shared


def _pair(left: int, right: int) -> tuple[int, int]:
    return (left, right) if left < right else (right, left)


def _compact_labels(label_map: np.ndarray) -> np.ndarray:
    labels = np.unique(label_map)
    labels = labels[labels > 0]
    if len(labels) == 0:
        return label_map.astype(np.int32)
    remap = np.zeros(int(labels.max()) + 1, dtype=np.int32)
    remap[labels] = np.arange(1, len(labels) + 1, dtype=np.int32)
    return remap[label_map]
