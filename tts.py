import os
import subprocess
import shutil
import sounddevice as sd
import numpy as np
from pathlib import Path

KOKORO_MODEL  = Path.home() / ".local/share/kokoro/kokoro-v1.0.fp16-gpu.onnx"
KOKORO_VOICES = Path.home() / ".local/share/kokoro/voices-v1.0.bin"
KOKORO_VOICE  = "ef_dora"   # voz española femenina; alternativas: em_alex, em_santa

_kokoro = None


def _get_kokoro():
    global _kokoro
    if _kokoro is None:
        from kokoro_onnx import Kokoro
        _kokoro = Kokoro(str(KOKORO_MODEL), str(KOKORO_VOICES))
    return _kokoro


def _speak_kokoro(text: str):
    k = _get_kokoro()
    samples, sr = k.create(text, voice=KOKORO_VOICE, lang="es")
    sd.play(samples, samplerate=sr)
    sd.wait()


def _speak_espeak(text: str):
    for binary in ("espeak-ng", "espeak"):
        if shutil.which(binary):
            subprocess.run([binary, "-s", "145", "-v", "es", text], check=True)
            return


def speak(text: str):
    if not text.strip():
        return
    try:
        _speak_kokoro(text)
    except Exception as e:
        print(f"[TTS kokoro] {e} — usando espeak")
        try:
            _speak_espeak(text)
        except Exception as e2:
            print(f"[TTS] {e2}")


def beep(freq: float = 880.0, duration: float = 0.12, volume: float = 0.4):
    rate = 44100
    t = np.linspace(0, duration, int(rate * duration), endpoint=False)
    fade = int(rate * 0.01)
    wave = np.sin(2 * np.pi * freq * t).astype(np.float32) * volume
    wave[:fade] *= np.linspace(0, 1, fade)
    wave[-fade:] *= np.linspace(1, 0, fade)
    sd.play(wave, samplerate=rate)
