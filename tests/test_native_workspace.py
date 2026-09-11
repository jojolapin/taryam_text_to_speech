import base64
import json
import time
import pytest
from PySide6.QtCore import QObject, Signal, QMimeData, QUrl, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtTest import QTest
from app.documents import new_document, SessionStore, decode_text, read_txt, validate_snapshot
from app.playback import PlaybackManager


@pytest.mark.parametrize("bitrate", [192, 256, 320])
def test_high_mp3_bitrate_is_honored_for_low_rate_voice(bitrate):
    import io
    pytest.importorskip("lameenc")
    from mutagen.mp3 import MP3
    from app.tts_engine import TTSEngine
    encoded = TTSEngine().encode_mp3(b"\x00\x00" * 22050, 22050, 1, bitrate)
    assert abs(MP3(io.BytesIO(encoded)).info.bitrate / 1000 - bitrate) < 2


@pytest.mark.parametrize("batch,fmt,bitrate", [(False,"mp3",256), (True,"mp3",192), (False,"wav",128)])
def test_visible_export_controls_dispatch_without_stopping_speech(window, monkeypatch, batch, fmt, bitrate):
    window.play()
    speaker = window.playback.active_playback_bookmark_id
    events = list(window.test_audio.events)
    calls = []
    method = "batch_export" if batch else "export_audio"
    monkeypatch.setattr(window.bridge, method, lambda *args: calls.append(args))
    panel = window.export_panel
    panel.format.setCurrentIndex(panel.format.findData(fmt))
    panel.bitrate.setCurrentIndex(panel.bitrate.findData(bitrate))
    panel.author.setText("QA author")
    (panel.batch if batch else panel.generate).click()
    assert len(calls) == 1
    assert calls[0][2] == fmt
    assert calls[0][5:7] == (bitrate, "QA author")
    assert window.playback.active_playback_bookmark_id == speaker
    assert window.test_audio.events == events
    assert panel.cancel.isEnabled() and not panel.generate.isEnabled()
    request = window.export_request
    window.bridge.exportProgress.emit(request, "encode", .7)
    assert panel.progress.value() == 70
    window.bridge.exportDone.emit(request, "QA output", 1., 1.)
    assert panel.generate.isEnabled() and not panel.cancel.isEnabled()
    assert "QA output" in panel.feedback.text()


def test_export_cancel_and_provider_specific_options(window, monkeypatch):
    panel = window.export_panel
    monkeypatch.setattr(window.bridge, "export_audio", lambda *args: window.bridge.exportError.emit(args[8], "cancelled"))
    panel.generate.click()
    assert window.export_request is None and panel.generate.isEnabled()
    assert panel.feedback.text() == "Export cancelled."
    panel.format.setCurrentIndex(panel.format.findData("wav"))
    assert not panel.bitrate.isEnabled()
    panel.format.setCurrentIndex(panel.format.findData("mp3"))
    assert panel.bitrate.isEnabled()
    window.add_document(new_document(provider="openai", voice="alloy"))
    assert not panel.bitrate.isEnabled()
    window.select_id("a")
    assert panel.bitrate.isEnabled()


class Audio(QObject):
    ended = Signal()
    failed = Signal(str)
    started = Signal()

    def __init__(self):
        super().__init__()
        self.events, self.live = [], False

    def play(self, data, mime, volume):
        assert not self.live, "Overlapping audio"
        self.live = True
        self.events.append(("play", data))
        self.started.emit()

    def stop(self):
        self.events.append(("stop",))
        self.live = False

    def pause(self):
        self.events.append(("pause",))

    def resume(self):
        self.started.emit()


@pytest.fixture
def window(tmp_path, monkeypatch, application):
    monkeypatch.setenv("TEXTSPEAK_DATA_DIR", str(tmp_path))
    from app.settings import Settings
    from app.bridge import Bridge
    from app.native_window import MainWindow
    settings = Settings()
    settings.set("last_voice", "test")
    bridge = Bridge(settings=settings)
    monkeypatch.setattr(bridge.engine, "discover_voices", lambda: [{"id":"test", "name":"Test Voice"}])
    requests = []
    monkeypatch.setattr(bridge, "synthesize", lambda text, voice, rate, volume, request, fmt: requests.append((request, text)))
    monkeypatch.setattr(bridge, "synthesize_openai", lambda *args: requests.append((args[-1], args[0])))
    a = new_document(id="a", title="Bookmark A", text="A long paragraph. " * 100, voice="test")
    w = MainWindow(settings, bridge, snapshot={"docs":[a], "activeId":"a"})
    old_audio = w.playback.audio
    audio = Audio()
    w.playback.audio = audio
    audio.started.connect(w.playback._started)
    audio.ended.connect(w.playback._ended)
    audio.failed.connect(w.playback._audio_failed)
    w.requests, w.test_audio = requests, audio
    w.show()
    application.processEvents()
    yield w
    w.close()
    application.processEvents()


