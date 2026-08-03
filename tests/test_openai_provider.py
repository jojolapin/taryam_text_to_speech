"""Tests for the OpenAI TTS provider (app/openai_provider.py).

Fully mocked \u2014 no network calls and no real API key are ever used. Verifies
config resolution/precedence, request shaping, mime handling, cancellation, and
that errors are sanitized (never leaking the key).

Run:  .venv\\Scripts\\python -m pytest -q tests/test_openai_provider.py

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import openai_provider as oap  # noqa: E402
from app.openai_provider import OpenAIError, OpenAIProvider, resolve_config  # noqa: E402


class FakeSettings:
    def __init__(self, data=None):
        self._d = dict(data or {})

    def get(self, key, default=None):
        return self._d.get(key, default)

    def set(self, key, value):
        self._d[key] = value


class FakeResp:
    def __init__(self, status_code=200, content=b"AUDIO", payload=None):
        self.status_code = status_code
        self.content = content
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, resp=None, raise_exc=None):
        self._resp = resp or FakeResp()
        self._raise = raise_exc
        self.last = None

    def post(self, url, headers=None, json=None, timeout=None):
        self.last = {"url": url, "headers": headers, "json": json, "timeout": timeout}
        if self._raise:
            raise self._raise
        return self._resp


# ---- .env parsing ---------------------------------------------------------

def test_parse_env_file_handles_comments_quotes_and_export(tmp_path):
    p = tmp_path / ".env"
    p.write_text(
        "# comment\n"
        "\n"
        "export OPENAI_API_KEY = \"sk-abc123\"\n"
        "OTHER='value'\n"
        "bad line without equals\n",
        encoding="utf-8",
    )
    data = oap._parse_env_file(p)
    assert data["OPENAI_API_KEY"] == "sk-abc123"
    assert data["OTHER"] == "value"
    assert "bad line without equals" not in data


def test_parse_env_file_missing_returns_empty(tmp_path):
    assert oap._parse_env_file(tmp_path / "nope.env") == {}


# ---- config resolution / precedence --------------------------------------

def test_resolve_prefers_settings_key(monkeypatch):
    monkeypatch.setattr(oap, "_key_from_env_files", lambda: "file-key")
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    cfg = resolve_config(FakeSettings({"openai_api_key": "settings-key"}))
    assert cfg.api_key == "settings-key"
    assert cfg.key_source == "settings"
    assert cfg.configured is True


def test_resolve_falls_back_to_env_file(monkeypatch):
    monkeypatch.setattr(oap, "_key_from_env_files", lambda: "file-key")
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    cfg = resolve_config(FakeSettings({}))
    assert cfg.api_key == "file-key"
    assert cfg.key_source == "env-file"


def test_resolve_falls_back_to_env_var(monkeypatch):
    monkeypatch.setattr(oap, "_key_from_env_files", lambda: "")
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    cfg = resolve_config(FakeSettings({}))
    assert cfg.api_key == "env-key"
    assert cfg.key_source == "env-var"


def test_resolve_none_when_unset(monkeypatch):
    monkeypatch.setattr(oap, "_key_from_env_files", lambda: "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = resolve_config(FakeSettings({}))
    assert cfg.api_key == ""
    assert cfg.key_source == "none"
    assert cfg.configured is False


def test_resolve_uses_defaults_and_custom_base_url(monkeypatch):
    monkeypatch.setattr(oap, "_key_from_env_files", lambda: "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = resolve_config(FakeSettings({
        "openai_api_key": "k",
        "openai_base_url": "https://proxy.local/v1/",
        "openai_model": "tts-1",
    }))
    assert cfg.base_url == "https://proxy.local/v1"  # trailing slash trimmed
    assert cfg.model == "tts-1"


# ---- availability ---------------------------------------------------------

def test_is_available_reflects_key(monkeypatch):
    monkeypatch.setattr(oap, "_key_from_env_files", lambda: "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    ok, _ = OpenAIProvider(FakeSettings({"openai_api_key": "k"})).is_available()
    assert ok is True
    ok2, _ = OpenAIProvider(FakeSettings({})).is_available()
    assert ok2 is False


# ---- synthesis: request shaping ------------------------------------------

def test_synthesize_gpt4o_uses_instructions_not_speed(monkeypatch):
    monkeypatch.setattr(oap, "_key_from_env_files", lambda: "")
    sess = FakeSession(FakeResp(200, b"MP3BYTES"))
    p = OpenAIProvider(FakeSettings({"openai_api_key": "sk-x", "openai_model": "gpt-4o-mini-tts"}), session=sess)
    audio, mime = p.synthesize("Hello", voice="alloy", speed=1.5, instructions="calm", response_format="mp3")
    assert audio == b"MP3BYTES"
    assert mime == "audio/mpeg"
    body = sess.last["json"]
    assert body["model"] == "gpt-4o-mini-tts"
    assert body["voice"] == "alloy"
    assert body["instructions"] == "calm"
    assert "speed" not in body
    # Authorization carries the key, but it's never surfaced in errors.
    assert sess.last["headers"]["Authorization"] == "Bearer sk-x"


def test_synthesize_classic_model_uses_speed(monkeypatch):
    monkeypatch.setattr(oap, "_key_from_env_files", lambda: "")
    sess = FakeSession(FakeResp(200, b"WAVE"))
    p = OpenAIProvider(FakeSettings({"openai_api_key": "sk-x"}), session=sess)
    p.synthesize("Hi", voice="nova", model="tts-1", speed=1.5, response_format="wav")
    body = sess.last["json"]
    assert body["speed"] == 1.5
    assert "instructions" not in body


def test_synthesize_mime_matches_format(monkeypatch):
    monkeypatch.setattr(oap, "_key_from_env_files", lambda: "")
    sess = FakeSession(FakeResp(200, b"X"))
    p = OpenAIProvider(FakeSettings({"openai_api_key": "sk-x"}), session=sess)
    _, mime = p.synthesize("Hi", response_format="flac")
    assert mime == "audio/flac"


# ---- synthesis: errors / cancel ------------------------------------------

def test_synthesize_requires_key(monkeypatch):
    monkeypatch.setattr(oap, "_key_from_env_files", lambda: "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    p = OpenAIProvider(FakeSettings({}))
    with pytest.raises(OpenAIError):
        p.synthesize("Hi")


def test_synthesize_401_is_sanitized(monkeypatch):
    monkeypatch.setattr(oap, "_key_from_env_files", lambda: "")
    sess = FakeSession(FakeResp(401, b"", {"error": {"message": "Bad key sk-secret"}}))
    p = OpenAIProvider(FakeSettings({"openai_api_key": "sk-secret"}), session=sess)
    with pytest.raises(OpenAIError) as ei:
        p.synthesize("Hi")
    msg = str(ei.value)
    assert "sk-secret" not in msg
    assert "unauthorized" in msg.lower()


def test_synthesize_429_is_sanitized(monkeypatch):
    monkeypatch.setattr(oap, "_key_from_env_files", lambda: "")
    sess = FakeSession(FakeResp(429, b""))
    p = OpenAIProvider(FakeSettings({"openai_api_key": "k"}), session=sess)
    with pytest.raises(OpenAIError) as ei:
        p.synthesize("Hi")
    assert "rate limit" in str(ei.value).lower() or "quota" in str(ei.value).lower()


def test_synthesize_timeout_is_sanitized(monkeypatch):
    monkeypatch.setattr(oap, "_key_from_env_files", lambda: "")

    class ConnectTimeout(Exception):
        pass

    sess = FakeSession(raise_exc=ConnectTimeout("boom"))
    p = OpenAIProvider(FakeSettings({"openai_api_key": "k"}), session=sess)
    with pytest.raises(OpenAIError) as ei:
        p.synthesize("Hi")
    assert "timed out" in str(ei.value).lower()


def test_synthesize_cancelled_before_request(monkeypatch):
    monkeypatch.setattr(oap, "_key_from_env_files", lambda: "")

    class Tok:
        cancelled = True

    sess = FakeSession(FakeResp(200, b"X"))
    p = OpenAIProvider(FakeSettings({"openai_api_key": "k"}), session=sess)
    with pytest.raises(OpenAIError) as ei:
        p.synthesize("Hi", cancel=Tok())
    assert str(ei.value) == "cancelled"
    assert sess.last is None  # never sent the request


def test_synthesize_empty_text_rejected(monkeypatch):
    monkeypatch.setattr(oap, "_key_from_env_files", lambda: "")
    p = OpenAIProvider(FakeSettings({"openai_api_key": "k"}), session=FakeSession())
    with pytest.raises(OpenAIError):
        p.synthesize("   ")
