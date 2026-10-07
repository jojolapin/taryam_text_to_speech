"""Engine routing, Kokoro voice ids, and PCM conversion."""
from __future__ import annotations

import io
import wave

import numpy as np
import pytest

from app.speech_engines.hardware import probe_hardware
from app.speech_engines.kokoro_catalog import choice_label, voice_by_storage_id, voices
from app.speech_engines.kokoro_engine import (
    PARAGRAPH_GAP_MS,
    KokoroEngine,
    _float_to_pcm,
    reading_blocks,
)
from app.speech_engines.router import (
    is_kokoro_voice,
    resolve_provider,
    speed_from_length_scale,
)


def test_automatic_prefers_cached_kokoro_and_never_selects_openai():
    assert resolve_provider("auto", kokoro_ready=True) == "kokoro"
    assert resolve_provider("auto", kokoro_ready=False) == "piper"
    assert resolve_provider("openai", kokoro_ready=True) == "openai"
    assert resolve_provider("kokoro", kokoro_ready=False) == "kokoro"
    assert resolve_provider("piper", kokoro_ready=True) == "piper"
    assert resolve_provider("", kokoro_ready=False) == "piper"
    assert resolve_provider("clone", kokoro_ready=False) == "clone"
    assert resolve_provider("auto", kokoro_ready=True) != "clone"
    assert resolve_provider("auto", kokoro_ready=False) != "clone"


def test_length_scale_converts_to_kokoro_speed():
    assert speed_from_length_scale(1.0) == 1.0
    assert speed_from_length_scale(1 / 1.5) == pytest.approx(1.5)
    assert speed_from_length_scale(0) == 1.0
    assert speed_from_length_scale(0.1) == 2.0


def test_kokoro_voice_ids_round_trip():
    row = voice_by_storage_id("kokoro:af_heart")
    assert row["kokoro_lang"] == "en-us"
    assert row["gender"] == "female"
    assert is_kokoro_voice(row["storage_id"])
    assert "Français" in choice_label(voice_by_storage_id("kokoro:ff_siwis"), "fr")
    assert len(voices()) >= 8


def test_hardware_probe_always_reports_cpu():
    info = probe_hardware()
    assert info["cpu"] is True
    assert info["kokoro_device"] == "cpu"
    assert isinstance(info["cuda"], bool)


def test_float_audio_is_clipped_mono_pcm():
    pcm = _float_to_pcm(np.array([0.0, 0.5, 2.0, -2.0], dtype=np.float32), 1.0)
    rate = 24000
    with wave.open(io.BytesIO(_wrap(pcm, rate)), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getframerate() == 24000
        frames = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2")
    assert frames.tolist() == [0, 16383, 32767, -32767]


def _wrap(pcm: bytes, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm)
    return buf.getvalue()


def test_synthesis_uses_the_voice_language_and_joins_paragraphs(monkeypatch):
    calls = []

    class FakeModel:
        def create(self, text, voice, speed, lang, trim):
            calls.append((text, voice, speed, lang, trim))
            return np.linspace(-0.2, 0.2, 240, dtype=np.float32), 22050

    monkeypatch.setattr("app.speech_engines.kokoro_engine._load", lambda: FakeModel())
    paragraph = "This sentence belongs to one long paragraph. " * 30
    text = "A short opening paragraph.\n\n" + paragraph
    pcm, rate, channels = KokoroEngine().synthesize_pcm(
        text,
        "kokoro:bm_george",
        length_scale=1 / 1.25,
        volume=0.5,
    )
    assert rate == 22050 and channels == 1
    assert len(calls) >= 2
    assert calls[0][0] == "A short opening paragraph."
    assert calls[0][1] == "bm_george"
    assert calls[0][2] == pytest.approx(1.25)
    assert calls[0][3] == "en-gb"
    covered = " ".join(part[0] for part in calls)
    assert " ".join(text.split()) == " ".join(covered.split())
    # A pause sits between paragraphs, so the buffer is longer than the raw joins.
    assert len(pcm) > len(calls) * 240 * 2


def test_new_kokoro_strings_exist_in_french():
    from app.i18n import STRINGS

    for key, text in STRINGS["en"].items():
        if key.startswith("kokoro.") or key.startswith("engine.") or key == "about.kokoro":
            assert STRINGS["fr"].get(key)


def test_reading_blocks_keep_every_word_and_pause_between_paragraphs():
    text = (
        'Dr. Smith said "Hello, world" on Jan. 3, 2024 at 3:30 p.m. '
        "The total was $1,250.50, i.e. about 12% more.\n\n"
        "Mr. Hale arrived. U.S. mail was waiting.\n\n"
        "Short. Then one last sentence ends the reading."
    )
    blocks = reading_blocks(text)
    covered = " ".join(block["text"] for block in blocks)
    assert " ".join(text.split()) == " ".join(covered.split())
    assert blocks[-1]["gap_ms"] == 0
    assert [block["gap_ms"] for block in blocks[:-1]] == [PARAGRAPH_GAP_MS, PARAGRAPH_GAP_MS]
    assert "1,250.50" in blocks[0]["text"]
    assert "U.S. mail" in covered
