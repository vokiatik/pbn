from __future__ import annotations

import os
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class AIProviderConfig:
    provider: str
    openai_api_key: str
    openai_model: str
    openai_quality: str
    google_api_key: str
    google_model: str
    request_timeout_seconds: int
    max_retries: int
    openai_moderation: str = "low"


def normalize_ai_provider(provider: str) -> str:
    provider = provider.strip().lower()
    if provider == "gpt":
        return "openai"
    if provider == "google":
        return "gemini"
    return provider


def load_ai_provider_config() -> AIProviderConfig:
    return AIProviderConfig(
        provider=normalize_ai_provider(os.getenv("AI_SIMPLIFICATION_PROVIDER", "openai")),
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        openai_model=os.getenv("OPENAI_IMAGE_MODEL", "").strip(),
        openai_quality=normalize_openai_quality(os.getenv("OPENAI_IMAGE_QUALITY", "low")),
        google_api_key=os.getenv("GOOGLE_API_KEY", "").strip(),
        google_model=os.getenv("GOOGLE_IMAGE_MODEL", "").strip(),
        request_timeout_seconds=int(os.getenv("AI_REQUEST_TIMEOUT_SECONDS", "180")),
        max_retries=int(os.getenv("AI_MAX_RETRIES", "2")),
        openai_moderation=normalize_openai_moderation(os.getenv("OPENAI_IMAGE_MODERATION", "low")),
    )


def with_provider_override(config: AIProviderConfig, provider: object) -> AIProviderConfig:
    requested_provider = normalize_ai_provider(str(provider)) if provider is not None else ""
    if not requested_provider:
        return config
    return replace(config, provider=requested_provider)


def normalize_openai_quality(quality: str) -> str:
    normalized = quality.strip().lower()
    if normalized in {"low", "medium", "high", "auto"}:
        return normalized
    return "low"


def normalize_openai_moderation(moderation: str) -> str:
    normalized = moderation.strip().lower()
    if normalized in {"auto", "low"}:
        return normalized
    return "low"
