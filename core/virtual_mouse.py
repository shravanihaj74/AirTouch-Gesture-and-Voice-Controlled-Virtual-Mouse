"""
core/virtual_mouse.py
━━━━━━━━━━━━━━━━━━━━
Central orchestrator for the Air Touch Virtual Mouse system.
Manages the main loop, coordinates all subsystems, and handles
the render pipeline.

Architecture:
  WebcamCapture → LowLightEnhancer → HandTracker → GestureEngine
      → CursorController → ActionExecutor → OverlayRenderer
  VoiceListener (async thread) → ActionExecutor
"""

import cv2
import time
import threading
import numpy as np
from collections import deque

from core.hand_tracker import HandTracker
from core.gesture_engine import GestureEngine
from core.cursor_controller import CursorController
from core.action_executor import ActionExecutor
from core.low_light_enhancer import LowLightEnhancer
from voice.voice_listener import VoiceListener
from utils.fps_counter import FPSCounter
from utils.config import Config


class VirtualMouse:
    """
    Main orchestrator. Runs the real-time gesture-to-action pipeline.

    Key design decisions:
    - Single OpenCV capture thread (most stable approach for webcams)
    - Voice runs on a daemon thread to avoid blocking the vision loop
    - All action execution is debounced to prevent accidental triggers
    - Frame processing is adaptive — skips enhancement when FPS drops
    """

    def __init__(self, config: Config):
        self.config = config
        self.running = False
        self._frame_times = deque(maxlen=60)
        self._latencies = deque(maxlen=60)

        # Session statistics
        self._stats = {
            "start_time": 0,
            "end_time": 0,
            "total_gestures": 0,
            "clicks": 0,
            "voice_commands": 0,
            "avg_fps": 0,
            "avg_latency_ms": 0,
            "duration": 0,
        }

        # Initialize subsystems
        self.tracker = HandTracker(config)
        self.gesture_engine = GestureEngine(config)
        self.cursor = CursorController(config)
        self.executor = ActionExecutor(config, self._on_action)
        self.enhancer = LowLightEnhancer(config)
        self.fps_counter = FPSCounter()

        # Voice listener (optional)
        self.voice = None
        if config.get("voice_enabled", True):
            try:
                self.voice = VoiceListener(config, self._on_voice_command)
            except Exception as e:
                print(f"[Voice] Could not initialize: {e}. Continuing without voice.")

    def _on_action(self, action_name: str):
        """Callback when any action fires — used for statistics."""
        if "click" in action_name.lower():
            self._stats["clicks"] += 1
        self._stats["total_gestures"] += 1

    def _on_voice_command(self, command: str):
        """Callback when a voice command is recognized."""
        self._stats["voice_commands"] += 1
        print(f"[Voice] Command: '{command}'")
        self.executor.execute_voice(command)

    def run(self):
        """Main loop."""
        # Open webcam
        cam_index = self.config.get("camera_index", 0)
        cap = cv2.VideoCapture(cam_index)

        if not cap.isOpened():
            raise RuntimeError(
                f"Cannot open camera {cam_index}. "
                "Check that your webcam is connected and not in use."
            )

        # Configure capture for performance
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, 30)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # Minimize buffer lag

        self.running = True
        self._stats["start_time"] = time.time()

        # Start voice listener in background
        if self.voice:
            self.voice.start()

        print("\n[AirTouch] Camera ready. Show your hand to begin.")
        print("[AirTouch] Gesture Guide:")
        print("  ✌ Index up       → Move cursor")
        print("  👌 Pinch          → Left click")
        print("  ✊ Fist           → Drag")
        print("  🖐 Open palm      → Stop / Release")
        print("  ☝ Two fingers up → Scroll (move up/down)")
        print("  🤙 Thumb + Pinky  → Right click")
        print("  Press Q or ESC to quit.\n")

        mode = self.config.get("mode", "default")
        debug = self.config.get("debug", False)

        while self.running:
            t_start = time.perf_counter()

            ret, frame = cap.read()
            if not ret:
                print("[AirTouch] Frame capture failed. Retrying...")
                time.sleep(0.05)
                continue

            # Flip for mirror effect (natural for users)
            frame = cv2.flip(frame, 1)

            # ── Low-light enhancement (adaptive — only when needed) ──
            brightness = self.enhancer.estimate_brightness(frame)
            if brightness < self.config.get("low_light_threshold", 80):
                frame = self.enhancer.enhance(frame)

            # ── Hand tracking ──
            landmarks, hand_info = self.tracker.process(frame)

            gesture_result = None
            if landmarks:
                # ── Gesture recognition ──
                gesture_result = self.gesture_engine.recognize(landmarks, hand_info)

                # ── Cursor movement ──
                if gesture_result.cursor_point is not None:
                    self.cursor.update(gesture_result.cursor_point)

                # ── Action execution ──
                self.executor.process(gesture_result)

            # ── Overlay rendering ──
            frame = self._render_overlay(frame, landmarks, gesture_result, debug)

            # ── FPS display ──
            fps = self.fps_counter.update()
            self._frame_times.append(fps)
            cv2.putText(
                frame,
                f"FPS: {fps:.0f}  Mode: {mode.upper()}",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                (0, 255, 100), 2
            )

            # Latency tracking
            latency_ms = (time.perf_counter() - t_start) * 1000
            self._latencies.append(latency_ms)

            cv2.imshow("Air Touch Virtual Mouse  [Q / ESC to quit]", frame)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), ord("Q"), 27):  # Q or ESC
                self.running = False

        # Cleanup
        cap.release()
        cv2.destroyAllWindows()
        self._stats["end_time"] = time.time()

    def _render_overlay(self, frame, landmarks, gesture_result, debug: bool):
        """Draw hand skeleton, gesture label, and debug info onto frame."""
        h, w = frame.shape[:2]

        # Draw hand landmarks
        if landmarks:
            self._draw_landmarks(frame, landmarks, w, h)

        # Gesture label box
        if gesture_result and gesture_result.gesture_name != "none":
            confidence = gesture_result.confidence
            label = f"{gesture_result.gesture_name}  {confidence:.0%}"
            color = self._confidence_color(confidence)

            # Background pill
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
            cv2.rectangle(frame, (8, h - 50), (tw + 20, h - 20), (0, 0, 0), -1)
            cv2.putText(
                frame, label,
                (12, h - 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2
            )

        # Debug panel
        if debug and gesture_result:
            self._draw_debug_panel(frame, gesture_result)

        # Mode indicator
        mode = self.config.get("mode", "default")
        mode_colors = {
            "default": (255, 255, 255),
            "gaming": (0, 100, 255),
            "presentation": (0, 200, 100),
            "accessibility": (255, 200, 0),
        }
        cv2.putText(
            frame, f"● {mode.upper()}",
            (w - 180, 30),
            cv2.FONT_HERSHEY_SIMPLEX, 0.65,
            mode_colors.get(mode, (255, 255, 255)), 2
        )

        return frame

    def _draw_landmarks(self, frame, landmarks, w, h):
        """Draw hand skeleton with colored joints."""
        # MediaPipe hand connections
        connections = [
            (0,1),(1,2),(2,3),(3,4),          # Thumb
            (0,5),(5,6),(6,7),(7,8),           # Index
            (0,9),(9,10),(10,11),(11,12),      # Middle
            (0,13),(13,14),(14,15),(15,16),    # Ring
            (0,17),(17,18),(18,19),(19,20),    # Pinky
            (5,9),(9,13),(13,17),              # Palm base
        ]

        pts = [(int(lm.x * w), int(lm.y * h)) for lm in landmarks.landmark]

        # Draw bones
        for a, b in connections:
            cv2.line(frame, pts[a], pts[b], (100, 220, 255), 2)

        # Draw joints
        fingertip_ids = {4, 8, 12, 16, 20}
        for i, pt in enumerate(pts):
            color = (0, 255, 180) if i in fingertip_ids else (255, 255, 255)
            radius = 6 if i in fingertip_ids else 4
            cv2.circle(frame, pt, radius, color, -1)
            cv2.circle(frame, pt, radius + 1, (0, 0, 0), 1)

    def _draw_debug_panel(self, frame, gr):
        """Draw debug info panel (right side)."""
        h, w = frame.shape[:2]
        lines = [
            f"Gesture : {gr.gesture_name}",
            f"Confidence: {gr.confidence:.2f}",
            f"Fingers : {gr.fingers_up}",
            f"Pinch   : {gr.pinch_dist:.3f}",
            f"Locked  : {gr.is_locked}",
        ]
        x = w - 250
        for i, line in enumerate(lines):
            cv2.putText(
                frame, line,
                (x, 60 + i * 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (200, 200, 200), 1
            )

    def _confidence_color(self, confidence: float):
        """Green → Yellow → Red based on confidence."""
        if confidence > 0.8:
            return (0, 255, 100)
        elif confidence > 0.55:
            return (0, 220, 255)
        else:
            return (0, 100, 255)

    def get_session_stats(self) -> dict:
        """Return session statistics."""
        duration = self._stats.get("end_time", time.time()) - self._stats["start_time"]
        avg_fps = float(np.mean(list(self._frame_times))) if self._frame_times else 0
        avg_lat = float(np.mean(list(self._latencies))) if self._latencies else 0
        return {
            **self._stats,
            "duration": duration,
            "avg_fps": avg_fps,
            "avg_latency_ms": avg_lat,
        }

    def cleanup(self):
        """Stop all subsystems cleanly."""
        self.running = False
        if self.voice:
            self.voice.stop()
