from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

from .io_utils import atomic_write_json, save_rgb
from .print_spec import PrintSpec, mm_to_px


LABEL_GRAY_RGB = (115, 115, 115)
LABEL_HEIGHTS_MM = (4.0, 3.0, 2.0, 1.0)
LABEL_FONT_SIZES_PT = tuple(height_mm / 25.4 * 72.0 for height_mm in LABEL_HEIGHTS_MM)


@dataclass(frozen=True)
class NumberingStats:
    placed_numbers: int
    repeated_numbers: int
    printed_dark_details: int
    unnumbered_region_ids: list[int]
    deliberate_dark_region_ids: list[int] | None = None
    minimum_label_pocket_mm: float = 0.0
    prefilled_detail_region_ids: list[int] | None = None
    adaptive_label_region_ids: list[int] | None = None
    minimum_label_font_pt: float = 0.0
    label_font_points_by_region: dict[int, list[float]] | None = None
    prefilled_area_percent: float = 0.0
    label_plan: dict[str, object] | None = None
    minimum_label_height_mm: float = 0.0
    label_height_counts: dict[str, int] | None = None

    @property
    def unnumbered_regions(self) -> int:
        return len(self.unnumbered_region_ids)

    def to_dict(self) -> dict[str, object]:
        return {
            "placed_numbers": self.placed_numbers,
            "repeated_numbers": self.repeated_numbers,
            "printed_dark_details": self.printed_dark_details,
            "unnumbered_regions": self.unnumbered_regions,
            "unnumbered_region_ids": self.unnumbered_region_ids,
            "deliberate_dark_region_ids": self.deliberate_dark_region_ids or [],
            "prefilled_detail_region_ids": self.prefilled_detail_region_ids or [],
            "prefilled_detail_count": len(self.prefilled_detail_region_ids or []),
            "minimum_label_pocket_mm": self.minimum_label_pocket_mm,
            "adaptive_label_region_ids": self.adaptive_label_region_ids or [],
            "adaptive_label_count": len(self.adaptive_label_region_ids or []),
            "minimum_label_font_pt": self.minimum_label_font_pt,
            "label_font_points_by_region": {
                str(key): values for key, values in (self.label_font_points_by_region or {}).items()
            },
            "prefilled_area_percent": self.prefilled_area_percent,
            "minimum_label_height_mm": self.minimum_label_height_mm,
            "label_height_counts": self.label_height_counts or {},
        }


def render_template_and_exports(
    region_map: np.ndarray,
    region_to_color: dict[int, int],
    palette_rgb: list[tuple[int, int, int]],
    template_dir: Path,
    export_dir: Path,
    print_spec: PrintSpec | None = None,
    painted_reference_rgb: np.ndarray | None = None,
    contour_tolerance_mm: float = 0.2,
    prepared_artifacts: tuple[Image.Image, Image.Image, NumberingStats] | None = None,
    prefilled_detail_region_ids: set[int] | None = None,
    protected_region_ids: set[int] | None = None,
    label_plan: dict[str, object] | None = None,
) -> dict[str, object]:
    print_spec = print_spec or PrintSpec()
    template_dir.mkdir(parents=True, exist_ok=True)
    export_dir.mkdir(parents=True, exist_ok=True)

    palette = [
        {
            "number": index + 1,
            "color_id": index + 1,
            "rgb": [int(v) for v in rgb],
            "hex": "#{:02x}{:02x}{:02x}".format(*[int(v) for v in rgb]),
        }
        for index, rgb in enumerate(palette_rgb)
    ]
    if prepared_artifacts is None:
        template_page, palette_page, numbering_stats = build_print_artifacts(
            region_map,
            region_to_color,
            palette_rgb,
            print_spec,
            contour_tolerance_mm,
            prefilled_detail_region_ids=prefilled_detail_region_ids,
            protected_region_ids=protected_region_ids,
            label_plan=label_plan,
        )
    else:
        template_page, palette_page, numbering_stats = prepared_artifacts

    template_path = template_dir / "numbered_template.png"
    palette_sheet_path = template_dir / "palette_sheet.png"
    template_page.save(template_path, dpi=(print_spec.dpi, print_spec.dpi))
    palette_page.save(palette_sheet_path, dpi=(print_spec.dpi, print_spec.dpi))
    atomic_write_json(template_dir / "palette.json", palette)

    final_png = export_dir / "pbn_final.png"
    final_palette_png = export_dir / "pbn_final_palette.png"
    template_pdf = export_dir / "pbn_template.pdf"
    palette_pdf = export_dir / "palette_sheet.pdf"
    template_page.save(final_png, dpi=(print_spec.dpi, print_spec.dpi))
    palette_page.save(final_palette_png, dpi=(print_spec.dpi, print_spec.dpi))
    template_page.save(template_pdf, "PDF", resolution=print_spec.dpi)
    palette_page.save(palette_pdf, "PDF", resolution=print_spec.dpi)

    painted_reference_path = export_dir / "painted_reference.png"
    if painted_reference_rgb is None:
        painted = np.zeros((*region_map.shape, 3), dtype=np.uint8)
        for region_id, color_id in region_to_color.items():
            if 1 <= color_id <= len(palette_rgb):
                painted[region_map == region_id] = palette_rgb[color_id - 1]
        painted_reference_rgb = painted
    save_rgb(painted_reference_path, painted_reference_rgb)

    result = {
        **numbering_stats.to_dict(),
        "region_count": int(len(region_to_color)),
        "palette_size": int(len(palette_rgb)),
        "outputs": {
            "template": str(template_path),
            "palette_sheet": str(palette_sheet_path),
            "pbn_final": str(final_png),
            "pbn_final_palette": str(final_palette_png),
            "template_pdf": str(template_pdf),
            "palette_pdf": str(palette_pdf),
            "painted_reference": str(painted_reference_path),
        },
    }
    atomic_write_json(export_dir / "export_result.json", result)
    return result


