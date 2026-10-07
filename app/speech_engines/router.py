"""Choose a speech engine without tying the editor to one provider.

Automatic mode stays on this computer. It never selects the paid cloud
engine, because that uploads the document and can incur charges.

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations


def resolve_provider(requested: str, *, kokoro_ready: bool, piper_ready: bool = True) -> str:
    """Return the engine the user asked for.

    An explicit choice is kept even when its model is not downloaded yet,
    so the interface can offer the download. Automatic uses Kokoro only
    after that model is cached, and otherwise uses Piper. Automatic never
    selects OpenAI and never selects a cloned voice.
    """
    choice = (requested or "piper").strip().lower()
    if choice == "openai":
        return "openai"
    if choice == "kokoro":
        return "kokoro"
    if choice == "piper":
        return "piper"
    if choice == "clone":
        return "clone"
    if choice == "auto":
        if kokoro_ready:
            return "kokoro"
        if piper_ready:
            return "piper"
        return "piper"
    return "piper"


def is_kokoro_voice(voice_id: str) -> bool:
    return (voice_id or "").startswith("kokoro:")


def is_clone_voice(voice_id: str) -> bool:
    return (voice_id or "").startswith("clone:")


def kokoro_voice_name(voice_id: str) -> str:
    value = voice_id or ""
    if value.startswith("kokoro:"):
        return value.split(":", 1)[1]
    return value


def speed_from_length_scale(length_scale: float) -> float:
    """Piper's length scale is the inverse of the reading-speed slider."""
    try:
        scale = float(length_scale)
    except (TypeError, ValueError):
        scale = 1.0
    if scale <= 0:
        return 1.0
    speed = 1.0 / scale
    return max(0.5, min(2.0, speed))
