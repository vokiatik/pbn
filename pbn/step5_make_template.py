import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def ensure_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_region_to_number(regions: list[dict[str, Any]]) -> dict[int, int]:
    return {
        int(region["region_id"]): int(region["paint_number"])
        for region in regions
    }


def make_boundary_map(
    region_map: np.ndarray,
    line_thickness: int = 1,
) -> np.ndarray:
    h, w = region_map.shape

    edges = np.zeros((h, w), dtype=np.uint8)

    edges[:, 1:] |= region_map[:, 1:] != region_map[:, :-1]
    edges[1:, :] |= region_map[1:, :] != region_map[:-1, :]

    if line_thickness > 1:
        kernel = np.ones((line_thickness, line_thickness), np.uint8)
        edges = cv2.dilate(edges, kernel, iterations=1)

    return edges.astype(bool)


def find_number_position(region_mask: np.ndarray) -> tuple[int, int, float] | None:
    mask_u8 = region_mask.astype(np.uint8)

    dist = cv2.distanceTransform(mask_u8, cv2.DIST_L2, 5)

    _, max_val, _, max_loc = cv2.minMaxLoc(dist)

    if max_val < 3:
        return None

    x, y = max_loc

    return int(x), int(y), float(max_val)


def load_font(font_size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for font_name in ["arial.ttf", "DejaVuSans.ttf"]:
        try:
            return ImageFont.truetype(font_name, font_size)
        except Exception:
            continue

    return ImageFont.load_default()


def draw_numbers(
    img: Image.Image,
    region_map: np.ndarray,
    region_to_number: dict[int, int],
    font_size: int,
    min_number_area: int,
) -> int:
    draw = ImageDraw.Draw(img)
    font = load_font(font_size)

    placed_count = 0

    region_ids = np.unique(region_map)
    region_ids = [int(x) for x in region_ids if int(x) != 0]

    for region_id in region_ids:
        region_mask = region_map == region_id

        area = int(region_mask.sum())

        if area < min_number_area:
            continue

        pos = find_number_position(region_mask)

        if pos is None:
            continue

        x, y, radius = pos

        number = str(region_to_number.get(region_id, "?"))

        bbox = draw.textbbox((0, 0), number, font=font)

        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        if text_w > radius * 1.7 or text_h > radius * 1.7:
            continue

        draw.text(
            (x - text_w / 2, y - text_h / 2),
            number,
            fill=(0, 0, 0),
            font=font,
        )

        placed_count += 1

    return placed_count


def make_template_image(
    region_map: np.ndarray,
    region_to_number: dict[int, int],
    line_thickness: int = 1,
    min_number_area: int = 100,
    font_size: int = 14,
) -> tuple[Image.Image, int]:
    h, w = region_map.shape

    canvas = np.full((h, w, 3), 255, dtype=np.uint8)

    boundaries = make_boundary_map(
        region_map=region_map,
        line_thickness=line_thickness,
    )

    canvas[boundaries] = [0, 0, 0]

    img = Image.fromarray(canvas)

    placed_numbers = draw_numbers(
        img=img,
        region_map=region_map,
        region_to_number=region_to_number,
        font_size=font_size,
        min_number_area=min_number_area,
    )

    return img, placed_numbers


def make_colored_debug_image(
    region_map: np.ndarray,
    regions: list[dict[str, Any]],
    palette: list[dict[str, Any]],
) -> Image.Image:
    region_to_number = build_region_to_number(regions)

    palette_rgb = np.array(
        [item["rgb"] for item in palette],
        dtype=np.uint8,
    )

    h, w = region_map.shape

    out = np.zeros((h, w, 3), dtype=np.uint8)

    for region_id, paint_number in region_to_number.items():
        color_index = paint_number - 1

        if color_index < 0 or color_index >= len(palette_rgb):
            continue

        out[region_map == region_id] = palette_rgb[color_index]

    return Image.fromarray(out)


def make_palette_sheet_image(
    palette: list[dict[str, Any]],
    swatch_size: int = 80,
) -> Image.Image:
    cols = 4
    rows = int(np.ceil(len(palette) / cols))

    width = cols * 260
    height = rows * 110 + 80

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    title_font = load_font(28)
    font = load_font(18)

    draw.text(
        (30, 25),
        "Paint-by-number palette",
        fill=(0, 0, 0),
        font=title_font,
    )

    start_y = 80

    for index, item in enumerate(palette):
        col = index % cols
        row = index // cols

        x = col * 260 + 30
        y = start_y + row * 110

        rgb = tuple(int(v) for v in item["rgb"])
        number = int(item["number"])
        hex_color = str(item["hex"])

        draw.rectangle(
            [x, y, x + swatch_size, y + swatch_size],
            fill=rgb,
            outline=(0, 0, 0),
        )

        draw.text(
            (x + swatch_size + 15, y + 10),
            f"#{number}",
            fill=(0, 0, 0),
            font=font,
        )

        draw.text(
            (x + swatch_size + 15, y + 40),
            hex_color,
            fill=(0, 0, 0),
            font=font,
        )

    return img


def run_step5_make_template(
    region_map_path: str,
    regions_path: str,
    palette_path: str,
    output_dir: str,
    line_thickness: int = 1,
    font_size: int = 14,
    min_number_area: int = 100,
) -> dict[str, Any]:
    ensure_dir(output_dir)

    region_map = np.load(region_map_path)

    regions = load_json(regions_path)
    palette = load_json(palette_path)

    h, w = region_map.shape

    region_to_number = build_region_to_number(regions)

    template_image, placed_numbers = make_template_image(
        region_map=region_map,
        region_to_number=region_to_number,
        line_thickness=line_thickness,
        min_number_area=min_number_area,
        font_size=font_size,
    )

    colored_debug_image = make_colored_debug_image(
        region_map=region_map,
        regions=regions,
        palette=palette,
    )

    palette_sheet_image = make_palette_sheet_image(
        palette=palette,
    )

    template_path = str(Path(output_dir) / "pbn_template.png")
    colored_debug_path = str(Path(output_dir) / "pbn_colored_debug.png")
    palette_sheet_path = str(Path(output_dir) / "palette_sheet.png")
    result_path = str(Path(output_dir) / "step5_result.json")

    template_image.save(template_path)
    colored_debug_image.save(colored_debug_path)
    palette_sheet_image.save(palette_sheet_path)

    region_ids = np.unique(region_map)
    region_count = len([int(x) for x in region_ids if int(x) != 0])

    result = {
        "step": 5,
        "image_width": int(w),
        "image_height": int(h),
        "region_count": int(region_count),
        "placed_numbers": int(placed_numbers),
        "params": {
            "line_thickness": int(line_thickness),
            "font_size": int(font_size),
            "min_number_area": int(min_number_area),
        },
        "outputs": {
            "template": template_path,
            "colored_debug": colored_debug_path,
            "palette_sheet": palette_sheet_path,
        },
    }

    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    return result