from __future__ import annotations

import mimetypes
from pathlib import Path

from .constants import PUBLIC_STEP_FILES
from .types import FileRecord


def build_project_root(payload: dict, public_id: str) -> Path:
    return Path(
        payload.get("project_root")
        or payload.get("output_path")
        or f"/storage/projects/{public_id}"
    )


def file_record(file_type: str, path: Path) -> FileRecord:
    mime_type, _ = mimetypes.guess_type(path.name)
    return {
        "file_type": file_type,
        "filename": path.name,
        "file_path": str(path),
        "mime_type": mime_type or "application/octet-stream",
        "size_bytes": path.stat().st_size,
    }


def public_step_files(project_root: Path, step: int) -> list[FileRecord]:
    out: list[FileRecord] = []

    for file_type, rel_path in PUBLIC_STEP_FILES.get(step, []):
        path = project_root / rel_path
        if path.exists() and path.is_file():
            out.append(file_record(file_type, path))
    print(f"public_step_files for step {step}: {[f['filename'] for f in out]}")
    return out


def detect_upload_preview_file(project_root: Path) -> list[FileRecord]:
    preview_path = project_root / "generated" / "upload_preview.jpg"
    if not preview_path.exists() or not preview_path.is_file():
        return []

    return [
        {
            "file_type": "upload_preview",
            "filename": "upload_preview.jpg",
            "file_path": str(preview_path),
            "mime_type": "image/jpeg",
            "size_bytes": preview_path.stat().st_size,
        }
    ]


def detect_files(output_path: Path) -> list[FileRecord]:
    discovered: list[FileRecord] = []

    if not output_path.exists():
        return discovered

    for path in sorted(output_path.rglob("*")):
        if not path.is_file():
            continue

        rel = path.relative_to(output_path)
        file_type = str(rel.with_suffix("")).replace("\\", "_").replace("/", "_")
        discovered.append(file_record(file_type, path))

    return discovered
