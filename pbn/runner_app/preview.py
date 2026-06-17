import traceback
from pathlib import Path

from fastapi import HTTPException
from PIL import Image, ImageOps


def create_upload_preview(original_image: Path, project_dir: Path) -> Path:
    generated_dir = project_dir / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)

    preview_path = generated_dir / "upload_preview.jpg"

    try:
        with Image.open(original_image) as img:
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB")

            # Keep the upload preview small enough for the UI, but stable.
            img.thumbnail((1600, 1600))

            img.save(
                preview_path,
                format="JPEG",
                quality=90,
                optimize=True,
            )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": f"Failed to create upload preview from {original_image}",
                "message": str(exc),
                "traceback": traceback.format_exc(),
            },
        ) from exc

    return preview_path


def upload_preview_result(preview_path: Path) -> dict:
    return {
        "file_type": "upload_preview",
        "filename": "upload_preview.jpg",
        "file_path": str(preview_path),
        "mime_type": "image/jpeg",
        "size_bytes": preview_path.stat().st_size,
    }
