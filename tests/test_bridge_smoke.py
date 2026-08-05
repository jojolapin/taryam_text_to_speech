"""Smoke tests for the QWebChannel bridge (no GUI, no registry writes).

Focus: the request-id cancel-token contract that underpins stale-session
protection on the Python side, plus the pure filename/snippet helpers. A dummy
Settings object is injected so no real QSettings/registry is touched.

Run with:  .venv\\Scripts\\python -m pytest -q tests/test_bridge_smoke.py

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def qapp():
    """A minimal, headless QCoreApplication so QObject/QThreadPool are usable."""
    from PySide6.QtCore import QCoreApplication
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


class _DummySettings:
    """Stand-in for app.settings.Settings that never touches QSettings."""

    def __init__(self) -> None:
        self._d: dict = {}

    def get(self, key, default=None):
        return self._d.get(key, default)

    def set(self, key, value) -> None:
        self._d[key] = value

    def get_json(self, key, default):
        import json as _json
        raw = self._d.get(key)
        if raw is None:
            return default
        try:
            return _json.loads(raw)
        except (TypeError, ValueError):
            return default


# ---------------------------------------------------------------------------
# Pure helpers (no Qt app needed)
# ---------------------------------------------------------------------------

def test_safe_filename_sanitizes_and_adds_extension() -> None:
    from app.bridge import _safe_filename
    out = _safe_filename("My: reading/notes?.txt", "mp3")
    assert out.endswith(".mp3")
    assert "/" not in out and ":" not in out and "?" not in out


def test_safe_filename_falls_back_when_empty() -> None:
    from app.bridge import _safe_filename
    out = _safe_filename("///", "wav", fallback="fallback-name")
    assert out == "fallback-name.wav"


def test_first_line_snippet_collapses_whitespace() -> None:
    from app.bridge import _first_line_snippet
    out = _first_line_snippet("  Hello   world  \nsecond line")
    assert out == "Hello world"


# ---------------------------------------------------------------------------
# Cancel-token contract (needs a QCoreApplication for QThreadPool)
# ---------------------------------------------------------------------------

def test_cancel_unknown_request_is_noop(qapp) -> None:
    from app.bridge import Bridge
    bridge = Bridge(engine=object(), settings=_DummySettings())
    # Must not raise for an id that was never registered.
    bridge.cancel("does-not-exist")


def test_cancel_flips_the_matching_token(qapp) -> None:
    from app.bridge import Bridge
    from app.tts_engine import CancelToken
    bridge = Bridge(engine=object(), settings=_DummySettings())

    tok = CancelToken()
    bridge._cancels["req-1"] = tok
    assert tok.cancelled is False

    bridge.cancel("req-1")
    assert tok.cancelled is True


def test_cancel_sets_download_event(qapp) -> None:
    import threading
    from app.bridge import Bridge
    bridge = Bridge(engine=object(), settings=_DummySettings())

    ev = threading.Event()
    bridge._dl_cancels["dl-1"] = ev
    assert not ev.is_set()

    bridge.cancel("dl-1")
    assert ev.is_set()


# ---------------------------------------------------------------------------
# Pronunciation + speaking-style slots
# ---------------------------------------------------------------------------

def test_pronunciation_rules_seeded_from_settings(qapp) -> None:
    import json
    from app.bridge import Bridge
    s = _DummySettings()
    s.set("pronunciation_rules", json.dumps([{"from": "Dr", "to": "Doctor"}]))
    bridge = Bridge(engine=object(), settings=s)
    assert bridge._pron_rules == [{"from": "Dr", "to": "Doctor"}]


def test_set_pronunciation_rules_applies_to_normalized_speech(qapp) -> None:
    import json
    from app.bridge import Bridge
    bridge = Bridge(engine=object(), settings=_DummySettings())
    bridge.set_pronunciation_rules(json.dumps([{"from": "NASA", "to": "N A S A"}]))
    spoken = bridge._normalize_for_tts("Go NASA go", "plain")
    assert spoken == "Go N A S A go"


def test_set_pronunciation_rules_rejects_bad_json(qapp) -> None:
    from app.bridge import Bridge
    bridge = Bridge(engine=object(), settings=_DummySettings())
    bridge.set_pronunciation_rules("{not json")
    assert bridge._pron_rules == []


def test_preview_pronunciation_returns_original_and_spoken(qapp) -> None:
    import json
    from app.bridge import Bridge
    bridge = Bridge(engine=object(), settings=_DummySettings())
    out = json.loads(bridge.preview_pronunciation(
        "Hello Dr Smith", json.dumps([{"from": "Dr", "to": "Doctor"}]), "plain"))
    assert out["original"] == "Hello Dr Smith"
    assert out["spoken"] == "Hello Doctor Smith"


def test_preview_pronunciation_does_not_change_stored_rules(qapp) -> None:
    import json
    from app.bridge import Bridge
    bridge = Bridge(engine=object(), settings=_DummySettings())
    bridge.preview_pronunciation("x", json.dumps([{"from": "x", "to": "y"}]), "plain")
    # Preview uses the passed rules only; the active set stays empty.
    assert bridge._pron_rules == []


def test_speaking_styles_slot_lists_presets(qapp) -> None:
    import json
    from app.bridge import Bridge
    bridge = Bridge(engine=object(), settings=_DummySettings())
    data = json.loads(bridge.speaking_styles())
    assert data["default"] == "neutral"
    ids = {p["id"] for p in data["presets"]}
    assert {"neutral", "narration", "calm"} <= ids
