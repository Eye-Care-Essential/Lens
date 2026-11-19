from __future__ import annotations

import unittest

import numpy as np

from app.config import DetectionConfig
from app.detection.dedupe import DedupeFilter
from app.detection.motion_trigger import MotionState
from app.detection.pipeline import AutoDetectionPipeline


def _item_frame(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    tiles = rng.integers(20, 240, size=(8, 9), dtype=np.uint8)
    return np.repeat(np.repeat(tiles, 24, axis=0), 24, axis=1)


class DetectionPipelineAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = DetectionConfig(
            motion_threshold=0.02,
            stable_ms=100,
            cooldown_ms=300,
            dedupe_hamming=6,
        )
        self.pipeline = AutoDetectionPipeline(self.settings)
        self.empty = np.zeros((192, 216), dtype=np.uint8)
        self.pipeline.reset_background(self.empty)

    def _place_item(self, frame: np.ndarray, start_ms: int):
        first = self.pipeline.update(frame, start_ms)
        self.assertEqual(first.state, MotionState.MOTION)
        settling = self.pipeline.update(frame, start_ms + 50)
        self.assertEqual(settling.state, MotionState.STABLE)
        return self.pipeline.update(frame, start_ms + 151)

    def test_five_different_items_trigger_once_each_and_removal_is_ignored(self) -> None:
        self.pipeline.update(self.empty, 0)
        triggers = 0

        for index in range(5):
            item = _item_frame(index + 10)
            item_start = 500 + index * 1200
            update = self._place_item(item, item_start)
            self.assertTrue(update.triggered, update.ignored_reason)
            triggers += 1

            for offset in range(200, 800, 100):
                still = self.pipeline.update(item, item_start + offset)
                self.assertFalse(still.triggered)

        self.assertEqual(triggers, 5)
        removal_time = 500 + 4 * 1200 + 900
        self.assertEqual(self.pipeline.update(self.empty, removal_time).state, MotionState.MOTION)
        self.assertEqual(self.pipeline.update(self.empty, removal_time + 50).state, MotionState.STABLE)
        removal = self.pipeline.update(self.empty, removal_time + 151)
        self.assertFalse(removal.triggered)
        self.assertEqual(removal.ignored_reason, "empty_scene")

    def test_duplicate_filter_skips_a_near_identical_auto_frame(self) -> None:
        original = _item_frame(30)
        changed = original.copy()
        changed[12:16, 12:16] = np.clip(changed[12:16, 12:16].astype(np.int16) + 1, 0, 255).astype(np.uint8)
        dedupe = DedupeFilter(max_hamming_distance=6)
        dedupe.remember(original)
        self.assertTrue(dedupe.is_duplicate(changed))

    def test_cooldown_blocks_a_second_auto_trigger(self) -> None:
        self.pipeline.update(self.empty, 0)
        self.assertTrue(self._place_item(_item_frame(40), 100).triggered)
        cooling = self._place_item(_item_frame(41), 300)
        self.assertFalse(cooling.triggered)
        self.assertEqual(cooling.ignored_reason, "cooldown")


if __name__ == "__main__":
    unittest.main()
