from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtMultimedia import QCameraDevice, QMediaDevices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.ai.factory import create_provider
from app.camera.camera_view import CameraView, device_id
from app.config import AppConfig, DEFAULT_MODELS, PROVIDER_IDS, SearchSiteConfig
from app.paths import config_path
from app.workers import ConnectionTestWorker

PROVIDER_LABELS = {
    "claude": "Claude",
    "gemini": "Gemini",
    "openai": "OpenAI",
    "custom": "Custom / OpenAI-compatible",
}


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.config = copy.deepcopy(config)
        self.reset_background_requested = False
        self._devices: list[QCameraDevice] = []
        self._current_provider_id = self.config.active_provider
        self._test_worker: ConnectionTestWorker | None = None
        self.setWindowTitle("PriceLens settings")
        self.setModal(True)
        self.resize(820, 650)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_ai_tab(), "AI")
        self.tabs.addTab(self._build_camera_tab(), "Camera")
        self.tabs.addTab(self._build_sites_tab(), "Sites")
        self.tabs.addTab(self._build_detection_tab(), "Detection")
        self.tabs.addTab(self._build_general_tab(), "General")

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.save_button = self.buttons.button(QDialogButtonBox.StandardButton.Save)
        self.cancel_button = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self._accept_settings)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(self.buttons)
        self._load_all_controls()

    def _build_ai_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        form = QFormLayout()
        self.provider_combo = QComboBox()
        for provider_id in PROVIDER_IDS:
            self.provider_combo.addItem(PROVIDER_LABELS[provider_id], provider_id)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setClearButtonEnabled(True)
        self.show_key = QCheckBox("Show key")
        key_row = QHBoxLayout()
        key_row.addWidget(self.api_key, 1)
        key_row.addWidget(self.show_key)
        self.model = QLineEdit()
        self.default_model_button = QPushButton("Default")
        model_row = QHBoxLayout()
        model_row.addWidget(self.model, 1)
        model_row.addWidget(self.default_model_button)
        self.base_url = QLineEdit()
        self.base_url_label = QLabel("Base URL")
        self.timeout = QSpinBox()
        self.timeout.setRange(1, 300)
        self.timeout.setSuffix(" sec")
        form.addRow("Active provider", self.provider_combo)
        form.addRow("API key", key_row)
        form.addRow("Model", model_row)
        form.addRow(self.base_url_label, self.base_url)
        form.addRow("Request timeout", self.timeout)
        outer.addLayout(form)

        test_row = QHBoxLayout()
        self.test_button = QPushButton("Test connection")
        self.test_result = QLabel("")
        self.test_result.setWordWrap(True)
        test_row.addWidget(self.test_button)
        test_row.addWidget(self.test_result, 1)
        outer.addLayout(test_row)
        outer.addStretch(1)

        self.provider_combo.currentIndexChanged.connect(self._provider_changed)
        self.show_key.toggled.connect(self._toggle_key_visibility)
        self.default_model_button.clicked.connect(self._use_default_model)
        self.test_button.clicked.connect(self._test_connection)
        return tab

    def _build_camera_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        form = QFormLayout()
        self.camera_combo = QComboBox()
        self.camera_refresh_button = QPushButton("Refresh devices")
        camera_row = QHBoxLayout()
        camera_row.addWidget(self.camera_combo, 1)
        camera_row.addWidget(self.camera_refresh_button)
        self.resolution_combo = QComboBox()
        self.resolution_combo.addItems(["640x480", "1280x720", "1920x1080"])
        form.addRow("Camera", camera_row)
        form.addRow("Resolution", self.resolution_combo)
        outer.addLayout(form)
        self.camera_preview = CameraView()
        self.camera_preview.preview.setMinimumSize(360, 200)
        self.camera_preview.preview.setMaximumHeight(280)
        outer.addWidget(QLabel("Selected camera preview"))
        outer.addWidget(self.camera_preview, 1)
        self.camera_refresh_button.clicked.connect(self._refresh_devices)
        self.camera_combo.currentIndexChanged.connect(self._preview_selected_camera)
        self.resolution_combo.currentTextChanged.connect(self._preview_selected_camera)
        return tab

    def _build_sites_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        self.secondhand_mode = QCheckBox("Add 二手 to Shopee and Ruten searches")
        outer.addWidget(self.secondhand_mode)
        self.sites_table = QTableWidget(0, 4)
        self.sites_table.setHorizontalHeaderLabels(["Enabled", "Site", "Query", "URL template"])
        self.sites_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.sites_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.sites_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.sites_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        outer.addWidget(self.sites_table, 1)
        test_site_row = QHBoxLayout()
        self.test_site_button = QPushButton("Test open selected site")
        test_site_row.addWidget(self.test_site_button)
        test_site_row.addStretch(1)
        outer.addLayout(test_site_row)
        self.test_site_button.clicked.connect(self._test_selected_site)
        return tab

    def _build_detection_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        form = QFormLayout()
        self.motion_threshold = QDoubleSpinBox()
        self.motion_threshold.setRange(0.001, 1.0)
        self.motion_threshold.setDecimals(3)
        self.motion_threshold.setSingleStep(0.005)
        self.stable_ms = QSpinBox()
        self.stable_ms.setRange(100, 30000)
        self.stable_ms.setSuffix(" ms")
        self.cooldown_ms = QSpinBox()
        self.cooldown_ms.setRange(0, 60000)
        self.cooldown_ms.setSuffix(" ms")
        self.dedupe_hamming = QSpinBox()
        self.dedupe_hamming.setRange(0, 64)
        self.barcode_enabled = QCheckBox("Try to decode a visible barcode")
        self.reset_background_button = QPushButton("Reset background now")
        self.background_message = QLabel("The current preview becomes the empty-scene reference when saved.")
        self.background_message.setWordWrap(True)
        form.addRow("Motion threshold", self.motion_threshold)
        form.addRow("Still time before trigger", self.stable_ms)
        form.addRow("Auto-trigger cooldown", self.cooldown_ms)
        form.addRow("Duplicate distance", self.dedupe_hamming)
        form.addRow("Barcode", self.barcode_enabled)
        outer.addLayout(form)
        outer.addWidget(self.reset_background_button)
        outer.addWidget(self.background_message)
        outer.addStretch(1)
        self.reset_background_button.clicked.connect(self._request_background_reset)
        return tab

    def _build_general_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        form = QFormLayout()
        self.max_history = QSpinBox()
        self.max_history.setRange(1, 10000)
        self.open_tabs_delay = QSpinBox()
        self.open_tabs_delay.setRange(0, 5000)
        self.open_tabs_delay.setSuffix(" ms")
        form.addRow("Maximum history entries", self.max_history)
        form.addRow("Delay between search tabs", self.open_tabs_delay)
        outer.addLayout(form)

        buttons = QHBoxLayout()
        self.export_button = QPushButton("Export config")
        self.import_button = QPushButton("Import config")
        self.open_config_button = QPushButton("Open config folder")
        buttons.addWidget(self.export_button)
        buttons.addWidget(self.import_button)
        buttons.addWidget(self.open_config_button)
        outer.addLayout(buttons)
        self.config_warning = QLabel("Exported config includes API keys. Keep the file private.")
        self.config_warning.setWordWrap(True)
        outer.addWidget(self.config_warning)
        outer.addStretch(1)
        self.export_button.clicked.connect(self._export_config)
        self.import_button.clicked.connect(self._import_config)
        self.open_config_button.clicked.connect(self._open_config_folder)
        return tab

    def _load_all_controls(self) -> None:
        provider_index = self.provider_combo.findData(self.config.active_provider)
        self.provider_combo.blockSignals(True)
        self.provider_combo.setCurrentIndex(max(0, provider_index))
        self.provider_combo.blockSignals(False)
        self._current_provider_id = str(self.provider_combo.currentData())
        self._load_provider_fields(self._current_provider_id)
        self.timeout.setValue(self.config.ai_timeout_sec)
        self._refresh_devices(self.config.camera_device_id)
        self.resolution_combo.setCurrentText(self.config.camera_resolution)
        self.secondhand_mode.setChecked(self.config.search.secondhand_mode)
        self._load_sites()
        detection = self.config.detection
        self.motion_threshold.setValue(detection.motion_threshold)
        self.stable_ms.setValue(detection.stable_ms)
        self.cooldown_ms.setValue(detection.cooldown_ms)
        self.dedupe_hamming.setValue(detection.dedupe_hamming)
        self.barcode_enabled.setChecked(detection.barcode_enabled)
        self.max_history.setValue(self.config.general.max_history)
        self.open_tabs_delay.setValue(self.config.general.open_tabs_delay_ms)

    def _load_provider_fields(self, provider_id: str) -> None:
        provider = self.config.providers[provider_id]
        self.api_key.setText(provider.api_key)
        self.model.setText(provider.model or DEFAULT_MODELS[provider_id])
        self.base_url.setText(provider.base_url)
        is_custom = provider_id == "custom"
        self.base_url_label.setVisible(is_custom)
        self.base_url.setVisible(is_custom)
        self.test_result.clear()

    def _store_provider_fields(self, provider_id: str) -> None:
        provider = self.config.providers[provider_id]
        provider.api_key = self.api_key.text().strip()
        provider.model = self.model.text().strip() or DEFAULT_MODELS[provider_id]
        provider.base_url = self.base_url.text().strip() if provider_id == "custom" else ""

    def _provider_changed(self, index: int) -> None:
        if not hasattr(self, "api_key"):
            return
        self._store_provider_fields(self._current_provider_id)
        provider_id = str(self.provider_combo.itemData(index))
        if provider_id not in PROVIDER_IDS:
            return
        self._current_provider_id = provider_id
        self._load_provider_fields(provider_id)

    def _toggle_key_visibility(self, visible: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        self.api_key.setEchoMode(mode)

    def _use_default_model(self) -> None:
        self.model.setText(DEFAULT_MODELS[self._current_provider_id])

    def _test_connection(self) -> None:
        self._store_provider_fields(self._current_provider_id)
        self.config.active_provider = self._current_provider_id
        try:
            provider = create_provider(self.config)
        except Exception as exc:
            self.test_result.setStyleSheet("color: #b42318;")
            self.test_result.setText(str(exc))
            return
        self._test_worker = ConnectionTestWorker(provider, self)
        self._test_worker.completed.connect(self._connection_test_finished)
        self._test_worker.finished.connect(self._release_test_worker)
        self.test_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        for widget in (self.provider_combo, self.api_key, self.show_key, self.model, self.default_model_button, self.base_url, self.timeout):
            widget.setEnabled(False)
        self.test_result.setStyleSheet("")
        self.test_result.setText("Testing…")
        self._test_worker.start()

    def _connection_test_finished(self, passed: bool, message: str) -> None:
        self.test_result.setStyleSheet("color: #18794e;" if passed else "color: #b42318;")
        self.test_result.setText(("✅ " if passed else "❌ ") + (message or ("Connection succeeded." if passed else "Connection failed.")))

    def _release_test_worker(self) -> None:
        worker = self._test_worker
        self._test_worker = None
        self.test_button.setEnabled(True)
        self.save_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        for widget in (self.provider_combo, self.api_key, self.show_key, self.model, self.default_model_button, self.base_url, self.timeout):
            widget.setEnabled(True)
        if worker is not None:
            worker.deleteLater()

    def _refresh_devices(self, preferred_id: str | None = None) -> None:
        if preferred_id is None:
            current = self.camera_combo.currentData()
            preferred_id = device_id(current) if isinstance(current, QCameraDevice) else self.config.camera_device_id
        self._devices = list(QMediaDevices.videoInputs())
        self.camera_combo.blockSignals(True)
        self.camera_combo.clear()
        for device in self._devices:
            self.camera_combo.addItem(device.description(), device)
        if not self._devices:
            self.camera_combo.addItem("No camera found", "")
            selected = 0
        else:
            selected = next((i for i, device in enumerate(self._devices) if device_id(device) == preferred_id), -1)
            if selected < 0 and preferred_id:
                self.camera_combo.insertItem(0, "Saved camera unavailable", f"__missing__:{preferred_id}")
                selected = 0
            elif selected < 0:
                selected = 0
        self.camera_combo.setCurrentIndex(selected)
        self.camera_combo.blockSignals(False)
        self._preview_selected_camera(selected)

    def _preview_selected_camera(self, *_args) -> None:
        device = self.camera_combo.currentData()
        if not isinstance(device, QCameraDevice):
            device = None
        self.camera_preview.set_device(device, self.resolution_combo.currentText())

    def _load_sites(self) -> None:
        self.sites_table.setRowCount(len(self.config.search.sites))
        for row, site in enumerate(self.config.search.sites):
            enabled = QCheckBox()
            enabled.setChecked(site.enabled)
            self.sites_table.setCellWidget(row, 0, enabled)
            self.sites_table.setItem(row, 1, QTableWidgetItem(site.name))
            query_field = QComboBox()
            query_field.addItem("Traditional Chinese", "zh")
            query_field.addItem("English", "en")
            query_field.setCurrentIndex(0 if site.query_field == "zh" else 1)
            self.sites_table.setCellWidget(row, 2, query_field)
            self.sites_table.setItem(row, 3, QTableWidgetItem(site.url_template))
            self.sites_table.item(row, 1).setFlags(self.sites_table.item(row, 1).flags() & ~Qt.ItemFlag.ItemIsEditable)

    def _collect_sites(self) -> list[SearchSiteConfig]:
        sites = []
        for row, old_site in enumerate(self.config.search.sites):
            enabled = self.sites_table.cellWidget(row, 0)
            query_field = self.sites_table.cellWidget(row, 2)
            template = self.sites_table.item(row, 3).text().strip() if self.sites_table.item(row, 3) else ""
            if not template:
                template = old_site.url_template
            if "{q}" not in template:
                QMessageBox.warning(self, "Invalid URL template", f"{old_site.name} needs a {{q}} placeholder.")
                raise ValueError("Invalid search URL template")
            sites.append(SearchSiteConfig(
                id=old_site.id,
                name=old_site.name,
                enabled=enabled.isChecked(),
                url_template=template,
                query_field=str(query_field.currentData()),
            ))
        return sites

    def _test_selected_site(self) -> None:
        from urllib.parse import quote
        import webbrowser

        row = self.sites_table.currentRow()
        if row < 0:
            row = 0
        if row >= len(self.config.search.sites):
            return
        template = self.sites_table.item(row, 3)
        url_template = template.text().strip() if template else ""
        if "{q}" not in url_template:
            QMessageBox.warning(self, "Invalid URL template", "The URL template needs a {q} placeholder.")
            return
        try:
            webbrowser.open_new_tab(url_template.format(q=quote("iPhone 13", safe="")))
        except Exception as exc:
            QMessageBox.warning(self, "Could not open browser", str(exc))

    def _request_background_reset(self) -> None:
        self.reset_background_requested = True
        self.background_message.setText("Background will reset to the live camera view when Settings is saved.")

    def _collect_config(self) -> AppConfig:
        self._store_provider_fields(self._current_provider_id)
        self.config.active_provider = self._current_provider_id
        self.config.ai_timeout_sec = self.timeout.value()
        device = self.camera_combo.currentData()
        if isinstance(device, QCameraDevice):
            self.config.camera_device_id = device_id(device)
        elif self.camera_combo.currentText() == "Saved camera unavailable":
            self.config.camera_device_id = str(device).removeprefix("__missing__:")
        elif self.camera_combo.currentText() != "No camera found":
            self.config.camera_device_id = ""
        self.config.camera_resolution = self.resolution_combo.currentText()
        self.config.search.secondhand_mode = self.secondhand_mode.isChecked()
        self.config.search.sites = self._collect_sites()
        self.config.detection.motion_threshold = self.motion_threshold.value()
        self.config.detection.stable_ms = self.stable_ms.value()
        self.config.detection.cooldown_ms = self.cooldown_ms.value()
        self.config.detection.dedupe_hamming = self.dedupe_hamming.value()
        self.config.detection.barcode_enabled = self.barcode_enabled.isChecked()
        self.config.general.max_history = self.max_history.value()
        self.config.general.open_tabs_delay_ms = self.open_tabs_delay.value()
        return self.config

    def _export_config(self) -> None:
        try:
            config = self._collect_config()
        except ValueError:
            return
        filename, _ = QFileDialog.getSaveFileName(self, "Export config", "PriceLens-config.json", "JSON files (*.json)")
        if not filename:
            return
        try:
            config.export_to(filename)
            QMessageBox.information(self, "Config exported", "Config exported. The file contains API keys; keep it private.")
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))

    def _import_config(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "Import config", "", "JSON files (*.json)")
        if not filename:
            return
        try:
            self.config = AppConfig.import_from(filename)
            self._load_all_controls()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Import failed", f"Could not import this config file: {exc}")

    def _open_config_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(config_path().parent)))

    def _accept_settings(self) -> None:
        try:
            self.config = self._collect_config()
        except ValueError:
            return
        self.camera_preview.stop()
        super().accept()

    def reject(self) -> None:
        self.camera_preview.stop()
        super().reject()
