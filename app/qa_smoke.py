"""Explicit --self-test mode. Uses only a dedicated fixture profile; no network."""
import json
import os
import time
import wave
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from .documents import new_document, atomic_write


def run(app, settings, bridge, output, voice_dir=None):
    from .native_window import MainWindow
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if voice_dir:
        bridge.engine.voices_dir = lambda: Path(voice_dir).resolve()
    voices = bridge.engine.discover_voices()
    usable = [v for v in voices if v["id"].startswith("en_")]
    if not usable:
        raise RuntimeError("Self-test needs an installed English Piper voice.")
    voice = usable[0]["id"]
    settings.set("last_voice", voice)
    doc = new_document(id="qa-a", title="Bookmark A · playback test", voice=voice,
        text="This is the Text Speak Pro playback test. Speech continues while another bookmark is edited. " * 5)
    window = MainWindow(settings, bridge, snapshot={"docs":[doc], "activeId":doc["id"]})
    window.show()
    report = {"voice":voice, "checks":[], "errors":[]}
    stage = [0]
    started = time.monotonic()
    def error(message):
        report["errors"].append(message)
        finish(1)
    window.show_error = error
    window.playback.error.disconnect()
    window.playback.error.connect(error)

    def finish(code):
        if stage[0] == -1:
            return
        stage[0] = -1
        report["elapsed_seconds"] = round(time.monotonic()-started, 2)
        report["exit_code"] = code
        atomic_write(output / "smoke-result.json", json.dumps(report, indent=2).encode())
        window.close()
        app.exit(code)

    def tick():
        try:
            if time.monotonic()-started > 60:
                raise TimeoutError("Real audio did not reach the expected state within 60 seconds.")
            if stage[0] == 0:
                window.play()
                stage[0] = 1
            elif stage[0] == 1 and window.playback.state == "PLAYING":
                report["checks"].append("Piper synthesis and native audio entered PLAYING")
                window.add_document(new_document(id="qa-b", title="Bookmark B · editing test", voice=voice))
                window.editor().insertPlainText("Bonjour, café, résumé. Unicode works: 😀.\nThis second bookmark can be edited during speech.")
                assert window.playback.active_playback_bookmark_id == "qa-a"
                assert window.playback.audio.player.isPlaying()
                window.grab().save(str(output / "native-light.png"))
                report["checks"].append("Create and edit B while actual A output remains playing")
                window.playback.pause()
                assert window.playback.state == "PAUSED"
                window.playback.resume()
                stage[0] = 2
            elif stage[0] == 2 and window.playback.state == "PLAYING":
                report["checks"].append("Native audio pause and resume")
                previous_player = window.playback.audio.player
                window.play()
                assert not previous_player.isPlaying()
                assert window.playback.active_playback_bookmark_id == "qa-b"
                report["checks"].append("Play B synchronously stopped A output")
                stage[0] = 3
            elif stage[0] == 3 and window.playback.state == "PLAYING":
                report["checks"].append("B produced native PLAYING state")
                window.apply_theme("dark")
                QApplication.processEvents()
                window.grab().save(str(output / "native-dark.png"))
                window.playback.stop()
                assert window.playback.audio.player is None
                window.save_pool.waitForDone()
                window.session.save(window.snapshot())
                loaded = window.session.load()
                assert len(loaded["docs"]) == 2 and loaded["docs"][1]["text"].startswith("Bonjour")
                report["checks"].append("Stop and session recovery")
                finish(0)
        except Exception as exc:
            error(str(exc))
    timer = QTimer(window)
    timer.timeout.connect(tick)
    timer.start(100)
    return app.exec()


def verify_migration(app, settings, bridge, output):
    """Verify startup against the synthetic library from qa_legacy_migration."""
    from .native_window import MainWindow
    output = Path(output)
    window = MainWindow(settings, bridge)
    window.show()
    started = time.monotonic()
    finished = [False]
    def finish(error=None):
        if finished[0]:
            return
        finished[0] = True
        atomic_write(output/"migration-result.json", json.dumps({"passed":error is None, "error":error}).encode())
        window.close()
        app.exit(0 if error is None else 1)
    window.show_error = finish
    def check():
        if window.ready:
            try:
                assert window.documents["legacy-a"]["text"] == "Legacy text café 😀"
                assert window.documents["legacy-b"]["extraField"] == "preserved"
                assert window.selected_id == "legacy-b"
                finish()
            except Exception as error:
                finish(str(error) or "Migration assertion failed")
        elif time.monotonic()-started > 30:
            finish("Migration startup timed out")
    timer = QTimer(window)
    timer.timeout.connect(check)
    timer.start(100)
    return app.exec()