def build_print_artifacts(
    region_map: np.ndarray,
    region_to_number: dict[int, int],
    palette_rgb: list[tuple[int, int, int]],
    print_spec: PrintSpec,
    contour_tolerance_mm: float,
    prefilled_detail_region_ids: set[int] | None = None,
    protected_region_ids: set[int] | None = None,
    label_plan: dict[str, object] | None = None,
) -> tuple[Image.Image, Image.Image, NumberingStats]:
    """Render vector-like shared geometry directly onto the 300-DPI print page."""
    page_width, page_height = print_spec.page_px
    margin = mm_to_px(print_spec.margin_mm, print_spec.dpi)
    available_width = page_width - 2 * margin
    available_height = page_height - 2 * margin
    source_height, source_width = region_map.shape
    scale = min(available_width / source_width, available_height / source_height)
    rendered_width = int(round(source_width * scale))
    rendered_height = int(round(source_height * scale))
    offset_x = (page_width - rendered_width) // 2
    offset_y = (page_height - rendered_height) // 2

    protected_region_ids = set(protected_region_ids or set())
    requested_prefilled_ids = set(prefilled_detail_region_ids or set()) & protected_region_ids
    if label_plan is None:
        label_plan = _build_label_plan(
            region_map,
            region_to_number,
            print_spec,
            scale,
            requested_prefilled_ids,
            protected_region_ids,
        )
    plan_prefilled_ids = {
        int(value)
        for value in label_plan.get("prefilled_region_ids", [])
        if isinstance(value, (int, float, str)) and str(value).isdigit()
    } & protected_region_ids
    prefilled_detail_region_ids = requested_prefilled_ids | plan_prefilled_ids

    canvas = np.full((page_height, page_width, 3), 255, dtype=np.uint8)
    if prefilled_detail_region_ids:
        source_fill = np.full((source_height, source_width, 3), 255, dtype=np.uint8)
        for region_id in prefilled_detail_region_ids:
            color_id = region_to_number.get(region_id, 0)
            if 1 <= color_id <= len(palette_rgb):
                source_fill[region_map == region_id] = palette_rgb[color_id - 1]
        rendered_fill = cv2.resize(source_fill, (rendered_width, rendered_height), interpolation=cv2.INTER_NEAREST)
        canvas[offset_y : offset_y + rendered_height, offset_x : offset_x + rendered_width] = rendered_fill
    line_width = max(1, mm_to_px(0.18, print_spec.dpi))
    epsilon_source = contour_tolerance_mm * print_spec.dpi / 25.4 / max(scale, 1e-6)
    for points, closed in _shared_boundary_polylines(region_map):
        contour = points.astype(np.float32).reshape((-1, 1, 2))
        if len(points) > 2 and epsilon_source > 0:
            contour = cv2.approxPolyDP(contour, epsilon_source, closed=closed)
        page_points = contour[:, 0, :].astype(np.float64)
        page_points[:, 0] = offset_x + page_points[:, 0] * scale
        page_points[:, 1] = offset_y + page_points[:, 1] * scale
        cv2.polylines(
            canvas,
            [np.rint(page_points).astype(np.int32).reshape((-1, 1, 2))],
            isClosed=closed,
            color=(0, 0, 0),
            thickness=line_width,
            lineType=cv2.LINE_AA,
        )
    outer = np.asarray(
        [
            [offset_x, offset_y],
            [offset_x + rendered_width, offset_y],
            [offset_x + rendered_width, offset_y + rendered_height],
            [offset_x, offset_y + rendered_height],
        ],
        dtype=np.int32,
    ).reshape((-1, 1, 2))
    cv2.polylines(
        canvas,
        [outer],
        isClosed=True,
        color=(0, 0, 0),
        thickness=line_width,
        lineType=cv2.LINE_AA,
    )

    placements = [item for item in label_plan.get("placements", []) if isinstance(item, dict)]
    font_points_by_region: dict[int, list[float]] = {}
    heights_by_region: dict[int, list[float]] = {}
    minimum_pocket = float("inf")
    numbered_regions: set[int] = set()
    placed = 0
    for placement in placements:
        try:
            region_id = int(placement["region_id"])
            x = float(placement["x"])
            y = float(placement["y"])
            font_pt = float(placement["font_pt"])
            height_mm = float(placement.get("height_mm", font_pt / 72.0 * 25.4))
            pocket_mm = float(placement.get("pocket_mm", 0.0))
        except (KeyError, TypeError, ValueError):
            continue
        number = str(region_to_number.get(region_id, "?"))
        text_width, text_height, font_scale, thickness = _label_text_metrics(number, font_pt, print_spec.dpi)
        page_x, page_y = offset_x + x * scale, offset_y + y * scale
        cv2.putText(
            canvas,
            number,
            (int(round(page_x - text_width / 2)), int(round(page_y + text_height / 2))),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            LABEL_GRAY_RGB,
            thickness,
            cv2.LINE_AA,
        )
        font_points_by_region.setdefault(region_id, []).append(font_pt)
        heights_by_region.setdefault(region_id, []).append(height_mm)
        minimum_pocket = min(minimum_pocket, pocket_mm)
        numbered_regions.add(region_id)
        placed += 1

    unnumbered = sorted(
        int(value)
        for value in label_plan.get("unnumbered_region_ids", [])
        if isinstance(value, (int, float, str)) and str(value).isdigit()
    )
    adaptive_ids = sorted(
        region_id
        for region_id, sizes in font_points_by_region.items()
        if any(height < LABEL_HEIGHTS_MM[0] for height in heights_by_region.get(region_id, []))
    )
    all_font_points = [size for sizes in font_points_by_region.values() for size in sizes]
    all_heights = [height for heights in heights_by_region.values() for height in heights]
    height_counts = {
        f"{height:g}": sum(abs(value - height) <= 1e-6 for value in all_heights)
        for height in LABEL_HEIGHTS_MM
    }
    prefilled_area_percent = 100.0 * sum(
        int(np.count_nonzero(region_map == region_id)) for region_id in prefilled_detail_region_ids
    ) / max(1, region_map.size)
    image = Image.fromarray(canvas, mode="RGB")
    stats = NumberingStats(
        placed_numbers=placed,
        repeated_numbers=max(0, placed - len(numbered_regions)),
        printed_dark_details=0,
        unnumbered_region_ids=unnumbered,
        deliberate_dark_region_ids=[],
        minimum_label_pocket_mm=0.0 if minimum_pocket == float("inf") else minimum_pocket,
        prefilled_detail_region_ids=sorted(prefilled_detail_region_ids),
        adaptive_label_region_ids=adaptive_ids,
        minimum_label_font_pt=min(all_font_points, default=0.0),
        label_font_points_by_region=font_points_by_region,
        prefilled_area_percent=prefilled_area_percent,
        label_plan=label_plan,
        minimum_label_height_mm=min(all_heights, default=0.0),
        label_height_counts=height_counts,
    )
    palette_page = _make_print_palette_page(palette_rgb, print_spec)
    return image, palette_page, stats


