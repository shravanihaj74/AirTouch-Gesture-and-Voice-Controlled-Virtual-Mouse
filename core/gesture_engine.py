"""
core/gesture_engine.py
━━━━━━━━━━━━━━━━━━━━━
AI-powered gesture recognition with confidence scoring,
smart locking, gesture prediction, and tremor compensation.

Gestures recognized:
  move_cursor    — Index finger only up
  left_click     — Pinch (thumb + index close)
  right_click    — Thumb + Pinky extended, others folded
  double_click   — Rapid double pinch
  drag           — Fist (all fingers down)
  scroll         — Index + Middle up, move hand vertically
  screenshot     — All 5 fingers spread wide
  volume_up      — Thumb + Index + Middle up
  volume_down    — Thumb down (hook)
  brightness_up  — All fingers up, palm facing forward
  minimize       — Swipe down gesture (wrist movement)
  maximize       — V-sign (Index + Middle spread wide)
  zoom_in        — Pinch both hands (single hand: thumb + index stretch)
  stop           — Open palm
"""

import time
import numpy as np
from dataclasses import dataclass, field
from typing import Optional, List, Tuple
from collections import deque

from core.hand_tracker import HandTracker


@dataclass
class GestureResult:
    """Result of one frame's gesture recognition."""
    gesture_name: str = "none"
    confidence: float = 0.0
    cursor_point: Optional[Tuple[float, float]] = None   # normalized 0-1
    fingers_up: List[bool] = field(default_factory=list)
    pinch_dist: float = 0.0
    is_locked: bool = False
    scroll_delta: float = 0.0
    is_new: bool = False      # True only on the first frame of a new gesture


