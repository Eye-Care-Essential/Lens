from __future__ import annotations

import json

from app.ai.base import ProductResult


def extract_json(response_text: str) -> dict:
    """Accept a bare JSON object or one surrounded by prose or code fences."""
    start = response_text.find("{")
    end = response_text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("The AI provider returned no product details.")
    try:
        value = json.loads(response_text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError("The AI provider returned product details in an unreadable format.") from exc
    if not isinstance(value, dict):
        raise ValueError("The AI provider returned product details in an unreadable format.")
    return value


def product_result(raw: dict) -> ProductResult:
    def field(name: str) -> str:
        value = raw.get(name, "")
        return value.strip() if isinstance(value, str) else ""

    name_zh = field("name_zh")
    name_en = field("name_en")
    brand = field("brand")
    model = field("model")
    category = field("category")
    query_zh = field("query_zh") or " ".join(part for part in (brand, model, name_zh, category) if part)
    query_en = field("query_en") or " ".join(part for part in (brand, model, name_en, category) if part)
    if not query_zh and not query_en:
        raise ValueError("The AI provider could not identify the item. Try a clearer photo.")
    return ProductResult(
        name_zh=name_zh,
        name_en=name_en,
        brand=brand,
        model=model,
        category=category,
        query_zh=query_zh or query_en,
        query_en=query_en or query_zh,
        msrp_estimate=field("msrp_estimate"),
        raw=raw,
    )


def safe_error(exc: Exception, api_key: str) -> str:
    message = str(exc)
    if api_key:
        message = message.replace(api_key, "[hidden]")
    return message[:500] or "The provider request failed."


def provider_failure_hint(message: str) -> str:
    """Turn common authentication errors into an actionable self-test result."""
    lowered = message.lower()
    if any(token in lowered for token in ("401", "403", "unauthorized", "api key", "api_key", "invalid key", "authentication")):
        return "Provider rejected the API key. Check the key in Settings."
    return f"Provider connection failed. Check the API key, model, quota, or network. ({message[:220]})"
