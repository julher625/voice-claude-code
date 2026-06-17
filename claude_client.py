import subprocess


class ClaudeClient:
    """
    Wraps the `claude` CLI. Uses `-p` (print mode) for the first message
    and `--continue -p` for subsequent ones so the conversation persists.
    """

    def __init__(self):
        self._first = True

    def send(self, message: str) -> str:
        cmd = ["claude"]
        if not self._first:
            cmd.append("--continue")
        cmd += ["-p", message]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=180,
            )
            self._first = False
            if result.returncode != 0:
                err = result.stderr.strip() or "error desconocido"
                return f"[Error del CLI] {err}"
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            return "[Error] Tiempo de espera agotado esperando respuesta de Claude."
        except FileNotFoundError:
            return (
                "[Error] No se encontró el CLI 'claude'. "
                "Asegúrate de que Claude Code está instalado y en el PATH."
            )
