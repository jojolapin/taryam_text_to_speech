"""Voice catalog: browse + download free Piper voices.

The bundled ``voice_catalog.json`` ships with ~50 curated voices. At runtime
the UI can hit "Refresh catalog" which fetches the canonical ``voices.json``
from the HuggingFace ``rhasspy/piper-voices`` repo and merges in any new
entries. Downloads are plain HTTPS GETs (no dependency on the piper CLI).

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Callable, Iterable, Optional

from . import paths as app_paths


log = logging.getLogger("textspeak.catalog")

HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
HF_VOICES_JSON = f"{HF_BASE}/voices.json"


def _fetch_bytes(url: str, timeout: float = 30.0) -> bytes:
    import requests  # local import keeps top-level import cheap

    resp = requests.get(url, timeout=timeout, stream=False)
    resp.raise_for_status()
    return resp.content


def _stream_download(url: str, dest: Path, *, progress: Optional[Callable[[int, int], None]] = None,
                     chunk_size: int = 64 * 1024, cancel: Optional[threading.Event] = None) -> None:
    import requests

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length", 0) or 0)
        done = 0
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if cancel is not None and cancel.is_set():
                    f.close()
                    tmp.unlink(missing_ok=True)
                    raise KeyboardInterrupt("download cancelled")
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    tmp.replace(dest)


def _path_for_id(voice_id: str) -> str:
    """Convert ``en_US-lessac-medium`` into the HuggingFace folder path
    ``en/en_US/lessac/medium``."""
    # Format: <lang>_<region>-<speaker>-<quality>
    try:
        locale, speaker, quality = voice_id.split("-", 2)
        lang = locale.split("_", 1)[0]
    except ValueError:
        raise ValueError(f"Unexpected voice id: {voice_id!r}")
    return f"{lang}/{locale}/{speaker}/{quality}"


def onnx_url(voice_id: str) -> str:
    return f"{HF_BASE}/{_path_for_id(voice_id)}/{voice_id}.onnx"


def config_url(voice_id: str) -> str:
    return f"{HF_BASE}/{_path_for_id(voice_id)}/{voice_id}.onnx.json"


def sample_url(voice_id: str) -> str:
    return f"{HF_BASE}/{_path_for_id(voice_id)}/samples/speaker_0.mp3"


def load_bundled_catalog() -> list[dict]:
    path = app_paths.voice_catalog_json()
    if not path.exists():
        log.warning("Bundled catalog missing at %s", path)
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return list(data.get("voices") or [])
    except Exception as e:  # noqa: BLE001
        log.warning("Could not read bundled catalog: %s", e)
        return []


def load_user_catalog() -> list[dict]:
    """Optional user-managed override (saved after Refresh)."""
    p = app_paths.user_data_dir() / "voice_catalog.user.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return list(data.get("voices") or [])
    except Exception as e:  # noqa: BLE001
        log.warning("Could not read user catalog: %s", e)
        return []


def save_user_catalog(voices: Iterable[dict]) -> None:
    p = app_paths.user_data_dir() / "voice_catalog.user.json"
    payload = {"voices": list(voices)}
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_catalogs(a: list[dict], b: list[dict]) -> list[dict]:
    """Merge b over a (b wins on id collision); preserves ordering from a then b-new."""
    by_id: dict[str, dict] = {v["id"]: dict(v) for v in a}
    for v in b:
        by_id[v["id"]] = {**by_id.get(v["id"], {}), **v}
    return list(by_id.values())


def full_catalog() -> list[dict]:
    return merge_catalogs(load_bundled_catalog(), load_user_catalog())


def refresh_from_hf(timeout: float = 30.0) -> list[dict]:
    """Fetch the canonical HuggingFace ``voices.json`` and flatten it into
    our schema. Returns the flattened list AND persists it as the user catalog."""
    raw = _fetch_bytes(HF_VOICES_JSON, timeout=timeout)
    payload = json.loads(raw.decode("utf-8"))
    flat: list[dict] = []
    for vid, meta in payload.items():
        try:
            lang = meta.get("language", {}).get("code") or ""
            country = meta.get("language", {}).get("name_native") or meta.get("language", {}).get("country_english") or ""
            speaker = (meta.get("speaker_id_map") or {}).get("0") or vid.split("-")[-2] if "-" in vid else ""
            quality = meta.get("quality") or vid.split("-")[-1]
            size_mb = 0
            files = meta.get("files") or {}
            for fname, info in files.items():
                if fname.endswith(".onnx"):
                    size_mb = round(info.get("size_bytes", 0) / (1024 * 1024), 1)
                    break
            flat.append({
                "id": vid,
                "language": lang,
                "country": country,
                "speaker": speaker,
                "gender": "",
                "quality": quality,
                "size_mb": size_mb,
                "sample_text": "",
            })
        except Exception as e:  # noqa: BLE001
            log.warning("Skipping catalog entry %s: %s", vid, e)
    flat.sort(key=lambda v: v["id"])
    save_user_catalog(flat)
    return flat


def installed_ids() -> set[str]:
    return {p.stem for p in app_paths.voices_dir().glob("*.onnx")}


def download_voice(voice_id: str, *, progress: Optional[Callable[[int, int], None]] = None,
                   cancel: Optional[threading.Event] = None) -> tuple[Path, Path]:
    """Download ``<id>.onnx`` + ``<id>.onnx.json`` into the voices folder."""
    dest_onnx = app_paths.voices_dir() / f"{voice_id}.onnx"
    dest_json = app_paths.voices_dir() / f"{voice_id}.onnx.json"

    # Small config first so we can fail fast if voice id is wrong.
    _stream_download(config_url(voice_id), dest_json, cancel=cancel)
    _stream_download(onnx_url(voice_id), dest_onnx, progress=progress, cancel=cancel)
    return dest_onnx, dest_json


def fetch_sample(voice_id: str) -> Optional[bytes]:
    """Fetch and cache a short audio sample for a voice. Returns bytes or None."""
    cache = app_paths.cache_dir() / "samples"
    cache.mkdir(parents=True, exist_ok=True)
    local = cache / f"{voice_id}.mp3"
    if local.exists() and local.stat().st_size > 0:
        return local.read_bytes()
    try:
        data = _fetch_bytes(sample_url(voice_id), timeout=30.0)
        local.write_bytes(data)
        return data
    except Exception as e:  # noqa: BLE001
        log.info("Sample unavailable for %s: %s", voice_id, e)
        return None
