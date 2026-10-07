"""Measure the installed Kokoro cache. Does not change the saved workspace.

Run with the build environment:

    .venv-build\\Scripts\\python.exe tools\\qa_kokoro_validate.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import wave
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from app.qa_audio import EN_LINE, FR_LINE, pcm_stats, play_wav, rss_bytes, wav_duration
from app.speech_engines.kokoro_catalog import voices
from app.speech_engines.kokoro_engine import (
    KokoroEngine,
    _load,
    model_path,
    models_ready,
    reading_blocks,
    unload,
    voices_path,
)
from app.tts_engine import TTSEngine


OUT = ROOT / "build" / "qa" / "kokoro-validation"
PARAGRAPH = (
    "On Tuesday morning, Dr. Hale opened the letter and read it aloud. "
    '"The invoice is $1,250.50," he said, "and it is due on Jan. 3, 2024, at 3:30 p.m." '
    "Mr. Cole checked the U.S. account, i.e. the one ending in 4412, then nodded."
)
LONG_TEXT = """
Dr. Elena Hale set the kettle on the stove and opened the window. The street was already awake. A bus hissed at the corner, a dog answered from the bakery, and the clock over the bank showed 7:42 a.m. She had promised herself one quiet page before the day began, but the page had other plans.

"Read the last paragraph twice," said the note from Mr. Cole. "The figure is $1,250.50, not $125.05, and the meeting is on Jan. 3, 2024, at 3:30 p.m. If the train is late, call the U.S. office, i.e. extension 4412." Elena read it again, slower, because numbers have a way of slipping when a person is tired.

She tested the short lines first. Ready. Wait. Go. Then she returned to the long one, the sentence that refused to end, the sentence that carried the invoice, the date, the time, the extension, and the small warning about the train, all the way to the period that finally let her breathe.

The second paragraph belonged to the street. Mrs. Lang waved from the step. Capt. Ortiz locked the gate. A child counted, "One, two, three," and then lost the count on purpose. Someone asked whether St. Mary's would open early. Someone else said no. The answers were short. The pauses were not empty; they were part of the walk.

By midmorning the letter had become a story. Elena quoted Mr. Cole to the empty kitchen: "Do not skip the ending." She wrote 12% in the margin, circled Fig. 4, and added the words "see also Vol. 2." Abbreviations stayed whole. Decimals stayed whole. The quotation marks stayed where he had put them.

A longer stretch followed, because a real reading is not a slogan. She described the room: the chipped blue cup, the stack of envelopes, the pencil with the bitten end, the rain that had not yet decided to fall. She named the people who would hear the letter later, including Prof. Nguyen, Sr. Adeyemi, and the clerk who always said "one moment" and meant it. None of those names were a reason to stop. The point was to keep going until the thought was finished.

After lunch she read the corrections. Item 1 asked for the date. Item 2 asked for the amount. Item 3 asked her to repeat the final warning without adding a word. She did. The train might be late. Call extension 4412. Do not skip the ending. When she reached that last period, the kettle clicked off, the dog stopped barking, and the page was done.

The afternoon reading was longer, and that was the point. A document is not a slogan repeated until the timer runs out. Elena turned to the minutes of the March meeting, which began with a question and ended with a decision. "Are we buying the spare press?" asked Lt. Rahman. "Not at $4,800," answered Ms. Idris. "We can service the old one for $640, provided the parts arrive before Apr. 18." Nobody interrupted the figure. Nobody turned the date into a guess.

She kept a tally in the margin. Page 1 had the kettle and the bus. Page 2 had the invoice. Page 3 had the street and the names. Page 4, this one, had the press, the parts, and the argument about whether a repaired machine was braver than a new one. The argument lasted six sentences. Then it stopped, because the room had agreed, and agreement does not need a drum roll.

There was still the letter from the archive. It quoted a line she had loved as a student: "Measure twice, then read it aloud." The archivist, Dr. Pell, had added a postscript in smaller type. The box number was 19. The shelf was C. The requested hours were 10:15 a.m. to 11:00 a.m., and the fee was 0.00 because the copy was for the school. Elena smiled at the zero. A zero is still a number, and a careful voice does not swallow it.

She practiced the awkward bits on their own. Ph.D. Nguyen. U.K. office. e.g. the blue folder. i.e. the one with the torn corner. St. Mary's, again, because the first mention had been easy and the second should be too. Then she put them back into sentences, where they belonged, between ordinary words and ordinary pauses.

