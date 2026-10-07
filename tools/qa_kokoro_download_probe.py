"""Download-failure checks against a temporary cache, not the user's model."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "build" / "qa" / "kokoro-validation" / "download-probe"


def main() -> int:
    import shutil

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    os.environ["TEXTSPEAK_DATA_DIR"] = str(OUT)
    from app.speech_engines import kokoro_engine as k

    folder = OUT / "models" / "kokoro"
    report = []

    cancel = threading.Event()

    def progress(done, total):
        if done > 0:
            cancel.set()

    try:
        k.download_models(progress=progress, cancel=cancel)
        report.append("interrupt: unexpected success")
    except KeyboardInterrupt:
        parts = list(folder.glob("*.part"))
        ready = k.models_ready()
        report.append(f"interrupt: cancelled parts={len(parts)} ready={ready}")
    except Exception as exc:
        report.append(f"interrupt: {type(exc).__name__}: {exc}")

    shutil.rmtree(folder, ignore_errors=True)
    k.MODEL_URL = "http://127.0.0.1:1/kokoro-v1.0.onnx"
    k.VOICES_URL = "http://127.0.0.1:1/voices-v1.0.bin"
    try:
        k.download_models()
        report.append("offline: unexpected success")
    except k.KokoroError as exc:
        parts = list(folder.glob("*.part")) if folder.exists() else []
        report.append(f"offline: {exc.code} parts={len(parts)} ready={k.models_ready()}")

    folder.mkdir(parents=True, exist_ok=True)
    (folder / "kokoro-v1.0.onnx").write_bytes(b"\x08partial")
    (folder / "voices-v1.0.bin").write_bytes(b"PK\x03\x04partial")
    k._voices_stamp = None
    k._model_unreadable = False
    report.append(f"incomplete: ready={k.models_ready()}")

    model = folder / "kokoro-v1.0.onnx"
    with model.open("wb") as handle:
        handle.write(b"<html>error page")
        handle.truncate(80 * 1024 * 1024 + 64)
    k._voices_stamp = None
    report.append(f"corrupt-header: ready={k.models_ready()}")

    child = subprocess.run(
        [sys.executable, "-c",
         "import os,sys; os.environ['TEXTSPEAK_DATA_DIR']=sys.argv[1]; "
         "sys.path.insert(0, sys.argv[2]); "
         "from app.speech_engines.kokoro_engine import models_ready; "
         "print('restart', models_ready())",
         str(OUT), str(ROOT)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=60,
    )
    report.append((child.stdout or child.stderr).strip())

    # Piper must still synthesize from the real profile, not this broken cache.
    del os.environ["TEXTSPEAK_DATA_DIR"]
    from app.tts_engine import TTSEngine
    piper = TTSEngine()
    voice = next(row["id"] for row in piper.discover_voices() if str(row["id"]).startswith("en_"))
    _pcm, rate, channels = piper.synthesize_pcm("Piper still reads this sentence.", voice)
    report.append(f"piper-after-failure: voice={voice} rate={rate} channels={channels} bytes={len(_pcm)}")
    print("\n".join(report))
    shutil.rmtree(OUT, ignore_errors=True)
    failed = any("unexpected" in line or "ready=True" in line or "restart True" in line for line in report)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
