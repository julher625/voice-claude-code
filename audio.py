import sounddevice as sd
import numpy as np

SAMPLE_RATE = 16000
CHANNELS = 1


class VoiceRecorder:
    def __init__(self):
        self._recording = False
        self._frames = []
        self._stream = None

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

    def stop(self) -> np.ndarray | None:
        self._recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        if not self._frames:
            return None
        return np.concatenate(self._frames, axis=0).flatten()
