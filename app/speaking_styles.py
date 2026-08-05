"""Speaking-style presets shared by the UI and the OpenAI provider.

A *speaking style* is a named delivery (calm, newscaster, cheerful...) that maps
to a natural-language ``instructions`` string understood by OpenAI's
``gpt-4o-mini-tts`` model. The same presets drive the UI dropdown (localized
labels) and export, so a document reads identically live and on disk.

Piper has no instruction channel, so styles are a no-op there; the UI hides the
control for offline voices. Instruction text is intentionally in English (the
model follows English delivery directions regardless of the spoken language).

Presets are data, not behaviour, so they are trivially unit-testable and can be
extended without touching the bridge.

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

from typing import Dict, List, Optional, TypedDict

__all__ = (
    "DEFAULT_STYLE",
    "STYLES",
    "all_presets",
    "get",
    "instruction_for",
    "is_valid",
)


class Preset(TypedDict):
    id: str
    label_en: str
    label_fr: str
    instructions: str


DEFAULT_STYLE = "neutral"


# Order here is the order shown in the UI dropdown.
STYLES: Dict[str, Preset] = {
    "neutral": {
        "id": "neutral",
        "label_en": "Neutral",
        "label_fr": "Neutre",
        "instructions": "",
    },
    "narration": {
        "id": "narration",
        "label_en": "Narration",
        "label_fr": "Narration",
        "instructions": (
            "Speak like a professional audiobook narrator: warm, measured pace, "
            "clear articulation, with natural pauses at punctuation."
        ),
    },
    "newscaster": {
        "id": "newscaster",
        "label_en": "Newscaster",
        "label_fr": "Présentateur",
        "instructions": (
            "Speak like a broadcast news anchor: confident, authoritative, "
            "crisp diction and a steady, even cadence."
        ),
    },
    "cheerful": {
        "id": "cheerful",
        "label_en": "Cheerful",
        "label_fr": "Enjoué",
        "instructions": (
            "Speak in a bright, upbeat and friendly tone, with lively energy "
            "and a smile in the voice."
        ),
    },
    "calm": {
        "id": "calm",
        "label_en": "Calm",
        "label_fr": "Calme",
        "instructions": (
            "Speak in a soft, calm and soothing tone, slowly and gently, as if "
            "guiding a relaxation session."
        ),
    },
    "serious": {
        "id": "serious",
        "label_en": "Serious",
        "label_fr": "Sérieux",
        "instructions": (
            "Speak in a serious, formal and composed tone, with deliberate "
            "pacing and gravitas."
        ),
    },
    "storyteller": {
        "id": "storyteller",
        "label_en": "Storyteller",
        "label_fr": "Conteur",
        "instructions": (
            "Speak like a captivating storyteller: expressive, with dynamic "
            "intonation and dramatic timing that draws the listener in."
        ),
    },
    "whisper": {
        "id": "whisper",
        "label_en": "Whisper",
        "label_fr": "Chuchotement",
        "instructions": (
            "Speak in a very quiet, breathy whisper, intimate and close, "
            "barely above silence."
        ),
    },
}


def all_presets() -> List[Preset]:
    """Return the presets in display order (copies, safe to serialize)."""
    return [dict(p) for p in STYLES.values()]  # type: ignore[misc]


def is_valid(style_id: Optional[str]) -> bool:
    return bool(style_id) and style_id in STYLES


def get(style_id: Optional[str]) -> Preset:
    """Return the preset for ``style_id`` (falls back to the default)."""
    if style_id and style_id in STYLES:
        return STYLES[style_id]
    return STYLES[DEFAULT_STYLE]


def instruction_for(style_id: Optional[str], custom: str = "") -> str:
    """Resolve the effective instruction string.

    A non-empty ``custom`` free-text instruction always wins (lets power users
    override a preset). Otherwise the preset's canned instruction is used; the
    neutral preset resolves to an empty string (model default delivery).
    """
    custom = (custom or "").strip()
    if custom:
        return custom
    return get(style_id)["instructions"]
