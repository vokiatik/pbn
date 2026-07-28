from __future__ import annotations

import base64
from pathlib import Path

from .http_client import (
    HTTPTransport,
    UrllibTransport,
    multipart_form_request,
    provider_request_error,
)
from .models import (
    ProviderConfigurationError,
    ProviderResponseError,
    SimplificationInstructions,
    SimplificationResult,
)
from .prompts import build_simplification_prompt


class OpenAIImageProvider:
    provider_name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str,
        quality: str = "low",
        moderation: str = "low",
        timeout_seconds: int = 180,
        transport: HTTPTransport | None = None,
        base_url: str = "https://api.openai.com/v1/images/edits",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.quality = _normalize_quality(quality)
        self.moderation = _normalize_moderation(moderation)
        self.cache_fingerprint = (
            f"openai-images-edit:quality={self.quality}:moderation={self.moderation}:format=png:v2"
        )
        self.timeout_seconds = timeout_seconds
        self.transport = transport or UrllibTransport()
        self.base_url = base_url

    def simplify(
        self,
        source_image: Path,
        output_path: Path,
        instructions: SimplificationInstructions,
    ) -> SimplificationResult:
        if not self.api_key:
            raise ProviderConfigurationError("OPENAI_API_KEY is required for OpenAI image simplification")
        if not self.model:
            raise ProviderConfigurationError("OPENAI_IMAGE_MODEL is required for OpenAI image simplification")

        request = build_openai_edit_request(
            source_image=source_image,
            api_key=self.api_key,
            model=self.model,
            quality=self.quality,
            moderation=self.moderation,
            instructions=instructions,
            url=self.base_url,
        )
        response = self.transport.send(request, self.timeout_seconds)
        if response.status_code < 200 or response.status_code >= 300:
            raise provider_request_error(response.status_code, response.body, response.headers)

        payload = response.json()
        image_bytes = _extract_single_openai_image(payload)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(image_bytes)
        return SimplificationResult(
            provider=self.provider_name,
            model=self.model,
            output_path=output_path,
            metadata={"response": _safe_metadata(payload)},
        )


def build_openai_edit_request(
    source_image: Path,
    api_key: str,
    model: str,
    instructions: SimplificationInstructions,
    quality: str = "low",
    moderation: str = "low",
    url: str = "https://api.openai.com/v1/images/edits",
):
    fields = {
        "model": model,
        "prompt": build_simplification_prompt(instructions),
        "n": "1",
        "size": _openai_size(instructions.output_width, instructions.output_height),
        "quality": _normalize_quality(quality),
        "output_format": "png",
    }
    if _supports_moderation(model):
        fields["moderation"] = _normalize_moderation(moderation)
    if _supports_input_fidelity(model):
        fields["input_fidelity"] = "high"
    return multipart_form_request(
        "POST",
        url,
        headers={"Authorization": f"Bearer {api_key}"},
        fields=fields,
        files={"image": source_image},
    )


def _supports_input_fidelity(model: str) -> bool:
    normalized = model.strip().lower()
    return normalized == "gpt-image-1"


def _supports_moderation(model: str) -> bool:
    return model.strip().lower().startswith("gpt-image-")


def _normalize_quality(quality: str) -> str:
    normalized = quality.strip().lower()
    if normalized in {"low", "medium", "high", "auto"}:
        return normalized
    return "low"


def _normalize_moderation(moderation: str) -> str:
    normalized = moderation.strip().lower()
    if normalized in {"auto", "low"}:
        return normalized
    return "low"


def _openai_size(width: int, height: int) -> str:
    if width > height:
        return "1536x1024"
    if height > width:
        return "1024x1536"
    return "1024x1024"


def _extract_single_openai_image(payload: object) -> bytes:
    if not isinstance(payload, dict):
        raise ProviderResponseError("OpenAI response was not a JSON object")
    data = payload.get("data")
    if not isinstance(data, list):
        raise ProviderResponseError("OpenAI response did not contain a data list")
    images = [item.get("b64_json") for item in data if isinstance(item, dict) and item.get("b64_json")]
    if len(images) != 1:
        raise ProviderResponseError(f"OpenAI response contained {len(images)} images; expected exactly one")
    try:
        if images[0] is not None: return base64.b64decode(images[0], validate=True)
        else: raise ProviderResponseError(f"OpenAI response contained {len(images)} images; expected exactly one")
    except ValueError as exc:
        raise ProviderResponseError("OpenAI image payload was not valid base64") from exc


def _safe_metadata(payload: object) -> object:
    if not isinstance(payload, dict):
        return {}
    return {key: value for key, value in payload.items() if key != "data"}
