#!/usr/bin/env python3
"""Voice input daemon for Claude Code.

Escucha SIGUSR1 (empezar a grabar) y SIGUSR2 (parar y transcribir).
Al terminar, escribe el texto en la ventana activa vía ydotool y pulsa Enter
para que Claude Code lo reciba como si fuera texto escrito a mano.
"""

import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import stt
import tts
from audio import VoiceRecorder

PID_FILE  = Path("/tmp/voice-claude.pid")
YDOTOOL   = "/usr/bin/ydotool"
YD_SOCKET = f"/run/user/{os.getuid()}/.ydotool_socket"


def notify(summary: str, body: str = ""):
    try:
        args = ["notify-send", "--app-name=Voice Claude", summary]
        if body:
            args.append(body)
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        pass


WTYPE = "/usr/bin/wtype"
_claude_window_address: str = ""


def get_active_window_address() -> str:
    try:
        import json
        result = subprocess.run(
            ["hyprctl", "activewindow", "-j"],
            capture_output=True, text=True
        )
        return json.loads(result.stdout).get("address", "")
    except Exception:
        return ""


def focus_claude_window():
    if _claude_window_address:
        subprocess.run(
            ["hyprctl", "dispatch",
             f'hl.dsp.focus({{ window = "address:{_claude_window_address}" }})'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        time.sleep(0.15)


def type_text(text: str):
    """Enfoca la ventana de Claude Code y escribe el texto."""
    focus_claude_window()
    env = {**os.environ, "WAYLAND_DISPLAY": os.environ.get("WAYLAND_DISPLAY", "wayland-1")}
    subprocess.run([WTYPE, text], env=env)
    time.sleep(0.05)
    subprocess.run([WTYPE, "-k", "Return"], env=env)


VISUALIZER = Path(__file__).parent / "visualizer.py"


class VoiceApp:
    def __init__(self, lang: str = "es"):
        self.lang = lang
        self.recorder = VoiceRecorder()
        self._recording = False
        self._busy = threading.Event()
        self._visualizer: subprocess.Popen | None = None

    def _send_amplitude(self, amp: float):
        proc = self._visualizer
        if proc and proc.poll() is None:
            try:
                proc.stdin.write(f"{amp:.4f}\n")
                proc.stdin.flush()
            except (BrokenPipeError, OSError):
                self._visualizer = None

    def _launch_visualizer(self):
        # Captura el fondo ANTES de que aparezca el orbe
        bg_path = "/tmp/orb_bg.png"
        try:
            subprocess.run(["grim", bg_path], timeout=2,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            bg_path = None

        try:
            cmd = ["/usr/bin/python3", str(VISUALIZER)]
            if bg_path:
                cmd += ["--bg", bg_path]
            self._visualizer = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except Exception as e:
            print(f"[visualizer] {e}", flush=True)
            self._visualizer = None

    def _kill_visualizer(self):
        proc = self._visualizer
        self._visualizer = None
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    def start_recording(self):
        if self._busy.is_set() or self._recording:
            return
        self._recording = True
        self._launch_visualizer()
        tts.beep(freq=880, duration=0.12)
        notify("🎙 Grabando…", "Suelta Super+Space para enviar")

    def stop_recording(self):
        if not self._recording:
            return
        self._recording = False
        self._kill_visualizer()
        tts.beep(freq=440, duration=0.10)
        audio = self.recorder.stop()

        if audio is None or len(audio) < 3200:
            notify("Voice Claude", "Audio muy corto, ignorado")
            return

        threading.Thread(target=self._process, args=(audio,), daemon=True).start()

    def _process(self, audio):
        self._busy.set()
        try:
            notify("⏳ Transcribiendo…")
            text = stt.transcribe(audio, language=self.lang)

            if not text:
                notify("Voice Claude", "No se detectó voz")
                return

            notify(f"✏️ {text[:80]}")
            type_text(text)
        finally:
            self._busy.clear()

    def run(self, model_size: str):
        global _claude_window_address
        PID_FILE.write_text(str(os.getpid()))
        print(f"Voice Claude daemon — PID {os.getpid()}", flush=True)

        _claude_window_address = get_active_window_address()
        print(f"Ventana Claude Code: {_claude_window_address}", flush=True)

        print("Cargando modelo Whisper…", flush=True)

        # Inicia el recorder aquí para que esté listo
        self.recorder = VoiceRecorder(amplitude_cb=self._send_amplitude)

        stt.load_model(model_size)
        print("Listo. Super+Space para hablar.", flush=True)
        notify("Voice Claude ✓", "Listo — Super+Space para hablar")

        app = self

        def _usr1(sig, frame):
            app.recorder.start()
            app.start_recording()

        def _usr2(sig, frame):
            app.stop_recording()

        def _term(sig, frame):
            PID_FILE.unlink(missing_ok=True)
            sys.exit(0)

        signal.signal(signal.SIGUSR1, _usr1)
        signal.signal(signal.SIGUSR2, _usr2)
        signal.signal(signal.SIGTERM, _term)
        signal.signal(signal.SIGINT, _term)

        try:
            while True:
                time.sleep(1)
        finally:
            PID_FILE.unlink(missing_ok=True)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--lang",  default="es")
    p.add_argument("--model", default="large-v3")
    return p.parse_args()


def main():
    args = parse_args()
    VoiceApp(lang=args.lang).run(args.model)


if __name__ == "__main__":
    main()