def _shared_boundary_polylines(region_map: np.ndarray) -> list[tuple[np.ndarray, bool]]:
    """Trace every internal label-grid edge once, splitting paths at junctions."""
    _, width = region_map.shape
    stride = width + 1
    starts: list[np.ndarray] = []
    ends: list[np.ndarray] = []

    vertical_y, vertical_x = np.nonzero(region_map[:, 1:] != region_map[:, :-1])
    if len(vertical_y):
        grid_x = vertical_x.astype(np.int64) + 1
        grid_y = vertical_y.astype(np.int64)
        starts.append(grid_y * stride + grid_x)
        ends.append((grid_y + 1) * stride + grid_x)

    horizontal_y, horizontal_x = np.nonzero(region_map[1:, :] != region_map[:-1, :])
    if len(horizontal_y):
        grid_x = horizontal_x.astype(np.int64)
        grid_y = horizontal_y.astype(np.int64) + 1
        starts.append(grid_y * stride + grid_x)
        ends.append(grid_y * stride + grid_x + 1)

    if not starts:
        return []
    edge_starts = np.concatenate(starts)
    edge_ends = np.concatenate(ends)
    adjacency: dict[int, list[int]] = {}
    edges: list[tuple[int, int]] = []
    for start_value, end_value in zip(edge_starts, edge_ends, strict=True):
        start, end = int(start_value), int(end_value)
        edge = (start, end) if start < end else (end, start)
        edges.append(edge)
        adjacency.setdefault(start, []).append(end)
        adjacency.setdefault(end, []).append(start)
    for neighbours in adjacency.values():
        neighbours.sort()

    visited: set[tuple[int, int]] = set()
    paths: list[tuple[np.ndarray, bool]] = []

    def trace(start: int, first: int) -> tuple[list[int], bool]:
        path = [start]
        previous, current = start, first
        visited.add((start, first) if start < first else (first, start))
        path.append(current)
        while True:
            if current == start:
                return path[:-1], True
            if len(adjacency[current]) != 2:
                return path, False
            next_values = [value for value in adjacency[current] if value != previous]
            if not next_values:
                return path, False
            next_value = next_values[0]
            edge = (current, next_value) if current < next_value else (next_value, current)
            if edge in visited:
                return path, False
            visited.add(edge)
            previous, current = current, next_value
            path.append(current)

    junctions = sorted(vertex for vertex, neighbours in adjacency.items() if len(neighbours) != 2)
    for start in junctions:
        for neighbour in adjacency[start]:
            edge = (start, neighbour) if start < neighbour else (neighbour, start)
            if edge in visited:
                continue
            path, closed = trace(start, neighbour)
            if len(path) >= 2:
                paths.append((_decode_grid_vertices(path, stride), closed))

    for start, end in sorted(edges):
        if (start, end) in visited:
            continue
        path, closed = trace(start, end)
        if len(path) >= 2:
            paths.append((_decode_grid_vertices(path, stride), closed))
    return paths


