from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut, QImage
from PySide6.QtMultimedia import QCameraDevice, QMediaDevices
from PySide6.QtWidgets import (
    QCheckBox,
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
from app.camera.camera_view import CameraView, image_to_jpeg
from app.config import AppConfig
from app.detection.barcode import BarcodeReader
from app.detection.image_utils import qimage_to_bgr, small_gray_frame
from app.detection.motion_trigger import MotionState
from app.detection.pipeline import AutoDetectionPipeline
from app.search.sites import open_search_tabs
from app.ui.settings_dialog import GeminiSettingsDialog
from app.workers import IdentifyWorker


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self._devices: list[QCameraDevice] = []
        self._worker: IdentifyWorker | None = None
        self._auto_detection_enabled = False
        self._auto_start_pending = config.detection.auto_enabled
        self._auto_pipeline: AutoDetectionPipeline | None = None
        self._needs_background = False
        self._last_detection_frame_ms = 0
        self._barcode_reader = BarcodeReader()
        self.setWindowTitle("PriceLens")
        self.resize(1180, 760)

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
        controls.setMinimumWidth(285)
        control_layout = QVBoxLayout(controls)
        control_layout.setContentsMargins(20, 20, 20, 20)
        control_layout.setSpacing(12)

        heading = QLabel("Identify a product")
        heading.setStyleSheet("font-size: 21px; font-weight: 600;")
        self.instructions = QLabel("Place an item in view for automatic detection, or press SPACE to identify now.")
        self.instructions.setWordWrap(True)
        self.identify_button = QPushButton("Identify now")
        self.identify_button.setMinimumHeight(44)
        self.identify_button.setDefault(True)
        self.detection_button = QPushButton("Start Detection")
        self.detection_button.setMinimumHeight(44)
        self.reset_background_button = QPushButton("Reset background")
        self.reset_background_button.setEnabled(False)
        self.detection_state_label = QLabel("STOPPED")
        self.detection_state_label.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.barcode_checkbox = QCheckBox("Use a visible barcode as a hint")
        self.barcode_checkbox.setChecked(self.config.detection.barcode_enabled)
        if not self._barcode_reader.available:
            self.barcode_checkbox.setEnabled(False)
            self.barcode_checkbox.setToolTip("Barcode support is unavailable in this OpenCV build.")
        self.provider_label = QLabel()
        self.provider_label.setWordWrap(True)
        self.settings_button = QPushButton("Gemini settings")
        self.result_label = QLabel("Product searches open in seven browser tabs.")
        self.result_label.setWordWrap(True)
        self.result_label.setMinimumHeight(82)

        control_layout.addWidget(heading)
        control_layout.addWidget(self.instructions)
        control_layout.addWidget(self.detection_state_label)
        control_layout.addWidget(self.detection_button)
        control_layout.addWidget(self.reset_background_button)
        control_layout.addWidget(self.identify_button)
        control_layout.addWidget(self.barcode_checkbox)
        control_layout.addSpacing(8)
        control_layout.addWidget(self.provider_label)
        control_layout.addWidget(self.settings_button)
        control_layout.addSpacing(8)
        control_layout.addWidget(self.result_label)
        control_layout.addStretch(1)
        row.addWidget(controls, 3)

        self.camera_combo.currentIndexChanged.connect(self._select_camera)
        self.refresh_button.clicked.connect(self._refresh_cameras)
        self.identify_button.clicked.connect(self.identify_now)
        self.detection_button.clicked.connect(self._toggle_detection)
        self.reset_background_button.clicked.connect(self._reset_background)
        self.barcode_checkbox.toggled.connect(self._barcode_setting_changed)
        self.settings_button.clicked.connect(self._open_settings)
        self.camera_view.camera_error.connect(self._show_camera_error)
        self.camera_view.frame_changed.connect(self._on_camera_frame)
        self.space_shortcut = QShortcut(QKeySequence("Space"), self)
        self.space_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.space_shortcut.activated.connect(self.identify_now)

        self._refresh_cameras(self.config.camera_device_id)
        self._update_provider_label()
        self._update_detection_controls()
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
            if self._auto_detection_enabled:
                self._stop_detection(save=False)
            self.statusBar().showMessage("Camera lost. Connect a camera and press Refresh.")

    def _select_camera(self, index: int) -> None:
        if index < 0:
            return
        device = self.camera_combo.itemData(index)
        self.camera_view.set_device(device)
        self.config.camera_device_id = self._device_id(device) if device else ""
        self._save_config(show_error=False)
        if self._auto_detection_enabled:
            self._needs_background = True
            self.statusBar().showMessage("Camera changed. Capturing a new background…")
        elif device:
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

    def _barcode_setting_changed(self, enabled: bool) -> None:
        self.config.detection.barcode_enabled = enabled
        self._save_config(show_error=False)

    def _toggle_detection(self) -> None:
        if self._auto_detection_enabled:
            self._stop_detection()
        else:
            self._start_detection()

    def _start_detection(self) -> bool:
        if not self.config.gemini_api_key:
            self._open_settings()
            if not self.config.gemini_api_key:
                self.config.detection.auto_enabled = False
                self._auto_start_pending = False
                self._save_config(show_error=False)
                self.statusBar().showMessage("Set a Gemini API key before starting detection.")
                return False

        image = self.camera_view.current_image()
        if image is None:
            self.statusBar().showMessage("Waiting for a live camera frame. Check the camera selection.")
            return False

        gray = small_gray_frame(image)
        self._auto_pipeline = AutoDetectionPipeline(self.config.detection)
        self._auto_pipeline.reset_background(gray)
        self._auto_detection_enabled = True
        self._auto_start_pending = False
        self._needs_background = False
        self._last_detection_frame_ms = int(time.monotonic() * 1000)
        self.config.detection.auto_enabled = True
        self._save_config(show_error=False)
        self._update_detection_controls()
        self.detection_state_label.setText(MotionState.IDLE.value)
        self.statusBar().showMessage("Detection started. Background captured; place an item in view.")
        return True

    def _stop_detection(self, save: bool = True) -> None:
        self._auto_detection_enabled = False
        self._auto_start_pending = False
        self._needs_background = False
        self._auto_pipeline = None
        self.config.detection.auto_enabled = False
        if save:
            self._save_config(show_error=False)
        self._update_detection_controls()
        self.detection_state_label.setText("STOPPED")
        if save:
            self.statusBar().showMessage("Detection stopped. SPACE and Identify now still work.")

    def _update_detection_controls(self) -> None:
        self.detection_button.setText("Stop Detection" if self._auto_detection_enabled else "Start Detection")
        self.reset_background_button.setEnabled(self._auto_detection_enabled)

    def _reset_background(self) -> None:
        if self._auto_pipeline is None:
            return
        image = self.camera_view.current_image()
        if image is None:
            self.statusBar().showMessage("Waiting for a camera frame before resetting background.")
            return
        self._auto_pipeline.reset_background(small_gray_frame(image))
        self.detection_state_label.setText(MotionState.IDLE.value)
        self.statusBar().showMessage("Background reset to the current camera view.")

    def _on_camera_frame(self, image: QImage) -> None:
        if self._auto_start_pending:
            self._start_detection()
        if not self._auto_detection_enabled or self._auto_pipeline is None:
            return

        now_ms = int(time.monotonic() * 1000)
        try:
            gray = small_gray_frame(image)
        except Exception as exc:
            self.statusBar().showMessage(f"Camera frame could not be processed: {exc}", 5000)
            return
        if self._needs_background:
            self._auto_pipeline.reset_background(gray)
            self._needs_background = False
            self.detection_state_label.setText(MotionState.IDLE.value)
            self.statusBar().showMessage("Camera ready. New background captured.")
            return
        if now_ms - self._last_detection_frame_ms < 100:
            return
        self._last_detection_frame_ms = now_ms

        update = self._auto_pipeline.update(gray, now_ms)
        self.detection_state_label.setText(update.state.value)
        if update.ignored_reason:
            messages = {
                "empty_scene": "Empty scene ignored.",
                "duplicate": "Same item ignored.",
                "cooldown": "Auto trigger skipped during cooldown.",
                "background_reset": "Camera frame size changed; background was reset.",
            }
            self.statusBar().showMessage(messages.get(update.ignored_reason, "Frame ignored."), 3000)
        if update.triggered:
            barcode = self._barcode_for(image)
            self._request_identification(image, barcode=barcode, manual=False)

    def _barcode_for(self, image: QImage) -> str | None:
        if not self.config.detection.barcode_enabled or not self._barcode_reader.available:
            return None
        return self._barcode_reader.decode(qimage_to_bgr(image))

    def identify_now(self) -> None:
        if self._worker is not None:
            self.statusBar().showMessage("busy — the current identification is still running.")
            return
        if not self.config.gemini_api_key:
            self._open_settings()
            if not self.config.gemini_api_key:
                return
        image = self.camera_view.current_image()
        if image is None:
            self.statusBar().showMessage("Waiting for a live camera frame. Check the camera selection.")
            return
        self._request_identification(image, barcode=self._barcode_for(image), manual=True)

    def _request_identification(self, image: QImage, barcode: str | None, manual: bool) -> None:
        if self._worker is not None:
            self.statusBar().showMessage("busy — trigger dropped while an identification is running.")
            return
        if not self.config.gemini_api_key:
            self.statusBar().showMessage("Set a Gemini API key in Gemini settings first.")
            return
        jpeg_bytes = image_to_jpeg(image)
        if not jpeg_bytes:
            self.statusBar().showMessage("Could not encode the current camera frame.")
            return

        provider = GeminiProvider(self.config.gemini_api_key, self.config.gemini_model)
        worker = IdentifyWorker(
            provider,
            jpeg_bytes,
            self.config.gemini_api_key,
            barcode=barcode,
            parent=self,
        )
        worker.succeeded.connect(self._identification_succeeded)
        worker.failed.connect(self._identification_failed)
        worker.finished.connect(self._worker_finished)
        self._worker = worker
        self.identify_button.setEnabled(False)
        self.result_label.setText("Identifying…")
        self.detection_state_label.setText("IDENTIFYING…")
        source = "manual request" if manual else "automatic trigger"
        self.statusBar().showMessage(f"Sending image to Gemini ({source})…")
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
        self.detection_state_label.setText("DONE")
        count = open_search_tabs(product)
        self.statusBar().showMessage(f"Opened {count} search tabs for {product.query_zh or product.query_en}.")

    def _identification_failed(self, message: str) -> None:
        self.result_label.setText("Identification failed. Check the key or connection and try again.")
        self.detection_state_label.setText(MotionState.IDLE.value if self._auto_detection_enabled else "STOPPED")
        self.statusBar().showMessage(message or "Identification failed.", 12000)

    def _worker_finished(self) -> None:
        worker = self._worker
        self._worker = None
        self.identify_button.setEnabled(True)
        if worker is not None:
            worker.deleteLater()

    def _show_camera_error(self, message: str) -> None:
        if self._auto_detection_enabled:
            self._stop_detection()
        self.detection_state_label.setText("CAMERA LOST")
        self.statusBar().showMessage(f"Camera lost: {message}. Press Refresh to reconnect.", 10000)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self.camera_view.stop()
        super().closeEvent(event)
