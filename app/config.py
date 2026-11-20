"""Portable application settings and migration from the original M1 config."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.paths import config_path

PROVIDER_IDS = ("claude", "gemini", "openai", "custom")
DEFAULT_MODELS = {
    "claude": "claude-sonnet-5",
    "gemini": "gemini-3.8-flash",
    "openai": "gpt-6.1-terra",
    "custom": "gpt-6.1-terra",
}

DEFAULT_SEARCH_SITES = (
    ("google_shopping", "Google Shopping", True, "https://www.google.com/search?tbm=shop&q={q}", "en"),
    ("biggo", "BigGo", True, "https://biggo.com.tw/s/?q={q}", "zh"),
    ("feebee", "feebee 飛比", True, "https://feebee.com.tw/s/?q={q}", "zh"),
    ("momo", "momo", True, "https://www.momoshop.com.tw/search/searchShop.jsp?keyword={q}", "zh"),
    ("pchome", "PChome 24h", True, "https://24h.pchome.com.tw/search/?q={q}", "zh"),
    ("shopee", "Shopee 蝦皮", True, "https://shopee.tw/search?keyword={q}", "zh"),
    ("ruten", "Ruten 露天", True, "https://www.ruten.com.tw/find/?q={q}", "zh"),
)


@dataclass
class ProviderConfig:
    api_key: str = ""
    model: str = ""
    base_url: str = ""


@dataclass
class DetectionConfig:
    auto_enabled: bool = False
    motion_threshold: float = 0.02
    stable_ms: int = 1000
    cooldown_ms: int = 3000
    dedupe_hamming: int = 6
    barcode_enabled: bool = True


@dataclass
class SearchSiteConfig:
    id: str
    name: str
    enabled: bool
    url_template: str
    query_field: str


@dataclass
class SearchConfig:
    secondhand_mode: bool = False
    sites: list[SearchSiteConfig] = field(default_factory=lambda: [
        SearchSiteConfig(*site) for site in DEFAULT_SEARCH_SITES
    ])


@dataclass
class GeneralConfig:
    max_history: int = 200
    open_tabs_delay_ms: int = 150


def _default_providers() -> dict[str, ProviderConfig]:
    return {name: ProviderConfig(model=DEFAULT_MODELS[name]) for name in PROVIDER_IDS}


@dataclass
class AppConfig:
    active_provider: str = "gemini"
    providers: dict[str, ProviderConfig] = field(default_factory=_default_providers)
    ai_timeout_sec: int = 30
    camera_device_id: str = ""
    camera_resolution: str = "1280x720"
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    general: GeneralConfig = field(default_factory=GeneralConfig)

    @classmethod
    def load(cls) -> "AppConfig":
        path = config_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        ai = data.get("ai", {})
        if not isinstance(ai, dict):
            ai = {}
        providers = _default_providers()
        for provider_id in PROVIDER_IDS:
            candidate = ai.get(provider_id, {})
            if isinstance(candidate, dict):
                providers[provider_id] = ProviderConfig(
                    api_key=str(candidate.get("api_key", "")),
                    model=str(candidate.get("model") or DEFAULT_MODELS[provider_id]),
                    base_url=str(candidate.get("base_url", "")),
                )

        camera = data.get("camera", {})
        detection = data.get("detection", {})
        search = data.get("search", {})
        general = data.get("general", {})
        camera = camera if isinstance(camera, dict) else {}
        detection = detection if isinstance(detection, dict) else {}
        search = search if isinstance(search, dict) else {}
        general = general if isinstance(general, dict) else {}

        search_sites = _load_sites(search.get("sites"))
        provider_id = str(ai.get("provider", "gemini")).lower()
        if provider_id not in PROVIDER_IDS:
            provider_id = "gemini"

        return cls(
            active_provider=provider_id,
            providers=providers,
            ai_timeout_sec=_bounded_int(ai.get("timeout_sec", 30), 1, 300, 30),
            camera_device_id=str(camera.get("device_id", "")),
            camera_resolution=str(camera.get("resolution", "1280x720")),
            detection=DetectionConfig(
                auto_enabled=bool(detection.get("auto_enabled", False)),
                motion_threshold=_bounded_float(detection.get("motion_threshold", 0.02), 0.001, 1.0, 0.02),
                stable_ms=_bounded_int(detection.get("stable_ms", 1000), 100, 30000, 1000),
                cooldown_ms=_bounded_int(detection.get("cooldown_ms", 3000), 0, 60000, 3000),
                dedupe_hamming=_bounded_int(detection.get("dedupe_hamming", 6), 0, 64, 6),
                barcode_enabled=bool(detection.get("barcode_enabled", True)),
            ),
            search=SearchConfig(
                secondhand_mode=bool(search.get("secondhand_mode", False)),
                sites=search_sites,
            ),
            general=GeneralConfig(
                max_history=_bounded_int(general.get("max_history", 200), 1, 10000, 200),
                open_tabs_delay_ms=_bounded_int(general.get("open_tabs_delay_ms", 150), 0, 5000, 150),
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ai": {
                "provider": self.active_provider,
                **{provider_id: asdict(self.providers[provider_id]) for provider_id in PROVIDER_IDS},
                "timeout_sec": self.ai_timeout_sec,
            },
            "camera": {"device_id": self.camera_device_id, "resolution": self.camera_resolution},
            "detection": asdict(self.detection),
            "search": {
                "secondhand_mode": self.search.secondhand_mode,
                "sites": [asdict(site) for site in self.search.sites],
            },
            "general": asdict(self.general),
        }

    def save(self) -> Path:
        """config_path() already falls back to APPDATA when the app folder is read-only."""
        path = config_path()
        write_json_atomic(path, self.to_dict())
        return path

    @classmethod
    def import_from(cls, path: str | Path) -> "AppConfig":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Config file must contain a JSON object.")
        return cls.from_dict(data)

    def export_to(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_json_atomic(path: Path, payload: Any) -> None:
    """Write to a temp file, then swap it in, so a crash never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f"{path.stem}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        Path(temp_name).replace(path)
    except Exception:
        try:
            Path(temp_name).unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _load_sites(values: object) -> list[SearchSiteConfig]:
    defaults = {site[0]: SearchSiteConfig(*site) for site in DEFAULT_SEARCH_SITES}
    if not isinstance(values, list):
        return list(defaults.values())
    sites: list[SearchSiteConfig] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        site_id = str(value.get("id", ""))
        if not site_id:
            continue
        default = defaults.get(site_id)
        if default is None:
            continue
        query_field = str(value.get("query_field", default.query_field)).lower()
        sites.append(SearchSiteConfig(
            id=site_id,
            name=str(value.get("name", default.name)),
            enabled=bool(value.get("enabled", default.enabled)),
            url_template=str(value.get("url_template", default.url_template)),
            query_field=query_field if query_field in {"zh", "en"} else default.query_field,
        ))
    return sites or list(defaults.values())


def _bounded_int(value: object, minimum: int, maximum: int, default: int) -> int:
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return default


def _bounded_float(value: object, minimum: float, maximum: float, default: float) -> float:
    try:
        return max(minimum, min(maximum, float(value)))
    except (TypeError, ValueError):
        return default
