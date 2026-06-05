# # """
# # voice/voice_listener.py
# # ━━━━━━━━━━━━━━━━━━━━━━
# # Async voice command recognition using SpeechRecognition + Google API
# # (or Vosk for fully offline operation).

# # Design:
# #   - Runs on a daemon thread so it never blocks the vision loop
# #   - Uses phrase_time_limit to prevent hanging on silence
# #   - Debounces identical consecutive commands (prevents echo)
# #   - Supports offline mode via Vosk (optional)

# # Supported commands (case-insensitive):
# #   click, double click, right click, scroll up, scroll down,
# #   copy, paste, undo, redo, select all, close window,
# #   minimize, maximize, screenshot, stop, volume up, volume down
# # """

# # import threading
# # import time
# # import logging
# # from typing import Callable

# # logger = logging.getLogger("AirTouch.Voice")


# # class VoiceListener:
# #     """
# #     Background voice command listener.

# #     Calls the `callback(command_str)` when a recognized phrase matches
# #     a known command. Non-matching speech is silently ignored.
# #     """

# #     COMMANDS = {
# #         "click", "left click", "right click", "double click",
# #         "scroll up", "scroll down",
# #         "copy", "paste", "undo", "redo", "select all",
# #         "close window", "minimize", "maximize",
# #         "screenshot", "stop",
# #         "volume up", "volume down",
# #     }

# #     def __init__(self, config, callback: Callable[[str], None]):
# #         self.config = config
# #         self.callback = callback
# #         self._running = False
# #         self._thread = None
# #         self._last_command = ""
# #         self._last_command_time = 0.0
# #         self._mic_index = config.get("mic_device_index", None)

# #         # Import here so missing library doesn't crash the whole app
# #         try:
# #             import speech_recognition as sr
# #             self._sr = sr
# #             self._recognizer = sr.Recognizer()
# #             # Tune for speed over accuracy
# #             try:
# #                 self._recognizer.energy_threshold = int(config.get("mic_energy_threshold", 300))
# #             except Exception:
# #                 self._recognizer.energy_threshold = 300
# #             self._recognizer.dynamic_energy_threshold = True
# #             self._recognizer.pause_threshold = 0.5  # Shorter pause = faster response
# #         except ImportError:
# #             raise ImportError(
# #                 "SpeechRecognition not installed. Run: pip install SpeechRecognition"
# #             )

# #     def start(self):
# #         """Start the background listening thread."""
# #         self._running = True
# #         self._thread = threading.Thread(
# #             target=self._listen_loop,
# #             name="VoiceListener",
# #             daemon=True
# #         )
# #         self._thread.start()
# #         logger.info("Voice listener started.")

# #     def stop(self):
# #         """Stop the background listening thread."""
# #         self._running = False
# #         if self._thread:
# #             self._thread.join(timeout=2)
# #         logger.info("Voice listener stopped.")

# #     def _listen_loop(self):
# #         """Continuous listen → recognize → dispatch loop."""
# #         sr = self._sr

# #         try:
# #             # Prefer explicit device index if provided; otherwise use default.
# #             if self._mic_index is not None:
# #                 mic = sr.Microphone(device_index=self._mic_index)
# #             else:
# #                 mic = sr.Microphone()
# #         except Exception as e:
# #             logger.error(f"Microphone not available with index {self._mic_index}: {e}")
# #             # Try to enumerate microphones and pick the first available one
# #             try:
# #                 names = sr.Microphone.list_microphone_names()
# #                 logger.info(f"Available microphones: {names}")
# #                 if names:
# #                     for idx in range(len(names)):
# #                         try:
# #                             mic = sr.Microphone(device_index=idx)
# #                             logger.info(f"Using microphone index {idx}: {names[idx]}")
# #                             break
# #                         except Exception:
# #                             continue
# #                     else:
# #                         logger.error("No usable microphone found after enumeration.")
# #                         return
# #                 else:
# #                     return
# #             except Exception as e2:
# #                 logger.error(f"Could not enumerate microphones: {e2}")
# #                 return

