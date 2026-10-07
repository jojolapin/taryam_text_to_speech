"""Measure Pocket TTS on this computer and save listening files.

The reference is a Kokoro preset unless --reference points at a recording the
user owns. A preset reference checks the pipeline. It is not a judgment of
similarity to a real person.

Samples under build/qa/pocket-cloning are left in place.
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
import wave
from pathlib import Path

import numpy as np

from app.speech_engines.clone_client import CloneClient, models_ready, shutdown_if_running
from app.speech_engines.clone_engine import CloneEngine
from app.speech_engines.clone_profiles import build_profile
from app.speech_engines.kokoro_engine import KokoroEngine
from app.tts_engine import TTSEngine


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "qa" / "pocket-cloning"

REFERENCE_TEXT = (
    "This is a clean reference recording for TextSpeak Pro. "
    "I am speaking at a steady pace, in a quiet room, with no music and no second voice. "
    "The sentences stay on one idea so the clone has enough of this sound to follow."
)
EN_SHORT = "This is a preview of my cloned voice in TextSpeak Pro."
FR_SHORT = "Ceci est un aperçu de ma voix clonée dans TextSpeak Pro."
EN_PARAGRAPH = (
    "The harbor was quiet after the rain. Elena read the note twice, "
    "then set it beside the window where the light was plain and even. "
    "Nothing in the room was in a hurry, and the sentence that followed "
    "kept the same voice from the first word to the last."
)
FR_PARAGRAPH = (
    "Le port était calme après la pluie. Élena a lu la note deux fois, "
    "puis elle l'a posée près de la fenêtre, dans une lumière simple. "
    "Rien dans la pièce n'était pressé, et la phrase suivante a gardé "
    "la même voix du premier mot jusqu'au dernier."
)
EN_LONG = "\n\n".join([
    "Chapter one. The reading begins with a full breath and a clear first sentence. "
    "A cloned voice has to stay the same person here, not only for this line, but for the page that follows.",
    "She crossed the room and opened the folder. Inside were dates, names, and one short list of parts. "
    "The amount was one thousand two hundred fifty dollars and fifty cents. The meeting was on January third, "
    "at half past three. None of those details was allowed to change the speaker.",
    "On the second page the paragraphs grew longer. The point was not to rush. "
    "Each sentence had to arrive whole, without a new accent, without a skipped ending, and without a word that was not on the page.",
    "He asked whether the train would wait. She answered that the office closed at six, "
    "and that the spare key was still in the blue drawer. The listener should hear one person telling one story.",
    "Near the end she repeated the facts in the same calm tone. The date stayed January third. "
    "The time stayed half past three. The drawer stayed blue. Then she stopped, because the page had stopped.",
    "This is the last paragraph of the long reading. If the voice is still the voice from the first sentence, "
    "the clone held its identity across the pages.",
])


def _duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / float(handle.getframerate())


def _peak(path: Path) -> int:
    with wave.open(str(path), "rb") as handle:
        frames = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2")
    return int(np.max(np.abs(frames))) if frames.size else 0


def _write_wav(path: Path, data: bytes) -> dict:
    path.write_bytes(data)
    return {
        "path": str(path.name),
        "bytes": len(data),
        "duration_s": round(_duration(path), 3),
        "peak": _peak(path),
    }


def _torch_in_this_process() -> bool:
    try:
        import torch  # noqa: F401
    except Exception:
        return False
    return True


def _reference(path: Path) -> None:
    if path.is_file() and path.stat().st_size > 1000:
        return
    wav = KokoroEngine().synthesize_wav_bytes(REFERENCE_TEXT, "kokoro:af_heart")
    path.write_bytes(wav)


def _timed(synth, text: str, voice: str, dest: Path) -> dict:
    started = time.perf_counter()
    wav = synth(text, voice)
    elapsed = time.perf_counter() - started
    info = _write_wav(dest, wav)
    info["synth_s"] = round(elapsed, 3)
    info["rtf"] = round(elapsed / info["duration_s"], 3) if info["duration_s"] else None
    return info


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", default="")
    parser.add_argument("--output", default=str(OUT))
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "torch_in_main_process": _torch_in_this_process(),
        "reference_kind": "user" if args.reference else "kokoro-preset-not-a-person",
    }
    if report["torch_in_main_process"]:
        raise SystemExit("PyTorch is importable in the main process. Pocket must stay in clone_runtime.")

    reference = Path(args.reference) if args.reference else output / "reference-kokoro-af-heart.wav"
    _reference(reference)
    shutil.copyfile(reference, output / "reference.wav")
    report["reference_s"] = round(_duration(output / "reference.wav"), 3)

    client = CloneClient()
    startup = time.perf_counter()
    client.ensure_running()
    report["service_startup_s"] = round(time.perf_counter() - startup, 3)
    cached = models_ready()
    load_started = time.perf_counter()
    status = client.ensure_models()
    report["model_load_s"] = round(time.perf_counter() - load_started, 3)
    report["models_were_cached"] = cached
    report["status_after_load"] = {
        "pocket_tts": status.get("pocket_tts"),
        "torch": status.get("torch"),
        "models_loaded": status.get("models_loaded"),
        "rss_bytes": status.get("rss_bytes"),
        "download_bytes": status.get("download_bytes"),
    }
    again = time.perf_counter()
    second = client.ensure_models()
    report["second_ensure_s"] = round(time.perf_counter() - again, 3)
    report["download_bytes_after_second_ensure"] = second.get("download_bytes")

    profile_started = time.perf_counter()
    profile = build_profile(
        display_name="Pipeline check",
        source_wav=output / "reference.wav",
        source_kind="import",
        transcript="",
        consent=True,
        presented="I confirm that this is my voice or that I have permission to create and use this voice profile.",
        locale="en",
        engine_version=str(status.get("pocket_tts") or ""),
        service=client,
    )
    report["profile_s"] = round(time.perf_counter() - profile_started, 3)
    report["profile_id"] = profile["voice_id"]
    voice_en = profile["voice_id"] + ":en"
    voice_fr = profile["voice_id"] + ":fr"
    clone = CloneEngine(client)
    kokoro = KokoroEngine()
    piper = TTSEngine()
    piper_en = next(row["id"] for row in piper.discover_voices() if str(row["id"]).startswith("en_US-"))
    piper_fr = next((row["id"] for row in piper.discover_voices() if str(row["id"]).startswith("fr_")), "")

    def clone_wav(text: str, voice: str) -> bytes:
        return clone.synthesize_wav_bytes(text, voice)

    def kokoro_wav(text: str, voice: str) -> bytes:
        return kokoro.synthesize_wav_bytes(text, voice)

    def piper_wav(text: str, voice: str) -> bytes:
        data, _seconds, _rate, _channels = piper.export_audio(text, voice, "wav", 1.0, 1.0, 128)
        return data

    samples = {
        "pocket_en_short_first": _timed(clone_wav, EN_SHORT, voice_en, output / "pocket-en-short.wav"),
        "pocket_en_short_second": _timed(clone_wav, EN_SHORT, voice_en, output / "pocket-en-short-second.wav"),
        "pocket_en_paragraph": _timed(clone_wav, EN_PARAGRAPH, voice_en, output / "pocket-en-paragraph.wav"),
        "pocket_fr_short": _timed(clone_wav, FR_SHORT, voice_fr, output / "pocket-fr-short.wav"),
        "pocket_fr_paragraph": _timed(clone_wav, FR_PARAGRAPH, voice_fr, output / "pocket-fr-paragraph.wav"),
        "pocket_en_long": _timed(clone_wav, EN_LONG, voice_en, output / "pocket-en-long.wav"),
        "kokoro_en_short": _timed(kokoro_wav, EN_SHORT, "kokoro:af_heart", output / "kokoro-en-short.wav"),
        "kokoro_en_paragraph": _timed(kokoro_wav, EN_PARAGRAPH, "kokoro:af_heart", output / "kokoro-en-paragraph.wav"),
        "kokoro_fr_short": _timed(kokoro_wav, FR_SHORT, "kokoro:ff_siwis", output / "kokoro-fr-short.wav"),
        "kokoro_fr_paragraph": _timed(kokoro_wav, FR_PARAGRAPH, "kokoro:ff_siwis", output / "kokoro-fr-paragraph.wav"),
        "piper_en_short": _timed(piper_wav, EN_SHORT, piper_en, output / "piper-en-short.wav"),
        "piper_en_paragraph": _timed(piper_wav, EN_PARAGRAPH, piper_en, output / "piper-en-paragraph.wav"),
    }
    if piper_fr:
        samples["piper_fr_short"] = _timed(piper_wav, FR_SHORT, piper_fr, output / "piper-fr-short.wav")
        samples["piper_fr_paragraph"] = _timed(piper_wav, FR_PARAGRAPH, piper_fr, output / "piper-fr-paragraph.wav")
    report["samples"] = samples
    report["piper_voices"] = {"en": piper_en, "fr": piper_fr}
    report["status_after_speech"] = client._request("GET", "/status", timeout=10)

    wav_export = clone.export_audio(EN_SHORT, voice_en, "wav", 1.0, 1.0, 128)[0]
    mp3_export = clone.export_audio(EN_SHORT, voice_en, "mp3", 1.0, 1.0, 128)[0]
    (output / "pocket-export.wav").write_bytes(wav_export)
    (output / "pocket-export.mp3").write_bytes(mp3_export)
    report["export"] = {"wav_bytes": len(wav_export), "mp3_bytes": len(mp3_export)}

    shutdown_if_running()
    time.sleep(0.6)
    report["service_stopped"] = not client.connect_existing()
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "startup_s": report["service_startup_s"],
        "model_load_s": report["model_load_s"],
        "profile_s": report["profile_s"],
        "en_short_rtf": samples["pocket_en_short_second"]["rtf"],
        "en_long_s": samples["pocket_en_long"]["duration_s"],
        "en_long_rtf": samples["pocket_en_long"]["rtf"],
        "rss": report["status_after_speech"].get("rss_bytes"),
        "stopped": report["service_stopped"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
