"""Paths used by the source build and the future portable Windows build."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _config_candidates() -> tuple[Path, Path]:
    if getattr(sys, "frozen", False):
        app_dir = Path(sys.executable).resolve().parent
    else:
        app_dir = Path(__file__).resolve().parents[1]

    app_data = os.environ.get("APPDATA")
    fallback_dir = Path(app_data) / "PriceLens" if app_data else Path.home() / ".config" / "PriceLens"
    return app_dir / "config.json", fallback_dir / "config.json"


def config_path() -> Path:
    """Return a writable config location, preferring the app directory."""
    primary, fallback = _config_candidates()
    for candidate in (primary, fallback):
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            probe = candidate.parent / ".pricelens-write-check"
            probe.write_text("", encoding="utf-8")
            probe.unlink()
            return candidate
        except OSError:
            continue
    return fallback


def app_data_dir() -> Path:
    """Keep local history beside the config (or in APPDATA when portable dir is read-only)."""
    return config_path().parent
