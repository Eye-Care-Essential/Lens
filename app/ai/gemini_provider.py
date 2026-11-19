from __future__ import annotations

from google import genai
from google.genai import types

from app.ai.base import ProductResult
from app.ai.prompt import IDENTIFICATION_PROMPT
from app.ai.response import extract_json, product_result, safe_error


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
        return product_result(extract_json(response_text))

    def test_connection(self) -> tuple[bool, str]:
        try:
            client = genai.Client(
                api_key=self._api_key,
                http_options=types.HttpOptions(timeout=self._timeout_sec * 1000),
            )
            response = client.models.generate_content(
                model=self._model,
                contents="Reply with exactly: OK",
                config=types.GenerateContentConfig(max_output_tokens=16, temperature=0),
            )
            return True, (response.text or "Connection succeeded.").strip()
        except Exception as exc:
            return False, safe_error(exc, self._api_key)
