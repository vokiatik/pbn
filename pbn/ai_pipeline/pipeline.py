from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import cv2
from PIL import Image
from skimage import color

from .config import AIProviderConfig, load_ai_provider_config, with_provider_override
from .detail_protection import (
    DetailProtection,
    apply_difficulty_protection,
    boundary_selection_coverage,
    detail_contour_tolerance,
    load_detail_protection,
    meaningful_selected_pairs,
    selected_boundary_mask,
    write_protection_trace,
)
from .io_utils import atomic_write_json, save_label_map_png, save_rgb
from .models import (
    ImageSimplificationProvider,
    ProcessingDiagnosticError,
    ProviderRequestError,
    SimplificationInstructions,
)
from .option_search import (
    DIFFICULTY_ORDER,
    OptionCandidate,
    density_target,
    option_max_attempts,
    select_option_candidates,
)
from .palette import derive_region_palette, reconcile_palette_after_alignment
from .print_spec import PrintSpec
from .provider_factory import create_provider
from .quality import assess_ai_source
from .regions import build_adjacency, build_region_records, record_to_dict
from .segmentation import (
    RetryProfile,
    _align_boundaries_to_source,
    _enforce_physical_constraints,
    _protected_edge_mask,
    _source_mm_per_pixel,
    _source_edge_strength,
    create_structural_atoms,
    region_boundary_evidence,
    retry_profiles,
)
from .source_prep import crop_provider_output, prepare_source_image
from .template_export import build_print_artifacts, render_template_and_exports
from .validation import validate_template_inputs


AI_PIPELINE_DIR = "pipeline_ai"


@dataclass(frozen=True)
class ParsedAISettings:
    target_palette_size: int
    page_size: str
    orientation: str
    fit_mode: str
    crop: dict[str, float] | None
    category: str
    preserve_elements: list[str]
    simplify_elements: list[str]
    prompt_guidance: str

    @property
    def print_spec(self) -> PrintSpec:
        return PrintSpec(page_size=self.page_size, orientation=self.orientation)


def run_ai_pipeline(
    project_dir: Path,
    original_image: Path,
    settings: dict[str, Any],
    provider: ImageSimplificationProvider | None = None,
    provider_config: AIProviderConfig | None = None,
    progress_callback: Callable[[str, int, str], None] | None = None,
) -> tuple[Path, dict[str, Any]]:
    root, image_result = generate_ai_image(
        project_dir,
        original_image,
        settings,
        provider,
        provider_config,
        progress_callback,
    )
    _, result = continue_ai_pipeline(project_dir, original_image, settings, progress_callback)
    result["prepared_source"] = image_result["prepared_source"]
    result.setdefault("metrics", {})["ai_quality"] = image_result.get("metrics", {}).get("ai_quality", {})
    atomic_write_json(root / "pipeline_result.json", result)
    return root, result


def generate_ai_image(
    project_dir: Path,
    original_image: Path,
    settings: dict[str, Any],
    provider: ImageSimplificationProvider | None = None,
    provider_config: AIProviderConfig | None = None,
    progress_callback: Callable[[str, int, str], None] | None = None,
    force_regenerate: bool = False,
) -> tuple[Path, dict[str, Any]]:
    root = project_dir / AI_PIPELINE_DIR
    parsed = _parse_settings(settings)
    print_spec = parsed.print_spec

    _report_progress(progress_callback, "preparing_source", 10, "Applying the approved print composition")
    prepared = prepare_source_image(
        original_image,
        root / "prepared",
        print_spec,
        parsed.fit_mode,
        parsed.crop,
    )
    instructions = _build_instructions(parsed, settings, prepared.width, prepared.height)

    provider_output = root / "ai" / "provider_output.png"
    reviewed_output = root / "ai" / "simplified.png"
    generation_json = root / "ai" / "generation.json"
    config = with_provider_override(provider_config or load_ai_provider_config(), settings.get("provider"))
    selected_provider = provider or create_provider(config)
    _report_progress(progress_callback, "generating_ai_image", 25, "Generating one simplified AI image")
    simplification = _simplify_once_per_run(
        selected_provider,
        prepared.source_path,
        provider_output,
        instructions,
        generation_json,
        config.max_retries,
        force_regenerate,
    )
    # This removes only provider padding recorded in crop_manifest.json. The reviewed
    # pixels are never quantized, filtered, or overwritten by local PBN processing.
    crop_provider_output(provider_output, reviewed_output, prepared)
    _report_progress(progress_callback, "assessing_ai_image", 30, "Checking paint-by-number source quality")
    ai_quality = assess_ai_source(
        reviewed_output,
        root / "ai",
        parsed.target_palette_size,
        print_spec,
    )

    result = {
        "pipeline_version": "ai-topology-v2",
        "storage_root": str(root),
        "prepared_source": {
            "source_path": str(prepared.source_path),
            "composition_path": str(prepared.composition_path),
            "crop_manifest": str(root / "prepared" / "crop_manifest.json"),
            "width": prepared.width,
            "height": prepared.height,
            "fit_mode": prepared.fit_mode,
            "page_size": parsed.page_size,
            "orientation": parsed.orientation,
        },
        "ai_generation": {
            "provider": simplification.provider,
            "model": simplification.model,
            "provider_output_path": str(provider_output),
            "reviewed_output_path": str(reviewed_output),
        },
        "outputs": {"ai_simplified": str(reviewed_output)},
        "metrics": {
            "target_palette_size": parsed.target_palette_size,
            "ai_quality": ai_quality,
        },
    }
    atomic_write_json(root / "ai" / "image_result.json", result)
    return root, result


def continue_ai_pipeline(
    project_dir: Path,
    original_image: Path,
    settings: dict[str, Any],
    progress_callback: Callable[[str, int, str], None] | None = None,
) -> tuple[Path, dict[str, Any]]:
    del original_image
    root = project_dir / AI_PIPELINE_DIR
    parsed = _parse_settings(settings)
    print_spec = parsed.print_spec
    reviewed_output = root / "ai" / "simplified.png"
    if not reviewed_output.is_file():
        raise ValueError("reviewed AI image is missing; regenerate the AI image before proceeding")
    if not (root / "prepared" / "crop_manifest.json").is_file():
        raise ValueError("saved crop manifest is missing; regenerate the AI image before proceeding")
    with Image.open(reviewed_output) as reviewed_image:
        reviewed_shape = (reviewed_image.height, reviewed_image.width)
    detail_protection = load_detail_protection(root, reviewed_shape, print_spec)

    profiles = {profile.name: profile for profile in retry_profiles(print_spec)}
    options_root = root / "options"
    work_root = options_root / ".attempts"
    attempt_reports_root = options_root / "attempt_reports"
    if work_root.exists():
        shutil.rmtree(work_root)
    if attempt_reports_root.exists():
        shutil.rmtree(attempt_reports_root)
    work_root.mkdir(parents=True, exist_ok=True)
    attempt_reports_root.mkdir(parents=True, exist_ok=True)

    _report_progress(progress_callback, "extracting_regions", 35, "Analyzing reviewed image structure")
    source_atoms, source_rgb, analysis_metrics = create_structural_atoms(
        reviewed_output, root / "analysis", print_spec
    )
    _report_progress(progress_callback, "extracting_regions", 42, "Building shared paintable region graph")
    geometry_base = _build_geometry_base(
        reviewed_output,
        work_root / "bases" / "shared",
        print_spec,
        profiles["hard"],
        detail_protection,
        source_atoms=source_atoms,
        source_rgb=source_rgb,
        analysis_metrics=analysis_metrics,
    )

    attempts: list[dict[str, object]] = []
    valid_candidates: list[OptionCandidate] = []
    candidate_dirs: dict[str, Path] = {}
    max_attempts = option_max_attempts()
    total_attempts = max_attempts
    completed_attempts = 0

    for attempt_index in range(max_attempts):
        for difficulty in ("hard",):
            profile = profiles[difficulty]
            density = density_target(difficulty, attempt_index)
            compaction_ceiling = density
            progress = 45 + int(round(48 * completed_attempts / max(1, total_attempts)))
            _report_progress(
                progress_callback,
                "normalizing_region_palette",
                progress,
                f"Generating {difficulty} PBN attempt {attempt_index + 1}/{max_attempts} "
                f"(target {density}, compaction ceiling {compaction_ceiling} regions)",
            )
            attempt_dir = work_root / difficulty / str(attempt_index + 1)
            base = geometry_base
            attempt_record, candidate = _build_option_attempt(
                attempt_dir,
                difficulty,
                attempt_index,
                density,
                compaction_ceiling,
                profile,
                base,
                parsed.target_palette_size,
                print_spec,
            )
            report_path = attempt_reports_root / f"{difficulty}-{attempt_index + 1}.json"
            source_report = attempt_dir / "validation" / "report.json"
            if source_report.is_file():
                shutil.copy2(source_report, report_path)
            else:
                atomic_write_json(
                    report_path,
                    {
                        "status": attempt_record["status"],
                        "metrics": attempt_record["metrics"],
                        "issues": [
                            {
                                "code": "processing_error",
                                "severity": "fail",
                                "message": str(reason),
                                "region_id": None,
                            }
                            for reason in attempt_record["rejection_reasons"]
                        ],
                        "suggested_actions": [],
                    },
                )
            attempt_record["report_path"] = str(report_path)
            attempts.append(attempt_record)
            if candidate is not None:
                valid_candidates.append(candidate)
                candidate_dirs[candidate.artifact_key] = attempt_dir
            completed_attempts += 1

        if valid_candidates:
            break

    selected = select_option_candidates(valid_candidates)
    selected_keys = {item.artifact_key for item in selected}
    for attempt in attempts:
        key = f"{attempt.get('difficulty')}:{attempt.get('attempt')}"
        attempt["selected"] = key in selected_keys

    options: list[dict[str, object]] = []
    selected_difficulties = {item.difficulty for item in selected}
    for item in selected:
        stable_dir = _publish_option_directory(options_root, item.difficulty, candidate_dirs[item.artifact_key])
        metadata = _load_json(stable_dir / "metadata.json")
        metadata["painted_preview_path"] = str(stable_dir / "painted_reference.png")
        metadata["template_preview_path"] = str(stable_dir / "numbered_template.png")
        atomic_write_json(stable_dir / "metadata.json", metadata)
        options.append(metadata)
    for difficulty in DIFFICULTY_ORDER:
        stale_dir = options_root / difficulty
        if difficulty not in selected_difficulties and stale_dir.exists():
            shutil.rmtree(stale_dir)

    options_payload = {
        "options": options,
        "attempts": attempts,
        "search": {
            "max_attempts_per_difficulty": max_attempts,
            "completed_attempt_count": len(attempts),
            "selected_difficulties": [item.difficulty for item in selected],
        },
    }
    atomic_write_json(options_root / "options.json", options_payload)
    if not options:
        _write_failed_validation_summary(root, attempts)
        raise ValueError(_failed_attempt_message(attempts))
    shutil.rmtree(work_root, ignore_errors=True)
    generation_metadata = _load_generation_metadata(root / "ai" / "generation.json")
    result = {
        "pipeline_version": "ai-topology-v2",
        "storage_root": str(root),
        "ai_generation": {
            "provider": generation_metadata.get("provider", "unknown"),
            "model": generation_metadata.get("model", "unknown"),
            "output_path": str(reviewed_output),
        },
        "outputs": {
            "ai_simplified": str(reviewed_output),
            "options_manifest": str(root / "options" / "options.json"),
        },
        "metrics": {
            "attempt_count": len(attempts),
            "valid_option_count": len(options),
            "target_palette_size": parsed.target_palette_size,
            "page_size": parsed.page_size,
            "orientation": parsed.orientation,
            "page_dimensions_px": list(print_spec.page_px),
            "options": options,
        },
    }
    atomic_write_json(root / "options_result.json", result)
    _report_progress(progress_callback, "options_ready", 100, "Hard PBN preview is ready")
    return root, result


