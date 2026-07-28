from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from .io_utils import atomic_write_json
from .models import PreparedSource
from .print_spec import PrintSpec


def prepare_source_image(
    original_image: Path,
    prepared_dir: Path,
    print_spec: PrintSpec,
    fit_mode: str = "cover",
    crop: dict[str, Any] | None = None,
) -> PreparedSource:
    if fit_mode not in {"cover", "contain"}:
        raise ValueError("fit_mode must be cover or contain")
    prepared_dir.mkdir(parents=True, exist_ok=True)
    preserved_original = prepared_dir / f"original{original_image.suffix.lower()}"
    if not preserved_original.exists():
        shutil.copy2(original_image, preserved_original)

    composition_width, composition_height = print_spec.composition_px
    provider_width, provider_height = print_spec.provider_canvas_px

    with Image.open(original_image) as image:
        raw_original_size = image.size
        normalized = ImageOps.exif_transpose(image).convert("RGB")
        original_width, original_height = normalized.size
        crop_box = _resolve_crop_box(normalized.size, print_spec.aspect_ratio, fit_mode, crop)

        if fit_mode == "cover":
            composition = normalized.crop(crop_box).resize(
                (composition_width, composition_height),
                Image.Resampling.LANCZOS,
            )
        else:
            fitted = ImageOps.contain(
                normalized,
                (composition_width, composition_height),
                method=Image.Resampling.LANCZOS,
            )
            composition = Image.new("RGB", (composition_width, composition_height), (255, 255, 255))
            composition.paste(
                fitted,
                ((composition_width - fitted.width) // 2, (composition_height - fitted.height) // 2),
            )

        composition_path = prepared_dir / "cropped_source.png"
        composition.save(composition_path, format="PNG")

        provider_canvas = Image.new("RGB", (provider_width, provider_height), (255, 255, 255))
        content_x = (provider_width - composition_width) // 2
        content_y = (provider_height - composition_height) // 2
        provider_canvas.paste(composition, (content_x, content_y))
        content_box = (content_x, content_y, content_x + composition_width, content_y + composition_height)
        output_path = prepared_dir / "ai_input.png"
        provider_canvas.save(output_path, format="PNG")

    atomic_write_json(
        prepared_dir / "crop_manifest.json",
        {
            "raw_original_size": list(raw_original_size),
            "original_size": [original_width, original_height],
            "normalized_crop": crop if fit_mode == "cover" else None,
            "crop_pixels": list(crop_box),
            "fit_mode": fit_mode,
            "page_size": print_spec.page_size,
            "orientation": print_spec.orientation,
            "composition_size": [composition_width, composition_height],
            "provider_canvas_size": [provider_width, provider_height],
            "provider_content_box": list(content_box),
        },
    )
    return PreparedSource(
        source_path=output_path,
        composition_path=composition_path,
        width=provider_width,
        height=provider_height,
        fit_mode=fit_mode,
        original_width=original_width,
        original_height=original_height,
        content_box=content_box,
    )


def crop_provider_output(provider_output: Path, output_path: Path, prepared: PreparedSource) -> None:
    with Image.open(provider_output) as image:
        rgb = image.convert("RGB")
        scale_x = rgb.width / prepared.width
        scale_y = rgb.height / prepared.height
        left, top, right, bottom = prepared.content_box
        scaled_box = (
            int(round(left * scale_x)),
            int(round(top * scale_y)),
            int(round(right * scale_x)),
            int(round(bottom * scale_y)),
        )
        cropped = rgb.crop(scaled_box)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cropped.save(output_path, format="PNG")


def _resolve_crop_box(
    size: tuple[int, int],
    target_ratio: float,
    fit_mode: str,
    crop: dict[str, Any] | None,
) -> tuple[int, int, int, int]:
    width, height = size
    if fit_mode == "contain":
        return 0, 0, width, height

    if crop:
        x = float(crop.get("x", 0.0))
        y = float(crop.get("y", 0.0))
        crop_width = float(crop.get("width", 1.0))
        crop_height = float(crop.get("height", 1.0))
        if x < 0 or y < 0 or crop_width <= 0 or crop_height <= 0 or x + crop_width > 1.000001 or y + crop_height > 1.000001:
            raise ValueError("crop must be a normalized rectangle inside the source image")
        box = (
            int(round(x * width)),
            int(round(y * height)),
            int(round((x + crop_width) * width)),
            int(round((y + crop_height) * height)),
        )
        actual_ratio = (box[2] - box[0]) / max(1, box[3] - box[1])
        if abs(actual_ratio - target_ratio) / target_ratio > 0.015:
            raise ValueError("crop aspect ratio does not match the selected page orientation")
        return box

    source_ratio = width / height
    if source_ratio > target_ratio:
        crop_width_px = int(round(height * target_ratio))
        left = (width - crop_width_px) // 2
        return left, 0, left + crop_width_px, height
    crop_height_px = int(round(width / target_ratio))
    top = (height - crop_height_px) // 2
    return 0, top, width, top + crop_height_px
