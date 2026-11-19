from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QVBoxLayout,
)

from app.config import AppConfig, DEFAULT_GEMINI_MODEL


class GeminiSettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Gemini settings")
        self.setModal(True)

        self.api_key = QLineEdit(config.gemini_api_key)
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("Paste your Gemini API key")
        self.api_key.setClearButtonEnabled(True)
        self.model = QLineEdit(config.gemini_model or DEFAULT_GEMINI_MODEL)
        self.model.setPlaceholderText(DEFAULT_GEMINI_MODEL)
        self.show_key = QCheckBox("Show key")
        self.show_key.toggled.connect(self._toggle_key_visibility)

        key_row = QHBoxLayout()
        key_row.addWidget(self.api_key, 1)
        key_row.addWidget(self.show_key)
        form = QFormLayout()
        form.addRow("Gemini API key", key_row)
        form.addRow("Model", self.model)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.resize(520, 140)

    def _toggle_key_visibility(self, visible: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        self.api_key.setEchoMode(mode)

    def accept(self) -> None:
        if not self.model.text().strip():
            self.model.setText(DEFAULT_GEMINI_MODEL)
        super().accept()
