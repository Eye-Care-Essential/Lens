from __future__ import annotations

import json

from app.ai.base import ProductResult


def extract_json(response_text: str) -> dict:
    """Accept a bare JSON object or one surrounded by prose or code fences."""
    start = response_text.find("{")
    end = response_text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("AI 供應商未回傳商品資料。")
    try:
        value = json.loads(response_text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError("無法讀取 AI 供應商回傳的商品資料格式。") from exc
    if not isinstance(value, dict):
        raise ValueError("無法讀取 AI 供應商回傳的商品資料格式。")
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
        raise ValueError("AI 供應商無法辨識商品。請換一張更清楚的照片再試。")
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
    return message[:500] or "供應商請求失敗。"


def provider_failure_hint(message: str) -> str:
    """Turn common authentication errors into an actionable self-test result."""
    lowered = message.lower()
    if any(token in lowered for token in ("401", "403", "unauthorized", "api key", "api_key", "invalid key", "authentication")):
        return "供應商拒絕接受 API 金鑰。請到「設定」確認金鑰。"
    return f"無法連線至供應商。請檢查 API 金鑰、模型、用量額度或網路。詳細資訊：{message[:220]}"