# #         with mic as source:
# #             # Calibrate ambient noise once at startup
# #             logger.info("Calibrating microphone noise level (2s)...")
# #             self._recognizer.adjust_for_ambient_noise(source, duration=1)
# #             logger.info("Microphone ready. Say a command.")

# #             while self._running:
# #                 try:
# #                     audio = self._recognizer.listen(
# #                         source,
# #                         timeout=3,
# #                         phrase_time_limit=5,
# #                     )
# #                     self._recognize(audio)

# #                 except sr.WaitTimeoutError:
# #                     logger.debug("Listen timeout: no speech detected")
# #                     pass   # No speech detected — normal
# #                 except sr.UnknownValueError:
# #                     logger.debug("Listen: audio could not be understood (UnknownValueError)")
# #                     pass   # Could not understand audio — normal
# #                 except Exception as e:
# #                     logger.debug(f"Listen error: {e}")
# #                     time.sleep(0.5)

# #     def _recognize(self, audio):
# #         """Attempt to recognize audio and match to known commands."""
# #         sr = self._sr
# #         use_offline = self.config.get("voice_offline_mode", False)
# #         debug_dump = self.config.get("voice_debug_dump", False)

# #         try:
# #             # Log raw audio size to help debug microphone capture issues
# #             try:
# #                 wav = audio.get_wav_data(convert_rate=16000, convert_width=2)
# #                 logger.debug(f"Captured audio bytes: {len(wav)}")
# #                 if debug_dump:
# #                     import datetime, os
# #                     fname = os.path.join(
# #                         os.path.expanduser("~"),
# #                         f"airtouch_debug_audio_{int(time.time())}.wav"
# #                     )
# #                     with open(fname, "wb") as f:
# #                         f.write(wav)
# #                     logger.info(f"Wrote debug audio to: {fname}")
# #             except Exception as e:
# #                 logger.debug(f"Could not extract wav data: {e}")

# #             if use_offline:
# #                 text = self._recognize_offline(audio)
# #             else:
# #                 # Use the existing recognizer instance (keeps thresholds)
# #                 try:
# #                     text = self._recognizer.recognize_google(audio).lower().strip()
# #                 except Exception as e:
# #                     logger.debug(f"Recognize error (online): {e}")
# #                     raise

# #             logger.debug(f"Heard: '{text}'")

# #             # Match to known commands (exact or substring match)
# #             matched = self._match_command(text)
# #             if matched:
# #                 now = time.time()
# #                 # Debounce: same command must wait 1.5s before repeating
# #                 if matched == self._last_command and now - self._last_command_time < 1.5:
# #                     return
# #                 self._last_command = matched
# #                 self._last_command_time = now
# #                 self.callback(matched)

# #         except sr.UnknownValueError:
# #             logger.debug("Recognition raised UnknownValueError (could not understand audio)")
# #             pass
# #         except sr.RequestError as e:
# #             logger.warning(
# #                 f"Speech API error: {e}. "
# #                 "Check internet connection or enable offline mode."
# #             )
# #         except Exception as e:
# #             logger.debug(f"Unhandled recognition exception: {e}")

# #     def _match_command(self, text: str) -> str:
# #         """
# #         Match recognized text to known commands.
# #         Returns the matched command string, or "" if no match.
# #         """
# #         # Direct match
# #         if text in self.COMMANDS:
# #             return text

# #         # Substring match (handles "please click" → "click")
# #         for cmd in sorted(self.COMMANDS, key=len, reverse=True):
# #             if cmd in text:
# #                 return cmd

# #         return ""

# #     def _recognize_offline(self, audio) -> str:
# #         """
# #         Offline recognition using Vosk (requires vosk package + model).
# #         Falls back to Google if vosk not available.
# #         """
# #         try:
# #             import vosk
# #             import json

