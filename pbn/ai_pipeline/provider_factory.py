from __future__ import annotations

from .config import AIProviderConfig
from .models import ImageSimplificationProvider, ProviderConfigurationError
from .providers_gemini import GeminiImageProvider
from .providers_openai import OpenAIImageProvider


def create_provider(config: AIProviderConfig) -> ImageSimplificationProvider:
    provider = _resolve_provider_name(config)
    if provider == "openai":
        return OpenAIImageProvider(
            api_key=config.openai_api_key,
            model=config.openai_model,
            quality=config.openai_quality,
            moderation=config.openai_moderation,
            timeout_seconds=config.request_timeout_seconds,
        )
    if provider == "gemini":
        return GeminiImageProvider(
            api_key=config.google_api_key,
            model=config.google_model,
            timeout_seconds=config.request_timeout_seconds,
        )
    raise ProviderConfigurationError(
        "AI_SIMPLIFICATION_PROVIDER must be one of: openai, gemini"
    )


def _resolve_provider_name(config: AIProviderConfig) -> str:
    provider = config.provider
    if provider in {"", "auto"}:
        configured = _configured_providers(config)
        if configured:
            return configured[0]
        raise ProviderConfigurationError(_no_provider_message())

    if provider not in {"openai", "gemini"}:
        raise ProviderConfigurationError(
            "AI_SIMPLIFICATION_PROVIDER must be one of: openai, gemini"
        )

    if _is_provider_configured(config, provider):
        return provider

    configured = _configured_providers(config)
    if len(configured) == 1:
        return configured[0]

    missing = _missing_config(config, provider)
    if configured:
        raise ProviderConfigurationError(
            f"{provider} image simplification is not fully configured; "
            f"missing {', '.join(missing)}"
        )
    raise ProviderConfigurationError(_no_provider_message())


def _configured_providers(config: AIProviderConfig) -> list[str]:
    return [provider for provider in ("openai", "gemini") if _is_provider_configured(config, provider)]


def _is_provider_configured(config: AIProviderConfig, provider: str) -> bool:
    if provider == "openai":
        return bool(config.openai_api_key and config.openai_model)
    if provider == "gemini":
        return bool(config.google_api_key and config.google_model)
    return False


def _missing_config(config: AIProviderConfig, provider: str) -> list[str]:
    if provider == "openai":
        missing = []
        if not config.openai_api_key:
            missing.append("OPENAI_API_KEY")
        if not config.openai_model:
            missing.append("OPENAI_IMAGE_MODEL")
        return missing
    if provider == "gemini":
        missing = []
        if not config.google_api_key:
            missing.append("GOOGLE_API_KEY")
        if not config.google_model:
            missing.append("GOOGLE_IMAGE_MODEL")
        return missing
    return []


def _no_provider_message() -> str:
    return (
        "No AI image provider is configured. Set either OPENAI_API_KEY and "
        "OPENAI_IMAGE_MODEL, or GOOGLE_API_KEY and GOOGLE_IMAGE_MODEL."
    )
