from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from app.ai.base import ProductResult, VisionProvider


class IdentifyWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, provider: VisionProvider, jpeg_bytes: bytes, api_key: str, parent=None) -> None:
        super().__init__(parent)
        self._provider = provider
        self._jpeg_bytes = jpeg_bytes
        self._api_key = api_key

    def run(self) -> None:
        try:
            result: ProductResult = self._provider.identify(self._jpeg_bytes)
        except Exception as exc:
            message = str(exc).replace(self._api_key, "[hidden]") if self._api_key else str(exc)
            self.failed.emit(message[:500] or "Identification failed. Please try again.")
            return
        self.succeeded.emit(result)
