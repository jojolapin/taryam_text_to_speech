"""Checks and preparation for a voice-cloning reference recording.

Pocket TTS ``export-voice`` uses the first 30 seconds of the file. The project
does not publish a hard minimum length. Samples with less than a few seconds
of speech are rejected here because they do not carry a usable voice.
About 10 to 20 seconds of clean speech is the range shown to the user.

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

POCKET_MAX_REFERENCE_S = 30.0
USABLE_SPEECH_S = 3.0
RECOMMENDED_SPEECH_S = 8.0
TARGET_RATE = 24000
_FRAME_S = 0.02
_SPEECH_RMS = 0.015
_EMPTY_PEAK = 0.008
_QUIET_PEAK = 0.05
_CLIP_LEVEL = 0.99


@dataclass
class AudioReport:
    level: str
    duration_s: float
    sample_rate: int
    channels: int
    peak: float
    speech_s: float
    clipped_ratio: float
    notes: list[str] = field(default_factory=list)


def _read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    if width == 2:
        samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 1:
        samples = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 4:
        samples = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"unsupported wav sample width {width}")
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return np.ascontiguousarray(samples, dtype=np.float32), int(rate)


def _speech_seconds(samples: np.ndarray, rate: int) -> float:
    if rate <= 0 or samples.size == 0:
        return 0.0
    frame = max(1, int(rate * _FRAME_S))
    count = 0
    for start in range(0, samples.size, frame):
        window = samples[start:start + frame]
        if window.size and float(np.sqrt(np.mean(window * window))) >= _SPEECH_RMS:
            count += 1
    return count * frame / rate


def analyze_samples(samples: np.ndarray, rate: int, channels: int) -> AudioReport:
    """Classify a mono float recording in the range -1 to 1."""
    audio = np.asarray(samples, dtype=np.float32).reshape(-1)
    duration = float(audio.size) / float(rate) if rate else 0.0
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    clipped = float(np.mean(np.abs(audio) >= _CLIP_LEVEL)) if audio.size else 0.0
    speech = _speech_seconds(audio, rate)
    notes: list[str] = []
    if peak < _EMPTY_PEAK or speech < 0.4:
        notes.append("empty")
    elif speech < USABLE_SPEECH_S:
        notes.append("too-short")
    else:
        if speech < RECOMMENDED_SPEECH_S:
            notes.append("short")
        if duration > POCKET_MAX_REFERENCE_S + 0.05:
            notes.append("long")
        if peak < _QUIET_PEAK:
            notes.append("quiet")
        silence_ratio = 1.0 - (speech / duration) if duration else 1.0
        if silence_ratio > 0.55:
            notes.append("silence")
    if clipped > 0.02:
        notes.append("clipping")
    elif "empty" not in notes:
        notes.append("no-clip")
    if "empty" not in notes and "quiet" not in notes and "clipping" not in notes:
        notes.append("level-ok")
    if any(code in notes for code in ("empty", "too-short", "clipping")):
        level = "error"
    elif any(code in notes for code in ("short", "long", "quiet", "silence")):
        level = "warning"
    else:
        level = "good"
    return AudioReport(
        level=level,
        duration_s=round(duration, 3),
        sample_rate=int(rate),
        channels=int(channels),
        peak=round(peak, 4),
        speech_s=round(speech, 3),
        clipped_ratio=round(clipped, 6),
        notes=notes,
    )


def analyze_wav(path: Path) -> AudioReport:
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        rate = handle.getframerate()
    samples, rate = _read_wav(path)
    return analyze_samples(samples, rate, channels)


def _trim_silence(samples: np.ndarray, rate: int) -> np.ndarray:
    frame = max(1, int(rate * _FRAME_S))
    first = 0
    last = samples.size
    for start in range(0, samples.size, frame):
        window = samples[start:start + frame]
        if window.size and float(np.sqrt(np.mean(window * window))) >= _SPEECH_RMS:
            first = start
            break
    for start in range(samples.size - frame, -1, -frame):
        window = samples[max(0, start):start + frame]
        if window.size and float(np.sqrt(np.mean(window * window))) >= _SPEECH_RMS:
            last = min(samples.size, start + frame)
            break
    pad = int(rate * 0.08)
    first = max(0, first - pad)
    last = min(samples.size, last + pad)
    if last <= first:
        return samples
    return samples[first:last]


def _resample(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate or samples.size == 0:
        return samples
    dest_len = max(1, int(round(samples.size * target_rate / source_rate)))
    old = np.linspace(0.0, 1.0, num=samples.size, endpoint=False)
    new = np.linspace(0.0, 1.0, num=dest_len, endpoint=False)
    return np.interp(new, old, samples).astype(np.float32)


def _write_wav(path: Path, samples: np.ndarray, rate: int) -> None:
    pcm = np.clip(samples, -1.0, 1.0)
    frames = (pcm * 32767.0).astype("<i2").tobytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(frames)


def prepare_wav(source: Path, dest: Path) -> tuple[AudioReport, list[str]]:
    """Write the mono clip Pocket will encode. Reject unusable audio."""
    with wave.open(str(source), "rb") as handle:
        channels = handle.getnchannels()
    samples, rate = _read_wav(source)
    report = analyze_samples(samples, rate, channels)
    actions: list[str] = []
    if channels > 1:
        actions.append("mono")
    if report.level == "error":
        return report, actions
    trimmed = _trim_silence(samples, rate)
    if trimmed.size != samples.size:
        actions.append("trim-silence")
    max_samples = int(POCKET_MAX_REFERENCE_S * rate)
    if trimmed.size > max_samples:
        trimmed = trimmed[:max_samples]
        actions.append("trim-30s")
    peak = float(np.max(np.abs(trimmed))) if trimmed.size else 0.0
    if _EMPTY_PEAK <= peak < _QUIET_PEAK:
        trimmed = trimmed * (0.7 / peak)
        actions.append("raise-level")
    prepared = _resample(trimmed, rate, TARGET_RATE)
    if rate != TARGET_RATE:
        actions.append("resample-24k")
    _write_wav(dest, prepared, TARGET_RATE)
    return report, actions
