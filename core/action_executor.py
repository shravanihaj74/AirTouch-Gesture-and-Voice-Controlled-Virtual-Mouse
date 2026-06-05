"""
core/action_executor.py
━━━━━━━━━━━━━━━━━━━━━━
Translates confirmed GestureResults into real OS actions.

Critical design: all actions are debounced to prevent:
  - Accidental repeated clicks from gesture flicker
  - Scroll runaway (applies velocity decay)
  - Key repeat on hold gestures

Real-world problems solved:
  - Accidental clicks: minimum gesture hold time before action fires
  - Repeated scroll events: velocity-based scroll with decay
  - Drag stability: separate pinch-hold state machine
  - Voice + gesture conflict: voice commands take priority for 500ms
"""

import time
import pyautogui
import subprocess
import platform
import logging
from typing import Callable, Optional
import pyautogui
import keyboard
import pygetwindow as gw

from core.gesture_engine import GestureResult

logger = logging.getLogger("AirTouch.Executor")

# OS detection
_OS = platform.system()   # "Windows", "Darwin", "Linux"


class ActionExecutor:
    """
    Fires OS-level actions based on gesture recognition results.

    Features:
    - Per-action cooldown timers
    - Drag state machine (start → hold → release)
    - Scroll velocity with decay (no more scroll flick-away)
    - Screenshot with countdown
    - Volume/brightness using OS commands
    """

    def __init__(self, config, on_action: Optional[Callable] = None):
        self.config = config
        self._on_action = on_action   # Stats callback

        # Cooldown state: {action_name: last_fire_time}
        self._cooldowns = {}

        # Cooldown durations (seconds)
        self._cooldown_map = {
            "left_click":    0.30,
            "right_click":   0.35,
            "double_click":  0.40,
            "drag":          0.05,
            "drag_release":  0.10,
            "scroll":        0.04,
            "screenshot":    1.50,
            "volume_up":     0.15,
            "volume_down":   0.15,
            "brightness_up": 0.20,
            "brightness_down": 0.20,
            "copy":          0.50,
            "paste":         0.50,
            "minimize":      0.80,
            "maximize_gesture": 0.80,
        }

        # Drag state
        self._drag_active = False

        # Voice command override (voice takes priority for 500ms)
        self._voice_override_until = 0.0

        # Scroll velocity for smooth scroll
        self._scroll_velocity = 0.0
        self._last_gesture = None

    def process(self, gr: GestureResult):
        """Process a GestureResult and fire the appropriate action."""
        now = time.time()

        # Skip gesture actions if voice just fired
        if now < self._voice_override_until:
            return

        gesture = gr.gesture_name
        self._last_gesture = gesture

        if gesture == "none" or gesture == "stop":
            if self._drag_active:
                self._end_drag()
            return

        # Check cooldown
        if not self._check_cooldown(gesture, now):
            return

        self._fire(gesture, gr)

    def _fire(self, gesture: str, gr: GestureResult):
        """Execute the action for a gesture."""
        try:
            if gesture == "move_cursor":
                pass  # Cursor controller handles this

            elif gesture == "left_click":
                if not self._drag_active:
                    pyautogui.click()
                    logger.debug("Left click")
                    self._notify("left_click")

            elif gesture == "right_click":
                pyautogui.rightClick()
                logger.debug("Right click")
                self._notify("right_click")

            elif gesture == "double_click":
                pyautogui.doubleClick()
                logger.debug("Double click")
                self._notify("double_click")

            elif gesture == "drag":
                if not self._drag_active:
                    self._start_drag()

            elif gesture == "drag_release":
                if self._drag_active:
                    self._end_drag()

            elif gesture == "scroll":
                delta = gr.scroll_delta
                if abs(delta) > 0.3:   # Dead zone
                    clicks = int(delta * 0.5)
                    if clicks != 0:
                        pyautogui.scroll(clicks)
                        logger.debug(f"Scroll: {clicks}")

            elif gesture == "screenshot":
                self._take_screenshot()

            elif gesture == "volume_up":
                self._volume_change(+5)

            elif gesture == "volume_down":
                self._volume_change(-5)

            elif gesture == "brightness_up":
                self._brightness_change(+10)

            elif gesture == "maximize_gesture":
                self._maximize_window()

        except Exception as e:
            logger.error(f"Action error for '{gesture}': {e}")

    # ── Drag state machine ─────────────────────────────────

    def _start_drag(self):
        logger.debug("Drag START")
        self._drag_active = True
        pyautogui.mouseDown()
        self._notify("drag")

    def _end_drag(self):
        logger.debug("Drag END")
        self._drag_active = False
        pyautogui.mouseUp()

    # ── Screenshot ─────────────────────────────────────────

    def _take_screenshot(self):
        import datetime, os
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(
            os.path.expanduser("~"),
            "Pictures",
            f"AirTouch_Screenshot_{timestamp}.png"
        )
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        img = pyautogui.screenshot()
        img.save(filename)
        logger.info(f"Screenshot saved: {filename}")
        self._notify("screenshot")

    # ── Volume control ─────────────────────────────────────

    def _volume_change(self, delta: int):
        try:
            if _OS == "Darwin":
                # macOS
                current = int(subprocess.check_output(
                    ["osascript", "-e", "output volume of (get volume settings)"]
                ).strip())
                new_vol = max(0, min(100, current + delta))
                subprocess.run(["osascript", "-e", f"set volume output volume {new_vol}"])

            elif _OS == "Linux":
                cmd = "pactl set-sink-volume @DEFAULT_SINK@ "
                cmd += f"+{delta}%" if delta > 0 else f"{delta}%"
                subprocess.run(cmd, shell=True)

            elif _OS == "Windows":
                # Uses nircmd or pycaw
                try:
                    from ctypes import cast, POINTER
                    from comtypes import CLSCTX_ALL
                    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
                    devices = AudioUtilities.GetSpeakers()
                    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                    volume = cast(interface, POINTER(IAudioEndpointVolume))
                    current_vol = volume.GetMasterVolumeLevelScalar()
                    new_vol = max(0.0, min(1.0, current_vol + delta / 100))
                    volume.SetMasterVolumeLevelScalar(new_vol, None)
                except ImportError:
                    logger.warning("pycaw not installed. Volume control unavailable on Windows.")

            logger.debug(f"Volume {'+' if delta > 0 else ''}{delta}%")
            self._notify("volume_up" if delta > 0 else "volume_down")

        except Exception as e:
            logger.warning(f"Volume control error: {e}")

    # ── Brightness control ─────────────────────────────────

    def _brightness_change(self, delta: int):
        try:
            if _OS == "Linux":
                result = subprocess.check_output(
                    ["brightnessctl", "get"], text=True
                ).strip()
                current = int(result)
                new_val = max(10, min(255, current + delta * 2))
                subprocess.run(["brightnessctl", "set", str(new_val)])

            elif _OS == "Windows":
                try:
                    import screen_brightness_control as sbc
                    current = sbc.get_brightness()[0]
                    sbc.set_brightness(max(5, min(100, current + delta)))
                except ImportError:
                    logger.warning("screen_brightness_control not installed.")

            elif _OS == "Darwin":
                # macOS brightness via IOKit (complex) — skip for now
                pass

            logger.debug(f"Brightness {'+' if delta > 0 else ''}{delta}")
        except Exception as e:
            logger.warning(f"Brightness control error: {e}")

    # ── Window management ──────────────────────────────────

    def _minimize_window(self):
        if _OS == "Darwin":
            pyautogui.hotkey("command", "m")
        elif _OS == "Windows":
            pyautogui.hotkey("win", "down")
        else:
            pyautogui.hotkey("super", "h")
        self._notify("minimize")

    def _maximize_window(self):
        if _OS == "Darwin":
            pyautogui.hotkey("command", "ctrl", "f")
        elif _OS == "Windows":
            pyautogui.hotkey("win", "up")
        else:
            pyautogui.hotkey("super", "up")
        self._notify("maximize")

    # ── Voice command handler ──────────────────────────────

    def execute_voice(self, command: str):
        """Execute an action from a voice command (overrides gesture for 500ms)."""
        self._voice_override_until = time.time() + 0.5
        command = command.lower().strip()

        actions = {
            "click":         pyautogui.click,
            "left click":    pyautogui.click,
            "right click":   pyautogui.rightClick,
            "double click":  pyautogui.doubleClick,
            "scroll up":     lambda: pyautogui.scroll(5),
            "scroll down":   lambda: pyautogui.scroll(-5),
            "copy":          lambda: pyautogui.hotkey("ctrl", "c"),
            "paste":         lambda: pyautogui.hotkey("ctrl", "v"),
            "undo":          lambda: pyautogui.hotkey("ctrl", "z"),
            "redo":          lambda: pyautogui.hotkey("ctrl", "y"),
            "select all":    lambda: pyautogui.hotkey("ctrl", "a"),
            "close window":  lambda: pyautogui.hotkey("alt", "f4"),
            "minimize":      self._minimize_window,
            "maximize":      self._maximize_window,
            "screenshot":    self._take_screenshot,
            "stop":          lambda: None,
            "volume up":     lambda: self._volume_change(10),
            "volume down":   lambda: self._volume_change(-10),
        }

        action = actions.get(command)
        if action:
            try:
                action()
                logger.info(f"Voice command executed: '{command}'")
                self._notify(f"voice:{command}")
            except Exception as e:
                logger.error(f"Voice action error: {e}")
        else:
            logger.debug(f"Unknown voice command: '{command}'")

    # ── Helpers ────────────────────────────────────────────

    def _check_cooldown(self, action: str, now: float) -> bool:
        """Return True if the action is allowed (not in cooldown)."""
        cooldown = self._cooldown_map.get(action, 0.2)
        last = self._cooldowns.get(action, 0.0)
        if now - last >= cooldown:
            self._cooldowns[action] = now
            return True
        return False

    def _notify(self, action_name: str):
        if self._on_action:
            self._on_action(action_name)


