from __future__ import annotations

import cv2
import numpy as np
from PySide6.QtGui import QImage


def qimage_to_bgr(image: QImage) -> np.ndarray:
    converted = image.convertToFormat(QImage.Format.Format_BGR888)
    raw = np.frombuffer(
        converted.constBits(),
        dtype=np.uint8,
        count=converted.sizeInBytes(),
    )
    rows = raw.reshape(converted.height(), converted.bytesPerLine())
    return rows[:, : converted.width() * 3].reshape(converted.height(), converted.width(), 3).copy()


def small_gray_frame(image: QImage, width: int = 320) -> np.ndarray:
    bgr = qimage_to_bgr(image)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    if gray.shape[1] > width:
        height = max(1, round(gray.shape[0] * width / gray.shape[1]))
        gray = cv2.resize(gray, (width, height), interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(gray, (5, 5), 0)
