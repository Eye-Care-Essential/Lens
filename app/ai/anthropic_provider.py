from __future__ import annotations

import base64

import anthropic

from app.ai.base import ProductResult
from app.ai.prompt import IDENTIFICATION_PROMPT
from app.ai.response import extract_json, product_result, safe_error


class ClaudeProvider:
    def __init__(self, api_key: str, model: str, timeout_sec: int = 30) -> None:
        self._api_key = api_key.strip()
        self._model = model.strip()
        self._timeout_sec = timeout_sec
        if not self._api_key:
            raise ValueError("Add an Anthropic API key in Settings.")

    def identify(self, jpeg_bytes: bytes, barcode: str | None = None) -> ProductResult:
        prompt = IDENTIFICATION_PROMPT
        if barcode:
            prompt += f"\nA barcode was decoded as {barcode!r}; use it only as an identification hint."
        client = anthropic.Anthropic(api_key=self._api_key, timeout=self._timeout_sec)
        response = client.messages.create(
            model=self._model,
            max_tokens=1200,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": base64.b64encode(jpeg_bytes).decode("ascii"),
                        },
                    },
                ],
            }],
        )
        response_text = "\n".join(block.text for block in response.content if getattr(block, "type", "") == "text")
        return product_result(extract_json(response_text))

    def test_connection(self) -> tuple[bool, str]:
        try:
            client = anthropic.Anthropic(api_key=self._api_key, timeout=self._timeout_sec)
            response = client.messages.create(
                model=self._model,
                max_tokens=16,
                messages=[{"role": "user", "content": "Reply with exactly: OK"}],
            )
            text = " ".join(block.text for block in response.content if getattr(block, "type", "") == "text")
            return True, text.strip() or "Connection succeeded."
        except Exception as exc:
            return False, safe_error(exc, self._api_key)
