"""Kokoro cache recovery, routing fallback, and saved bookmark identity."""
from __future__ import annotations

import errno
import io
import json
import os
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QObject, Signal

from app.documents import new_document, validate_snapshot
from app.playback import PlaybackManager
from app.speech_engines import kokoro_engine
from app.speech_engines.kokoro_engine import KokoroError, download_models, models_ready
from app.speech_engines.router import resolve_provider


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("TEXTSPEAK_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(kokoro_engine, "MODEL_MIN_BYTES", 16)
    monkeypatch.setattr(kokoro_engine, "VOICES_MIN_BYTES", 16)
    kokoro_engine._model = None
    kokoro_engine._model_unreadable = False
    kokoro_engine._voices_stamp = None
    yield tmp_path
    kokoro_engine._model = None
    kokoro_engine._model_unreadable = False
    kokoro_engine._voices_stamp = None


def _onnx(path: Path, payload: bytes = b"\x08\x07" + b"model-body-padding") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _voices(path: Path, names=("af_heart", "ff_siwis")) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays = {name: np.zeros(4, dtype=np.float32) for name in names}
    buf = io.BytesIO()
    np.savez(buf, **arrays)
    path.write_bytes(buf.getvalue())


def test_incomplete_html_and_corrupt_bank_are_not_installed(cache):
    folder = cache / "models" / "kokoro"
    _onnx(folder / "kokoro-v1.0.onnx", b"<html>not a model</html>")
    _voices(folder / "voices-v1.0.bin")
    assert models_ready() is False

    _onnx(folder / "kokoro-v1.0.onnx")
    (folder / "voices-v1.0.bin").write_bytes(b"PK\x03\x04" + b"broken" * 8)
    kokoro_engine._voices_stamp = None
    assert models_ready() is False

    _voices(folder / "voices-v1.0.bin", names=("af_bella",))
    kokoro_engine._voices_stamp = None
    assert models_ready() is False

    _voices(folder / "voices-v1.0.bin")
    kokoro_engine._voices_stamp = None
    assert models_ready() is True
    assert resolve_provider("auto", kokoro_ready=models_ready()) == "kokoro"


def test_unreadable_model_hides_kokoro_until_restart_and_piper_remains(cache):
    folder = cache / "models" / "kokoro"
    _onnx(folder / "kokoro-v1.0.onnx")
    _voices(folder / "voices-v1.0.bin")
    kokoro_engine._model_unreadable = True
    assert models_ready() is False
    assert resolve_provider("auto", kokoro_ready=False) == "piper"
    assert resolve_provider("openai", kokoro_ready=False) == "openai"
    assert resolve_provider("auto", kokoro_ready=True) == "kokoro"


def test_failed_download_leaves_no_partial_and_keeps_piper_route(cache, monkeypatch):
    def explode(url, dest, progress=None, cancel=None):
        partial = dest.with_suffix(dest.suffix + ".part")
        partial.write_bytes(b"partial")
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(kokoro_engine, "_stream_download", explode)
    with pytest.raises(KokoroError) as caught:
        download_models()
    assert caught.value.code == "kokoro-download-failed"
    folder = cache / "models" / "kokoro"
    assert not list(folder.glob("*.part"))
    assert models_ready() is False
    assert resolve_provider("auto", kokoro_ready=False) == "piper"


def test_cancelled_download_removes_the_partial_file(cache, monkeypatch):
    def cancel_midway(url, dest, progress=None, cancel=None):
        partial = dest.with_suffix(dest.suffix + ".part")
        partial.write_bytes(b"x" * 32)
        raise KeyboardInterrupt("download cancelled")

    monkeypatch.setattr(kokoro_engine, "_stream_download", cancel_midway)
    with pytest.raises(KeyboardInterrupt):
        download_models()
    assert not list((cache / "models" / "kokoro").glob("*.part"))
    assert models_ready() is False


def test_connection_loss_does_not_replace_a_good_cache(cache, monkeypatch):
    folder = cache / "models" / "kokoro"
    model = folder / "kokoro-v1.0.onnx"
    _onnx(model)
    _voices(folder / "voices-v1.0.bin")
    original = model.read_bytes()
    kokoro_engine._model_unreadable = True

    def offline(url, dest, progress=None, cancel=None):
        raise ConnectionError("network unreachable")

    monkeypatch.setattr(kokoro_engine, "_stream_download", offline)
    with pytest.raises(KokoroError) as caught:
        download_models()
    assert caught.value.code == "kokoro-download-failed"
    assert model.read_bytes() == original
    assert not list(folder.glob("*.part"))


def test_a_good_cache_is_not_downloaded_again(cache, monkeypatch):
    folder = cache / "models" / "kokoro"
    _onnx(folder / "kokoro-v1.0.onnx")
    _voices(folder / "voices-v1.0.bin")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("download should not start")

    monkeypatch.setattr(kokoro_engine, "_stream_download", forbidden)
    download_models()


def test_saved_piper_and_openai_bookmarks_keep_their_engine():
    raw = {
        "schema": 2,
        "activeId": "piper-doc",
        "docs": [
            {
                "id": "piper-doc",
                "title": "Old Piper",
                "text": "Read this with Piper.",
                "provider": "piper",
                "voice": "en_US-joe-medium",
            },
            {
                "id": "cloud-doc",
                "title": "Cloud",
                "text": "Leave this on OpenAI.",
                "provider": "openai",
                "voice": "nova",
            },
        ],
    }
    restored = validate_snapshot(json.loads(json.dumps(raw)))
    assert [(doc["provider"], doc["voice"]) for doc in restored["docs"]] == [
        ("piper", "en_US-joe-medium"),
        ("openai", "nova"),
    ]
    fresh = new_document()
    assert fresh["provider"] == "piper"
    assert not str(fresh["voice"]).startswith("kokoro:")


def test_real_workspace_piper_bookmarks_were_not_migrated():
    root = os.environ.get("APPDATA", "")
    path = Path(root) / "JojoLapin" / "TextSpeak Pro" / "workspace-v2.json"
    if not path.is_file():
        pytest.skip("no saved workspace on this machine")
    raw = json.loads(path.read_text(encoding="utf-8"))
    restored = validate_snapshot(raw)
    assert len(restored["docs"]) == len(raw["docs"])
    for original, restored_doc in zip(raw["docs"], restored["docs"]):
        assert restored_doc["provider"] == original.get("provider", "piper")
        assert restored_doc["voice"] == original.get("voice", "")
        if restored_doc["provider"] == "piper":
            assert not str(restored_doc["voice"]).startswith("kokoro:")


class _Bridge(QObject):
    synthesizeReady = Signal(str, str)
    openaiAudioReady = Signal(str, str, str)
    synthesizeError = Signal(str, str)
    openaiAudioError = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.calls = []

    def set_pronunciation_rules(self, _rules):
        return None

    def synthesize(self, *args):
        self.calls.append(args)

    def cancel(self, _request):
        return None


def test_kokoro_playback_does_not_split_a_normal_paragraph():
    bridge = _Bridge()
    manager = PlaybackManager(bridge)
    sentence = "This sentence stays with its neighbours. "
    text = sentence * 20
    assert 260 < len(text) < 900
    document = {
        "id": "k",
        "text": text,
        "voice": "kokoro:af_heart",
        "provider": "kokoro",
        "speed": 1.0,
        "volume": 1.0,
        "markdownMode": "auto",
        "effectiveRules": [],
    }
    assert manager.play(document)
    assert len(manager.chunks) == 1
    manager.stop()
    piper = dict(document, voice="en_US-lessac-medium", provider="piper")
    assert manager.play(piper)
    assert len(manager.chunks) > 1
    manager.stop()