# #             model_path = self.config.get("vosk_model_path", "vosk-model-small-en-us")
# #             if not hasattr(self, "_vosk_model"):
# #                 self._vosk_model = vosk.Model(model_path)
# #                 self._vosk_rec = vosk.KaldiRecognizer(self._vosk_model, 16000)

# #             wav_data = audio.get_wav_data(convert_rate=16000, convert_width=2)
# #             self._vosk_rec.AcceptWaveform(wav_data)
# #             result = json.loads(self._vosk_rec.Result())
# #             return result.get("text", "").lower()

# #         except Exception as e:
# #             logger.debug(f"Offline recognition failed: {e}. Falling back to Google.")
# #             try:
# #                 return self._recognizer.recognize_google(audio).lower().strip()
# #             except Exception:
# #                 return ""




# """
# voice/voice_listener.py
# ━━━━━━━━━━━━━━━━━━━━━━
# Offline voice command recognition using Vosk.
# No internet required. No Google API. No API keys.

# Setup:
#   1. pip install vosk sounddevice
#   2. Download model from: https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.22.zip
#   3. Extract and set "vosk_model_path" in your config to the folder path.

# Supported commands (case-insensitive):
#   click, double click, right click, scroll up, scroll down,
#   copy, paste, undo, redo, select all, close window,
#   minimize, maximize, screenshot, stop, volume up, volume down
# """

# import threading
# import time
# import logging
# from typing import Callable

# logger = logging.getLogger("AirTouch.Voice")


# class VoiceListener:
#     """
#     Background voice command listener using Vosk (fully offline).

#     Calls callback(command_str) when a recognized phrase matches
#     a known command. Non-matching speech is silently ignored.
#     """

#     COMMANDS = {
#         "click", "left click", "right click", "double click",
#         "scroll up", "scroll down",
#         "copy", "paste", "undo", "redo", "select all",
#         "close window", "minimize", "maximize",
#         "screenshot", "stop",
#         "volume up", "volume down",
#     }

#     def __init__(self, config, callback: Callable[[str], None]):
#         self.config = config
#         self.callback = callback
#         self._running = False
#         self._thread = None
#         self._last_command = ""
#         self._last_command_time = 0.0

#         # Microphone settings
#         self._mic_index = config.get("mic_device_index", None)
#         self._sample_rate = int(config.get("vosk_sample_rate", 16000))

#         # Load Vosk
#         try:
#             import vosk
#             self._vosk = vosk
#         except ImportError:
#             raise ImportError(
#                 "Vosk not installed. Run: pip install vosk"
#             )

#         # Load model
#         model_path = config.get("vosk_model_path", "vosk-model-small-en-us")
#         try:
#             logger.info(f"Loading Vosk model from: {model_path}")
#             self._model = vosk.Model(model_path)
#             logger.info("Vosk model loaded successfully.")
#         except Exception as e:
#             raise RuntimeError(
#                 f"Failed to load Vosk model at '{model_path}'. "
#                 f"Download from https://alphacephei.com/vosk/models — Error: {e}"
#             )

#         # Load sounddevice for mic input
#         try:
#             import sounddevice as sd
#             self._sd = sd
#         except ImportError:
#             raise ImportError(
#                 "sounddevice not installed. Run: pip install sounddevice"
#             )

#     def start(self):
#         """Start the background listening thread."""
#         self._running = True
#         self._thread = threading.Thread(
#             target=self._listen_loop,
#             name="VoiceListener",
#             daemon=True
#         )
#         self._thread.start()
#         logger.info("Vosk voice listener started.")

#     def stop(self):
#         """Stop the background listening thread."""
#         self._running = False
#         if self._thread:
#             self._thread.join(timeout=2)
#         logger.info("Voice listener stopped.")

#     def _listen_loop(self):
#         """Continuous listen → recognize → dispatch loop using sounddevice."""
#         import json
#         import queue

#         q = queue.Queue()
#         recognizer = self._vosk.KaldiRecognizer(self._model, self._sample_rate)

#         def audio_callback(indata, frames, time_info, status):
#             """Called by sounddevice for each audio chunk."""
#             if status:
#                 logger.debug(f"Audio stream status: {status}")
#             q.put(bytes(indata))

