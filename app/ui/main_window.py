from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtMultimedia import QCameraDevice, QMediaDevices
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.ai.gemini_provider import GeminiProvider
from app.camera.camera_view import CameraView
from app.config import AppConfig
from app.search.sites import open_search_tabs
from app.ui.settings_dialog import GeminiSettingsDialog
from app.workers import IdentifyWorker


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self._devices: list[QCameraDevice] = []
        self._worker: IdentifyWorker | None = None
        self.setWindowTitle("PriceLens")
        self.resize(1180, 720)

        root = QWidget()
        row = QHBoxLayout(root)
        row.setContentsMargins(18, 18, 18, 18)
        row.setSpacing(18)
        self.setCentralWidget(root)

        preview_column = QVBoxLayout()
        camera_row = QHBoxLayout()
        camera_row.addWidget(QLabel("Camera"))
        self.camera_combo = QComboBox()
        self.camera_combo.setMinimumWidth(250)
        self.refresh_button = QPushButton("Refresh")
        camera_row.addWidget(self.camera_combo, 1)
        camera_row.addWidget(self.refresh_button)
        preview_column.addLayout(camera_row)
        self.camera_view = CameraView()
        preview_column.addWidget(self.camera_view, 1)
        row.addLayout(preview_column, 7)

        controls = QFrame()
        controls.setFrameShape(QFrame.Shape.StyledPanel)
        controls.setMinimumWidth(270)
        control_layout = QVBoxLayout(controls)
        control_layout.setContentsMargins(20, 20, 20, 20)
        control_layout.setSpacing(14)
        heading = QLabel("Identify a product")
        heading.setStyleSheet("font-size: 21px; font-weight: 600;")
        self.instructions = QLabel("Hold an item in front of the camera, then press SPACE or Identify now.")
        self.instructions.setWordWrap(True)
        self.identify_button = QPushButton("Identify now")
        self.identify_button.setMinimumHeight(46)
        self.identify_button.setDefault(True)
        self.provider_label = QLabel()
        self.provider_label.setWordWrap(True)
        self.settings_button = QPushButton("Gemini settings")
        self.result_label = QLabel("Your product search will open in seven browser tabs.")
        self.result_label.setWordWrap(True)
        self.result_label.setMinimumHeight(88)
        control_layout.addWidget(heading)
        control_layout.addWidget(self.instructions)
        control_layout.addWidget(self.identify_button)
        control_layout.addSpacing(10)
        control_layout.addWidget(self.provider_label)
        control_layout.addWidget(self.settings_button)
        control_layout.addSpacing(10)
        control_layout.addWidget(self.result_label)
        control_layout.addStretch(1)
        row.addWidget(controls, 3)

        self.camera_combo.currentIndexChanged.connect(self._select_camera)
        self.refresh_button.clicked.connect(self._refresh_cameras)
        self.identify_button.clicked.connect(self.identify_now)
        self.settings_button.clicked.connect(self._open_settings)
        self.camera_view.camera_error.connect(self._show_camera_error)
        self.space_shortcut = QShortcut(QKeySequence("Space"), self)
        self.space_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.space_shortcut.activated.connect(self.identify_now)
        self._refresh_cameras(self.config.camera_device_id)
        self._update_provider_label()
        self.statusBar().showMessage("Ready")

    def _refresh_cameras(self, preferred_id: str | None = None) -> None:
        if preferred_id is None:
            preferred_id = self.config.camera_device_id
        self._devices = list(QMediaDevices.videoInputs())
        self.camera_combo.blockSignals(True)
        self.camera_combo.clear()
        for device in self._devices:
            self.camera_combo.addItem(device.description(), device)
        selected = next(
            (index for index, device in enumerate(self._devices) if self._device_id(device) == preferred_id),
            0 if self._devices else -1,
        )
        self.camera_combo.setCurrentIndex(selected)
        self.camera_combo.setEnabled(bool(self._devices))
        self.camera_combo.blockSignals(False)
        self._select_camera(selected)
        if not self._devices:
            self.camera_view.set_device(None)
            self.statusBar().showMessage("No camera found. Connect a camera and press Refresh.")

    def _select_camera(self, index: int) -> None:
        if index < 0:
            return
        device = self.camera_combo.itemData(index) if index >= 0 else None
        self.camera_view.set_device(device)
        self.config.camera_device_id = self._device_id(device) if device else ""
        self._save_config(show_error=False)
        if device:
            self.statusBar().showMessage(f"Camera: {device.description()}")

    @staticmethod
    def _device_id(device: QCameraDevice) -> str:
        return bytes(device.id()).decode("utf-8", errors="replace")

    def _open_settings(self) -> None:
        dialog = GeminiSettingsDialog(self.config, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.config.gemini_api_key = dialog.api_key.text().strip()
        self.config.gemini_model = dialog.model.text().strip()
        if self._save_config():
            self._update_provider_label()
            self.statusBar().showMessage("Gemini settings saved on this computer.")

    def _save_config(self, show_error: bool = True) -> bool:
        try:
            self.config.save()
            return True
        except OSError:
            if show_error:
                QMessageBox.warning(self, "Settings not saved", "PriceLens could not write its local config file.")
            return False

    def _update_provider_label(self) -> None:
        configured = "API key saved" if self.config.gemini_api_key else "API key not set"
        self.provider_label.setText(f"Provider: Gemini\nModel: {self.config.gemini_model}\n{configured}")

    def identify_now(self) -> None:
        if self._worker is not None:
            return
        if not self.config.gemini_api_key:
            self._open_settings()
            if not self.config.gemini_api_key:
                return
        jpeg_bytes = self.camera_view.current_jpeg()
        if not jpeg_bytes:
            self.statusBar().showMessage("Waiting for a live camera frame. Check the camera selection.")
            return

        provider = GeminiProvider(self.config.gemini_api_key, self.config.gemini_model)
        worker = IdentifyWorker(provider, jpeg_bytes, self.config.gemini_api_key, self)
        worker.succeeded.connect(self._identification_succeeded)
        worker.failed.connect(self._identification_failed)
        worker.finished.connect(self._worker_finished)
        self._worker = worker
        self.identify_button.setEnabled(False)
        self.result_label.setText("Identifying…")
        self.statusBar().showMessage("Sending image to Gemini…")
        worker.start()

    def _identification_succeeded(self, product) -> None:
        parts = [part for part in (product.name_zh, product.name_en) if part]
        if product.brand and product.brand not in parts:
            parts.append(product.brand)
        if product.model and product.model not in parts:
            parts.append(product.model)
        summary = " · ".join(parts) or product.query_zh
        if product.msrp_estimate:
            summary += f"\nAI estimate: {product.msrp_estimate}"
        self.result_label.setText(summary)
        count = open_search_tabs(product)
        self.statusBar().showMessage(f"Opened {count} search tabs for {product.query_zh or product.query_en}.")

    def _identification_failed(self, message: str) -> None:
        self.result_label.setText("Identification failed. Check the key or connection and try again.")
        self.statusBar().showMessage(message or "Identification failed.", 12000)

    def _worker_finished(self) -> None:
        worker = self._worker
        self._worker = None
        self.identify_button.setEnabled(True)
        if worker is not None:
            worker.deleteLater()

    def _show_camera_error(self, message: str) -> None:
        self.statusBar().showMessage(f"Camera error: {message}", 10000)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self.camera_view.stop()
        super().closeEvent(event)
