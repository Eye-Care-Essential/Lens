"""Local app settings for the MVP and automatic detection."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from app.paths import config_path

DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"


@dataclass
class DetectionConfig:
    auto_enabled: bool = False
    motion_threshold: float = 0.02
    stable_ms: int = 1000
    cooldown_ms: int = 3000
    dedupe_hamming: int = 6
    barcode_enabled: bool = True


@dataclass
class AppConfig:
    gemini_api_key: str = ""
    gemini_model: str = DEFAULT_GEMINI_MODEL
    camera_device_id: str = ""
    detection: DetectionConfig = field(default_factory=DetectionConfig)

    @classmethod
    def load(cls) -> "AppConfig":
        path = config_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()

        ai = data.get("ai", {}) if isinstance(data, dict) else {}
        gemini = ai.get("gemini", {}) if isinstance(ai, dict) else {}
        camera = data.get("camera", {}) if isinstance(data, dict) else {}
        detection = data.get("detection", {}) if isinstance(data, dict) else {}
        if not isinstance(gemini, dict):
            gemini = {}
        if not isinstance(camera, dict):
            camera = {}
        if not isinstance(detection, dict):
            detection = {}
        return cls(
            gemini_api_key=str(gemini.get("api_key", "")),
            gemini_model=str(gemini.get("model") or DEFAULT_GEMINI_MODEL),
            camera_device_id=str(camera.get("device_id", "")),
            detection=DetectionConfig(
                auto_enabled=bool(detection.get("auto_enabled", False)),
                motion_threshold=_bounded_float(detection.get("motion_threshold", 0.02), 0.001, 1.0, 0.02),
                stable_ms=_bounded_int(detection.get("stable_ms", 1000), 100, 30000, 1000),
                cooldown_ms=_bounded_int(detection.get("cooldown_ms", 3000), 0, 60000, 3000),
                dedupe_hamming=_bounded_int(detection.get("dedupe_hamming", 6), 0, 64, 6),
                barcode_enabled=bool(detection.get("barcode_enabled", True)),
            ),
        )

    def save(self) -> Path:
        """Write atomically; if the app folder is read-only, use the fallback path."""
        path = config_path()
        payload = {
            "ai": {
                "provider": "gemini",
                "gemini": {"api_key": self.gemini_api_key, "model": self.gemini_model},
                "timeout_sec": 30,
            },
            "camera": {"device_id": self.camera_device_id},
            "detection": {
                "auto_enabled": self.detection.auto_enabled,
                "motion_threshold": self.detection.motion_threshold,
                "stable_ms": self.detection.stable_ms,
                "cooldown_ms": self.detection.cooldown_ms,
                "dedupe_hamming": self.detection.dedupe_hamming,
                "barcode_enabled": self.detection.barcode_enabled,
            },
        }
        try:
            self._write(path, payload)
            return path
        except OSError:
            _, fallback = self._candidate_paths()
            self._write(fallback, payload)
            return fallback

    @staticmethod
    def _candidate_paths() -> tuple[Path, Path]:
        from app.paths import _config_candidates

        return _config_candidates()

    @staticmethod
    def _write(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix="config-", suffix=".tmp", dir=path.parent)
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
