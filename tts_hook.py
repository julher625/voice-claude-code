#!/usr/bin/env python3
"""
Hook de Stop para Claude Code.
Lee el transcript, extrae el último mensaje del asistente y lo reproduce por TTS.
"""
import json
import sys
import os
import subprocess
from pathlib import Path

MAX_TTS_CHARS = 600

def clean_for_tts(text: str) -> str:
    import re
    text = re.sub(r"```[\s\S]*?```", " [código] ", text)
    text = re.sub(r"`[^`]+`", "", text)
    text = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text)
    text = re.sub(r"#{1,6}\s*", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = text.strip()
    if len(text) > MAX_TTS_CHARS:
        # Trunca en el último punto/signo antes del límite
        cut = text.rfind(".", 0, MAX_TTS_CHARS)
        if cut == -1:
            cut = MAX_TTS_CHARS
        text = text[: cut + 1]
    return text


def is_real_user_message(content) -> bool:
    """Distingue mensajes reales del usuario de tool_results."""
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        return any(c.get("type") not in ("tool_result",) for c in content if isinstance(c, dict))
    return False


def current_turn_assistant_text(transcript_path: str) -> str:
    try:
        with open(transcript_path, "r") as f:
            lines = f.readlines()

        # Encuentra el inicio del turno actual: último mensaje real del usuario
        last_real_user_idx = -1
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = d.get("message", {})
            if msg.get("role") == "user" and is_real_user_message(msg.get("content", [])):
                last_real_user_idx = i

        # Recoge TODOS los textos del asistente desde ese punto (en orden)
        text_parts = []
        search_lines = lines[last_real_user_idx + 1:] if last_real_user_idx >= 0 else lines
        for line in search_lines:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = d.get("message", {})
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content", [])
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "text":
                        text_parts.append(c["text"].strip())
            elif isinstance(content, str):
                text_parts.append(content.strip())
    except Exception as e:
        print(f"[tts_hook] error leyendo transcript: {e}", file=sys.stderr)
        return ""
    return clean_for_tts(" ".join(text_parts))


def main():
    import time
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        sys.exit(0)

    transcript_path = data.get("transcript_path", "")
    if not transcript_path or not Path(transcript_path).exists():
        sys.exit(0)

    text = ""
    for _ in range(20):
        text = current_turn_assistant_text(transcript_path)
        if text:
            break
        time.sleep(0.5)

    if not text:
        sys.exit(0)

    # Llama al TTS usando el venv del proyecto
    script_dir = Path(__file__).parent
    venv_python = script_dir / ".venv" / "bin" / "python"

    cublas = str(script_dir / ".venv/lib/python3.14/site-packages/nvidia/cublas/lib")
    cudart = str(script_dir / ".venv/lib/python3.14/site-packages/nvidia/cuda_runtime/lib")
    env = {
        **os.environ,
        "LD_LIBRARY_PATH": f"{cublas}:{cudart}:{os.environ.get('LD_LIBRARY_PATH', '')}",
    }

    subprocess.run(
        [str(venv_python), "-c",
         f"import tts; tts.speak({repr(text)})"],
        cwd=str(script_dir),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


if __name__ == "__main__":
    main()
