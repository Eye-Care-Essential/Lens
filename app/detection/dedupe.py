from __future__ import annotations

import numpy as np


class DedupeFilter:
    """Perceptual dHash filter for auto-triggered frames."""

    def __init__(self, max_hamming_distance: int = 6) -> None:
        self.max_hamming_distance = max_hamming_distance
        self.last_hash: int | None = None

    def distance(self, frame: np.ndarray) -> int | None:
        if self.last_hash is None:
            return None
        return (self.last_hash ^ difference_hash(frame)).bit_count()

    def is_duplicate(self, frame: np.ndarray) -> bool:
        distance = self.distance(frame)
        return distance is not None and distance <= self.max_hamming_distance

    def remember(self, frame: np.ndarray) -> None:
        self.last_hash = difference_hash(frame)


def difference_hash(frame: np.ndarray) -> int:
    gray = np.asarray(frame, dtype=np.uint8)
    if gray.ndim != 2:
        raise ValueError("difference_hash expects a grayscale frame.")
    y_indices = np.linspace(0, gray.shape[0] - 1, 8).round().astype(int)
    x_indices = np.linspace(0, gray.shape[1] - 1, 9).round().astype(int)
    resized = gray[np.ix_(y_indices, x_indices)]
    comparisons = resized[:, 1:] > resized[:, :-1]
    result = 0
    for bit, value in enumerate(comparisons.flatten()):
        if value:
            result |= 1 << bit
    return result


def is_near_background(
    frame: np.ndarray,
    background: np.ndarray,
    pixel_diff_threshold: int = 24,
    changed_ratio_tolerance: float = 0.005,
    mean_diff_tolerance: float = 8.0,
) -> bool:
    current = np.asarray(frame, dtype=np.uint8)
    base = np.asarray(background, dtype=np.uint8)
    if current.shape != base.shape:
        return False
    difference = np.abs(current.astype(np.int16) - base.astype(np.int16))
    changed_ratio = float(np.count_nonzero(difference > pixel_diff_threshold) / difference.size)
    mean_difference = float(np.mean(difference))
    return changed_ratio <= changed_ratio_tolerance and mean_difference <= mean_diff_tolerance
