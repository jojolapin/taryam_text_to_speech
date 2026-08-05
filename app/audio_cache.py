"""Content-hash audio cache for synthesized speech.

Reusable OpenAI (and future provider) audio lives under
``<data>/cache/audio/``. Cache keys are SHA-256 digests of
``(provider, model, voice, style, format, text)``. Entries can be tagged with
tab ids so Settings can clear audio per tab without touching document text.

Piper voice-preview samples still live under ``cache/samples/``; this module
can report and clear them as the "Piper" cache bucket.

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import threading
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import paths as app_paths

log = logging.getLogger("textspeak.cache")

_INDEX_NAME = "index.json"


def audio_cache_dir() -> Path:
    p = app_paths.cache_dir() / "audio"
    p.mkdir(parents=True, exist_ok=True)
    return p


def samples_cache_dir() -> Path:
    p = app_paths.cache_dir() / "samples"
    p.mkdir(parents=True, exist_ok=True)
    return p


def make_key(
    *,
    provider: str,
    model: str,
    voice: str,
    style: str,
    fmt: str,
    text: str,
) -> str:
    """Stable content hash for an identical synthesis request."""
    payload = "\n".join([
        (provider or "").strip().lower(),
        (model or "").strip(),
        (voice or "").strip(),
        (style or "").strip(),
        (fmt or "mp3").strip().lower(),
        text or "",
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def join_audio_parts(parts: List[bytes], fmt: str) -> bytes:
    """Join sequential synthesis chunks into one playable file.

    MP3: frame concatenation (works with most players).
    WAV: strip headers and rewrite a single RIFF header.
    Other formats: only valid for a single part (multi-part raises).
    """
    parts = [p for p in parts if p]
    if not parts:
        return b""
    fmt = (fmt or "mp3").lower()
    if len(parts) == 1:
        return parts[0]
    if fmt == "mp3":
        return b"".join(parts)
    if fmt == "wav":
        return _join_wav(parts)
    raise ValueError(
        f"Cannot join multiple {fmt} chunks; export as MP3 or WAV instead."
    )


def _join_wav(parts: List[bytes]) -> bytes:
    frames: List[bytes] = []
    params = None
    for raw in parts:
        with wave.open(io.BytesIO(raw), "rb") as w:
            cur = w.getparams()
            if params is None:
                params = cur
            elif (cur.nchannels, cur.sampwidth, cur.framerate) != (
                params.nchannels, params.sampwidth, params.framerate
            ):
                raise ValueError("WAV chunk parameters do not match.")
            frames.append(w.readframes(w.getnframes()))
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        assert params is not None
        w.setparams(params)
        for f in frames:
            w.writeframes(f)
    return out.getvalue()


def _dir_size(path: Path) -> Tuple[int, int]:
    total = 0
    count = 0
    if not path.exists():
        return 0, 0
    for p in path.rglob("*"):
        if p.is_file() and p.name != _INDEX_NAME:
            try:
                total += p.stat().st_size
                count += 1
            except OSError:
                pass
    return total, count


class AudioCache:
    """On-disk content-hash cache with optional tab tagging."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root else audio_cache_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self._index_path = self.root / _INDEX_NAME
        self._lock = threading.RLock()
        self._index: Dict[str, Any] = self._load_index()

    # ---- persistence ----
    def _load_index(self) -> Dict[str, Any]:
        if not self._index_path.exists():
            return {"entries": {}}
        try:
            data = json.loads(self._index_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {"entries": {}}
            data.setdefault("entries", {})
            return data
        except (OSError, ValueError, TypeError):
            return {"entries": {}}

    def _save_index(self) -> None:
        try:
            tmp = self._index_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._index, ensure_ascii=False, indent=0),
                encoding="utf-8",
            )
            tmp.replace(self._index_path)
        except OSError as e:
            log.warning("Could not write audio cache index: %s", e)

    def _path_for(self, key: str, ext: str) -> Path:
        safe_ext = (ext or "bin").lstrip(".").lower() or "bin"
        return self.root / f"{key}.{safe_ext}"

    # ---- get / put ----
    def get(self, key: str) -> Optional[bytes]:
        with self._lock:
            entry = self._index.get("entries", {}).get(key)
            if not entry:
                return None
            path = self.root / entry.get("file", "")
            if not path.is_file():
                self._index["entries"].pop(key, None)
                self._save_index()
                return None
            try:
                return path.read_bytes()
            except OSError:
                return None

    def put(
        self,
        key: str,
        data: bytes,
        *,
        provider: str = "openai",
        fmt: str = "mp3",
        tab_id: str = "",
    ) -> Path:
        with self._lock:
            path = self._path_for(key, fmt)
            path.write_bytes(data)
            entries = self._index.setdefault("entries", {})
            prev = entries.get(key) or {}
            tabs = list(prev.get("tabs") or [])
            tid = (tab_id or "").strip()
            if tid and tid not in tabs:
                tabs.append(tid)
            entries[key] = {
                "file": path.name,
                "provider": (provider or "openai").lower(),
                "format": (fmt or "mp3").lower(),
                "size": len(data),
                "tabs": tabs,
            }
            self._save_index()
            return path

    def touch_tab(self, key: str, tab_id: str) -> None:
        """Associate an existing cache entry with a tab (e.g. after a hit)."""
        tid = (tab_id or "").strip()
        if not tid:
            return
        with self._lock:
            entry = self._index.get("entries", {}).get(key)
            if not entry:
                return
            tabs = list(entry.get("tabs") or [])
            if tid not in tabs:
                tabs.append(tid)
                entry["tabs"] = tabs
                self._save_index()

    # ---- stats / clear ----
    def stats(self) -> dict:
        with self._lock:
            by_provider: Dict[str, dict] = {}
            by_tab: Dict[str, dict] = {}
            total_bytes = 0
            count = 0
            for key, entry in list(self._index.get("entries", {}).items()):
                path = self.root / entry.get("file", "")
                size = int(entry.get("size") or 0)
                if path.is_file():
                    try:
                        size = path.stat().st_size
                    except OSError:
                        pass
                else:
                    self._index["entries"].pop(key, None)
                    continue
                provider = (entry.get("provider") or "openai").lower()
                bp = by_provider.setdefault(provider, {"bytes": 0, "count": 0})
                bp["bytes"] += size
                bp["count"] += 1
                for tid in entry.get("tabs") or []:
                    bt = by_tab.setdefault(tid, {"bytes": 0, "count": 0})
                    bt["bytes"] += size
                    bt["count"] += 1
                total_bytes += size
                count += 1
            self._save_index()

        sample_bytes, sample_count = _dir_size(samples_cache_dir())
        by_provider.setdefault("piper", {"bytes": 0, "count": 0})
        by_provider["piper"]["bytes"] += sample_bytes
        by_provider["piper"]["count"] += sample_count

        return {
            "audioBytes": total_bytes,
            "audioCount": count,
            "sampleBytes": sample_bytes,
            "sampleCount": sample_count,
            "totalBytes": total_bytes + sample_bytes,
            "byProvider": by_provider,
            "byTab": by_tab,
            "path": str(self.root),
        }

    def clear(
        self,
        *,
        provider: Optional[str] = None,
        tab_id: Optional[str] = None,
        include_samples: bool = False,
    ) -> dict:
        """Clear cache entries. Never touches document/tab text.

        - ``provider='openai'``: remove OpenAI audio entries
        - ``provider='piper'``: remove voice samples (``cache/samples``)
        - ``tab_id=...``: drop that tab's association; delete file if no tabs left
          (untagged entries are left alone unless provider clear)
        - both None + ``include_samples``: wipe all audio (+ samples if True)
        """
        removed_bytes = 0
        removed_count = 0
        tid = (tab_id or "").strip() if tab_id is not None else None
        prov = (provider or "").strip().lower() if provider else None

        with self._lock:
            entries = self._index.setdefault("entries", {})
            to_delete: List[str] = []
            for key, entry in list(entries.items()):
                eprov = (entry.get("provider") or "openai").lower()
                tabs = list(entry.get("tabs") or [])

                if tid is not None:
                    if tid not in tabs:
                        continue
                    tabs = [t for t in tabs if t != tid]
                    entry["tabs"] = tabs
                    # Only delete the file when this was the last referencing tab.
                    if tabs:
                        continue
                    to_delete.append(key)
                    continue

                if prov is not None:
                    if eprov != prov:
                        continue
                    to_delete.append(key)
                    continue

                # Full audio clear (no provider/tab filter)
                to_delete.append(key)

            for key in to_delete:
                entry = entries.pop(key, None) or {}
                path = self.root / entry.get("file", "")
                size = int(entry.get("size") or 0)
                if path.is_file():
                    try:
                        size = path.stat().st_size
                        path.unlink()
                    except OSError:
                        pass
                removed_bytes += size
                removed_count += 1
            self._save_index()

        if include_samples or prov == "piper":
            sb, sc = self._clear_samples()
            removed_bytes += sb
            removed_count += sc

        return {"removedBytes": removed_bytes, "removedCount": removed_count}

    @staticmethod
    def _clear_samples() -> Tuple[int, int]:
        root = samples_cache_dir()
        removed_bytes = 0
        removed_count = 0
        if not root.exists():
            return 0, 0
        for p in list(root.iterdir()):
            if not p.is_file():
                continue
            try:
                size = p.stat().st_size
                p.unlink()
                removed_bytes += size
                removed_count += 1
            except OSError:
                pass
        return removed_bytes, removed_count
