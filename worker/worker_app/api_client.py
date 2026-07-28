from __future__ import annotations

import logging
from typing import Any

import requests

from .config import WorkerConfig
from .types import FileRecord

logger = logging.getLogger(__name__)


class BackendInternalClient:
    def __init__(self, config: WorkerConfig) -> None:
        self.config = config

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-Internal-Secret": self.config.api_secret}

    def post_status(
        self,
        project_id: str,
        status: str,
        progress: int = 0,
        message: str = "",
        error_message: str = "",
    ) -> bool:
        payload: dict[str, int | str] = {
            "status": status,
            "progress": progress,
            "message": message,
            "error_message": error_message,
        }

        response = requests.post(
            f"{self.config.api_base}/projects/{project_id}/status",
            headers=self._headers,
            timeout=15,
            json=payload,
        )
        response.raise_for_status()
        response_payload: dict[str, Any] = response.json()
        return response_payload.get("applied") is not False

    def post_files(
        self,
        project_id: str,
        files: list[FileRecord],
    ) -> list[FileRecord]:
        """Register files in backend and return backend-saved records.

        This matters because local file records do not have DB IDs. The React preview URL
        needs backend file IDs, so events should contain the saved response records.
        """
        if not files:
            return []

        response = requests.post(
            f"{self.config.api_base}/projects/{project_id}/files",
            headers=self._headers,
            timeout=30,
            json={"files": files},
        )
        response.raise_for_status()

        payload: dict[str, Any] = response.json()
        saved_files = payload.get("files")
        if isinstance(saved_files, list):
            return saved_files

        logger.warning("backend /files response did not include files; falling back to local records")
        return files

    def post_pbn_options(self, project_id: str, options: list[dict[str, Any]]) -> None:
        response = requests.post(
            f"{self.config.api_base}/projects/{project_id}/pbn-options",
            headers=self._headers,
            timeout=30,
            json={"options": options},
        )
        response.raise_for_status()

    def post_ai_quality(self, project_id: str, quality: dict[str, Any]) -> None:
        response = requests.post(
            f"{self.config.api_base}/projects/{project_id}/ai-quality",
            headers=self._headers,
            timeout=30,
            json={"quality": quality},
        )
        response.raise_for_status()

    def post_pbn_selection(self, project_id: str, difficulty: str) -> None:
        response = requests.post(
            f"{self.config.api_base}/projects/{project_id}/pbn-selection",
            headers=self._headers,
            timeout=30,
            json={"difficulty": difficulty},
        )
        response.raise_for_status()
