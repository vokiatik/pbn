from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

from .http_client import HTTPTransport, UrllibTransport, json_request
from .models import (
    ProviderConfigurationError,
    ProviderRequestError,
    ProviderResponseError,
    SimplificationInstructions,
    SimplificationResult,
)
from .prompts import build_simplification_prompt


class GeminiImageProvider:
    provider_name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: int = 180,
        transport: HTTPTransport | None = None,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta/models",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.transport = transport or UrllibTransport()
        self.base_url = base_url.rstrip("/")

    def simplify(
        self,
        source_image: Path,
        output_path: Path,
        instructions: SimplificationInstructions,
    ) -> SimplificationResult:
        if not self.api_key:
            raise ProviderConfigurationError("GOOGLE_API_KEY is required for Gemini image simplification")
        if not self.model:
            raise ProviderConfigurationError("GOOGLE_IMAGE_MODEL is required for Gemini image simplification")

        request = build_gemini_edit_request(
            source_image=source_image,
            api_key=self.api_key,
            model=self.model,
            instructions=instructions,
            base_url=self.base_url,
        )
        response = self.transport.send(request, self.timeout_seconds)
        if response.status_code < 200 or response.status_code >= 300:
            raise ProviderRequestError(f"Gemini image edit failed with HTTP {response.status_code}")

        payload = response.json()
        image_bytes = _extract_single_gemini_image(payload)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(image_bytes)
        return SimplificationResult(
            provider=self.provider_name,
            model=self.model,
            output_path=output_path,
            metadata={"response": _safe_metadata(payload)},
        )


def build_gemini_edit_request(
    source_image: Path,
    api_key: str,
    model: str,
    instructions: SimplificationInstructions,
    base_url: str = "https://generativelanguage.googleapis.com/v1beta/models",
):
    mime_type = mimetypes.guess_type(source_image.name)[0] or "image/png"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": build_simplification_prompt(instructions)},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": base64.b64encode(source_image.read_bytes()).decode("ascii"),
                        }
                    },
                ]
            }
        ],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }
    return json_request(
        "POST",
        f"{base_url.rstrip('/')}/{model}:generateContent",
        headers={"x-goog-api-key": api_key},
        payload=payload,
    )


def _extract_single_gemini_image(payload: object) -> bytes:
    images: list[str] = []
    if isinstance(payload, dict):
        for candidate in payload.get("candidates", []) or []:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content")
            parts = content.get("parts", []) if isinstance(content, dict) else []
            for part in parts:
                if not isinstance(part, dict):
                    continue
                inline_data = part.get("inlineData") or part.get("inline_data")
                if isinstance(inline_data, dict) and inline_data.get("data"):
                    images.append(str(inline_data["data"]))
    if len(images) != 1:
        raise ProviderResponseError(f"Gemini response contained {len(images)} images; expected exactly one")
    try:
        return base64.b64decode(images[0], validate=True)
    except ValueError as exc:
        raise ProviderResponseError("Gemini image payload was not valid base64") from exc


def _safe_metadata(payload: object) -> object:
    if not isinstance(payload, dict):
        return {}
    redacted = dict(payload)
    for candidate in redacted.get("candidates", []) or []:
        if isinstance(candidate, dict) and isinstance(candidate.get("content"), dict):
            for part in candidate["content"].get("parts", []) or []:
                if isinstance(part, dict):
                    part.pop("inlineData", None)
                    part.pop("inline_data", None)
    return redacted

