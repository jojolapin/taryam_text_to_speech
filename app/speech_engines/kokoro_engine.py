"""Kokoro-82M ONNX speech, cached on disk and run on the CPU.

The model weights are Apache-2.0 (hexgrad/Kokoro-82M). The ``kokoro-onnx``
runtime is a separate package. Nothing in this module is taken from the
VoiceStudio application.

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import io
import logging
import re
import threading
import wave
from pathlib import Path
from typing import Callable, Optional

from .. import paths as app_paths
from ..chunking import chunk
from ..voice_catalog import _stream_download
from .kokoro_catalog import voice_by_storage_id
from .router import kokoro_voice_name, speed_from_length_scale


log = logging.getLogger("textspeak.kokoro")

MODEL_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
    "model-files-v1.0/kokoro-v1.0.onnx"
)
VOICES_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
    "model-files-v1.0/voices-v1.0.bin"
)
MODEL_FILE = "kokoro-v1.0.onnx"
VOICES_FILE = "voices-v1.0.bin"
# The ONNX graph is about 310 MB. These floors reject an HTML error page
# saved under the model name.
MODEL_MIN_BYTES = 80 * 1024 * 1024
VOICES_MIN_BYTES = 256 * 1024
SAMPLE_RATE = 24000
# One Kokoro call keeps sentence pauses inside the paragraph. Playback uses
# the same limit so a passage is not split again before it reaches the model.
MAX_BLOCK_CHARS = 900
PLAYBACK_CHARS = MAX_BLOCK_CHARS
# Used only when a paragraph is longer than one block, at a sentence boundary.
SENTENCE_GAP_MS = 260
# Blank line between paragraphs. Longer than a sentence join, still short
# enough that the reading stays one piece.
PARAGRAPH_GAP_MS = 480

_MODEL_LOCK = threading.Lock()
_SYNTH_LOCK = threading.Lock()
_model = None
_model_unreadable = False
_voices_stamp: Optional[tuple] = None


class KokoroError(RuntimeError):
    """A Kokoro failure the interface can translate by ``code``."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


def model_dir() -> Path:
    folder = app_paths.user_data_dir() / "models" / "kokoro"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def model_path() -> Path:
    return model_dir() / MODEL_FILE


def voices_path() -> Path:
    return model_dir() / VOICES_FILE


def _large_enough(path: Path, minimum: int) -> bool:
    try:
        return path.is_file() and path.stat().st_size >= minimum
    except OSError:
        return False


def _header_ok(path: Path, kind: str) -> bool:
    """Reject an HTML error page or a truncated stand-in saved under the model name."""
    try:
        with path.open("rb") as handle:
            head = handle.read(8)
    except OSError:
        return False
    if len(head) < 4 or head[:1] in {b"<", b"{"}:
        return False
    if kind == "voices":
        # NumPy npz (zip) or a plain npy array.
        return head.startswith(b"PK\x03\x04") or head.startswith(b"\x93NUMPY")
    # ONNX protobuf graphs used here start with field tag 0x08.
    return head[0] == 0x08


def _voices_bank_ok(path: Path) -> bool:
    """The voice bank must actually contain the preset voices, not only a zip header."""
    global _voices_stamp
    try:
        stamp = (path.stat().st_mtime_ns, path.stat().st_size)
    except OSError:
        return False
    if _voices_stamp == stamp:
        return True
    try:
        import numpy as np

        with np.load(path) as bank:
            names = set(getattr(bank, "files", []))
    except Exception:
        return False
    if "af_heart" not in names or "ff_siwis" not in names:
        return False
    _voices_stamp = stamp
    return True


def _files_present() -> bool:
    model = model_path()
    voices = voices_path()
    return (
        _large_enough(model, MODEL_MIN_BYTES)
        and _header_ok(model, "onnx")
        and _large_enough(voices, VOICES_MIN_BYTES)
        and _header_ok(voices, "voices")
        and _voices_bank_ok(voices)
    )


def models_ready() -> bool:
    if _model_unreadable:
        return False
    return _files_present()


def package_status() -> tuple[bool, str]:
    try:
        import kokoro_onnx  # noqa: F401
    except ImportError as exc:
        return False, str(exc)
    return True, ""