#         # List available devices if index is specified but fails
#         try:
#             device_info = self._sd.query_devices(
#                 self._mic_index, kind="input"
#             ) if self._mic_index is not None else self._sd.query_devices(
#                 kind="input"
#             )
#             logger.info(f"Using microphone: {device_info['name']}")
#         except Exception as e:
#             logger.warning(f"Could not query mic device: {e}")
#             logger.info(
#                 "Available input devices:\n" +
#                 str(self._sd.query_devices())
#             )

#         try:
#             with self._sd.RawInputStream(
#                 samplerate=self._sample_rate,
#                 blocksize=8000,          # ~0.5s chunks
#                 device=self._mic_index,
#                 dtype="int16",
#                 channels=1,
#                 callback=audio_callback,
#             ):
#                 logger.info("Microphone open. Listening for commands...")

#                 while self._running:
#                     try:
#                         data = q.get(timeout=1.0)  # 1s timeout so we can check _running
#                     except Exception:
#                         continue  # Queue empty — just loop again

#                     if recognizer.AcceptWaveform(data):
#                         result = json.loads(recognizer.Result())
#                         text = result.get("text", "").strip().lower()
#                         if text:
#                             logger.debug(f"Heard (final): '{text}'")
#                             self._dispatch(text)
#                     else:
#                         # Partial result — useful for low-latency command detection
#                         partial = json.loads(recognizer.PartialResult())
#                         partial_text = partial.get("partial", "").strip().lower()
#                         if partial_text:
#                             logger.debug(f"Partial: '{partial_text}'")
#                             # Fire on partial if it already matches a command
#                             # (gives faster response for short commands like "click")
#                             matched = self._match_command(partial_text)
#                             if matched:
#                                 now = time.time()
#                                 if not (
#                                     matched == self._last_command
#                                     and now - self._last_command_time < 1.5
#                                 ):
#                                     self._last_command = matched
#                                     self._last_command_time = now
#                                     logger.info(f"Command (partial match): '{matched}'")
#                                     self.callback(matched)
#                                     # Reset recognizer so partial doesn't re-fire
#                                     recognizer = self._vosk.KaldiRecognizer(
#                                         self._model, self._sample_rate
#                                     )

#         except self._sd.PortAudioError as e:
#             logger.error(
#                 f"Microphone error: {e}\n"
#                 "Check mic index in config or run without 'mic_device_index' to use default."
#             )
#         except Exception as e:
#             logger.error(f"Voice listener crashed: {e}")

#     def _dispatch(self, text: str):
#         """Match text to a command and fire the callback."""
#         matched = self._match_command(text)
#         if matched:
#             now = time.time()
#             # Debounce: same command must wait 1.5s before repeating
#             if matched == self._last_command and now - self._last_command_time < 1.5:
#                 logger.debug(f"Debounced repeated command: '{matched}'")
#                 return
#             self._last_command = matched
#             self._last_command_time = now
#             logger.info(f"Command fired: '{matched}'")
#             self.callback(matched)

#     def _match_command(self, text: str) -> str:
#         """
#         Match recognized text to known commands.
#         Tries exact match first, then substring (longest first).
#         Returns matched command string or "" if no match.
#         """
#         if text in self.COMMANDS:
#             return text

#         # Longest-first substring match: "please double click now" → "double click"
#         for cmd in sorted(self.COMMANDS, key=len, reverse=True):
#             if cmd in text:
#                 return cmd

#         return ""




"""
voice/voice_listener.py
━━━━━━━━━━━━━━━━━━━━━━
Offline voice command recognition using Vosk.
No internet required. No Google API. No API keys.
"""

import threading
import time
import logging
import numpy as np
from typing import Callable

logger = logging.getLogger("AirTouch.Voice")


