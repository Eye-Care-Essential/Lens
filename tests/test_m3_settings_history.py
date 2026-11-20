import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

from app.ai.base import ProductResult
from app.ai.factory import create_provider
from app.ai.response import provider_failure_hint
from app.config import AppConfig
from app.history.store import HistoryStore


def test_config_round_trip_all_m3_settings():
    config = AppConfig()
    config.active_provider = "custom"
    config.providers["custom"].api_key = "secret"
    config.providers["custom"].model = "vision-model"
    config.providers["custom"].base_url = "https://example.test/v1"
    config.ai_timeout_sec = 80
    config.camera_device_id = "camera-1"
    config.camera_resolution = "1920x1080"
    config.search.secondhand_mode = True
    config.search.sites[0].enabled = False
    config.search.sites[0].url_template = "https://shop.test/?q={q}"
    config.detection.stable_ms = 1400
    config.general.max_history = 42
    config.general.open_tabs_delay_ms = 200

    loaded = AppConfig.from_dict(json.loads(json.dumps(config.to_dict())))

    assert loaded.active_provider == "custom"
    assert loaded.providers["custom"].api_key == "secret"
    assert loaded.providers["custom"].base_url == "https://example.test/v1"
    assert loaded.camera_resolution == "1920x1080"
    assert loaded.search.secondhand_mode is True
    assert loaded.search.sites[0].enabled is False
    assert loaded.search.sites[0].url_template == "https://shop.test/?q={q}"
    assert loaded.detection.stable_ms == 1400
    assert loaded.general.max_history == 42
    assert loaded.general.open_tabs_delay_ms == 200


def test_m1_gemini_config_migrates():
    loaded = AppConfig.from_dict({
        "ai": {"gemini": {"api_key": "old-key", "model": "old-model"}},
        "camera": {"device_id": "old-camera"},
    })

    assert loaded.active_provider == "gemini"
    assert loaded.providers["gemini"].api_key == "old-key"
    assert loaded.providers["gemini"].model == "old-model"
    assert loaded.camera_device_id == "old-camera"


def test_provider_factory_uses_current_selection_without_restart():
    class DummyProvider:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    modules = {}
    for module_name, provider_name in (
        ("app.ai.gemini_provider", "GeminiProvider"),
        ("app.ai.anthropic_provider", "ClaudeProvider"),
        ("app.ai.openai_provider", "OpenAICompatibleProvider"),
    ):
        module = types.ModuleType(module_name)
        setattr(module, provider_name, DummyProvider)
        modules[module_name] = module
    config = AppConfig()
    config.providers["custom"].api_key = "key"
    config.providers["custom"].base_url = "https://custom.test/v1"
    config.active_provider = "custom"

    with patch.dict(sys.modules, modules):
        provider = create_provider(config)

    assert provider.kwargs["base_url"] == "https://custom.test/v1"
    assert provider.kwargs["compatible"] is True


def test_history_persists_entries_and_deletes_thumbnail(tmp_path: Path):
    product = ProductResult("相機", "Camera", "Brand", "Model", "camera", "品牌 相機", "Brand Camera", "NT$ 100", {})
    store = HistoryStore(tmp_path)
    entry = store.add_success(product, b"fake-jpeg", "12345", "gemini", max_entries=2)
    thumb = store.thumbnail_path(entry)

    loaded = HistoryStore(tmp_path)
    assert loaded.entries[0].query_zh == "品牌 相機"
    assert loaded.entries[0].barcode == "12345"
    assert thumb is not None and thumb.exists()
    assert loaded.delete(entry.id) is True
    assert not thumb.exists()


def test_provider_self_test_marks_authentication_errors():
    result = provider_failure_hint("HTTP 401 Unauthorized: invalid api_key")
    assert "拒絕接受 API 金鑰" in result


def test_history_failure_entry_and_trim_removes_oldest_thumbnail(tmp_path: Path):
    product = ProductResult("相機", "Camera", "Brand", "Model", "camera", "品牌 相機", "Brand Camera", "", {})
    store = HistoryStore(tmp_path)
    failed = store.add_failure("timeout", b"a", "", "claude", max_entries=1)
    old_thumb = store.thumbnail_path(failed)
    assert failed.status == "failed" and failed.name_zh == "辨識失敗" and failed.query_zh == ""

    store.add_success(product, b"b", "", "gemini", max_entries=1)

    loaded = HistoryStore(tmp_path)
    assert [entry.status for entry in loaded.entries] == ["success"]
    assert loaded.entries[0].name_en == "Camera"
    assert old_thumb is not None and not old_thumb.exists()
