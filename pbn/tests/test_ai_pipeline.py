from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from ai_pipeline.config import AIProviderConfig, normalize_ai_provider, with_provider_override
from ai_pipeline.detail_protection import (
    apply_difficulty_protection,
    boundary_selection_coverage,
    detail_contour_tolerance,
    load_detail_protection,
)
from ai_pipeline.hierarchical_merge import compact_hierarchically
from ai_pipeline.hybrid_geometry import build_hybrid_geometry
from ai_pipeline.microregions import build_source_microregions
from ai_pipeline.models import (
    ProcessingDiagnosticError,
    SimplificationInstructions,
    SimplificationResult,
)
from ai_pipeline.option_search import (
    OptionCandidate,
    coordinated_density_ceiling,
    density_target,
    has_complete_triplet,
    has_optimal_triplet,
    option_max_attempts,
    select_option_candidates,
)
from ai_pipeline.palette import derive_region_palette, reconcile_palette_after_alignment
from ai_pipeline.pipeline import (
    _attempt_failure_metrics,
    _failed_attempt_message,
    _write_attempt_failure_artifacts,
    generate_ai_image,
)
from ai_pipeline.print_spec import PrintSpec
from ai_pipeline.prompts import build_simplification_prompt
from ai_pipeline.providers_gemini import build_gemini_edit_request
from ai_pipeline.providers_openai import build_openai_edit_request
from ai_pipeline.regions import build_adjacency, build_region_records
from ai_pipeline.quality import assess_ai_source
from ai_pipeline.segmentation import (
    RetryProfile,
    _align_boundaries_to_source,
    _adjacency_pairs,
    _hole_counts,
    _enforce_physical_constraints,
    _merge_region_graph,
    _project_watershed_proposal,
    _source_mm_per_pixel,
    retry_profiles,
    segment_paint_regions,
)
from ai_pipeline.source_prep import prepare_source_image
from ai_pipeline.template_export import (
    LABEL_GRAY_RGB,
    NumberingStats,
    _shared_boundary_polylines,
    build_print_artifacts,
    make_template_image,
)
from ai_pipeline.validation import validate_template_inputs


