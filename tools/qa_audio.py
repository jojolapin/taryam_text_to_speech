"""Real installed-voice/export check using generated English/French fixtures."""
import argparse
import io
import json
import os
import sys
import time
import wave
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
parser = argparse.ArgumentParser()
parser.add_argument("voice_dir")
parser.add_argument("output")
args = parser.parse_args()
output = Path(args.output).resolve()
output.mkdir(parents=True, exist_ok=True)
os.environ["TEXTSPEAK_DATA_DIR"] = str(output)
from app.tts_engine import TTSEngine, write_mp3_with_tags
from mutagen.mp3 import MP3

engine = TTSEngine()
engine.voices_dir = lambda: Path(args.voice_dir)
results = []
for voice in engine.discover_voices():
    started = time.monotonic()
    text = "Bonjour. Ceci est un test de lecture avec des caractères accentués." if voice["id"].startswith("fr_") else "Hello. This is a generated test of clear speech and audio export."
    wav, seconds, rate, channels = engine.export_audio(text, voice["id"], "wav", 1.0, 1.0, 128)
    with wave.open(io.BytesIO(wav)) as reader:
        assert reader.getnframes() > 1000
    (output/(voice["id"]+".wav")).write_bytes(wav)
    pcm, sr, ch = engine.synthesize_pcm(text, voice["id"])
    mp3_path = output/(voice["id"]+".mp3")
    write_mp3_with_tags(mp3_path, engine.encode_mp3(pcm, sr, ch), title="Generated QA fixture")
    assert MP3(mp3_path).info.length > 0
    result = {"voice":voice["id"], "wav_seconds":round(seconds,2), "mp3_seconds":round(MP3(mp3_path).info.length,2), "elapsed":round(time.monotonic()-started,2)}
    results.append(result)
    print(json.dumps(result), flush=True)
(output/"audio-results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
