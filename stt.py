import numpy as np
from faster_whisper import WhisperModel

_model: WhisperModel | None = None


def load_model(model_size: str = "large-v3") -> WhisperModel:
    global _model
    if _model is None:
        _model = WhisperModel(model_size, device="cuda", compute_type="float16")
    return _model


def transcribe(audio: np.ndarray, language: str = "es") -> str:
    model = load_model()
    segments, _ = model.transcribe(
        audio,
        language=language,
        beam_size=10,
        best_of=5,
        temperature=0.0,
        initial_prompt="Conversación en español con Claude Code, asistente de programación:",
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300},
        condition_on_previous_text=False,
    )
    return " ".join(seg.text for seg in segments).strip()
