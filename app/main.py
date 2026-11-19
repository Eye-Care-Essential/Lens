from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.config import AppConfig
from app.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("PriceLens")
    app.setOrganizationName("PriceLens")
    window = MainWindow(AppConfig.load())
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
