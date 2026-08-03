"""OpenAI text-to-speech provider.

Calls the OpenAI ``/v1/audio/speech`` endpoint with the bundled ``requests``
library. The API key is resolved on the Python side only (in-app setting first,
then a ``.env`` file, then the ``OPENAI_API_KEY`` environment variable) and is
never sent to the webview. All errors are sanitized so the key or raw provider
payloads can't leak into the UI or logs.

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from . import paths as app_paths
from .providers import VoiceProvider

log = logging.getLogger("textspeak.openai")

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini-tts"

# Voices supported by the speech endpoint (gpt-4o-mini-tts superset).
OPENAI_VOICES = [
    "alloy", "ash", "ballad", "coral", "echo",
    "fable", "nova", "onyx", "sage", "shimmer", "verse",
]
OPENAI_MODELS = ["gpt-4o-mini-tts", "tts-1", "tts-1-hd"]
# Formats the browser <audio> element can play back directly.
OPENAI_FORMATS = ["mp3", "wav", "opus", "aac", "flac"]
_MIME = {
    "mp3": "audio/mpeg", "wav": "audio/wav", "opus": "audio/ogg",
    "aac": "audio/aac", "flac": "audio/flac",
}
# Only the classic models accept a numeric speed; gpt-4o-* uses instructions.
_SPEED_MODELS = {"tts-1", "tts-1-hd"}


class OpenAIError(Exception):
    """Sanitized, user-safe error (never contains the API key)."""


# --------------------------------------------------------------------------- #
# .env parsing (tiny; avoids a python-dotenv dependency)
# --------------------------------------------------------------------------- #

def _parse_env_file(path: Path) -> dict:
    out: dict = {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return out
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.lower().startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            out[key] = value
    return out


def _env_files() -> list[Path]:
    """Candidate .env locations: user data dir first, then next to the app."""
    seen: list[Path] = []
    try:
        seen.append(app_paths.user_data_dir() / ".env")
    except Exception:  # noqa: BLE001
        pass
    try:
        exe_env = app_paths._exe_dir() / ".env"  # noqa: SLF001 - intentional
        if exe_env not in seen:
            seen.append(exe_env)
    except Exception:  # noqa: BLE001
        pass
    return seen


def _key_from_env_files() -> str:
    for p in _env_files():
        data = _parse_env_file(p)
        if data.get("OPENAI_API_KEY"):
            return data["OPENAI_API_KEY"].strip()
    return ""


@dataclass
class OpenAIConfig:
    api_key: str
    model: str
    base_url: str
    voice: str
    response_format: str
    key_source: str  # 'settings' | 'env-file' | 'env-var' | 'none'

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


def resolve_config(settings) -> OpenAIConfig:
    """Resolve the effective OpenAI config. Key precedence: in-app setting,
    then a .env file, then the OPENAI_API_KEY environment variable."""
    key = ""
    source = "none"

    setting_key = ""
    try:
        setting_key = (settings.get("openai_api_key", "") or "").strip()
    except Exception:  # noqa: BLE001
        setting_key = ""
    if setting_key:
        key, source = setting_key, "settings"
    else:
        file_key = _key_from_env_files()
        if file_key:
            key, source = file_key, "env-file"
        else:
            env_key = (os.environ.get("OPENAI_API_KEY", "") or "").strip()
            if env_key:
                key, source = env_key, "env-var"

    def _get(name, default):
        try:
            return settings.get(name, default) or default
        except Exception:  # noqa: BLE001
            return default

    base_url = (_get("openai_base_url", "") or "").strip() or DEFAULT_BASE_URL
    base_url = base_url.rstrip("/")
    model = _get("openai_model", DEFAULT_MODEL)
    voice = _get("openai_voice", "alloy")
    fmt = _get("openai_format", "mp3")
    if fmt not in OPENAI_FORMATS:
        fmt = "mp3"
    return OpenAIConfig(api_key=key, model=model, base_url=base_url,
                        voice=voice, response_format=fmt, key_source=source)


def mime_for(fmt: str) -> str:
    return _MIME.get(fmt, "audio/mpeg")


class OpenAIProvider(VoiceProvider):
    id = "openai"
    label = "OpenAI (online)"
    offline = False
    requires_network = True
    is_ai = True

    def __init__(self, settings, session=None) -> None:
        self._settings = settings
        # `session` injectable for tests; real requests import is lazy.
        self._session = session

    # ---- availability / status ----
    def config(self) -> OpenAIConfig:
        return resolve_config(self._settings)

    def is_available(self) -> Tuple[bool, str]:
        cfg = self.config()
        if cfg.configured:
            return True, f"Configured ({cfg.key_source})"
        return False, "API key not configured"

    # ---- synthesis ----
    def synthesize(
        self,
        text: str,
        *,
        voice: Optional[str] = None,
        model: Optional[str] = None,
        speed: float = 1.0,
        instructions: str = "",
        response_format: Optional[str] = None,
        cancel=None,
        timeout: float = 60.0,
    ) -> Tuple[bytes, str]:
        """Return ``(audio_bytes, mime)``. Raises :class:`OpenAIError`."""
        cfg = self.config()
        if not cfg.configured:
            raise OpenAIError("OpenAI API key is not configured.")
        if not (text and text.strip()):
            raise OpenAIError("Nothing to synthesize.")
        if cancel is not None and getattr(cancel, "cancelled", False):
            raise OpenAIError("cancelled")

        model = model or cfg.model
        voice = voice or cfg.voice
        fmt = response_format or cfg.response_format
        if fmt not in OPENAI_FORMATS:
            fmt = "mp3"

        body = {"model": model, "input": text, "voice": voice, "response_format": fmt}
        if model in _SPEED_MODELS:
            body["speed"] = max(0.25, min(4.0, float(speed) or 1.0))
        elif instructions:
            body["instructions"] = instructions

        url = f"{cfg.base_url}/audio/speech"
        headers = {"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"}

        session = self._session
        if session is None:
            import requests  # lazy; bundled
            session = requests

        try:
            resp = session.post(url, headers=headers, json=body, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - normalize every transport error
            raise OpenAIError(self._transport_error(exc)) from None

        if cancel is not None and getattr(cancel, "cancelled", False):
            raise OpenAIError("cancelled")

        status = getattr(resp, "status_code", 0)
        if status != 200:
            raise OpenAIError(self._http_error(status, resp))

        content = resp.content
        if not content:
            raise OpenAIError("OpenAI returned an empty audio response.")
        return content, mime_for(fmt)

    # ---- error sanitization (never leak the key or raw payloads) ----
    @staticmethod
    def _http_error(status: int, resp) -> str:
        mapping = {
            400: "OpenAI rejected the request (check the model, voice, or text).",
            401: "OpenAI rejected the API key (unauthorized).",
            403: "This OpenAI key isn't allowed to use text-to-speech.",
            404: "OpenAI model or endpoint not found.",
            408: "OpenAI request timed out.",
            413: "The text chunk is too large for OpenAI.",
            429: "OpenAI rate limit or quota exceeded. Try again later.",
            500: "OpenAI had a server error. Try again later.",
            502: "OpenAI is temporarily unavailable (bad gateway).",
            503: "OpenAI is temporarily unavailable. Try again later.",
        }
        msg = mapping.get(status)
        if msg:
            return msg
        # Attempt a short, safe reason from the JSON error without echoing keys.
        try:
            data = resp.json()
            reason = (data.get("error", {}) or {}).get("type") or ""
            if reason and isinstance(reason, str) and len(reason) < 60:
                return f"OpenAI error ({status}): {reason}"
        except Exception:  # noqa: BLE001
            pass
        return f"OpenAI request failed (HTTP {status})."

    @staticmethod
    def _transport_error(exc: Exception) -> str:
        name = type(exc).__name__.lower()
        if "timeout" in name:
            return "OpenAI request timed out. Check your connection."
        if "connection" in name or "connect" in name:
            return "Could not reach OpenAI. Check your internet connection."
        if "ssl" in name:
            return "A secure connection to OpenAI could not be established."
        return "Network error while contacting OpenAI."