def deliver(window, index=0, content=b"audio"):
    window.bridge.synthesizeReady.emit(window.requests[index][0], base64.b64encode(content).decode())


def test_mandatory_bookmark_workflow(window, tmp_path, application):
    w = window
    w.play()
    deliver(w)
    assert w.playback.state == "PLAYING"
    before = list(w.test_audio.events)
    b = w.add_document(new_document(id="b", title="Bookmark B", voice="test"))
    QApplication.clipboard().setText("Pasted text é 😀\n")
    QTest.keyClick(w.editor(), Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClicks(w.editor(), "Typed text")
    assert "Pasted text" in b["text"]
    assert "Typed text" in b["text"]
    w.documents["b"]["title"] = "Renamed B"
    w.update_item("b")
    w.select_id("a")
    w.select_id("b")
    assert w.playback.active_playback_bookmark_id == "a"
    assert w.test_audio.events == before
    assert "Bookmark A" in w.speaker_label.text()
    w.play()
    assert w.test_audio.events[-1] == ("stop",)
    assert w.playback.active_playback_bookmark_id == "b"
    # Late A results are ignored, only B can play.
    deliver(w, 1, b"stale A")
    assert not w.test_audio.live
    deliver(w, 2, b"B audio")
    assert w.test_audio.events[-1] == ("play", b"B audio")
    assert w.playback.state == "PLAYING"
    w.playback.pause()
    w.select_id("a")
    w.playback.resume()
    assert w.playback.active_playback_bookmark_id == "b"
    assert w.playback.state == "PLAYING"
    w.playback.stop()
    assert not w.test_audio.live


def test_drop_empty_other_bookmark_preserves_audio(window, tmp_path, application):
    w = window
    w.play()
    deliver(w)
    b = w.add_document(new_document(id="b", voice="test"))
    fixture = tmp_path / "accented résumé file.txt"
    fixture.write_bytes(b"\xef\xbb\xbf" + "Bonjour é 😀\r\nSecond line".encode())
    data = QMimeData()
    data.setUrls([QUrl.fromLocalFile(str(fixture))])
    w.editor().insertFromMimeData(data)
    limit = time.monotonic()+5
    while not b["text"] and time.monotonic()<limit:
        application.processEvents()
        QTest.qWait(10)
    assert b["text"] == "Bonjour é 😀\nSecond line"
    assert b["title"] == "accented résumé file"
    assert w.playback.active_playback_bookmark_id == "a"
    assert w.test_audio.live


def test_delete_non_speaking_bookmark(window):
    window.play()
    deliver(window)
    window.add_document(new_document(id="b", voice="test"))
    window.close_document()
    assert window.playback.active_playback_bookmark_id == "a"
    assert window.test_audio.live


def test_pause_during_loading_and_stale_stop(window):
    window.play()
    window.playback.pause()
    deliver(window)
    assert not window.test_audio.live
    window.playback.resume()
    assert window.test_audio.live
    window.playback.stop()
    deliver(window, 1)
    assert not window.test_audio.live


def test_native_editor_shortcuts_and_context_actions(window):
    editor = window.editor()
    editor.selectAll()
    QTest.keyClicks(editor, "Hello world")
    QTest.keyClick(editor, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(editor, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert QApplication.clipboard().text() == "Hello world"
    QTest.keyClick(editor, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier)
    assert editor.toPlainText() == ""
    QTest.keyClick(editor, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert editor.toPlainText() == "Hello world"
    editor.undo()
    assert editor.toPlainText() == ""
    editor.redo()
    assert editor.toPlainText() == "Hello world"
    editor.selectAll()
    menu = editor.createStandardContextMenu()
    actions = {a.text().split("\t")[0].replace("&", ""):a for a in menu.actions()}
    assert {"Undo", "Redo", "Cut", "Copy", "Paste", "Delete", "Select All"}.issubset(actions)
    actions["Copy"].trigger()
    actions["Cut"].trigger()
    assert editor.toPlainText() == ""
    actions["Paste"].trigger()
    assert editor.toPlainText() == "Hello world"
    menu.deleteLater()


def test_independent_undo_and_plain_text_drop(window):
    a_editor = window.editor()
    a_editor.selectAll()
    a_editor.insertPlainText("A changed")
    window.add_document(new_document(id="b"))
    mime = QMimeData()
    mime.setHtml("<b>Unwanted formatting</b>")
    mime.setText("Plain text é")
    window.editor().insertFromMimeData(mime)
    assert window.editor().toPlainText() == "Plain text é"
    window.select_id("a")
    a_editor.undo()
    assert a_editor.toPlainText().startswith("A long paragraph.")
    assert window.documents["b"]["text"] == "Plain text é"


def test_find_replace_unicode_single_undo(window):
    editor = window.editor()
    editor.setPlainText("café café\nCAFÉ 😀")
    dialog = window.find_dialog
    dialog.query.setText("café")
    dialog.replacement.setText("tea")
    dialog.replace_all()
    assert editor.toPlainText() == "tea tea\ntea 😀"
    editor.undo()
    assert editor.toPlainText() == "café café\nCAFÉ 😀"


def test_selection_unicode_offsets(window):
    window.editor().setPlainText("😀 Hello selected words.")
    cursor = window.editor().textCursor()
    cursor.setPosition(9)
    cursor.setPosition(17, QTextCursor.MoveMode.KeepAnchor)
    window.editor().setTextCursor(cursor)
    window.play()
    assert window.requests[0][1] == "selected"


@pytest.mark.parametrize("raw,expected", [(b"", ""), (b"\xef\xbb\xbfHello", "Hello"),
    ("é 😀".encode(), "é 😀"), ("é".encode("utf-16"), "é"),
    (b"\x93Hello\x94", "“Hello”"), (b"a\rb\r\nc\n", "a\nb\nc\n")])
def test_encodings(raw, expected):
    assert decode_text(raw) == expected


def test_unsupported_binary_and_large_files(tmp_path):
    binary = tmp_path/"image.exe"
    binary.write_bytes(b"MZ\x00")
    with pytest.raises(ValueError):
        read_txt(binary)
    with pytest.raises(ValueError):
        decode_text(b"MZ\x00")
    large = tmp_path/"large.txt"
    text = "Long text é 😀\n"*100000
    large.write_text(text, encoding="utf-8")
    assert read_txt(large) == text


def test_atomic_recovery_and_legacy_unknown_fields(tmp_path):
    store = SessionStore(tmp_path/"workspace.json")
    legacy = {"schema":1, "activeId":"a", "docs":[{"id":"a", "text":"Old text é", "bookmarks":[{"position":4}], "futureField":"keep"}]}
    store.save(legacy)
    newer = validate_snapshot(legacy)
    newer["docs"][0]["text"] = "New text"
    store.save(newer)
    store.path.write_text("broken")
    restored = store.load()
    assert restored["docs"][0]["text"] == "Old text é"
    assert restored["docs"][0]["futureField"] == "keep"
    assert restored["docs"][0]["bookmarks"] == [{"position":4}]
    assert store.recovered


def test_save_and_restart_preserves_unsaved_text(window, tmp_path):
    window.editor().insertPlainText("Unsaved edit é")
    snapshot = window.snapshot()
    window.save_pool.waitForDone()
    window.session.save(snapshot)
    restored = window.session.load()
    assert restored["docs"][0]["text"] == window.editor().toPlainText()
    assert restored["docs"][0]["dirty"]


def test_loading_controls_do_not_change_speaker_snapshot(window):
    window.document()["pronunciationRules"] = [{"from":"paragraph", "to":"passage"}]
    window.play()
    deliver(window)
    before = window.playback.document.copy()
    window.add_document(new_document(id="b", voice="test", volume=0.0, speed=1.8))
    window.volume.setValue(0)
    window.rate.setValue(1.2)
    assert window.playback.document == before
    assert window.playback.active_playback_bookmark_id == "a"


def test_audio_failure_stops_and_cancels(window, monkeypatch):
    messages = []
    window.playback.error.disconnect()
    window.playback.error.connect(messages.append)
    window.play()
    deliver(window)
    window.test_audio.failed.emit("Device unavailable")
    assert window.playback.state == "STOPPED"
    assert not window.test_audio.live
    deliver(window, 1)
    assert not window.test_audio.live
    assert "Device unavailable" in messages[0]


def test_rapid_play_stop_rejects_all_old_results(window):
    for i in range(30):
        window.play()
        window.playback.stop()
    for i in range(len(window.requests)):
        deliver(window, i)
    assert not any(event[0] == "play" for event in window.test_audio.events)
    assert window.playback.state == "STOPPED"


def test_modified_close_cancel_preserves_document(window, monkeypatch):
    window.editor().insertPlainText("Unsaved")
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Cancel)
    window.close_document()
    assert window.document()["id"] == "a"
    assert "Unsaved" in window.editor().toPlainText()


def test_import_modified_cancel_replace_append_new(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    original = window.document()["text"]
    choice = ["Cancel"]
    def execute(box):
        return 0
    def clicked(box):
        return next(b for b in box.buttons() if b.text().replace("&", "") == choice[0])
    monkeypatch.setattr(QMessageBox, "exec", execute)
    monkeypatch.setattr(QMessageBox, "clickedButton", clicked)
    window.finish_import([(str(tmp_path/"test.txt"), "Imported")], "a")
    assert window.document()["text"] == original
    choice[0] = "Append"
    window.finish_import([(str(tmp_path/"test.txt"), "Imported")], "a")
    assert window.document()["text"].endswith("Imported")
    choice[0] = "Open in New Bookmark"
    window.finish_import([(str(tmp_path/"new.txt"), "New")], "a")
    assert window.document()["text"] == "New"
    choice[0] = "Replace Current Text"
    window.finish_import([(str(tmp_path/"replace.txt"), "Replacement")], "a")
    assert window.documents["a"]["text"] == "Replacement"
    window.editors["a"].undo()
    assert window.documents["a"]["text"].endswith("Imported")


def test_save_failure_preserves_file_and_dirty_state(window, tmp_path, monkeypatch):
    from app import documents
    path = tmp_path/"precious.txt"
    path.write_text("Original", encoding="utf-8")
    window.document()["path"] = str(path)
    window.editor().insertPlainText("Changed")
    messages=[]
    monkeypatch.setattr(window, "show_error", messages.append)
    monkeypatch.setattr(documents.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("Disk error")))
    assert not window.save_document()
    assert path.read_text() == "Original"
    assert window.document()["dirty"]
    assert messages
    # Restore before fixture closes and saves recovery.
    monkeypatch.undo()


def test_large_editor_and_find_remain_usable(window, application):
    text = "A readable paragraph with accented café and Unicode 😀.\n" * 20000
    started = time.monotonic()
    window.editor().setPlainText(text)
    window.find_dialog.query.setText("Unicode")
    assert window.find_dialog.find()
    window.add_document(new_document(id="large-b"))
    window.select_id("a")
    assert window.editor().toPlainText() == text
    assert time.monotonic()-started < 10


def test_native_dialogs_construct(window):
    from app.native_dialogs import SettingsDialog, PronunciationDialog
    settings = SettingsDialog(window)
    pronunciation = PronunciationDialog(window)
    pronunciation.add_rule({"from":"DAIDALUS", "to":"Day-da-lus"})
    pronunciation.save()
    assert window.settings.get_json("pronunciation_rules", [])[0]["to"] == "Day-da-lus"
    settings.close()


def test_html_import_does_not_save_over_original(window, tmp_path):
    from app.file_import import read_document
    path = tmp_path/"page.html"
    original = "<h1>Café</h1><script>bad()</script><p>Hello &amp; world</p>"
    path.write_text(original, encoding="utf-8")
    text = read_document(path)
    assert "bad" not in text and "Hello & world" in text
    window.finish_import([(str(path), text)], "missing")
    assert window.document()["path"] == ""
    assert window.document()["dirty"]
    assert path.read_text(encoding="utf-8") == original


def test_empty_and_multiple_imports_create_distinct_documents(window, tmp_path):
    b = window.add_document(new_document(id="b"))
    window.finish_import([(str(tmp_path/"empty.txt"), ""), (str(tmp_path/"two.txt"), "Second")], "b")
    assert b["text"] == ""
    assert b["title"] == "empty"
    assert len(window.documents) == 3
    assert window.document()["text"] == "Second"


def test_per_document_format_overrides_legacy_global_preference(window):
    window.settings.set("markdown_mode", "on")
    assert window.bridge._normalize_for_tts("**Hello**", "document:off") == "**Hello**"
    window.settings.set("markdown_mode", "off")
    assert window.bridge._normalize_for_tts("**Hello**", "document:on") == "Hello"
