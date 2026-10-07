"""OpenAI text-to-speech provider.

Calls the OpenAI ``/v1/audio/speech`` endpoint with the bundled ``requests``
library. The API key is resolved on the Python side only (in-app setting first,
then a ``.env`` file, then the ``OPENAI_API_KEY`` environment variable) and is
never sent to the webview. All errors are sanitized so the key or raw provider
payloads can't leak into the UI or logs.

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional, Tuple

from . import paths as app_paths
from .providers import VoiceProvider

log = logging.getLogger("textspeak.openai")

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini-tts"
# Chat model used by the "smart tools" (clean / translate / summarize / explain).
DEFAULT_TEXT_MODEL = "gpt-4o-mini"

# Smart-tool tasks -> system prompt. Prompts insist on returning ONLY the
# transformed text (no preamble) and preserving the source language unless the
# task is an explicit translation. Kept in English; the models follow reliably.
SMART_TASKS = {
    "clean": (
        "You are a meticulous copy editor. Fix spelling, punctuation, spacing "
        "and obvious grammar mistakes in the user's text WITHOUT changing its "
        "meaning, tone, language or structure. Do not add or remove content. "
        "Return ONLY the corrected text, with no comments or preamble."
    ),
    "summarize": (
        "You are a concise summarizer. Produce a clear, faithful summary of the "
        "user's text in the SAME language as the text. Keep the key points. "
        "Return ONLY the summary, with no preamble."
    ),
    "explain": (
        "You explain things simply. Rewrite the user's text so a general "
        "audience can understand it, in the SAME language as the text, keeping "
        "it accurate. Return ONLY the explanation, with no preamble."
    ),
    "translate": (
        "You are a professional translator. Translate the user's text into "
        "{target}. Preserve meaning, tone and formatting. Return ONLY the "
        "translation, with no preamble."
    ),
}

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
    """Sanitized, user-safe error (never contains the API key).

    ``limit`` is set for HTTP 429. It holds OpenAI's own code, message, request
    id, and reset information so the dialog can show proof without a second call.
    """

    def __init__(self, message: str, limit: Optional[dict] = None) -> None:
        super().__init__(message)
        self.limit = limit


# Record separator wrapped in a marker that cannot appear in a normal sentence.
LIMIT_MARKER = "\u241eOPENAI_LIMIT\u241e"

_SECRET = re.compile(r"(sk-[A-Za-z0-9_\-]{6,})|(Bearer\s+\S+)", re.IGNORECASE)
_IDENT = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_NUM = re.compile(r"^\d+(?:\.\d+)?$")
_DURATION = re.compile(
    r"^(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?(?:(\d+(?:\.\d+)?)ms)?$"
)
_TRY_AGAIN = re.compile(
    r"try again in\s+(\d+(?:\.\d+)?)\s*"
    r"(milliseconds|millisecond|seconds|second|minutes|minute|hours|hour|ms|secs|sec|mins|min|s|m|h)?",
    re.IGNORECASE,
)
_BUCKETS = (
    ("requests", "x-ratelimit-limit-requests", "x-ratelimit-remaining-requests", "x-ratelimit-reset-requests"),
    ("tokens", "x-ratelimit-limit-tokens", "x-ratelimit-remaining-tokens", "x-ratelimit-reset-tokens"),
    ("project_tokens", "x-ratelimit-limit-project-tokens", "x-ratelimit-remaining-project-tokens", "x-ratelimit-reset-project-tokens"),
)
_DELAY_UNIT = {
    "ms": "ms", "millisecond": "ms", "milliseconds": "ms",
    "s": "s", "sec": "s", "secs": "s", "second": "s", "seconds": "s",
    "m": "m", "min": "m", "mins": "m", "minute": "m", "minutes": "m",
    "h": "h", "hour": "h", "hours": "h",
}


def format_openai_error(exc: BaseException) -> str:
    """Signal payload. A plain message, or a marker plus the 429 report."""
    limit = getattr(exc, "limit", None)
    if not isinstance(limit, dict):
        return str(exc)
    payload = {"summary": str(exc), "limit": limit}
    return LIMIT_MARKER + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def is_openai_limit_message(message: str) -> bool:
    return bool(message) and LIMIT_MARKER in message


def decode_openai_limit(message: str) -> Optional[dict]:
    """Return ``{"summary", "limit"}`` when ``message`` carries a 429 report."""
    if not is_openai_limit_message(message):
        return None
    raw = message.split(LIMIT_MARKER, 1)[1]
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("limit"), dict):
        return None
    return data


def openai_error_summary(message: str) -> str:
    """Short text for the status line and the log. Never the raw payload."""
    if not message or LIMIT_MARKER not in message:
        return message
    data = decode_openai_limit(message)
    summary = data.get("summary") if data else ""
    if summary:
        return str(summary)
    head = message.split(LIMIT_MARKER, 1)[0].strip()
    return head or "OpenAI rate limit or quota exceeded."


def parse_delay_seconds(value: str, *, now: Optional[float] = None) -> Optional[float]:
    """Parse Retry-After seconds, an HTTP date, or OpenAI's ``6m0s`` duration."""
    raw = (value or "").strip()
    if not raw or len(raw) > 80:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        seconds = None
    else:
        if math.isfinite(seconds) and 0 <= seconds <= 366 * 86400:
            return seconds
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError, OverflowError):
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        base = time.time() if now is None else now
        return max(0.0, min(366 * 86400, parsed.timestamp() - base))
    match = _DURATION.match(raw.lower().replace(" ", ""))
    if not match or not any(match.groups()):
        return None
    days, hours, minutes, secs, millis = match.groups()
    total = 0.0
    if days:
        total += int(days) * 86400
    if hours:
        total += int(hours) * 3600
    if minutes:
        total += int(minutes) * 60
    if secs:
        total += float(secs)
    if millis:
        total += float(millis) / 1000.0
    if total > 366 * 86400:
        return None
    return total