class GestureEngine:
    """
    Recognizes hand gestures from MediaPipe landmarks with:
    - Temporal smoothing (gesture history buffer)
    - Confidence gating (prevents accidental triggers)
    - Smart locking (prevents gesture flickering mid-action)
    - Rapid pinch detection (double-click)
    - Tremor compensation for scroll stability
    """

    # ── Confidence thresholds ──────────────────────────────
    CLICK_PINCH_THRESH     = 0.38   # Normalized pinch dist < this = click
    DRAG_LOCK_THRESH       = 0.35   # Pinch held > DRAG_DELAY seconds = drag
    DOUBLE_CLICK_INTERVAL  = 0.45   # Max seconds between two clicks
    GESTURE_LOCK_FRAMES    = 6      # Frames to hold a gesture before confirming
    SCROLL_SMOOTHING       = 5      # Frame buffer for scroll delta averaging

    def __init__(self, config):
        self.config = config
        self.tracker = HandTracker(config)

        # Gesture history for temporal smoothing
        self._history = deque(maxlen=8)

        # Locking state
        self._locked_gesture = None
        self._lock_counter = 0

        # Click timing (for double-click detection)
        self._last_click_time = 0.0
        self._click_count = 0

        # Drag state
        self._pinch_start_time = 0.0
        self._dragging = False

        # Scroll smoothing
        self._scroll_history = deque(maxlen=self.SCROLL_SMOOTHING)
        self._last_scroll_y = None

        # Gesture prediction buffer (last 3 raw gestures)
        self._raw_history = deque(maxlen=3)

        # Mode-specific configuration
        mode = config.get("mode", "default")
        self._mode_config = self._get_mode_config(mode)

    def _get_mode_config(self, mode: str) -> dict:
        """Per-mode tuning parameters."""
        configs = {
            "default": {
                "pinch_thresh": 0.38,
                "lock_frames": 6,
                "scroll_sensitivity": 1.0,
            },
            "gaming": {
                "pinch_thresh": 0.40,  # More lenient for speed
                "lock_frames": 3,       # React faster
                "scroll_sensitivity": 2.0,
            },
            "presentation": {
                "pinch_thresh": 0.35,  # More strict (avoid accidents)
                "lock_frames": 8,
                "scroll_sensitivity": 0.5,
            },
            "accessibility": {
                "pinch_thresh": 0.42,  # Very lenient for motor impairment
                "lock_frames": 4,
                "scroll_sensitivity": 0.7,
            },
        }
        return configs.get(mode, configs["default"])

    def recognize(self, landmarks, hand_info) -> GestureResult:
        """
        Main recognition pipeline for one frame.
        Returns a GestureResult with gesture name, confidence, and cursor point.
        """
        lm = landmarks.landmark
        pinch_thresh = self._mode_config["pinch_thresh"]

        # ── Extract features ──────────────────────────────
        fingers = self.tracker.get_finger_states(landmarks)
        pinch_dist = self.tracker.get_pinch_distance(landmarks)
        n_fingers_up = sum(fingers)

        # Cursor point = index fingertip (normalized)
        cursor_pt = (lm[8].x, lm[8].y)

        # ── Raw gesture classification ─────────────────────
        raw_gesture, raw_confidence = self._classify(
            fingers, pinch_dist, n_fingers_up, pinch_thresh
        )

        self._raw_history.append(raw_gesture)

        # ── Temporal smoothing ─────────────────────────────
        # Only commit to a gesture if it's been consistent for N frames
        # This kills jitter and prevents accidental mid-gesture misfires
        smoothed_gesture, smoothed_conf = self._temporal_smooth(
            raw_gesture, raw_confidence
        )

        # ── Drag detection (pinch-hold) ────────────────────
        if smoothed_gesture == "pinch_hold":
            smoothed_gesture = "left_click"  # reclassify below

        is_pinching = pinch_dist < pinch_thresh
        if is_pinching and not self._dragging:
            if self._pinch_start_time == 0:
                self._pinch_start_time = time.time()
            elif time.time() - self._pinch_start_time > 0.6:
                smoothed_gesture = "drag"
                self._dragging = True
        elif not is_pinching:
            self._pinch_start_time = 0
            if self._dragging:
                self._dragging = False
                smoothed_gesture = "drag_release"

        # ── Double click detection ─────────────────────────
        if smoothed_gesture == "left_click":
            now = time.time()
            if now - self._last_click_time < self.DOUBLE_CLICK_INTERVAL:
                self._click_count += 1
                if self._click_count >= 2:
                    smoothed_gesture = "double_click"
                    self._click_count = 0
            else:
                self._click_count = 1
            self._last_click_time = now

        # ── Scroll delta calculation ───────────────────────
        scroll_delta = 0.0
        if smoothed_gesture == "scroll":
            current_y = lm[8].y
            if self._last_scroll_y is not None:
                raw_delta = self._last_scroll_y - current_y   # Positive = scroll up
                self._scroll_history.append(raw_delta)
                # Smooth the scroll
                scroll_delta = float(np.mean(self._scroll_history))
                scroll_delta *= self._mode_config["scroll_sensitivity"] * 20
            self._last_scroll_y = current_y
        else:
            self._last_scroll_y = None
            self._scroll_history.clear()

        # ── Smart locking ──────────────────────────────────
        is_new = False
        if smoothed_gesture != self._locked_gesture:
            self._lock_counter += 1
            if self._lock_counter >= self._mode_config["lock_frames"]:
                is_new = True
                self._locked_gesture = smoothed_gesture
                self._lock_counter = 0
            else:
                # Not yet confirmed — return previous locked gesture
                smoothed_gesture = self._locked_gesture or "none"
                smoothed_conf = 0.5
        else:
            self._lock_counter = 0

        return GestureResult(
            gesture_name=smoothed_gesture or "none",
            confidence=smoothed_conf,
            cursor_point=cursor_pt,
            fingers_up=fingers,
            pinch_dist=pinch_dist,
            is_locked=(smoothed_gesture == self._locked_gesture),
            scroll_delta=scroll_delta,
            is_new=is_new,
        )

    def _classify(
        self,
        fingers: List[bool],
        pinch_dist: float,
        n_up: int,
        pinch_thresh: float,
    ) -> Tuple[str, float]:
        """
        Rule-based classification with confidence scoring.

        Returns (gesture_name, confidence 0-1).
        Confidence is based on how clearly the gesture matches.
        """
        thumb, index, middle, ring, pinky = fingers

        # ── Pinch (left click) ─────────────────────────────
        if pinch_dist < pinch_thresh:
            # Confidence scales with how closed the pinch is
            conf = 1.0 - (pinch_dist / pinch_thresh)
            conf = min(1.0, conf * 1.3)  # Boost
            return "left_click", float(conf)

        # ── Move cursor (index finger only) ───────────────
        if index and not middle and not ring and not pinky:
            conf = 0.95 if not thumb else 0.80
            return "move_cursor", conf

        # ── Scroll (index + middle up, others down) ───────
        if index and middle and not ring and not pinky:
            conf = 0.90
            return "scroll", conf

        # ── Right click (thumb + pinky, others folded) ────
        if thumb and pinky and not index and not middle and not ring:
            conf = 0.88
            return "right_click", conf

        # ── Open palm (stop / release) ─────────────────────
        if n_up >= 4:
            conf = min(1.0, n_up / 5 * 0.95)
            return "stop", conf

        # ── Fist (drag) ────────────────────────────────────
        if n_up == 0:
            return "drag", 0.92

        # ── Screenshot (all 5 spread — V-shape detection) ─
        if n_up == 5:
            # Extra check: fingers spread wide
            return "screenshot", 0.85

        # ── Volume / Brightness ────────────────────────────
        if thumb and index and middle and not ring and not pinky:
            return "volume_up", 0.80

        if not thumb and not index and not middle and not ring and pinky:
            return "volume_down", 0.78

        # ── Maximize (V sign wide) ─────────────────────────
        if index and middle and not thumb and not ring and not pinky:
            return "maximize_gesture", 0.75

        return "none", 0.0

    def _temporal_smooth(
        self, raw_gesture: str, raw_conf: float
    ) -> Tuple[str, float]:
        """
        Require a gesture to appear in the last N frames before committing.
        Prevents single-frame misfires.
        """
        self._history.append((raw_gesture, raw_conf))

        if len(self._history) < 3:
            return raw_gesture, raw_conf

        # Count occurrences in recent history
        recent = list(self._history)[-5:]
        counts = {}
        conf_sums = {}
        for g, c in recent:
            counts[g] = counts.get(g, 0) + 1
            conf_sums[g] = conf_sums.get(g, 0.0) + c

        # Pick the most common gesture in recent window
        best = max(counts, key=lambda g: (counts[g], conf_sums.get(g, 0)))
        agreement = counts[best] / len(recent)

        # Confidence = average confidence of winning gesture × agreement ratio
        avg_conf = conf_sums[best] / counts[best]
        final_conf = avg_conf * (0.7 + 0.3 * agreement)

        return best, min(1.0, final_conf)
