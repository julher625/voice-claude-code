#!/usr/bin/env python3
"""
TTS Streamer — watches Claude Code transcripts and reads assistant text aloud
as new blocks appear, without waiting for the Stop hook.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

import tts

SCRIPT_DIR = Path(__file__).parent
CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"
POLL_INTERVAL = 0.3   # seconds between transcript checks
MAX_TTS_CHARS = 600


def clean_for_tts(text: str) -> str:
    text = re.sub(r"```[\s\S]*?```", " [código] ", text)
    text = re.sub(r"`[^`]+`", "", text)
    text = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text)
    text = re.sub(r"#{1,6}\s*", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def truncate(text: str) -> str:
    if len(text) <= MAX_TTS_CHARS:
        return text
    cut = text.rfind(".", 0, MAX_TTS_CHARS)
    if cut == -1:
        cut = MAX_TTS_CHARS
    return text[: cut + 1]


def is_real_user_message(content) -> bool:
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        return any(
            isinstance(c, dict) and c.get("type") not in ("tool_result",)
            for c in content
        )
    return False


def get_active_transcript() -> Path | None:
    """Returns the most recently modified JSONL across all projects."""
    try:
        files = list(CLAUDE_PROJECTS.glob("*/*.jsonl"))
        if not files:
            return None
        return max(files, key=lambda f: f.stat().st_mtime)
    except Exception:
        return None


class TranscriptWatcher:
    def __init__(self):
        self._transcript: Path | None = None
        self._line_count: int = 0
        self._in_turn: bool = True  # ready from the start

    def _reset_for_new_file(self, path: Path):
        self._transcript = path
        try:
            self._line_count = len(path.read_text().splitlines())
        except Exception:
            self._line_count = 0
        self._in_turn = True

    def check(self):
        active = get_active_transcript()
        if active is None:
            return

        if active != self._transcript:
            self._reset_for_new_file(active)

        try:
            lines = active.read_text().splitlines()
        except Exception:
            return

        if len(lines) == self._line_count:
            return  # nothing new

        new_lines = lines[self._line_count:]
        self._line_count = len(lines)

        for line in new_lines:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg = d.get("message", {})
            role = msg.get("role")

            if role == "user" and is_real_user_message(msg.get("content", [])):
                self._in_turn = True
                continue

            if not self._in_turn or role != "assistant":
                continue

            content = msg.get("content", [])
            if not isinstance(content, list):
                continue

            for block in content:
                if not isinstance(block, dict) or block.get("type") != "text":
                    continue
                raw = block["text"].strip()
                if not raw:
                    continue
                cleaned = clean_for_tts(raw)
                to_speak = truncate(cleaned)
                if to_speak:
                    tts.speak(to_speak)


def main():
    print("[tts_streamer] iniciando…", flush=True)
    watcher = TranscriptWatcher()

    # Inicializa con el estado actual del transcript para no releer el pasado
    active = get_active_transcript()
    if active:
        try:
            watcher._transcript = active
            watcher._line_count = len(active.read_text().splitlines())
            print(f"[tts_streamer] sincronizado en línea {watcher._line_count}", flush=True)
        except Exception:
            pass

    while True:
        try:
            watcher.check()
        except Exception as e:
            print(f"[tts_streamer] error: {e}", file=sys.stderr)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