def _file_usable(dest: Path, minimum: int, kind: str) -> bool:
    if not (_large_enough(dest, minimum) and _header_ok(dest, kind)):
        return False
    if kind == "voices":
        return _voices_bank_ok(dest)
    return True


def download_models(
    progress: Optional[Callable[[int, int], None]] = None,
    cancel: Optional[threading.Event] = None,
) -> None:
    """Download the ONNX graph and the voice bank once. Safe to repeat."""
    global _model_unreadable, _voices_stamp
    files = (
        (MODEL_URL, model_path(), MODEL_MIN_BYTES, "onnx"),
        (VOICES_URL, voices_path(), VOICES_MIN_BYTES, "voices"),
    )
    # A readable cache is left untouched. A model that failed to load is fetched again.
    if _model_unreadable:
        pending = list(files)
    else:
        pending = [item for item in files if not _file_usable(item[1], item[2], item[3])]
    if not pending:
        if progress:
            progress(1, 1)
        return
    for index, (url, dest, minimum, kind) in enumerate(pending, start=1):
        if cancel is not None and cancel.is_set():
            raise KeyboardInterrupt("download cancelled")
        partial = dest.with_suffix(dest.suffix + ".part")

        def _one(done: int, total: int, *, base: int = index - 1, count: int = len(pending)) -> None:
            if not progress:
                return
            fraction = (done / total) if total else 0
            progress(int((base + fraction) * 1000), count * 1000)

        log.info("Downloading Kokoro file %s", dest.name)
        try:
            _stream_download(url, dest, progress=_one, cancel=cancel)
        except KeyboardInterrupt:
            partial.unlink(missing_ok=True)
            raise
        except Exception as exc:
            partial.unlink(missing_ok=True)
            if dest.exists() and not _large_enough(dest, minimum):
                dest.unlink(missing_ok=True)
            log.warning("Kokoro download failed for %s: %s", dest.name, exc)
            raise KokoroError("kokoro-download-failed", dest.name) from exc
        usable = _large_enough(dest, minimum) and _header_ok(dest, kind)
        if usable and kind == "voices":
            _voices_stamp = None
            usable = _voices_bank_ok(dest)
        if not usable:
            dest.unlink(missing_ok=True)
            _voices_stamp = None
            raise KokoroError("kokoro-download-small", dest.name)
        if progress:
            progress(index * 1000, len(pending) * 1000)
    _model_unreadable = False
    unload()


def unload() -> None:
    """Drop the in-memory session. The files on disk stay cached."""
    global _model
    with _MODEL_LOCK:
        _model = None


def _load():
    global _model, _model_unreadable
    ok, detail = package_status()
    if not ok:
        raise KokoroError("kokoro-missing-package", detail)
    if not _files_present():
        raise KokoroError("kokoro-model-missing", "")
    with _MODEL_LOCK:
        if _model is not None:
            return _model
        try:
            from kokoro_onnx import Kokoro

            log.info("Loading Kokoro from %s", model_path())
            _model = Kokoro(str(model_path()), str(voices_path()))
            _model_unreadable = False
        except Exception as exc:
            _model = None
            _model_unreadable = True
            log.exception("Kokoro model could not be loaded")
            raise KokoroError("kokoro-model-invalid", type(exc).__name__) from exc
        return _model


def _silence(milliseconds: int, sample_rate: int) -> bytes:
    frames = int(sample_rate * max(0, milliseconds) / 1000)
    return b"\x00\x00" * frames


def reading_blocks(text: str) -> list[dict]:
    """Split a reading into Kokoro calls without dropping or repeating text.

    Paragraphs stay intact until they exceed ``MAX_BLOCK_CHARS``. Kokoro then
    inserts its own sentence and clause pauses inside the call. The gap after
    a block is only the pause that call cannot see: a sentence join inside a
    long paragraph, or a longer pause after a blank line.
    """
    raw = text or ""
    paragraphs = [part.strip() for part in re.split(r"\n[ \t]*\n", raw) if part and part.strip()]
    if not paragraphs and raw.strip():
        paragraphs = [raw.strip()]
    blocks: list[dict] = []
    for paragraph_index, paragraph in enumerate(paragraphs):
        pieces = [part["text"] for part in chunk(paragraph, MAX_BLOCK_CHARS)] or [paragraph]
        for index, piece in enumerate(pieces):
            end_of_paragraph = index == len(pieces) - 1
            end_of_text = end_of_paragraph and paragraph_index == len(paragraphs) - 1
            if end_of_text:
                gap = 0
            elif end_of_paragraph:
                gap = PARAGRAPH_GAP_MS
            else:
                gap = SENTENCE_GAP_MS
            blocks.append({"text": piece, "gap_ms": gap})
    return blocks


