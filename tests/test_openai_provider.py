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
    def __init__(self, status_code=200, content=b"AUDIO", payload=None, headers=None):
        self.status_code = status_code
        self.content = content
        self._payload = payload or {}
        self.headers = headers or {}

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
    assert ei.value.limit["status"] == 429
    assert ei.value.limit["kind"] == "unknown"
    assert ei.value.limit["resets_at"] is None


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


# ---- synthesis: disk cache ------------------------------------------------

def test_synthesize_serves_identical_request_from_cache(monkeypatch, tmp_path):
    from app.audio_cache import AudioCache

    monkeypatch.setattr(oap, "_key_from_env_files", lambda: "")
    sess = FakeSession(FakeResp(200, b"FROM_NET"))
    cache = AudioCache(root=tmp_path / "audio")
    p = OpenAIProvider(FakeSettings({"openai_api_key": "k"}), session=sess)

    a1, _ = p.synthesize(
        "Hello cache", voice="alloy", model="gpt-4o-mini-tts",
        instructions="calm", response_format="mp3",
        cache=cache, tab_id="tab-1",
    )
    assert a1 == b"FROM_NET"
    assert sess.last is not None
    sess.last = None  # reset so a second call must not hit the network

    a2, _ = p.synthesize(
        "Hello cache", voice="alloy", model="gpt-4o-mini-tts",
        instructions="calm", response_format="mp3",
        cache=cache, tab_id="tab-1",
    )
    assert a2 == b"FROM_NET"
    assert sess.last is None  # cache hit — no network call


def test_synthesize_cache_miss_when_voice_or_style_changes(monkeypatch, tmp_path):
    from app.audio_cache import AudioCache

    monkeypatch.setattr(oap, "_key_from_env_files", lambda: "")
    sess = FakeSession(FakeResp(200, b"A"))
    cache = AudioCache(root=tmp_path / "audio")
    p = OpenAIProvider(FakeSettings({"openai_api_key": "k"}), session=sess)

    p.synthesize("Hello", voice="alloy", instructions="calm", response_format="mp3",
                 cache=cache, tab_id="t")
    sess._resp = FakeResp(200, b"B")
    sess.last = None
    audio, _ = p.synthesize("Hello", voice="nova", instructions="calm", response_format="mp3",
                            cache=cache, tab_id="t")
    assert audio == b"B"
    assert sess.last is not None  # network called again

    sess._resp = FakeResp(200, b"C")
    sess.last = None
    audio2, _ = p.synthesize("Hello", voice="alloy", instructions="excited", response_format="mp3",
                             cache=cache, tab_id="t")
    assert audio2 == b"C"
    assert sess.last is not None


# ---- smart tools (text -> text) -------------------------------------------

def _chat_resp(text):
    return FakeResp(200, b"", {"choices": [{"message": {"content": text}}]})


def test_transform_clean_posts_to_chat_and_returns_text(monkeypatch):
    monkeypatch.setattr(oap, "_key_from_env_files", lambda: "")
    sess = FakeSession(_chat_resp("  Cleaned text.  "))
    p = OpenAIProvider(FakeSettings({"openai_api_key": "sk-x"}), session=sess)
    out = p.transform_text("clean me", "clean")
    assert out == "Cleaned text."  # trimmed
    assert sess.last["url"].endswith("/chat/completions")
    body = sess.last["json"]
    assert body["model"] == oap.DEFAULT_TEXT_MODEL
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["content"] == "clean me"
    assert sess.last["headers"]["Authorization"] == "Bearer sk-x"


def test_transform_translate_injects_target_language(monkeypatch):
    monkeypatch.setattr(oap, "_key_from_env_files", lambda: "")
    sess = FakeSession(_chat_resp("Bonjour"))
    p = OpenAIProvider(FakeSettings({"openai_api_key": "k"}), session=sess)
    out = p.transform_text("Hello", "translate", target_lang="French")
    assert out == "Bonjour"
    system = sess.last["json"]["messages"][0]["content"]
    assert "French" in system


