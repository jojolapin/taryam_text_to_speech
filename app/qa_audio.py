"""Headless speech check used by the packaged executable.

Writes a JSON report and short audio files. It does not open the editor and
does not call the OpenAI API.

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import json
import os
import time
import wave
from pathlib import Path

import numpy as np
from PySide6.QtCore import QBuffer, QEventLoop, QIODevice, QTimer, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from .documents import atomic_write


EN_LINE = "The quick brown fox reads the final sentence clearly."
FR_LINE = "Le renard brun lit la dernière phrase clairement."


def rss_bytes() -> int:
    """Current process working set. Zero when the figure is unavailable."""
    try:
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.K32GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD,
        ]
        kernel.K32GetProcessMemoryInfo.restype = wintypes.BOOL
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        ok = kernel.K32GetProcessMemoryInfo(
            kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb,
        )
        return int(counters.WorkingSetSize) if ok else 0
    except Exception:
        return 0


def pcm_stats(pcm: bytes, sample_rate: int) -> dict:
    samples = np.frombuffer(pcm, dtype="<i2")
    count = int(samples.size)
    peak = int(np.max(np.abs(samples))) if count else 0
    clipped = int(np.count_nonzero(np.abs(samples) >= 32760)) if count else 0
    return {
        "samples": count,
        "sample_rate": int(sample_rate),
        "channels": 1,
        "duration_s": round(count / sample_rate, 3) if sample_rate else 0.0,
        "peak": peak,
        "clipped_samples": clipped,
        "clipped_ratio": round(clipped / count, 6) if count else 0.0,
    }


def wav_duration(data: bytes) -> float:
    with wave.open(__import__("io").BytesIO(data), "rb") as handle:
        return handle.getnframes() / handle.getframerate()


def play_wav(app, wav: bytes, timeout_s: float = 8.0) -> str:
    """Start native playback and return 'playing', an error, or 'timeout'."""
    player = QMediaPlayer()
    output = QAudioOutput()
    output.setVolume(0.2)
    player.setAudioOutput(output)
    buffer = QBuffer()
    buffer.setData(wav)
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    player.setSourceDevice(buffer, QUrl("qa.wav"))
    loop = QEventLoop()
    result = {"value": "timeout"}

    def started(state):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            result["value"] = "playing"
            player.stop()
            loop.quit()

    def failed(_error, message):
        result["value"] = message or "playback error"
        loop.quit()

    player.playbackStateChanged.connect(started)
    player.errorOccurred.connect(failed)
    QTimer.singleShot(int(timeout_s * 1000), loop.quit)
    player.play()
    loop.exec()
    player.stop()
    player.setSource(QUrl())
    buffer.close()
    app.processEvents()
    return result["value"]


def run_download(output) -> int:
    """Download the Kokoro cache into the current data directory and exit."""
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report: dict = {"ok": False, "errors": []}
    try:
        from .speech_engines.kokoro_engine import download_models, model_path, models_ready, voices_path

        download_models()
        report["ready"] = models_ready()
        report["model_bytes"] = model_path().stat().st_size if model_path().exists() else 0
        report["voices_bytes"] = voices_path().stat().st_size if voices_path().exists() else 0
        if not report["ready"]:
            report["errors"].append("download finished but the cache is not readable")
        report["ok"] = not report["errors"]
    except Exception as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
    atomic_write(output / "qa-download.json", json.dumps(report, indent=2).encode("utf-8"))
    return 0 if report["ok"] else 1


def run(app, output) -> int:
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report: dict = {"checks": [], "errors": [], "voices": [], "rss_bytes": rss_bytes()}
    started = time.perf_counter()
    try:
        _exercise(app, output, report)
    except Exception as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
    report["elapsed_s"] = round(time.perf_counter() - started, 2)
    report["ok"] = not report["errors"]
    atomic_write(output / "qa-audio.json", json.dumps(report, indent=2).encode("utf-8"))
    return 0 if report["ok"] else 1


def _exercise(app, output: Path, report: dict) -> None:
    from .openai_provider import OpenAIProvider
    from .settings import Settings
    from .speech_engines.kokoro_engine import KokoroEngine, models_ready, package_status
    from .speech_engines.router import resolve_provider
    from .tts_engine import TTSEngine

    installed, detail = package_status()
    if not installed:
        raise RuntimeError(f"Kokoro package missing: {detail}")
    report["checks"].append("kokoro package import")
    if not models_ready():
        raise RuntimeError("Kokoro model files are not ready")
    report["checks"].append("kokoro model cache")

    import espeakng_loader

    data_path = Path(espeakng_loader.get_data_path())
    library_path = Path(espeakng_loader.get_library_path())
    if not data_path.exists() or not library_path.exists():
        raise RuntimeError(f"espeak-ng missing: data={data_path} library={library_path}")
    report["espeak_data"] = str(data_path)
    report["espeak_library"] = str(library_path)
    report["checks"].append("espeak-ng located")

    assert resolve_provider("auto", kokoro_ready=True) == "kokoro"
    assert resolve_provider("auto", kokoro_ready=False) == "piper"
    assert resolve_provider("openai", kokoro_ready=True) == "openai"
    assert resolve_provider("clone", kokoro_ready=True) == "clone"
    assert resolve_provider("auto", kokoro_ready=True) != "clone"
    report["checks"].append("automatic routing stays local")

    engine = KokoroEngine()
    voices = (
        ("kokoro:af_heart", EN_LINE, "en-female"),
        ("kokoro:am_michael", EN_LINE, "en-male"),
        ("kokoro:ff_siwis", FR_LINE, "fr-female"),
    )
    first_wav = b""
    for voice_id, text, label in voices:
        t0 = time.perf_counter()
        pcm, rate, channels = engine.synthesize_pcm(text, voice_id)
        elapsed = time.perf_counter() - t0
        stats = pcm_stats(pcm, rate)
        stats.update(voice=voice_id, label=label, synth_s=round(elapsed, 3), channels=channels)
        if rate != 24000 or channels != 1:
            raise RuntimeError(f"{label} sample rate {rate} channels {channels}")
        if not (1.2 <= stats["duration_s"] <= 12):
            raise RuntimeError(f"{label} duration {stats['duration_s']}s is not reasonable")
        if stats["clipped_ratio"] > 0.005:
            raise RuntimeError(f"{label} clipping ratio {stats['clipped_ratio']}")
        if stats["peak"] < 1000:
            raise RuntimeError(f"{label} peak {stats['peak']} is silent")
        wav, _seconds, wav_rate, _ch = engine.export_audio(text, voice_id, "wav", 1.0, 1.0, 128)
        mp3, _seconds, mp3_rate, _ch = engine.export_audio(text, voice_id, "mp3", 1.0, 1.0, 128)
        (output / f"{label}.wav").write_bytes(wav)
        (output / f"{label}.mp3").write_bytes(mp3)
        if abs(wav_duration(wav) - stats["duration_s"]) > 0.05:
            raise RuntimeError(f"{label} wav duration does not match pcm")
        if wav_rate != 24000 or mp3_rate != 24000 or len(mp3) < 1000:
            raise RuntimeError(f"{label} export is incomplete")
        stats["wav_bytes"] = len(wav)
        stats["mp3_bytes"] = len(mp3)
        report["voices"].append(stats)
        if not first_wav:
            first_wav = wav
    report["checks"].append("kokoro english and french synthesis plus wav and mp3")

    playback = play_wav(app, first_wav)
    report["playback"] = playback
    if playback != "playing":
        raise RuntimeError(f"playback did not start: {playback}")
    report["checks"].append("native playback")

    piper = TTSEngine()
    discovered = piper.discover_voices()
    english = next((row["id"] for row in discovered if str(row["id"]).startswith("en_")), "")
    if not english:
        raise RuntimeError("no Piper English voice is installed")
    pcm, rate, channels = piper.synthesize_pcm(EN_LINE, english)
    stats = pcm_stats(pcm, rate)
    if stats["duration_s"] < 1.0 or stats["peak"] < 1000 or channels != 1:
        raise RuntimeError(f"Piper synthesis failed: {stats}")
    wav, _s, _r, _c = piper.export_audio(EN_LINE, english, "wav", 1.0, 1.0, 128)
    mp3, _s, _r, _c = piper.export_audio(EN_LINE, english, "mp3", 1.0, 1.0, 128)
    (output / "piper-en.wav").write_bytes(wav)
    (output / "piper-en.mp3").write_bytes(mp3)
    report["piper_voice"] = english
    report["piper"] = stats
    report["checks"].append("piper synthesis plus wav and mp3")

    provider = OpenAIProvider(Settings())
    available, _status = provider.is_available()
    report["openai_explicit_path"] = callable(getattr(provider, "synthesize", None))
    report["openai_configured"] = bool(available)
    report["openai_live_call"] = "skipped"
    if not report["openai_explicit_path"]:
        raise RuntimeError("OpenAI provider has no synthesize method")
    report["checks"].append("openai path present; live call skipped")
    try:
        import torch  # noqa: F401
        report["torch_in_app"] = True
    except Exception:
        report["torch_in_app"] = False
    if report["torch_in_app"]:
        raise RuntimeError("PyTorch is loaded in the main TextSpeak Pro process")
    report["checks"].append("main process has no PyTorch")
    if os.environ.get("TEXTSPEAK_QA_CLONE") == "1":
        from .speech_engines.clone_client import CloneClient, runtime_installed
        from .speech_engines.clone_errors import CloneError

        report["clone_runtime"] = runtime_installed()
        if not report["clone_runtime"]:
            raise RuntimeError("Pocket runtime was not found beside the application or TEXTSPEAK_CLONE_HOME")
        client = CloneClient()
        try:
            client.ensure_models()
            report["clone_ensure"] = "ok"
        except CloneError as exc:
            report["clone_ensure"] = exc.code
        finally:
            client.shutdown()
        if report["clone_ensure"] not in {"ok", "clone-model-gated"}:
            raise RuntimeError(f"Pocket service failed: {report['clone_ensure']}")
        report["checks"].append("pocket service responded")
    report["rss_after_bytes"] = rss_bytes()
