"""What a speech engine can do, independent of any one vendor.

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class EngineCapabilities:
    """Stable facts the interface can show without loading a model."""

    id: str
    label: str
    local: bool
    requires_network: bool
    requires_api_key: bool
    voice_cloning: bool
    streaming: bool
    multilingual: bool
    emotion: bool
    speed: bool
    pitch: bool
    gpu: bool
    cpu: bool
    languages: tuple[str, ...]
    notes: str = ""

    def as_dict(self) -> dict:
        data = asdict(self)
        data["languages"] = list(self.languages)
        return data


KOKORO = EngineCapabilities(
    id="kokoro",
    label="Kokoro",
    local=True,
    requires_network=False,
    requires_api_key=False,
    voice_cloning=False,
    streaming=False,
    multilingual=True,
    emotion=False,
    speed=True,
    pitch=False,
    gpu=False,
    cpu=True,
    languages=("en-us", "en-gb", "fr-fr", "es", "it", "pt-br", "ja", "zh", "hi"),
    notes="Preset voices. ONNX on CPU. Model download is cached after the first install.",
)

PIPER = EngineCapabilities(
    id="piper",
    label="Piper",
    local=True,
    requires_network=False,
    requires_api_key=False,
    voice_cloning=False,
    streaming=False,
    multilingual=True,
    emotion=False,
    speed=True,
    pitch=False,
    gpu=False,
    cpu=True,
    languages=("multi",),
    notes="Small ONNX voices, one file per voice. Broad language coverage.",
)

CLONE = EngineCapabilities(
    id="clone",
    label="Pocket TTS",
    local=True,
    requires_network=False,
    requires_api_key=False,
    voice_cloning=True,
    streaming=False,
    multilingual=True,
    emotion=False,
    speed=False,
    pitch=False,
    gpu=False,
    cpu=True,
    languages=("en", "fr"),
    notes="Explicit cloned voices only. Runs in a separate Pocket TTS process. Automatic never selects it.",
)

OPENAI = EngineCapabilities(
    id="openai",
    label="OpenAI",
    local=False,
    requires_network=True,
    requires_api_key=True,
    voice_cloning=False,
    streaming=False,
    multilingual=True,
    emotion=True,
    speed=True,
    pitch=False,
    gpu=False,
    cpu=False,
    languages=("multi",),
    notes="Cloud voices. Speaking styles apply on gpt-4o-mini-tts. Usage is billed by the provider.",
)

CAPABILITIES = {
    KOKORO.id: KOKORO,
    PIPER.id: PIPER,
    CLONE.id: CLONE,
    OPENAI.id: OPENAI,
}