def test_transform_uses_custom_text_model_from_settings(monkeypatch):
    monkeypatch.setattr(oap, "_key_from_env_files", lambda: "")
    sess = FakeSession(_chat_resp("x"))
    p = OpenAIProvider(FakeSettings({"openai_api_key": "k", "openai_text_model": "gpt-4o"}), session=sess)
    p.transform_text("hi", "summarize")
    assert sess.last["json"]["model"] == "gpt-4o"


def test_transform_unknown_task_rejected(monkeypatch):
    monkeypatch.setattr(oap, "_key_from_env_files", lambda: "")
    p = OpenAIProvider(FakeSettings({"openai_api_key": "k"}), session=FakeSession(_chat_resp("x")))
    with pytest.raises(OpenAIError):
        p.transform_text("hi", "nonsense")


def test_transform_empty_text_rejected(monkeypatch):
    monkeypatch.setattr(oap, "_key_from_env_files", lambda: "")
    p = OpenAIProvider(FakeSettings({"openai_api_key": "k"}), session=FakeSession(_chat_resp("x")))
    with pytest.raises(OpenAIError):
        p.transform_text("   ", "clean")


def test_transform_requires_key(monkeypatch):
    monkeypatch.setattr(oap, "_key_from_env_files", lambda: "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    p = OpenAIProvider(FakeSettings({}), session=FakeSession(_chat_resp("x")))
    with pytest.raises(OpenAIError):
        p.transform_text("hi", "clean")


def test_transform_cancelled_before_request(monkeypatch):
    monkeypatch.setattr(oap, "_key_from_env_files", lambda: "")

    class Tok:
        cancelled = True

    sess = FakeSession(_chat_resp("x"))
    p = OpenAIProvider(FakeSettings({"openai_api_key": "k"}), session=sess)
    with pytest.raises(OpenAIError) as ei:
        p.transform_text("hi", "clean", cancel=Tok())
    assert str(ei.value) == "cancelled"
    assert sess.last is None


def test_transform_401_is_sanitized(monkeypatch):
    monkeypatch.setattr(oap, "_key_from_env_files", lambda: "")
    sess = FakeSession(FakeResp(401, b"", {"error": {"message": "Bad key sk-secret"}}))
    p = OpenAIProvider(FakeSettings({"openai_api_key": "sk-secret"}), session=sess)
    with pytest.raises(OpenAIError) as ei:
        p.transform_text("hi", "clean")
    assert "sk-secret" not in str(ei.value)


def test_transform_malformed_response_is_sanitized(monkeypatch):
    monkeypatch.setattr(oap, "_key_from_env_files", lambda: "")
    sess = FakeSession(FakeResp(200, b"", {"unexpected": True}))
    p = OpenAIProvider(FakeSettings({"openai_api_key": "k"}), session=sess)
    with pytest.raises(OpenAIError) as ei:
        p.transform_text("hi", "clean")
    assert "unexpected" in str(ei.value).lower()


# ---- HTTP 429: proof, reset time, no secrets --------------------------------

def _raise_429(monkeypatch, payload, headers, now=1_700_000_000.0):
    monkeypatch.setattr(oap, "_key_from_env_files", lambda: "")
    monkeypatch.setattr(oap.time, "time", lambda: now)
    sess = FakeSession(FakeResp(429, b"", payload, headers))
    provider = OpenAIProvider(FakeSettings({"openai_api_key": "sk-secret"}), session=sess)
    with pytest.raises(OpenAIError) as caught:
        provider.synthesize("Hi")
    return caught.value


def test_429_credit_balance_has_no_return_date_and_hides_the_key(monkeypatch):
    exc = _raise_429(monkeypatch, {
        "error": {
            "message": "You exceeded your current quota. Key sk-secret was used.",
            "type": "insufficient_quota",
            "code": "credit_balance_exhausted",
        }
    }, {"x-request-id": "req_credit1", "retry-after": "30"})
    assert exc.limit["kind"] == "credits"
    assert exc.limit["code"] == "credit_balance_exhausted"
    assert exc.limit["request_id"] == "req_credit1"
    assert exc.limit["resets_at"] is None
    assert "sk-secret" not in str(exc)
    encoded = oap.format_openai_error(exc)
    assert "sk-secret" not in encoded
    assert "[redacted]" in encoded
    decoded = oap.decode_openai_limit(encoded)
    assert decoded["summary"].startswith("OpenAI quota exceeded.")
    assert decoded["limit"]["code"] == "credit_balance_exhausted"


def test_429_rate_limit_uses_the_longest_empty_bucket(monkeypatch):
    now = 1_700_000_000.0
    exc = _raise_429(monkeypatch, {
        "error": {
            "message": "Rate limit reached. Please try again in 20s.",
            "type": "tokens",
            "code": "rate_limit_exceeded",
        }
    }, {
        "x-request-id": "req_rate1",
        "retry-after": "20",
        "x-ratelimit-limit-requests": "500",
        "x-ratelimit-remaining-requests": "0",
        "x-ratelimit-reset-requests": "1s",
        "x-ratelimit-limit-tokens": "200000",
        "x-ratelimit-remaining-tokens": "0",
        "x-ratelimit-reset-tokens": "6m0s",
    }, now=now)
    assert exc.limit["kind"] == "rate_limit"
    assert exc.limit["reset_source"] == "x-ratelimit-reset-tokens"
    assert exc.limit["reset_seconds"] == 360
    assert exc.limit["resets_at"] == now + 360
    assert exc.limit["buckets"][0]["remaining"] == "0"
    assert exc.limit["buckets"][0]["limit"] == "500"


def test_429_rate_limit_reads_try_again_from_the_message(monkeypatch):
    now = 1_700_000_000.0
    exc = _raise_429(monkeypatch, {
        "error": {
            "message": "Rate limit reached for requests. Please try again in 12s.",
            "type": "requests",
            "code": "rate_limit_exceeded",
        }
    }, {}, now=now)
    assert exc.limit["reset_source"] == "message"
    assert exc.limit["resets_at"] == now + 12


def test_429_org_spend_resets_at_next_utc_month(monkeypatch):
    from datetime import datetime, timezone
    now = datetime(2026, 10, 5, 20, 9, tzinfo=timezone.utc).timestamp()
    exc = _raise_429(monkeypatch, {
        "error": {
            "message": "Organization spend limit reached.",
            "type": "insufficient_quota",
            "code": "organization_spend_limit_exceeded",
        }
    }, {"x-request-id": "req_spend1"}, now=now)
    expected = datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp()
    assert exc.limit["kind"] == "org_spend"
    assert exc.limit["reset_source"] == "monthly-utc"
    assert exc.limit["resets_at"] == expected


def test_429_december_spend_limit_rolls_to_january(monkeypatch):
    from datetime import datetime, timezone
    now = datetime(2026, 12, 18, 12, tzinfo=timezone.utc).timestamp()
    exc = _raise_429(monkeypatch, {
        "error": {"message": "limit", "type": "insufficient_quota", "code": "project_spend_limit_exceeded"}
    }, {}, now=now)
    assert exc.limit["resets_at"] == datetime(2027, 1, 1, tzinfo=timezone.utc).timestamp()


def test_parse_delay_accepts_openai_durations_and_http_dates():
    from datetime import datetime, timezone
    assert oap.parse_delay_seconds("6m0s") == 360
    assert oap.parse_delay_seconds("1s") == 1
    assert oap.parse_delay_seconds("1500ms") == 1.5
    assert oap.parse_delay_seconds("20") == 20
    now = datetime(2025, 12, 1, tzinfo=timezone.utc).timestamp()
    reset = oap.parse_delay_seconds("Thu, 01 Jan 2026 00:00:00 GMT", now=now)
    assert reset == datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() - now