class VoiceListener:

    COMMANDS = {
        "click", "left click", "right click", "double click",
        "scroll up", "scroll down",
        "copy", "paste", "undo", "redo", "select all",
        "close window", "minimize", "maximize",
        "screenshot", "stop",
        "volume up", "volume down",
    }

    def __init__(self, config, callback: Callable[[str], None]):
        self.config = config
        self.callback = callback
        self._running = False
        self._thread = None
        self._last_command = ""
        self._last_command_time = 0.0

        self._mic_index = config.get("mic_device_index", 1)
        self._device_rate = 44100
        self._target_rate = 16000

        try:
            import vosk
            self._vosk = vosk
        except ImportError:
            raise ImportError("Vosk not installed. Run: pip install vosk")

        model_path = config.get("vosk_model_path", "vosk-model-small-en-us-0.15")
        try:
            logger.info(f"Loading Vosk model from: {model_path}")
            self._model = vosk.Model(model_path)
            logger.info("Vosk model loaded successfully.")
        except Exception as e:
            raise RuntimeError(f"Failed to load Vosk model at '{model_path}'. Error: {e}")

        try:
            import sounddevice as sd
            self._sd = sd
        except ImportError:
            raise ImportError("sounddevice not installed. Run: pip install sounddevice")

    def start(self):
        self._running = True
        self._thread = threading.Thread(
            target=self._listen_loop,
            name="VoiceListener",
            daemon=True
        )
        self._thread.start()
        logger.info("Vosk voice listener started.")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        logger.info("Voice listener stopped.")

    def _listen_loop(self):
        import queue, json

        q = queue.Queue()
        recognizer = self._vosk.KaldiRecognizer(self._model, self._target_rate)

        def callback(indata, frames, time_info, status):
            # indata is float32 numpy array from InputStream
            audio = (indata[:, 0] * 32767).astype(np.int16)
            # Resample 44100 -> 16000
            resampled = np.interp(
                np.linspace(0, len(audio), int(len(audio) * self._target_rate / self._device_rate)),
                np.arange(len(audio)),
                audio.astype(np.float32)
            ).astype(np.int16)
            q.put(resampled.tobytes())

        logger.info(f"Opening mic device {self._mic_index} at {self._device_rate}Hz...")

        try:
            with self._sd.InputStream(
                samplerate=self._device_rate,
                blocksize=self._device_rate,  # 1 second chunks
                device=self._mic_index,
                dtype="float32",
                channels=1,
                callback=callback,
            ):
                logger.info("Microphone open. Listening for commands...")

                while self._running:
                    try:
                        data = q.get(timeout=1.0)
                    except Exception:
                        continue

                    if recognizer.AcceptWaveform(data):
                        result = json.loads(recognizer.Result())
                        text = result.get("text", "").strip().lower()
                        if text:
                            logger.debug(f"Heard (final): '{text}'")
                            self._dispatch(text)
                    else:
                        partial = json.loads(recognizer.PartialResult())
                        partial_text = partial.get("partial", "").strip().lower()
                        if partial_text:
                            logger.debug(f"Partial: '{partial_text}'")
                            matched = self._match_command(partial_text)
                            if matched:
                                now = time.time()
                                if not (matched == self._last_command and now - self._last_command_time < 1.5):
                                    self._last_command = matched
                                    self._last_command_time = now
                                    logger.info(f"Command (partial): '{matched}'")
                                    self.callback(matched)
                                    # Reset so partial doesn't re-fire
                                    recognizer = self._vosk.KaldiRecognizer(self._model, self._target_rate)

        except Exception as e:
            logger.error(f"Voice listener error: {e}")

    def _dispatch(self, text: str):
        matched = self._match_command(text)
        if matched:
            now = time.time()
            if matched == self._last_command and now - self._last_command_time < 1.5:
                return
            self._last_command = matched
            self._last_command_time = now
            logger.info(f"Command fired: '{matched}'")
            self.callback(matched)

    def _match_command(self, text: str) -> str:
        if text in self.COMMANDS:
            return text
        for cmd in sorted(self.COMMANDS, key=len, reverse=True):
            if cmd in text:
                return cmd
        return ""
