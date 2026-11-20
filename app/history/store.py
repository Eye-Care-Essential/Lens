from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.ai.base import ProductResult
from app.config import write_json_atomic
from app.paths import app_data_dir

_PRODUCT_FIELDS = ("name_zh", "name_en", "brand", "model", "category", "query_zh", "query_en", "msrp_estimate")


@dataclass
class HistoryEntry:
    id: str
    timestamp: str
    thumbnail: str
    name_zh: str
    name_en: str
    brand: str
    model: str
    category: str
    query_zh: str
    query_en: str
    msrp_estimate: str
    barcode: str
    provider: str
    status: str
    error: str = ""


class HistoryStore:
    def __init__(self, data_dir: str | Path | None = None) -> None:
        self.data_dir = Path(data_dir) if data_dir is not None else app_data_dir()
        self.history_path = self.data_dir / "history.json"
        self.thumbs_dir = self.data_dir / "thumbs"
        self.entries: list[HistoryEntry] = []
        self.load()

    def load(self) -> list[HistoryEntry]:
        try:
            raw = json.loads(self.history_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.entries = []
            return self.entries
        if not isinstance(raw, list):
            self.entries = []
            return self.entries
        loaded: list[HistoryEntry] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                loaded.append(HistoryEntry(**{key: value for key, value in item.items() if key in HistoryEntry.__dataclass_fields__}))
            except TypeError:
                continue
        self.entries = loaded
        return self.entries

    def add_success(
        self,
        product: ProductResult,
        thumbnail_bytes: bytes,
        barcode: str,
        provider: str,
        max_entries: int = 200,
    ) -> HistoryEntry:
        fields = {name: getattr(product, name) for name in _PRODUCT_FIELDS}
        return self._add(thumbnail_bytes, max_entries, barcode=barcode, provider=provider, status="success", **fields)

    def add_failure(
        self,
        error: str,
        thumbnail_bytes: bytes,
        barcode: str,
        provider: str,
        max_entries: int = 200,
    ) -> HistoryEntry:
        return self._add(
            thumbnail_bytes, max_entries, name_zh="Identification failed",
            barcode=barcode, provider=provider, status="failed", error=error,
        )

    def _add(self, thumbnail_bytes: bytes, max_entries: int, **fields: str) -> HistoryEntry:
        self.thumbs_dir.mkdir(parents=True, exist_ok=True)
        thumb_name = f"{uuid.uuid4().hex}.jpg"
        (self.thumbs_dir / thumb_name).write_bytes(thumbnail_bytes)
        entry = HistoryEntry(
            id=uuid.uuid4().hex,
            timestamp=_timestamp(),
            thumbnail=thumb_name,
            **{**dict.fromkeys(_PRODUCT_FIELDS, ""), **fields},
        )
        self.entries.insert(0, entry)
        self._write()
        self.trim(max_entries)
        return entry

    def delete(self, entry_id: str) -> bool:
        entry = next((item for item in self.entries if item.id == entry_id), None)
        if entry is None:
            return False
        self.entries = [item for item in self.entries if item.id != entry_id]
        self._delete_thumbnail(entry.thumbnail)
        self._write()
        return True

    def trim(self, max_entries: int) -> None:
        limit = max(1, int(max_entries))
        removed = self.entries[limit:]
        if not removed:
            return
        self.entries = self.entries[:limit]
        for item in removed:
            self._delete_thumbnail(item.thumbnail)
        self._write()

    def thumbnail_path(self, entry: HistoryEntry) -> Path | None:
        if not entry.thumbnail:
            return None
        path = self.thumbs_dir / entry.thumbnail
        return path if path.exists() else None

    def _write(self) -> None:
        write_json_atomic(self.history_path, [asdict(entry) for entry in self.entries])

    def _delete_thumbnail(self, filename: str) -> None:
        if not filename:
            return
        try:
            (self.thumbs_dir / filename).unlink(missing_ok=True)
        except OSError:
            pass


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
