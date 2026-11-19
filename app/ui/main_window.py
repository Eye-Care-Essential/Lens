from __future__ import annotations

import time

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtMultimedia import QCameraDevice, QMediaDevices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.ai.base import ProductResult
from app.ai.factory import create_provider
from app.camera.camera_view import CameraView, image_to_jpeg
from app.config import AppConfig
from app.detection.barcode import BarcodeReader
from app.detection.image_utils import qimage_to_bgr, small_gray_frame
from app.detection.motion_trigger import MotionState
from app.detection.pipeline import AutoDetectionPipeline
from app.history.store import HistoryEntry, HistoryStore
from app.paths import app_data_dir
from app.search.sites import open_search_tabs
from app.ui.selftest_dialog import SelfTestDialog
from app.ui.settings_dialog import SettingsDialog
from app.workers import IdentifyWorker

PROVIDER_NAMES = {"claude": "Claude", "gemini": "Gemini", "openai": "OpenAI", "custom": "Custom"}


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
        self._pending_jpeg = b""
        self._pending_barcode = ""
        self._pending_provider = ""
        self._session_calls = 0
        self._barcode_reader = BarcodeReader()
        self.history_store = HistoryStore()
        try:
            self.history_store.trim(self.config.general.max_history)
        except OSError:
            pass
        self.setWindowTitle("PriceLens")
        self.resize(1280, 800)

        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(12)
        self.setCentralWidget(root)

        toolbar = QHBoxLayout()
        self.settings_button = QPushButton("Settings")
        self.self_test_button = QPushButton("Self-Test")
        self.open_history_button = QPushButton("Open history folder")
        toolbar.addWidget(self.settings_button)
        toolbar.addWidget(self.self_test_button)
        toolbar.addWidget(self.open_history_button)
        toolbar.addStretch(1)
        self.provider_label = QLabel()
        toolbar.addWidget(self.provider_label)
        outer.addLayout(toolbar)

        content = QHBoxLayout()
        content.setSpacing(16)
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
        content.addLayout(preview_column, 7)

        controls = QFrame()
        controls.setFrameShape(QFrame.Shape.StyledPanel)
        controls.setMinimumWidth(320)
        control_layout = QVBoxLayout(controls)
        control_layout.setContentsMargins(16, 16, 16, 16)
        control_layout.setSpacing(10)
        heading = QLabel("Identify a product")
        heading.setStyleSheet("font-size: 21px; font-weight: 600;")
        self.instructions = QLabel("Place an item in view for automatic detection, or press SPACE to identify now.")
        self.instructions.setWordWrap(True)
        self.camera_name_label = QLabel("Camera: —")
        self.detection_state_label = QLabel("STOPPED")
        self.detection_state_label.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.detection_button = QPushButton("Start Detection")
        self.detection_button.setMinimumHeight(44)
        self.reset_background_button = QPushButton("Reset background")
        self.reset_background_button.setEnabled(False)
        self.identify_button = QPushButton("Identify now")
        self.identify_button.setMinimumHeight(44)
        self.identify_button.setDefault(True)
        self.barcode_checkbox = QCheckBox("Use a visible barcode as a hint")
        self.barcode_checkbox.setChecked(self.config.detection.barcode_enabled)
        if not self._barcode_reader.available:
            self.barcode_checkbox.setEnabled(False)
            self.barcode_checkbox.setToolTip("Barcode support is unavailable in this OpenCV build.")
        self.result_label = QLabel("Product searches open in enabled browser tabs.")
        self.result_label.setWordWrap(True)
        self.result_label.setMinimumHeight(64)
        self.history_label = QLabel("History")
        self.history_label.setStyleSheet("font-size: 15px; font-weight: 600;")
        self.history_list = QListWidget()
        self.history_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_list.setMinimumHeight(230)
        control_layout.addWidget(heading)
        control_layout.addWidget(self.instructions)
        control_layout.addWidget(self.camera_name_label)
        control_layout.addWidget(self.detection_state_label)
        control_layout.addWidget(self.detection_button)
        control_layout.addWidget(self.reset_background_button)
        control_layout.addWidget(self.identify_button)
        control_layout.addWidget(self.barcode_checkbox)
        control_layout.addWidget(self.result_label)
        control_layout.addWidget(self.history_label)
        control_layout.addWidget(self.history_list, 1)
        content.addWidget(controls, 3)
        outer.addLayout(content, 1)

        self.camera_combo.currentIndexChanged.connect(self._select_camera)
        self.refresh_button.clicked.connect(self._refresh_cameras)
        self.identify_button.clicked.connect(self.identify_now)
        self.detection_button.clicked.connect(self._toggle_detection)
        self.reset_background_button.clicked.connect(self._reset_background)
        self.barcode_checkbox.toggled.connect(self._barcode_setting_changed)
        self.settings_button.clicked.connect(self._open_settings)
        self.self_test_button.clicked.connect(self._run_self_test)
        self.open_history_button.clicked.connect(self._open_history_folder)
        self.history_list.itemDoubleClicked.connect(self._open_history_entry)
        self.history_list.customContextMenuRequested.connect(self._history_context_menu)
        self.camera_view.camera_error.connect(self._show_camera_error)
        self.camera_view.frame_changed.connect(self._on_camera_frame)
        self.space_shortcut = QShortcut(QKeySequence("Space"), self)
        self.space_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.space_shortcut.activated.connect(self.identify_now)

        self._refresh_cameras(self.config.camera_device_id)
        self._update_provider_label()
        self._update_detection_controls()
        self._refresh_history()
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
            0 if self._devices and not preferred_id else -1,
        )
        if not self._devices:
            self.camera_combo.addItem("No camera found", "")
            selected = 0
        elif preferred_id and selected < 0:
            self.camera_combo.insertItem(0, "Saved camera unavailable", "")
            selected = 0
        self.camera_combo.setCurrentIndex(selected)
        self.camera_combo.setEnabled(bool(self._devices))
        self.camera_combo.blockSignals(False)
        self._select_camera(selected)
        if not self._devices:
            self.camera_view.set_device(None)
            if self._auto_detection_enabled:
                self._stop_detection(save=False)
            self.statusBar().showMessage("Camera not found. Connect a camera and press Refresh.")

    def _select_camera(self, index: int) -> None:
        device = self.camera_combo.itemData(index) if index >= 0 else None
        if not isinstance(device, QCameraDevice):
            device = None
        self.camera_view.set_device(device, self.config.camera_resolution)
        if device is not None:
            self.config.camera_device_id = self._device_id(device)
            self._save_config(show_error=False)
        if device:
            self.camera_name_label.setText(f"Camera: {device.description()}")
        elif self.config.camera_device_id:
            self.camera_name_label.setText("Camera: saved device unavailable")
        else:
            self.camera_name_label.setText("Camera: unavailable")
        if self._auto_detection_enabled:
            self._needs_background = True
            self.statusBar().showMessage("Camera changed. Capturing a new background…")
        elif device:
            self.statusBar().showMessage(f"Camera: {device.description()}")
        if self._auto_start_pending and device is None:
            self.statusBar().showMessage("Saved camera is unplugged. Choose another camera or run Self-Test.")

    @staticmethod
    def _device_id(device: QCameraDevice | None) -> str:
        return bytes(device.id()).decode("utf-8", errors="replace") if device else ""

    def _pause_camera_for_dialog(self) -> bool:
        was_running = self._auto_detection_enabled or self._auto_start_pending
        self._auto_detection_enabled = False
        self._auto_start_pending = False
        self._auto_pipeline = None
        self.camera_view.set_device(None)
        return was_running

    def _resume_camera_after_dialog(self, was_running: bool) -> None:
        self.config.detection.auto_enabled = was_running
        self._auto_start_pending = was_running
        self._auto_detection_enabled = False
        device = self.camera_combo.currentData()
        self.camera_view.set_device(device if isinstance(device, QCameraDevice) else None, self.config.camera_resolution)
        self._update_detection_controls()
        self._save_config(show_error=False)

    def _open_settings(self) -> None:
        was_running = self._pause_camera_for_dialog()
        dialog = SettingsDialog(self.config, self)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        if accepted:
            self.config = dialog.config
            try:
                self.history_store.trim(self.config.general.max_history)
            except OSError as exc:
                self.statusBar().showMessage(f"History limit could not be applied: {exc}", 5000)
            self.barcode_checkbox.setChecked(self.config.detection.barcode_enabled)
            if dialog.reset_background_requested:
                self._needs_background = True
            self._save_config()
            self._update_provider_label()
            self._refresh_cameras(self.config.camera_device_id)
            self.statusBar().showMessage("Settings saved. The selected provider is active immediately.")
        self._resume_camera_after_dialog(was_running)

    def _run_self_test(self) -> None:
        was_running = self._pause_camera_for_dialog()
        dialog = SelfTestDialog(self.config, self)
        dialog.exec()
        self._resume_camera_after_dialog(was_running)

    def _save_config(self, show_error: bool = True) -> bool:
        try:
            self.config.save()
            return True
        except OSError:
            if show_error:
                QMessageBox.warning(self, "Settings not saved", "PriceLens could not write its local config file.")
            return False

    def _update_provider_label(self) -> None:
        provider_id = self.config.active_provider
        provider = self.config.providers.get(provider_id)
        if provider is None:
            self.provider_label.setText("Provider: unavailable")
            return
        configured = "API key saved" if provider.api_key else "API key not set"
        self.provider_label.setText(f"Provider: {PROVIDER_NAMES.get(provider_id, provider_id)} · {provider.model} · {configured}")
        self.provider_label.setToolTip(self.provider_label.text())

    def _barcode_setting_changed(self, enabled: bool) -> None:
        self.config.detection.barcode_enabled = enabled
        self._save_config(show_error=False)

    def _toggle_detection(self) -> None:
        if self._auto_detection_enabled:
            self._stop_detection()
        else:
            self._start_detection()

    def _active_api_configured(self) -> bool:
        provider = self.config.providers.get(self.config.active_provider)
        return bool(provider and provider.api_key.strip())

    def _start_detection(self) -> bool:
        if not self._active_api_configured():
            self._open_settings()
            if not self._active_api_configured():
                self.config.detection.auto_enabled = False
                self._auto_start_pending = False
                self._save_config(show_error=False)
                self.statusBar().showMessage("Set an API key for the selected provider before starting detection.")
                return False

        image = self.camera_view.current_image()
        if image is None:
            self.statusBar().showMessage("Waiting for a live camera frame. Check the camera selection.")
            return False
        self._auto_pipeline = AutoDetectionPipeline(self.config.detection)
        self._auto_pipeline.reset_background(small_gray_frame(image))
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

    def _on_camera_frame(self, image) -> None:
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
            self._request_identification(image, barcode=self._barcode_for(image), manual=False)

    def _barcode_for(self, image) -> str | None:
        if not self.config.detection.barcode_enabled or not self._barcode_reader.available:
            return None
        return self._barcode_reader.decode(qimage_to_bgr(image))

    def identify_now(self) -> None:
        if self._worker is not None:
            self.statusBar().showMessage("busy — the current identification is still running.")
            return
        if not self._active_api_configured():
            self._open_settings()
            if not self._active_api_configured():
                return
        image = self.camera_view.current_image()
        if image is None:
            self.statusBar().showMessage("Waiting for a live camera frame. Check the camera selection.")
            return
        self._request_identification(image, barcode=self._barcode_for(image), manual=True)

    def _request_identification(self, image, barcode: str | None, manual: bool) -> None:
        if self._worker is not None:
            self.statusBar().showMessage("busy — trigger dropped while an identification is running.")
            return
        jpeg_bytes = image_to_jpeg(image)
        if not jpeg_bytes:
            self.statusBar().showMessage("Could not encode the current camera frame.")
            return
        try:
            provider = create_provider(self.config)
        except Exception as exc:
            self.statusBar().showMessage(str(exc), 10000)
            return
        self._pending_jpeg = jpeg_bytes
        self._pending_barcode = barcode or ""
        self._pending_provider = self.config.active_provider
        worker = IdentifyWorker(provider, jpeg_bytes, self.config.providers[self.config.active_provider].api_key, barcode=barcode, parent=self)
        worker.succeeded.connect(self._identification_succeeded)
        worker.failed.connect(self._identification_failed)
        worker.finished.connect(self._worker_finished)
        self._worker = worker
        self.identify_button.setEnabled(False)
        self.result_label.setText("Identifying…")
        self.detection_state_label.setText("IDENTIFYING…")
        source = "manual request" if manual else "automatic trigger"
        self.statusBar().showMessage(f"Sending image to {PROVIDER_NAMES.get(self._pending_provider, self._pending_provider)} ({source})…")
        worker.start()

    def _record_success(self, product: ProductResult) -> None:
        try:
            self.history_store.add_success(product, self._pending_jpeg, self._pending_barcode, self._pending_provider, self.config.general.max_history)
            self._refresh_history()
        except OSError as exc:
            self.statusBar().showMessage(f"History could not be saved: {exc}", 5000)

    def _identification_succeeded(self, product: ProductResult) -> None:
        self._session_calls += 1
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
        self._record_success(product)
        count = open_search_tabs(product, self.config.search, self.config.general.open_tabs_delay_ms)
        self.statusBar().showMessage(f"Opened {count} search tabs for {product.query_zh or product.query_en}. Session calls: {self._session_calls}.")

    def _identification_failed(self, message: str) -> None:
        self._session_calls += 1
        self.result_label.setText("Identification failed. Check the key or connection and try again.")
        self.detection_state_label.setText(MotionState.IDLE.value if self._auto_detection_enabled else "STOPPED")
        try:
            self.history_store.add_failure(message, self._pending_jpeg, self._pending_barcode, self._pending_provider, self.config.general.max_history)
            self._refresh_history()
        except OSError as exc:
            self.statusBar().showMessage(f"History could not be saved: {exc}", 5000)
        self.statusBar().showMessage(f"{message or 'Identification failed.'} · Session calls: {self._session_calls}.", 12000)

    def _worker_finished(self) -> None:
        worker = self._worker
        self._worker = None
        self.identify_button.setEnabled(True)
        if worker is not None:
            worker.deleteLater()

    def _refresh_history(self) -> None:
        self.history_list.clear()
        for entry in self.history_store.entries:
            if entry.status == "success":
                title = " · ".join(part for part in (entry.name_zh, entry.name_en, entry.brand, entry.model) if part) or entry.query_zh or entry.query_en
                if entry.msrp_estimate:
                    title += f"\nAI estimate: {entry.msrp_estimate}"
            else:
                title = f"Identification failed\n{entry.error[:100]}"
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            item.setToolTip(f"{entry.timestamp} · {PROVIDER_NAMES.get(entry.provider, entry.provider)} · {entry.status}")
            thumbnail = self.history_store.thumbnail_path(entry)
            if thumbnail:
                pixmap = QPixmap(str(thumbnail))
                if not pixmap.isNull():
                    item.setIcon(QIcon(pixmap.scaled(64, 48, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)))
            self.history_list.addItem(item)

    def _entry_for_item(self, item: QListWidgetItem | None) -> HistoryEntry | None:
        if item is None:
            return None
        entry_id = item.data(Qt.ItemDataRole.UserRole)
        return next((entry for entry in self.history_store.entries if entry.id == entry_id), None)

    def _open_history_entry(self, item: QListWidgetItem) -> None:
        entry = self._entry_for_item(item)
        if entry is None or entry.status != "success":
            return
        product = ProductResult(entry.name_zh, entry.name_en, entry.brand, entry.model, entry.category, entry.query_zh, entry.query_en, entry.msrp_estimate, {})
        count = open_search_tabs(product, self.config.search, self.config.general.open_tabs_delay_ms)
        self.statusBar().showMessage(f"Reopened {count} search tabs for {entry.query_zh or entry.query_en}.")

    def _history_context_menu(self, position) -> None:
        item = self.history_list.itemAt(position)
        entry = self._entry_for_item(item)
        if entry is None:
            return
        menu = QMenu(self)
        copy_action = menu.addAction("Copy search query")
        delete_action = menu.addAction("Delete history entry")
        selected = menu.exec(self.history_list.mapToGlobal(position))
        if selected == copy_action:
            query = entry.query_zh or entry.query_en
            QApplication.clipboard().setText(query)
        elif selected == delete_action:
            self.history_store.delete(entry.id)
            self._refresh_history()

    def _open_history_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(app_data_dir())))

    def _show_camera_error(self, message: str) -> None:
        if self._auto_detection_enabled:
            self._stop_detection()
        self.detection_state_label.setText("CAMERA LOST")
        self.statusBar().showMessage(f"Camera lost: {message}. Press Refresh to reconnect.", 10000)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self.camera_view.stop()
        super().closeEvent(event)
