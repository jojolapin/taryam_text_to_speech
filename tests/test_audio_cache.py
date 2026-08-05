"""Tests for app/audio_cache.py — content-hash cache, join, clear-by-tab.

No network. Clearing audio must never imply deleting document text (cache only).

Run:  .venv\\Scripts\\python -m pytest -q tests/test_audio_cache.py

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import io
import sys
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.audio_cache import AudioCache, join_audio_parts, make_key  # noqa: E402


def _wav_bytes(frames: bytes = b"\x00\x01" * 100, rate: int = 22050) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)
    return buf.getvalue()


def test_make_key_stable_and_sensitive_to_voice_and_style():
    a = make_key(provider="openai", model="m", voice="alloy", style="calm",
                 fmt="mp3", text="Hello")
    b = make_key(provider="openai", model="m", voice="alloy", style="calm",
                 fmt="mp3", text="Hello")
    assert a == b
    assert a != make_key(provider="openai", model="m", voice="nova", style="calm",
                         fmt="mp3", text="Hello")
    assert a != make_key(provider="openai", model="m", voice="alloy", style="excited",
                         fmt="mp3", text="Hello")
    assert a != make_key(provider="openai", model="m", voice="alloy", style="calm",
                         fmt="wav", text="Hello")


def test_put_get_and_cache_hit(tmp_path):
    cache = AudioCache(root=tmp_path / "audio")
    key = make_key(provider="openai", model="m", voice="alloy", style="",
                   fmt="mp3", text="hi")
    assert cache.get(key) is None
    cache.put(key, b"AUDIO1", provider="openai", fmt="mp3", tab_id="tab-a")
    assert cache.get(key) == b"AUDIO1"
    # Second put overwrites bytes but keeps tab tags
    cache.put(key, b"AUDIO2", provider="openai", fmt="mp3", tab_id="tab-b")
    assert cache.get(key) == b"AUDIO2"
    stats = cache.stats()
    assert stats["audioCount"] == 1
    assert stats["audioBytes"] == 6
    assert "tab-a" in stats["byTab"]
    assert "tab-b" in stats["byTab"]


def test_clear_by_tab_keeps_shared_until_last_ref(tmp_path):
    cache = AudioCache(root=tmp_path / "audio")
    key = make_key(provider="openai", model="m", voice="alloy", style="",
                   fmt="mp3", text="shared")
    cache.put(key, b"XX", provider="openai", fmt="mp3", tab_id="t1")
    cache.touch_tab(key, "t2")
    # Clear t1 — file stays because t2 still references it
    r1 = cache.clear(tab_id="t1")
    assert r1["removedCount"] == 0
    assert cache.get(key) == b"XX"
    # Clear t2 — last ref, file goes
    r2 = cache.clear(tab_id="t2")
    assert r2["removedCount"] == 1
    assert cache.get(key) is None


def test_clear_openai_does_not_touch_piper_samples(tmp_path, monkeypatch):
    audio_root = tmp_path / "audio"
    samples = tmp_path / "samples"
    samples.mkdir()
    (samples / "voice.mp3").write_bytes(b"sample")
    monkeypatch.setattr("app.audio_cache.samples_cache_dir", lambda: samples)

    cache = AudioCache(root=audio_root)
    key = make_key(provider="openai", model="m", voice="alloy", style="",
                   fmt="mp3", text="x")
    cache.put(key, b"oa", provider="openai", fmt="mp3", tab_id="t")
    cache.clear(provider="openai")
    assert cache.get(key) is None
    assert (samples / "voice.mp3").exists()


def test_clear_piper_only_samples(tmp_path, monkeypatch):
    audio_root = tmp_path / "audio"
    samples = tmp_path / "samples"
    samples.mkdir()
    (samples / "voice.mp3").write_bytes(b"sample")
    monkeypatch.setattr("app.audio_cache.samples_cache_dir", lambda: samples)

    cache = AudioCache(root=audio_root)
    key = make_key(provider="openai", model="m", voice="alloy", style="",
                   fmt="mp3", text="keep")
    cache.put(key, b"oa", provider="openai", fmt="mp3")
    r = cache.clear(provider="piper")
    assert r["removedCount"] == 1
    assert cache.get(key) == b"oa"
    assert not (samples / "voice.mp3").exists()


def test_join_mp3_concatenates():
    assert join_audio_parts([b"aaa", b"bbb"], "mp3") == b"aaabbb"


def test_join_wav_merges_pcm():
    a = _wav_bytes(b"\x01\x02" * 50)
    b = _wav_bytes(b"\x03\x04" * 50)
    joined = join_audio_parts([a, b], "wav")
    with wave.open(io.BytesIO(joined), "rb") as w:
        assert w.getnframes() == 100  # 50 + 50 frames (2 bytes each sample)


def test_join_other_format_requires_single_part():
    with pytest.raises(ValueError):
        join_audio_parts([b"a", b"b"], "opus")
    assert join_audio_parts([b"solo"], "opus") == b"solo"
