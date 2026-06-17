#!/usr/bin/env bash
# Hyprland bindr → tecla SOLTADA → parar y procesar
PID=$(cat /tmp/voice-claude.pid 2>/dev/null)
[ -n "$PID" ] && kill -SIGUSR2 "$PID" 2>/dev/null
