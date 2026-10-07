"""Cloned voice profiles stored beside the other user voices.

A profile is one speaker. English and French each get their own Pocket TTS
state, because ``export-voice --language`` binds the file to that checkpoint.
The same reference recording is encoded twice. One state is not reused for
the other language.

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..paths import user_data_dir
from .clone_errors import CloneError
from .reference_audio import prepare_wav

PROFILE_VERSION = 1
ENGINE_ID = "pocket-tts"
CONSENT_STATEMENT = (
    "I confirm that this is my voice or that I have permission to create and use this voice profile."
)
PREVIEW_TEXT = {
    "en": "This is a preview of my cloned voice in TextSpeak Pro.",
    "fr": "Ceci est un aperçu de ma voix clonée dans TextSpeak Pro.",
}
# Pocket TTS 2.1.0 rejects language="french" and tells the caller to use the
# 24-layer French model. English and French are therefore different checkpoints.
POCKET_LANGUAGE = {"en": "english", "fr": "french_24l"}
_ID = re.compile(r"^[0-9a-f]{32}$")


def cloned_voices_dir() -> Path:
    path = user_data_dir() / "voices" / "cloned"
    path.mkdir(parents=True, exist_ok=True)
    return path


def pocket_model_dir() -> Path:
    path = user_data_dir() / "models" / "pocket"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def split_voice_id(voice_id: str) -> tuple[str, str]:
    """Return ``(profile_id, language)`` from ``clone:<id>`` or ``clone:<id>:en``."""
    raw = voice_id or ""
    if raw.startswith("clone:"):
        raw = raw.split(":", 1)[1]
    if ":" in raw:
        profile_id, language = raw.split(":", 1)
        return profile_id, language.strip().lower()
    return raw, ""


def storage_id(profile_id: str, language: str) -> str:
    return f"clone:{profile_id}:{language}"


def _folder(profile_id: str) -> Path:
    if not _ID.fullmatch(profile_id or ""):
        raise CloneError("clone-profile-missing", profile_id)
    return cloned_voices_dir() / profile_id


def _relative_name(value: str) -> str:
    path = Path(str(value or ""))
    if path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
        raise CloneError("clone-profile-corrupt", str(value))
    return path.name


def _read_metadata(folder: Path) -> dict:
    path = folder / "metadata.json"
    if not path.is_file():
        raise CloneError("clone-profile-missing", folder.name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CloneError("clone-profile-corrupt", folder.name) from exc
    if not isinstance(data, dict):
        raise CloneError("clone-profile-corrupt", folder.name)
    consent = data.get("consent")
    if not isinstance(consent, dict) or consent.get("accepted") is not True:
        raise CloneError("clone-profile-corrupt", "consent")
    for key in ("profile_version", "voice_id", "display_name", "engine", "cached_profiles"):
        if key not in data:
            raise CloneError("clone-profile-corrupt", key)
    if data.get("engine") != ENGINE_ID:
        raise CloneError("clone-profile-corrupt", str(data.get("engine")))
    cached = data.get("cached_profiles")
    if not isinstance(cached, dict) or not cached:
        raise CloneError("clone-profile-corrupt", "cached_profiles")
    for name in cached.values():
        _relative_name(str(name))
    return data


def list_profiles() -> list[dict]:
    found = []
    root = cloned_voices_dir()
    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        try:
            found.append(_read_metadata(folder))
        except CloneError:
            continue
    return found


def load_profile(voice_id: str) -> dict:
    profile_id, _language = split_voice_id(voice_id)
    return _read_metadata(_folder(profile_id))


def profile_file(profile: dict, name: str) -> Path:
    profile_id, _language = split_voice_id(str(profile.get("voice_id", "")))
    return _folder(profile_id) / _relative_name(name)


def state_file(profile: dict, language: str) -> Path:
    cached = profile.get("cached_profiles") or {}
    name = cached.get(language)
    if not name:
        raise CloneError("clone-language", language)
    path = profile_file(profile, str(name))
    if not path.is_file() or path.stat().st_size < 64:
        raise CloneError("clone-state-missing", language)
    return path


def resolve_language(profile: dict, voice_id: str) -> str:
    _profile_id, requested = split_voice_id(voice_id)
    languages = [str(item) for item in profile.get("supported_languages") or []]
    language = requested or ("en" if "en" in languages else (languages[0] if languages else ""))
    if language not in languages:
        raise CloneError("clone-language", language or requested)
    state_file(profile, language)
    return language


def voice_choices(lang: str) -> list[dict]:
    """Selector rows. The label is the display name, not the Pocket file name."""
    from .. import i18n

    rows = []
    for profile in list_profiles():
        profile_id, _language = split_voice_id(str(profile["voice_id"]))
        name = str(profile.get("display_name") or "Voice")
        for language in profile.get("supported_languages") or []:
            try:
                state_file(profile, str(language))
            except CloneError:
                continue
            label = i18n.t("clone.voice.label", lang, name=name, language=i18n.t(f"clone.lang.{language}", lang))
            rows.append({
                "storage_id": storage_id(profile_id, str(language)),
                "label": label,
                "language": str(language),
                "display_name": name,
            })
    return rows


def delete_profile(voice_id: str) -> bool:
    profile_id, _language = split_voice_id(voice_id)
    folder = _folder(profile_id)
    if not folder.exists():
        return False
    shutil.rmtree(folder)
    return True


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_profile(
    *,
    display_name: str,
    source_wav: Path,
    source_kind: str,
    transcript: str,
    consent: bool,
    presented: str,
    locale: str,
    engine_version: str,
    service,
    ui_language: str = "en",
) -> dict:
    """Encode English and French states. The profile is invisible until this returns."""
    if not consent:
        raise CloneError("clone-consent", "")
    name = (display_name or "").strip()
    if not name:
        raise CloneError("clone-audio-rejected", "name")
    profile_id = uuid.uuid4().hex
    root = cloned_voices_dir()
    staging = root / f".partial-{profile_id}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        reference = staging / "reference.wav"
        report, actions = prepare_wav(Path(source_wav), reference)
        if report.level == "error":
            raise CloneError("clone-audio-rejected", ",".join(report.notes))
        (staging / "reference.txt").write_text(transcript or "", encoding="utf-8")
        cached = {}
        previews = {}
        for language, pocket_name in POCKET_LANGUAGE.items():
            dest = staging / f"voice_{language}.safetensors"
            service.export_state(reference, dest, pocket_name)
            if not dest.is_file() or dest.stat().st_size < 64:
                raise CloneError("clone-state-missing", language)
            preview = service.synthesize_wav(dest, PREVIEW_TEXT[language], pocket_name)
            preview_name = f"preview_{language}.wav"
            (staging / preview_name).write_bytes(preview)
            cached[language] = dest.name
            previews[language] = preview_name
        shown = "fr" if ui_language == "fr" else "en"
        shutil.copyfile(staging / previews[shown], staging / "preview.wav")
        metadata = {
            "profile_version": PROFILE_VERSION,
            "voice_id": f"clone:{profile_id}",
            "display_name": name,
            "engine": ENGINE_ID,
            "engine_version": engine_version,
            "created": _now(),
            "supported_languages": ["en", "fr"],
            "language_models": dict(POCKET_LANGUAGE),
            "reference_duration_s": report.duration_s,
            "reference_speech_s": report.speech_s,
            "reference_source": source_kind if source_kind in {"import", "record"} else "import",
            "reference_wav": "reference.wav",
            "reference_txt": "reference.txt",
            "preparation": actions,
            "cached_profiles": cached,
            "previews": previews,
            "preview_file": "preview.wav",
            "consent": {
                "accepted": True,
                "statement": CONSENT_STATEMENT,
                "presented": presented,
                "locale": locale if locale in {"en", "fr"} else "en",
                "timestamp": _now(),
            },
        }
        _write_json(staging / "metadata.json", metadata)
        final = root / profile_id
        staging.rename(final)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return load_profile(profile_id)