def _build_geometry_base(
    reviewed_output: Path,
    base_dir: Path,
    print_spec: PrintSpec,
    profile: RetryProfile,
    detail_protection: DetailProtection | None = None,
    *,
    source_atoms: np.ndarray | None = None,
    source_rgb: np.ndarray | None = None,
    analysis_metrics: dict[str, object] | None = None,
) -> dict[str, object]:
    if source_atoms is None or source_rgb is None:
        source_atoms, source_rgb, analysis_metrics = create_structural_atoms(
            reviewed_output, base_dir / "analysis", print_spec
        )
    regions_dir = base_dir / "regions"
    regions_dir.mkdir(parents=True, exist_ok=True)
    save_label_map_png(source_atoms, regions_dir / "source_atoms.png")
    region_map = source_atoms
    save_label_map_png(region_map, regions_dir / "initial_region_map.png")
    np.save(regions_dir / "region_id_map.npy", region_map)
    geometry_log = [{"operation": "structural_analysis", **(analysis_metrics or {})}]
    boundary_evidence = region_boundary_evidence(source_rgb, region_map)
    hybrid_metrics: dict[str, object] = {}
    selection_coverage: dict[tuple[int, int], float] = {}
    selected_edge_mask = np.zeros(region_map.shape, dtype=bool)
    if detail_protection is not None:
        selection_coverage = boundary_selection_coverage(region_map, detail_protection.weight)
        hybrid_metrics = {
            "selected_area_percent": detail_protection.coverage_percent,
            "base_region_count": int(region_map.max()),
            "hybrid_region_count": int(region_map.max()),
            "source_guided_selection": True,
        }
        meaningful_pairs = meaningful_selected_pairs(
            source_rgb,
            region_map,
            boundary_evidence,
            selection_coverage,
        )
        selected_edge_mask = selected_boundary_mask(region_map, meaningful_pairs)
        write_protection_trace(
            base_dir / "regions" / "detail_protection.json",
            detail_protection,
            hybrid_metrics,
        )
        protected_ids = {
            region_id
            for pair, value in boundary_evidence.items()
            if value >= 0.70
            for region_id in pair
        }
        protection_scores: dict[int, float] = {}
        for pair, value in boundary_evidence.items():
            protection_scores[pair[0]] = max(protection_scores.get(pair[0], 0.0), value)
            protection_scores[pair[1]] = max(protection_scores.get(pair[1], 0.0), value)
        protection_mask = _protected_edge_mask(region_map, boundary_evidence)
    else:
        protected_ids = {
            region_id for pair, value in boundary_evidence.items()
            if value >= 0.70 for region_id in pair
        }
        protection_scores = {}
        for pair, value in boundary_evidence.items():
            protection_scores[pair[0]] = max(protection_scores.get(pair[0], 0.0), value)
            protection_scores[pair[1]] = max(protection_scores.get(pair[1], 0.0), value)
        protection_mask = _protected_edge_mask(region_map, boundary_evidence)
    return {
        "source_atoms": source_atoms,
        "region_map": region_map,
        "source_rgb": source_rgb,
        "geometry_log": geometry_log,
        "protected_ids": protected_ids,
        "protection_scores": protection_scores,
        "protection_mask": protection_mask,
        "boundary_evidence": boundary_evidence,
        "edge_strength": _source_edge_strength(source_rgb, profile.boundary_edge_scales),
        "source_lab": color.rgb2lab(source_rgb.astype(np.float64) / 255.0),
        "detail_protection": detail_protection,
        "selection_coverage": selection_coverage,
        "selected_edge_mask": selected_edge_mask,
        "hybrid_metrics": hybrid_metrics,
    }


