from __future__ import annotations

import json

from google import genai
from google.genai import types

from app.ai.base import ProductResult
from app.ai.prompt import IDENTIFICATION_PROMPT


class GeminiProvider:
    def __init__(self, api_key: str, model: str, timeout_sec: int = 30) -> None:
        if not api_key.strip():
            raise ValueError("Add a Gemini API key in Gemini settings first.")
        self._api_key = api_key.strip()
        self._model = model.strip()
        self._timeout_sec = timeout_sec

    def identify(self, jpeg_bytes: bytes, barcode: str | None = None) -> ProductResult:
        prompt = IDENTIFICATION_PROMPT
        if barcode:
            prompt += f"\nA barcode was decoded as {barcode!r}; use it only as an identification hint."

        client = genai.Client(
            api_key=self._api_key,
            http_options=types.HttpOptions(timeout=self._timeout_sec * 1000),
        )
        response = client.models.generate_content(
            model=self._model,
            contents=[prompt, types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg")],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )
        response_text = response.text or ""
        raw = _extract_json(response_text)
        return _to_product_result(raw)


def _extract_json(response_text: str) -> dict:
    """Accept either a bare JSON object or a JSON object surrounded by prose/fences."""
    start = response_text.find("{")
    end = response_text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Gemini returned no product details. Try identifying the item again.")
    try:
        value = json.loads(response_text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError("Gemini returned product details in an unreadable format.") from exc
    if not isinstance(value, dict):
        raise ValueError("Gemini returned product details in an unreadable format.")
    return value


def _to_product_result(raw: dict) -> ProductResult:
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
        raise ValueError("Gemini could not identify the item. Try a clearer photo.")
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
