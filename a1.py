import vosk, sounddevice as sd, queue, json
import numpy as np

model = vosk.Model(r"C:\Users\Shravani Hajare\.cache\vosk\vosk-model-small-en-us-0.15")
rec = vosk.KaldiRecognizer(model, 16000)
q = queue.Queue()

def callback(indata, frames, time, status):
    # indata is numpy array here (not Raw)
    audio = (indata[:, 0] * 32767).astype(np.int16)
    resampled = np.interp(
        np.linspace(0, len(audio), int(len(audio) * 16000 / 44100)),
        np.arange(len(audio)),
        audio.astype(np.float32)
    ).astype(np.int16)
    q.put(resampled.tobytes())

print("Say something...")
# InputStream (not Raw) gives numpy array directly
with sd.InputStream(samplerate=44100, blocksize=44100, device=1, dtype="float32", channels=1, callback=callback):
    for _ in range(40):
        data = q.get()
        if rec.AcceptWaveform(data):
            result = json.loads(rec.Result())
            print("Heard:", result["text"])
        else:
            partial = json.loads(rec.PartialResult())
            if partial["partial"]:
                print("Partial:", partial["partial"])