def _build_option_attempt(
    attempt_dir: Path,
    difficulty: str,
    attempt_index: int,
    target_regions: int,
    compaction_ceiling: int,
    profile: RetryProfile,
    base: dict[str, object],
    target_palette_size: int,
    print_spec: PrintSpec,
) -> tuple[dict[str, object], OptionCandidate | None]:
    attempt_started = time.perf_counter()
    stage_seconds = {"palette_and_graph": 0.0, "physical_floor": 0.0, "source_edge_alignment": 0.0, "template": 0.0}
    attempt_number = attempt_index + 1
    failure_stage = "initialization"
    failure_map: np.ndarray | None = None
    failure_rgb: np.ndarray | None = None
    failure_palette_size: int | None = None
    has_detail_protection = bool(base.get("detail_protection"))
    contour_tolerance_mm = (
        detail_contour_tolerance(profile.contour_tolerance_mm)
        if has_detail_protection
        else profile.contour_tolerance_mm
    )
    settings = {
        "density_target": target_regions,
        "coordinated_compaction_ceiling": compaction_ceiling,
        "region_budget": profile.region_budget,
        "segmentation_budget": profile.segmentation_budget,
        "initial_superpixels": profile.initial_superpixels,
        "merge_delta_e_00": profile.merge_delta_e,
        "contour_tolerance_mm": contour_tolerance_mm,
        "boundary_snap_mm": profile.boundary_snap_mm,
        "boundary_edge_scales_source_pixels": list(profile.boundary_edge_scales),
        "protected_microregions": has_detail_protection,
    }
    try:
        region_map = base["region_map"]
        source_rgb = base["source_rgb"]
        geometry_log = base["geometry_log"]
        protected_ids = base["protected_ids"]
        protection_scores = base["protection_scores"]
        protection_mask = base["protection_mask"]
        boundary_evidence = base["boundary_evidence"]
        edge_strength = base["edge_strength"]
        source_lab = base["source_lab"]
        detail_protection = base.get("detail_protection")
        selection_coverage = base.get("selection_coverage", {})
        selected_edge_mask = base.get("selected_edge_mask")
        hybrid_metrics = base.get("hybrid_metrics", {})
        assert isinstance(region_map, np.ndarray)
        assert isinstance(source_rgb, np.ndarray)
        assert isinstance(geometry_log, list)
        assert isinstance(protected_ids, set)
        assert isinstance(protection_scores, dict)
        assert isinstance(protection_mask, np.ndarray)
        assert isinstance(boundary_evidence, dict)
        assert isinstance(edge_strength, np.ndarray)
        assert isinstance(source_lab, np.ndarray)
        assert detail_protection is None or isinstance(detail_protection, DetailProtection)
        assert isinstance(selection_coverage, dict)
        assert isinstance(selected_edge_mask, np.ndarray)
        assert isinstance(hybrid_metrics, dict)
        failure_map = region_map
        failure_rgb = source_rgb

        user_protected_pairs: set[tuple[int, int]] = set()
        protection_metrics: dict[str, object] = {}
        if detail_protection is not None:
            failure_stage = "detail_protection"
            (
                boundary_evidence,
                user_protection_scores,
                user_protected_ids,
                user_protected_pairs,
                protection_metrics,
            ) = apply_difficulty_protection(
                source_rgb,
                region_map,
                boundary_evidence,
                selection_coverage,
                difficulty,
            )
            protected_ids = set(protected_ids) | user_protected_ids
            protection_scores = {
                region_id: max(
                    float(protection_scores.get(region_id, 0.0)),
                    float(user_protection_scores.get(region_id, 0.0)),
                )
                for region_id in set(protection_scores) | set(user_protection_scores)
            }

        working_map = region_map
        working_protected_ids = protected_ids
        working_protection_scores = protection_scores
        working_boundary_evidence = boundary_evidence
        mm_per_source_pixel = _source_mm_per_pixel(region_map.shape, print_spec)
        labelability_merge_count = 0
        physical_floor_merges = 0
        palette_region_map: np.ndarray | None = None
        first_palette_preview: np.ndarray | None = None
        first_floor_region_count: int | None = None
        boundary_alignment: dict[str, object] = {}
        aggregate_fidelity_metrics: dict[str, int] = {
            "weak_boundary_merge_count": 0,
            "density_merge_count": 0,
            "physical_constraint_merge_count": 0,
            "palette_conflict_merge_count": 0,
            "faithful_alternative_colour_count": 0,
            "selected_forced_merge_count": 0,
            "palette_protected_forced_merge_count": 0,
        }
        aggregate_palette_protected_forced_merges: list[dict[str, object]] = []
        for _ in range(8):
            failure_stage = "palette_derivation"
            failure_map = working_map
            failure_palette_size = None
            stage_started = time.perf_counter()
            final_map, painted, region_to_color, palette_rgb, assignments = derive_region_palette(
                source_rgb,
                working_map,
                attempt_dir / "palette",
                target_palette_size,
                protected_region_ids=working_protected_ids,
                protection_scores=working_protection_scores,
                boundary_evidence=working_boundary_evidence,
                target_region_count=compaction_ceiling,
                dynamic_compaction=True,
                maximum_region_count=(compaction_ceiling * 110 + 99) // 100,
                user_protected_pairs=user_protected_pairs,
                minimum_area_pixels=0.5 / mm_per_source_pixel**2,
                minimum_width_pixels=0.5 / mm_per_source_pixel,
            )
            stage_seconds["palette_and_graph"] += time.perf_counter() - stage_started
            if palette_region_map is None:
                palette_region_map = final_map
                first_palette_preview = painted.copy()
            failure_map = final_map
            failure_palette_size = len(palette_rgb)
            fidelity_metrics = _load_json(attempt_dir / "palette" / "fidelity_metrics.json")
            for key in aggregate_fidelity_metrics:
                aggregate_fidelity_metrics[key] += int(fidelity_metrics.get(key, 0))
            aggregate_palette_protected_forced_merges.extend(
                item
                for item in fidelity_metrics.get("palette_protected_forced_merges", [])
                if isinstance(item, dict)
            )
            final_protected_ids = _remap_region_ids(working_map, final_map, working_protected_ids)
            final_protection_scores = _remap_region_scores(
                working_map,
                final_map,
                working_protection_scores,
            )
            failure_stage = "physical_floor"
            before_floor_map = final_map
            stage_started = time.perf_counter()
            final_map, floor_log = _enforce_physical_constraints(
                source_rgb,
                final_map,
                print_spec,
                _protected_edge_mask(final_map, region_boundary_evidence(source_rgb, final_map)),
                min_area_mm2=0.5,
                min_width_mm=0.5,
                min_label_pocket_mm=0.0,
            )
            stage_seconds["physical_floor"] += time.perf_counter() - stage_started
            physical_floor_merges += len(floor_log)
            if first_floor_region_count is None:
                first_floor_region_count = int(final_map.max())
            if floor_log:
                final_protected_ids = _remap_region_ids(before_floor_map, final_map, final_protected_ids)
                final_protection_scores = _remap_region_scores(
                    before_floor_map, final_map, final_protection_scores
                )
            failure_stage = "source_edge_alignment"
            stage_started = time.perf_counter()
            final_map, boundary_alignment, _ = _align_boundaries_to_source(
                source_rgb,
                final_map,
                print_spec,
                edge_scales=profile.boundary_edge_scales,
                maximum_snap_mm=profile.boundary_snap_mm,
                prepared_edge_strength=edge_strength,
                prepared_source_lab=source_lab,
            )
            stage_seconds["source_edge_alignment"] += time.perf_counter() - stage_started
            failure_map = final_map
            post_alignment_palette_merges = 0
            for _ in range(8):
                failure_map = final_map

                aligned_evidence = region_boundary_evidence(source_rgb, final_map)
                aligned_protected_ids = set(final_protected_ids)
                aligned_protection_scores = dict(final_protection_scores)
                aligned_user_pairs: set[tuple[int, int]] = set()
                if detail_protection is not None:
                    aligned_selection_coverage = boundary_selection_coverage(
                        final_map,
                        detail_protection.weight,
                    )
                    (
                        aligned_evidence,
                        aligned_user_scores,
                        aligned_user_ids,
                        aligned_user_pairs,
                        protection_metrics,
                    ) = apply_difficulty_protection(
                        source_rgb,
                        final_map,
                        aligned_evidence,
                        aligned_selection_coverage,
                        difficulty,
                    )
                    aligned_protected_ids |= aligned_user_ids
                    for region_id, value in aligned_user_scores.items():
                        aligned_protection_scores[region_id] = max(
                            aligned_protection_scores.get(region_id, 0.0),
                            value,
                        )

                before_palette_map = final_map
                failure_stage = "post_alignment_palette_reconciliation"
                final_map, region_to_color, reconciliation_metrics = reconcile_palette_after_alignment(
                    source_rgb,
                    final_map,
                    palette_rgb,
                    aligned_protected_ids,
                    aligned_protection_scores,
                    aligned_evidence,
                    aligned_user_pairs,
                )
                failure_map = final_map
                final_protected_ids = _remap_region_ids(
                    before_palette_map,
                    final_map,
                    aligned_protected_ids,
                )
                final_protection_scores = _remap_region_scores(
                    before_palette_map,
                    final_map,
                    aligned_protection_scores,
                )
                for key in (
                    "palette_conflict_merge_count",
                    "faithful_alternative_colour_count",
                    "selected_forced_merge_count",
                    "palette_protected_forced_merge_count",
                ):
                    aggregate_fidelity_metrics[key] += int(reconciliation_metrics.get(key, 0))
                aggregate_palette_protected_forced_merges.extend(
                    item
                    for item in reconciliation_metrics.get("palette_protected_forced_merges", [])
                    if isinstance(item, dict)
                )
                palette_merges = int(reconciliation_metrics.get("palette_conflict_merge_count", 0))
                post_alignment_palette_merges += palette_merges
                if palette_merges == 0:
                    break
            else:
                raise ValueError("post-alignment palette reconciliation did not converge")
            boundary_alignment["post_alignment_palette_merge_count"] = post_alignment_palette_merges
            boundary_alignment["post_alignment_seam_merge_count"] = 0
            assignments = [
                {
                    "region_id": region_id,
                    "color_id": color_id,
                    "palette_rgb": list(palette_rgb[color_id - 1]),
                }
                for region_id, color_id in sorted(region_to_color.items())
            ]
            painted = _paint_region_map(final_map, region_to_color, palette_rgb)
            save_rgb(attempt_dir / "palette" / "preview.png", painted)
            atomic_write_json(attempt_dir / "palette" / "region_colours.json", assignments)
            records = build_region_records(
                final_map,
                source_rgb,
                build_adjacency(final_map),
                color_ids=region_to_color,
            )
            failure_stage = "template_rendering"
            stage_started = time.perf_counter()
            artifacts = build_print_artifacts(
                final_map,
                region_to_color,
                palette_rgb,
                print_spec,
                contour_tolerance_mm,
                protected_region_ids=final_protected_ids,
            )
            stage_seconds["template"] += time.perf_counter() - stage_started
            merge_for_labels = set(artifacts[2].unnumbered_region_ids)
            prefilled_ids = set(artifacts[2].prefilled_detail_region_ids or [])
            keep_prefilled = _prefilled_ids_within_limit(
                final_map,
                prefilled_ids,
                final_protection_scores,
                _region_reconstruction_benefit(
                    final_map,
                    source_rgb,
                    region_to_color,
                    palette_rgb,
                    prefilled_ids,
                ),
                maximum_area_percent=3.0,
            )
            merge_for_labels.update(prefilled_ids - keep_prefilled)
            if not merge_for_labels:
                break
            failure_stage = "labelability_cleanup"
            next_map = _merge_unlabelable_regions(final_map, source_rgb, merge_for_labels)
            next_count = int(np.unique(next_map[next_map > 0]).size)
            current_count = int(np.unique(final_map[final_map > 0]).size)
            if next_count >= current_count:
                raise ValueError("unlabelable regions could not be merged deterministically")
            labelability_merge_count += current_count - next_count
            retained_protected = final_protected_ids - merge_for_labels
            working_protected_ids = _remap_region_ids(final_map, next_map, retained_protected)
            working_protection_scores = _remap_region_scores(
                final_map,
                next_map,
                final_protection_scores,
            )
            working_map = next_map
            failure_map = working_map
            working_boundary_evidence = region_boundary_evidence(source_rgb, working_map)
            if detail_protection is not None:
                working_selection_coverage = boundary_selection_coverage(
                    working_map,
                    detail_protection.weight,
                )
                (
                    working_boundary_evidence,
                    user_scores,
                    user_ids,
                    user_protected_pairs,
                    protection_metrics,
                ) = apply_difficulty_protection(
                    source_rgb,
                    working_map,
                    working_boundary_evidence,
                    working_selection_coverage,
                    difficulty,
                )
                working_protected_ids |= user_ids
                for region_id, value in user_scores.items():
                    working_protection_scores[region_id] = max(
                        working_protection_scores.get(region_id, 0.0),
                        value,
                    )
        else:
            raise ValueError("adaptive label planning did not converge within eight passes")

        fidelity_metrics.update(aggregate_fidelity_metrics)
        fidelity_metrics["palette_protected_forced_merges"] = aggregate_palette_protected_forced_merges
        fidelity_metrics["labelability_merge_count"] = labelability_merge_count
        fidelity_metrics["artificial_boundary_count"] = int(fidelity_metrics.get("artificial_boundary_count", 0))
        fidelity_metrics["unsupported_transition_edge_count"] = 0
        fidelity_metrics["boundary_alignment"] = boundary_alignment
        atomic_write_json(attempt_dir / "palette" / "fidelity_metrics.json", fidelity_metrics)
        reconstruction_delta = _mean_reconstruction_delta_e(source_rgb, painted)
        retention = _protected_boundary_retention(protection_mask, final_map)
        selected_retention = _protected_boundary_retention(selected_edge_mask, final_map)
        protected_mean_delta, protected_p90_delta = _protected_fidelity_metrics(
            source_rgb,
            painted,
            protection_mask,
        )
        selected_prefilled_count = 0
        if detail_protection is not None:
            selected_prefilled_count = sum(
                1
                for region_id in set(artifacts[2].prefilled_detail_region_ids or [])
                if np.any(detail_protection.mask & (final_map == region_id))
            )
        count = len(records)
        faithful_below_minimum = count < 250 and retention >= 0.65 and reconstruction_delta <= 6.0
        failure_stage = "validation"
        report = validate_template_inputs(
            final_map,
            records,
            region_to_color,
            attempt_dir / "validation",
            target_palette_size,
            print_spec=print_spec,
            region_budget=profile.region_budget,
            minimum_region_count=None if faithful_below_minimum else 250,
            numbering_stats=artifacts[2],
            palette_rgb=palette_rgb,
            painted_reference=painted,
            template_size=artifacts[0].size,
            prefilled_detail_region_ids=artifacts[2].prefilled_detail_region_ids,
            protected_region_ids=final_protected_ids,
            protected_boundary_retention=retention,
            protected_mean_delta_e_00=protected_mean_delta,
            protected_p90_delta_e_00=protected_p90_delta,
            artificial_boundary_count=int(fidelity_metrics.get("artificial_boundary_count", 0)),
            mean_reconstruction_delta_e_00=reconstruction_delta,
        )
        report.metrics.update(
            {
                "generation_stages": {
                    "source_atoms": int(base["source_atoms"].max()),
                    "after_physical_floor": first_floor_region_count,
                    "after_graph_and_palette": int(palette_region_map.max()) if palette_region_map is not None else count,
                    "final_regions": count,
                    "physical_floor_merges": physical_floor_merges,
                    "graph_physical_merges": int(fidelity_metrics.get("physical_constraint_merge_count", 0)),
                    "labelability_merges": labelability_merge_count,
                },
                "processing_seconds": {
                    **{key: round(value, 3) for key, value in stage_seconds.items()},
                    "attempt_total": round(time.perf_counter() - attempt_started, 3),
                },
                "density_target": target_regions,
                "coordinated_compaction_ceiling": compaction_ceiling,
                "protected_boundary_retention": retention,
                "mean_reconstruction_delta_e_00": reconstruction_delta,
                "difficulty": difficulty,
                "protected_region_ids": sorted(final_protected_ids),
                "preferred_minimum_region_count": profile.minimum_regions,
                "global_minimum_region_count": 250,
                "faithful_below_minimum": faithful_below_minimum,
                "source_supported_boundary_recall": retention,
                "advanced_area_percent": float(
                    detail_protection.coverage_percent if detail_protection is not None else 0.0
                ),
                "selected_boundary_retention": selected_retention,
                "selected_prefilled_detail_count": selected_prefilled_count,
                "selected_forced_merge_count": int(fidelity_metrics.get("selected_forced_merge_count", 0)),
                "palette_protected_forced_merge_count": int(
                    fidelity_metrics.get("palette_protected_forced_merge_count", 0)
                ),
                "protection_overflow_percent": float(fidelity_metrics.get("protection_overflow_percent", 0.0)),
                "detail_protection": protection_metrics,
                "hybrid_geometry": hybrid_metrics,
                "fidelity": fidelity_metrics,
                "minimum_label_height_mm": artifacts[2].minimum_label_height_mm,
                "label_height_counts": artifacts[2].label_height_counts or {},
                "boundary_alignment": boundary_alignment,
            }
        )
        atomic_write_json(attempt_dir / "validation" / "report.json", report.to_dict())
        attempt_record = {
            "difficulty": difficulty,
            "attempt": attempt_number,
            "status": report.status,
            "density_target": target_regions,
            "actual_region_count": count,
            "settings": settings,
            "metrics": report.metrics,
            "rejection_reasons": sorted({issue.code for issue in report.issues}),
            "selected": False,
        }
        if report.status != "pass":
            return attempt_record, None

        candidate_payload = {
            "profile": profile,
            "source_atoms": base["source_atoms"],
            "palette_region_map": palette_region_map,
            "initial_palette_preview": first_palette_preview,
            "region_map": final_map,
            "source_rgb": source_rgb,
            "painted": painted,
            "region_to_color": region_to_color,
            "palette_rgb": palette_rgb,
            "assignments": assignments,
            "records": records,
            "artifacts": artifacts,
            "report": report,
            "geometry_log": [*geometry_log, boundary_alignment],
            "prefilled_detail_region_ids": set(artifacts[2].prefilled_detail_region_ids or []),
            "protected_region_ids": final_protected_ids,
            "protection_mask": protection_mask,
            "edge_strength": edge_strength,
            "detail_protection": detail_protection,
            "selected_edge_mask": selected_edge_mask,
        }
        _save_option_candidate(attempt_dir, candidate_payload)
        metadata = _option_metadata(attempt_dir, profile, report, palette_rgb, artifacts[2])
        atomic_write_json(attempt_dir / "metadata.json", metadata)
        artifact_key = f"{difficulty}:{attempt_number}"
        return attempt_record, OptionCandidate(
            difficulty=difficulty,
            attempt=attempt_number,
            density_target=target_regions,
            region_count=count,
            artifact_key=artifact_key,
            reconstruction_delta_e_00=reconstruction_delta,
            boundary_recall=retention,
            selected_boundary_retention=selected_retention,
        )
    except Exception as exc:
        diagnostics = exc.diagnostics if isinstance(exc, ProcessingDiagnosticError) else {}
        if (
            isinstance(exc, ProcessingDiagnosticError)
            and isinstance(exc.diagnostic_region_map, np.ndarray)
        ):
            failure_map = exc.diagnostic_region_map
        metrics = _attempt_failure_metrics(
            failure_map,
            failure_rgb,
            print_spec,
            target_palette_size,
            failure_palette_size,
            failure_stage,
            diagnostics,
        )
        reason = f"processing_error: {exc}"
        _write_attempt_failure_artifacts(
            attempt_dir,
            reason,
            metrics,
            failure_map,
        )
        return (
            {
                "difficulty": difficulty,
                "attempt": attempt_number,
                "status": "error",
                "density_target": target_regions,
                "actual_region_count": metrics.get("total_region_count"),
                "settings": settings,
                "metrics": metrics,
                "rejection_reasons": [reason],
                "selected": False,
            },
            None,
        )