def _float_to_pcm(samples, volume: float) -> bytes:
    import numpy as np

    audio = np.asarray(samples, dtype=np.float32).reshape(-1)
    gain = max(0.0, min(1.0, float(volume)))
    audio = np.clip(audio * gain, -1.0, 1.0)
    return (audio * 32767.0).astype("<i2").tobytes()


def _wav_bytes(pcm: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)
    return buf.getvalue()


class KokoroEngine:
    """Synthesize with the cached Kokoro session. One session per process."""

    def synthesize_pcm(
        self,
        text: str,
        voice_id: str,
        length_scale: float = 1.0,
        volume: float = 1.0,
        token=None,
        progress: Optional[Callable[[str, float], None]] = None,
    ) -> tuple[bytes, int, int]:
        row = voice_by_storage_id(voice_id)
        if row is None:
            raise KokoroError("kokoro-voice-unknown", kokoro_voice_name(voice_id))
        blocks = reading_blocks(text or "")
        if not blocks:
            raise ValueError("There is no text to read.")
        model = _load()
        speed = speed_from_length_scale(length_scale)
        parts: list[bytes] = []
        sample_rate = SAMPLE_RATE
        for index, block in enumerate(blocks):
            if token is not None and getattr(token, "cancelled", False):
                raise KeyboardInterrupt("cancelled")
            with _SYNTH_LOCK:
                samples, rate = model.create(
                    block["text"],
                    voice=row["id"],
                    speed=speed,
                    lang=row["kokoro_lang"],
                    trim=True,
                )
            rate = int(rate)
            if index and rate != sample_rate:
                raise KokoroError("kokoro-model-invalid", f"sample rate changed from {sample_rate} to {rate}")
            sample_rate = rate
            parts.append(_float_to_pcm(samples, volume))
            if block["gap_ms"]:
                parts.append(_silence(block["gap_ms"], sample_rate))
            if progress:
                progress("synth", (index + 1) / len(blocks))
        if token is not None and getattr(token, "cancelled", False):
            raise KeyboardInterrupt("cancelled")
        return b"".join(parts), sample_rate, 1

    def synthesize_wav_bytes(
        self,
        text: str,
        voice_id: str,
        length_scale: float = 1.0,
        volume: float = 1.0,
        token=None,
    ) -> bytes:
        pcm, sample_rate, _channels = self.synthesize_pcm(
            text, voice_id, length_scale, volume, token,
        )
        return _wav_bytes(pcm, sample_rate)

    def export_audio(
        self,
        text: str,
        voice_id: str,
        fmt: str,
        length_scale: float,
        volume: float,
        bitrate: int,
        token=None,
        progress: Optional[Callable[[str, float], None]] = None,
    ) -> tuple[bytes, float, int, int]:
        from ..tts_engine import TTSEngine

        def synth_progress(stage: str, ratio: float) -> None:
            if progress:
                progress(stage, ratio * 0.85)

        pcm, sample_rate, channels = self.synthesize_pcm(
            text, voice_id, length_scale, volume, token, progress=synth_progress,
        )
        if progress:
            progress("encode", 0.9)
        encoder = TTSEngine()
        kind = (fmt or "mp3").lower()
        if kind == "wav":
            data = encoder.encode_wav(pcm, sample_rate, channels)
        elif kind == "ogg":
            data = encoder.encode_ogg(pcm, sample_rate, channels)
        else:
            data = encoder.encode_mp3(pcm, sample_rate, channels, bitrate)
        if progress:
            progress("done", 1.0)
        seconds = len(pcm) / (sample_rate * channels * 2) if sample_rate else 0.0
        return data, seconds, sample_rate, channels
