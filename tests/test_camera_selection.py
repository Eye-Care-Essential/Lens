from dataclasses import dataclass
from types import SimpleNamespace

import pytest


@dataclass
class FakeDevice:
    name: str
    identifier: str
    facing: object

    def description(self):
        return self.name

    def id(self):
        return self.identifier.encode("utf-8")

    def position(self):
        return self.facing


@pytest.fixture
def multimedia():
    return pytest.importorskip("PySide6.QtMultimedia")


@pytest.fixture
def qt_app(monkeypatch):
    widgets = pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return widgets.QApplication.instance() or widgets.QApplication([])


@pytest.mark.parametrize(
    ("position", "expected"),
    [
        ("FrontFace", "Integrated webcam (Built-in)"),
        ("BackFace", "Integrated webcam (Built-in)"),
        ("UnspecifiedPosition", "Integrated webcam"),
    ],
)
def test_camera_label_uses_reported_position(multimedia, position, expected):
    from app.camera.camera_view import camera_label

    facing = getattr(multimedia.QCameraDevice.Position, position)
    assert camera_label(FakeDevice("Integrated webcam", "cam", facing)) == expected


@pytest.mark.parametrize(
    ("device_ids", "preferred", "default", "expected"),
    [
        (["built-in", "usb"], "usb", "built-in", (1, False)),
        (["usb", "built-in"], "unplugged", "built-in", (1, True)),
        (["built-in", "usb"], "unplugged", "missing-default", (0, True)),
        ([], "usb", "built-in", (-1, False)),
        (["usb", "built-in"], "", "built-in", (1, False)),
    ],
)
def test_choose_camera_index(multimedia, device_ids, preferred, default, expected):
    from app.camera.camera_view import choose_camera_index

    assert choose_camera_index(device_ids, preferred, default) == expected


def test_main_window_preserves_missing_camera_and_resumes_it_after_refresh(
    multimedia, qt_app, monkeypatch, tmp_path
):
    pytest.importorskip("cv2")
    from app.config import AppConfig
    from app.history.store import HistoryStore
    from app.ui import main_window

    position = multimedia.QCameraDevice.Position
    other_usb = FakeDevice("Backup USB webcam", "backup", position.UnspecifiedPosition)
    built_in = FakeDevice("Notebook webcam", "built-in", position.FrontFace)
    preferred_usb = FakeDevice("Preferred USB webcam", "preferred", position.UnspecifiedPosition)
    devices = [other_usb, built_in]
    previews = []
    saves = []
    monkeypatch.setattr(
        main_window, "QMediaDevices",
        SimpleNamespace(videoInputs=lambda: devices, defaultVideoInput=lambda: built_in),
    )
    monkeypatch.setattr(main_window, "QCameraDevice", FakeDevice)
    monkeypatch.setattr(main_window, "HistoryStore", lambda: HistoryStore(tmp_path))
    monkeypatch.setattr(
        main_window.CameraView, "set_device", lambda view, device, resolution="": previews.append(device)
    )
    monkeypatch.setattr(AppConfig, "save", lambda config: saves.append(config.camera_device_id))

    config = AppConfig(camera_device_id="preferred")
    window = main_window.MainWindow(config)
    try:
        assert window.camera_combo.count() == 2
        assert window.camera_combo.currentText() == "Notebook webcam (Built-in)"
        assert previews[-1] is built_in
        assert "已切換至 Notebook webcam (Built-in)" in window.statusBar().currentMessage()
        assert config.camera_device_id == "preferred"
        assert saves == []

        devices.append(preferred_usb)
        window.refresh_button.click()
        assert window.camera_combo.currentText() == "Preferred USB webcam"
        assert previews[-1] is preferred_usb
        assert config.camera_device_id == "preferred"

        window.next_camera_button.click()
        assert previews[-1] is other_usb
        assert saves[-1] == config.camera_device_id == "backup"

        assert window.next_camera_shortcut.key().toString() == "C"
        window.next_camera_shortcut.activated.emit()
        assert previews[-1] is built_in
        assert saves[-1] == config.camera_device_id == "built-in"

        window.camera_combo.setCurrentIndex(2)
        window.camera_combo.activated.emit(2)
        assert previews[-1] is preferred_usb
        assert saves[-1] == config.camera_device_id == "preferred"
    finally:
        window.close()


@pytest.mark.parametrize("failure", ["missing", "error", "timeout"])
def test_self_test_camera_failures_show_privacy_hint(qt_app, monkeypatch, failure):
    pytest.importorskip("cv2")
    from app.config import AppConfig
    from app.ui import selftest_dialog

    monkeypatch.setattr(selftest_dialog, "QMediaDevices", SimpleNamespace(videoInputs=lambda: []))
    dialog = selftest_dialog.SelfTestDialog(AppConfig())
    dialog._pending_checks = 1
    dialog._set_result("camera", None, selftest_dialog._CHECKING)
    try:
        if failure == "missing":
            dialog._start_camera_check()
        elif failure == "error":
            dialog._camera_error(None, "Access denied")
        else:
            dialog._camera_timed_out()
        message = dialog._results["camera"].text()
        assert "隱私權與安全性 → 相機" in message
        assert "讓傳統型應用程式存取您的相機" in message
        assert "相機隱私遮罩" in message
        assert "相機鍵" in message
        if failure == "error":
            assert "Access denied" in message
    finally:
        dialog.close()