def _attempt_failure_metrics(
    label_map: np.ndarray | None,
    source_rgb: np.ndarray | None,
    print_spec: PrintSpec,
    target_palette_size: int,
    palette_size: int | None,
    failure_stage: str,
    diagnostics: dict[str, Any],
) -> dict[str, object]:
    metrics: dict[str, object] = {
        "failure_stage": failure_stage,
        "target_palette_size": target_palette_size,
    }
    if palette_size is not None:
        metrics["palette_size"] = palette_size
    if label_map is not None and source_rgb is not None:
        records = build_region_records(label_map, source_rgb, build_adjacency(label_map))
        mm_per_pixel = _source_mm_per_pixel(label_map.shape, print_spec)
        metrics.update(
            {
                "total_region_count": len(records),
                "min_region_area_mm2": min(
                    (record.area * mm_per_pixel**2 for record in records),
                    default=0.0,
                ),
                "min_estimated_width_mm": min(
                    (record.estimated_thickness * mm_per_pixel for record in records),
                    default=0.0,
                ),
            }
        )
    metrics.update(diagnostics)
    return metrics


def _write_attempt_failure_artifacts(
    attempt_dir: Path,
    reason: str,
    metrics: dict[str, object],
    label_map: np.ndarray | None,
) -> None:
    failure_dir = attempt_dir / "failure"
    failure_dir.mkdir(parents=True, exist_ok=True)
    if label_map is not None:
        np.save(failure_dir / "region_id_map.npy", label_map)
        save_label_map_png(label_map, failure_dir / "region_map.png")
    atomic_write_json(
        failure_dir / "diagnostics.json",
        {
            "status": "error",
            "message": reason,
            "metrics": metrics,
        },
    )
    affected_region_ids = metrics.get("affected_region_ids")
    region_id = None
    if isinstance(affected_region_ids, list) and len(affected_region_ids) == 1:
        region_id = affected_region_ids[0]
    atomic_write_json(
        attempt_dir / "validation" / "report.json",
        {
            "status": "error",
            "metrics": metrics,
            "issues": [
                {
                    "code": "processing_error",
                    "severity": "fail",
                    "message": reason,
                    "region_id": region_id,
                }
            ],
            "suggested_actions": [],
        },
    )


