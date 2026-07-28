from __future__ import annotations

import requests

from .config import WorkerConfig
from .types import JsonDict


class RunnerRequestError(RuntimeError):
    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = code != "moderation_blocked"


def _runner_error_detail(response: requests.Response) -> object:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or response.reason

    return payload.get("detail", payload) if isinstance(payload, dict) else payload


def _runner_error_message(response: requests.Response, detail: object | None = None) -> str:
    if detail is None:
        detail = _runner_error_detail(response)

    if isinstance(detail, dict):
        error = detail.get("error")
        if isinstance(error, str) and error:
            return _format_moderation_error(error, detail)
    if isinstance(detail, str) and detail:
        return detail
    return response.text.strip() or response.reason


def _format_moderation_error(message: str, detail: dict[str, object]) -> str:
    if detail.get("code") != "moderation_blocked":
        return message

    parts = [message]
    moderation_details = detail.get("moderation_details")
    stage = None
    categories: list[str] = []
    if isinstance(moderation_details, dict):
        raw_stage = moderation_details.get("moderation_stage")
        if isinstance(raw_stage, str) and raw_stage:
            stage = raw_stage
            parts.append(f"Moderation stage: {stage}.")
        raw_categories = moderation_details.get("categories")
        if isinstance(raw_categories, list):
            categories = [value for value in raw_categories if isinstance(value, str) and value]
            if categories:
                parts.append(f"Categories: {', '.join(categories)}.")

    if "harassment" in categories:
        parts.append("Try removing abusive or targeting language and focus on neutral visual details.")
    elif stage == "input":
        parts.append("Try revising the prompt or input image, then generate again.")
    elif stage == "output":
        parts.append("The generated result was blocked; change the prompt and generate again.")
    else:
        parts.append("Try changing the prompt or input image, then generate again.")

    request_id = detail.get("request_id")
    if isinstance(request_id, str) and request_id and request_id not in message:
        parts.append(f"OpenAI request ID: {request_id}.")
    return " ".join(parts)


class PythonRunnerClient:
    def __init__(self, config: WorkerConfig) -> None:
        self.config = config

    def generate_upload_preview(self, project_id: str, public_id: str, input_path: str | None = None) -> JsonDict:
        response = requests.post(
            f"{self.config.python_runner_base_url}/generate-upload-preview",
            timeout=5 * 60,
            json={
                "project_id": project_id,
                "public_id": public_id,
                "input_path": input_path,
            },
        )
        response.raise_for_status()
        return response.json()

    def run_ai_pipeline(
        self,
        project_id: str,
        public_id: str,
        settings: JsonDict,
        input_path: str | None = None,
    ) -> JsonDict:
        return self._post_pipeline(
            endpoint="run-ai-pipeline",
            project_id=project_id,
            public_id=public_id,
            settings=settings,
            input_path=input_path,
        )

    def generate_ai_image(
        self,
        project_id: str,
        public_id: str,
        settings: JsonDict,
        input_path: str | None = None,
        force_regenerate: bool = False,
    ) -> JsonDict:
        return self._post_pipeline(
            endpoint="generate-ai-image",
            project_id=project_id,
            public_id=public_id,
            settings=settings,
            input_path=input_path,
            force_regenerate=force_regenerate,
        )

    def continue_ai_pipeline(
        self,
        project_id: str,
        public_id: str,
        settings: JsonDict,
        input_path: str | None = None,
    ) -> JsonDict:
        return self._post_pipeline(
            endpoint="continue-ai-pipeline",
            project_id=project_id,
            public_id=public_id,
            settings=settings,
            input_path=input_path,
        )

    def finalize_pbn_option(
        self,
        project_id: str,
        public_id: str,
        settings: JsonDict,
        difficulty: str,
        input_path: str | None = None,
    ) -> JsonDict:
        return self._post_pipeline(
            endpoint="finalize-pbn-option",
            project_id=project_id,
            public_id=public_id,
            settings=settings,
            input_path=input_path,
            extra_payload={"difficulty": difficulty},
        )

    def _post_pipeline(
        self,
        endpoint: str,
        project_id: str,
        public_id: str,
        settings: JsonDict,
        input_path: str | None = None,
        force_regenerate: bool = False,
        extra_payload: JsonDict | None = None,
    ) -> JsonDict:
        response = requests.post(
            f"{self.config.python_runner_base_url}/{endpoint}",
            timeout=60 * 60,
            json={
                "project_id": project_id,
                "public_id": public_id,
                "input_path": input_path,
                "settings": settings,
                "force_regenerate": force_regenerate,
                "callback_base": self.config.api_base,
                "callback_secret": self.config.api_secret,
                **(extra_payload or {}),
            },
        )
        if not response.ok:
            detail = _runner_error_detail(response)
            code = detail.get("code") if isinstance(detail, dict) and isinstance(detail.get("code"), str) else None
            raise RunnerRequestError(
                f"AI pipeline runner request failed ({response.status_code}): "
                f"{_runner_error_message(response, detail)}",
                code=code,
            )
        return response.json()

    def is_ready(self) -> bool:
        try:
            response = requests.get(f"{self.config.python_runner_base_url}/health", timeout=5)
            return bool(response.ok and response.json().get("ok"))
        except requests.RequestException:
            return False
