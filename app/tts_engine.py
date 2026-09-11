"""Piper TTS engine + WAV / MP3 / OGG encoders.

Synthesis happens off the GUI thread (callers should wrap these in
``QRunnable``). Voice ONNX models are cached in memory so the first call
eats the 0.5-2 s load and later calls are near-instant.

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from threading import Lock
from typing import Callable, Optional

from . import paths as app_paths


log = logging.getLogger("textspeak.engine")
_SYNTHESIS_LOCK = Lock()  # Piper's process-global espeak voice is mutable.


class PiperMissingError(RuntimeError):
    """Raised when ``piper-tts`` is not importable."""


def _import_piper():
    try:
        from piper import PiperVoice, SynthesisConfig  # type: ignore
    except ImportError as e:  # pragma: no cover - import guard
        raise PiperMissingError(str(e)) from e
    return PiperVoice, SynthesisConfig


def _verify_piper_data_bundle() -> None:
    """Raise a readable error if piper's native data files are missing.

    When the app is frozen by PyInstaller, ``piper/espeak-ng-data/`` and the
    native ``espeakbridge.pyd`` extension MUST be shipped alongside
    ``piper/__init__.py`` (piper uses ``Path(__file__).parent`` to locate
    them). If they're missing, ``espeakbridge.initialize()`` either raises
    a cryptic OSError or - worse - aborts the whole process. This check
    converts that into a normal Python exception we can surface in the UI.
    """
    try:
        import piper  # type: ignore
    except ImportError as e:
        raise PiperMissingError(str(e)) from e
    piper_dir = Path(piper.__file__).resolve().parent
    espeak_dir = piper_dir / "espeak-ng-data"
    if not espeak_dir.is_dir() or not any(espeak_dir.iterdir()):
        raise RuntimeError(
            "Piper data files are missing from this build. "
            f"Expected folder: {espeak_dir}\n"
            "This usually means the app was built without collect_all('piper'). "
            "Rebuild with the latest textspeak_pro.spec."
        )
    # espeakbridge is the native extension that consumes the data above
    bridge_candidates = list(piper_dir.glob("espeakbridge*.pyd")) + \
                        list(piper_dir.glob("espeakbridge*.so")) + \
                        list(piper_dir.glob("espeakbridge*.dylib"))
    if not bridge_candidates:
        raise RuntimeError(
            "Piper native extension 'espeakbridge' is missing from this build. "
            f"Expected it under: {piper_dir}"
        )


try:
    import lameenc  # type: ignore
    HAS_LAMEENC = True
except ImportError:  # pragma: no cover
    HAS_LAMEENC = False


class CancelToken:
    """Cooperative cancel signal shared with workers."""

    __slots__ = ("_flag",)

    def __init__(self) -> None:
        self._flag = False

    def cancel(self) -> None:
        self._flag = True

    @property
    def cancelled(self) -> bool:
        return self._flag


class TTSEngine:
    """Stateful wrapper around ``piper.PiperVoice``.

    Voice loading is protected by an instance lock. Synthesis is serialized
    across instances because Piper's espeak phonemizer changes global voice
    state. The lock is acquired on workers, never on the GUI thread.
    """

    def __init__(self) -> None:
        self._cache: dict[str, object] = {}
        self._lock = Lock()

    # ---- discovery ----

    def voices_dir(self) -> Path:
        return app_paths.voices_dir()

    def discover_voices(self) -> list[dict]:
        out: list[dict] = []
        vdir = self.voices_dir()
        if not vdir.exists():
            return out
        for onnx_path in sorted(vdir.glob("*.onnx")):
            cfg = Path(str(onnx_path) + ".json")
            if not cfg.exists():
                log.warning("Missing config for voice %s", onnx_path.name)
                continue
            language = "unknown"
            speaker = ""
            quality = ""
            try:
                meta = json.loads(cfg.read_text(encoding="utf-8"))
                lang_field = meta.get("language")
                if isinstance(lang_field, dict):
                    language = lang_field.get("code") or lang_field.get("family") or "unknown"
                elif isinstance(lang_field, str):
                    language = lang_field
                speaker = (meta.get("dataset") or {}).get("speaker", "") if isinstance(meta.get("dataset"), dict) else ""
                quality = meta.get("quality") or ""
            except Exception as e:  # noqa: BLE001
                log.warning("Could not read voice config %s: %s", cfg.name, e)
            out.append({
                "id": onnx_path.stem,
                "name": onnx_path.stem.replace("_", " "),
                "language": language,
                "speaker": speaker,
                "quality": quality,
                "size_mb": round(onnx_path.stat().st_size / (1024 * 1024), 1),
            })
        return out

    # ---- voice cache ----

    def get_voice(self, voice_id: str):
        with self._lock:
            cached = self._cache.get(voice_id)
            if cached is not None:
                return cached
            PiperVoice, _ = _import_piper()
            _verify_piper_data_bundle()
            model = self.voices_dir() / f"{voice_id}.onnx"
            if not model.exists():
                raise FileNotFoundError(f"Voice '{voice_id}' is not installed.")
            log.info("Loading voice %s", voice_id)
            voice = PiperVoice.load(str(model))
            self._cache[voice_id] = voice
            return voice

    def drop_voice(self, voice_id: str) -> None:
        with self._lock:
            self._cache.pop(voice_id, None)

    def delete_voice_files(self, voice_id: str) -> bool:
        """Remove a voice's ONNX + config from disk. Returns True on success."""
        self.drop_voice(voice_id)
        onnx = self.voices_dir() / f"{voice_id}.onnx"
        cfg = Path(str(onnx) + ".json")
        removed = False
        for p in (onnx, cfg):
            try:
                p.unlink()
                removed = True
            except FileNotFoundError:
                continue
            except OSError as e:
                log.warning("Could not delete %s: %s", p, e)
        return removed

    # ---- synthesis primitives ----

    def _synth_config(self, length_scale: float, volume: float):
        _, SynthesisConfig = _import_piper()
        length_scale = max(0.3, min(3.0, float(length_scale)))
        volume = max(0.0, min(1.0, float(volume)))
        return SynthesisConfig(length_scale=length_scale, volume=volume, normalize_audio=True)

    def synthesize_wav_bytes(self, text: str, voice_id: str, length_scale: float = 1.0,
                             volume: float = 1.0, token: Optional[CancelToken] = None) -> bytes:
        with _SYNTHESIS_LOCK:
            if token and token.cancelled:
                raise KeyboardInterrupt("cancelled")
            voice = self.get_voice(voice_id)
            cfg = self._synth_config(length_scale, volume)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wav_file:
                voice.synthesize_wav(text, wav_file, syn_config=cfg)
        if token and token.cancelled:
            raise KeyboardInterrupt("cancelled")
        return buf.getvalue()

    def synthesize_pcm(self, text: str, voice_id: str, length_scale: float = 1.0,
                       volume: float = 1.0) -> tuple[bytes, int, int]:
        """Return (pcm_bytes, sample_rate, channels). 16-bit little-endian PCM."""
        wav_bytes = self.synthesize_wav_bytes(text, voice_id, length_scale, volume)
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
            pcm = wav.readframes(wav.getnframes())
            sr = wav.getframerate()
            channels = wav.getnchannels()
            if wav.getsampwidth() != 2:
                raise RuntimeError(f"Unexpected sample width {wav.getsampwidth() * 8}-bit")
        return pcm, sr, channels

    # ---- encoders ----

    def encode_mp3(self, pcm: bytes, sample_rate: int, channels: int, bitrate: int = 128) -> bytes:
        if not HAS_LAMEENC:
            raise RuntimeError("lameenc is not installed")
        if bitrate not in (64, 96, 128, 160, 192, 256, 320):
            bitrate = 128
        enc = lameenc.Encoder()
        enc.set_bit_rate(bitrate)
        enc.set_in_sample_rate(sample_rate)
        # Low-rate Piper voices otherwise use MPEG-2, whose bitrate tops out at
        # 160 kbps. Let LAME resample to MPEG-1 so 192/256/320 are honored.
        if bitrate > 160 and sample_rate < 32000:
            enc.set_out_sample_rate(44100)
        enc.set_channels(channels)
        enc.set_quality(2)
        # Feed bounded PCM blocks: lameenc sizes each output buffer from input
        # samples, which can be insufficient for one large upsampling call.
        encoded = [enc.encode(pcm[offset:offset + 2048]) for offset in range(0, len(pcm), 2048)]
        encoded.append(enc.flush())
        return b"".join(encoded)

    def encode_wav(self, pcm: bytes, sample_rate: int, channels: int) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(channels)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            w.writeframes(pcm)
        return buf.getvalue()

    def encode_ogg(self, pcm: bytes, sample_rate: int, channels: int, quality: float = 0.5) -> bytes:
        """Encode PCM to OGG Vorbis.

        Uses ``oggenc`` if available on PATH, otherwise falls back to a plain
        WAV wrapped in an OGG extension (rare). This keeps the dependency
        surface lean; most users will use MP3 anyway.
        """
        try:
            proc = subprocess.run(
                ["oggenc", "--quality", str(quality), "--raw", "--raw-bits=16",
                 f"--raw-chan={channels}", f"--raw-rate={sample_rate}",
                 "-o", "-", "-"],
                input=pcm, capture_output=True, check=True, timeout=300,
            )
            return proc.stdout
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            raise RuntimeError("OGG export needs the optional oggenc encoder. Use WAV or MP3 instead.") from e

    # ---- high-level exports ----

    def export_audio(self, text: str, voice_id: str, fmt: str, length_scale: float,
                     volume: float, bitrate: int, token: Optional[CancelToken] = None,
                     progress: Optional[Callable[[str, float], None]] = None,
                     ) -> tuple[bytes, float, int, int]:
        """Synthesize + encode the full text. Returns (data, audio_seconds, sample_rate, channels)."""
        if progress:
            progress("synth", 0.0)
        from .chunking import chunk
        parts = chunk(text, 1000)
        if not parts:
            raise ValueError("There is no text to export.")
        pcm_parts = []
        for index, part in enumerate(parts):
            if token and token.cancelled:
                raise KeyboardInterrupt("cancelled")
            pcm_part, sr, channels = self.synthesize_pcm(part["text"], voice_id, length_scale, volume)
            pcm_parts.append(pcm_part)
            if progress:
                progress("synth", .65 * (index + 1) / len(parts))
        pcm = b"".join(pcm_parts)
        if token and token.cancelled:
            raise KeyboardInterrupt("cancelled")
        if progress:
            progress("encode", 0.7)
        fmt = (fmt or "mp3").lower()
        if fmt == "wav":
            data = self.encode_wav(pcm, sr, channels)
        elif fmt == "ogg":
            data = self.encode_ogg(pcm, sr, channels)
        else:
            data = self.encode_mp3(pcm, sr, channels, bitrate)
        if progress:
            progress("done", 1.0)
        audio_seconds = len(pcm) / (sr * channels * 2)
        return data, audio_seconds, sr, channels


