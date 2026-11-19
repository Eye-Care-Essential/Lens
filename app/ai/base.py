from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ProductResult:
    name_zh: str
    name_en: str
    brand: str
    model: str
    category: str
    query_zh: str
    query_en: str
    msrp_estimate: str
    raw: dict


class VisionProvider(Protocol):
    def identify(self, jpeg_bytes: bytes, barcode: str | None = None) -> ProductResult: ...
