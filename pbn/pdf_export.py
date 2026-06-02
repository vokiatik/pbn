from __future__ import annotations

from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

# Paper sizes with 3 mm bleed on each side (width × height in cm)
PAPER_SIZES_WITH_BLEED_CM: dict[str, tuple[float, float]] = {
    "a4": (21.6, 30.3),   # A4 (21.0 × 29.7) + 3 mm bleed per side
    "a3": (30.3, 42.6),   # A3 (29.7 × 42.0) + 3 mm bleed per side
}


def export_pdf(
    out_path: Path,
    lines_image_path: Path,
    palette_records: list[dict[str, Any]],
    target_size_cm: tuple[float, float] | None = None,
    print_format: str = "a4",
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if target_size_cm is None:
        target_size_cm = PAPER_SIZES_WITH_BLEED_CM.get(print_format, PAPER_SIZES_WITH_BLEED_CM["a4"])

    width_cm, height_cm = target_size_cm
    c = canvas.Canvas(str(out_path), pagesize=(width_cm * cm, height_cm * cm))

    img = ImageReader(str(lines_image_path))
    iw, ih = img.getSize()
    page_w = width_cm * cm
    page_h = height_cm * cm
    scale = min(page_w / float(iw), page_h / float(ih))
    draw_w = iw * scale
    draw_h = ih * scale
    dx = (page_w - draw_w) * 0.5
    dy = (page_h - draw_h) * 0.5
    c.drawImage(
        img,
        dx,
        dy,
        width=draw_w,
        height=draw_h,
        preserveAspectRatio=True,
        mask="auto",
    )
    c.showPage()

    c.setFont("Helvetica-Bold", 16)
    c.drawString(1.5 * cm, (height_cm - 2.0) * cm, "Paint-by-Numbers Palette")

    c.setFont("Helvetica", 10)
    c.drawString(1.5 * cm, (height_cm - 2.8) * cm, "Instructions: paint light colors first, then mid-tones, then dark tones.")

    y = (height_cm - 4.0) * cm
    row_h = 0.62 * cm
    col_x = [1.5 * cm, 11.0 * cm]

    for idx, rec in enumerate(palette_records):
        col = idx % 2
        if idx > 0 and col == 0:
            y -= row_h
            if y < 1.8 * cm:
                c.showPage()
                c.setFont("Helvetica", 10)
                y = (height_cm - 2.2) * cm

        x = col_x[col]
        rgb = [int(v) for v in rec.get("rgb", [0, 0, 0])]
        c.setFillColor(colors.Color(rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0))
        c.rect(x, y - 0.35 * cm, 0.45 * cm, 0.45 * cm, fill=1, stroke=1)

        c.setFillColor(colors.black)
        number = int(rec.get("number", idx + 1))
        hex_code = str(rec.get("hex", "#000000"))
        c.drawString(x + 0.6 * cm, y - 0.2 * cm, f"{number:02d}: {hex_code}  RGB {rgb[0]},{rgb[1]},{rgb[2]}")

    c.showPage()
    c.save()
