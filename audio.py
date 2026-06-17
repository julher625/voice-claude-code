import sounddevice as sd
import numpy as np
from typing import Callable, Optional

SAMPLE_RATE = 16000
CHANNELS = 1


class VoiceRecorder:
    def __init__(self, amplitude_cb: Optional[Callable[[float], None]] = None):
        self._recording = False
        self._frames = []
        self._stream = None
        self._amplitude_cb = amplitude_cb

    def start(self):
        self._recording = True
        self._frames = []
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            callback=self._callback,
            blocksize=1024,
        )
        self._stream.start()

    def _callback(self, indata, frame_count, time_info, status):
        if self._recording:
            self._frames.append(indata.copy())
            if self._amplitude_cb:
                rms = float(np.sqrt(np.mean(indata ** 2)))
                self._amplitude_cb(min(1.0, rms * 12.0))

    def stop(self) -> np.ndarray | None:
        self._recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        if not self._frames:
            return None
        return np.concatenate(self._frames, axis=0).flatten()