def _publish_option_directory(options_root: Path, difficulty: str, source_dir: Path) -> Path:
    staging = options_root / f".selected-{difficulty}"
    target = options_root / difficulty
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(source_dir, staging)
    if target.exists():
        shutil.rmtree(target)
    staging.replace(target)
    return target


def finalize_pbn_option(
    project_dir: Path,
    settings: dict[str, Any],
    difficulty: str,
    progress_callback: Callable[[str, int, str], None] | None = None,
) -> tuple[Path, dict[str, Any]]:
    root = project_dir / AI_PIPELINE_DIR
    parsed = _parse_settings(settings)
    profiles = {profile.name: profile for profile in retry_profiles(parsed.print_spec)}
    if difficulty != "hard":
        raise ValueError("only hard PBN output is supported")
    manifest = _load_json(root / "options" / "options.json")
    valid_names = {str(item.get("difficulty")) for item in manifest.get("options", []) if isinstance(item, dict)}
    if difficulty not in valid_names:
        raise ValueError(f"saved {difficulty} option is missing or invalid")

    profile = profiles[difficulty]
    contour_tolerance_mm = (
        detail_contour_tolerance(profile.contour_tolerance_mm)
        if (root / "input" / "detail_protection.png").is_file()
        else profile.contour_tolerance_mm
    )
    option_dir = root / "options" / difficulty
    region_map = np.load(option_dir / "regions" / "region_id_map.npy").astype(np.int32)
    with Image.open(root / "ai" / "simplified.png") as image:
        source_rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    palette_payload = _load_json(option_dir / "palette" / "palette.json")
    palette_rgb = [tuple(int(value) for value in item["rgb"]) for item in palette_payload if isinstance(item, dict)]
    assignments = _load_json(option_dir / "palette" / "region_colours.json")
    region_to_color = {int(item["region_id"]): int(item["color_id"]) for item in assignments if isinstance(item, dict)}
    metadata = _load_json(option_dir / "metadata.json")
    prefilled_ids = {int(value) for value in metadata.get("prefilled_detail_region_ids", [])}
    protected_ids = {int(value) for value in metadata.get("protected_region_ids", [])}
    # Legacy options did not persist protected ids separately. Their existing
    # prefilled details are the only safe fallback candidates during rebuild.
    protected_ids.update(prefilled_ids)
    label_plan_path = option_dir / "label_plan.json"
    label_plan = _load_json(label_plan_path) if label_plan_path.is_file() else None
    painted = np.full((*region_map.shape, 3), 255, dtype=np.uint8)
    for region_id, color_id in region_to_color.items():
        painted[region_map == region_id] = palette_rgb[color_id - 1]
    records = build_region_records(region_map, source_rgb, build_adjacency(region_map), color_ids=region_to_color)
    artifacts = build_print_artifacts(
        region_map,
        region_to_color,
        palette_rgb,
        parsed.print_spec,
        contour_tolerance_mm,
        prefilled_detail_region_ids=prefilled_ids,
        protected_region_ids=protected_ids,
        label_plan=label_plan,
    )
    if artifacts[2].label_plan:
        atomic_write_json(label_plan_path, artifacts[2].label_plan)
    if label_plan is None:
        rebuilt_preview = artifacts[0].copy()
        rebuilt_preview.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
        rebuilt_preview.save(option_dir / "numbered_template.png")
    generation_metrics = _load_json(option_dir / "validation" / "report.json").get("metrics", {})
    report = validate_template_inputs(
        region_map,
        records,
        region_to_color,
        root / "validation",
        parsed.target_palette_size,
        print_spec=parsed.print_spec,
        region_budget=profile.region_budget,
        numbering_stats=artifacts[2],
        palette_rgb=palette_rgb,
        painted_reference=painted,
        template_size=artifacts[0].size,
        prefilled_detail_region_ids=prefilled_ids,
        protected_region_ids=protected_ids,
        protected_boundary_retention=(
            float(metadata["protected_boundary_retention"])
            if "protected_boundary_retention" in metadata
            else None
        ),
        protected_mean_delta_e_00=(
            float(metadata["protected_mean_delta_e_00"])
            if "protected_mean_delta_e_00" in metadata
            else None
        ),
        protected_p90_delta_e_00=(
            float(metadata["protected_p90_delta_e_00"])
            if "protected_p90_delta_e_00" in metadata
            else None
        ),
        artificial_boundary_count=int(metadata.get("artificial_boundary_count", 0)),
        mean_reconstruction_delta_e_00=(
            float(metadata["mean_reconstruction_delta_e_00"])
            if "mean_reconstruction_delta_e_00" in metadata
            else None
        ),
    )
    if isinstance(generation_metrics, dict):
        for key, value in generation_metrics.items():
            report.metrics.setdefault(key, value)
    atomic_write_json(root / "validation" / "report.json", report.to_dict())
    if report.status != "pass":
        raise ValueError(f"saved {difficulty} option no longer passes validation")

    candidate: dict[str, object] = {
        "profile": profile,
        "region_map": region_map,
        "source_rgb": source_rgb,
        "painted": painted,
        "region_to_color": region_to_color,
        "palette_rgb": palette_rgb,
        "assignments": assignments,
        "records": records,
        "artifacts": artifacts,
        "report": report,
        "geometry_log": _load_json(option_dir / "regions" / "merge_log.json"),
        "prefilled_detail_region_ids": prefilled_ids,
        "protected_region_ids": protected_ids,
        "edge_strength": _source_edge_strength(source_rgb, profile.boundary_edge_scales),
    }
    _report_progress(progress_callback, "generating_template", 70, f"Rendering selected {difficulty} option")
    _publish_selected_option(root, candidate)
    export_result = render_template_and_exports(
        region_map=region_map,
        region_to_color=region_to_color,
        palette_rgb=palette_rgb,
        template_dir=root / "template",
        export_dir=root / "export",
        print_spec=parsed.print_spec,
        painted_reference_rgb=painted,
        contour_tolerance_mm=contour_tolerance_mm,
        prepared_artifacts=artifacts,
        prefilled_detail_region_ids=prefilled_ids,
        protected_region_ids=protected_ids,
        label_plan=artifacts[2].label_plan,
    )
    result = {
        "pipeline_version": "ai-topology-v2",
        "selected_difficulty": difficulty,
        "outputs": export_result["outputs"],
        "metrics": {"difficulty": difficulty, "validation": report.to_dict(), "numbering": export_result},
    }
    atomic_write_json(root / "pipeline_result.json", result)
    _report_progress(progress_callback, "completed", 100, f"{difficulty.title()} printable PBN is ready")
    return root, result


