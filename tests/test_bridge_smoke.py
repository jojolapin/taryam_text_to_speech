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
