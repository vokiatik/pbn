from pathlib import Path
from typing import Any

from fastapi import HTTPException

from runner_app.config import PROJECTS_DIR


def as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        return value.lower().strip() in {"1", "true", "yes", "y", "on"}

    return bool(value)


def require_file(path: Path, label: str) -> str:
    if not path.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Missing {label}: {path}",
        )

    return str(path)


def get_project_dir_by_ids(project_id: str, public_id: str | None = None) -> Path:
    folder_name = public_id or project_id
    project_dir = PROJECTS_DIR / folder_name

    if not project_dir.exists():
        available_projects: list[str] = []

        if PROJECTS_DIR.exists():
            available_projects = [p.name for p in PROJECTS_DIR.iterdir() if p.is_dir()]

        raise HTTPException(
            status_code=404,
            detail={
                "error": "Project directory not found",
                "project_dir": str(project_dir),
                "projects_dir": str(PROJECTS_DIR),
                "available_projects": available_projects[:50],
            },
        )

    return project_dir


def find_original_image(project_dir: Path) -> Path:
    candidates = [
        project_dir / "original.png",
        project_dir / "original.jpg",
        project_dir / "original.jpeg",
        project_dir / "original.webp",
        project_dir / "original.heic",
        project_dir / "original.heif",
    ]

    original_dir = project_dir / "original"

    if original_dir.exists():
        for ext in ["*.png", "*.jpg", "*.jpeg", "*.webp", "*.heic", "*.heif"]:
            candidates.extend(sorted(original_dir.glob(ext)))

    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise HTTPException(
        status_code=400,
        detail={
            "error": "Original image not found",
            "project_dir": str(project_dir),
            "checked": [str(candidate) for candidate in candidates],
        },
    )


def resolve_original_image(project_dir: Path, input_path: str | None = None) -> Path:
    if not input_path:
        return find_original_image(project_dir)

    project_root = project_dir.resolve()
    candidate = Path(input_path)
    if not candidate.is_absolute():
        candidate = project_dir / candidate
    candidate = candidate.resolve()

    try:
        candidate.relative_to(project_root)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Input image must be inside the project directory",
                "project_dir": str(project_root),
                "input_path": str(candidate),
            },
        ) from exc

    if not candidate.exists():
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Input image not found",
                "input_path": str(candidate),
            },
        )

    return candidate
