"""Cloned voices, consent, routing, and Pocket TTS failure handling."""
from __future__ import annotations

import json
import wave
from pathlib import Path

import numpy as np
import pytest

from app import i18n
from app.documents import new_document, validate_snapshot
from app.playback import PlaybackManager
from app.speech_engines import clone_client
from app.speech_engines.clone_client import CloneClient
from app.speech_engines.clone_engine import CloneEngine
from app.speech_engines.clone_errors import CloneError
from app.speech_engines.clone_profiles import (
    CONSENT_STATEMENT,
    POCKET_LANGUAGE,
    PREVIEW_TEXT,
    build_profile,
    delete_profile,
    list_profiles,
    load_profile,
    pocket_model_dir,
    resolve_language,
    voice_choices,
)
from app.speech_engines.kokoro_engine import PARAGRAPH_GAP_MS
from app.speech_engines.reference_audio import POCKET_MAX_REFERENCE_S, analyze_wav, prepare_wav
from app.speech_engines.router import is_clone_voice, is_kokoro_voice, resolve_provider
from PySide6.QtCore import QObject, Signal


def _wav(path: Path, samples: np.ndarray, rate: int = 16000, channels: int = 1) -> None:
    audio = np.asarray(samples, dtype=np.float32)
    if channels == 1:
        frames = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    else:
        frames = np.column_stack([audio, audio])
        frames = (np.clip(frames, -1, 1) * 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(frames.tobytes())


def _tone(seconds: float, rate: int = 16000, amplitude: float = 0.3) -> np.ndarray:
    count = int(seconds * rate)
    time = np.arange(count) / rate
    return (amplitude * np.sin(2 * np.pi * 180 * time)).astype(np.float32)


def _pcm_wav(value: int = 2000, count: int = 80, rate: int = 24000) -> bytes:
    import io

    pcm = np.full(count, value, dtype="<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm)
    return buf.getvalue()


class _FakePocket:
    def __init__(self):
        self.languages = []
        self.texts = []

    def export_state(self, wav: Path, dest: Path, language: str) -> None:
        assert wav.is_file()
        self.languages.append(language)
        dest.write_bytes(b"voice-state-" + language.encode("ascii") + (b"\0" * 64))

    def synthesize_wav(self, state: Path, text: str, language: str) -> bytes:
        assert state.is_file()
        self.texts.append((language, text))
        return _pcm_wav()


@pytest.fixture
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("TEXTSPEAK_DATA_DIR", str(tmp_path))
    return tmp_path


def test_reference_rejects_empty_short_and_clipped_audio(tmp_path):
    empty = tmp_path / "empty.wav"
    _wav(empty, np.zeros(16000 * 5, dtype=np.float32))
    assert analyze_wav(empty).level == "error"
    assert "empty" in analyze_wav(empty).notes

    short = tmp_path / "short.wav"
    _wav(short, _tone(1.0))
    short_report = analyze_wav(short)
    assert short_report.level == "error"
    assert "too-short" in short_report.notes

    clipped = tmp_path / "clipped.wav"
    _wav(clipped, _tone(12.0, amplitude=1.0))
    clipped_report = analyze_wav(clipped)
    assert clipped_report.level == "error"
    assert "clipping" in clipped_report.notes


def test_reference_warns_and_trims_to_pocket_limit(tmp_path):
    quiet = tmp_path / "quiet.wav"
    _wav(quiet, _tone(12.0, amplitude=0.03))
    quiet_report = analyze_wav(quiet)
    assert quiet_report.level == "warning"
    assert "quiet" in quiet_report.notes

    good = tmp_path / "good.wav"
    _wav(good, _tone(12.4, amplitude=0.3), channels=2)
    report = analyze_wav(good)
    assert report.level == "good"
    assert report.channels == 2
    assert "level-ok" in report.notes
    assert "no-clip" in report.notes

    long = tmp_path / "long.wav"
    _wav(long, _tone(40.0, amplitude=0.3))
    prepared = tmp_path / "prepared.wav"
    long_report, actions = prepare_wav(long, prepared)
    assert long_report.level == "warning"
    assert "long" in long_report.notes
    assert "trim-30s" in actions
    with wave.open(str(prepared), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getframerate() == 24000
        assert handle.getnframes() / handle.getframerate() <= POCKET_MAX_REFERENCE_S + 0.05


def test_consent_is_required_and_profile_stores_both_languages(data_dir, tmp_path):
    source = tmp_path / "voice.wav"
    _wav(source, _tone(12.0))
    service = _FakePocket()
    with pytest.raises(CloneError) as denied:
        build_profile(
            display_name="My Voice",
            source_wav=source,
            source_kind="import",
            transcript="",
            consent=False,
            presented=CONSENT_STATEMENT,
            locale="en",
            engine_version="2.1.0",
            service=service,
        )
    assert denied.value.code == "clone-consent"
    assert list_profiles() == []

    profile = build_profile(
        display_name="My Voice",
        source_wav=source,
        source_kind="record",
        transcript="hello",
        consent=True,
        presented=CONSENT_STATEMENT,
        locale="en",
        engine_version="2.1.0",
        service=service,
        ui_language="en",
    )
    assert service.languages == ["english", "french_24l"]
    assert [text for _language, text in service.texts] == [PREVIEW_TEXT["en"], PREVIEW_TEXT["fr"]]
    assert profile["consent"]["accepted"] is True
    assert profile["consent"]["statement"] == CONSENT_STATEMENT
    assert profile["consent"]["timestamp"]
    assert profile["engine"] == "pocket-tts"
    assert profile["engine_version"] == "2.1.0"
    assert profile["supported_languages"] == ["en", "fr"]
    assert profile["language_models"] == POCKET_LANGUAGE
    assert profile["cached_profiles"] == {"en": "voice_en.safetensors", "fr": "voice_fr.safetensors"}
    assert profile["reference_source"] == "record"
    raw = json.dumps(profile)
    assert "C:\\" not in raw
    assert ":\\" not in raw
    folder = data_dir / "voices" / "cloned" / profile["voice_id"].split(":", 1)[1]
    assert (folder / "reference.wav").is_file()
    assert (folder / "reference.txt").read_text(encoding="utf-8") == "hello"
    assert (folder / "preview.wav").is_file()
    assert (folder / "voice_en.safetensors").is_file()
    assert (folder / "voice_fr.safetensors").is_file()
    labels = {row["language"]: row["label"] for row in voice_choices("en")}
    assert labels["en"].startswith("My Voice")
    assert "English" in labels["en"]
    assert "Français" in voice_choices("fr")[1]["label"] or "French" in voice_choices("en")[1]["label"]


def test_invalid_reference_does_not_create_a_profile(data_dir, tmp_path):
    source = tmp_path / "short.wav"
    _wav(source, _tone(0.5))
    before = list(data_dir.rglob("*"))
    with pytest.raises(CloneError) as rejected:
        build_profile(
            display_name="Nope",
            source_wav=source,
            source_kind="import",
            transcript="",
            consent=True,
            presented=CONSENT_STATEMENT,
            locale="fr",
            engine_version="2.1.0",
            service=_FakePocket(),
        )
    assert rejected.value.code == "clone-audio-rejected"
    assert list_profiles() == []
    assert not list((data_dir / "voices").glob("cloned/.partial-*"))
    del before


def test_delete_profile_keeps_model_cache(data_dir, tmp_path):
    source = tmp_path / "voice.wav"
    _wav(source, _tone(12.0))
    profile = build_profile(
        display_name="My Voice",
        source_wav=source,
        source_kind="import",
        transcript="",
        consent=True,
        presented=CONSENT_STATEMENT,
        locale="en",
        engine_version="2.1.0",
        service=_FakePocket(),
    )
    marker = pocket_model_dir() / "ready.json"
    marker.write_text("{}", encoding="utf-8")
    assert delete_profile(profile["voice_id"]) is True
    assert list_profiles() == []
    assert marker.is_file()
    with pytest.raises(CloneError) as missing:
        load_profile(profile["voice_id"])
    assert missing.value.code == "clone-profile-missing"


def test_models_ready_requires_cloning_weights(data_dir):
    marker = pocket_model_dir() / "ready.json"
    marker.write_text(
        json.dumps({"languages": {"english": {}, "french_24l": {}}}),
        encoding="utf-8",
    )
    assert clone_client.models_ready() is False
    marker.write_text(
        json.dumps({
            "languages": {"english": {}, "french_24l": {}},
            "voice_cloning": True,
        }),
        encoding="utf-8",
    )
    assert clone_client.models_ready() is True


def test_corrupt_profile_and_missing_language_state(data_dir):
    folder = data_dir / "voices" / "cloned" / ("ab" * 16)
    folder.mkdir(parents=True)
    (folder / "metadata.json").write_text("{", encoding="utf-8")
    with pytest.raises(CloneError) as corrupt:
        load_profile("clone:" + folder.name)
    assert corrupt.value.code == "clone-profile-corrupt"

    good = data_dir / "voices" / "cloned" / ("cd" * 16)
    good.mkdir()
    (good / "reference.wav").write_bytes(b"1234")
    (good / "reference.txt").write_text("", encoding="utf-8")
    (good / "voice_en.safetensors").write_bytes(b"x" * 80)
    metadata = {
        "profile_version": 1,
        "voice_id": f"clone:{good.name}",
        "display_name": "Half",
        "engine": "pocket-tts",
        "engine_version": "2.1.0",
        "created": "2026-10-07T00:00:00+00:00",
        "supported_languages": ["en"],
        "language_models": {"en": "english"},
        "reference_duration_s": 12,
        "reference_source": "import",
        "cached_profiles": {"en": "voice_en.safetensors"},
        "preview_file": "preview.wav",
        "consent": {"accepted": True, "statement": CONSENT_STATEMENT, "timestamp": "2026-10-07T00:00:00+00:00"},
    }
    (good / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    profile = load_profile(f"clone:{good.name}")
    assert resolve_language(profile, f"clone:{good.name}:en") == "en"
    with pytest.raises(CloneError) as french:
        resolve_language(profile, f"clone:{good.name}:fr")
    assert french.value.code == "clone-language"
    (good / "voice_en.safetensors").write_bytes(b"tiny")
    with pytest.raises(CloneError) as missing_state:
        resolve_language(profile, f"clone:{good.name}:en")
    assert missing_state.value.code == "clone-state-missing"


def test_routing_keeps_automatic_off_cloning_and_preserves_bookmarks():
    assert resolve_provider("auto", kokoro_ready=True) == "kokoro"
    assert resolve_provider("auto", kokoro_ready=False) == "piper"
    assert resolve_provider("clone", kokoro_ready=True) == "clone"
    assert resolve_provider("openai", kokoro_ready=False) == "openai"
    assert resolve_provider("kokoro", kokoro_ready=False) == "kokoro"
    assert resolve_provider("piper", kokoro_ready=True) == "piper"
    assert is_clone_voice("clone:abc:en")
    assert not is_clone_voice("kokoro:af_heart")
    assert is_kokoro_voice("kokoro:af_heart")
    assert not is_kokoro_voice("clone:abc:en")
    docs = [
        new_document(id="piper", provider="piper", voice="en_US-joe-medium", text="piper"),
        new_document(id="openai", provider="openai", voice="nova", text="openai"),
        new_document(id="kokoro", provider="kokoro", voice="kokoro:af_heart", text="kokoro"),
        new_document(id="clone", provider="clone", voice="clone:" + "ab" * 16 + ":fr", text="clone"),
    ]
    restored = validate_snapshot({"schema": 2, "activeId": "piper", "docs": docs})
    by_id = {doc["id"]: doc for doc in restored["docs"]}
    assert by_id["piper"]["provider"] == "piper" and by_id["piper"]["voice"] == "en_US-joe-medium"
    assert by_id["openai"]["provider"] == "openai" and by_id["openai"]["voice"] == "nova"
    assert by_id["kokoro"]["provider"] == "kokoro" and by_id["kokoro"]["voice"] == "kokoro:af_heart"
    assert by_id["clone"]["provider"] == "clone"
    assert by_id["clone"]["voice"].startswith("clone:")


def test_clone_strings_exist_in_french():
    missing = [key for key in i18n.STRINGS["en"] if key.startswith("clone.") and key not in i18n.STRINGS["fr"]]
    assert missing == []


def test_service_missing_does_not_touch_other_engines(monkeypatch):
    monkeypatch.setattr(clone_client, "clone_python", lambda: None)
    with pytest.raises(CloneError) as missing:
        CloneClient().ensure_running()
    assert missing.value.code == "clone-runtime-missing"


class _Bridge(QObject):
    synthesizeReady = Signal(str, str)
    openaiAudioReady = Signal(str, str, str)
    synthesizeError = Signal(str, str)
    openaiAudioError = Signal(str, str)

    def set_pronunciation_rules(self, _rules):
        return None

    def synthesize(self, *args):
        return None

    def cancel(self, _request):
        return None


def test_clone_playback_uses_the_long_form_chunk_size():
    manager = PlaybackManager(_Bridge())
    text = "This sentence stays with its neighbours. " * 20
    assert 260 < len(text) < 900
    document = {
        "id": "clone",
        "text": text,
        "voice": "clone:" + "ab" * 16 + ":en",
        "provider": "clone",
        "speed": 1.0,
        "volume": 1.0,
        "markdownMode": "auto",
        "effectiveRules": [],
    }
    assert manager.play(document)
    assert len(manager.chunks) == 1
    manager.stop()


def test_long_text_reuses_one_state_and_exports_wav_and_mp3(data_dir, tmp_path):
    source = tmp_path / "voice.wav"
    _wav(source, _tone(12.0))
    profile = build_profile(
        display_name="My Voice",
        source_wav=source,
        source_kind="import",
        transcript="",
        consent=True,
        presented=CONSENT_STATEMENT,
        locale="en",
        engine_version="2.1.0",
        service=_FakePocket(),
    )
    voice = profile["voice_id"] + ":en"
    calls = []

    class _Speaking:
        def synthesize_wav(self, state: Path, text: str, language: str) -> bytes:
            calls.append((state.name, language, text))
            return _pcm_wav()

    engine = CloneEngine(client=_Speaking())
    text = "First paragraph stays whole.\n\nSecond paragraph follows."
    pcm, rate, channels = engine.synthesize_pcm(text, voice)
    assert channels == 1 and rate == 24000
    assert [item[0] for item in calls] == ["voice_en.safetensors", "voice_en.safetensors"]
    assert [item[1] for item in calls] == ["english", "english"]
    assert calls[0][2].startswith("First")
    assert calls[1][2].startswith("Second")
    samples = np.frombuffer(pcm, dtype="<i2")
    gap = int(rate * PARAGRAPH_GAP_MS / 1000)
    zeros = np.where(samples == 0)[0]
    assert zeros.size >= gap

    french = engine.synthesize_pcm("Bonjour tout le monde.", profile["voice_id"] + ":fr")
    assert french[2] == 1
    assert calls[-1][0] == "voice_fr.safetensors"
    assert calls[-1][1] == "french_24l"

    wav, seconds, wav_rate, wav_channels = engine.export_audio(text, voice, "wav", 1.0, 1.0, 128)
    mp3, _seconds, mp3_rate, mp3_channels = engine.export_audio(text, voice, "mp3", 1.0, 1.0, 128)
    assert wav[:4] == b"RIFF"
    assert wav_rate == 24000 and wav_channels == 1 and seconds > 0
    assert mp3[:3] == b"ID3" or mp3[0] == 0xFF
    assert mp3_rate == 24000 and mp3_channels == 1 and len(mp3) > 100

    with pytest.raises(CloneError) as french_missing:
        engine.synthesize_pcm("Bonjour.", profile["voice_id"] + ":de")
    assert french_missing.value.code == "clone-language"
