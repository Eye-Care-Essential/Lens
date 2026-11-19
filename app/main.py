from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.config import AppConfig
from app.paths import config_path
from app.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("PriceLens")
    app.setOrganizationName("PriceLens")
    first_launch = not config_path().exists()
    window = MainWindow(AppConfig.load())
    window.show()
    if first_launch:
        QTimer.singleShot(0, window._run_self_test)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
