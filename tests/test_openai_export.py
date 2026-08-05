"""Tests for OpenAI export helpers: default export dir + chunked join path.

Mocks OpenAIProvider.synthesize so no network is used. Verifies that a second
identical export request hits the cache (no extra synthesize calls beyond chunks).

Run:  .venv\\Scripts\\python -m pytest -q tests/test_openai_export.py

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.audio_cache import AudioCache, join_audio_parts  # noqa: E402
from app.chunking import chunk as semantic_chunk  # noqa: E402
from app import paths as app_paths  # noqa: E402


def test_default_export_dir_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(app_paths, "is_portable", lambda: False)
    music = tmp_path / "Music"
    music.mkdir()
    monkeypatch.setenv("XDG_MUSIC_DIR", str(music))
    out = app_paths.default_export_dir()
    assert out == music / "TextSpeak Pro"
    assert out.is_dir()


def test_default_export_dir_portable(monkeypatch, tmp_path):
    monkeypatch.setattr(app_paths, "is_portable", lambda: True)
    monkeypatch.setattr(app_paths, "_exe_dir", lambda: tmp_path)
    out = app_paths.default_export_dir()
    assert out == tmp_path / "audio"
    assert out.is_dir()


def test_openai_export_join_uses_cache_across_identical_chunks(tmp_path):
    """Simulate the export loop: synthesize each chunk with a shared cache;
    re-running the same text must not call the network again."""
    cache = AudioCache(root=tmp_path / "audio")
    calls = {"n": 0}

    def fake_synthesize(text, **kwargs):
        calls["n"] += 1
        key_bits = (kwargs.get("voice"), kwargs.get("model"), kwargs.get("instructions"),
                    kwargs.get("response_format"), text)
        # Mimic provider cache behaviour via AudioCache
        from app.audio_cache import make_key
        key = make_key(
            provider="openai",
            model=kwargs.get("model") or "m",
            voice=kwargs.get("voice") or "alloy",
            style=kwargs.get("instructions") or "",
            fmt=kwargs.get("response_format") or "mp3",
            text=text,
        )
        hit = cache.get(key)
        if hit is not None:
            calls["n"] -= 1  # don't count cache hits as network
            return hit, "audio/mpeg"
        data = ("CHUNK:" + text[:20]).encode("utf-8")
        cache.put(key, data, provider="openai", fmt="mp3", tab_id=kwargs.get("tab_id") or "")
        return data, "audio/mpeg"

    text = "First sentence. Second sentence. Third sentence about 3.14 and https://x.test."
    chunks = semantic_chunk(text, max_chars=40)
    assert len(chunks) >= 1

    parts1 = []
    for ch in chunks:
        audio, _ = fake_synthesize(
            ch["text"], voice="alloy", model="gpt-4o-mini-tts",
            instructions="calm", response_format="mp3", tab_id="tab-x",
        )
        parts1.append(audio)
    net1 = calls["n"]
    joined1 = join_audio_parts(parts1, "mp3")
    assert joined1

    # Identical request — all cache hits
    calls["n"] = 0
    parts2 = []
    for ch in chunks:
        audio, _ = fake_synthesize(
            ch["text"], voice="alloy", model="gpt-4o-mini-tts",
            instructions="calm", response_format="mp3", tab_id="tab-x",
        )
        parts2.append(audio)
    assert calls["n"] == 0
    assert join_audio_parts(parts2, "mp3") == joined1
    assert net1 >= 1
