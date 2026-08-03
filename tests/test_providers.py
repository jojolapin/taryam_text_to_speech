"""Tests for the Python voice provider registry (app/providers.py).

Run with:  .venv\\Scripts\\python -m pytest -q tests/test_providers.py

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.providers import PiperProvider, ProviderRegistry, VoiceProvider  # noqa: E402


class _FakeEngine:
    def __init__(self, voices):
        self._voices = voices

    def discover_voices(self):
        return self._voices


def test_piper_available_when_voices_installed():
    p = PiperProvider(_FakeEngine([{"id": "en_US-lessac-medium"}]))
    ok, detail = p.is_available()
    assert ok is True
    assert "1" in detail


def test_piper_unavailable_without_voices():
    p = PiperProvider(_FakeEngine([]))
    ok, detail = p.is_available()
    assert ok is False
    assert detail


def test_piper_availability_probe_never_raises():
    class Boom:
        def discover_voices(self):
            raise RuntimeError("disk gone")

    p = PiperProvider(Boom())
    ok, _ = p.is_available()
    assert ok is False


def test_provider_info_shape_is_json_serializable():
    p = PiperProvider(_FakeEngine([{"id": "v"}]))
    info = p.info()
    assert info.id == "piper"
    assert info.offline is True
    assert info.requires_network is False
    assert info.is_ai is False
    assert info.available is True


def test_registry_register_get_and_default_fallback():
    reg = ProviderRegistry("piper")
    piper = reg.register(PiperProvider(_FakeEngine([{"id": "v"}])))
    assert reg.get("piper") is piper
    assert reg.has("piper") is True
    assert reg.get("openai") is piper  # unknown falls back to default
    assert reg.ids() == ["piper"]


def test_registry_status_lists_all_providers():
    reg = ProviderRegistry("piper")
    reg.register(PiperProvider(_FakeEngine([{"id": "v"}])))
    status = reg.status()
    assert isinstance(status, list) and len(status) == 1
    entry = status[0]
    assert entry["id"] == "piper"
    assert entry["available"] is True
    assert set(["id", "label", "offline", "requires_network", "is_ai", "available", "detail"]).issubset(entry.keys())


def test_base_provider_defaults():
    base = VoiceProvider()
    ok, detail = base.is_available()
    assert ok is True
    assert detail == ""
