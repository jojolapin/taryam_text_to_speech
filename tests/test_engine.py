"""Smoke tests for the TTS engine (no real Piper synthesis required).

These cover voice discovery, the cancel token, and the pure PCM encoders so
regressions in the engine surface without needing an ONNX model or audio output.

Run with:  .venv\\Scripts\\python -m pytest -q tests/test_engine.py

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import io
import json
import sys
import wave
from pathlib import Path

# Make the project root importable when pytest is launched from elsewhere
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.tts_engine import CancelToken, TTSEngine  # noqa: E402


# ---------------------------------------------------------------------------
# CancelToken
# ---------------------------------------------------------------------------

def test_cancel_token_starts_uncancelled() -> None:
    assert CancelToken().cancelled is False


def test_cancel_token_flips_once_cancelled() -> None:
    tok = CancelToken()
    tok.cancel()
    assert tok.cancelled is True


# ---------------------------------------------------------------------------
# Voice discovery
# ---------------------------------------------------------------------------

def test_discover_voices_on_empty_dir_returns_empty(tmp_path, monkeypatch) -> None:
    engine = TTSEngine()
    monkeypatch.setattr(engine, "voices_dir", lambda: tmp_path)
    assert engine.discover_voices() == []


def test_discover_voices_reads_metadata(tmp_path, monkeypatch) -> None:
    vid = "en_US-test-medium"
    (tmp_path / f"{vid}.onnx").write_bytes(b"\x00" * 10)
    (tmp_path / f"{vid}.onnx.json").write_text(json.dumps({
        "language": {"code": "en_US"},
        "dataset": {"speaker": "test"},
        "quality": "medium",
    }), encoding="utf-8")

    engine = TTSEngine()
    monkeypatch.setattr(engine, "voices_dir", lambda: tmp_path)
    voices = engine.discover_voices()

    assert len(voices) == 1
    v = voices[0]
    assert v["id"] == vid
    assert v["language"] == "en_US"
    assert v["speaker"] == "test"
    assert v["quality"] == "medium"


def test_discover_voices_skips_onnx_without_config(tmp_path, monkeypatch) -> None:
    # An .onnx with no matching .onnx.json must be ignored, not crash.
    (tmp_path / "orphan-voice.onnx").write_bytes(b"\x00")
    engine = TTSEngine()
    monkeypatch.setattr(engine, "voices_dir", lambda: tmp_path)
    assert engine.discover_voices() == []


# ---------------------------------------------------------------------------
# PCM encoders (pure, no Piper)
# ---------------------------------------------------------------------------

def test_encode_wav_roundtrips_pcm() -> None:
    engine = TTSEngine()
    sample_rate, channels = 22050, 1
    pcm = b"\x01\x00\x02\x00\x03\x00\x04\x00"  # 4 samples, 16-bit mono
    data = engine.encode_wav(pcm, sample_rate, channels)

    with wave.open(io.BytesIO(data), "rb") as w:
        assert w.getframerate() == sample_rate
        assert w.getnchannels() == channels
        assert w.getsampwidth() == 2
        assert w.readframes(w.getnframes()) == pcm
