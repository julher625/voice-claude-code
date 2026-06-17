#!/usr/bin/env bash
# Hyprland bind  → tecla PRESIONADA → empezar a grabar
PID=$(cat /tmp/voice-claude.pid 2>/dev/null)
[ -n "$PID" ] && kill -SIGUSR1 "$PID" 2>/dev/null || \
    notify-send "Voice Claude" "El daemon no está corriendo. Espera a que cargue."
