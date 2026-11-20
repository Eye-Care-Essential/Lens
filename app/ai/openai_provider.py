from __future__ import annotations

import base64

from openai import OpenAI

from app.ai.base import ProductResult
from app.ai.prompt import IDENTIFICATION_PROMPT
from app.ai.response import extract_json, product_result, safe_error


class OpenAICompatibleProvider:
    """OpenAI API or a compatible endpoint when base_url is provided."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "",
        timeout_sec: int = 30,
        compatible: bool = False,
    ) -> None:
        self._api_key = api_key.strip()
        self._model = model.strip()
        self._base_url = base_url.strip()
        self._timeout_sec = timeout_sec
        self._compatible = compatible
        if not self._api_key:
            raise ValueError("Add an OpenAI API key in Settings.")
        if compatible and not self._base_url:
            raise ValueError("Enter the compatible API base URL in Settings.")

    def _client(self) -> OpenAI:
        return OpenAI(
            api_key=self._api_key,
            base_url=self._base_url or None,
            timeout=self._timeout_sec,
        )

    def identify(self, jpeg_bytes: bytes, barcode: str | None = None) -> ProductResult:
        prompt = IDENTIFICATION_PROMPT
        if barcode:
            prompt += f"\nA barcode was decoded as {barcode!r}; use it only as an identification hint."
        image_url = "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode("ascii")
        kwargs = {
            "model": self._model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url, "detail": "high"}},
                ],
            }],
            "response_format": {"type": "json_object"},
        }
        kwargs["max_tokens" if self._compatible else "max_completion_tokens"] = 1200
        response = self._client().chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""
        return product_result(extract_json(content))

    def test_connection(self) -> tuple[bool, str]:
        try:
            response = self._client().chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": "Reply with exactly: OK"}],
                **({"max_tokens": 16} if self._compatible else {"max_completion_tokens": 16}),
            )
            text = response.choices[0].message.content or ""
            return True, text.strip() or "Connection succeeded."
        except Exception as exc:
            return False, safe_error(exc, self._api_key)
