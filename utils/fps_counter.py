"""
utils/fps_counter.py
━━━━━━━━━━━━━━━━━━━
Rolling-window FPS counter.
"""

import time
from collections import deque


class FPSCounter:
    """
    Efficient rolling-window FPS counter.
    Uses a deque of recent frame timestamps to compute
    instantaneous FPS without per-frame timer overhead.
    """

    def __init__(self, window: int = 30):
        self._timestamps = deque(maxlen=window)

    def update(self) -> float:
        """Call once per frame. Returns current FPS."""
        now = time.perf_counter()
        self._timestamps.append(now)
        if len(self._timestamps) < 2:
            return 0.0
        elapsed = self._timestamps[-1] - self._timestamps[0]
        return (len(self._timestamps) - 1) / max(elapsed, 1e-6)