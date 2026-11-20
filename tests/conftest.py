import pytest


@pytest.fixture(scope="session")
def qt_application():
    widgets = pytest.importorskip("PySide6.QtWidgets")
    # Qt's GUI and multimedia state is process-wide. Keep the application alive
    # across tests instead of tearing it down and recreating it between windows.
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("QT_QPA_PLATFORM", "offscreen")
        app = widgets.QApplication.instance() or widgets.QApplication([])
        yield app


@pytest.fixture
def qt_app(qt_application):
    from PySide6.QtCore import QEvent

    yield qt_application

    # Destroy test windows and their media sessions before the application exits.
    for widget in qt_application.topLevelWidgets():
        if widget.parent() is None:
            widget.close()
            widget.deleteLater()
    qt_application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
