"""Synthesize a cloned voice through the local Pocket TTS service.

Long text uses the same paragraph blocks as Kokoro. Pocket does not turn a
blank line into silence, so the pause is inserted in the audio here.

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import io
import wave
from typing import Callable, Optional

import numpy as np

from .clone_client import CloneClient
from .clone_errors import CloneError
from .clone_profiles import POCKET_LANGUAGE, load_profile, resolve_language, state_file
from .kokoro_engine import reading_blocks


def _wav_pcm(data: bytes) -> tuple[bytes, int]:
    with wave.open(io.BytesIO(data), "rb") as handle:
        if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
            raise CloneError("clone-synthesis", "unexpected wav layout")
        return handle.readframes(handle.getnframes()), handle.getframerate()


def _apply_volume(pcm: bytes, volume: float) -> bytes:
    gain = max(0.0, min(1.0, float(volume)))
    if gain == 1.0:
        return pcm
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
    scaled = np.clip(samples * gain, -32768.0, 32767.0).astype("<i2")
    return scaled.tobytes()


def _silence(milliseconds: int, sample_rate: int) -> bytes:
    frames = int(sample_rate * max(0, milliseconds) / 1000)
    return b"\x00\x00" * frames


def _wav_bytes(pcm: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)
    return buf.getvalue()


class CloneEngine:
    """One client, reused for the blocks of a reading."""

    def __init__(self, client: CloneClient | None = None):
        self.client = client or CloneClient()

    def synthesize_pcm(
        self,
        text: str,
        voice_id: str,
        length_scale: float = 1.0,
        volume: float = 1.0,
        token=None,
        progress: Optional[Callable[[str, float], None]] = None,
    ) -> tuple[bytes, int, int]:
        del length_scale  # Pocket TTS has no reading-speed control in this runtime.
        try:
            profile = load_profile(voice_id)
        except CloneError:
            raise
        language = resolve_language(profile, voice_id)
        pocket_name = str((profile.get("language_models") or {}).get(language) or POCKET_LANGUAGE.get(language, ""))
        if pocket_name not in set(POCKET_LANGUAGE.values()):
            raise CloneError("clone-language", language)
        state = state_file(profile, language)
        blocks = reading_blocks(text or "")
        if not blocks:
            raise ValueError("There is no text to read.")
        parts: list[bytes] = []
        sample_rate = 24000
        for index, block in enumerate(blocks):
            if token is not None and getattr(token, "cancelled", False):
                raise KeyboardInterrupt("cancelled")
            wav = self.client.synthesize_wav(state, block["text"], pocket_name)
            pcm, rate = _wav_pcm(wav)
            if index and rate != sample_rate:
                raise CloneError("clone-synthesis", f"sample rate changed from {sample_rate} to {rate}")
            sample_rate = rate
            parts.append(_apply_volume(pcm, volume))
            if block["gap_ms"]:
                parts.append(_silence(block["gap_ms"], sample_rate))
            if progress:
                progress("synth", (index + 1) / len(blocks))
        if token is not None and getattr(token, "cancelled", False):
            raise KeyboardInterrupt("cancelled")
        return b"".join(parts), sample_rate, 1

    def synthesize_wav_bytes(
        self,
        text: str,
        voice_id: str,
        length_scale: float = 1.0,
        volume: float = 1.0,
        token=None,
    ) -> bytes:
        pcm, sample_rate, _channels = self.synthesize_pcm(
            text, voice_id, length_scale, volume, token,
        )
        return _wav_bytes(pcm, sample_rate)

    def export_audio(
        self,
        text: str,
        voice_id: str,
        fmt: str,
        length_scale: float,
        volume: float,
        bitrate: int,
        token=None,
        progress: Optional[Callable[[str, float], None]] = None,
    ) -> tuple[bytes, float, int, int]:
        from ..tts_engine import TTSEngine

        def synth_progress(stage: str, ratio: float) -> None:
            if progress:
                progress(stage, ratio * 0.85)

        pcm, sample_rate, channels = self.synthesize_pcm(
            text, voice_id, length_scale, volume, token, progress=synth_progress,
        )
        if progress:
            progress("encode", 0.9)
        encoder = TTSEngine()
        kind = (fmt or "mp3").lower()
        if kind == "wav":
            data = encoder.encode_wav(pcm, sample_rate, channels)
        elif kind == "ogg":
            data = encoder.encode_ogg(pcm, sample_rate, channels)
        else:
            data = encoder.encode_mp3(pcm, sample_rate, channels, bitrate)
        if progress:
            progress("done", 1.0)
        seconds = len(pcm) / (sample_rate * channels * 2) if sample_rate else 0.0
        return data, seconds, sample_rate, channels
