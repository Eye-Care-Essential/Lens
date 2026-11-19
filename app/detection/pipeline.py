from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.config import DetectionConfig
from app.detection.dedupe import DedupeFilter, is_near_background
from app.detection.motion_trigger import MotionState, MotionTrigger


@dataclass(frozen=True)
class DetectionUpdate:
    state: MotionState
    triggered: bool = False
    ignored_reason: str | None = None


class AutoDetectionPipeline:
    """Motion detection plus empty-scene, dedupe, and cooldown guards."""

    def __init__(self, settings: DetectionConfig) -> None:
        self.settings = settings
        self.motion = MotionTrigger(settings.motion_threshold, settings.stable_ms)
        self.dedupe = DedupeFilter(settings.dedupe_hamming)
        self.background: np.ndarray | None = None
        self.last_trigger_ms: int | None = None

    def reset_background(self, frame: np.ndarray) -> None:
        background = _copy_gray(frame)
        self.background = background
        self.motion.reset(background)

    def update(self, frame: np.ndarray, now_ms: int) -> DetectionUpdate:
        gray = _copy_gray(frame)
        if self.background is None:
            self.reset_background(gray)
            return DetectionUpdate(MotionState.IDLE)
        if gray.shape != self.background.shape:
            self.reset_background(gray)
            return DetectionUpdate(MotionState.IDLE, ignored_reason="background_reset")

        motion_update = self.motion.update(gray, now_ms)
        if not motion_update.stable_frame:
            return DetectionUpdate(motion_update.state)

        if is_near_background(gray, self.background):
            return DetectionUpdate(MotionState.STABLE, ignored_reason="empty_scene")
        if self.dedupe.is_duplicate(gray):
            return DetectionUpdate(MotionState.STABLE, ignored_reason="duplicate")
        if (
            self.last_trigger_ms is not None
            and now_ms - self.last_trigger_ms < self.settings.cooldown_ms
        ):
            return DetectionUpdate(MotionState.STABLE, ignored_reason="cooldown")

        self.last_trigger_ms = now_ms
        self.dedupe.remember(gray)
        return DetectionUpdate(MotionState.STABLE, triggered=True)


def _copy_gray(frame: np.ndarray) -> np.ndarray:
    gray = np.asarray(frame)
    if gray.ndim != 2:
        raise ValueError("AutoDetectionPipeline expects a grayscale frame.")
    if gray.dtype != np.uint8:
        gray = np.clip(gray, 0, 255).astype(np.uint8)
    return gray.copy()
