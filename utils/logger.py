"""
utils/logger.py — Colored console + file logging setup
utils/fps_counter.py — Rolling FPS measurement
"""

import logging
import sys
import time
from collections import deque


# ══════════════════════════════════════════════════════════════
# Logger
# ══════════════════════════════════════════════════════════════

class _ColorFormatter(logging.Formatter):
    COLORS = {
        "DEBUG":    "\033[36m",    # Cyan
        "INFO":     "\033[32m",    # Green
        "WARNING":  "\033[33m",    # Yellow
        "ERROR":    "\033[31m",    # Red
        "CRITICAL": "\033[35m",    # Magenta
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.COLORS.get(record.levelname, "")
        record.levelname = f"{color}{record.levelname:<8}{self.RESET}"
        return super().format(record)


def setup_logger(name: str, level=logging.INFO) -> logging.Logger:
    """Set up a colored console logger + optional file logger."""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        # Console handler
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(level)
        fmt = _ColorFormatter(
            fmt="%(asctime)s  %(levelname)s %(name)s — %(message)s",
            datefmt="%H:%M:%S"
        )
        ch.setFormatter(fmt)
        logger.addHandler(ch)

    return logger


# ══════════════════════════════════════════════════════════════
# FPS Counter
# ══════════════════════════════════════════════════════════════

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