def _protection_metadata(geometry_log: list[dict[str, object]]) -> dict[str, object]:
    for entry in reversed(geometry_log):
        if entry.get("operation") == "protection_summary":
            return {
                "protected_region_ids": list(entry.get("protected_region_ids", [])),
                "prefilled_detail_region_ids": list(entry.get("prefilled_detail_region_ids", [])),
                "region_protection_scores": dict(entry.get("region_protection_scores", {})),
            }
    return {"protected_region_ids": [], "prefilled_detail_region_ids": [], "region_protection_scores": {}}


def _remap_region_ids(before: np.ndarray, after: np.ndarray, region_ids: set[int]) -> set[int]:
    result: set[int] = set()
    for region_id in region_ids:
        values, counts = np.unique(after[before == region_id], return_counts=True)
        usable = [(int(value), int(count)) for value, count in zip(values, counts, strict=True) if int(value) > 0]
        if usable:
            target, overlap = max(usable, key=lambda item: (item[1], -item[0]))
            target_area = int(np.count_nonzero(after == target))
            if overlap / max(1, target_area) >= 0.80:
                result.add(target)
    return result


def _remap_region_scores(
    before: np.ndarray,
    after: np.ndarray,
    scores: dict[int, float],
) -> dict[int, float]:
    result: dict[int, float] = {}
    for region_id, score in scores.items():
        values, counts = np.unique(after[before == region_id], return_counts=True)
        usable = [(int(value), int(count)) for value, count in zip(values, counts, strict=True) if int(value) > 0]
        if not usable:
            continue
        target, _ = max(usable, key=lambda item: (item[1], -item[0]))
        result[target] = max(result.get(target, 0.0), float(score))
    return result


def _prefilled_ids_within_limit(
    region_map: np.ndarray,
    prefilled_ids: set[int],
    protection_scores: dict[int, float],
    reconstruction_benefit: dict[int, float],
    maximum_area_percent: float,
) -> set[int]:
    if not prefilled_ids:
        return set()
    maximum_pixels = int(np.floor(region_map.size * maximum_area_percent / 100.0))
    areas = {region_id: int(np.count_nonzero(region_map == region_id)) for region_id in prefilled_ids}
    kept: set[int] = set()
    used = 0
    for region_id in sorted(
        prefilled_ids,
        key=lambda item: (
            -protection_scores.get(item, 0.0),
            -reconstruction_benefit.get(item, 0.0),
            areas[item],
            item,
        ),
    ):
        if used + areas[region_id] > maximum_pixels:
            continue
        kept.add(region_id)
        used += areas[region_id]
    return kept


def _region_reconstruction_benefit(
    region_map: np.ndarray,
    source_rgb: np.ndarray,
    region_to_color: dict[int, int],
    palette_rgb: list[tuple[int, int, int]],
    region_ids: set[int],
) -> dict[int, float]:
    if not region_ids:
        return {}
    source_lab = color.rgb2lab(source_rgb.astype(np.float64) / 255.0)
    palette_lab = color.rgb2lab(np.asarray(palette_rgb, dtype=np.uint8)[None, :, :] / 255.0)[0]
    adjacency = build_adjacency(region_map)
    result: dict[int, float] = {}
    for region_id in region_ids:
        pixels = source_lab[region_map == region_id]
        if not pixels.size or region_id not in region_to_color:
            continue
        representative = np.median(pixels, axis=0)
        current_colour = region_to_color[region_id] - 1
        current_error = float(color.deltaE_ciede2000(representative[None, :], palette_lab[current_colour][None, :])[0])
        neighbour_errors = [
            float(
                color.deltaE_ciede2000(
                    representative[None, :],
                    palette_lab[region_to_color[neighbour] - 1][None, :],
                )[0]
            )
            for neighbour in adjacency.get(region_id, set())
            if neighbour in region_to_color
        ]
        result[region_id] = max(0.0, min(neighbour_errors, default=current_error) - current_error)
    return result


def _merge_unlabelable_regions(
    region_map: np.ndarray,
    source_rgb: np.ndarray,
    merge_region_ids: set[int],
) -> np.ndarray:
    maximum = int(region_map.max())
    parent = np.arange(maximum + 1, dtype=np.int32)
    adjacency = build_adjacency(region_map)
    source_lab = color.rgb2lab(source_rgb.astype(np.float64) / 255.0)
    areas = np.bincount(region_map.ravel(), minlength=maximum + 1).astype(np.int64)
    means: dict[int, np.ndarray] = {}
    for region_id in range(1, maximum + 1):
        pixels = source_lab[region_map == region_id]
        if pixels.size:
            means[region_id] = np.median(pixels, axis=0)
    evidence = region_boundary_evidence(source_rgb, region_map)

    def find(region_id: int) -> int:
        while parent[region_id] != region_id:
            parent[region_id] = parent[int(parent[region_id])]
            region_id = int(parent[region_id])
        return region_id

    for region_id in sorted(merge_region_ids, key=lambda item: (areas[item], item)):
        root = find(region_id)
        neighbours = sorted(adjacency.get(region_id, set()))
        candidates = [find(neighbour) for neighbour in neighbours if find(neighbour) != root]
        if not candidates:
            continue
        target = min(
            set(candidates),
            key=lambda candidate: (
                float(color.deltaE_ciede2000(means[region_id][None, :], means[candidate][None, :])[0]),
                evidence.get((min(region_id, candidate), max(region_id, candidate)), 0.0),
                -int(areas[candidate]),
                candidate,
            ),
        )
        parent[root] = target

    roots = np.asarray([find(index) for index in range(maximum + 1)], dtype=np.int32)
    rooted = roots[region_map]
    active = np.unique(rooted)
    active = active[active > 0]
    compact = np.zeros(maximum + 1, dtype=np.int32)
    compact[active] = np.arange(1, len(active) + 1, dtype=np.int32)
    return compact[rooted]


def _mean_reconstruction_delta_e(source_rgb: np.ndarray, painted_rgb: np.ndarray) -> float:
    source_lab = color.rgb2lab(source_rgb.astype(np.float64) / 255.0)
    painted_lab = color.rgb2lab(painted_rgb.astype(np.float64) / 255.0)
    return float(np.mean(color.deltaE_ciede2000(source_lab, painted_lab)))


def _paint_region_map(
    region_map: np.ndarray,
    region_to_color: dict[int, int],
    palette_rgb: list[tuple[int, int, int]],
) -> np.ndarray:
    lut = np.full((int(region_map.max()) + 1, 3), 255, dtype=np.uint8)
    for region_id, color_id in region_to_color.items():
        if 1 <= color_id <= len(palette_rgb):
            lut[region_id] = palette_rgb[color_id - 1]
    return lut[region_map]


def _protected_boundary_retention(protected_edge_mask: np.ndarray, region_map: np.ndarray) -> float:
    protected = protected_edge_mask.astype(bool)
    if not np.any(protected):
        return 1.0
    boundaries = np.zeros(region_map.shape, dtype=np.uint8)
    boundaries[:, 1:] |= region_map[:, 1:] != region_map[:, :-1]
    boundaries[1:, :] |= region_map[1:, :] != region_map[:-1, :]
    boundaries = cv2.dilate(boundaries, np.ones((5, 5), np.uint8), iterations=1).astype(bool)
    return float(np.count_nonzero(protected & boundaries) / max(1, np.count_nonzero(protected)))


def _protected_fidelity_metrics(
    source_rgb: np.ndarray,
    painted_rgb: np.ndarray,
    protected_edge_mask: np.ndarray,
) -> tuple[float, float]:
    if not np.any(protected_edge_mask):
        return 0.0, 0.0
    detail_mask = cv2.dilate(
        protected_edge_mask.astype(np.uint8),
        np.ones((7, 7), np.uint8),
        iterations=1,
    ).astype(bool)
    source_lab = color.rgb2lab(source_rgb.astype(np.float64) / 255.0)
    painted_lab = color.rgb2lab(painted_rgb.astype(np.float64) / 255.0)
    values = color.deltaE_ciede2000(source_lab, painted_lab)[detail_mask]
    if not values.size:
        return 0.0, 0.0
    return float(np.mean(values)), float(np.percentile(values, 90))


