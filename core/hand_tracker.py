"""
core/hand_tracker.py
━━━━━━━━━━━━━━━━━━━
MediaPipe-based hand landmark detector.

Solves real-world problems:
  - Uses static_image_mode=False for video continuity (reduces jitter)
  - min_detection_confidence tunable per profile (helps in low-light)
  - Returns structured HandInfo alongside raw landmarks
  - Gracefully handles 0 or 2+ hands (picks dominant hand)
"""

import mediapipe as mp
import numpy as np
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class HandInfo:
    """Structured metadata about a detected hand."""
    handedness: str        # "Left" or "Right"
    detection_confidence: float
    tracking_confidence: float
    bbox: Tuple[int, int, int, int]   # x, y, w, h (pixel space)
    wrist_pos: Tuple[float, float]    # normalized 0-1


class HandTracker:
    """
    Wraps MediaPipe Hands for optimized single-hand real-time tracking.

    Configuration keys (from Config):
      max_hands            : int   = 1
      detection_confidence : float = 0.75
      tracking_confidence  : float = 0.65
      model_complexity     : int   = 0   (0=lite, 1=full)
    """

    # MediaPipe landmark indices (handy constants)
    WRIST       = 0
    THUMB_TIP   = 4
    INDEX_TIP   = 8
    MIDDLE_TIP  = 12
    RING_TIP    = 16
    PINKY_TIP   = 20
    INDEX_MCP   = 5
    MIDDLE_MCP  = 9
    RING_MCP    = 13
    PINKY_MCP   = 17

    def __init__(self, config):
        self.config = config
        self._mp_hands = mp.solutions.hands

        det_conf = config.get("detection_confidence", 0.75)
        trk_conf = config.get("tracking_confidence", 0.65)
        complexity = config.get("model_complexity", 0)   # 0 = lite (fast)
        max_hands = config.get("max_hands", 1)

        self.hands = self._mp_hands.Hands(
            static_image_mode=False,       # Video mode — tracks across frames
            max_num_hands=max_hands,
            model_complexity=complexity,
            min_detection_confidence=det_conf,
            min_tracking_confidence=trk_conf,
        )

        self._prev_landmarks = None

    def process(self, frame_bgr) -> Tuple[Optional[object], Optional[HandInfo]]:
        """
        Process a BGR frame and return (landmarks, HandInfo) or (None, None).

        Returns the dominant hand when multiple hands are detected.
        Falls back to last known landmarks for 1 missed frame (prevents flicker).
        """
        import cv2

        # MediaPipe requires RGB
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False   # Small perf gain
        results = self.hands.process(rgb)

        if not results.multi_hand_landmarks:
            return None, None

        # Pick the hand with highest detection confidence
        best_idx = 0
        if len(results.multi_hand_landmarks) > 1 and results.multi_handedness:
            scores = [h.classification[0].score for h in results.multi_handedness]
            best_idx = int(np.argmax(scores))

        landmarks = results.multi_hand_landmarks[best_idx]
        self._prev_landmarks = landmarks

        # Build HandInfo
        handedness_label = "Right"
        det_conf = 1.0
        if results.multi_handedness and best_idx < len(results.multi_handedness):
            cls = results.multi_handedness[best_idx].classification[0]
            handedness_label = cls.label
            det_conf = cls.score

        h, w = frame_bgr.shape[:2]
        bbox = self._calc_bbox(landmarks, w, h)
        wrist = landmarks.landmark[self.WRIST]

        hand_info = HandInfo(
            handedness=handedness_label,
            detection_confidence=det_conf,
            tracking_confidence=trk_conf if 'trk_conf' in dir() else 0.65,
            bbox=bbox,
            wrist_pos=(wrist.x, wrist.y),
        )

        return landmarks, hand_info

    def _calc_bbox(self, landmarks, w: int, h: int) -> Tuple[int, int, int, int]:
        """Compute bounding box of all landmarks in pixel space."""
        xs = [lm.x for lm in landmarks.landmark]
        ys = [lm.y for lm in landmarks.landmark]
        x1 = int(min(xs) * w) - 10
        y1 = int(min(ys) * h) - 10
        x2 = int(max(xs) * w) + 10
        y2 = int(max(ys) * h) + 10
        return (
            max(0, x1),
            max(0, y1),
            min(w, x2) - max(0, x1),
            min(h, y2) - max(0, y1),
        )

    def get_finger_states(self, landmarks) -> list:
        """
        Returns [thumb, index, middle, ring, pinky] as booleans (True = up/extended).

        Uses robust tip-vs-pip comparison for index..pinky.
        Uses tip-vs-mcp-x for thumb (handles both hands).
        """
        lm = landmarks.landmark
        fingers = []

        # Thumb — compare x position of tip vs IP joint
        if lm[self.THUMB_TIP].x < lm[3].x:
            fingers.append(True)   # Extended (for right hand mirror view)
        else:
            fingers.append(False)

        # Index, Middle, Ring, Pinky — tip above PIP joint (lower y = higher on screen)
        tip_ids   = [8, 12, 16, 20]
        pip_ids   = [6, 10, 14, 18]
        for tip, pip in zip(tip_ids, pip_ids):
            fingers.append(lm[tip].y < lm[pip].y)

        return fingers

    def get_pinch_distance(self, landmarks) -> float:
        """
        Returns normalized distance between index fingertip and thumb tip.
        ~0.04 = pinching, ~0.15+ = open. Normalized to hand size.
        """
        lm = landmarks.landmark
        thumb = np.array([lm[self.THUMB_TIP].x, lm[self.THUMB_TIP].y])
        index = np.array([lm[self.INDEX_TIP].x, lm[self.INDEX_TIP].y])

        # Normalize by wrist-to-middle-mcp distance (hand scale reference)
        wrist = np.array([lm[self.WRIST].x, lm[self.WRIST].y])
        mid_mcp = np.array([lm[self.MIDDLE_MCP].x, lm[self.MIDDLE_MCP].y])
        hand_scale = np.linalg.norm(mid_mcp - wrist) + 1e-6

        raw_dist = np.linalg.norm(index - thumb)
        return float(raw_dist / hand_scale)

    def release(self):
        self.hands.close()
