"""Settings store backed by QSettings.

Uses a portable INI next to the exe when portable mode is active, otherwise
falls back to the native backend (registry on Windows).

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import json
import os
from typing import Any

from PySide6.QtCore import QSettings

from . import APP_NAME, APP_ORG_DIR
from . import paths as app_paths


_DEFAULTS: dict[str, Any] = {
    "theme": "system",               # system | light | dark
    "language": "system",            # system | en | fr
    "last_voice": "",
    "last_speed": 1.0,
    "last_volume": 1.0,
    "mp3_bitrate": 128,
    "export_format": "mp3",          # mp3 | wav | ogg
    "id3_author": "",
    "window_geometry": "",           # base64 from QByteArray
    "window_state": "",
    "save_text": False,
    "saved_text": "",
    "saved_position": 0,
    "highlight": False,
    "auto_scroll": True,
    "wizard_complete": False,
    "recent_files": "[]",            # JSON list of absolute paths
    "presets": "[]",                 # JSON list of {name, voice, speed, volume, language}
    "bookmarks": "[]",               # JSON list of {id, position, preview, timestamp}
    "last_export_dir": "",
    # Markdown-aware reading
    "markdown_mode": "auto",         # auto | on | off
    "md_read_code": False,           # read code block contents verbatim
    "md_read_urls": False,           # read URLs in links
    "md_read_tables": True,          # read table rows as sentences
    # OpenAI voice provider (non-secret settings only; the API key is stored
    # under "openai_api_key" which is deliberately NOT listed here so it never
    # leaks through all()/get_prefs into the webview).
    "openai_model": "gpt-4o-mini-tts",
    "openai_voice": "alloy",
    "openai_format": "mp3",          # mp3 | wav | opus | aac | flac
    "openai_base_url": "",           # optional override; empty => official API
    "openai_text_model": "gpt-4o-mini",  # chat model for smart tools
    "ai_disclosure_ack": False,      # user acknowledged AI-voice disclosure
    # Non-destructive pronunciation: JSON list of global rules
    # [{from,to,whole_word,match_case,is_regex,enabled}]. Per-document rules live
    # in the workspace snapshot (IndexedDB), merged with these at play time.
    "pronunciation_rules": "[]",
    # Speaking style preset id (OpenAI delivery); "" => neutral/default.
    "speaking_style": "neutral",
}


# Settings keys that hold secrets and must never be returned by all()/get_prefs.
SECRET_KEYS = frozenset({"openai_api_key"})


class Settings:
    """Thin typed wrapper around QSettings."""

    def __init__(self) -> None:
        if app_paths.is_portable() or os.environ.get("TEXTSPEAK_DATA_DIR"):
            self._q = QSettings(str(app_paths.settings_ini()), QSettings.Format.IniFormat)
        else:
            self._q = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, APP_ORG_DIR, APP_NAME)

    # ---- generic get/set ----

    def get(self, key: str, default: Any = None) -> Any:
        if default is None:
            default = _DEFAULTS.get(key)
        v = self._q.value(key, default)
        # QSettings can return strings even for bools/numbers; coerce based on default type.
        if default is not None and type(default) is not type(v):
            try:
                if isinstance(default, bool):
                    if isinstance(v, str):
                        return v.strip().lower() in {"1", "true", "yes", "on"}
                    return bool(v)
                if isinstance(default, int):
                    return int(v)
                if isinstance(default, float):
                    return float(v)
                if isinstance(default, str):
                    return str(v)
            except (TypeError, ValueError):
                return default
        return v

    def set(self, key: str, value: Any) -> None:
        self._q.setValue(key, value)
        self._q.sync()

    def all(self) -> dict[str, Any]:
        return {k: self.get(k) for k in _DEFAULTS}

    # ---- helpers for JSON-encoded lists ----

    def get_json(self, key: str, default: Any) -> Any:
        raw = self.get(key, json.dumps(default))
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return default

    def set_json(self, key: str, value: Any) -> None:
        self.set(key, json.dumps(value, ensure_ascii=False))

    # ---- window geometry ----

    def save_window_geometry(self, geometry_bytes: bytes, state_bytes: bytes) -> None:
        import base64
        self.set("window_geometry", base64.b64encode(geometry_bytes).decode("ascii"))
        self.set("window_state", base64.b64encode(state_bytes).decode("ascii"))

    def load_window_geometry(self) -> tuple[bytes | None, bytes | None]:
        import base64
        g = self.get("window_geometry", "")
        s = self.get("window_state", "")
        try:
            gb = base64.b64decode(g) if g else None
            sb = base64.b64decode(s) if s else None
        except (ValueError, TypeError):
            return None, None
        return gb, sb

    # ---- recent files (MRU, max 10) ----

    def add_recent_file(self, path: str, limit: int = 10) -> list[str]:
        items: list[str] = self.get_json("recent_files", [])
        items = [p for p in items if p != path]
        items.insert(0, path)
        items = items[:limit]
        self.set_json("recent_files", items)
        return items

    def clear_recent_files(self) -> None:
        self.set_json("recent_files", [])
