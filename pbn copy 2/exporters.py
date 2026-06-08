from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .contour_extraction import RegionContour
from .number_placement import RegionNumber
from .palette_matching import PaletteDataV2


PAGE_SIZES_CM: dict[str, tuple[float, float]] = {
    "a4": (21.0, 29.7),
    "a3": (29.7, 42.0),
}


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def save_png(path: Path, image_rgb: np.ndarray) -> None:
    ensure_dir(path.parent)
    Image.fromarray(image_rgb.astype(np.uint8)).save(path)


def save_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def build_colored_preview(label_map: np.ndarray, palette: PaletteDataV2) -> np.ndarray:
    return palette.rgb[label_map].astype(np.uint8)


def _draw_contours_base(shape: tuple[int, int], contours: list[RegionContour], line_width: int) -> np.ndarray:
    h, w = shape
    canvas = np.full((h, w, 3), 255, dtype=np.uint8)
    for rc in contours:
        if len(rc.contour) < 2:
            continue
        contour = rc.contour.reshape(-1, 1, 2)
        cv2.drawContours(canvas, [contour], contourIdx=-1, color=(0, 0, 0), thickness=line_width, lineType=cv2.LINE_AA)
    return canvas


def build_outline_image(shape: tuple[int, int], contours: list[RegionContour], line_width: int) -> np.ndarray:
    return _draw_contours_base(shape, contours, line_width)


def build_numbered_image(
    shape: tuple[int, int],
    contours: list[RegionContour],
    numbers: list[RegionNumber],
    line_width: int,
    font_scale: float,
) -> np.ndarray:
    canvas = _draw_contours_base(shape, contours, line_width)
    for region in numbers:
        if region.number_skipped or region.number_position_xy is None:
            continue
        if region.uses_external_label and region.leader_line_start_xy is not None and region.leader_line_end_xy is not None:
            cv2.line(canvas, region.leader_line_start_xy, region.leader_line_end_xy, (0, 0, 0), 1, cv2.LINE_AA)
            cv2.line(canvas, region.leader_line_end_xy, region.number_position_xy, (0, 0, 0), 1, cv2.LINE_AA)
        x, y = region.number_position_xy
        text = str(region.color_label + 1)
        (tw, th), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1)
        tx = int(x - tw / 2)
        ty = int(y + th / 2)
        cv2.putText(canvas, text, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 0, 0), 1, cv2.LINE_AA)
    return canvas


def save_palette_json(path: Path, palette: PaletteDataV2) -> None:
    records = []
    for idx in range(len(palette.numbers)):
        records.append(
            {
                "number": int(palette.numbers[idx]),
                "name": palette.names[idx],
                "hex": palette.hex_codes[idx],
                "rgb": [int(v) for v in palette.rgb[idx].tolist()],
                "lab": [float(round(v, 3)) for v in palette.lab[idx].tolist()],
            }
        )
    save_json(path, records)


def save_svg(
    path: Path,
    shape: tuple[int, int],
    contours: list[RegionContour],
    numbers: list[RegionNumber],
    palette: PaletteDataV2,
) -> None:
    ensure_dir(path.parent)
    h, w = shape
    lines: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
        '<rect x="0" y="0" width="100%" height="100%" fill="white"/>',
    ]

    for rc in contours:
        pts = rc.contour
        if pts.shape[0] < 3:
            continue
        parts = [f"M {int(pts[0, 0])} {int(pts[0, 1])}"]
        for p in pts[1:]:
            parts.append(f"L {int(p[0])} {int(p[1])}")
        parts.append("Z")
        color_hex = palette.hex_codes[int(rc.color_label)]
        d = " ".join(parts)
        lines.append(f'<path d="{d}" fill="{color_hex}" stroke="#000000" stroke-width="1"/>')

    for region in numbers:
        if region.number_skipped or region.number_position_xy is None:
            continue
        if region.uses_external_label and region.leader_line_start_xy is not None and region.leader_line_end_xy is not None:
            sx, sy = region.leader_line_start_xy
            ex, ey = region.leader_line_end_xy
            lx, ly = region.number_position_xy
            lines.append(f'<line x1="{sx}" y1="{sy}" x2="{ex}" y2="{ey}" stroke="#000000" stroke-width="1"/>')
            lines.append(f'<line x1="{ex}" y1="{ey}" x2="{lx}" y2="{ly}" stroke="#000000" stroke-width="1"/>')
        x, y = region.number_position_xy
        text = str(region.color_label + 1)
        lines.append(
            f'<text x="{x}" y="{y}" font-family="Arial" font-size="10" text-anchor="middle" '
            f'alignment-baseline="middle" fill="#000000">{text}</text>'
        )

    lines.append("</svg>")
    path.write_text("\n".join(lines), encoding="utf-8")


def export_pdf(out_path: Path, numbered_png: Path, palette: PaletteDataV2, page_size: str) -> None:
    ensure_dir(out_path.parent)
    width_cm, height_cm = PAGE_SIZES_CM.get(page_size.lower(), PAGE_SIZES_CM["a4"])
    c = canvas.Canvas(str(out_path), pagesize=(width_cm * cm, height_cm * cm))

    img = ImageReader(str(numbered_png))
    iw, ih = img.getSize()
    page_w = width_cm * cm
    page_h = height_cm * cm
    scale = min(page_w / float(iw), page_h / float(ih))
    draw_w = iw * scale
    draw_h = ih * scale
    dx = (page_w - draw_w) * 0.5
    dy = (page_h - draw_h) * 0.5
    c.drawImage(img, dx, dy, width=draw_w, height=draw_h, preserveAspectRatio=True, mask="auto")
    c.showPage()

    c.setFont("Helvetica-Bold", 16)
    c.drawString(1.5 * cm, (height_cm - 1.8) * cm, "Paint by Number Palette")

    c.setFont("Helvetica", 10)
    y = (height_cm - 3.0) * cm
    row_h = 0.9 * cm
    for idx in range(len(palette.numbers)):
        if y < 1.5 * cm:
            c.showPage()
            c.setFont("Helvetica", 10)
            y = (height_cm - 2.0) * cm

        rgb = palette.rgb[idx]
        c.setFillColor(colors.Color(rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0))
        c.rect(1.5 * cm, y - 0.45 * cm, 0.55 * cm, 0.55 * cm, stroke=1, fill=1)

        c.setFillColor(colors.black)
        c.drawString(
            2.3 * cm,
            y - 0.2 * cm,
            f"{int(palette.numbers[idx]):02d}  {palette.names[idx]}  {palette.hex_codes[idx]}",
        )
        y -= row_h

    c.showPage()
    c.save()