def _save_option_candidate(option_dir: Path, candidate: dict[str, object]) -> None:
    region_map = candidate["region_map"]
    painted = candidate["painted"]
    records = candidate["records"]
    assignments = candidate["assignments"]
    palette_rgb = candidate["palette_rgb"]
    artifacts = candidate["artifacts"]
    report = candidate["report"]
    edge_strength = candidate.get("edge_strength")
    detail_protection = candidate.get("detail_protection")
    selected_edges = candidate.get("selected_edge_mask")
    assert isinstance(region_map, np.ndarray)
    assert isinstance(painted, np.ndarray)

    regions_dir = option_dir / "regions"
    regions_dir.mkdir(parents=True, exist_ok=True)
    np.save(regions_dir / "region_id_map.npy", region_map)
    save_label_map_png(region_map, regions_dir / "initial_region_map.png")
    if isinstance(edge_strength, np.ndarray):
        edge_preview = np.rint(np.clip(edge_strength, 0.0, 1.0) * 255.0).astype(np.uint8)
        save_rgb(regions_dir / "boundary_strength.png", np.repeat(edge_preview[..., None], 3, axis=2))
    if isinstance(detail_protection, DetailProtection):
        mask_preview = np.where(detail_protection.mask[..., None], np.asarray([23, 72, 160], dtype=np.uint8), 255)
        save_rgb(regions_dir / "detail_protection.png", mask_preview)
        atomic_write_json(
            regions_dir / "detail_protection.json",
            {
                "sha256": detail_protection.sha256,
                "coverage_percent": detail_protection.coverage_percent,
                "transition_source_pixels": detail_protection.transition_source_pixels,
            },
        )
    if isinstance(selected_edges, np.ndarray):
        selected_preview = np.where(selected_edges[..., None], np.asarray([220, 45, 45], dtype=np.uint8), 255)
        save_rgb(regions_dir / "selected_source_edges.png", selected_preview)
    atomic_write_json(regions_dir / "regions.json", [record_to_dict(record) for record in records])  # type: ignore[arg-type]
    atomic_write_json(regions_dir / "adjacency.json", {str(key): sorted(value) for key, value in build_adjacency(region_map).items()})
    atomic_write_json(regions_dir / "merge_log.json", candidate["geometry_log"])

    palette_dir = option_dir / "palette"
    palette_dir.mkdir(parents=True, exist_ok=True)
    save_rgb(palette_dir / "preview.png", painted)
    atomic_write_json(palette_dir / "palette.json", [{"color_id": index + 1, "rgb": list(value)} for index, value in enumerate(palette_rgb)])  # type: ignore[arg-type]
    atomic_write_json(palette_dir / "region_colours.json", assignments)

    save_rgb(option_dir / "painted_reference.png", painted)
    template_page = artifacts[0].copy()  # type: ignore[index,union-attr]
    template_page.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
    template_page.save(option_dir / "numbered_template.png")
    numbering_stats = artifacts[2]  # type: ignore[index]
    if numbering_stats.label_plan:  # type: ignore[union-attr]
        atomic_write_json(option_dir / "label_plan.json", numbering_stats.label_plan)  # type: ignore[union-attr]
    atomic_write_json(option_dir / "validation" / "report.json", report.to_dict())  # type: ignore[union-attr]
    if os.getenv("PBN_DEBUG_IMAGES", "").strip().lower() in {"1", "true", "yes"}:
        debug = option_dir / "debug"
        debug.mkdir(parents=True, exist_ok=True)
        save_rgb(debug / "01_reviewed.png", candidate["source_rgb"])  # type: ignore[arg-type]
        save_label_map_png(candidate["source_atoms"], debug / "02_source_atoms.png")  # type: ignore[arg-type]
        if isinstance(edge_strength, np.ndarray):
            edges = np.rint(np.clip(edge_strength, 0.0, 1.0) * 255.0).astype(np.uint8)
            save_rgb(debug / "03_source_edges.png", np.repeat(edges[..., None], 3, axis=2))
        if isinstance(candidate.get("palette_region_map"), np.ndarray):
            save_label_map_png(candidate["palette_region_map"], debug / "04_after_graph_merge.png")  # type: ignore[arg-type]
        if isinstance(candidate.get("initial_palette_preview"), np.ndarray):
            save_rgb(debug / "05_palette.png", candidate["initial_palette_preview"])  # type: ignore[arg-type]
        save_label_map_png(region_map, debug / "06_final_regions.png")
        save_rgb(debug / "07_final_preview.png", painted)
        template_page.save(debug / "08_template.png")


def _option_metadata(
    option_dir: Path,
    profile: RetryProfile,
    report: object,
    palette_rgb: list[tuple[int, int, int]],
    numbering_stats: object,
) -> dict[str, object]:
    metrics = report.metrics  # type: ignore[attr-defined]
    public_fidelity = dict(metrics.get("fidelity", {}))
    public_fidelity.pop("boundary_alignment", None)
    return {
        "difficulty": profile.name,
        "status": "valid",
        "region_count": int(metrics["total_region_count"]),
        "palette_size": len(palette_rgb),
        "prefilled_detail_count": int(metrics.get("prefilled_detail_count", 0)),
        "prefilled_area_percent": float(metrics.get("prefilled_area_percent", 0.0)),
        "adaptive_label_count": int(metrics.get("adaptive_label_count", 0)),
        "minimum_label_font_pt": float(metrics.get("minimum_label_font_pt", 0.0)),
        "minimum_label_height_mm": float(metrics.get("minimum_label_height_mm", 0.0)),
        "label_height_counts": dict(metrics.get("label_height_counts", {})),
        "protected_boundary_retention": float(metrics.get("protected_boundary_retention", 0.0)),
        "protected_mean_delta_e_00": float(metrics.get("protected_mean_delta_e_00", 0.0)),
        "protected_p90_delta_e_00": float(metrics.get("protected_p90_delta_e_00", 0.0)),
        "region_budget_overflow_percent": float(metrics.get("region_budget_overflow_percent", 0.0)),
        "mean_reconstruction_delta_e_00": float(metrics.get("mean_reconstruction_delta_e_00", 0.0)),
        "artificial_boundary_count": int(metrics.get("artificial_boundary_count", 0)),
        "source_supported_boundary_recall": float(metrics.get("source_supported_boundary_recall", 0.0)),
        "advanced_area_percent": float(metrics.get("advanced_area_percent", 0.0)),
        "selected_boundary_retention": float(metrics.get("selected_boundary_retention", 1.0)),
        "selected_prefilled_detail_count": int(metrics.get("selected_prefilled_detail_count", 0)),
        "selected_forced_merge_count": int(metrics.get("selected_forced_merge_count", 0)),
        "palette_protected_forced_merge_count": int(
            metrics.get("palette_protected_forced_merge_count", 0)
        ),
        "protection_overflow_percent": float(metrics.get("protection_overflow_percent", 0.0)),
        "fidelity": public_fidelity,
        "prefilled_detail_region_ids": list(numbering_stats.prefilled_detail_region_ids or []),  # type: ignore[attr-defined]
        "protected_region_ids": sorted(int(value) for value in metrics.get("protected_region_ids", [])),
        "painted_preview_path": str(option_dir / "painted_reference.png"),
        "template_preview_path": str(option_dir / "numbered_template.png"),
    }


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _publish_selected_option(root: Path, option: dict[str, object]) -> None:
    region_map = option["region_map"]
    source_rgb = option["source_rgb"]
    records = option["records"]
    region_to_color = option["region_to_color"]
    palette_rgb = option["palette_rgb"]
    assignments = option["assignments"]
    painted = option["painted"]
    report = option["report"]
    edge_strength = option.get("edge_strength")

    assert isinstance(region_map, np.ndarray)
    assert isinstance(source_rgb, np.ndarray)
    assert isinstance(painted, np.ndarray)
    public_regions = root / "regions"
    public_regions.mkdir(parents=True, exist_ok=True)
    np.save(public_regions / "region_id_map.npy", region_map)
    save_label_map_png(region_map, public_regions / "initial_region_map.png")
    if isinstance(edge_strength, np.ndarray):
        edge_preview = np.rint(np.clip(edge_strength, 0.0, 1.0) * 255.0).astype(np.uint8)
        save_rgb(public_regions / "boundary_strength.png", np.repeat(edge_preview[..., None], 3, axis=2))
    atomic_write_json(public_regions / "regions.json", [record_to_dict(record) for record in records])  # type: ignore[arg-type]
    atomic_write_json(
        public_regions / "adjacency.json",
        {str(key): sorted(value) for key, value in build_adjacency(region_map).items()},
    )

    public_palette = root / "palette"
    public_palette.mkdir(parents=True, exist_ok=True)
    save_rgb(public_palette / "preview.png", painted)
    atomic_write_json(
        public_palette / "palette.json",
        [{"color_id": index + 1, "rgb": list(value)} for index, value in enumerate(palette_rgb)],  # type: ignore[arg-type]
    )
    atomic_write_json(public_palette / "region_colours.json", assignments)

    cleanup_dir = root / "cleanup"
    cleanup_dir.mkdir(parents=True, exist_ok=True)
    np.save(cleanup_dir / "cleaned_region_map.npy", region_map)
    save_label_map_png(region_map, cleanup_dir / "cleaned_region_map.png")
    atomic_write_json(cleanup_dir / "cleanup_log.json", option["geometry_log"])
    atomic_write_json(cleanup_dir / "regions.json", [record_to_dict(record) for record in records])  # type: ignore[arg-type]

    validation_dir = root / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(validation_dir / "report.json", report.to_dict())  # type: ignore[union-attr]


