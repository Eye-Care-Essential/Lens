from __future__ import annotations

import tempfile
import urllib.request
import webbrowser
from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtMultimedia import QCamera, QCameraDevice, QMediaCaptureSession, QMediaDevices, QVideoSink
from PySide6.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from app.ai.factory import create_provider
from app.ai.response import provider_failure_hint
from app.config import AppConfig
from app.detection.barcode import BarcodeReader
from app.paths import config_path
from app.workers import ConnectionTestWorker


class SystemChecksWorker(QThread):
    check_finished = Signal(str, bool, str)

    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.config = config

    def run(self) -> None:
        self._emit("config", *_check_config())
        self._emit("internet", *_check_internet())
        self._emit("browser", *_check_browser())
        self._emit("barcode", *_check_barcode(self.config.detection.barcode_enabled))

    def _emit(self, name: str, passed: bool, message: str) -> None:
        self.check_finished.emit(name, passed, message)


class SelfTestDialog(QDialog):
    """Runs local, network, camera, and active-provider checks without blocking the UI."""

    CHECK_NAMES = {
        "config": "Configuration file",
        "camera": "Camera preview",
        "internet": "Internet connection",
        "provider": "AI provider and API key",
        "browser": "Default browser",
        "barcode": "Barcode detector",
    }

    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self._camera: QCamera | None = None
        self._camera_session: QMediaCaptureSession | None = None
        self._camera_sink: QVideoSink | None = None
        self._camera_timer = QTimer(self)
        self._camera_timer.setSingleShot(True)
        self._camera_timer.timeout.connect(self._camera_timed_out)
        self._checks_worker: SystemChecksWorker | None = None
        self._provider_worker: ConnectionTestWorker | None = None
        self._pending_checks = 0
        self._results: dict[str, QLabel] = {}
        self.setWindowTitle("PriceLens Self-Test")
        self.setModal(True)
        self.resize(620, 400)

        layout = QVBoxLayout(self)
        intro = QLabel("Run these checks to diagnose camera, connection, and provider setup.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        grid = QGridLayout()
        for row, (key, name) in enumerate(self.CHECK_NAMES.items()):
            status = QLabel("○")
            status.setMinimumWidth(24)
            message = QLabel("Not run")
            message.setWordWrap(True)
            self._results[key] = message
            grid.addWidget(status, row, 0)
            grid.addWidget(QLabel(name), row, 1)
            grid.addWidget(message, row, 2)
            setattr(self, f"_{key}_led", status)
        layout.addLayout(grid)
        self.preview = QLabel("Camera check preview will appear here")
        self.preview.setMinimumHeight(90)
        self.preview.setMaximumHeight(130)
        self.preview.setStyleSheet("background: #171a20; color: #d6d8dc; border: 1px solid #454a54;")
        layout.addWidget(self.preview)
        controls = QHBoxLayout()
        self.run_button = QPushButton("Run all checks")
        self.close_button = QPushButton("Close")
        controls.addWidget(self.run_button)
        controls.addStretch(1)
        controls.addWidget(self.close_button)
        layout.addLayout(controls)
        self.run_button.clicked.connect(self.run_all_checks)
        self.close_button.clicked.connect(self.reject)

    def run_all_checks(self) -> None:
        if self._pending_checks:
            return
        for key in self.CHECK_NAMES:
            self._set_result(key, None, "Checking…")
        self.preview.clear()
        self.preview.setText("Waiting for a camera frame (3 seconds)…")
        self.run_button.setEnabled(False)
        self._pending_checks = 6
        self.close_button.setEnabled(False)
        self._start_camera_check()

        self._checks_worker = SystemChecksWorker(self.config, self)
        self._checks_worker.check_finished.connect(self._system_check_finished)
        self._checks_worker.finished.connect(self._release_system_worker)
        self._checks_worker.start()
        try:
            provider_config = self.config.providers[self.config.active_provider]
            if not provider_config.api_key.strip():
                self._finish_check("provider", False, "Add an API key for the selected provider in Settings.")
            else:
                provider = create_provider(self.config)
                self._provider_worker = ConnectionTestWorker(provider, self)
                self._provider_worker.completed.connect(self._provider_check_finished)
                self._provider_worker.finished.connect(self._release_provider_worker)
                self._provider_worker.start()
        except Exception as exc:
            self._finish_check("provider", False, _provider_hint(str(exc)))

    def _start_camera_check(self) -> None:
        devices = list(QMediaDevices.videoInputs())
        selected_id = self.config.camera_device_id
        device = next((item for item in devices if _device_id(item) == selected_id), None) if selected_id else (devices[0] if devices else None)
        if not devices:
            self._camera_finished(False, "No camera found. Connect a camera, then press Refresh in Settings.")
            return
        if selected_id and device is None:
            self._camera_finished(False, "The selected camera is unplugged or unavailable. Select a connected camera in Settings.")
            return
        if device is None:
            self._camera_finished(False, "No camera is selected. Choose a camera in Settings.")
            return
        self.preview.setText(f"Opening {device.description()}…")
        try:
            self._camera = QCamera(device, self)
            self._camera.errorOccurred.connect(self._camera_error)
            self._camera_session = QMediaCaptureSession(self)
            self._camera_sink = QVideoSink(self)
            self._camera_sink.videoFrameChanged.connect(self._camera_frame)
            self._camera_session.setVideoSink(self._camera_sink)
            self._camera_session.setCamera(self._camera)
            self._camera.start()
            self._camera_timer.start(3000)
        except Exception as exc:
            self._camera_finished(False, f"Selected camera could not be opened. {exc}")

    def _camera_frame(self, frame) -> None:
        image = frame.toImage()
        if image.isNull():
            return
        from PySide6.QtGui import QPixmap
        from PySide6.QtCore import Qt

        self.preview.setPixmap(QPixmap.fromImage(image).scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self._camera_finished(True, "Camera opened and delivered a frame.")

    def _camera_error(self, _error, message: str) -> None:
        self._camera_finished(False, f"Camera could not open. {message or 'Close other apps using the camera and retry.'}")

    def _camera_timed_out(self) -> None:
        self._camera_finished(False, "No camera frame arrived within 3 seconds. Close other apps using the camera and retry.")

    def _camera_finished(self, passed: bool, message: str) -> None:
        if self._camera_timer.isActive():
            self._camera_timer.stop()
        if self._camera is not None:
            self._camera.stop()
        self._finish_check("camera", passed, message)

    def _system_check_finished(self, key: str, passed: bool, message: str) -> None:
        self._finish_check(key, passed, message)

    def _provider_check_finished(self, passed: bool, message: str) -> None:
        self._finish_check("provider", passed, message if passed else _provider_hint(message))

    def _finish_check(self, key: str, passed: bool, message: str) -> None:
        current = self._results[key].text()
        if current != "Checking…":
            return
        self._set_result(key, passed, message)
        self._pending_checks -= 1
        if self._pending_checks <= 0:
            self.run_button.setEnabled(True)
            self.close_button.setEnabled(True)

    def _set_result(self, key: str, passed: bool | None, message: str) -> None:
        led = getattr(self, f"_{key}_led")
        led.setText("○" if passed is None else ("✓" if passed else "✗"))
        led.setStyleSheet("color: #18794e;" if passed else ("color: #b42318;" if passed is False else ""))
        self._results[key].setText(message)

    def _release_system_worker(self) -> None:
        worker = self._checks_worker
        self._checks_worker = None
        if worker is not None:
            worker.deleteLater()

    def _release_provider_worker(self) -> None:
        worker = self._provider_worker
        self._provider_worker = None
        if worker is not None:
            worker.deleteLater()

    def reject(self) -> None:
        if self._pending_checks:
            return
        self._camera_timer.stop()
        if self._camera is not None:
            self._camera.stop()
        super().reject()


def _device_id(device: QCameraDevice) -> str:
    return bytes(device.id()).decode("utf-8", errors="replace")


def _check_config() -> tuple[bool, str]:
    path = config_path()
    try:
        if path.exists():
            path.read_bytes()
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix="self-test-", delete=True) as probe:
            probe.write(b"ok")
            probe.flush()
            probe.seek(0)
            if probe.read() != b"ok":
                return False, "Config folder could not read back a temporary file. Check folder permissions."
        return True, "Config folder is readable and writable."
    except OSError as exc:
        return False, f"Config folder is not readable or writable: {exc}"


def _check_internet() -> tuple[bool, str]:
    try:
        request = urllib.request.Request("https://www.google.com/generate_204", method="GET")
        with urllib.request.urlopen(request, timeout=5):
            pass
        return True, "Internet connection is reachable."
    except Exception as exc:
        return False, f"Could not reach the internet. Check your connection or proxy settings. ({exc})"


def _check_browser() -> tuple[bool, str]:
    try:
        webbrowser.get()
        return True, "A default browser is available."
    except Exception:
        return False, "No default browser was found. Set a default browser in Windows settings."


def _check_barcode(enabled: bool) -> tuple[bool, str]:
    if not enabled:
        return True, "Barcode scanning is disabled in Settings."
    try:
        reader = BarcodeReader()
    except Exception as exc:
        return False, f"Barcode detector could not initialize: {exc}"
    if reader.available:
        return True, "OpenCV barcode detector initialized."
    return False, "Barcode detector is unavailable. Install the OpenCV contrib package or disable barcode scanning in Settings."


def _provider_hint(message: str) -> str:
    return provider_failure_hint(message)
