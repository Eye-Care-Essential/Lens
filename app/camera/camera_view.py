from __future__ import annotations

from PySide6.QtCore import Qt, QIODevice, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtMultimedia import QCamera, QCameraDevice, QMediaCaptureSession, QVideoFrame, QVideoSink
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class CameraView(QWidget):
    camera_error = Signal(str)
    frame_changed = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._camera: QCamera | None = None
        self._image: QImage | None = None
        self._session = QMediaCaptureSession(self)
        self._sink = QVideoSink(self)
        self._session.setVideoSink(self._sink)
        self._sink.videoFrameChanged.connect(self._on_video_frame)

        self.preview = QLabel("Select a camera to start live preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(480, 320)
        self.preview.setStyleSheet("background: #171a20; color: #d6d8dc; border: 1px solid #454a54;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.preview)

    def set_device(self, device: QCameraDevice | None) -> None:
        if self._camera is not None:
            self._camera.stop()
            self._session.setCamera(None)
            self._camera.deleteLater()
            self._camera = None
        self._image = None
        self.preview.clear()
        self.preview.setText("Select a camera to start live preview" if device is None else "Starting camera…")
        if device is None:
            return

        camera = QCamera(device, self)
        camera.errorOccurred.connect(self._on_camera_error)
        self._camera = camera
        self._session.setCamera(camera)
        camera.start()

    def stop(self) -> None:
        if self._camera is not None:
            self._camera.stop()

    def current_jpeg(self) -> bytes | None:
        return image_to_jpeg(self.current_image())

    def current_image(self) -> QImage | None:
        if self._image is None or self._image.isNull():
            return None
        return self._image.copy()

    def _on_video_frame(self, frame: QVideoFrame) -> None:
        image = frame.toImage()
        if image.isNull():
            return
        self._image = image.copy()
        self.frame_changed.emit(self._image.copy())
        pixmap = QPixmap.fromImage(self._image)
        self.preview.setPixmap(
            pixmap.scaled(
                self.preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        if self._image is not None:
            self.preview.setPixmap(
                QPixmap.fromImage(self._image).scaled(
                    self.preview.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def _on_camera_error(self, _error: object, message: str) -> None:
        clean_message = message.strip() or "Camera could not be opened."
        self.preview.setText(f"Camera unavailable\n{clean_message}")
        self.camera_error.emit(clean_message)


def image_to_jpeg(source: QImage | None) -> bytes | None:
    if source is None or source.isNull():
        return None

    from PySide6.QtCore import QByteArray, QBuffer

    image = source
    if max(image.width(), image.height()) > 1024:
        image = image.scaled(
            1024,
            1024,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    data = QByteArray()
    buffer = QBuffer(data)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        return None
    image.save(buffer, "JPEG", 85)
    buffer.close()
    return bytes(data)
