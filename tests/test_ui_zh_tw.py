import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENGLISH_UI_WORDS = re.compile(
    r"\b(?:settings?|camera|start|stop(?:ped)?|refresh|fail(?:ed|ure)?|ready|close|"
    r"save[ds]?|cancel|history|resolution|identify|identifying|identification|"
    r"connection|default|search|browser|barcode|provider|general|detec(?:t|tion))\b",
    re.IGNORECASE,
)
ALLOWED_LITERALS = {
    "app/ui/selftest_dialog.py": {"camera", "provider", "browser", "barcode"},  # check IDs
    "app/ui/settings_dialog.py": {"Invalid search URL template"},  # caught validation error
}


def test_ui_string_literals_do_not_use_common_english_labels():
    sources = sorted((ROOT / "app/ui").rglob("*.py"))
    sources.append(ROOT / "app/camera/camera_view.py")
    violations = []
    for path in sources:
        name = path.relative_to(ROOT).as_posix()
        syntax = ast.parse(path.read_text(encoding="utf-8"), filename=name)
        docstrings = {
            node.body[0].value
            for node in ast.walk(syntax)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and ast.get_docstring(node) is not None
        }
        for node in ast.walk(syntax):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if node in docstrings or node.value in ALLOWED_LITERALS.get(name, ()):
                continue
            if ENGLISH_UI_WORDS.search(node.value):
                violations.append(f"{name}:{node.lineno}: {node.value!r}")

    assert not violations, "English UI literals found:\n" + "\n".join(violations)


def test_localized_buttons_fit_the_default_layouts(monkeypatch, tmp_path):
    from types import SimpleNamespace

    import pytest

    widgets = pytest.importorskip("PySide6.QtWidgets")
    pytest.importorskip("cv2")

    from app.config import AppConfig
    from app.history.store import HistoryStore
    from app.ui import main_window, settings_dialog
    from app.ui.selftest_dialog import SelfTestDialog

    empty_devices = SimpleNamespace(videoInputs=lambda: [])
    monkeypatch.setattr(main_window, "QMediaDevices", empty_devices)
    monkeypatch.setattr(settings_dialog, "QMediaDevices", empty_devices)
    monkeypatch.setattr(main_window, "HistoryStore", lambda: HistoryStore(tmp_path))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = widgets.QApplication.instance() or widgets.QApplication([])
    config = AppConfig()
    main = main_window.MainWindow(config)
    settings = settings_dialog.SettingsDialog(config)
    self_test = SelfTestDialog(config)

    def check_buttons(window):
        app.processEvents()
        for button in window.findChildren(widgets.QPushButton):
            if button.isVisible():
                assert button.width() >= button.sizeHint().width(), button.text()

    try:
        main.show()
        check_buttons(main)
        assert main.windowTitle() == "PriceLens"
        settings.show()
        for index in range(settings.tabs.count()):
            settings.tabs.setCurrentIndex(index)
            check_buttons(settings)
        self_test.show()
        check_buttons(self_test)
    finally:
        self_test.close()
        settings.close()
        main.close()
