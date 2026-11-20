from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox


def show_message(parent, icon: QMessageBox.Icon, title: str, message: str) -> None:
    dialog = QMessageBox(icon, title, message, QMessageBox.StandardButton.Ok, parent)
    dialog.setTextFormat(Qt.TextFormat.PlainText)
    dialog.button(QMessageBox.StandardButton.Ok).setText("確定")
    dialog.exec()
