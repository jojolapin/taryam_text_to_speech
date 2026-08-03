"""QWebChannel bridge between JS (webview) and Python.

All slots are callable from JS as ``window.bridge.<method>(...)``. Heavy ops
emit signals back to JS so the UI can stay responsive. Requests are keyed by
a client-supplied ``request_id`` string so rapid cancels don't conflict.

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot

from . import APP_AUTHOR, APP_COPYRIGHT, APP_NAME, APP_VERSION
from . import paths as app_paths
from . import text_normalize
from . import voice_catalog
from .openai_provider import (
    OPENAI_FORMATS,
    OPENAI_MODELS,
    OPENAI_VOICES,
    OpenAIError,
    OpenAIProvider,
    resolve_config,
)
from .providers import PiperProvider, ProviderRegistry
from .settings import Settings
from .tts_engine import CancelToken, PiperMissingError, TTSEngine, write_mp3_with_tags


log = logging.getLogger("textspeak.bridge")


# ---------- QRunnable workers ----------

class _Runnable(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self.setAutoDelete(True)

    def run(self):  # noqa: D401
        try:
            self._fn(*self._args, **self._kwargs)
        except Exception:  # noqa: BLE001
            log.exception("Worker crashed")


# ---------- helpers ----------

def _safe_filename(name: str, extension: str, fallback: str = "textspeak-reading") -> str:
    name = (name or "").strip()
    name = re.sub(r"[^\w.\- ]+", "", name, flags=re.UNICODE)
    name = name.replace(" ", "_").strip("._-")
    if not name:
        name = fallback
    name = name[:80]
    ext = extension.lstrip(".").lower()
    if not name.lower().endswith("." + ext):
        name += "." + ext
    return name


def _first_line_snippet(text: str, length: int = 48) -> str:
    first = (text.strip().splitlines() or [""])[0]
    first = re.sub(r"\s+", " ", first).strip()
    return first[:length] if first else ""


# ---------- the bridge ----------

class Bridge(QObject):
    """JS-facing bridge object."""

    # ---- signals consumed by JS ----
    synthesizeReady = Signal(str, str)       # (request_id, wav_base64)
    synthesizeError = Signal(str, str)       # (request_id, message)
    openaiAudioReady = Signal(str, str, str) # (request_id, audio_base64, mime)
    openaiAudioError = Signal(str, str)      # (request_id, message)
    exportProgress = Signal(str, str, float) # (request_id, stage, ratio)
    exportDone = Signal(str, str, float, float)  # (request_id, path, audio_seconds, synth_seconds)
    exportError = Signal(str, str)           # (request_id, message)
    catalogProgress = Signal(str, int, int)  # (request_id, done, total)
    catalogDone = Signal(str, str)           # (request_id, voice_id)
    catalogError = Signal(str, str)          # (request_id, message)
    sampleReady = Signal(str, str, str)      # (request_id, voice_id, mp3_base64 or '')
    themeChanged = Signal(str)               # scheme: 'light' | 'dark'
    languageChanged = Signal(str)            # 'en' | 'fr'
    voicesChanged = Signal()                 # a voice was installed/deleted
    fileDropped = Signal(str)                # path dropped onto window
    readClipboardRequested = Signal()
    stopRequested = Signal()
    quitRequested = Signal()
    minimizeRequested = Signal()
    toggleMaximizeRequested = Signal()
    closeRequested = Signal()

    def __init__(self, engine: Optional[TTSEngine] = None, settings: Optional[Settings] = None) -> None:
        super().__init__()
        self.engine = engine or TTSEngine()
        self.settings = settings or Settings()
        self.pool = QThreadPool.globalInstance()
        self._cancels: dict[str, CancelToken] = {}
        self._dl_cancels: dict[str, threading.Event] = {}

        # Voice providers: Piper (offline) + OpenAI (online, opt-in).
        self.providers = ProviderRegistry("piper")
        self.providers.register(PiperProvider(self.engine))
        self.providers.register(OpenAIProvider(self.settings))

    # ---- text normalization (markdown / html -> TTS plain) ----

    def _resolve_md_lang(self) -> str:
        pref = (self.settings.get("language", "system") or "system").lower()
        if pref in {"en", "fr"}:
            return pref
        return "fr" if self._system_fr() else "en"

    def _effective_format(self, fmt: str, text: str) -> str:
        """Honour the user's ``markdown_mode`` setting on top of the caller's
        ``fmt`` hint. Returns one of ``"markdown" | "html" | "plain"``."""
        mode = (self.settings.get("markdown_mode", "auto") or "auto").lower()
        fmt = (fmt or "auto").lower()
        if mode == "off":
            return "plain" if fmt in {"auto", "markdown"} else fmt
        if mode == "on":
            # Force markdown unless caller explicitly says html
            return "html" if fmt == "html" else "markdown"
        # auto: honour explicit caller hints; otherwise sniff
        if fmt in {"markdown", "html", "plain"}:
            return fmt
        return text_normalize.detect_format("<memory>", text=text)

    def _normalize_for_tts(self, text: str, fmt: str) -> str:
        effective = self._effective_format(fmt, text)
        if effective == "plain":
            return text
        return text_normalize.normalize(
            text, effective,
            lang=self._resolve_md_lang(),
            read_code=bool(self.settings.get("md_read_code", False)),
            read_urls=bool(self.settings.get("md_read_urls", False)),
            read_tables=bool(self.settings.get("md_read_tables", True)),
        )

    # --- PySide6 @Slot type hints must use the exact Python types it maps ---

    # ============================================================
    # App info
    # ============================================================
    @Slot(result=str)
    def provider_status(self) -> str:
        """JSON list of voice providers and their availability (UI status)."""
        try:
            return json.dumps(self.providers.status())
        except Exception:  # noqa: BLE001
            log.exception("provider_status failed")
            return json.dumps([])

    # ============================================================
    # OpenAI configuration / status (API key never leaves Python)
    # ============================================================
    @Slot(result=str)
    def openai_status(self) -> str:
        """Non-secret OpenAI config for the UI. Never includes the API key."""
        try:
            cfg = resolve_config(self.settings)
            return json.dumps({
                "configured": cfg.configured,
                "keySource": cfg.key_source,
                "model": cfg.model,
                "voice": cfg.voice,
                "format": cfg.response_format,
                "baseUrl": cfg.base_url,
                "voices": OPENAI_VOICES,
                "models": OPENAI_MODELS,
                "formats": OPENAI_FORMATS,
                "disclosureAck": bool(self.settings.get("ai_disclosure_ack", False)),
            })
        except Exception:  # noqa: BLE001
            log.exception("openai_status failed")
            return json.dumps({"configured": False, "keySource": "none"})

    @Slot(str, result=str)
    def set_openai_key(self, key: str) -> str:
        """Store the API key locally (QSettings). Returns refreshed status JSON.
        The key is intentionally not echoed back."""
        self.settings.set("openai_api_key", (key or "").strip())
        return self.openai_status()

    @Slot(result=str)
    def clear_openai_key(self) -> str:
        self.settings.set("openai_api_key", "")
        return self.openai_status()

    @Slot(result=bool)
    def openai_has_key(self) -> bool:
        return bool(resolve_config(self.settings).configured)

    @Slot(result=str)
    def app_info(self) -> str:
        return json.dumps({
            "name": APP_NAME,
            "version": APP_VERSION,
            "author": APP_AUTHOR,
            "copyright": APP_COPYRIGHT,
            "portable": app_paths.is_portable(),
            "voices_dir": str(app_paths.voices_dir()),
            "logs_dir": str(app_paths.logs_dir()),
            "system_lang": "fr" if self._system_fr() else "en",
            "system_theme": self._system_theme(),
        })

    def _system_fr(self) -> bool:
        try:
            from PySide6.QtCore import QLocale
            return (QLocale.system().name() or "").lower().startswith("fr")
        except Exception:  # noqa: BLE001
            return False

    def _system_theme(self) -> str:
        try:
            from PySide6.QtGui import QGuiApplication
            hints = QGuiApplication.styleHints()
            scheme = hints.colorScheme()
            from PySide6.QtCore import Qt
            if scheme == Qt.ColorScheme.Dark:
                return "dark"
            if scheme == Qt.ColorScheme.Light:
                return "light"
        except Exception:  # noqa: BLE001
            pass
        return "dark"

    # ============================================================
    # Preferences
    # ============================================================
    @Slot(result=str)
    def get_prefs(self) -> str:
        return json.dumps(self.settings.all())

    @Slot(str, "QVariant")
    def set_pref(self, key: str, value: Any) -> None:
        self.settings.set(key, value)
        if key == "language":
            self.languageChanged.emit(value or "system")
        if key == "theme":
            self.themeChanged.emit(value or "system")

    @Slot(bool)
    def set_portable(self, enabled: bool) -> None:
        app_paths.set_portable(enabled)

    # ============================================================
    # Voices (installed)
    # ============================================================
    @Slot(result=str)
    def list_voices(self) -> str:
        try:
            return json.dumps(self.engine.discover_voices())
        except PiperMissingError as e:
            return json.dumps({"error": str(e), "missing": True})
        except Exception as e:  # noqa: BLE001
            return json.dumps({"error": str(e)})

    # ============================================================
    # Text normalization (markdown -> TTS-friendly plain text)
    # ============================================================
    @Slot(str, str, result=str)
    def normalize_text(self, text: str, fmt: str) -> str:
        """Return a JSON payload ``{plain, format}`` for the given text.

        ``fmt`` may be ``"auto" | "markdown" | "html" | "plain"``. The
        ``markdown_mode`` setting always has the final say (off/on can
        override the caller).
        """
        effective = self._effective_format(fmt or "auto", text or "")
        plain = self._normalize_for_tts(text or "", fmt or "auto")
        return json.dumps({"plain": plain, "format": effective})

    # ============================================================
    # Synthesis (single chunk for playback)
    # ============================================================
    @Slot(str, str, float, float, str, str)
    def synthesize(self, text: str, voice_id: str, length_scale: float,
                   volume: float, request_id: str, fmt: str = "plain") -> None:
        token = CancelToken()
        self._cancels[request_id] = token
        speech_text = self._normalize_for_tts(text, fmt)

        def _worker():
            try:
                wav = self.engine.synthesize_wav_bytes(speech_text, voice_id, length_scale, volume, token)
                if token.cancelled:
                    return
                self.synthesizeReady.emit(request_id, base64.b64encode(wav).decode("ascii"))
            except PiperMissingError:
                self.synthesizeError.emit(request_id, "piper-missing")
            except FileNotFoundError as e:
                self.synthesizeError.emit(request_id, f"voice-missing: {e}")
            except Exception as e:  # noqa: BLE001
                log.exception("Synthesis failed")
                self.synthesizeError.emit(request_id, str(e))
            finally:
                self._cancels.pop(request_id, None)

        self.pool.start(_Runnable(_worker))

    @Slot(str, str, str, float, str, str, str, str)
    def synthesize_openai(self, text: str, voice: str, model: str, speed: float,
                          instructions: str, response_format: str,
                          text_format: str, request_id: str) -> None:
        """Synthesize one chunk via OpenAI. Emits openaiAudioReady/Error.

        The API key is resolved and used entirely inside the provider; it is
        never part of this call's arguments or the emitted signals.
        """
        token = CancelToken()
        self._cancels[request_id] = token
        speech_text = self._normalize_for_tts(text, text_format or "plain")
        provider = self.providers.get("openai")

        def _worker():
            try:
                if not isinstance(provider, OpenAIProvider):
                    self.openaiAudioError.emit(request_id, "OpenAI provider unavailable.")
                    return
                audio, mime = provider.synthesize(
                    speech_text,
                    voice=voice or None,
                    model=model or None,
                    speed=speed or 1.0,
                    instructions=instructions or "",
                    response_format=response_format or None,
                    cancel=token,
                )
                if token.cancelled:
                    return
                self.openaiAudioReady.emit(
                    request_id, base64.b64encode(audio).decode("ascii"), mime
                )
            except OpenAIError as e:
                if str(e) == "cancelled":
                    return
                self.openaiAudioError.emit(request_id, str(e))
            except Exception:  # noqa: BLE001 - sanitized; never leak details
                log.exception("OpenAI synthesis failed")
                self.openaiAudioError.emit(request_id, "OpenAI synthesis failed.")
            finally:
                self._cancels.pop(request_id, None)

        self.pool.start(_Runnable(_worker))

    @Slot(str)
    def cancel(self, request_id: str) -> None:
        tok = self._cancels.get(request_id)
        if tok:
            tok.cancel()
        ev = self._dl_cancels.get(request_id)
        if ev:
            ev.set()

    # ============================================================
    # Audio export (full text -> file)
    # ============================================================
    @Slot(str, str, str, float, float, int, str, str, str, str)
    def export_audio(self, text: str, voice_id: str, fmt: str,
                     length_scale: float, volume: float, bitrate: int,
                     id3_author: str, suggested_name: str, request_id: str,
                     text_format: str = "plain") -> None:
        """Opens a native Save dialog on the main thread, then synthesizes off-thread."""
        from PySide6.QtWidgets import QFileDialog

        text = self._normalize_for_tts(text, text_format)
        fmt = (fmt or "mp3").lower()
        ext_map = {"mp3": "mp3", "wav": "wav", "ogg": "ogg"}
        ext = ext_map.get(fmt, "mp3")
        suggested = _safe_filename(suggested_name, ext, fallback="textspeak-reading")

        filters = {
            "mp3": "MP3 Audio (*.mp3)",
            "wav": "WAV Audio (*.wav)",
            "ogg": "OGG Vorbis (*.ogg)",
        }
        save_dir = self.settings.get("last_export_dir", str(Path.home())) or str(Path.home())
        start_path = str(Path(save_dir) / suggested)
        out_path, _ = QFileDialog.getSaveFileName(None, "Save audio", start_path, filters[fmt])
        if not out_path:
            self.exportError.emit(request_id, "cancelled")
            return
        self.settings.set("last_export_dir", str(Path(out_path).parent))

        token = CancelToken()
        self._cancels[request_id] = token

        def _worker():
            t0 = time.time()
            try:
                def progress(stage: str, ratio: float):
                    self.exportProgress.emit(request_id, stage, ratio)

                data, audio_seconds, _sr, _ch = self.engine.export_audio(
                    text, voice_id, fmt, length_scale, volume, bitrate,
                    token=token, progress=progress,
                )
                if token.cancelled:
                    self.exportError.emit(request_id, "cancelled")
                    return

                out = Path(out_path)
                if fmt == "mp3":
                    write_mp3_with_tags(
                        out, data,
                        title=_first_line_snippet(text) or out.stem,
                        artist=id3_author or APP_AUTHOR,
                        album=APP_NAME,
                        comment=f"Generated offline by {APP_NAME} - {APP_COPYRIGHT}",
                    )
                else:
                    out.write_bytes(data)

                self.exportDone.emit(request_id, str(out), audio_seconds, time.time() - t0)
            except PiperMissingError:
                self.exportError.emit(request_id, "piper-missing")
            except Exception as e:  # noqa: BLE001
                log.exception("Export failed")
                self.exportError.emit(request_id, str(e))
            finally:
                self._cancels.pop(request_id, None)

        self.pool.start(_Runnable(_worker))

    @Slot(str, str, str, float, float, int, str, str, str, str)
    def batch_export(self, paragraphs_json: str, voice_id: str, fmt: str,
                     length_scale: float, volume: float, bitrate: int,
                     id3_author: str, prefix: str, request_id: str,
                     text_format: str = "plain") -> None:
        """Export one file per paragraph into a user-chosen folder."""
        from PySide6.QtWidgets import QFileDialog
        try:
            paragraphs: list[str] = json.loads(paragraphs_json)
        except ValueError:
            self.exportError.emit(request_id, "invalid payload")
            return
        paragraphs = [self._normalize_for_tts(p, text_format) for p in paragraphs if p and p.strip()]
        paragraphs = [p for p in paragraphs if p and p.strip()]
        if not paragraphs:
            self.exportError.emit(request_id, "no paragraphs")
            return

        save_dir = self.settings.get("last_export_dir", str(Path.home())) or str(Path.home())
        folder = QFileDialog.getExistingDirectory(None, "Choose output folder", save_dir)
        if not folder:
            self.exportError.emit(request_id, "cancelled")
            return
        self.settings.set("last_export_dir", folder)

        ext = {"mp3": "mp3", "wav": "wav", "ogg": "ogg"}.get((fmt or "mp3").lower(), "mp3")
        prefix = prefix or "part"
        token = CancelToken()
        self._cancels[request_id] = token

        def _worker():
            total = len(paragraphs)
            t0 = time.time()
            try:
                for i, text in enumerate(paragraphs, 1):
                    if token.cancelled:
                        self.exportError.emit(request_id, "cancelled")
                        return
                    self.exportProgress.emit(request_id, "synth", (i - 1) / total)
                    data, audio_seconds, _sr, _ch = self.engine.export_audio(
                        text, voice_id, ext, length_scale, volume, bitrate, token=token,
                    )
                    name = _safe_filename(f"{prefix}-{i:03d}", ext)
                    out = Path(folder) / name
                    if ext == "mp3":
                        write_mp3_with_tags(
                            out, data,
                            title=_first_line_snippet(text) or out.stem,
                            artist=id3_author or APP_AUTHOR,
                            album=APP_NAME,
                        )
                    else:
                        out.write_bytes(data)
                    self.exportProgress.emit(request_id, "paragraph", i / total)
                self.exportDone.emit(request_id, folder, 0.0, time.time() - t0)
            except Exception as e:  # noqa: BLE001
                log.exception("Batch export failed")
                self.exportError.emit(request_id, str(e))
            finally:
                self._cancels.pop(request_id, None)

        self.pool.start(_Runnable(_worker))

    # ============================================================
    # Voice Catalog
    # ============================================================
    @Slot(result=str)
    def catalog_list(self) -> str:
        voices = voice_catalog.full_catalog()
        installed = voice_catalog.installed_ids()
        for v in voices:
            v["installed"] = v["id"] in installed
        return json.dumps({"voices": voices})

    @Slot(str)
    def catalog_refresh(self, request_id: str) -> None:
        def _worker():
            try:
                merged = voice_catalog.refresh_from_hf()
                installed = voice_catalog.installed_ids()
                for v in merged:
                    v["installed"] = v["id"] in installed
                self.catalogProgress.emit(request_id, len(merged), len(merged))
                self.catalogDone.emit(request_id, "")
            except Exception as e:  # noqa: BLE001
                log.exception("Catalog refresh failed")
                self.catalogError.emit(request_id, str(e))

        self.pool.start(_Runnable(_worker))

    @Slot(str, str)
    def catalog_download(self, voice_id: str, request_id: str) -> None:
        cancel = threading.Event()
        self._dl_cancels[request_id] = cancel

        def _worker():
            try:
                def progress(done: int, total: int):
                    self.catalogProgress.emit(request_id, done, total)
                voice_catalog.download_voice(voice_id, progress=progress, cancel=cancel)
                # Drop any previously cached load of this id
                self.engine.drop_voice(voice_id)
                self.catalogDone.emit(request_id, voice_id)
                self.voicesChanged.emit()
            except KeyboardInterrupt:
                self.catalogError.emit(request_id, "cancelled")
            except Exception as e:  # noqa: BLE001
                log.exception("Voice download failed")
                self.catalogError.emit(request_id, str(e))
            finally:
                self._dl_cancels.pop(request_id, None)

        self.pool.start(_Runnable(_worker))

    @Slot(str)
    def catalog_cancel(self, request_id: str) -> None:
        ev = self._dl_cancels.get(request_id)
        if ev:
            ev.set()

    @Slot(str, result=bool)
    def catalog_delete(self, voice_id: str) -> bool:
        ok = self.engine.delete_voice_files(voice_id)
        if ok:
            self.voicesChanged.emit()
        return ok

    @Slot(str, str)
    def catalog_play_sample(self, voice_id: str, request_id: str) -> None:
        def _worker():
            data = voice_catalog.fetch_sample(voice_id)
            b64 = base64.b64encode(data).decode("ascii") if data else ""
            self.sampleReady.emit(request_id, voice_id, b64)

        self.pool.start(_Runnable(_worker))

    # ============================================================
    # Filesystem helpers
    # ============================================================
    @Slot()
    def open_voices_folder(self) -> None:
        self._open_in_explorer(app_paths.voices_dir())

    @Slot()
    def open_logs_folder(self) -> None:
        self._open_in_explorer(app_paths.logs_dir())

    @Slot()
    def open_data_folder(self) -> None:
        self._open_in_explorer(app_paths.user_data_dir())

    def _open_in_explorer(self, path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
            if sys.platform.startswith("win"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])  # noqa: S603,S607
            else:
                subprocess.Popen(["xdg-open", str(path)])  # noqa: S603,S607
        except Exception as e:  # noqa: BLE001
            log.warning("Could not open %s: %s", path, e)

    # ============================================================
    # File import (txt / md / html / pdf)
    # ============================================================
    @Slot(str, result=str)
    def read_text_file(self, path: str) -> str:
        p = Path(path)
        if not p.exists() or not p.is_file():
            return json.dumps({"error": f"Not found: {path}"})
        try:
            ext = p.suffix.lower()
            fmt = "plain"
            if ext == ".pdf":
                text = self._extract_pdf(p)
            else:
                raw = p.read_bytes()
                # Try utf-8 first, then latin-1 as forgiving fallback
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    text = raw.decode("latin-1", errors="replace")
                if ext in {".html", ".htm"}:
                    # Keep raw HTML in the editor; UI can decide to render or
                    # normalize. For now, strip for pleasant editing.
                    text = self._strip_html(text)
                    fmt = "plain"
                elif ext in {".md", ".markdown", ".mdown", ".mkd"}:
                    fmt = "markdown"
                else:
                    # No extension hint -> sniff the content
                    fmt = text_normalize.detect_format(p, text=text)
            # Track recent
            self.settings.add_recent_file(str(p))
            return json.dumps({"name": p.name, "path": str(p), "text": text, "format": fmt})
        except Exception as e:  # noqa: BLE001
            return json.dumps({"error": str(e)})

    def _extract_pdf(self, path: Path) -> str:
        try:
            from pypdf import PdfReader  # type: ignore
        except ImportError:
            raise RuntimeError("pypdf is not installed")
        reader = PdfReader(str(path))
        chunks: list[str] = []
        for page in reader.pages:
            try:
                chunks.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001
                continue
        return "\n\n".join(c.strip() for c in chunks if c and c.strip())

    def _strip_html(self, html: str) -> str:
        # Lightweight: rely on Qt's text extractor for decent fidelity
        try:
            from PySide6.QtGui import QTextDocument
            doc = QTextDocument()
            doc.setHtml(html)
            return doc.toPlainText()
        except Exception:  # noqa: BLE001
            return re.sub(r"<[^>]+>", "", html)

    # ============================================================
    # Clipboard
    # ============================================================
    @Slot(result=str)
    def read_clipboard(self) -> str:
        try:
            from PySide6.QtGui import QGuiApplication
            return QGuiApplication.clipboard().text() or ""
        except Exception as e:  # noqa: BLE001
            log.warning("clipboard read failed: %s", e)
            return ""

    @Slot(str)
    def set_clipboard(self, text: str) -> None:
        try:
            from PySide6.QtGui import QGuiApplication
            QGuiApplication.clipboard().setText(text or "")
        except Exception as e:  # noqa: BLE001
            log.warning("clipboard write failed: %s", e)

    # ============================================================
    # Recent files & presets
    # ============================================================
    @Slot(result=str)
    def recent_files(self) -> str:
        return json.dumps(self.settings.get_json("recent_files", []))

    @Slot()
    def recent_clear(self) -> None:
        self.settings.clear_recent_files()

    @Slot(result=str)
    def presets_list(self) -> str:
        return json.dumps(self.settings.get_json("presets", []))

    @Slot(str, str)
    def preset_save(self, name: str, data_json: str) -> None:
        try:
            data = json.loads(data_json or "{}")
        except ValueError:
            data = {}
        data["name"] = name
        presets = self.settings.get_json("presets", [])
        presets = [p for p in presets if p.get("name") != name]
        presets.append(data)
        self.settings.set_json("presets", presets)

    @Slot(str)
    def preset_delete(self, name: str) -> None:
        presets = [p for p in self.settings.get_json("presets", []) if p.get("name") != name]
        self.settings.set_json("presets", presets)

    # ============================================================
    # Window chrome (from the custom title bar)
    # ============================================================
    beginDragRequested = Signal()
    beginResizeRequested = Signal(int)

    @Slot()
    def minimize_window(self) -> None:
        self.minimizeRequested.emit()

    @Slot()
    def toggle_maximize(self) -> None:
        self.toggleMaximizeRequested.emit()

    @Slot()
    def close_window(self) -> None:
        self.closeRequested.emit()

    @Slot()
    def quit_app(self) -> None:
        self.quitRequested.emit()

    @Slot()
    def begin_window_drag(self) -> None:
        """Start a native window move (``QWindow.startSystemMove``)."""
        self.beginDragRequested.emit()

    @Slot(int)
    def begin_window_resize(self, edges: int) -> None:
        """Start a native resize. ``edges`` is a ``Qt.Edges`` bitmask from JS."""
        self.beginResizeRequested.emit(int(edges))