def _decode_grid_vertices(vertices: list[int], stride: int) -> np.ndarray:
    values = np.asarray(vertices, dtype=np.int64)
    return np.stack((values % stride, values // stride), axis=1).astype(np.float32)


def _build_label_plan(
    region_map: np.ndarray,
    region_to_number: dict[int, int],
    print_spec: PrintSpec,
    scale: float,
    requested_prefilled_ids: set[int],
    protected_region_ids: set[int],
) -> dict[str, object]:
    region_objects = ndimage.find_objects(region_map)
    repeat_spacing_source = mm_to_px(35.0, print_spec.dpi) / max(scale, 1e-6)
    placements: list[dict[str, object]] = []
    prefilled = set(requested_prefilled_ids)
    unnumbered: list[int] = []
    source_height, source_width = region_map.shape

    for region_id, region_slice in enumerate(region_objects, start=1):
        if region_slice is None or region_id in prefilled:
            continue
        top, bottom = int(region_slice[0].start or 0), int(region_slice[0].stop or source_height)
        left, right = int(region_slice[1].start or 0), int(region_slice[1].stop or source_width)
        local_mask = region_map[region_slice] == region_id
        physical_length_mm = max(right - left, bottom - top) * scale * 25.4 / print_spec.dpi
        max_positions = max(1, min(12, int(physical_length_mm // 35.0) + 1))
        local_positions = find_number_positions(
            local_mask,
            max_positions=max_positions,
            min_radius=0.5,
            spacing_px=repeat_spacing_source,
            allow_fallback=True,
        )
        number = str(region_to_number.get(region_id, "?"))
        region_placements: list[dict[str, object]] = []
        for x, y, radius in local_positions:
            label_size = _largest_fitting_label(number, radius * scale, print_spec.dpi)
            if label_size is None:
                continue
            height_mm, font_pt = label_size
            region_placements.append(
                {
                    "region_id": region_id,
                    "x": x + left,
                    "y": y + top,
                    "font_pt": font_pt,
                    "height_mm": height_mm,
                    "pocket_mm": 2.0 * radius * scale * 25.4 / print_spec.dpi,
                }
            )
        if region_placements:
            placements.extend(region_placements)
        elif region_id in protected_region_ids:
            prefilled.add(region_id)
        else:
            unnumbered.append(region_id)

    return {
        "version": 1,
        "label_rgb": list(LABEL_GRAY_RGB),
        "font_sizes_pt": list(LABEL_FONT_SIZES_PT),
        "label_heights_mm": list(LABEL_HEIGHTS_MM),
        "placements": placements,
        "prefilled_region_ids": sorted(prefilled),
        "unnumbered_region_ids": sorted(unnumbered),
    }


def _largest_fitting_label(
    text: str,
    radius_page_px: float,
    dpi: int,
) -> tuple[float, float] | None:
    available = 2.0 * radius_page_px
    for height_mm, font_pt in zip(LABEL_HEIGHTS_MM, LABEL_FONT_SIZES_PT, strict=True):
        width, height, _, _ = _label_text_metrics(text, font_pt, dpi)
        if width <= available and height <= available:
            return height_mm, font_pt
    return None


def _label_text_metrics(text: str, font_pt: float, dpi: int) -> tuple[int, int, float, int]:
    target_height_px = max(1.0, font_pt / 72.0 * dpi)
    font_scale = target_height_px / 22.0
    thickness = max(1, int(round(target_height_px / 14.0)))
    (width, height), _ = cv2.getTextSize(
        text,
        cv2.FONT_HERSHEY_SIMPLEX,
        font_scale,
        thickness,
    )
    return width, height, font_scale, thickness


def _make_print_palette_page(
    palette_rgb: list[tuple[int, int, int]],
    print_spec: PrintSpec,
) -> Image.Image:
    palette = [
        {
            "number": index + 1,
            "rgb": list(rgb),
            "hex": "#{:02x}{:02x}{:02x}".format(*rgb),
        }
        for index, rgb in enumerate(palette_rgb)
    ]
    sheet = make_palette_sheet_image(palette)
    page = Image.new("RGB", print_spec.page_px, "white")
    margin = mm_to_px(print_spec.margin_mm, print_spec.dpi)
    sheet.thumbnail((page.width - 2 * margin, page.height - 2 * margin), Image.Resampling.LANCZOS)
    page.paste(sheet, ((page.width - sheet.width) // 2, margin))
    return page


def make_template_image(
    region_map: np.ndarray,
    region_to_number: dict[int, int],
    palette_rgb: list[tuple[int, int, int]] | None = None,
    line_thickness: int = 1,
    min_number_area: int = 100,
    font_size: int = 14,
) -> tuple[Image.Image, NumberingStats]:
    h, w = region_map.shape
    canvas = np.full((h, w, 3), 255, dtype=np.uint8)
    edges = np.zeros((h, w), dtype=np.uint8)
    edges[:, 1:] |= region_map[:, 1:] != region_map[:, :-1]
    edges[1:, :] |= region_map[1:, :] != region_map[:-1, :]
    if line_thickness > 1:
        edges = cv2.dilate(edges, np.ones((line_thickness, line_thickness), np.uint8), iterations=1)
    canvas[edges.astype(bool)] = [0, 0, 0]
    image = Image.fromarray(canvas, mode="RGB")
    stats = draw_numbers(
        image=image,
        region_map=region_map,
        region_to_number=region_to_number,
        palette_rgb=palette_rgb or [],
        font_size=font_size,
        min_font_size=6,
        min_number_area=min_number_area,
    )
    return image, stats


def draw_numbers(
    image: Image.Image,
    region_map: np.ndarray,
    region_to_number: dict[int, int],
    palette_rgb: list[tuple[int, int, int]],
    font_size: int,
    min_number_area: int,
    min_font_size: int = 6,
) -> NumberingStats:
    draw = ImageDraw.Draw(image)
    placed = 0
    numbered_regions = 0
    printed_dark_details = 0
    unnumbered_region_ids: list[int] = []
    font_cache: dict[int, ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}

    for region_id in [int(value) for value in np.unique(region_map) if int(value)]:
        mask = region_map == region_id
        number = str(region_to_number.get(region_id, "?"))
        area = int(mask.sum())
        positions = find_number_positions(mask, max_positions=_max_numbers_for_region(area), min_radius=1.4)
        region_placements = 0
        for x, y, radius in positions:
            font = _largest_fitting_font(
                draw=draw,
                text=number,
                radius=radius,
                max_font_size=font_size,
                min_font_size=min_font_size,
                font_cache=font_cache,
            )
            if font is None:
                continue
            bbox = draw.textbbox((0, 0), number, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            draw.text(
                (x - text_w / 2 - bbox[0], y - text_h / 2 - bbox[1]),
                number,
                fill=(0, 0, 0),
                font=font,
            )
            placed += 1
            region_placements += 1

        if region_placements:
            numbered_regions += 1
            continue

        best_radius = positions[0][2] if positions else 0.0
        if positions and _draw_tiny_pixel_number(draw, mask, number, positions[0][0], positions[0][1]):
            placed += 1
            numbered_regions += 1
            continue

        color_id = region_to_number.get(region_id, 0)
        if _should_print_as_dark_detail(mask, color_id, palette_rgb, min_number_area, best_radius, min_font_size):
            _fill_region_black(draw, mask)
            printed_dark_details += 1
        else:
            unnumbered_region_ids.append(region_id)

    repeated_numbers = max(0, placed - numbered_regions)
    return NumberingStats(
        placed_numbers=placed,
        repeated_numbers=repeated_numbers,
        printed_dark_details=printed_dark_details,
        unnumbered_region_ids=unnumbered_region_ids,
    )


def find_number_position(region_mask: np.ndarray) -> tuple[int, int, float] | None:
    positions = find_number_positions(region_mask, max_positions=1, min_radius=3.0)
    if not positions:
        return None
    return positions[0]


def find_number_positions(
    region_mask: np.ndarray,
    max_positions: int = 6,
    min_radius: float = 1.4,
    spacing_px: float | None = None,
    allow_fallback: bool = True,
) -> list[tuple[int, int, float]]:
    padded_mask = np.pad(region_mask.astype(np.uint8), 1, mode="constant", constant_values=0)
    dist = cv2.distanceTransform(padded_mask, cv2.DIST_L2, 5)[1:-1, 1:-1]
    if not np.any(dist):
        return []

    candidate_ys, candidate_xs = np.nonzero(dist >= min_radius)
    if len(candidate_xs) == 0:
        if not allow_fallback:
            return []
        _, max_val, _, max_loc = cv2.minMaxLoc(dist)
        if max_val <= 0:
            return []
        candidate_xs = np.asarray([max_loc[0]])
        candidate_ys = np.asarray([max_loc[1]])

    candidates = sorted(
        (
            (int(x), int(y), float(dist[int(y), int(x)]))
            for x, y in zip(candidate_xs, candidate_ys, strict=False)
        ),
        key=lambda item: (-item[2], item[1], item[0]),
    )
    selected: list[tuple[int, int, float]] = []
    for x, y, radius in candidates:
        spacing = spacing_px if spacing_px is not None else max(10.0, radius * 5.0)
        if all((x - prev_x) ** 2 + (y - prev_y) ** 2 >= spacing**2 for prev_x, prev_y, _ in selected):
            selected.append((x, y, radius))
        if len(selected) >= max_positions:
            break
    return selected


def _largest_fitting_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    radius: float,
    max_font_size: int,
    min_font_size: int,
    font_cache: dict[int, ImageFont.FreeTypeFont | ImageFont.ImageFont],
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont | None:
    available = radius * 1.95
    for size in range(max_font_size, min_font_size - 1, -1):
        font = font_cache.setdefault(size, load_font(size))
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        if text_w <= available and text_h <= available:
            return font
    return None


def _max_numbers_for_region(area: int) -> int:
    if area < 500:
        return 1
    return max(1, min(8, int(area // 1800) + 1))


def _should_print_as_dark_detail(
    mask: np.ndarray,
    color_id: int,
    palette_rgb: list[tuple[int, int, int]],
    min_number_area: int,
    best_radius: float,
    min_font_size: int,
) -> bool:
    if color_id < 1 or color_id > len(palette_rgb):
        return False
    if not _is_dark_color(palette_rgb[color_id - 1]):
        return False
    area = int(mask.sum())
    return area <= min_number_area or best_radius < min_font_size * 0.45


def _is_dark_color(rgb: tuple[int, int, int]) -> bool:
    red, green, blue = (int(v) for v in rgb)
    luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return luminance <= 70


def _fill_region_black(draw: ImageDraw.ImageDraw, mask: np.ndarray) -> None:
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return
    draw.point(list(zip(xs.tolist(), ys.tolist(), strict=False)), fill=(0, 0, 0))


TINY_DIGITS = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
    "?": ("111", "001", "011", "000", "010"),
}


def _draw_tiny_pixel_number(
    draw: ImageDraw.ImageDraw,
    mask: np.ndarray,
    text: str,
    center_x: int,
    center_y: int,
) -> bool:
    glyphs = [TINY_DIGITS.get(char, TINY_DIGITS["?"]) for char in text]
    width = len(glyphs) * 3 + max(0, len(glyphs) - 1)
    height = 5
    x0 = int(round(center_x - width / 2))
    y0 = int(round(center_y - height / 2))
    pixels: list[tuple[int, int]] = []

    for glyph_index, glyph in enumerate(glyphs):
        glyph_x = x0 + glyph_index * 4
        for gy, row in enumerate(glyph):
            for gx, value in enumerate(row):
                if value != "1":
                    continue
                x = glyph_x + gx
                y = y0 + gy
                if y < 0 or y >= mask.shape[0] or x < 0 or x >= mask.shape[1] or not mask[y, x]:
                    return False
                pixels.append((x, y))

    if not pixels:
        return False
    draw.point(pixels, fill=(0, 0, 0))
    return True


def load_font(font_size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for font_name in [
        "arial.ttf",
        "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]:
        try:
            return ImageFont.truetype(font_name, font_size)
        except Exception:
            continue
    return ImageFont.load_default()


def make_palette_sheet_image(
    palette: list[dict[str, object]],
    swatch_size: int = 80,
) -> Image.Image:
    cols = 4
    rows = int(np.ceil(len(palette) / cols))
    width = cols * 260
    height = rows * 110 + 80
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = load_font(28)
    font = load_font(18)
    draw.text((30, 25), "Paint-by-number palette", fill=(0, 0, 0), font=title_font)
    for index, item in enumerate(palette):
        col = index % cols
        row = index // cols
        x = col * 260 + 30
        y = 80 + row * 110
        rgb = tuple(int(v) for v in item["rgb"])  # type: ignore[index]
        number = int(item["number"])  # type: ignore[arg-type]
        hex_color = str(item["hex"])
        draw.rectangle([x, y, x + swatch_size, y + swatch_size], fill=rgb, outline=(0, 0, 0))
        draw.text((x + swatch_size + 15, y + 10), f"#{number}", fill=(0, 0, 0), font=font)
        draw.text((x + swatch_size + 15, y + 40), hex_color, fill=(0, 0, 0), font=font)
    return image
