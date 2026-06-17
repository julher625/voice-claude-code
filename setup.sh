#!/usr/bin/env bash
set -e

echo "=== Voice Claude Code — Setup ==="

# 1. Dependencias del sistema
echo
echo "→ Instalando dependencias del sistema..."
if command -v pacman &>/dev/null; then
    sudo pacman -S --needed --noconfirm portaudio espeak-ng wget
elif command -v apt-get &>/dev/null; then
    sudo apt-get install -y portaudio19-dev espeak-ng wget
else
    echo "Instala manualmente: portaudio, espeak-ng, wget"
fi

# 2. Entorno virtual Python
echo
echo "→ Creando entorno virtual..."
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

# 3. Paquetes Python
echo
echo "→ Instalando paquetes Python..."
pip install --upgrade pip
pip install -r requirements.txt

# 4. Voz Piper (opcional, alta calidad)
echo
echo "→ Descargando voz Piper en español (opcional)..."
python main.py --download-voice || echo "  (se usará espeak-ng como fallback)"

echo
echo "=== Instalación completada ==="
echo
echo "Para iniciar:"
echo "  source .venv/bin/activate"
echo "  python main.py"
echo
echo "Opciones:"
echo "  --lang en        # Cambiar idioma de transcripción"
echo "  --model medium   # Modelo más ligero (menos preciso)"