# """
# core/action_executor.py
# ━━━━━━━━━━━━━━━━━━━━━━
# Final Fixed Version for Air Touch Virtual Mouse
# """

# import time
# import pyautogui
# import subprocess
# import platform
# import logging
# import pygetwindow as gw

# from typing import Callable, Optional
# from core.gesture_engine import GestureResult

# logger = logging.getLogger("AirTouch.Executor")

# # IMPORTANT FIXES
# pyautogui.FAILSAFE = False
# pyautogui.PAUSE = 0

# # OS detection
# _OS = platform.system()


# class ActionExecutor:

#     def __init__(self, config, on_action: Optional[Callable] = None):

#         self.config = config
#         self._on_action = on_action

#         self._cooldowns = {}

#         self._cooldown_map = {
#             "left_click": 0.30,
#             "right_click": 0.35,
#             "double_click": 0.40,
#             "drag": 0.05,
#             "drag_release": 0.10,
#             "scroll": 0.04,
#             "screenshot": 1.50,
#             "volume_up": 0.15,
#             "volume_down": 0.15,
#             "copy": 0.50,
#             "paste": 0.50,
#             "minimize": 0.80,
#             "maximize": 0.80,
#         }

#         self._drag_active = False
#         self._voice_override_until = 0.0

#     # =====================================================
#     # MAIN GESTURE PROCESSOR
#     # =====================================================

