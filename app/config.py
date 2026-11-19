"""Small M1 configuration: Gemini credentials and selected camera."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.paths import config_path

DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"


@dataclass
class AppConfig:
    gemini_api_key: str = ""
    gemini_model: str = DEFAULT_GEMINI_MODEL
    camera_device_id: str = ""

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
        if not isinstance(gemini, dict):
            gemini = {}
        if not isinstance(camera, dict):
            camera = {}
        return cls(
            gemini_api_key=str(gemini.get("api_key", "")),
            gemini_model=str(gemini.get("model") or DEFAULT_GEMINI_MODEL),
            camera_device_id=str(camera.get("device_id", "")),
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
