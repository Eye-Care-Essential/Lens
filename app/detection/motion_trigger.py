from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np


class MotionState(str, Enum):
    IDLE = "IDLE"
    MOTION = "MOTION"
    STABLE = "STABLE…"


@dataclass(frozen=True)
class MotionUpdate:
    state: MotionState
    stable_frame: bool = False
    changed_ratio: float = 0.0


class MotionTrigger:
    """IDLE → MOTION → STABLE trigger driven by downscaled grayscale frames."""

    def __init__(
        self,
        motion_threshold: float = 0.02,
        stable_ms: int = 1000,
        pixel_diff_threshold: int = 24,
    ) -> None:
        self.motion_threshold = motion_threshold
        self.stable_ms = stable_ms
        self.pixel_diff_threshold = pixel_diff_threshold
        self.state = MotionState.IDLE
        self._previous: np.ndarray | None = None
        self._stable_since_ms: int | None = None

    def reset(self, frame: np.ndarray) -> None:
        self._previous = _gray_frame(frame).copy()
        self._stable_since_ms = None
        self.state = MotionState.IDLE

    def update(self, frame: np.ndarray, now_ms: int) -> MotionUpdate:
        current = _gray_frame(frame)
        if self._previous is None or self._previous.shape != current.shape:
            self.reset(current)
            return MotionUpdate(self.state)

        difference = np.abs(current.astype(np.int16) - self._previous.astype(np.int16))
        changed_ratio = float(np.count_nonzero(difference > self.pixel_diff_threshold) / difference.size)
        self._previous = current.copy()
        motion = changed_ratio > self.motion_threshold

        if self.state is MotionState.IDLE:
            if motion:
                self.state = MotionState.MOTION
        elif self.state is MotionState.MOTION:
            if not motion:
                self.state = MotionState.STABLE
                self._stable_since_ms = now_ms
        elif self.state is MotionState.STABLE:
            if motion:
                self.state = MotionState.MOTION
                self._stable_since_ms = None
            elif self._stable_since_ms is not None and now_ms - self._stable_since_ms >= self.stable_ms:
                self.state = MotionState.IDLE
                self._stable_since_ms = None
                return MotionUpdate(MotionState.STABLE, stable_frame=True, changed_ratio=changed_ratio)

        return MotionUpdate(self.state, changed_ratio=changed_ratio)


def _gray_frame(frame: np.ndarray) -> np.ndarray:
    array = np.asarray(frame)
    if array.ndim != 2:
        raise ValueError("MotionTrigger expects a single-channel grayscale frame.")
    if array.dtype != np.uint8:
        array = np.clip(array, 0, 255).astype(np.uint8)
    return array