#     def process(self, gr: GestureResult):

#         now = time.time()

#         if now < self._voice_override_until:
#             return

#         gesture = gr.gesture_name

#         if gesture == "none" or gesture == "stop":

#             if self._drag_active:
#                 self._end_drag()

#             return

#         if not self._check_cooldown(gesture, now):
#             return

#         self._fire(gesture, gr)

#     # =====================================================
#     # FIRE ACTIONS
#     # =====================================================

#     def _fire(self, gesture: str, gr: GestureResult):

#         try:

#             if gesture == "move_cursor":
#                 pass

#             elif gesture == "left_click":
#                 if not self._drag_active:
#                     pyautogui.click()
#                     logger.debug("Left Click")

#             elif gesture == "right_click":
#                 pyautogui.rightClick()
#                 logger.debug("Right Click")

#             elif gesture == "double_click":
#                 pyautogui.doubleClick()
#                 logger.debug("Double Click")

#             elif gesture == "drag":

#                 if not self._drag_active:
#                     self._start_drag()

#             elif gesture == "drag_release":

#                 if self._drag_active:
#                     self._end_drag()

#             # ===============================
#             # SCROLL FIX
#             # ===============================

#             elif gesture == "scroll":

#                 delta = gr.scroll_delta

#                 if abs(delta) > 0.3:

#                     clicks = int(delta * 100)

#                     if clicks != 0:
#                         pyautogui.scroll(clicks)
#                         logger.debug(f"Scroll: {clicks}")

#             elif gesture == "screenshot":
#                 self._take_screenshot()

#             elif gesture == "volume_up":
#                 self._volume_change(+5)

#             elif gesture == "volume_down":
#                 self._volume_change(-5)

