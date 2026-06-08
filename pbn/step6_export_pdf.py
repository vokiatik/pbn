import json
from pathlib import Path
from typing import Any

from PIL import Image


def ensure_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def cm_to_px(cm: float, dpi: int) -> int:
    return int((cm / 2.54) * dpi)


def fit_image_to_page(
    image: Image.Image,
    page_w: int,
    page_h: int,
    resampling: Image.Resampling = Image.Resampling.NEAREST,
) -> Image.Image:
    img = image.copy()

    img.thumbnail(
        (page_w, page_h),
        resampling,
    )

    page = Image.new("RGB", (page_w, page_h), "white")

    x = (page_w - img.width) // 2
    y = (page_h - img.height) // 2

    page.paste(img, (x, y))

    return page


def run_step6_export_pdf(
    template_path: str,
    palette_sheet_path: str,
    output_dir: str,
    page_width_cm: float = 29.7,
    page_height_cm: float = 42.0,
    dpi: int = 300,
) -> dict[str, Any]:
    ensure_dir(output_dir)

    page_w = cm_to_px(page_width_cm, dpi)
    page_h = cm_to_px(page_height_cm, dpi)

    template = Image.open(template_path).convert("RGB")
    palette_sheet = Image.open(palette_sheet_path).convert("RGB")

    template_page = fit_image_to_page(
        image=template,
        page_w=page_w,
        page_h=page_h,
        resampling=Image.Resampling.NEAREST,
    )

    palette_page = fit_image_to_page(
        image=palette_sheet,
        page_w=page_w,
        page_h=page_h,
        resampling=Image.Resampling.LANCZOS,
    )

    template_pdf_path = str(Path(output_dir) / "pbn_template_A3.pdf")
    palette_pdf_path = str(Path(output_dir) / "palette_sheet_A3.pdf")
    template_png_path = str(Path(output_dir) / "pbn_template_A3_preview.png")
    result_path = str(Path(output_dir) / "step6_result.json")

    template_page.save(
        template_pdf_path,
        "PDF",
        resolution=dpi,
    )

    palette_page.save(
        palette_pdf_path,
        "PDF",
        resolution=dpi,
    )

    template_page.save(
        template_png_path,
        dpi=(dpi, dpi),
    )

    result = {
        "step": 6,
        "page_width_cm": float(page_width_cm),
        "page_height_cm": float(page_height_cm),
        "dpi": int(dpi),
        "page_width_px": int(page_w),
        "page_height_px": int(page_h),
        "template_source_width_px": int(template.width),
        "template_source_height_px": int(template.height),
        "outputs": {
            "template_pdf": template_pdf_path,
            "palette_pdf": palette_pdf_path,
            "template_preview": template_png_path,
        },
    }

    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    return result