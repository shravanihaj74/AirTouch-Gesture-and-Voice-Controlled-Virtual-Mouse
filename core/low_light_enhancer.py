"""
core/low_light_enhancer.py
━━━━━━━━━━━━━━━━━━━━━━━━━
Adaptive image enhancement for low-light webcam conditions.

Techniques used:
  1. CLAHE (Contrast Limited Adaptive Histogram Equalization)
     — Enhances local contrast without washing out bright areas
  2. Gamma correction
     — Lifts shadows while preserving highlights
  3. Noise reduction (bilateral filter)
     — Removes webcam noise that confuses hand detection

Why this matters:
  Most virtual mouse systems fail in dim rooms because MediaPipe
  loses confidence below ~80 brightness. Our enhancer activates
  automatically only when needed, preserving performance in
  normal conditions.
"""

import cv2
import numpy as np


class LowLightEnhancer:
    """
    Adaptive low-light video frame enhancer.

    Activates automatically when average frame brightness drops
    below the configured threshold.
    """

    def __init__(self, config):
        self.config = config

        # CLAHE setup — applied to L channel of LAB color space
        clip_limit = config.get("clahe_clip_limit", 2.5)
        tile_grid = config.get("clahe_tile_grid", (8, 8))

        self._clahe = cv2.createCLAHE(
            clipLimit=clip_limit,
            tileGridSize=tile_grid
        )

        self._gamma = config.get("low_light_gamma", 1.6)
        self._gamma_lut = self._build_gamma_lut(self._gamma)

        # Cache for brightness estimation (every N frames)
        self._brightness_cache = 100
        self._brightness_frame_count = 0

    def estimate_brightness(self, frame_bgr) -> float:
        """
        Fast brightness estimate using mean of grayscale image.
        Returns 0-255. Values below ~80 = low light.
        """
        # Only compute every 5 frames (expensive on large frames)
        self._brightness_frame_count += 1
        if self._brightness_frame_count % 5 != 0:
            return self._brightness_cache

        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        self._brightness_cache = float(np.mean(gray))
        return self._brightness_cache

    def enhance(self, frame_bgr) -> np.ndarray:
        """
        Enhance a BGR frame for better hand detection in low light.

        Pipeline:
          BGR → LAB → CLAHE on L → Gamma correction → Denoise → BGR
        """
        # Convert to LAB color space
        lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB)
        l_chan, a_chan, b_chan = cv2.split(lab)

        # CLAHE on luminance channel
        l_enhanced = self._clahe.apply(l_chan)

        # Gamma correction on luminance
        l_enhanced = cv2.LUT(l_enhanced, self._gamma_lut)

        # Merge back
        lab_enhanced = cv2.merge([l_enhanced, a_chan, b_chan])
        enhanced = cv2.cvtColor(lab_enhanced, cv2.COLOR_LAB2BGR)

        # Light denoising (bilateral — preserves edges for hand detection)
        enhanced = cv2.bilateralFilter(enhanced, d=5, sigmaColor=50, sigmaSpace=50)

        return enhanced

    def _build_gamma_lut(self, gamma: float) -> np.ndarray:
        """Precompute 8-bit gamma lookup table."""
        inv_gamma = 1.0 / gamma
        table = np.array([
            (i / 255.0) ** inv_gamma * 255
            for i in range(256)
        ], dtype=np.uint8)
        return table