def _clean_text(value: str, limit: int = 500) -> str:
    text = _SECRET.sub("[redacted]", value or "")
    text = "".join(ch for ch in text if ch == "\n" or ord(ch) >= 32)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _ident(value) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    return value if _IDENT.match(value) else ""


def _num(value: str) -> str:
    value = (value or "").strip()
    return value if _NUM.match(value) else ""


def _header_map(resp) -> dict:
    headers = getattr(resp, "headers", None)
    if not headers:
        return {}
    try:
        items = list(headers.items())
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for key, value in items:
        if key is None or value is None:
            continue
        out[str(key).lower()] = str(value).strip()
    return out


def _error_body(resp) -> dict:
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001
        return {}
    err = data.get("error") if isinstance(data, dict) else None
    return err if isinstance(err, dict) else {}


def _classify(code: str, error_type: str, message: str) -> str:
    code_l = code.lower()
    type_l = error_type.lower()
    if code_l in {"rate_limit_exceeded", "slow_down"} or type_l in {"rate_limit_error", "requests", "tokens"}:
        return "rate_limit"
    if code_l == "credit_balance_exhausted":
        return "credits"
    if code_l == "organization_spend_limit_exceeded":
        return "org_spend"
    if code_l == "project_spend_limit_exceeded":
        return "project_spend"
    if code_l == "organization_usage_limit_exceeded":
        return "usage_limit"
    if code_l == "insufficient_quota" or type_l == "insufficient_quota":
        return "quota"
    lowered = message.lower()
    if "rate limit" in lowered or "too many requests" in lowered:
        return "rate_limit"
    if any(word in lowered for word in ("quota", "billing", "credit", "spend limit")):
        return "quota"
    return "unknown"


def _delay_from_message(message: str) -> Optional[float]:
    match = _TRY_AGAIN.search(message or "")
    if not match:
        return None
    unit = _DELAY_UNIT.get((match.group(2) or "s").lower(), "s")
    return parse_delay_seconds(f"{match.group(1)}{unit}")


def _next_utc_month(now: float) -> float:
    """Start of the next calendar month at 00:00 UTC.

    OpenAI documents monthly spend limits as resetting on the next monthly
    cycle, and its usage pages are counted in UTC. The response itself does
    not include that timestamp.
    """
    current = datetime.fromtimestamp(now, timezone.utc)
    year = current.year + (1 if current.month == 12 else 0)
    month = 1 if current.month == 12 else current.month + 1
    return datetime(year, month, 1, tzinfo=timezone.utc).timestamp()