class FakeProvider:
    provider_name = "fake"
    model = "mock-image"

    def __init__(self) -> None:
        self.calls = 0

    def simplify(
        self,
        source_image: Path,
        output_path: Path,
        instructions: SimplificationInstructions,
    ) -> SimplificationResult:
        self.calls += 1
        with Image.open(source_image) as image:
            width, height = image.size
        # Keep the provider aspect ratio while limiting test cost.
        width, height = ((288, 192) if width > height else (192, 288))
        rgb = np.zeros((height, width, 3), dtype=np.uint8)
        rgb[:, : width // 2] = [215, 55, 45]
        rgb[:, width // 2 :] = [45, 80, 210]
        rgb[height // 3 : 2 * height // 3, width // 3 : 2 * width // 3] = [235, 210, 70]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(rgb, mode="RGB").save(output_path)
        return SimplificationResult(self.provider_name, self.model, output_path, {"calls": self.calls})


class ProviderContractTests(unittest.TestCase):
    def test_prompt_requests_large_paintable_regions_and_user_guidance(self) -> None:
        prompt = build_simplification_prompt(
            SimplificationInstructions(
                target_palette_size=18,
                prompt_guidance="Keep both cats recognizable and simplify the blinds.",
            )
        )

        self.assertIn("Edit the provided image", prompt)
        self.assertIn("exactly 18 flat, reusable colors", prompt)
        self.assertIn("no gradients, antialiasing", prompt)
        self.assertIn("Do not add objects or change the pose or crop", prompt)
        self.assertNotIn("identity", prompt.lower())
        self.assertIn("Keep both cats recognizable", prompt)

    def test_openai_request_uses_provider_canvas_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "input.png"
            Image.new("RGB", (1536, 1024), "white").save(source)
            request = build_openai_edit_request(
                source,
                api_key="test-key",
                model="gpt-image-2",
                instructions=SimplificationInstructions(
                    target_palette_size=17,
                    output_width=1536,
                    output_height=1024,
                ),
            )

        body = request.body.decode("utf-8", errors="replace")
        self.assertIn("1536x1024", body)
        self.assertIn('name="moderation"', body)
        self.assertIn("\r\n\r\nlow\r\n", body)
        self.assertIn("exactly 17 flat, reusable colors", body)
        self.assertIn("Keep the original pose, composition, and crop", body)
        self.assertNotIn("identity", body.lower())
        self.assertIn('name="image"; filename="input.png"', body)

    def test_gemini_request_contains_one_source_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "input.png"
            Image.new("RGB", (32, 24), "white").save(source)
            request = build_gemini_edit_request(
                source,
                api_key="test-key",
                model="gemini-image-test",
                instructions=SimplificationInstructions(category="pet"),
            )

        payload = json.loads(request.body.decode("utf-8"))
        parts = payload["contents"][0]["parts"]
        prompt = next(part["text"] for part in parts if "text" in part)
        self.assertEqual(sum(1 for part in parts if "inline_data" in part), 1)
        self.assertIn("exactly 24 flat, reusable colors", prompt)
        self.assertIn("Keep the original pose, composition, and crop", prompt)
        self.assertEqual(payload["generationConfig"]["responseModalities"], ["TEXT", "IMAGE"])

    def test_provider_alias_is_normalized_without_changing_other_settings(self) -> None:
        config = AIProviderConfig("gemini", "", "", "low", "key", "model", 10, 1)
        overridden = with_provider_override(config, "GPT")
        self.assertEqual(normalize_ai_provider(" google "), "gemini")
        self.assertEqual(overridden.provider, "openai")
        self.assertEqual(overridden.max_retries, 1)


class PrintCompositionTests(unittest.TestCase):
    def test_a_series_dimensions_are_fixed_at_300_dpi(self) -> None:
        self.assertEqual(PrintSpec("a3", "portrait").page_px, (3508, 4961))
        self.assertEqual(PrintSpec("a3", "landscape").page_px, (4961, 3508))
        self.assertEqual(PrintSpec("a4", "portrait").page_px, (2480, 3508))
        self.assertEqual(PrintSpec("a4", "landscape").page_px, (3508, 2480))

    def test_normalized_crop_is_recorded_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.png"
            Image.new("RGB", (400, 300), "red").save(source)
            crop = {"x": 0.1, "y": 0.2, "width": 0.8, "height": 0.8 / np.sqrt(2) * 400 / 300}
            prepared = prepare_source_image(
                source,
                Path(tmp) / "prepared",
                PrintSpec("a3", "landscape"),
                "cover",
                crop,
            )
            manifest = json.loads((Path(tmp) / "prepared" / "crop_manifest.json").read_text())

        self.assertEqual(manifest["crop_pixels"], [40, 60, 360, 286])
        self.assertEqual(manifest["provider_canvas_size"], [1536, 1024])
        self.assertEqual(prepared.content_box, (44, 0, 1492, 1024))

    def test_exif_orientation_is_applied_before_crop_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "rotated.jpg"
            image = Image.new("RGB", (40, 20), "white")
            exif = image.getexif()
            exif[274] = 6
            image.save(source, exif=exif)
            prepare_source_image(source, Path(tmp) / "prepared", PrintSpec(), "contain")
            manifest = json.loads((Path(tmp) / "prepared" / "crop_manifest.json").read_text())

        self.assertEqual(manifest["original_size"], [20, 40])

    def test_invalid_crop_ratio_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.png"
            Image.new("RGB", (100, 100), "white").save(source)
            with self.assertRaisesRegex(ValueError, "aspect ratio"):
                prepare_source_image(
                    source,
                    Path(tmp) / "prepared",
                    PrintSpec("a3", "portrait"),
                    "cover",
                    {"x": 0, "y": 0, "width": 1, "height": 1},
                )


class GeometryAndPaletteTests(unittest.TestCase):
    def test_user_difficulty_profiles_have_required_ranges(self) -> None:
        a3 = retry_profiles(PrintSpec("a3", "portrait"))
        a4 = retry_profiles(PrintSpec("a4", "landscape"))
        self.assertEqual([profile.name for profile in a3], ["easy", "medium", "hard"])
        self.assertEqual([profile.minimum_regions for profile in a3], [250, 450, 700])
        self.assertEqual([profile.region_budget for profile in a3], [500, 750, 1050])
        self.assertEqual([profile.initial_superpixels for profile in a3], [3000, 9450, 9450])
        self.assertEqual([profile.segmentation_budget for profile in a3], [1400, 9450, 9450])
        self.assertEqual([profile.merge_delta_e for profile in a3], [1.5, 0.0, 0.0])
        self.assertEqual([profile.contour_tolerance_mm for profile in a3], [0.25, 0.15, 0.10])
        self.assertEqual([profile.boundary_edge_scales for profile in a3], [(1.4, 2.8), (0.7, 1.4, 2.8), (0.7, 1.4, 2.8)])
        self.assertEqual([profile.boundary_snap_mm for profile in a3], [0.6, 0.6, 0.6])
        self.assertEqual(a4, a3)

    def test_density_ceiling_does_not_preserve_unsupported_cells(self) -> None:
        height, width = 50, 58
        region_map = np.arange(1, height * width + 1, dtype=np.int32).reshape(height, width)
        rgb = np.full((height, width, 3), [120, 125, 130], dtype=np.uint8)
        with tempfile.TemporaryDirectory() as tmp:
            final_map, _, mapping, palette, _ = derive_region_palette(
                rgb,
                region_map,
                Path(tmp) / "first",
                target_palette_size=24,
                target_region_count=1050,
            )
            second_map, _, second_mapping, second_palette, _ = derive_region_palette(
                rgb,
                region_map,
                Path(tmp) / "second",
                target_palette_size=24,
                target_region_count=1050,
            )

        self.assertEqual(len(mapping), 1)
        self.assertEqual(len(np.unique(final_map)), len(mapping))
        self.assertLessEqual(len(palette), 24)
        self.assertEqual(_same_colour_edges(final_map, mapping), 0)
        np.testing.assert_array_equal(second_map, final_map)
        self.assertEqual(second_mapping, mapping)
        self.assertEqual(second_palette, palette)

    def test_density_target_never_merges_a_protected_region(self) -> None:
        region_map = np.ones((20, 60), dtype=np.int32)
        region_map[:, 20:40] = 2
        region_map[:, 40:] = 3
        rgb = np.full((20, 60, 3), [120, 130, 140], dtype=np.uint8)
        rgb[:, :20] = [90, 100, 110]
        rgb[:, 40:] = [170, 180, 190]
        with tempfile.TemporaryDirectory() as tmp:
            final_map, _, mapping, _, _ = derive_region_palette(
                rgb,
                region_map,
                Path(tmp),
                target_palette_size=8,
                protected_region_ids={2},
                protection_scores={2: 1.0},
                boundary_evidence={(1, 2): 1.0, (2, 3): 1.0},
                target_region_count=1,
            )

        self.assertEqual(len(mapping), 3)
        self.assertEqual(len(np.unique(final_map)), 3)
        self.assertEqual(_same_colour_edges(final_map, mapping), 0)

    def test_coordinated_selection_lowers_medium_to_keep_hard(self) -> None:
        candidates = [
            OptionCandidate("easy", 1, 375, 375, "easy:1"),
            OptionCandidate("medium", 1, 750, 750, "medium:1"),
            OptionCandidate("medium", 3, 650, 650, "medium:3"),
            OptionCandidate("hard", 5, 750, 750, "hard:5"),
        ]

        selected = select_option_candidates(candidates)

        self.assertEqual([(item.difficulty, item.region_count) for item in selected], [("easy", 375), ("medium", 650), ("hard", 750)])
        self.assertTrue(has_complete_triplet(candidates))
        self.assertFalse(has_optimal_triplet(candidates))

    def test_selection_rejects_a_harder_option_that_worsens_fidelity(self) -> None:
        candidates = [
            OptionCandidate("easy", 1, 375, 375, "easy:1", 2.0, 0.90),
            OptionCandidate("medium", 1, 750, 600, "medium:1", 2.1, 0.92),
            OptionCandidate("hard", 1, 1050, 900, "hard:1", 2.8, 0.95),
        ]

        selected = select_option_candidates(candidates)

        self.assertEqual([item.difficulty for item in selected], ["easy", "medium"])

    def test_retry_exhaustion_publishes_best_valid_subset(self) -> None:
        candidates = [
            OptionCandidate("easy", 1, 375, 375, "easy:1"),
            OptionCandidate("medium", 1, 750, 750, "medium:1"),
            OptionCandidate("hard", 5, 750, 750, "hard:5"),
        ]

        selected = select_option_candidates(candidates)

        self.assertFalse(has_complete_triplet(candidates))
        self.assertEqual([item.difficulty for item in selected], ["easy", "hard"])

    def test_search_stops_only_at_the_best_density_triplet(self) -> None:
        candidates = [
            OptionCandidate("easy", 1, 375, 375, "easy:1"),
            OptionCandidate("medium", 1, 750, 750, "medium:1"),
            OptionCandidate("hard", 1, 1050, 1050, "hard:1"),
        ]

        self.assertTrue(has_optimal_triplet(candidates))

    def test_attempt_schedules_and_limit_are_bounded(self) -> None:
        self.assertEqual([density_target("easy", index) for index in range(5)], [375, 350, 400, 325, 425])
        self.assertEqual([density_target("medium", index) for index in range(5)], [750, 700, 650, 600, 550])
        self.assertEqual([density_target("hard", index) for index in range(5)], [1050, 975, 900, 825, 750])
        with patch.dict("os.environ", {"PBN_OPTION_MAX_ATTEMPTS": "99"}):
            self.assertEqual(option_max_attempts(), 5)
        with patch.dict("os.environ", {"PBN_OPTION_MAX_ATTEMPTS": "2"}):
            self.assertEqual(option_max_attempts(), 2)

    def test_later_medium_retry_coordinates_with_the_densest_valid_hard(self) -> None:
        candidates = [
            OptionCandidate("hard", 1, 1050, 472, "hard:1"),
            OptionCandidate("hard", 2, 975, 450, "hard:2"),
        ]

        self.assertEqual(coordinated_density_ceiling("medium", 700, candidates), 429)
        self.assertEqual(
            coordinated_density_ceiling(
                "medium",
                650,
                candidates,
                [(750, 472), (429, 336)],
            ),
            589,
        )
        self.assertEqual(
            coordinated_density_ceiling(
                "medium",
                600,
                candidates,
                [(750, 472), (429, 336), (589, 472)],
            ),
            509,
        )
        self.assertEqual(coordinated_density_ceiling("easy", 350, candidates), 350)
        self.assertEqual(coordinated_density_ceiling("medium", 750, []), 750)

    def test_palette_is_capped_and_equal_colour_neighbours_are_merged(self) -> None:
        region_map = np.zeros((30, 90), dtype=np.int32)
        region_map[:, :30] = 1
        region_map[:, 30:60] = 2
        region_map[:, 60:] = 3
        rgb = np.zeros((30, 90, 3), dtype=np.uint8)
        rgb[:, :30] = [210, 50, 40]
        rgb[:, 30:60] = [211, 49, 40]
        rgb[:, 60:] = [30, 60, 220]
        with tempfile.TemporaryDirectory() as tmp:
            final_map, painted, mapping, palette, _ = derive_region_palette(
                rgb,
                region_map,
                Path(tmp) / "first",
                target_palette_size=2,
            )
            second_map, second_painted, second_mapping, second_palette, _ = derive_region_palette(
                rgb,
                region_map,
                Path(tmp) / "second",
                target_palette_size=2,
            )

        self.assertLessEqual(len(palette), 2)
        self.assertEqual(len(np.unique(final_map)), 2)
        self.assertEqual(set(mapping), {1, 2})
        self.assertEqual(painted.shape, rgb.shape)
        self.assertEqual(_same_colour_edges(final_map, mapping), 0)
        np.testing.assert_array_equal(second_map, final_map)
        np.testing.assert_array_equal(second_painted, painted)
        self.assertEqual(second_mapping, mapping)
        self.assertEqual(second_palette, palette)

    def test_slico_segmentation_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "fur_blinds.png"
            _write_fur_blinds_fixture(source)
            with Image.open(source) as fixture:
                fixture.resize((720, 480), Image.Resampling.NEAREST).save(source)
            profile = RetryProfile("test", 80, 6.0, 0.35)
            first, _, _ = segment_paint_regions(source, root / "first", PrintSpec("a4", "landscape"), profile)
            second, _, _ = segment_paint_regions(source, root / "second", PrintSpec("a4", "landscape"), profile)

        np.testing.assert_array_equal(first, second)
        self.assertLessEqual(len(np.unique(first)), profile.region_budget)

    def test_hard_protected_boundary_is_not_merged_to_hit_budget(self) -> None:
        rgb = np.zeros((80, 120, 3), dtype=np.uint8)
        rgb[:, :60] = [245, 245, 245]
        rgb[:, 60:] = [15, 15, 15]
        labels = np.ones((80, 120), dtype=np.int32)
        labels[:, 60:] = 2

        merged, protected_mask, log = _merge_region_graph(rgb, labels, region_budget=1, merge_delta_e=999.0)

        self.assertEqual(len(np.unique(merged)), 2)
        self.assertTrue(protected_mask.any())
        self.assertGreater(log[0]["protected_merge_veto_count"], 0)
        self.assertTrue(log[0]["budget_overflow"])
        self.assertIn("maximum_merged_protection_score", log[0])
        self.assertIn("merge_reason_counts", log[0])

    def test_protected_score_survives_constituent_graph_merge(self) -> None:
        rgb = np.zeros((80, 150, 3), dtype=np.uint8)
        rgb[:, :100] = [235, 235, 235]
        rgb[:, 100:] = [20, 20, 20]
        labels = np.ones((80, 150), dtype=np.int32)
        labels[:, 50:100] = 2
        labels[:, 100:] = 3

        merged, _, _ = _merge_region_graph(rgb, labels, region_budget=1, merge_delta_e=999.0)

        self.assertEqual(len(np.unique(merged)), 2)

    def test_printer_floor_merges_only_the_unrenderable_protected_detail(self) -> None:
        labels = np.ones((1000, 1000), dtype=np.int32)
        labels[100:106, 100:106] = 2
        labels[200:203, 200:203] = 3
        rgb = np.full((1000, 1000, 3), 220, dtype=np.uint8)
        rgb[100:106, 100:106] = [30, 30, 30]
        rgb[200:203, 200:203] = [30, 30, 30]
        protected = np.zeros(labels.shape, dtype=bool)
        protected[98:108, 98:108] = True
        protected[198:205, 198:205] = True

        cleaned, _ = _enforce_physical_constraints(
            rgb,
            labels,
            PrintSpec("a4", "portrait"),
            protected,
            min_area_mm2=12.0,
            min_width_mm=1.5,
            min_label_pocket_mm=4.0,
        )

        component_areas = sorted(np.bincount(cleaned.ravel())[1:])
        self.assertEqual(len(component_areas), 2)
        self.assertEqual(component_areas[0], 36)

    def test_geometry_cleanup_does_not_merge_only_for_a_four_mm_label_pocket(self) -> None:
        labels = np.ones((1000, 1000), dtype=np.int32)
        labels[100:110, 100:110] = 2
        rgb = np.full((1000, 1000, 3), 220, dtype=np.uint8)
        rgb[100:110, 100:110] = [80, 90, 100]

        cleaned, _ = _enforce_physical_constraints(
            rgb,
            labels,
            PrintSpec("a4", "portrait"),
            np.zeros(labels.shape, dtype=bool),
            min_area_mm2=0.5,
            min_width_mm=0.5,
            min_label_pocket_mm=4.0,
        )

        self.assertEqual(len(np.unique(cleaned)), 2)

    def test_source_edge_alignment_is_bounded_deterministic_and_topology_safe(self) -> None:
        height, width = 240, 768
        yy = np.arange(height)
        source_edge = np.rint(width / 2 + 20 * np.sin(yy / 28.0)).astype(np.int32)
        labels = np.ones((height, width), dtype=np.int32)
        rgb = np.zeros((height, width, 3), dtype=np.uint8)
        for y, edge_x in enumerate(source_edge):
            rgb[y, :edge_x] = [225, 70, 55]
            rgb[y, edge_x:] = [55, 90, 220]
            jagged_x = int(np.clip(edge_x + (2 if (y // 4) % 2 else -2), 1, width - 1))
            labels[y, jagged_x:] = 2
        before_pairs = _adjacency_pairs(labels)
        with tempfile.TemporaryDirectory():
            first, first_log, _ = _align_boundaries_to_source(
                rgb,
                labels,
                PrintSpec("a4", "landscape"),
                edge_scales=(0.7, 1.4, 2.8),
            )
            second, second_log, _ = _align_boundaries_to_source(
                rgb,
                labels,
                PrintSpec("a4", "landscape"),
                edge_scales=(0.7, 1.4, 2.8),
            )

        np.testing.assert_array_equal(first, second)
        self.assertEqual(first_log, second_log)
        self.assertEqual(_adjacency_pairs(first), before_pairs)
        self.assertEqual(set(np.unique(first)), {1, 2})
        self.assertTrue(first_log["topology_preserved"])
        self.assertGreaterEqual(first_log["source_edge_alignment_gain"], 0.0)
        self.assertLessEqual(first_log["actual_snap_radius_mm"], 0.6 + 1e-6)

    def test_source_edge_alignment_reduces_peninsula_widening_without_removing_it(self) -> None:
        height, width = 220, 768
        source = np.ones((height, width), dtype=np.int32)
        source[60:160, 260:430] = 2
        source[106:114, 430:540] = 2
        labels = np.ones_like(source)
        labels[60:160, 260:430] = 2
        labels[104:116, 430:540] = 2
        rgb = np.full((height, width, 3), [230, 220, 205], dtype=np.uint8)
        rgb[source == 2] = [75, 100, 175]
        before_area = int(np.count_nonzero(labels == 2))

        aligned, log, _ = _align_boundaries_to_source(
            rgb,
            labels,
            PrintSpec("a4", "landscape"),
            edge_scales=(0.7, 1.4, 2.8),
        )

        self.assertLess(int(np.count_nonzero(aligned == 2)), before_area)
        self.assertTrue(np.any(aligned[106:114, 450:520] == 2))
        self.assertEqual(_hole_counts(aligned, {1, 2}), _hole_counts(labels, {1, 2}))
        self.assertTrue(log["topology_preserved"])

    def test_source_edge_projection_does_not_change_a_frozen_region(self) -> None:
        labels = np.ones((20, 40), dtype=np.int32)
        labels[:, 20:] = 2
        proposal = labels.copy()
        proposal[:10, 19] = 2
        proposal[10:, 20] = 1
        source_lab = np.zeros((20, 40, 3), dtype=np.float64)
        median_lut = np.zeros((3, 3), dtype=np.float64)

        movable, _ = _project_watershed_proposal(
            labels,
            proposal,
            source_lab,
            median_lut,
            {(1, 2)},
            set(),
        )
        projected, _ = _project_watershed_proposal(
            labels,
            proposal,
            source_lab,
            median_lut,
            {(1, 2)},
            {2},
        )

        self.assertFalse(np.array_equal(movable, labels))
        np.testing.assert_array_equal(projected == 2, labels == 2)

    def test_source_edge_alignment_returns_valid_baseline_when_all_proposals_fail(self) -> None:
        labels = np.ones((40, 80), dtype=np.int32)
        labels[:, 40:] = 2
        candidate = np.ones_like(labels)
        candidate[:, 39:] = 2
        rgb = np.full((40, 80, 3), [220, 70, 55], dtype=np.uint8)
        rgb[:, 40:] = [55, 90, 220]
        violation = {
            "region_id": 2,
            "area_pixels": 10,
            "area_mm2": 0.6,
            "estimated_width_mm": 0.49,
            "area_failed": False,
            "width_failed": True,
        }

        def floor_violations(label_map: np.ndarray, *_: object) -> list[dict[str, object]]:
            return [] if np.array_equal(label_map, labels) else [violation]

        with (
            patch(
                "ai_pipeline.segmentation._project_watershed_proposal",
                return_value=(candidate, 1),
            ),
            patch(
                "ai_pipeline.segmentation._printer_floor_violations",
                side_effect=floor_violations,
            ),
        ):
            aligned, log, _ = _align_boundaries_to_source(
                rgb,
                labels,
                PrintSpec("a4", "landscape"),
                edge_scales=(0.7, 1.4, 2.8),
            )

        np.testing.assert_array_equal(aligned, labels)
        self.assertEqual(log["status"], "skipped")
        self.assertEqual(log["reason"], "all_snap_proposals_rejected")
        self.assertEqual(log["changed_pixel_count"], 0)
        self.assertEqual(log["actual_snap_radius_mm"], 0.0)
        self.assertGreater(log["rejected_radius_count"], 0)

    def test_source_edge_alignment_failure_reports_affected_regions(self) -> None:
        labels = np.ones((40, 80), dtype=np.int32)
        labels[:, 40:] = 2
        rgb = np.full((40, 80, 3), [220, 70, 55], dtype=np.uint8)
        rgb[:, 40:] = [55, 90, 220]
        violation = {
            "region_id": 2,
            "area_pixels": 10,
            "area_mm2": 0.6,
            "estimated_width_mm": 0.49,
            "area_failed": False,
            "width_failed": True,
        }

        with patch(
            "ai_pipeline.segmentation._printer_floor_violations",
            return_value=[violation],
        ):
            with self.assertRaises(ProcessingDiagnosticError) as raised:
                _align_boundaries_to_source(
                    rgb,
                    labels,
                    PrintSpec("a4", "landscape"),
                    edge_scales=(0.7, 1.4, 2.8),
                )

        self.assertEqual(raised.exception.diagnostics["affected_region_ids"], [2])
        self.assertEqual(
            raised.exception.diagnostics["baseline_printer_floor_violations"],
            [violation],
        )
        rejected = raised.exception.diagnostics["rejected_radii"]
        self.assertEqual(rejected[0]["printer_floor_violations"], [violation])

    def test_boundary_snap_uses_physical_page_scale(self) -> None:
        for page_size in ("a3", "a4"):
            for orientation, shape in (("landscape", (1024, 1448)), ("portrait", (1448, 1024))):
                mm_per_pixel = _source_mm_per_pixel(shape, PrintSpec(page_size, orientation))
                radius = max(1, int(np.floor(0.6 / mm_per_pixel)))
                self.assertLessEqual(radius * mm_per_pixel, 0.6 + 1e-6)

    def test_protected_same_colour_neighbours_keep_distinct_palette_assignments(self) -> None:
        rgb = np.zeros((30, 90, 3), dtype=np.uint8)
        rgb[:, :30] = [130, 130, 130]
        rgb[:, 30:60] = [132, 132, 132]
        rgb[:, 60:] = [20, 20, 20]
        region_map = np.ones((30, 90), dtype=np.int32)
        region_map[:, 30:60] = 2
        region_map[:, 60:] = 3
        with tempfile.TemporaryDirectory() as tmp:
            final_map, _, mapping, palette, _ = derive_region_palette(
                rgb,
                region_map,
                Path(tmp),
                target_palette_size=2,
                protected_region_ids={1, 2},
                protection_scores={1: 1.0, 2: 1.0},
            )

        left = int(final_map[10, 10])
        middle = int(final_map[10, 40])
        self.assertNotEqual(left, middle)
        self.assertNotEqual(mapping[left], mapping[middle])
        self.assertLessEqual(len(palette), 2)


class ProtectedMicroregionTests(unittest.TestCase):
    def test_mask_feathering_and_difficulty_protection_are_source_gated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "input"
            input_dir.mkdir(parents=True)
            mask = np.zeros((100, 100), dtype=np.uint8)
            mask[:, 45:55] = 255
            Image.fromarray(mask, mode="L").save(input_dir / "detail_protection.png")
            protection = load_detail_protection(root, mask.shape, PrintSpec("a4", "landscape"))

        self.assertIsNotNone(protection)
        assert protection is not None
        self.assertEqual(protection.weight[50, 50], 1.0)
        self.assertGreater(protection.weight[50, 44], 0.0)
        labels = np.ones(mask.shape, dtype=np.int32)
        labels[:, 50:] = 2
        coverage = boundary_selection_coverage(labels, protection.weight)
        contrasting = np.full((*mask.shape, 3), [230, 220, 200], dtype=np.uint8)
        contrasting[:, 50:] = [45, 65, 160]
        hard_evidence, _, _, hard_pairs, hard_metrics = apply_difficulty_protection(
            contrasting,
            labels,
            {(1, 2): 0.01},
            coverage,
            "hard",
        )
        flat = np.full((*mask.shape, 3), 150, dtype=np.uint8)
        flat_evidence, _, _, flat_pairs, _ = apply_difficulty_protection(
            flat,
            labels,
            {(1, 2): 0.0},
            coverage,
            "hard",
        )

        self.assertGreaterEqual(hard_evidence[(1, 2)], 0.70)
        self.assertIn((1, 2), hard_pairs)
        self.assertEqual(hard_metrics["difficulty_multiplier"], 11.6)
        self.assertEqual(hard_metrics["evidence_floor_applied_boundary_count"], 1)
        self.assertEqual(flat_evidence[(1, 2)], 0.0)
        self.assertEqual(flat_pairs, set())

    def test_detail_contours_receive_only_a_small_local_smoothing_nudge(self) -> None:
        self.assertAlmostEqual(detail_contour_tolerance(0.25), 0.3625)
        self.assertAlmostEqual(detail_contour_tolerance(0.15), 0.2175)
        self.assertAlmostEqual(detail_contour_tolerance(0.10), 0.145)

    def test_exact_microregions_collapse_indistinguishable_singletons(self) -> None:
        rgb = np.full((80, 120, 3), [120, 120, 120], dtype=np.uint8)
        rgb[20:60, 30:90] = [121, 121, 121]
        zone = np.ones(rgb.shape[:2], dtype=bool)
        result = build_source_microregions(rgb, zone)

        self.assertEqual(result.metrics["initial_exact_component_count"], 2)
        self.assertEqual(result.metrics["final_microregion_count"], 1)

    def test_hybrid_geometry_replaces_whole_intersecting_slic_atoms(self) -> None:
        rgb = np.full((120, 180, 3), [220, 210, 190], dtype=np.uint8)
        rgb[35:85, 45:75] = [60, 80, 170]
        base = np.ones((120, 180), dtype=np.int32)
        base[:, 90:] = 2
        mask = np.zeros((120, 180), dtype=bool)
        mask[40:80, 50:70] = True
        protection = type("Protection", (), {
            "mask": mask,
            "weight": mask.astype(np.float32),
            "coverage_percent": 100.0 * float(mask.mean()),
            "sha256": "test",
            "transition_source_pixels": 1,
        })()

        result = build_hybrid_geometry(rgb, base, protection, PrintSpec("a4", "landscape"))

        self.assertGreaterEqual(result.metrics["final_microregion_count"], 2)
        self.assertGreater(result.metrics["advanced_zone_percent"], result.metrics["selected_area_percent"])
        self.assertGreater(result.metrics["unsupported_transition_merge_count"], 0)
        self.assertEqual(result.metrics["unsupported_transition_edge_count"], 0)
        self.assertEqual(result.label_map.shape, base.shape)
        self.assertTrue(np.all(result.label_map > 0))

    def test_protected_palette_conflict_uses_deterministic_fallback_merge(self) -> None:
        labels = np.ones((40, 80), dtype=np.int32)
        labels[:, 40:] = 2
        rgb = np.full((40, 80, 3), [130, 130, 130], dtype=np.uint8)
        rgb[:, 40:] = [132, 132, 132]
        evidence = {(1, 2): 0.90}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            natural_map, _, _, natural_palette, _ = derive_region_palette(
                rgb,
                labels,
                root / "natural",
                target_palette_size=1,
                boundary_evidence=evidence,
                target_region_count=2,
                dynamic_compaction=True,
                maximum_region_count=2,
            )
            natural_metrics = json.loads((root / "natural" / "fidelity_metrics.json").read_text())
            repeated_map, _, _, repeated_palette, _ = derive_region_palette(
                rgb,
                labels,
                root / "natural-repeated",
                target_palette_size=1,
                boundary_evidence=evidence,
                target_region_count=2,
                dynamic_compaction=True,
                maximum_region_count=2,
            )
            repeated_metrics = json.loads(
                (root / "natural-repeated" / "fidelity_metrics.json").read_text()
            )
            selected_map, _, _, _, _ = derive_region_palette(
                rgb,
                labels,
                root / "selected",
                target_palette_size=1,
                boundary_evidence=evidence,
                target_region_count=2,
                dynamic_compaction=True,
                maximum_region_count=2,
                user_protected_pairs={(1, 2)},
            )
            metrics = json.loads((root / "selected" / "fidelity_metrics.json").read_text())

        np.testing.assert_array_equal(repeated_map, natural_map)
        self.assertEqual(repeated_palette, natural_palette)
        self.assertEqual(len(natural_palette), 1)
        self.assertEqual(len(np.unique(natural_map)), 1)
        self.assertEqual(natural_metrics, repeated_metrics)
        self.assertEqual(natural_metrics["palette_protected_forced_merge_count"], 1)
        fallback = natural_metrics["palette_protected_forced_merges"][0]
        self.assertEqual((fallback["left_region_id"], fallback["right_region_id"]), (1, 2))
        self.assertIn("reconstruction_loss_delta_e_00", fallback)
        self.assertEqual(len(np.unique(selected_map)), 1)
        self.assertEqual(metrics["selected_forced_merge_count"], 1)
        self.assertEqual(metrics["palette_protected_forced_merge_count"], 0)

    def test_failed_attempt_diagnostics_are_saved_and_summarized_once(self) -> None:
        labels = np.ones((20, 30), dtype=np.int32)
        labels[:, 15:] = 2
        rgb = np.full((20, 30, 3), 128, dtype=np.uint8)
        diagnostics = {
            "affected_region_ids": [2],
            "rejected_radius_count": 2,
        }
        metrics = _attempt_failure_metrics(
            labels,
            rgb,
            PrintSpec("a4", "landscape"),
            24,
            24,
            "source_edge_alignment",
            diagnostics,
        )
        reason = "processing_error: source-edge alignment failed"
        attempts = [
            {
                "difficulty": "easy",
                "attempt": attempt,
                "actual_region_count": 2,
                "metrics": metrics,
                "rejection_reasons": [reason],
            }
            for attempt in (1, 2)
        ]

        with tempfile.TemporaryDirectory() as tmp:
            attempt_dir = Path(tmp) / ".attempts" / "easy" / "1"
            _write_attempt_failure_artifacts(
                attempt_dir,
                reason,
                metrics,
                labels,
            )
            saved = json.loads(
                (attempt_dir / "failure" / "diagnostics.json").read_text(encoding="utf-8")
            )
            report = json.loads(
                (attempt_dir / "validation" / "report.json").read_text(encoding="utf-8")
            )

        message = _failed_attempt_message(attempts)
        self.assertEqual(saved["metrics"]["failure_stage"], "source_edge_alignment")
        self.assertEqual(report["issues"][0]["region_id"], 2)
        self.assertEqual(message.count(reason), 1)
        self.assertIn("easy: 2 attempt(s)", message)
        self.assertIn("regions=2", message)
        self.assertIn("affected-regions=2", message)
        self.assertNotIn("?", message)

    def test_post_alignment_palette_reconciliation_removes_new_artificial_edge(self) -> None:
        labels = np.ones((40, 80), dtype=np.int32)
        labels[:, 40:] = 2
        rgb = np.full((40, 80, 3), [178, 178, 178], dtype=np.uint8)
        rgb[:, 40:] = [180, 180, 180]

        resolved, mapping, metrics = reconcile_palette_after_alignment(
            rgb,
            labels,
            [(170, 170, 170), (190, 190, 190)],
            set(),
            {},
            {(1, 2): 0.0},
            set(),
        )

        self.assertEqual(len(np.unique(resolved)), 1)
        self.assertEqual(set(mapping), {1})
        self.assertGreater(metrics["palette_conflict_merge_count"], 0)
        self.assertEqual(metrics["artificial_boundary_count"], 0)

    def test_dynamic_merger_uses_protected_overflow_and_updates_adjacency(self) -> None:
        height, width = 80, 280
        labels = np.zeros((height, width), dtype=np.int32)
        rgb = np.zeros((height, width, 3), dtype=np.uint8)
        palette = np.asarray([[50.0, 40.0, 20.0], [80.0, -30.0, 25.0]], dtype=np.float64)
        evidence: dict[tuple[int, int], float] = {}
        selected: set[tuple[int, int]] = set()
        for index in range(14):
            left, right = index * 20, (index + 1) * 20
            labels[:, left:right] = index + 1
            rgb[:, left:right] = [190, 80 + index * 3, 60] if index % 2 else [60, 100, 190]
            if index:
                pair = (index, index + 1)
                evidence[pair] = 0.90
                selected.add(pair)

        result = compact_hierarchically(
            rgb,
            labels,
            palette,
            {},
            evidence,
            target_region_count=10,
            maximum_region_count=11,
            user_protected_pairs=selected,
        )

        self.assertEqual(len(np.unique(result.label_map)), 11)
        self.assertEqual(result.metrics["protection_overflow_percent"], 10.0)
        self.assertEqual(result.metrics["selected_forced_merge_count"], 3)
        self.assertTrue(result.metrics["dynamic_adjacency_updates"])


class ValidationAndNumberingTests(unittest.TestCase):
    def test_shared_boundary_paths_draw_every_internal_edge_once(self) -> None:
        region_map = np.ones((12, 18), dtype=np.int32)
        region_map[:, 9:] = 2
        region_map[6:, 4:9] = 3
        paths = _shared_boundary_polylines(region_map)
        traced_segments = sum(len(points) if closed else len(points) - 1 for points, closed in paths)
        expected_segments = int(
            np.count_nonzero(region_map[:, 1:] != region_map[:, :-1])
            + np.count_nonzero(region_map[1:, :] != region_map[:-1, :])
        )

        self.assertEqual(traced_segments, expected_segments)
        self.assertTrue(all(len(points) >= 2 for points, _ in paths))

    def test_valid_geometry_passes_all_hard_checks(self) -> None:
        region_map = np.ones((140, 100), dtype=np.int32)
        region_map[:, 50:] = 2
        rgb = np.zeros((140, 100, 3), dtype=np.uint8)
        rgb[:, :50] = [210, 80, 60]
        rgb[:, 50:] = [60, 90, 210]
        mapping = {1: 1, 2: 2}
        palette = [(210, 80, 60), (60, 90, 210)]
        records = build_region_records(region_map, rgb, build_adjacency(region_map), mapping)
        painted = np.where((region_map == 1)[..., None], palette[0], palette[1]).astype(np.uint8)
        stats = NumberingStats(2, 0, 0, [], [], 4.2)
        with tempfile.TemporaryDirectory() as tmp:
            report = validate_template_inputs(
                region_map,
                records,
                mapping,
                Path(tmp),
                2,
                print_spec=PrintSpec("a4", "portrait"),
                region_budget=10,
                numbering_stats=stats,
                palette_rgb=palette,
                painted_reference=painted,
                template_size=PrintSpec("a4", "portrait").page_px,
            )

        self.assertEqual(report.status, "pass")

    def test_unnumbered_and_same_colour_adjacency_are_hard_failures(self) -> None:
        region_map = np.ones((80, 80), dtype=np.int32)
        region_map[:, 40:] = 2
        rgb = np.full((80, 80, 3), 150, dtype=np.uint8)
        mapping = {1: 1, 2: 1}
        records = build_region_records(region_map, rgb, build_adjacency(region_map), mapping)
        stats = NumberingStats(1, 0, 0, [2], [], 4.1)
        with tempfile.TemporaryDirectory() as tmp:
            report = validate_template_inputs(
                region_map,
                records,
                mapping,
                Path(tmp),
                1,
                numbering_stats=stats,
                palette_rgb=[(150, 150, 150)],
            )

        codes = {issue.code for issue in report.issues}
        self.assertEqual(report.status, "fail")
        self.assertIn("unnumbered_region", codes)
        self.assertIn("same_color_adjacency", codes)

    def test_long_region_repeats_its_number(self) -> None:
        region_map = np.ones((18, 120), dtype=np.int32)
        _, stats = make_template_image(region_map, {1: 7}, [(210, 210, 210)], font_size=14)
        self.assertGreater(stats.repeated_numbers, 0)
        self.assertEqual(stats.unnumbered_regions, 0)

    def test_prefilled_detail_uses_palette_colour_without_number(self) -> None:
        region_map = np.ones((40, 60), dtype=np.int32)
        region_map[17:23, 27:33] = 2
        image, _, stats = build_print_artifacts(
            region_map,
            {1: 1, 2: 2},
            [(230, 230, 230), (220, 40, 60)],
            PrintSpec("a4", "landscape"),
            0.3,
            prefilled_detail_region_ids={2},
            protected_region_ids={2},
        )
        self.assertEqual(image.size, PrintSpec("a4", "landscape").page_px)
        self.assertEqual(stats.prefilled_detail_region_ids, [2])
        self.assertEqual(stats.unnumbered_regions, 0)

    def test_labels_shrink_to_three_points_then_prefill_protected_detail(self) -> None:
        region_map = np.ones((1000, 1000), dtype=np.int32)
        region_map[100:900, 500:505] = 2
        region_map[500, 700] = 3
        mapping = {1: 1, 2: 2, 3: 3}
        palette = [(235, 235, 235), (210, 80, 60), (30, 30, 30)]

        image, _, stats = build_print_artifacts(
            region_map,
            mapping,
            palette,
            PrintSpec("a4", "portrait"),
            0.3,
            protected_region_ids={2, 3},
        )
        replay, _, replay_stats = build_print_artifacts(
            region_map,
            mapping,
            palette,
            PrintSpec("a4", "portrait"),
            0.3,
            protected_region_ids={2, 3},
            label_plan=stats.label_plan,
        )

        self.assertIn(2, stats.adaptive_label_region_ids or [])
        self.assertGreaterEqual(stats.minimum_label_height_mm, 1.0)
        self.assertGreaterEqual(stats.minimum_label_font_pt, 1.0 / 25.4 * 72.0)
        self.assertIn(3, stats.prefilled_detail_region_ids or [])
        self.assertEqual(stats.unnumbered_regions, 0)
        self.assertTrue(np.any(np.all(np.asarray(image) == np.asarray(LABEL_GRAY_RGB), axis=2)))
        self.assertTrue(np.array_equal(np.asarray(image), np.asarray(replay)))
        self.assertEqual(stats.to_dict(), replay_stats.to_dict())

    def test_labels_use_discrete_physical_heights_and_measure_full_number(self) -> None:
        region_map = np.ones((1000, 1000), dtype=np.int32)
        region_map[:, 400:418] = 2
        region_map[:, 600:618] = 3
        mapping = {1: 1, 2: 7, 3: 18}
        palette = [(index * 10, index * 10, index * 10) for index in range(1, 19)]

        _, _, stats = build_print_artifacts(
            region_map,
            mapping,
            palette,
            PrintSpec("a4", "portrait"),
            0.3,
        )

        placements = stats.label_plan["placements"] if stats.label_plan else []
        one_digit = [float(item["height_mm"]) for item in placements if int(item["region_id"]) == 2]
        two_digit = [float(item["height_mm"]) for item in placements if int(item["region_id"]) == 3]
        self.assertTrue(one_digit)
        self.assertTrue(two_digit)
        self.assertIn(one_digit[0], {1.0, 2.0, 3.0, 4.0})
        self.assertIn(two_digit[0], {1.0, 2.0, 3.0, 4.0})
        self.assertLessEqual(two_digit[0], one_digit[0])
        self.assertEqual(sum((stats.label_height_counts or {}).values()), stats.placed_numbers)

    def test_artificial_boundaries_and_global_reconstruction_are_hard_failures(self) -> None:
        region_map = np.ones((100, 100), dtype=np.int32)
        region_map[:, 50:] = 2
        rgb = np.full((100, 100, 3), 200, dtype=np.uint8)
        mapping = {1: 1, 2: 2}
        palette = [(200, 200, 200), (180, 180, 180)]
        records = build_region_records(region_map, rgb, build_adjacency(region_map), mapping)
        stats = NumberingStats(2, 0, 0, [], minimum_label_height_mm=1.0)
        with tempfile.TemporaryDirectory() as tmp:
            report = validate_template_inputs(
                region_map,
                records,
                mapping,
                Path(tmp),
                2,
                numbering_stats=stats,
                artificial_boundary_count=1,
                mean_reconstruction_delta_e_00=6.1,
            )

        codes = {issue.code for issue in report.issues}
        self.assertIn("artificial_boundary", codes)
        self.assertIn("global_reconstruction_loss", codes)

    def test_prefilled_area_over_three_percent_fails_validation(self) -> None:
        region_map = np.ones((100, 100), dtype=np.int32)
        region_map[:, :5] = 2
        rgb = np.full((100, 100, 3), 230, dtype=np.uint8)
        rgb[:, :5] = [200, 50, 50]
        mapping = {1: 1, 2: 2}
        palette = [(230, 230, 230), (200, 50, 50)]
        records = build_region_records(region_map, rgb, build_adjacency(region_map), mapping)
        _, _, stats = build_print_artifacts(
            region_map,
            mapping,
            palette,
            PrintSpec("a4", "portrait"),
            0.3,
            prefilled_detail_region_ids={2},
            protected_region_ids={2},
        )
        with tempfile.TemporaryDirectory() as tmp:
            report = validate_template_inputs(
                region_map,
                records,
                mapping,
                Path(tmp),
                2,
                numbering_stats=stats,
                palette_rgb=palette,
                protected_region_ids={2},
            )
        self.assertIn("prefilled_area_exceeded", {issue.code for issue in report.issues})

    def test_ordinary_region_cannot_use_prefilled_fallback(self) -> None:
        region_map = np.ones((40, 80), dtype=np.int32)
        region_map[:, 40:] = 2
        rgb = np.full((40, 80, 3), 180, dtype=np.uint8)
        mapping = {1: 1, 2: 2}
        records = build_region_records(region_map, rgb, build_adjacency(region_map), mapping)
        stats = NumberingStats(
            placed_numbers=1,
            repeated_numbers=0,
            printed_dark_details=0,
            unnumbered_region_ids=[],
            prefilled_detail_region_ids=[2],
            minimum_label_font_pt=7.0,
        )
        with tempfile.TemporaryDirectory() as tmp:
            report = validate_template_inputs(
                region_map,
                records,
                mapping,
                Path(tmp),
                2,
                numbering_stats=stats,
                palette_rgb=[(180, 180, 180), (120, 120, 120)],
                protected_region_ids=set(),
            )

        self.assertIn("ordinary_region_prefilled", {issue.code for issue in report.issues})

    def test_region_budget_rejects_more_than_ten_percent_overflow(self) -> None:
        region_map = np.zeros((120, 120), dtype=np.int32)
        for index in range(12):
            region_map[:, index * 10 : (index + 1) * 10] = index + 1
        rgb = np.full((120, 120, 3), 180, dtype=np.uint8)
        mapping = {index: index for index in range(1, 13)}
        records = build_region_records(region_map, rgb, build_adjacency(region_map), mapping)
        stats = NumberingStats(12, 0, 0, [], minimum_label_font_pt=7.0)
        with tempfile.TemporaryDirectory() as tmp:
            report = validate_template_inputs(
                region_map,
                records,
                mapping,
                Path(tmp),
                12,
                region_budget=10,
                numbering_stats=stats,
                palette_rgb=[(index * 15, index * 15, index * 15) for index in range(1, 13)],
            )

        self.assertIn("protected_budget_exceeded", {issue.code for issue in report.issues})


class AIQualityAssessmentTests(unittest.TestCase):
    def test_flat_source_passes_and_gradient_source_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            flat = np.full((256, 256, 3), [225, 210, 180], dtype=np.uint8)
            flat[64:192, 64:192] = [70, 80, 100]
            flat_path = root / "flat.png"
            Image.fromarray(flat, mode="RGB").save(flat_path)
            ramp = np.linspace(20, 235, 256, dtype=np.float64)
            x, y = np.meshgrid(ramp, ramp)
            blue = 127.5 + 107.5 * np.sin((x + y) * np.pi / 96.0)
            gradient = np.clip(np.stack([x, y, blue], axis=2), 0, 255).astype(np.uint8)
            gradient_path = root / "gradient.png"
            Image.fromarray(gradient, mode="RGB").save(gradient_path)

            flat_report = assess_ai_source(flat_path, root / "flat-report", 24, PrintSpec("a3", "landscape"))
            gradient_report = assess_ai_source(gradient_path, root / "gradient-report", 24, PrintSpec("a3", "landscape"))
            repeated_gradient_report = assess_ai_source(gradient_path, root / "gradient-report-2", 24, PrintSpec("a3", "landscape"))

        self.assertEqual(flat_report["status"], "pass")
        self.assertEqual(gradient_report["status"], "warn")
        self.assertIn("palette_mismatch", gradient_report["codes"])
        self.assertEqual(gradient_report, repeated_gradient_report)


class ImmutableAIImageTests(unittest.TestCase):
    def test_provider_output_is_preserved_and_review_image_is_not_quantized(self) -> None:
        provider = FakeProvider()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            Image.new("RGB", (300, 200), "white").save(source)
            config = AIProviderConfig("openai", "", "", "low", "", "", 1, 0)
            settings = {
                "page_size": "a3",
                "orientation": "landscape",
                "fit_mode": "cover",
                "target_palette_size": 24,
            }
            _, first = generate_ai_image(root, source, settings, provider, config)
            provider_path = root / "pipeline_ai" / "ai" / "provider_output.png"
            provider_bytes = provider_path.read_bytes()
            _, second = generate_ai_image(root, source, settings, provider, config)
            provider_bytes_after = provider_path.read_bytes()

            with Image.open(first["outputs"]["ai_simplified"]) as reviewed:
                colour_count = len(reviewed.convert("RGB").getcolors(maxcolors=100) or [])

        self.assertEqual(provider.calls, 1)
        self.assertEqual(provider_bytes_after, provider_bytes)
        self.assertEqual(first["outputs"]["ai_simplified"], second["outputs"]["ai_simplified"])
        self.assertEqual(colour_count, 3)


def _same_colour_edges(region_map: np.ndarray, mapping: dict[int, int]) -> int:
    return sum(
        1
        for left, neighbours in build_adjacency(region_map).items()
        for right in neighbours
        if right > left and mapping[left] == mapping[right]
    )


def _write_fur_blinds_fixture(path: Path) -> None:
    height, width = 120, 180
    rgb = np.full((height, width, 3), [205, 195, 175], dtype=np.uint8)
    for y in range(8, 55, 9):
        rgb[y : y + 3, 85:] = [80, 85, 90]
    yy, xx = np.indices((height, width))
    body = ((xx - 50) ** 2 / 42**2 + (yy - 76) ** 2 / 35**2) < 1
    rgb[body] = [145, 95, 55]
    speckles = body & (((xx * 17 + yy * 31) % 29) < 3)
    rgb[speckles] = [80, 55, 40]
    Image.fromarray(rgb, mode="RGB").save(path)


if __name__ == "__main__":
    unittest.main()
