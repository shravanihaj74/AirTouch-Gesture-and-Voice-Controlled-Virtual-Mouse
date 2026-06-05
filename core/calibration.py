"""
core/calibration.py
━━━━━━━━━━━━━━━━━━
Interactive user calibration wizard.

Guides the user to position their hand at 4 corners + center
of their comfortable working area. Maps these to screen corners,
computing per-user offset and scale factors.

Why calibration matters:
  Everyone sits at a different distance from their webcam and holds
  their hand at different heights. Without calibration, the virtual
  mouse works for the developer but feels "shifted" for everyone else.
"""

import cv2
import numpy as np
import time
import pyautogui

from core.hand_tracker import HandTracker


class CalibrationSystem:
    """
    5-point calibration wizard.
    Captures hand positions at screen corners + center,
    then fits an affine transform to map them to screen coords.
    """

    CALIBRATION_POINTS = [
        ("TOP LEFT",     (0.0,  0.0 )),
        ("TOP RIGHT",    (1.0,  0.0 )),
        ("BOTTOM RIGHT", (1.0,  1.0 )),
        ("BOTTOM LEFT",  (0.0,  1.0 )),
        ("CENTER",       (0.5,  0.5 )),
    ]

    def __init__(self, config):
        self.config = config
        self.tracker = HandTracker(config)
        self.screen_w, self.screen_h = pyautogui.size()

    def run(self):
        """
        Run the interactive calibration wizard.
        Opens a fullscreen OpenCV window showing instructions.
        """
        cap = cv2.VideoCapture(self.config.get("camera_index", 0))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        captured_points = []   # Hand positions
        target_points = []     # Corresponding screen positions

        print("\n[Calibration] Starting 5-point calibration wizard.")
        print("  For each position, move your index finger to the indicated")
        print("  corner/center of your WORKING AREA and hold still for 2 seconds.\n")

        for label, screen_norm in self.CALIBRATION_POINTS:
            screen_px = (
                int(screen_norm[0] * self.screen_w),
                int(screen_norm[1] * self.screen_h),
            )
            print(f"  → Point your finger at: {label}  (hold 2 seconds)")

            # Collect frames for 2 seconds
            positions = []
            collect_start = time.time()

            while time.time() - collect_start < 2.5:
                ret, frame = cap.read()
                if not ret:
                    continue
                frame = cv2.flip(frame, 1)
                landmarks, _ = self.tracker.process(frame)

                if landmarks:
                    lm = landmarks.landmark
                    positions.append((lm[8].x, lm[8].y))   # Index tip

                # Show calibration UI
                h, w = frame.shape[:2]
                overlay = frame.copy()
                cv2.putText(overlay, f"CALIBRATION: {label}", (30, 50),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 100), 2)

                elapsed = time.time() - collect_start
                bar_w = int((elapsed / 2.5) * (w - 60))
                cv2.rectangle(overlay, (30, h - 50), (30 + bar_w, h - 20),
                              (0, 255, 100), -1)

                if landmarks:
                    pts = [(int(lm.x * w), int(lm.y * h))
                           for lm in landmarks.landmark]
                    cv2.circle(overlay, pts[8], 12, (0, 100, 255), -1)

                cv2.imshow("Air Touch — Calibration", overlay)
                cv2.waitKey(1)

            if positions:
                # Use median position (robust to outliers)
                avg_x = float(np.median([p[0] for p in positions]))
                avg_y = float(np.median([p[1] for p in positions]))
                captured_points.append((avg_x, avg_y))
                target_points.append(screen_norm)
                print(f"    Captured: ({avg_x:.3f}, {avg_y:.3f})")
            else:
                print(f"    WARNING: No hand detected at {label}. Skipping.")

        cap.release()
        cv2.destroyAllWindows()

        # ── Compute calibration transform ──────────────────
        if len(captured_points) >= 3:
            self._compute_calibration(captured_points, target_points)
        else:
            print("[Calibration] Not enough points. Using defaults.")

    def _compute_calibration(self, captured, targets):
        """Fit simple scale + offset from captured hand pts to screen norm pts."""
        cx = np.array([p[0] for p in captured])
        cy = np.array([p[1] for p in captured])
        tx = np.array([p[0] for p in targets])
        ty = np.array([p[1] for p in targets])

        # Simple linear regression: screen_norm ≈ a * hand_norm + b
        scale_x = float(np.polyfit(cx, tx, 1)[0])
        scale_y = float(np.polyfit(cy, ty, 1)[0])
        offset_x = float(np.mean(tx - scale_x * cx))
        offset_y = float(np.mean(ty - scale_y * cy))

        self.config.set("calibration_scale_x", scale_x)
        self.config.set("calibration_scale_y", scale_y)
        self.config.set("calibration_offset_x", offset_x)
        self.config.set("calibration_offset_y", offset_y)

        print(f"[Calibration] Done.")
        print(f"  Scale: ({scale_x:.3f}, {scale_y:.3f})")
        print(f"  Offset: ({offset_x:.3f}, {offset_y:.3f})")
