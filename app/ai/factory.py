from __future__ import annotations

from app.ai.base import VisionProvider
from app.config import AppConfig, PROVIDER_IDS


def create_provider(config: AppConfig, provider_id: str | None = None) -> VisionProvider:
    selected = (provider_id or config.active_provider).lower()
    if selected not in PROVIDER_IDS:
        raise ValueError(f"Unsupported AI provider: {selected}")
    settings = config.providers[selected]
    timeout = config.ai_timeout_sec
    if selected == "gemini":
        from app.ai.gemini_provider import GeminiProvider

        return GeminiProvider(settings.api_key, settings.model, timeout)
    if selected == "claude":
        from app.ai.anthropic_provider import ClaudeProvider

        return ClaudeProvider(settings.api_key, settings.model, timeout)

    from app.ai.openai_provider import OpenAICompatibleProvider

    return OpenAICompatibleProvider(
        api_key=settings.api_key,
        model=settings.model,
        base_url=settings.base_url if selected == "custom" else "",
        timeout_sec=timeout,
        compatible=selected == "custom",
    )