def _buckets(headers: dict, now: float) -> list:
    found = []
    for name, limit_header, remain_header, reset_header in _BUCKETS:
        limit = _num(headers.get(limit_header, ""))
        remaining = _num(headers.get(remain_header, ""))
        delay = parse_delay_seconds(headers.get(reset_header, ""), now=now)
        if not limit and not remaining and delay is None:
            continue
        item = {"name": name, "reset_header": reset_header}
        if limit:
            item["limit"] = limit
        if remaining:
            item["remaining"] = remaining
        if delay is not None:
            item["reset_seconds"] = delay
            item["resets_at"] = now + delay
        found.append(item)
    return found


def _choose_reset(kind: str, now: float, retry_after, buckets, message_delay):
    """Return ``(resets_at, source, seconds)``.

    Billing errors are not cleared by waiting, so a Retry-After header on those
    responses is ignored. A rate limit uses the longest exhausted bucket.
    """
    if kind in {"org_spend", "project_spend"}:
        resets = _next_utc_month(now)
        return resets, "monthly-utc", max(0.0, resets - now)
    if kind != "rate_limit":
        return None, "", None
    exhausted = [
        bucket for bucket in buckets
        if bucket.get("remaining") == "0" and bucket.get("reset_seconds") is not None
    ]
    candidates = []
    if exhausted:
        candidates.extend((bucket["reset_header"], bucket["reset_seconds"]) for bucket in exhausted)
        if retry_after is not None:
            candidates.append(("retry-after", retry_after))
    elif retry_after is not None:
        candidates.append(("retry-after", retry_after))
    else:
        candidates.extend(
            (bucket["reset_header"], bucket["reset_seconds"])
            for bucket in buckets if bucket.get("reset_seconds") is not None
        )
        if not candidates and message_delay is not None:
            candidates.append(("message", message_delay))
    if not candidates:
        if message_delay is not None:
            return now + message_delay, "message", message_delay
        return None, "", None
    source, seconds = max(candidates, key=lambda item: item[1])
    return now + seconds, source, seconds


def _summary_429(kind: str, code: str) -> str:
    if kind == "rate_limit":
        text = "OpenAI rate limit exceeded."
    elif kind == "unknown":
        text = "OpenAI rate limit or quota exceeded."
    else:
        text = "OpenAI quota exceeded."
    if code:
        return f"{text} ({code})"
    return text + " Try again later."


