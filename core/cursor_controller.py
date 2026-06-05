"""
core/cursor_controller.py
━━━━━━━━━━━━━━━━━━━━━━━━
Converts normalized hand landmark coordinates (0-1) to screen
pixel coordinates, with:

  - Adaptive Kalman-like smoothing  (eliminates jitter)
  - Tremor compensation             (filters high-frequency micro-tremors)
  - Active zone mapping             (use center 60% of camera = full screen)
  - Screen edge clamping            (cursor never goes off-screen)
  - Speed-adaptive smoothing        (fast moves = less smooth, slow = more)

Real-world problem solved:
  Existing virtual mice map raw hand position directly to screen,
  causing severe cursor shake. Our adaptive smoother applies more
  aggressive filtering when the hand is nearly still (tremor zone)
  and less when moving fast (intentional movement).
"""

import pyautogui
import numpy as np
from collections import deque

# Prevent PyAutoGUI from throwing FailSafeException when mouse hits corner
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0   # Remove default pause between calls (latency killer)


class CursorController:
    """
    Translates normalized hand position to screen cursor position.

    Config keys:
      smoothing_alpha     : float  = 0.18  (lower = smoother, higher = faster)
      active_zone_margin  : float  = 0.20  (ignore outer 20% of frame)
      tremor_threshold    : float  = 0.008 (below this delta = tremor, filter harder)
      speed_boost         : float  = 1.4   (multiplier for fast movements)
    """

    def __init__(self, config):
        self.config = config

        # Screen resolution (cached once)
        self.screen_w, self.screen_h = pyautogui.size()

        # Active zone — the region of the camera frame mapped to the screen
        # Using center 60% prevents erratic behavior at frame edges
        margin = config.get("active_zone_margin", 0.20)
        self._zone_x1 = margin
        self._zone_x2 = 1.0 - margin
        self._zone_y1 = margin
        self._zone_y2 = 1.0 - margin

        # Smoothing state
        self._alpha = config.get("smoothing_alpha", 0.18)
        self._smoothed_x = None
        self._smoothed_y = None

        # Tremor compensation — rolling position history
        self._pos_history = deque(maxlen=5)

        # Speed detection
        self._prev_raw_x = None
        self._prev_raw_y = None

        # Calibration offsets (set by CalibrationSystem)
        self._offset_x = config.get("calibration_offset_x", 0.0)
        self._offset_y = config.get("calibration_offset_y", 0.0)
        self._scale_x  = config.get("calibration_scale_x", 1.0)
        self._scale_y  = config.get("calibration_scale_y", 1.0)

    def update(self, normalized_point: tuple):
        """
        Move the cursor to match the given normalized hand position (0-1 range).

        Steps:
          1. Apply calibration correction
          2. Map active zone to full screen
          3. Detect speed (fast vs tremor)
          4. Apply adaptive smoothing
          5. Move cursor
        """
        nx, ny = normalized_point

        # Apply calibration offsets
        nx = (nx + self._offset_x) * self._scale_x
        ny = (ny + self._offset_y) * self._scale_y

        # ── Active zone remapping ──────────────────────────
        # Points outside the active zone are clamped to edges
        # Points inside are linearly mapped to full screen
        screen_x = self._remap(nx, self._zone_x1, self._zone_x2, 0, self.screen_w)
        screen_y = self._remap(ny, self._zone_y1, self._zone_y2, 0, self.screen_h)

        # ── Speed detection ────────────────────────────────
        speed = 0.0
        if self._prev_raw_x is not None:
            dx = screen_x - self._prev_raw_x
            dy = screen_y - self._prev_raw_y
            speed = np.sqrt(dx * dx + dy * dy)

        self._prev_raw_x = screen_x
        self._prev_raw_y = screen_y

        # ── Adaptive alpha ─────────────────────────────────
        # When speed is low (near-still hand): reduce alpha → smoother
        # When speed is high (intentional move): increase alpha → more responsive
        tremor_thresh = self.config.get("tremor_threshold", 8.0)  # pixels
        base_alpha = self._alpha

        if speed < tremor_thresh:
            # Tremor zone: apply heavy smoothing
            alpha = base_alpha * 0.4
        elif speed > 60:
            # Fast intentional movement: less lag
            alpha = min(0.6, base_alpha * 2.5)
        else:
            alpha = base_alpha

        # ── Exponential moving average smoothing ──────────
        if self._smoothed_x is None:
            self._smoothed_x = screen_x
            self._smoothed_y = screen_y
        else:
            self._smoothed_x = alpha * screen_x + (1 - alpha) * self._smoothed_x
            self._smoothed_y = alpha * screen_y + (1 - alpha) * self._smoothed_y

        # ── Screen clamping (prevent going off-screen) ────
        final_x = int(np.clip(self._smoothed_x, 0, self.screen_w - 1))
        final_y = int(np.clip(self._smoothed_y, 0, self.screen_h - 1))

        # ── Move cursor ────────────────────────────────────
        # duration=0 for zero-latency movement (pyautogui default adds 0.1s lag!)
        pyautogui.moveTo(final_x, final_y, duration=0)

    def get_position(self) -> tuple:
        """Return current smoothed cursor position."""
        if self._smoothed_x is None:
            return pyautogui.position()
        return (int(self._smoothed_x), int(self._smoothed_y))

    def _remap(self, val: float, in_min: float, in_max: float,
               out_min: float, out_max: float) -> float:
        """Linear remap with clamping."""
        t = (val - in_min) / (in_max - in_min + 1e-8)
        t = max(0.0, min(1.0, t))
        return out_min + t * (out_max - out_min)

    def reset_smoothing(self):
        """Reset smoothing state (call when hand reappears after absence)."""
        self._smoothed_x = None
        self._smoothed_y = None
        self._prev_raw_x = None
        self._prev_raw_y = None
