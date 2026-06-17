from __future__ import annotations

import requests

from .config import WorkerConfig
from .types import JsonDict


class PythonRunnerClient:
    def __init__(self, config: WorkerConfig) -> None:
        self.config = config

    def run_step(
        self,
        step: int,
        project_id: str,
        public_id: str,
        parameters: JsonDict,
    ) -> JsonDict:
        response = requests.post(
            f"{self.config.python_runner_base_url}/run-step/{step}",
            timeout=60 * 60,
            json={
                "project_id": project_id,
                "public_id": public_id,
                "params": parameters,
            },
        )
        response.raise_for_status()
        return response.json()

    def generate_upload_preview(self, project_id: str, public_id: str) -> JsonDict:
        response = requests.post(
            f"{self.config.python_runner_base_url}/generate-upload-preview",
            timeout=5 * 60,
            json={
                "project_id": project_id,
                "public_id": public_id,
            },
        )
        response.raise_for_status()
        return response.json()
