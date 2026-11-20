from __future__ import annotations

import tempfile
import urllib.request
import webbrowser

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtMultimedia import QCamera, QMediaCaptureSession, QMediaDevices, QVideoSink
from PySide6.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from app.ai.factory import create_provider
from app.camera.camera_view import device_id
from app.ai.response import provider_failure_hint
from app.config import AppConfig
from app.detection.barcode import BarcodeReader
from app.paths import config_path
from app.workers import ConnectionTestWorker


_CHECKING = "檢查中…"
_CAMERA_PRIVACY_HINT = (
    "請在 Windows 的「設定 → 隱私權與安全性 → 相機」開啟"
    "「讓傳統型應用程式存取您的相機」，並確認筆電的相機隱私遮罩已打開、"
    "相機未被相機鍵停用。"
)


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
        "config": "設定檔",
        "camera": "相機預覽",
        "internet": "網路連線",
        "provider": "AI 供應商與 API 金鑰",
        "browser": "預設瀏覽器",
        "barcode": "條碼偵測",
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
        self.setWindowTitle("PriceLens 自我檢查")
        self.setModal(True)
        self.resize(620, 400)

        layout = QVBoxLayout(self)
        intro = QLabel("檢查相機、網路連線、AI 供應商與其他設定。")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        grid = QGridLayout()
        for row, (key, name) in enumerate(self.CHECK_NAMES.items()):
            status = QLabel("○")
            status.setMinimumWidth(24)
            message = QLabel("尚未檢查")
            message.setWordWrap(True)
            message.setTextFormat(Qt.TextFormat.PlainText)
            self._results[key] = message
            grid.addWidget(status, row, 0)
            grid.addWidget(QLabel(name), row, 1)
            grid.addWidget(message, row, 2)
            setattr(self, f"_{key}_led", status)
        grid.setColumnStretch(2, 1)
        layout.addLayout(grid)
        self.preview = QLabel("相機檢查的預覽畫面將顯示於此")
        self.preview.setWordWrap(True)
        self.preview.setMinimumHeight(90)
        self.preview.setMaximumHeight(130)
        self.preview.setStyleSheet("background: #171a20; color: #d6d8dc; border: 1px solid #454a54;")
        layout.addWidget(self.preview)
        controls = QHBoxLayout()
        self.run_button = QPushButton("執行所有檢查")
        self.close_button = QPushButton("關閉")
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
            self._set_result(key, None, _CHECKING)
        self.preview.clear()
        self.preview.setText("正在等候相機畫面（最多 3 秒）…")
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
                self._finish_check("provider", False, "請在「設定」中輸入所選供應商的 API 金鑰。")
            elif self.config.active_provider == "custom" and not provider_config.base_url.strip():
                self._finish_check("provider", False, "請在「設定」中輸入自訂供應商的基礎網址。")
            else:
                provider = create_provider(self.config)
                self._provider_worker = ConnectionTestWorker(provider, self)
                self._provider_worker.completed.connect(self._provider_check_finished)
                self._provider_worker.finished.connect(self._release_provider_worker)
                self._provider_worker.start()
        except Exception as exc:
            self._finish_check("provider", False, provider_failure_hint(str(exc)))

    def _start_camera_check(self) -> None:
        devices = list(QMediaDevices.videoInputs())
        selected_id = self.config.camera_device_id
        device = next((item for item in devices if device_id(item) == selected_id), None) if selected_id else (devices[0] if devices else None)
        if not devices:
            self._camera_finished(False, "找不到相機。請連接相機，再到「設定」按「重新整理裝置」。")
            return
        if selected_id and device is None:
            self._camera_finished(False, "所選相機未連接或無法使用。請在「設定」選擇已連接的相機。")
            return
        if device is None:
            self._camera_finished(False, "尚未選擇相機。請到「設定」選擇相機。")
            return
        self.preview.setText(f"正在開啟 {device.description()}…")
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
            self._camera_finished(False, f"無法開啟所選的相機：{exc}")

    def _camera_frame(self, frame) -> None:
        image = frame.toImage()
        if image.isNull():
            return
        from PySide6.QtGui import QPixmap

        self.preview.setPixmap(QPixmap.fromImage(image).scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self._camera_finished(True, "已開啟相機並收到畫面。")

    def _camera_error(self, _error, message: str) -> None:
        hint = "無法開啟相機。請關閉其他正在使用相機的應用程式，再試一次。"
        self._camera_finished(False, f"{hint} 詳細資訊：{message}" if message else hint)

    def _camera_timed_out(self) -> None:
        self._camera_finished(False, "等候 3 秒後仍未收到相機畫面。請關閉其他正在使用相機的應用程式，再試一次。")

    def _camera_finished(self, passed: bool, message: str) -> None:
        if self._camera_timer.isActive():
            self._camera_timer.stop()
        if self._camera is not None:
            self._camera.stop()
        if not passed:
            message = f"{message}\n{_CAMERA_PRIVACY_HINT}"
        self._finish_check("camera", passed, message)

    def _system_check_finished(self, key: str, passed: bool, message: str) -> None:
        self._finish_check(key, passed, message)

    def _provider_check_finished(self, passed: bool, message: str) -> None:
        self._finish_check("provider", passed, "供應商連線成功。" if passed else provider_failure_hint(message))

    def _finish_check(self, key: str, passed: bool, message: str) -> None:
        current = self._results[key].text()
        if current != _CHECKING:
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
                return False, "無法讀取設定資料夾中的暫存檔。請檢查資料夾權限。"
        return True, "設定資料夾可正常讀寫。"
    except OSError as exc:
        return False, f"設定資料夾無法讀取或寫入：{exc}"


def _check_internet() -> tuple[bool, str]:
    try:
        request = urllib.request.Request("https://www.google.com/generate_204", method="GET")
        with urllib.request.urlopen(request, timeout=5):
            pass
        return True, "網路連線正常。"
    except Exception as exc:
        return False, f"無法連上網際網路。請檢查網路連線或代理伺服器設定。詳細資訊：{exc}"


def _check_browser() -> tuple[bool, str]:
    try:
        webbrowser.get()
        return True, "可使用預設瀏覽器。"
    except Exception:
        return False, "找不到預設瀏覽器。請在 Windows 設定中選擇預設瀏覽器。"


def _check_barcode(enabled: bool) -> tuple[bool, str]:
    if not enabled:
        return True, "已在「設定」中停用條碼掃描。"
    try:
        reader = BarcodeReader()
    except Exception as exc:
        return False, f"無法初始化條碼偵測：{exc}"
    if reader.available:
        return True, "OpenCV 條碼偵測已初始化。"
    return False, "條碼偵測無法使用。請安裝 OpenCV contrib 套件，或在「設定」中停用條碼掃描。"
