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
from app.camera.camera_view import CameraView, camera_label, choose_camera_index, device_id, image_to_jpeg
from app.config import AppConfig
from app.detection.barcode import BarcodeReader
from app.detection.image_utils import qimage_to_bgr, small_gray_frame
from app.detection.motion_trigger import MotionState
from app.detection.pipeline import AutoDetectionPipeline
from app.history.store import HistoryEntry, HistoryStore
from app.paths import app_data_dir
from app.search.sites import open_search_tabs
from app.ui.messages import show_message
from app.ui.selftest_dialog import SelfTestDialog
from app.ui.settings_dialog import SettingsDialog
from app.workers import IdentifyWorker

PROVIDER_NAMES = {"claude": "Claude", "gemini": "Gemini", "openai": "OpenAI", "custom": "自訂"}
MOTION_LABELS = {
    MotionState.IDLE: "等待中",
    MotionState.MOTION: "偵測到動作",
    MotionState.STABLE: "畫面穩定…",
}


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
        self._pending_thumb = b""
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
        self.settings_button = QPushButton("設定")
        self.self_test_button = QPushButton("自我檢查")
        self.open_history_button = QPushButton("開啟紀錄資料夾")
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
        camera_row.addWidget(QLabel("相機"))
        self.camera_combo = QComboBox()
        self.camera_combo.setMinimumWidth(250)
        self.refresh_button = QPushButton("重新整理")
        self.next_camera_button = QPushButton("下一台相機")
        self.next_camera_button.setToolTip("切換到下一台相機（C）")
        camera_row.addWidget(self.camera_combo, 1)
        camera_row.addWidget(self.refresh_button)
        camera_row.addWidget(self.next_camera_button)
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
        heading = QLabel("辨識商品")
        heading.setStyleSheet("font-size: 21px; font-weight: 600;")
        self.instructions = QLabel("將商品放入畫面即可自動偵測，也可按空白鍵立即辨識。")
        self.instructions.setWordWrap(True)
        self.camera_name_label = QLabel("相機：—")
        self.camera_name_label.setWordWrap(True)
        self.detection_state_label = QLabel("已停止")
        self.detection_state_label.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.detection_button = QPushButton("開始偵測")
        self.detection_button.setMinimumHeight(44)
        self.reset_background_button = QPushButton("重設背景")
        self.reset_background_button.setEnabled(False)
        self.identify_button = QPushButton("立即辨識")
        self.identify_button.setMinimumHeight(44)
        self.identify_button.setDefault(True)
        self.barcode_checkbox = QCheckBox("使用畫面中的條碼輔助辨識")
        self.barcode_checkbox.setChecked(self.config.detection.barcode_enabled)
        if not self._barcode_reader.available:
            self.barcode_checkbox.setEnabled(False)
            self.barcode_checkbox.setToolTip("目前的 OpenCV 版本不支援條碼辨識。")
        self.result_label = QLabel("辨識後會在瀏覽器分頁中開啟已啟用網站的搜尋結果。")
        self.result_label.setWordWrap(True)
        self.result_label.setMinimumHeight(64)
        self.history_label = QLabel("辨識紀錄")
        self.history_label.setStyleSheet("font-size: 15px; font-weight: 600;")
        self.history_list = QListWidget()
        self.history_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_list.setWordWrap(True)
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

        self.camera_combo.activated.connect(self._select_camera)
        # lambda: clicked sends checked=False, which would become preferred_id.
        self.refresh_button.clicked.connect(lambda: self._refresh_cameras())
        self.next_camera_button.clicked.connect(self._next_camera)
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
        self.next_camera_shortcut = QShortcut(QKeySequence("C"), self)
        self.next_camera_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.next_camera_shortcut.activated.connect(self._next_camera)

        self.statusBar().showMessage("就緒")
        self._refresh_cameras(self.config.camera_device_id)
        self._update_provider_label()
        self._update_detection_controls()
        self._refresh_history()

    def _refresh_cameras(self, preferred_id: str | None = None) -> None:
        if preferred_id is None:
            preferred_id = self.config.camera_device_id
        self._devices = list(QMediaDevices.videoInputs())
        self.camera_combo.blockSignals(True)
        self.camera_combo.clear()
        for device in self._devices:
            self.camera_combo.addItem(camera_label(device), device)
        selected, is_fallback = choose_camera_index(
            [device_id(device) for device in self._devices],
            preferred_id,
            device_id(QMediaDevices.defaultVideoInput()) if self._devices else "",
        )
        if not self._devices:
            self.camera_combo.addItem("找不到相機", "")
        self.camera_combo.setCurrentIndex(max(0, selected))
        self.camera_combo.setEnabled(bool(self._devices))
        self.camera_combo.blockSignals(False)
        can_cycle = len(self._devices) > 1
        self.next_camera_button.setEnabled(can_cycle)
        self.next_camera_shortcut.setEnabled(can_cycle)
        self._select_camera(selected, persist=not is_fallback)
        if not self._devices:
            if self._auto_detection_enabled:
                self._stop_detection(save=False)
            self.statusBar().showMessage("找不到相機。請連接相機後按「重新整理」。")
        elif is_fallback:
            label = self.camera_combo.itemText(selected)
            self.statusBar().showMessage(f"找不到已儲存的相機，已切換至 {label}。")

    def _next_camera(self) -> None:
        count = self.camera_combo.count()
        if count > 1:
            index = (self.camera_combo.currentIndex() + 1) % count
            self.camera_combo.setCurrentIndex(index)
            self._select_camera(index)

    def _select_camera(self, index: int, persist: bool = True) -> None:
        device = self.camera_combo.itemData(index) if index >= 0 else None
        if not isinstance(device, QCameraDevice):
            device = None
        self.camera_view.set_device(device, self.config.camera_resolution)
        if device is not None and persist:
            self.config.camera_device_id = device_id(device)
            self._save_config(show_error=False)
        if device:
            self.camera_name_label.setText(f"相機：{self.camera_combo.itemText(index)}")
        elif self.config.camera_device_id:
            self.camera_name_label.setText("相機：已儲存的裝置無法使用")
        else:
            self.camera_name_label.setText("相機：無法使用")
        if self._auto_detection_enabled:
            self._needs_background = True
            self.statusBar().showMessage("已切換相機。正在擷取新背景…")
        elif device:
            self.statusBar().showMessage(self.camera_name_label.text())
        if self._auto_start_pending and device is None:
            self.statusBar().showMessage("已儲存的相機未連接。請改選其他相機，或執行自我檢查。")

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
                self.statusBar().showMessage(f"無法套用紀錄筆數上限：{exc}", 5000)
            self.barcode_checkbox.setChecked(self.config.detection.barcode_enabled)
            if dialog.reset_background_requested:
                self._needs_background = True
            self._save_config()
            self._update_provider_label()
            self._refresh_cameras(self.config.camera_device_id)
            self.statusBar().showMessage("已儲存設定，所選供應商已生效。")
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
                show_message(self, QMessageBox.Icon.Warning, "無法儲存設定", "PriceLens 無法寫入本機設定檔。")
            return False

    def _update_provider_label(self) -> None:
        provider_id = self.config.active_provider
        provider = self.config.providers.get(provider_id)
        if provider is None:
            self.provider_label.setText("供應商：無法使用")
            return
        configured = "已儲存 API 金鑰" if provider.api_key else "尚未設定 API 金鑰"
        self.provider_label.setText(f"供應商：{PROVIDER_NAMES.get(provider_id, provider_id)} ・ {provider.model} ・ {configured}")
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
                self.statusBar().showMessage("請先設定所選供應商的 API 金鑰，再開始偵測。")
                return False

        image = self.camera_view.current_image()
        if image is None:
            self.statusBar().showMessage("正在等候相機畫面。請確認選取的相機。")
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
        self.detection_state_label.setText(MOTION_LABELS[MotionState.IDLE])
        self.statusBar().showMessage("已開始偵測並擷取背景。請將商品放入畫面。")
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
        self.detection_state_label.setText("已停止")
        if save:
            self.statusBar().showMessage("已停止偵測。仍可按空白鍵或點選「立即辨識」。")

    def _update_detection_controls(self) -> None:
        self.detection_button.setText("停止偵測" if self._auto_detection_enabled else "開始偵測")
        self.reset_background_button.setEnabled(self._auto_detection_enabled)

    def _reset_background(self) -> None:
        if self._auto_pipeline is None:
            return
        image = self.camera_view.current_image()
        if image is None:
            self.statusBar().showMessage("正在等候相機畫面，再重設背景。")
            return
        self._auto_pipeline.reset_background(small_gray_frame(image))
        self.detection_state_label.setText(MOTION_LABELS[MotionState.IDLE])
        self.statusBar().showMessage("已將目前的相機畫面設為背景。")

    def _on_camera_frame(self, image) -> None:
        # Webcams send dark frames for about a second while exposure settles;
        # a background captured then makes the empty table look like an item.
        if self.camera_view.frame_count < 30:
            return
        if self._auto_start_pending:
            self._start_detection()
        if not self._auto_detection_enabled or self._auto_pipeline is None:
            return
        now_ms = int(time.monotonic() * 1000)
        if now_ms - self._last_detection_frame_ms < 100:
            return  # throttle before the full-frame conversion below
        self._last_detection_frame_ms = now_ms
        try:
            gray = small_gray_frame(image)
        except Exception as exc:
            self.statusBar().showMessage(f"無法處理相機畫面：{exc}", 5000)
            return
        if self._needs_background:
            self._auto_pipeline.reset_background(gray)
            self._needs_background = False
            self.detection_state_label.setText(MOTION_LABELS[MotionState.IDLE])
            self.statusBar().showMessage("相機已就緒，並已擷取新背景。")
            return
        if self._worker is not None:
            return  # a trigger now would be dropped, yet the pipeline would count it as handled
        update = self._auto_pipeline.update(gray, now_ms)
        self.detection_state_label.setText(MOTION_LABELS[update.state])
        if update.ignored_reason:
            messages = {
                "empty_scene": "已略過沒有商品的畫面。",
                "duplicate": "已略過重複商品。",
                "cooldown": "冷卻期間已略過自動辨識。",
                "background_reset": "相機畫面尺寸已變更，已重設背景。",
            }
            self.statusBar().showMessage(messages.get(update.ignored_reason, "已略過此畫面。"), 3000)
        if update.triggered:
            self._request_identification(image, barcode=self._barcode_for(image), manual=False)

    def _barcode_for(self, image) -> str | None:
        if not self.config.detection.barcode_enabled or not self._barcode_reader.available:
            return None
        return self._barcode_reader.decode(qimage_to_bgr(image))

    def identify_now(self) -> None:
        if self._worker is not None:
            self.statusBar().showMessage("正在辨識，請稍候。")
            return
        if not self._active_api_configured():
            self._open_settings()
            if not self._active_api_configured():
                return
        image = self.camera_view.current_image()
        if image is None:
            self.statusBar().showMessage("正在等候相機畫面。請確認選取的相機。")
            return
        self._request_identification(image, barcode=self._barcode_for(image), manual=True)

    def _request_identification(self, image, barcode: str | None, manual: bool) -> None:
        if self._worker is not None:
            self.statusBar().showMessage("正在辨識，已略過這次觸發。")
            return
        jpeg_bytes = image_to_jpeg(image)
        if not jpeg_bytes:
            self.statusBar().showMessage("無法編碼目前的相機畫面。")
            return
        if self.config.active_provider == "custom" and not self.config.providers["custom"].base_url.strip():
            self.statusBar().showMessage("請在「設定」中輸入自訂供應商的基礎網址。", 10000)
            return
        try:
            provider = create_provider(self.config)
        except Exception as exc:
            self.statusBar().showMessage(f"無法啟用 AI 供應商：{exc}", 10000)
            return
        # History shows 64x48 icons; storing the full photo made every refresh decode 200 big JPEGs.
        thumb = image.scaled(160, 120, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self._pending_thumb = image_to_jpeg(thumb) or b""
        self._pending_barcode = barcode or ""
        self._pending_provider = self.config.active_provider
        worker = IdentifyWorker(provider, jpeg_bytes, self.config.providers[self.config.active_provider].api_key, barcode=barcode, parent=self)
        worker.succeeded.connect(self._identification_succeeded)
        worker.failed.connect(self._identification_failed)
        worker.finished.connect(self._worker_finished)
        self._worker = worker
        self.identify_button.setEnabled(False)
        self.result_label.setText("辨識中…")
        self.detection_state_label.setText("辨識中…")
        source = "手動辨識" if manual else "自動辨識"
        self.statusBar().showMessage(f"正在將影像傳送至 {PROVIDER_NAMES.get(self._pending_provider, self._pending_provider)}（{source}）…")
        worker.start()

    def _record_success(self, product: ProductResult) -> None:
        try:
            self.history_store.add_success(product, self._pending_thumb, self._pending_barcode, self._pending_provider, self.config.general.max_history)
            self._refresh_history()
        except OSError as exc:
            self.statusBar().showMessage(f"無法儲存辨識紀錄：{exc}", 5000)

    def _identification_succeeded(self, product: ProductResult) -> None:
        self._session_calls += 1
        parts = [part for part in (product.name_zh, product.name_en) if part]
        if product.brand and product.brand not in parts:
            parts.append(product.brand)
        if product.model and product.model not in parts:
            parts.append(product.model)
        summary = " · ".join(parts) or product.query_zh
        if product.msrp_estimate:
            summary += f"\nAI 估價：{product.msrp_estimate}"
        self.result_label.setText(summary)
        self.detection_state_label.setText("完成")
        self._record_success(product)
        count = open_search_tabs(product, self.config.search, self.config.general.open_tabs_delay_ms)
        self.statusBar().showMessage(f"已為「{product.query_zh or product.query_en}」開啟 {count} 個搜尋分頁。本次已呼叫 AI {self._session_calls} 次。")

    def _identification_failed(self, message: str) -> None:
        self._session_calls += 1
        self.result_label.setText("辨識失敗。請檢查 API 金鑰或網路連線後再試。")
        self.detection_state_label.setText(MOTION_LABELS[MotionState.IDLE] if self._auto_detection_enabled else "已停止")
        try:
            self.history_store.add_failure(message, self._pending_thumb, self._pending_barcode, self._pending_provider, self.config.general.max_history)
            self._refresh_history()
        except OSError as exc:
            self.statusBar().showMessage(f"無法儲存辨識紀錄：{exc}", 5000)
        detail = f"詳細資訊：{message}。" if message else ""
        self.statusBar().showMessage(f"辨識失敗。{detail}本次已呼叫 AI {self._session_calls} 次。", 12000)

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
                    title += f"\nAI 估價：{entry.msrp_estimate}"
            else:
                title = f"辨識失敗\n{entry.error[:100]}"
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            status = "成功" if entry.status == "success" else "失敗"
            item.setToolTip(f"{entry.timestamp} · {PROVIDER_NAMES.get(entry.provider, entry.provider)} · {status}")
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
        self.statusBar().showMessage(f"已為「{entry.query_zh or entry.query_en}」重新開啟 {count} 個搜尋分頁。")

    def _history_context_menu(self, position) -> None:
        item = self.history_list.itemAt(position)
        entry = self._entry_for_item(item)
        if entry is None:
            return
        menu = QMenu(self)
        copy_action = menu.addAction("複製搜尋關鍵字")
        delete_action = menu.addAction("刪除這筆紀錄")
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
        self.detection_state_label.setText("相機已中斷")
        self.statusBar().showMessage(f"相機已中斷，請按「重新整理」以重新連線。詳細資訊：{message}", 10000)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self.camera_view.stop()
        if self._worker is not None:
            self.hide()  # the wait can last the full AI timeout (up to 300 s)
            self._worker.wait()  # destroying a running QThread aborts the app
        super().closeEvent(event)
