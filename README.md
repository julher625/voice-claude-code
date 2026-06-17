# Voice Claude Code

Push-to-talk voice interface for [Claude Code](https://claude.ai/code) on Linux/Wayland.

Speak → Whisper transcribes → text is typed into Claude Code → Claude responds → Kokoro reads the response aloud.

## Architecture

```
Super+Space (hold) → mic recording starts
Super+Space (release) → Whisper STT (GPU) → wtype → Claude Code
                                                         ↓
                                              Claude Code Stop hook
                                                         ↓
                                              tts_hook.py → Kokoro TTS (GPU)
```

## Requirements

### System
- Linux with Wayland (tested on Hyprland)
- `wtype` — Unicode-aware text input for Wayland
- `espeak-ng` — TTS fallback
- `hyprctl` — window focus (Hyprland only)
- NVIDIA GPU with CUDA (tested on RTX 3060, driver CUDA 13.2)

### Python
- Python 3.12+ (tested on 3.14)
- See `requirements.txt`

### Models
Download manually before first run:

```bash
mkdir -p ~/.local/share/kokoro
# Kokoro ONNX GPU model (~170 MB)
wget -O ~/.local/share/kokoro/kokoro-v1.0.fp16-gpu.onnx \
  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.fp16-gpu.onnx
# Voice files (~27 MB)
wget -O ~/.local/share/kokoro/voices-v1.0.bin \
  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
```

Whisper `large-v3` downloads automatically on first run (~3 GB).

## Installation

```bash
git clone https://github.com/julher625/voice-claude-code
cd voice-claude-code

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### CUDA libraries (if not installed system-wide)

The venv installs CUDA libs via pip. `start.sh` sets `LD_LIBRARY_PATH` automatically.

## Setup

### 1. Claude Code Stop hook

Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /path/to/voice-claude-code/tts_hook.py"
          }
        ]
      }
    ]
  }
}
```

### 2. Hyprland keybind (push-to-talk)

Add to your Hyprland config (`~/.config/hypr/hyprland.conf` or a custom lua file):

```lua
-- Push-to-talk: hold Super+Space to record
hl.bind("SUPER",       "Space", hl.exec("/path/to/voice-claude-code/ptt_press.sh"),   { release = false })
hl.bind("SUPER",       "Space", hl.exec("/path/to/voice-claude-code/ptt_release.sh"), { release = true  })
```

Or classic config syntax:
```
bind  = SUPER, Space, exec, /path/to/voice-claude-code/ptt_press.sh
bindr = SUPER, Space, exec, /path/to/voice-claude-code/ptt_release.sh
```

## Usage

Start the daemon **from the Claude Code terminal window** (so it captures that window for focus):

```bash
bash start.sh
```

Then hold `Super+Space` to speak. Release to send.

The daemon writes its PID to `/tmp/voice-claude.pid`.

## Configuration

| File | Purpose |
|------|---------|
| `stt.py` | Change Whisper model (`large-v3`, `large-v3-turbo`, etc.) |
| `tts.py` | Change Kokoro voice (`ef_dora`, `em_alex`, `em_santa`) |
| `tts_hook.py` | Adjust `MAX_TTS_CHARS` (default 600) to control how much is read aloud |
| `start.sh` | Pass `--lang en` or `--model large-v3-turbo` for different language/model |

## TTS Voices (Spanish)

| Voice | Description |
|-------|-------------|
| `ef_dora` | Female (default) |
| `em_alex` | Male |
| `em_santa` | Male (alternate) |

## Notes

- The daemon must be started from the Claude Code terminal so it captures the correct window address for focus (Hyprland only).
- TTS reads up to `MAX_TTS_CHARS` characters of each response to keep playback short.
- The Stop hook waits up to 10 seconds for the transcript to be written before giving up.