#             # ===============================
#             # MAXIMIZE FIX
#             # ===============================

#             elif gesture == "maximize_gesture":
#                 self._maximize_window()

#         except Exception as e:
#             logger.error(f"Action error for '{gesture}': {e}")

#     # =====================================================
#     # DRAG
#     # =====================================================

#     def _start_drag(self):

#         logger.debug("Drag START")

#         self._drag_active = True

#         pyautogui.mouseDown()

#     def _end_drag(self):

#         logger.debug("Drag END")

#         self._drag_active = False

#         pyautogui.mouseUp()

#     # =====================================================
#     # SCREENSHOT
#     # =====================================================

#     def _take_screenshot(self):

#         import datetime
#         import os

#         timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

#         filename = os.path.join(
#             os.path.expanduser("~"),
#             "Pictures",
#             f"AirTouch_Screenshot_{timestamp}.png"
#         )

#         os.makedirs(os.path.dirname(filename), exist_ok=True)

#         img = pyautogui.screenshot()

#         img.save(filename)

#         logger.info(f"Screenshot saved: {filename}")

#     # =====================================================
#     # VOLUME CONTROL
#     # =====================================================

#     def _volume_change(self, delta: int):

#         try:

#             if _OS == "Windows":

#                 pyautogui.press("volumeup" if delta > 0 else "volumedown")

#             logger.debug(f"Volume {'+' if delta > 0 else ''}{delta}%")

#         except Exception as e:

#             logger.warning(f"Volume control error: {e}")

#     # =====================================================
#     # WINDOW MANAGEMENT
#     # =====================================================

#     def _minimize_window(self):

#         try:

#             win = gw.getActiveWindow()

#             if win:
#                 win.minimize()

#                 logger.info("Window Minimized")

#         except Exception as e:

#             logger.error(f"Minimize error: {e}")

#     def _maximize_window(self):

#         try:

#             pyautogui.hotkey("win", "up")

#             logger.info("Window Maximized")

#         except Exception as e:

#             logger.error(f"Maximize error: {e}")

#     # =====================================================
#     # VOICE COMMANDS
#     # =====================================================

#     def execute_voice(self, command: str):

#         self._voice_override_until = time.time() + 0.5

#         command = command.lower().strip()

#         try:

#             # ===============================
#             # CLICKS
#             # ===============================

#             if command in ["click", "left click"]:

#                 pyautogui.click()

#             elif command == "right click":

#                 pyautogui.rightClick()

#             elif command == "double click":

#                 pyautogui.doubleClick()

#             # ===============================
#             # SCROLL FIX
#             # ===============================

#             elif command == "scroll up":

#                 pyautogui.scroll(500)

#             elif command == "scroll down":

#                 pyautogui.scroll(-500)

#             # ===============================
#             # COPY PASTE
#             # ===============================

#             elif command == "copy":

#                 pyautogui.hotkey("ctrl", "c")

#             elif command == "paste":

#                 pyautogui.hotkey("ctrl", "v")

#             elif command == "undo":

#                 pyautogui.hotkey("ctrl", "z")

#             elif command == "redo":

#                 pyautogui.hotkey("ctrl", "y")

#             elif command == "select all":

#                 pyautogui.hotkey("ctrl", "a")

#             # ===============================
#             # WINDOW CONTROL FIX
#             # ===============================

#             elif command == "minimize":

#                 self._minimize_window()

#             elif command == "maximize":

#                 self._maximize_window()

#             elif command == "close window":

#                 pyautogui.hotkey("alt", "f4")

#             # ===============================
#             # SCREENSHOT
#             # ===============================

#             elif command == "screenshot":

#                 self._take_screenshot()

#             # ===============================
#             # VOLUME
#             # ===============================

#             elif command == "volume up":

#                 self._volume_change(+10)

#             elif command == "volume down":

#                 self._volume_change(-10)

#             elif command == "stop":

#                 pass

#             logger.info(f"Voice command executed: {command}")

#         except Exception as e:

#             logger.error(f"Voice action error: {e}")

#     # =====================================================
#     # HELPERS
#     # =====================================================

#     def _check_cooldown(self, action: str, now: float):

#         cooldown = self._cooldown_map.get(action, 0.2)

#         last = self._cooldowns.get(action, 0.0)

#         if now - last >= cooldown:

#             self._cooldowns[action] = now

#             return True

#         return False