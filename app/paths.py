"""Filesystem paths.

Resolves where to put voices / settings / logs based on two modes:

- **Portable**: everything lives next to the .exe (or next to main.py during dev).
  Triggered when a ``portable.flag`` file exists alongside the executable.
- **Installed**: voices in ``%APPDATA%/JojoLapin/TextSpeak Pro/`` on Windows,
  ``~/Library/Application Support/...`` on macOS, ``~/.local/share/...`` on Linux.
  Settings go through QSettings (registry on Windows).

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _exe_dir() -> Path:
    """Directory of the running app (PyInstaller bundle or main.py)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _bundle_dir() -> Path:
    """Directory where bundled read-only resources live.

    PyInstaller extracts data files into ``sys._MEIPASS`` at runtime for
    --onefile builds; during dev it's just the project root.
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
    return Path(__file__).resolve().parent.parent


def portable_flag_path() -> Path:
    return _exe_dir() / "portable.flag"


def is_portable() -> bool:
    # Manual opt-in: a file next to the exe forces portable mode
    if portable_flag_path().exists():
        return True
    # Env var override (useful for testing)
    if os.environ.get("TEXTSPEAK_PORTABLE", "").strip() in {"1", "true", "yes"}:
        return True
    return False


def set_portable(enabled: bool) -> None:
    flag = portable_flag_path()
    if enabled:
        try:
            flag.write_text("TextSpeak Pro portable mode\n", encoding="utf-8")
        except OSError:
            # Read-only install folder - fall through gracefully
            pass
    else:
        try:
            flag.unlink()
        except FileNotFoundError:
            pass


def _installed_user_dir() -> Path:
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "JojoLapin" / "TextSpeak Pro"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "TextSpeak Pro"
    # Linux / other Unix
    xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(xdg) / "TextSpeak Pro"


def user_data_dir() -> Path:
    p = _exe_dir() if is_portable() else _installed_user_dir()
    p.mkdir(parents=True, exist_ok=True)
    return p


def voices_dir() -> Path:
    p = user_data_dir() / "voices"
    p.mkdir(parents=True, exist_ok=True)
    return p


def logs_dir() -> Path:
    p = user_data_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_dir() -> Path:
    p = user_data_dir() / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def settings_ini() -> Path:
    return user_data_dir() / "settings.ini"


def bundled_resource(*relative_parts: str) -> Path:
    return _bundle_dir().joinpath(*relative_parts)


def ui_dir() -> Path:
    return bundled_resource("ui")


def resources_dir() -> Path:
    return bundled_resource("resources")


def voice_catalog_json() -> Path:
    return bundled_resource("voice_catalog.json")
