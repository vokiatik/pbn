"""Small structural regressions for the source-guided PBN graph."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from skimage import color, measure

from ai_pipeline.hierarchical_merge import compact_hierarchically
from ai_pipeline.pipeline import _build_geometry_base, _build_option_attempt, continue_ai_pipeline, finalize_pbn_option
from ai_pipeline.print_spec import PrintSpec
from ai_pipeline.regions import build_adjacency, build_region_records
from ai_pipeline.segmentation import create_structural_atoms, region_boundary_evidence, retry_profiles
from ai_pipeline.validation import validate_template_inputs


class StructuralGenerationTests(unittest.TestCase):
    def _analyze(self, name: str, image: Image.Image, root: Path) -> tuple[np.ndarray, np.ndarray]:
        source = root / f"{name}.png"
        image.save(source)
        labels, rgb, metrics = create_structural_atoms(source, root / name)
        cached, _, cached_metrics = create_structural_atoms(source, root / name)
        self.assertTrue(cached_metrics["cache_hit"])
        np.testing.assert_array_equal(labels, cached)
        self.assertEqual(metrics["initial_region_count"], int(labels.max()))
        self.assertEqual(int(measure.label(labels, connectivity=1, background=0).max()), int(labels.max()))
        return labels, rgb

    def _generate(self, name: str, image: Image.Image, root: Path) -> tuple[np.ndarray, np.ndarray]:
        source = root / f"{name}.png"
        image.save(source)
        spec = PrintSpec()
        profile = retry_profiles(spec)[2]
        base = _build_geometry_base(source, root / name / "base", spec, profile)
        output = root / name / "final"
        record, candidate = _build_option_attempt(output, "hard", 0, 650, 650, profile, base, 24, spec)
        self.assertIsNotNone(candidate, record["rejection_reasons"])
        labels = np.load(output / "regions" / "region_id_map.npy")
        self.assertEqual(int(measure.label(labels, connectivity=1, background=0).max()), int(labels.max()))
        with Image.open(output / "painted_reference.png") as preview:
            painted = np.asarray(preview.convert("RGB"))
        paints = json.loads((output / "palette" / "palette.json").read_text())
        self.assertEqual(len(paints), len({tuple(paint["rgb"]) for paint in paints}))
        metrics = json.loads((output / "validation" / "report.json").read_text())["metrics"]
        self.assertEqual(metrics["regions_below_print_floor"], 0)
        self.assertEqual(metrics["disconnected_island_count"], 0)
        self.assertEqual(metrics["unnumbered_region_count"], 0)
        alignment = metrics["boundary_alignment"]
        self.assertLessEqual(alignment["actual_snap_radius_mm"], alignment["requested_snap_radius_mm"] + 1e-6)
        return labels, painted

    def test_nine_structural_cases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            size = 192
            for name in (
                "face_eyes", "separated_fingers", "thin_stripe", "weak_shading",
                "flat_background", "tiny_object", "curved_silhouette",
                "straight_boundary", "multiple_resolutions",
            ):
                with self.subTest(name=name):
                    image = Image.new("RGB", (size, size), "#e4d0b8")
                    draw = ImageDraw.Draw(image)
                    points: list[tuple[tuple[int, int], tuple[int, int]]] = []
                    if name == "face_eyes":
                        draw.ellipse((35, 18, 158, 177), fill="#c99470")
                        draw.ellipse((70, 79, 76, 85), fill="#171512")
                        draw.ellipse((117, 79, 123, 85), fill="#171512")
                        draw.arc((78, 95, 117, 139), 10, 170, fill="#542b2b", width=3)
                        points = [((73, 82), (80, 82)), ((120, 82), (127, 82))]
                    elif name == "separated_fingers":
                        for x in (52, 72, 92):
                            draw.rounded_rectangle((x, 38, x + 11, 146), radius=5, fill="#78482f")
                            points.append(((x + 5, 70), (x + 15, 70)))
                    elif name == "thin_stripe":
                        draw.rectangle((36, 38, 155, 145), fill="#dad4c7")
                        draw.rectangle((94, 38, 97, 145), fill="#252525")
                        points = [((95, 85), (101, 85))]
                    elif name == "weak_shading":
                        draw.rectangle((45, 45, 146, 146), fill="#e3cfb7")
                        points = [((60, 60), (20, 20))]
                    elif name == "flat_background":
                        points = [((50, 50), (150, 150))]
                    elif name == "tiny_object":
                        draw.ellipse((93, 93, 98, 98), fill="#1b1b1b")
                        points = [((95, 95), (105, 95))]
                    elif name == "curved_silhouette":
                        draw.ellipse((28, 28, 164, 164), fill="#426e92")
                        points = [((96, 96), (15, 96)), ((44, 96), (15, 96))]
                    elif name == "straight_boundary":
                        draw.rectangle((58, 30, 145, 159), fill="#426e92")
                        points = [((65, 90), (50, 90)), ((135, 90), (155, 90))]
                    else:
                        draw.ellipse((75, 75, 83, 83), fill="#171512")
                        points = [((79, 79), (90, 79))]

                    labels, _ = self._analyze(name, image, root)
                    if name == "flat_background":
                        self.assertEqual(int(labels.max()), 1)
                    elif name == "weak_shading":
                        self.assertLessEqual(int(labels.max()), 8)
                    else:
                        for foreground, background in points:
                            self.assertNotEqual(labels[foreground[1], foreground[0]], labels[background[1], background[0]])

                    final, painted = self._generate(name, image, root)
                    expected_regions = {
                        "face_eyes": 5, "separated_fingers": 4, "thin_stripe": 4,
                        "weak_shading": 1, "flat_background": 1, "tiny_object": 2,
                        "curved_silhouette": 2, "straight_boundary": 2, "multiple_resolutions": 2,
                    }
                    self.assertLessEqual(int(final.max()), expected_regions[name])
                    if name not in {"flat_background", "weak_shading"}:
                        for foreground, background in points:
                            self.assertNotEqual(final[foreground[1], foreground[0]], final[background[1], background[0]])
                            self.assertFalse(np.array_equal(painted[foreground[1], foreground[0]], painted[background[1], background[0]]))

            low = Image.new("RGB", (96, 96), "#d7b797")
            high = Image.new("RGB", (192, 192), "#d7b797")
            ImageDraw.Draw(low).ellipse((36, 36, 41, 41), fill="#171512")
            ImageDraw.Draw(high).ellipse((72, 72, 83, 83), fill="#171512")
            low_labels, _ = self._analyze("multi_low", low, root)
            high_labels, _ = self._analyze("multi_high", high, root)
            self.assertNotEqual(low_labels[39, 39], low_labels[50, 39])
            self.assertNotEqual(high_labels[78, 78], high_labels[100, 78])
            low_eye = np.repeat(np.repeat(low_labels == low_labels[39, 39], 2, axis=0), 2, axis=1)
            high_eye = high_labels == high_labels[78, 78]
            overlap = np.count_nonzero(low_eye & high_eye) / max(1, np.count_nonzero(low_eye | high_eye))
            self.assertGreater(overlap, 0.55)

            high = low.resize((192, 192), Image.Resampling.NEAREST)
            low_final, low_painted = self._generate("final_low", low, root)
            high_final, high_painted = self._generate("final_high", high, root)
            self.assertEqual(int(low_final.max()), int(high_final.max()))
            low_dark = np.repeat(np.repeat(low_painted[..., 0] < 60, 2, axis=0), 2, axis=1)
            high_dark = high_painted[..., 0] < 60
            overlap = np.count_nonzero(low_dark & high_dark) / max(1, np.count_nonzero(low_dark | high_dark))
            self.assertGreater(overlap, 0.95)

    def test_merge_spends_detail_on_eye_before_weak_shading(self) -> None:
        image = Image.new("RGB", (160, 160), "#d8b898")
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 100, 159, 159), fill="#d0b494")
        draw.ellipse((74, 55, 80, 61), fill="#171512")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            labels, rgb = self._analyze("eye_and_shade", image, root)
            palette = color.rgb2lab(
                np.asarray([[[216, 184, 152], [208, 180, 148], [23, 21, 18]]], dtype=np.float64) / 255.0
            )[0]
            result = compact_hierarchically(
                rgb, labels, palette, {}, region_boundary_evidence(rgb, labels), 2, 2
            )
            final = result.label_map
            self.assertNotEqual(final[58, 77], final[80, 77], "the eye must survive")
            self.assertEqual(final[80, 77], final[130, 77], "weak shading should merge first")
            self.assertEqual(len(np.unique(final)), 2)

    def test_one_square_millimetre_dark_detail_survives_atomization(self) -> None:
        image = Image.new("RGB", (512, 512), "#d8b898")
        ImageDraw.Draw(image).rectangle((254, 254, 255, 255), fill="#171512")
        with tempfile.TemporaryDirectory() as directory:
            labels, _ = self._analyze("tiny_printable_eye", image, Path(directory))
            final, painted = self._generate("tiny_printable_eye", image, Path(directory))
            self.assertNotEqual(final[254, 254], final[260, 254])
            self.assertLess(int(painted[254, 254, 0]), 60)
        self.assertNotEqual(labels[254, 254], labels[260, 254])

    def test_diagonal_shapes_get_separate_numbered_regions(self) -> None:
        image = Image.new("RGB", (192, 192), "#e4d0b8")
        draw = ImageDraw.Draw(image)
        draw.rectangle((40, 40, 95, 95), fill="#171512")
        draw.rectangle((96, 96, 151, 151), fill="#171512")
        with tempfile.TemporaryDirectory() as directory:
            labels, _ = self._generate("diagonal", image, Path(directory))
        self.assertEqual(int(labels.max()), 3)
        self.assertNotEqual(labels[70, 70], labels[110, 110])

    def test_final_generation_is_deterministic(self) -> None:
        image = Image.new("RGB", (192, 192), "#e4d0b8")
        draw = ImageDraw.Draw(image)
        draw.ellipse((35, 18, 158, 177), fill="#c99470")
        draw.ellipse((70, 79, 76, 85), fill="#171512")
        draw.ellipse((117, 79, 123, 85), fill="#171512")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_map, first_painted = self._generate("first", image, root)
            second_map, second_painted = self._generate("second", image, root)
        np.testing.assert_array_equal(first_map, second_map)
        np.testing.assert_array_equal(first_painted, second_painted)

    def test_continuation_produces_only_hard_and_removes_legacy_options(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            root = project / "pipeline_ai"
            (root / "ai").mkdir(parents=True)
            (root / "prepared").mkdir()
            (root / "prepared" / "crop_manifest.json").write_text("{}")
            image = Image.new("RGB", (192, 192), "#e4d0b8")
            ImageDraw.Draw(image).ellipse((50, 50, 140, 140), fill="#171512")
            image.save(root / "ai" / "simplified.png")
            for legacy in ("easy", "medium"):
                (root / "options" / legacy).mkdir(parents=True)
                (root / "options" / legacy / "numbered_template.png").write_bytes(b"stale")
            _, result = continue_ai_pipeline(project, Path("unused"), {})
            self.assertEqual(result["metrics"]["attempt_count"], 1)
            self.assertEqual([option["difficulty"] for option in result["metrics"]["options"]], ["hard"])
            saved_report = (root / "options" / "hard" / "validation" / "report.json").read_bytes()
            for legacy in ("easy", "medium"):
                self.assertFalse((root / "options" / legacy).exists())
                with self.assertRaisesRegex(ValueError, "only hard"):
                    finalize_pbn_option(project, {}, legacy)
            _, exported = finalize_pbn_option(project, {}, "hard")
            self.assertEqual(exported["selected_difficulty"], "hard")
            self.assertTrue((root / "export" / "pbn_template.pdf").is_file())
            self.assertEqual((root / "options" / "hard" / "validation" / "report.json").read_bytes(), saved_report)
            exported_report = json.loads((root / "validation" / "report.json").read_text())
            self.assertIn("processing_seconds", exported_report["metrics"])
            with Image.open(root / "export" / "pbn_final.png") as template:
                self.assertEqual(template.size, PrintSpec().page_px)

    def test_validation_rejects_disconnected_regions_and_duplicate_paints(self) -> None:
        labels = np.ones((32, 32), dtype=np.int32)
        labels[4:10, 4:10] = 2
        labels[20:26, 20:26] = 2
        rgb = np.full((32, 32, 3), 200, dtype=np.uint8)
        records = build_region_records(labels, rgb, build_adjacency(labels))
        self.assertEqual(records[1].components, 2)
        with tempfile.TemporaryDirectory() as directory:
            report = validate_template_inputs(
                labels, records, {1: 1, 2: 2}, Path(directory), 24,
                palette_rgb=[(200, 200, 200), (200, 200, 200)],
            )
        self.assertIn("disconnected_region", {issue.code for issue in report.issues})
        self.assertIn("duplicate_palette_colour", {issue.code for issue in report.issues})
        self.assertEqual(report.metrics["disconnected_island_count"], 1)

    def test_graph_resolves_unpaintable_atom_before_final_cleanup(self) -> None:
        labels = np.ones((80, 80), dtype=np.int32)
        labels[20:22, 20:22] = 2
        labels[40:46, 40:46] = 3
        rgb = np.full((80, 80, 3), [216, 184, 152], dtype=np.uint8)
        rgb[20:22, 20:22] = [211, 180, 149]
        rgb[40:46, 40:46] = [23, 21, 18]
        palette = color.rgb2lab(
            np.asarray([[[216, 184, 152], [23, 21, 18]]], dtype=np.float64) / 255.0
        )[0]
        result = compact_hierarchically(
            rgb, labels, palette, {}, region_boundary_evidence(rgb, labels),
            target_region_count=3, maximum_region_count=3,
            minimum_area_pixels=10, minimum_width_pixels=1,
        )
        self.assertEqual(result.label_map[20, 20], result.label_map[25, 25])
        self.assertNotEqual(result.label_map[42, 42], result.label_map[25, 25])
        self.assertGreaterEqual(result.metrics["physical_constraint_merge_count"], 1)


if __name__ == "__main__":
    unittest.main()
