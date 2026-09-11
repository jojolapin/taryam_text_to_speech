"""Exercise visible export controls with real Piper audio and isolated file dialogs."""
import argparse
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

from PySide6.QtWidgets import QApplication, QFileDialog
from mutagen.mp3 import MP3
from mutagen.easyid3 import EasyID3
from app.bridge import Bridge
from app.settings import Settings
from app.native_window import MainWindow
from app.documents import new_document

app = QApplication([])
app.setStyle("Fusion")
settings = Settings()
bridge = Bridge(settings=settings)
bridge.engine.voices_dir = lambda: Path(args.voice_dir).resolve()
voice = next(v["id"] for v in bridge.engine.discover_voices() if v["id"].startswith("en_"))
doc = new_document(id="export-qa", title="Export QA", voice=voice,
    text="This is the first exported paragraph.\n\nThis is the second exported paragraph.")
window = MainWindow(settings, bridge, snapshot={"docs":[doc], "activeId":doc["id"]})
window.show()
errors, results = [], []
window.show_error = errors.append
try:
    scenarios = [(False, "mp3", rate) for rate in (64,128,192,256,320)] + [
        (False,"wav",128), (True,"mp3",192), (True,"wav",128)]
    for batch, fmt, bitrate in scenarios:
        folder = output / f'{"batch" if batch else "single"}-{fmt}-{bitrate}'
        folder.mkdir(exist_ok=True)
        QFileDialog.getSaveFileName = lambda *args, target=folder/f"reading.{fmt}", **kwargs: (str(target), "")
        QFileDialog.getExistingDirectory = lambda *args, target=folder, **kwargs: str(target)
        panel = window.export_panel
        panel.format.setCurrentIndex(panel.format.findData(fmt))
        panel.bitrate.setCurrentIndex(panel.bitrate.findData(bitrate))
        panel.author.setText("TextSpeak export QA")
        (panel.batch if batch else panel.generate).click()
        deadline = time.monotonic() + 60
        while window.export_request and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        assert window.export_request is None, "Export timeout"
        assert not errors, errors
        files = list(folder.glob("*."+fmt))
        assert len(files) == (2 if batch else 1), files
        for file in files:
            if fmt == "mp3":
                audio = MP3(file)
                assert audio.info.length > 0
                assert abs(audio.info.bitrate/1000 - bitrate) < 2, (bitrate, audio.info.bitrate)
                assert EasyID3(file)["artist"] == ["TextSpeak export QA"]
            else:
                with wave.open(str(file)) as audio:
                    assert audio.getnframes() > 1000 and audio.getsampwidth() == 2
        result = dict(batch=batch, format=fmt, bitrate=bitrate if fmt=="mp3" else None, files=len(files), passed=True)
        results.append(result)
        print(json.dumps(result), flush=True)
    (output/"export-results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
finally:
    window.close()
    bridge.pool.waitForDone()