def _limit_error(resp) -> OpenAIError:
    now = time.time()
    headers = _header_map(resp)
    err = _error_body(resp)
    code = _ident(err.get("code"))
    error_type = _ident(err.get("type"))
    message = _clean_text(err.get("message") if isinstance(err.get("message"), str) else "")
    request_id = _ident(headers.get("x-request-id", ""))
    kind = _classify(code, error_type, message)
    buckets = _buckets(headers, now)
    retry_after = parse_delay_seconds(headers.get("retry-after", ""), now=now)
    message_delay = _delay_from_message(message)
    resets_at, reset_source, reset_seconds = _choose_reset(
        kind, now, retry_after, buckets, message_delay,
    )
    limit = {
        "kind": kind,
        "status": 429,
        "code": code,
        "error_type": error_type,
        "message": message,
        "request_id": request_id,
        "checked_at": now,
        "resets_at": resets_at,
        "reset_source": reset_source,
        "reset_seconds": reset_seconds,
        "retry_after_seconds": retry_after,
        "buckets": buckets,
    }
    log.info(
        "OpenAI 429 kind=%s code=%s type=%s request_id=%s reset_source=%s",
        kind, code or "-", error_type or "-", request_id or "-", reset_source or "-",
    )
    return OpenAIError(_summary_429(kind, code), limit=limit)


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
        cache=None,
        tab_id: str = "",
        use_cache: bool = True,
    ) -> Tuple[bytes, str]:
        """Return ``(audio_bytes, mime)``. Raises :class:`OpenAIError`.

        When ``cache`` is provided, identical
        (text+model+voice+style+format) requests are served from disk without
        a network call.
        """
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
        style = instructions or ""

        cache_key = None
        if cache is not None and use_cache:
            from .audio_cache import make_key
            cache_key = make_key(
                provider="openai", model=model, voice=voice,
                style=style, fmt=fmt, text=text,
            )
            hit = cache.get(cache_key)
            if hit is not None:
                cache.touch_tab(cache_key, tab_id)
                return hit, mime_for(fmt)

        body = {"model": model, "input": text, "voice": voice, "response_format": fmt}
        if model in _SPEED_MODELS:
            body["speed"] = max(0.25, min(4.0, float(speed) or 1.0))
        elif style:
            body["instructions"] = style

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
            raise self._http_error(status, resp)

        content = resp.content
        if not content:
            raise OpenAIError("OpenAI returned an empty audio response.")

        if cache is not None and cache_key:
            try:
                cache.put(cache_key, content, provider="openai", fmt=fmt, tab_id=tab_id or "")
            except OSError:
                log.warning("Failed to write OpenAI audio to cache", exc_info=True)

        return content, mime_for(fmt)

    # ---- smart tools (text -> text) ----
    def transform_text(
        self,
        text: str,
        task: str,
        *,
        target_lang: str = "",
        model: Optional[str] = None,
        cancel=None,
        timeout: float = 90.0,
    ) -> str:
        """Run a smart-tool text transformation and return the new text.

        ``task`` is one of :data:`SMART_TASKS`. Uses the chat-completions
        endpoint with a text model (never a TTS model). Raises
        :class:`OpenAIError` on any failure (message is always sanitized).
        """
        cfg = self.config()
        if not cfg.configured:
            raise OpenAIError("OpenAI API key is not configured.")
        if not (text and text.strip()):
            raise OpenAIError("Nothing to transform.")
        if task not in SMART_TASKS:
            raise OpenAIError(f"Unknown smart tool: {task}")
        if cancel is not None and getattr(cancel, "cancelled", False):
            raise OpenAIError("cancelled")

        system = SMART_TASKS[task]
        if task == "translate":
            target = (target_lang or "English").strip() or "English"
            system = system.format(target=target)

        text_model = (model or self._text_model()).strip() or DEFAULT_TEXT_MODEL
        body = {
            "model": text_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
            "temperature": 0.3,
        }
        url = f"{cfg.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"}

        session = self._session
        if session is None:
            import requests  # lazy; bundled
            session = requests

        try:
            resp = session.post(url, headers=headers, json=body, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            raise OpenAIError(self._transport_error(exc)) from None

        if cancel is not None and getattr(cancel, "cancelled", False):
            raise OpenAIError("cancelled")

        status = getattr(resp, "status_code", 0)
        if status != 200:
            raise self._http_error(status, resp)

        try:
            data = resp.json()
            out = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise OpenAIError("OpenAI returned an unexpected response.") from None
        if not (out and out.strip()):
            raise OpenAIError("OpenAI returned an empty result.")
        return out.strip()

    def _text_model(self) -> str:
        try:
            return (self._settings.get("openai_text_model", DEFAULT_TEXT_MODEL)
                    or DEFAULT_TEXT_MODEL)
        except Exception:  # noqa: BLE001
            return DEFAULT_TEXT_MODEL

    # ---- error sanitization (never leak the key or raw payloads) ----
    @staticmethod
    def _http_error(status: int, resp) -> "OpenAIError":
        if status == 429:
            return _limit_error(resp)
        mapping = {
            400: "OpenAI rejected the request (check the model, voice, or text).",
            401: "OpenAI rejected the API key (unauthorized).",
            403: "This OpenAI key isn't allowed to use text-to-speech.",
            404: "OpenAI model or endpoint not found.",
            408: "OpenAI request timed out.",
            413: "The text chunk is too large for OpenAI.",
            500: "OpenAI had a server error. Try again later.",
            502: "OpenAI is temporarily unavailable (bad gateway).",
            503: "OpenAI is temporarily unavailable. Try again later.",
        }
        msg = mapping.get(status)
        if msg:
            return OpenAIError(msg)
        # Attempt a short, safe reason from the JSON error without echoing keys.
        try:
            data = resp.json()
            reason = (data.get("error", {}) or {}).get("type") or ""
            if reason and isinstance(reason, str) and len(reason) < 60 and _ident(reason):
                return OpenAIError(f"OpenAI error ({status}): {reason}")
        except Exception:  # noqa: BLE001
            pass
        return OpenAIError(f"OpenAI request failed (HTTP {status}).")

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
