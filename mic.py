# import sounddevice as sd
# print(sd.query_devices(1))

import sounddevice as sd
import numpy as np

def callback(indata, frames, time, status):
    volume = np.linalg.norm(indata) * 10
    print(f"Volume: {int(volume)} {'█' * int(volume)}")

print("Speak into mic...")
with sd.InputStream(device=1, channels=1, samplerate=44100, callback=callback):
    sd.sleep(5000)