Near the end she allowed one quiet inventory of what the listener would need. The amount is $1,250.50. The date is Jan. 3, 2024. The time is 3:30 p.m. The extension is 4412. The press stays. The parts must arrive before Apr. 18. The archive opens at 10:15 a.m. None of those facts was new. Hearing them together was the test: a run of details, then a human sentence after them, so the list did not become the whole voice.

Elena closed the folder. She did not add a moral, and she did not return to the first page to make the ending match the beginning by force. The dog had started up again, one short bark and then silence. The clock said 4:06 p.m. She spoke the final line only once, in the same tone as the rest. "That is the end of the letter." The kettle was cold. The window stayed open. The reading was finished.
""".strip()


def _save(report: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


def _words(text: str) -> int:
    return len(text.split())


def _mp3_duration(data: bytes) -> float:
    from mutagen.mp3 import MP3

    return float(MP3(BytesIO(data)).info.length)


def _accept(stats: dict, words: int) -> str:
    duration = stats["duration_s"]
    if stats["sample_rate"] <= 0 or stats["peak"] < 1000:
        return "silent or invalid"
    if stats["clipped_ratio"] > 0.005:
        return "clipped"
    low = words / 5.5
    high = max(8.0, words / 1.15)
    if not (low <= duration <= high):
        return f"duration {duration}s outside {low:.1f}-{high:.1f}"
    return ""


def _synth(engine, text: str, voice: str) -> dict:
    rss_before = rss_bytes()
    started = time.perf_counter()
    pcm, rate, channels = engine.synthesize_pcm(text, voice)
    elapsed = time.perf_counter() - started
    stats = pcm_stats(pcm, rate)
    stats.update(
        voice=voice,
        words=_words(text),
        channels=channels,
        synth_s=round(elapsed, 3),
        rtf=round(elapsed / stats["duration_s"], 3) if stats["duration_s"] else None,
        rss_before=rss_before,
        rss_after=rss_bytes(),
    )
    problem = _accept(stats, stats["words"])
    if problem:
        stats["problem"] = problem
    return stats, pcm


def _export(engine, text: str, voice: str, stem: Path) -> dict:
    wav, seconds, rate, _channels = engine.export_audio(text, voice, "wav", 1.0, 1.0, 160)
    mp3, _seconds, mp3_rate, _channels = engine.export_audio(text, voice, "mp3", 1.0, 1.0, 160)
    stem.with_suffix(".wav").write_bytes(wav)
    stem.with_suffix(".mp3").write_bytes(mp3)
    wav_s = wav_duration(wav)
    mp3_s = _mp3_duration(mp3)
    return {
        "wav_s": round(wav_s, 3),
        "mp3_s": round(mp3_s, 3),
        "wav_bytes": len(wav),
        "mp3_bytes": len(mp3),
        "rate": rate,
        "mp3_rate": mp3_rate,
        "declared_s": round(seconds, 3),
        "wav_matches": abs(wav_s - seconds) < 0.08,
        "mp3_matches": abs(mp3_s - seconds) < 0.45,
    }


def _blocks(text: str) -> dict:
    blocks = reading_blocks(text)
    covered = " ".join(block["text"] for block in blocks)
    return {
        "blocks": len(blocks),
        "chars": [len(block["text"]) for block in blocks],
        "gaps_ms": [block["gap_ms"] for block in blocks],
        "covers_source": " ".join(text.split()) == " ".join(covered.split()),
        "final_text": blocks[-1]["text"] if blocks else "",
        "repeated": covered.lower().count("do not skip the ending") if "ending" in text.lower() else None,
    }


def _workspace() -> dict:
    root = os.environ.get("APPDATA", "")
    path = Path(root) / "JojoLapin" / "TextSpeak Pro" / "workspace-v2.json"
    if not path.is_file():
        return {"present": False}
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for doc in raw.get("docs", []):
        rows.append({
            "title": doc.get("title", ""),
            "provider": doc.get("provider", ""),
            "voice": doc.get("voice", ""),
            "chars": len(doc.get("text", "")),
        })
    piper = [row for row in rows if row["provider"] == "piper"]
    migrated = [row for row in piper if str(row["voice"]).startswith("kokoro:")]
    return {
        "present": True,
        "documents": len(rows),
        "rows": rows,
        "piper_documents": len(piper),
        "piper_documents_rewritten_to_kokoro": len(migrated),
    }


def _voice_bank() -> dict:
    import numpy as np

    with np.load(voices_path()) as bank:
        names = sorted(getattr(bank, "files", []))
    catalog = voices()
    return {
        "installed_count": len(names),
        "french_installed": [name for name in names if name.startswith("ff_") or name.startswith("fm_")],
        "french_male_installed": [name for name in names if name.startswith("fm_")],
        "catalog_french": [
            {"id": row["id"], "gender": row["gender"]}
            for row in catalog if row["language"] == "fr-FR"
        ],
    }


def _download_probe(report: dict) -> None:
    """Exercise a temporary cache. The user's cached model is not modified."""
    temp = OUT / "download-cache"
    if temp.exists():
        import shutil
        shutil.rmtree(temp)
    temp.mkdir(parents=True)
    code = r"""
import os, sys, threading
from pathlib import Path
os.environ["TEXTSPEAK_DATA_DIR"] = sys.argv[1]
sys.path.insert(0, sys.argv[2])
from app.speech_engines import kokoro_engine as k

mode = sys.argv[3]
folder = Path(sys.argv[1]) / "models" / "kokoro"
if mode == "cancel":
    cancel = threading.Event()
    def progress(done, total):
        # download_models reports overall units, not raw bytes.
        if done > 0:
            cancel.set()
    try:
        k.download_models(progress=progress, cancel=cancel)
        print("RESULT success")
    except KeyboardInterrupt:
        print("RESULT cancelled")
    parts = list(folder.glob("*.part"))
    print("PARTS", len(parts))
    print("READY", k.models_ready())
elif mode == "offline":
    def refuse(url, dest, progress=None, cancel=None):
        import socket
        raise ConnectionError("network unreachable")
    k._stream_download = refuse
    try:
        k.download_models()
        print("RESULT success")
    except k.KokoroError as exc:
        print("RESULT", exc.code)
    print("PARTS", len(list(folder.glob("*.part"))))
    print("READY", k.models_ready())
elif mode == "full":
    k.download_models()
    print("READY", k.models_ready())
    print("MODEL", k.model_path().stat().st_size)
    print("VOICES", k.voices_path().stat().st_size)
"""
    def run(mode: str, timeout: int) -> str:
        proc = subprocess.run(
            [sys.executable, "-c", code, str(temp), str(ROOT), mode],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return (proc.stdout or "") + (proc.stderr or "")

    report["download"] = {}
    try:
        report["download"]["interrupted"] = run("cancel", 180)
    except Exception as exc:
        report["download"]["interrupted"] = f"{type(exc).__name__}: {exc}"
    try:
        report["download"]["offline"] = run("offline", 60)
    except Exception as exc:
        report["download"]["offline"] = f"{type(exc).__name__}: {exc}"
    import shutil
    shutil.rmtree(temp, ignore_errors=True)
    temp.mkdir(parents=True)
    try:
        report["download"]["full"] = run("full", 600)
    except Exception as exc:
        report["download"]["full"] = f"{type(exc).__name__}: {exc}"
    shutil.rmtree(temp, ignore_errors=True)


def main() -> int:
    from app.speech_engines.hardware import probe_hardware

    report: dict = {
        "hardware": probe_hardware(),
        "long_words": _words(LONG_TEXT),
        "model_ready": models_ready(),
        "model_bytes": model_path().stat().st_size if model_path().exists() else 0,
        "voices_bytes": voices_path().stat().st_size if voices_path().exists() else 0,
        "workspace": _workspace(),
        "bank": _voice_bank(),
        "long_structure": _blocks(LONG_TEXT),
        "paragraph_structure": _blocks(PARAGRAPH),
    }
    _save(report)
    app = QApplication.instance() or QApplication([])
    engine = KokoroEngine()
    unload()
    rss_before_load = rss_bytes()
    started = time.perf_counter()
    _load()
    report["init_s"] = round(time.perf_counter() - started, 3)
    report["rss_before_load"] = rss_before_load
    report["rss_after_load"] = rss_bytes()
    _save(report)

    cases = [
        ("en_female_short", "kokoro:af_heart", EN_LINE),
        ("en_female_short_again", "kokoro:af_heart", EN_LINE),
        ("en_male_short", "kokoro:am_michael", EN_LINE),
        ("fr_female_short", "kokoro:ff_siwis", FR_LINE),
        ("en_female_paragraph", "kokoro:af_heart", PARAGRAPH),
        ("en_male_paragraph", "kokoro:am_michael", PARAGRAPH),
        ("fr_female_paragraph", "kokoro:ff_siwis", PARAGRAPH),
    ]
    report["kokoro"] = {}
    for name, voice, text in cases:
        print(f"kokoro {name}", flush=True)
        stats, pcm = _synth(engine, text, voice)
        if name.endswith("short") or name.endswith("paragraph"):
            stats["export"] = _export(engine, text, voice, OUT / name)
        report["kokoro"][name] = stats
        if name == "en_female_short":
            from app.speech_engines.kokoro_engine import _wav_bytes
            report["playback"] = play_wav(app, _wav_bytes(pcm, stats["sample_rate"]))
        _save(report)

    print("kokoro long", flush=True)
    peak = {"rss": rss_bytes()}
    stop = threading.Event()

    def watch():
        while not stop.wait(0.25):
            peak["rss"] = max(peak["rss"], rss_bytes())

    threading.Thread(target=watch, daemon=True).start()
    stats, pcm = _synth(engine, LONG_TEXT, "kokoro:af_heart")
    stop.set()
    stats["rss_peak"] = peak["rss"]
    from app.speech_engines.kokoro_engine import _wav_bytes
    from app.tts_engine import TTSEngine as _Encoder

    wav = _wav_bytes(pcm, stats["sample_rate"])
    mp3 = _Encoder().encode_mp3(pcm, stats["sample_rate"], 1, 160)
    (OUT / "long.wav").write_bytes(wav)
    (OUT / "long.mp3").write_bytes(mp3)
    wav_s = wav_duration(wav)
    mp3_s = _mp3_duration(mp3)
    stats["export"] = {
        "wav_s": round(wav_s, 3),
        "mp3_s": round(mp3_s, 3),
        "wav_bytes": len(wav),
        "mp3_bytes": len(mp3),
        "wav_matches": abs(wav_s - stats["duration_s"]) < 0.08,
        "mp3_matches": abs(mp3_s - stats["duration_s"]) < 0.45,
        "source": "measured pcm encoded with the same wav and mp3 encoders export uses",
    }
    stats["structure"] = report["long_structure"]
    report["kokoro"]["long"] = stats
    _save(report)

    piper = TTSEngine()
    discovered = {row["id"] for row in piper.discover_voices()}
    pairs = [
        ("en_female", "en_US-lessac-medium", EN_LINE, PARAGRAPH),
        ("en_male", "en_US-joe-medium", EN_LINE, PARAGRAPH),
        ("fr_female", "fr_FR-siwis-medium", FR_LINE, PARAGRAPH),
    ]
    report["piper"] = {}
    for label, voice, short, paragraph in pairs:
        if voice not in discovered:
            report["piper"][label] = {"missing": voice}
            continue
        print(f"piper {label}", flush=True)
        short_stats, _pcm = _synth(piper, short, voice)
        paragraph_stats, _pcm = _synth(piper, paragraph, voice)
        short_stats["export"] = _export(piper, short, voice, OUT / f"piper-{label}")
        report["piper"][label] = {"short": short_stats, "paragraph": paragraph_stats}
        _save(report)
    if "en_US-lessac-medium" in discovered:
        print("piper long", flush=True)
        long_stats, _pcm = _synth(piper, LONG_TEXT, "en_US-lessac-medium")
        report["piper"]["long"] = long_stats
        _save(report)

    print("download probes", flush=True)
    _download_probe(report)
    _save(report)
    problems = []
    for group in ("kokoro",):
        for name, stats in report.get(group, {}).items():
            if isinstance(stats, dict) and stats.get("problem"):
                problems.append(f"{group}:{name}: {stats['problem']}")
            export = stats.get("export") if isinstance(stats, dict) else None
            if export and not (export["wav_matches"] and export["mp3_matches"]):
                problems.append(f"{group}:{name}: export duration mismatch")
    if not report["long_structure"]["covers_source"]:
        problems.append("long text coverage failed")
    if report["workspace"].get("piper_documents_rewritten_to_kokoro"):
        problems.append("saved piper bookmarks were rewritten")
    if report.get("playback") != "playing":
        problems.append(f"playback {report.get('playback')}")
    report["problems"] = problems
    _save(report)
    print(json.dumps({"problems": problems, "init_s": report.get("init_s")}, indent=2))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
