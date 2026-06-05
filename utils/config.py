"""
utils/config.py  —  Configuration manager with profile support
utils/logger.py  —  Logging setup
utils/fps_counter.py — Real-time FPS measurement
"""

# ══════════════════════════════════════════════════════════════
# utils/config.py
# ══════════════════════════════════════════════════════════════

import json
import os
from pathlib import Path


class Config:
    """
    Hierarchical configuration with profile support.

    Priority (highest first):
      1. Runtime overrides (set via config.set())
      2. User profile file   (~/.airtouch/profiles/<name>.json)
      3. Default values

    Usage:
        config = Config(profile="default")
        config.get("smoothing_alpha", 0.18)
        config.set("smoothing_alpha", 0.25)
        config.save()
    """

    DEFAULTS = {
        # Camera
        "camera_index": 0,

        # Hand tracking
        "detection_confidence": 0.75,
        "tracking_confidence": 0.65,
        "model_complexity": 0,
        "max_hands": 1,

        # Cursor
        "smoothing_alpha": 0.18,
        "active_zone_margin": 0.20,
        "tremor_threshold": 8.0,
        "speed_boost": 1.4,

        # Calibration
        "calibration_offset_x": 0.0,
        "calibration_offset_y": 0.0,
        "calibration_scale_x": 1.0,
        "calibration_scale_y": 1.0,

        # Low light
        "low_light_threshold": 80,
        "clahe_clip_limit": 2.5,
        "clahe_tile_grid": [8, 8],
        "low_light_gamma": 1.6,

        # Voice
        "voice_enabled": True,
        "voice_offline_mode": True,          # ← change False to True
        "mic_energy_threshold": 300,
        "vosk_model_path": r"C:\Users\Shravani Hajare\.cache\vosk\vosk-model-small-en-us-0.15",  # ← add -0.15 at the end
        "mic_device_index": None,            # ← add this new line

        # Gesture
        "gesture_lock_frames": 6,
        "double_click_interval": 0.45,
        "drag_hold_time": 0.6,

        # Mode
        "mode": "default",
        "debug": False,
    }

    def __init__(self, profile: str = "default"):
        self._profile = profile
        self._data = dict(self.DEFAULTS)
        self._overrides = {}
        self._load_profile(profile)

    def get(self, key: str, default=None):
        """Get config value. Overrides > profile > defaults."""
        if key in self._overrides:
            return self._overrides[key]
        val = self._data.get(key, default)
        return val if val is not None else default

    def set(self, key: str, value):
        """Set a runtime override."""
        self._overrides[key] = value

    def save(self):
        """Persist current settings to the profile file."""
        profile_path = self._get_profile_path(self._profile)
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        merged = {**self._data, **self._overrides}
        with open(profile_path, "w") as f:
            json.dump(merged, f, indent=2)

    def _load_profile(self, name: str):
        path = self._get_profile_path(name)
        if path.exists():
            try:
                with open(path) as f:
                    self._data.update(json.load(f))
            except Exception as e:
                print(f"[Config] Could not load profile '{name}': {e}")

    def _get_profile_path(self, name: str) -> Path:
        return Path.home() / ".airtouch" / "profiles" / f"{name}.json"