def _write_failed_validation_summary(root: Path, attempts: list[dict[str, object]]) -> None:
    atomic_write_json(
        root / "validation" / "report.json",
        {
            "status": "fail",
            "metrics": {"attempt_count": len(attempts)},
            "issues": [
                {
                    "code": "all_profiles_failed",
                    "severity": "fail",
                    "message": _failed_attempt_message(attempts),
                    "region_id": None,
                }
            ],
            "attempts": attempts,
            "suggested_actions": [
                "Regenerate the AI image with larger colour areas, simplified fur or texture, and a simpler background."
            ],
        },
    )


def _failed_attempt_message(attempts: list[dict[str, object]]) -> str:
    summaries: list[str] = []
    for difficulty in DIFFICULTY_ORDER:
        difficulty_attempts = [
            attempt for attempt in attempts if attempt.get("difficulty") == difficulty
        ]
        if not difficulty_attempts:
            continue
        metrics = [
            attempt.get("metrics")
            for attempt in difficulty_attempts
            if isinstance(attempt.get("metrics"), dict)
        ]
        region_counts: set[int] = set()
        for attempt in difficulty_attempts:
            attempt_metrics = attempt.get("metrics")
            if not isinstance(attempt_metrics, dict):
                attempt_metrics = {}
            value = attempt_metrics.get(
                "total_region_count",
                attempt.get("actual_region_count"),
            )
            if isinstance(value, (int, float)):
                region_counts.add(int(value))
        palette_sizes = {
            int(item["palette_size"])
            for item in metrics
            if isinstance(item.get("palette_size"), (int, float))
        }
        target_palette_sizes = {
            int(item["target_palette_size"])
            for item in metrics
            if isinstance(item.get("target_palette_size"), (int, float))
        }
        stages = sorted(
            {
                str(item["failure_stage"])
                for item in metrics
                if item.get("failure_stage")
            }
        )
        affected_region_ids = sorted(
            {
                int(region_id)
                for item in metrics
                for region_id in (
                    item.get("affected_region_ids")
                    if isinstance(item.get("affected_region_ids"), list)
                    else []
                )
                if isinstance(region_id, int)
            }
        )
        reasons = sorted(
            {
                str(reason)
                for attempt in difficulty_attempts
                for reason in (attempt.get("rejection_reasons") or [])
            }
        )
        fields = [
            f"{difficulty}: {len(difficulty_attempts)} attempt(s)",
            f"regions={_number_set_summary(region_counts)}",
        ]
        if palette_sizes or target_palette_sizes:
            fields.append(
                "palette="
                f"{_number_set_summary(palette_sizes)}/"
                f"{_number_set_summary(target_palette_sizes)}"
            )
        if stages:
            fields.append(f"stage={','.join(stages)}")
        if affected_region_ids:
            shown_ids = affected_region_ids[:12]
            suffix = ",..." if len(affected_region_ids) > len(shown_ids) else ""
            fields.append(
                "affected-regions=" + ",".join(str(value) for value in shown_ids) + suffix
            )
        if reasons:
            fields.append("reason=" + " | ".join(reasons))
        summaries.append(", ".join(fields))
    return (
        "All bounded local PBN attempts failed validation. "
        + "; ".join(summaries)
        + ". Regenerate a simpler AI image."
    )


def _number_set_summary(values: set[int]) -> str:
    if not values:
        return "unknown"
    minimum, maximum = min(values), max(values)
    return str(minimum) if minimum == maximum else f"{minimum}-{maximum}"


def _simplify_once_per_run(
    provider: ImageSimplificationProvider,
    prepared_source: Path,
    output_path: Path,
    instructions: SimplificationInstructions,
    generation_json: Path,
    max_retries: int,
    force_regenerate: bool = False,
):
    provider_name = str(getattr(provider, "provider_name", "")).strip().lower()
    provider_model = str(getattr(provider, "model", "")).strip()
    cache_key = _simplification_cache_key(provider, instructions, prepared_source)
    if not force_regenerate and output_path.exists() and generation_json.exists():
        metadata = _load_generation_metadata(generation_json)
        if (
            str(metadata.get("provider", "")).strip().lower() == provider_name
            and (not provider_model or str(metadata.get("model", "")).strip() == provider_model)
            and metadata.get("cache_key") == cache_key
        ):
            return type(
                "ExistingSimplification",
                (),
                {
                    "provider": metadata.get("provider", "unknown"),
                    "model": metadata.get("model", "unknown"),
                    "output_path": output_path,
                },
            )()

    attempt = 0
    while True:
        try:
            result = provider.simplify(prepared_source, output_path, instructions)
            atomic_write_json(
                generation_json,
                {
                    "provider": result.provider,
                    "model": result.model,
                    "output_path": str(result.output_path),
                    "cache_key": cache_key,
                    "metadata": result.metadata,
                },
            )
            return result
        except ProviderRequestError as exc:
            if not exc.retryable:
                raise
            attempt += 1
            if attempt > max_retries:
                raise


def _load_generation_metadata(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _simplification_cache_key(
    provider: ImageSimplificationProvider,
    instructions: SimplificationInstructions,
    prepared_source: Path,
) -> dict[str, Any]:
    return {
        "version": 7,
        "provider_request": str(getattr(provider, "cache_fingerprint", "")),
        "prepared_source_sha256": hashlib.sha256(prepared_source.read_bytes()).hexdigest(),
        "instructions": {
            "category": instructions.category,
            "target_palette_size": instructions.target_palette_size,
            "preserve_elements": instructions.preserve_elements,
            "simplify_elements": instructions.simplify_elements,
            "prompt_guidance": instructions.prompt_guidance,
            "preserve_composition": instructions.preserve_composition,
            "preserve_identity": instructions.preserve_identity,
            "output_width": instructions.output_width,
            "output_height": instructions.output_height,
        },
    }


def _parse_settings(settings: dict[str, Any]) -> ParsedAISettings:
    page_size = str(settings.get("page_size", "a3")).strip().lower()
    orientation = str(settings.get("orientation", "portrait")).strip().lower()
    fit_mode = str(settings.get("fit_mode", "cover")).strip().lower()
    PrintSpec(page_size=page_size, orientation=orientation)
    if fit_mode not in {"cover", "contain"}:
        raise ValueError("fit_mode must be cover or contain")
    target_palette_size = _int_setting(settings, "target_palette_size", _int_setting(settings, "target_colors", 24))
    if target_palette_size < 8 or target_palette_size > 40:
        raise ValueError("target_palette_size must be between 8 and 40")
    crop = _normalized_crop(settings.get("crop")) if fit_mode == "cover" else None
    return ParsedAISettings(
        target_palette_size=target_palette_size,
        page_size=page_size,
        orientation=orientation,
        fit_mode=fit_mode,
        crop=crop,
        category=str(settings.get("category", "illustration")),
        preserve_elements=_string_list(settings.get("preserve_elements", [])),
        simplify_elements=_string_list(settings.get("simplify_elements", [])),
        prompt_guidance=_string_setting(settings.get("prompt_guidance", "")),
    )


def _normalized_crop(value: object) -> dict[str, float] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("crop must be a normalized rectangle")
    try:
        crop = {key: float(value[key]) for key in ("x", "y", "width", "height")}
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("crop must contain x, y, width, and height") from exc
    if (
        crop["x"] < 0
        or crop["y"] < 0
        or crop["width"] <= 0
        or crop["height"] <= 0
        or crop["x"] + crop["width"] > 1.000001
        or crop["y"] + crop["height"] > 1.000001
    ):
        raise ValueError("crop must be a normalized rectangle inside the source image")
    return crop


def _build_instructions(
    parsed: ParsedAISettings,
    settings: dict[str, Any],
    output_width: int,
    output_height: int,
) -> SimplificationInstructions:
    return SimplificationInstructions(
        category=parsed.category,
        target_palette_size=parsed.target_palette_size,
        preserve_elements=parsed.preserve_elements,
        simplify_elements=parsed.simplify_elements,
        prompt_guidance=parsed.prompt_guidance,
        preserve_composition=bool(settings.get("preserve_composition", True)),
        preserve_identity=bool(settings.get("preserve_identity", True)),
        output_width=output_width,
        output_height=output_height,
    )


def _int_setting(settings: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(settings.get(key, default))
    except (TypeError, ValueError):
        return default


def _string_setting(value: object) -> str:
    return "" if value is None else str(value).strip()


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _report_progress(
    progress_callback: Callable[[str, int, str], None] | None,
    stage: str,
    progress: int,
    message: str,
) -> None:
    if progress_callback:
        progress_callback(stage, progress, message)