def write_mp3_with_tags(path: Path, mp3_bytes: bytes, *, title: str = "", artist: str = "",
                        album: str = "TextSpeak Pro", comment: str = "") -> None:
    """Stage tagged MP3 data beside the destination before replacing it."""
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix="." + path.stem, suffix=".mp3", dir=path.parent)
    os.close(fd)
    try:
        _write_mp3_with_tags(Path(temporary), mp3_bytes, title=title, artist=artist, album=album, comment=comment)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_mp3_with_tags(path: Path, mp3_bytes: bytes, *, title: str = "", artist: str = "",
                         album: str = "TextSpeak Pro", comment: str = "") -> None:
    """Write ``mp3_bytes`` to ``path`` and stamp ID3v2 tags."""
    path.write_bytes(mp3_bytes)
    try:
        from mutagen.easyid3 import EasyID3  # type: ignore
        from mutagen.id3 import ID3NoHeaderError  # type: ignore
        try:
            tags = EasyID3(str(path))
        except ID3NoHeaderError:
            from mutagen.mp3 import MP3  # type: ignore
            mp3 = MP3(str(path))
            mp3.add_tags()
            mp3.save()
            tags = EasyID3(str(path))
        if title:
            tags["title"] = title
        if artist:
            tags["artist"] = artist
        if album:
            tags["album"] = album
        if comment:
            # EasyID3 does not expose COMM directly; use album-comment or just skip.
            pass
        tags.save()
    except Exception as e:  # noqa: BLE001 - tag failure must not break export
        log.warning("Could not write ID3 tags to %s: %s", path, e)
