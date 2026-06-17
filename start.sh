#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv/bin/activate"

OLD_PID=$(cat /tmp/voice-claude.pid 2>/dev/null)
if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    kill "$OLD_PID"
    sleep 0.5
fi

CUBLAS="$SCRIPT_DIR/.venv/lib/python3.14/site-packages/nvidia/cublas/lib"
CUDART="$SCRIPT_DIR/.venv/lib/python3.14/site-packages/nvidia/cuda_runtime/lib"
export LD_LIBRARY_PATH="$CUBLAS:$CUDART:$LD_LIBRARY_PATH"

# shellcheck source=/dev/null
source "$VENV"
exec python "$SCRIPT_DIR/main.py" "$@"
