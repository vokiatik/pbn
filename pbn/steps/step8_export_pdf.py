import json
from pathlib import Path
from typing import Any, Literal

from PIL import Image, ImageOps


def ensure_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def cm_to_px(cm: float, dpi: int) -> int:
    return int((cm / 2.54) * dpi)


def fit_image_to_page(
    image: Image.Image,
    page_w: int,
    page_h: int,
    resampling: Image.Resampling = Image.Resampling.NEAREST,
    fit_mode: Literal["contain", "cover", "stretch"] = "cover",
) -> Image.Image:
    img = image.copy()

    if fit_mode == "contain":
        img.thumbnail((page_w, page_h), resampling)

        page = Image.new("RGB", (page_w, page_h), "white")
        x = (page_w - img.width) // 2
        y = (page_h - img.height) // 2
        page.paste(img, (x, y))
        return page

    if fit_mode == "cover":
        return ImageOps.fit(
            img,
            (page_w, page_h),
            method=resampling,
            centering=(0.5, 0.5),
        ).convert("RGB")

    if fit_mode == "stretch":
        return img.resize((page_w, page_h), resampling).convert("RGB")

    raise ValueError(
        f"Unsupported fit_mode: {fit_mode}. "
        f"Expected one of: 'contain', 'cover', 'stretch'."
    )


def run_step8_export_pdf(
    template_path: str,
    palette_sheet_path: str,
    output_dir: str,
    page_width_cm: float = 29.7,
    page_height_cm: float = 42.0,
    dpi: int = 300,
    fit_mode: Literal["contain", "cover", "stretch"] = "cover",
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
        fit_mode=fit_mode,
    )

    palette_page = fit_image_to_page(
        image=palette_sheet,
        page_w=page_w,
        page_h=page_h,
        resampling=Image.Resampling.LANCZOS,
        fit_mode=fit_mode,
    )

    template_pdf_path = str(Path(output_dir) / "step8_pbn_template_A3_preview.pdf")
    palette_pdf_path = str(Path(output_dir) / "step8_palette_sheet_A3.pdf")
    template_png_path = str(Path(output_dir) / "step8_pbn_template_A3_preview.png")
    final_png_path = str(Path(output_dir) / "pbn_final.png")
    final_palette_png_path = str(Path(output_dir) / "pbn_final_palette.png")
    result_path = str(Path(output_dir) / "step8_result.json")

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

    template_page.save(
        final_png_path,
        dpi=(dpi, dpi),
    )

    palette_page.save(
        final_palette_png_path,
        dpi=(dpi, dpi),
    )

    result = {
        "step": 8,
        "page_width_cm": float(page_width_cm),
        "page_height_cm": float(page_height_cm),
        "dpi": int(dpi),
        "fit_mode": fit_mode,
        "page_width_px": int(page_w),
        "page_height_px": int(page_h),
        "template_source_width_px": int(template.width),
        "template_source_height_px": int(template.height),
        "outputs": {
            "preview": final_png_path,
            "template_preview": final_png_path,
            "palette_preview": final_palette_png_path,
            "pbn_final": final_png_path,
            "pbn_final_palette": final_palette_png_path,
            "template_pdf": template_pdf_path,
            "palette_pdf": palette_pdf_path,
        }
    }

    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    return result
