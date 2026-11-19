from __future__ import annotations

import cv2
import numpy as np


class BarcodeReader:
    """Optional OpenCV barcode decoder; it never blocks product identification."""

    def __init__(self) -> None:
        self._detector = None
        barcode_module = getattr(cv2, "barcode", None)
        detector_type = getattr(barcode_module, "BarcodeDetector", None) if barcode_module else None
        if detector_type is not None:
            try:
                self._detector = detector_type()
            except Exception:
                self._detector = None

    @property
    def available(self) -> bool:
        return self._detector is not None

    def decode(self, bgr_frame: np.ndarray) -> str | None:
        if self._detector is None:
            return None
        try:
            method = getattr(self._detector, "detectAndDecodeWithType", None)
            result = method(bgr_frame) if method is not None else self._detector.detectAndDecode(bgr_frame)
        except Exception:
            return None
        decoded = result
        if isinstance(result, tuple):
            decoded = result[1] if result and isinstance(result[0], (bool, np.bool_)) else result[0]
        if isinstance(decoded, str):
            return decoded.strip() or None
        if isinstance(decoded, (tuple, list, np.ndarray)):
            for value in decoded:
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None
