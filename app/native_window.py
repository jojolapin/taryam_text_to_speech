"""Native document workspace. Synthesis and document storage remain separate."""
from __future__ import annotations

import copy
import json
import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QThreadPool, QSignalBlocker
from PySide6.QtGui import QAction, QKeySequence, QFont, QTextCursor, QColor, QPalette, QIcon
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QSplitter, QListWidget, QListWidgetItem, QStackedWidget,
    QLineEdit, QPushButton, QLabel, QComboBox, QDoubleSpinBox, QSpinBox,
    QFileDialog, QMessageBox, QInputDialog, QFontDialog, QTextEdit, QToolBar,
    QAbstractItemView, QMenu, QSystemTrayIcon)

from . import APP_NAME, APP_AUTHOR, APP_YEAR, paths
from .documents import new_document, validate_snapshot, SessionStore
from .editor import TextEditor, FindDialog
from .playback import PlaybackManager
from .workers import Job
from .document_controller import DocumentController

log = logging.getLogger("textspeak.window")


class MainWindow(QMainWindow):
    def __init__(self, settings, bridge, snapshot=None):
        super().__init__()
        self.settings, self.bridge = settings, bridge
        self.document_controller = DocumentController(self)
        self.documents = self.document_controller.documents
        self.editors = self.document_controller.editors
        self.selected_id = None
        self.ready = False
        self.jobs = set()
        self.session = SessionStore(paths.user_data_dir() / "workspace-v2.json")
        self.save_pool = QThreadPool(self)
        self.save_pool.setMaxThreadCount(1)
        self.playback = PlaybackManager(bridge, parent=self)
        self.autosave = QTimer(self)
        self.autosave.setSingleShot(True)
        self.autosave.setInterval(600)
        self.autosave.timeout.connect(self.save_session)
        self.sleep_timer = QTimer(self)
        self.sleep_timer.setSingleShot(True)
        self.sleep_timer.timeout.connect(self.playback.stop)
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(str(paths.resources_dir() / "icon.ico")))
        self.resize(1160, 780)
        self.setMinimumSize(960, 640)
        self._build_ui()
        self._menus()
        self._tray()
        self.playback.changed.connect(self.reflect_playback)
        self.playback.position.connect(self.remember_position)
        self.playback.passage.connect(self.highlight_passage)
        self.playback.error.connect(self.show_error)
        self.bridge.voicesChanged.connect(self.reload_voices)
        self.bridge.stopRequested.connect(self.playback.stop)
        self.bridge.readClipboardRequested.connect(self.read_clipboard)
        self.bridge.quitRequested.connect(self.close)
        self.bridge.exportDone.connect(self.export_done)
        self.bridge.exportError.connect(self.export_error)
        self.bridge.exportProgress.connect(self.export_progress)
        self.export_request = None
        self.smart_requests = {}
        self.bridge.smartToolReady.connect(self.smart_done)
        self.bridge.smartToolError.connect(self.smart_error)
        self.apply_theme(self.settings.get("theme", "system"))
        geometry, state = settings.load_window_geometry()
        if geometry:
            self.restoreGeometry(geometry)
        if state:
            self.restoreState(state)
        self.reload_voices()
        self.centralWidget().setEnabled(False)
        self.menuBar().setEnabled(False)
        if snapshot is not None:
            self.load_snapshot(snapshot)
        else:
            QTimer.singleShot(0, self.restore_session)

    def _build_ui(self):
        workspace = QWidget()
        workspace.setObjectName("workspace")
        page = QVBoxLayout(workspace)
        page.setContentsMargins(18, 8, 18, 8)
        page.setSpacing(14)
        header = QWidget()
        header.setObjectName("brandHeader")
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(20, 14, 20, 14)
        logo = QLabel()
        logo.setPixmap(self.windowIcon().pixmap(40, 40))
        header_row.addWidget(logo)
        brand = QVBoxLayout()
        title = QLabel(f"{APP_NAME}™")
        title.setObjectName("brandTitle")
        brand.addWidget(title)
        subtitle = QLabel(f"by {APP_AUTHOR} · Read, listen, and create audio.")
        subtitle.setObjectName("mutedLabel")
        brand.addWidget(subtitle)
        header_row.addLayout(brand)
        header_row.addStretch()
        settings_button = QPushButton("Voices && settings")
        settings_button.clicked.connect(self.show_settings)
        header_row.addWidget(settings_button)
        page.addWidget(header)
        splitter = QSplitter()
        splitter.setHandleWidth(12)
        page.addWidget(splitter, 1)
        self.setCentralWidget(workspace)
        left = QWidget()
        left.setObjectName("libraryCard")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(14, 16, 14, 14)
        heading = QLabel("BOOKMARKS")
        heading.setObjectName("sectionLabel")
        left_layout.addWidget(heading)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Find a bookmark…")
        self.filter.setAccessibleName("Filter bookmarks")
        self.filter.textChanged.connect(self.filter_documents)
        left_layout.addWidget(self.filter)
        self.library = QListWidget()
        self.library.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.library.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.library.setAccessibleName("Bookmarks")
        self.library.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.library.currentItemChanged.connect(self.select_document)
        self.library.itemDoubleClicked.connect(lambda _: self.rename_document())
        self.library.model().rowsMoved.connect(lambda *args: self.schedule_save())
        left_layout.addWidget(self.library)
        add = QPushButton("+ Add Bookmark")
        add.setObjectName("primaryButton")
        add.clicked.connect(lambda: self.add_document())
        left_layout.addWidget(add)
        splitter.addWidget(left)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)
        editor_pane = QWidget()
        editor_pane.setObjectName("editorPane")
        editor_layout = QVBoxLayout(editor_pane)
        editor_layout.setContentsMargins(18, 14, 18, 12)
        editor_layout.setSpacing(10)
        right_layout.addWidget(editor_pane, 1)
        self.document_heading = QLabel("Text Speak Pro")
        self.document_heading.setObjectName("documentTitle")
        editor_layout.addWidget(self.document_heading)
        controls = QHBoxLayout()
        self.provider = QComboBox()
        self.provider.addItem("Piper · Offline", "piper")
        self.provider.addItem("OpenAI · Online", "openai")
        self.provider.setAccessibleName("Speech provider")
        self.voice = QComboBox()
        self.voice.setMinimumContentsLength(14)
        self.voice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.voice.setAccessibleName("Voice")
        self.rate = QDoubleSpinBox()
        self.rate.setRange(.5, 2.0)
        self.rate.setSingleStep(.05)
        self.rate.setSuffix(" ×")
        self.rate.setAccessibleName("Reading speed")
        self.volume = QSpinBox()
        self.volume.setRange(0, 100)
        self.volume.setSuffix(" %")
        self.volume.setAccessibleName("Volume")
        controls.addWidget(self.provider)
        controls.addWidget(self.voice, 1)
        controls.addWidget(QLabel("Speed"))
        controls.addWidget(self.rate)
        controls.addWidget(QLabel("Volume"))
        controls.addWidget(self.volume)
        editor_layout.addLayout(controls)
        self.provider.currentIndexChanged.connect(self.provider_changed)
        self.voice.currentIndexChanged.connect(self.controls_changed)
        self.rate.valueChanged.connect(self.controls_changed)
        self.volume.valueChanged.connect(self.controls_changed)
        self.stack = QStackedWidget()
        editor_layout.addWidget(self.stack, 1)
        self.transport_layout = QVBoxLayout()
        editor_layout.addLayout(self.transport_layout)
        self.speaker_label = QLabel("Stopped")
        self.speaker_label.setObjectName("playbackStatus")
        self.speaker_label.setAccessibleName("Playback status and speaking bookmark")
        self.speaker_label.setWordWrap(True)
        editor_layout.addWidget(self.speaker_label)
        from .native_export import ExportPanel
        self.export_panel = ExportPanel(self)
        right_layout.addWidget(self.export_panel)
        self.provider.currentIndexChanged.connect(self.export_panel.refresh_options)
        splitter.addWidget(right)
        splitter.setSizes([250, 910])
        splitter.setStretchFactor(1, 1)
        self.find_dialog = FindDialog(self.editor, self)
        self.statusBar().showMessage("Opening your bookmark library…")
        copyright_label = QLabel(f"© {APP_YEAR} {APP_AUTHOR}")
        copyright_label.setObjectName("mutedLabel")
        self.statusBar().addPermanentWidget(copyright_label)

    def action(self, menu, label, callback, shortcut=None):
        action = QAction(label, self)
        action.triggered.connect(lambda checked=False: callback())
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        menu.addAction(action)
        return action

    def _menus(self):
        from .native_menus import build_menus
        build_menus(self)

    def _tray(self):
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self.windowIcon(), self)
            self.tray.setToolTip(APP_NAME)
            menu = QMenu(self)
            self.action(menu, "Show", self.showNormal)
            self.action(menu, "Read Clipboard", self.read_clipboard)
            self.action(menu, "Stop", self.playback.stop)
            self.action(menu, "Quit", self.close)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(lambda reason: self.showNormal() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
            self.tray.show()

    def restore_session(self):
        try:
            snapshot = self.session.load()
            if snapshot is not None:
                self.load_snapshot(snapshot)
                if self.session.recovered:
                    QMessageBox.information(self, "Workspace recovered", "The most recent workspace was damaged. Your recovery backup was loaded; the original files are preserved.")
                return
            if (paths.user_data_dir() / "webstorage" / "IndexedDB").exists():
                from .legacy_migration import LegacyMigration
                self.migration = LegacyMigration(self)
                self.migration.finished.connect(self.load_snapshot)
                self.migration.failed.connect(self.show_error)
                self.migration.start()
            else:
                self.load_snapshot(None)
        except Exception as error:
            log.exception("Workspace load failed")
            self.show_error(str(error))

    def load_snapshot(self, snapshot):
        try:
            if snapshot is None:
                text = self.settings.get("saved_text", "") if self.settings.get("save_text", False) else ""
                snapshot = dict(docs=[new_document(text=text, dirty=bool(text),
                    bookmarks=self.settings.get_json("bookmarks", []),
                    playbackPosition=self.settings.get("saved_position", 0))])
            checked = validate_snapshot(snapshot)
            for doc in checked["docs"]:
                self.add_document(doc, select=False)
            self.ready = True
            self.centralWidget().setEnabled(True)
            self.menuBar().setEnabled(True)
            self.select_id(checked["activeId"])
            self.save_session()
            self.statusBar().showMessage("Ready · Bookmarks are recovered automatically between sessions")
            self.reflect_playback()
        except Exception as error:
            self.ready = False
            self.show_error("Could not restore bookmarks. Original data was preserved. " + str(error))

    def editor(self):
        return self.editors.get(self.selected_id)

    def document(self):
        return self.documents.get(self.selected_id)

    def add_document(self, doc=None, select=True):
        return self.document_controller.add_document(doc=doc, select=select)

    def select_id(self, doc_id):
        return self.document_controller.select_id(doc_id=doc_id)

    def select_document(self, item, previous=None):
        return self.document_controller.select_document(item=item, previous=previous)

    def text_changed(self, doc):
        return self.document_controller.text_changed(doc=doc)

    def update_item(self, doc_id):
        return self.document_controller.update_item(doc_id=doc_id)

    def filter_documents(self, query):
        return self.document_controller.filter_documents(query=query)

    def rename_document(self):
        return self.document_controller.rename_document()

    def duplicate_document(self):
        return self.document_controller.duplicate_document()

    def move_document(self, direction):
        return self.document_controller.move_document(direction=direction)

    def next_document(self, direction):
        return self.document_controller.next_document(direction=direction)

    def protect_document(self, doc):
        return self.document_controller.protect_document(doc=doc)

    def close_document(self):
        return self.document_controller.close_document()

    def snapshot(self):
        return self.document_controller.snapshot()

    def schedule_save(self):
        if self.ready:
            self.autosave.start()

    def run_job(self, function, done, pool=None):
        job = Job(function)
        self.jobs.add(job)
        job.signals.done.connect(done)
        job.signals.failed.connect(self.show_error)
        job.signals.done.connect(lambda _: self.jobs.discard(job))
        job.signals.failed.connect(lambda _: self.jobs.discard(job))
        (pool or QThreadPool.globalInstance()).start(job)

    def save_session(self):
        if self.ready:
            snapshot = self.snapshot()
            self.run_job(lambda: self.session.save(snapshot), lambda _: None, self.save_pool)

    def open_files(self):
        return self.document_controller.open_files()

    def import_files(self, names, target_id):
        return self.document_controller.import_files(names=names, target_id=target_id)

    def finish_import(self, results, target_id):
        return self.document_controller.finish_import(results=results, target_id=target_id)

    def save_document(self, save_as=False, doc_id=None):
        return self.document_controller.save_document(save_as=save_as, doc_id=doc_id)

    def populate_recent(self):
        return self.document_controller.populate_recent()

    def reload_voices(self):
        current = self.voice.currentData()
        with QSignalBlocker(self.voice):
            self.voice.clear()
            if self.provider.currentData() == "openai":
                from .openai_provider import OPENAI_VOICES
                for voice in OPENAI_VOICES:
                    self.voice.addItem(voice.title(), voice)
            else:
                for voice in self.bridge.engine.discover_voices():
                    self.voice.addItem(voice["name"], voice["id"])
            index = self.voice.findData(current)
            if index >= 0:
                self.voice.setCurrentIndex(index)

    def provider_changed(self):
        self.reload_voices()
        self.controls_changed()

    def controls_changed(self):
        doc = self.document()
        if not doc:
            return
        doc.update(provider=self.provider.currentData(), voice=self.voice.currentData() or "",
                   speed=self.rate.value(), volume=self.volume.value()/100)
        self.settings.set("last_speed", doc["speed"])
        self.settings.set("last_volume", doc["volume"])
        if doc["provider"] == "piper":
            self.settings.set("last_voice", doc["voice"])
        # Changes apply to the next explicit Play, never restart another bookmark.
        self.schedule_save()

    def playback_document(self):
        self.controls_changed()
        doc = copy.deepcopy(self.document())
        doc["effectiveRules"] = self.settings.get_json("pronunciation_rules", []) + doc.get("pronunciationRules", [])
        doc["model"] = self.settings.get("openai_model", "gpt-4o-mini-tts")
        if not doc.get("speakingInstructions"):
            from .speaking_styles import instruction_for
            doc["speakingInstructions"] = instruction_for(doc.get("speakingStyle", "neutral"))
        return doc

    def play(self, mode="normal"):
        if not self.document():
            return
        doc = self.playback_document()
        if doc.get("provider") == "openai" and not self.settings.get("ai_disclosure_ack", False):
            answer = QMessageBox.question(self, "Online AI Voice", "OpenAI voices send the selected text to your configured OpenAI provider and may incur API charges. Continue?")
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.settings.set("ai_disclosure_ack", True)
        cursor = self.editor().textCursor()
        # QTextCursor uses UTF-16 offsets; Python synthesis uses Unicode codepoints.
        text = doc["text"]
        to_python = lambda pos: len(text.encode("utf-16-le")[:pos*2].decode("utf-16-le", errors="ignore"))
        start, end = 0, None
        if mode == "cursor":
            start = to_python(cursor.position())
        elif mode == "position":
            start = doc.get("playbackPosition", 0)
        elif cursor.hasSelection():
            start, end = to_python(cursor.selectionStart()), to_python(cursor.selectionEnd())
        elif mode == "selection":
            return
        self.playback.play(doc, start, end)

    def toggle_playback(self):
        if self.playback.state == "PAUSED":
            self.playback.resume()
        elif self.playback.state in {"PLAYING", "LOADING"}:
            self.playback.pause()
        else:
            self.play()

    def reflect_playback(self):
        state = self.playback.state
        speaker = self.documents.get(self.playback.active_playback_bookmark_id)
        self.speaker_label.setText(f'{state.title()} · {speaker["title"]}' if speaker else "Stopped")
        self.pause_action.setEnabled(state in {"PLAYING", "LOADING"})
        self.resume_action.setEnabled(state == "PAUSED")
        self.stop_action.setEnabled(state != "STOPPED")
        for doc_id in self.documents:
            self.update_item(doc_id)
            if state == "STOPPED":
                self.editors[doc_id].setExtraSelections([])

    def remember_position(self, doc_id, position):
        if doc_id in self.documents:
            self.documents[doc_id]["playbackPosition"] = position
            self.schedule_save()

    def highlight_passage(self, doc_id, start, end):
        if doc_id not in self.editors:
            return
        doc = self.documents[doc_id]
        if doc["text"] != self.playback.document["text"]:
            return  # Do not highlight offsets into text edited after playback began.
        editor = self.editors[doc_id]
        selection = QTextEdit.ExtraSelection()
        selection.cursor = QTextCursor(editor.document())
        selection.cursor.setPosition(len(doc["text"][:start].encode("utf-16-le"))//2)
        selection.cursor.setPosition(len(doc["text"][:end].encode("utf-16-le"))//2, QTextCursor.MoveMode.KeepAnchor)
        selection.format.setBackground(QColor("#d4e9fa"))
        selection.format.setForeground(QColor("#152c40"))
        editor.setExtraSelections([selection])

    def add_marker(self):
        doc = self.document()
        if doc:
            pos = self.editor().textCursor().position()
            doc.setdefault("bookmarks", []).append(dict(position=pos, preview=self.editor().textCursor().block().text()[:80]))
            self.schedule_save()

    def populate_markers(self):
        self.markers_menu.clear()
        for marker in (self.document() or {}).get("bookmarks", []):
            self.action(self.markers_menu, marker.get("preview") or f'Position {marker.get("position", 0)}',
                        lambda m=marker: self.goto_marker(m))

    def goto_marker(self, marker):
        cursor = self.editor().textCursor()
        cursor.setPosition(min(self.editor().document().characterCount()-1, max(0, marker.get("position", 0))))
        self.editor().setTextCursor(cursor)
        self.editor().setFocus()

    def set_timer(self, minutes):
        self.sleep_timer.stop()
        if minutes:
            self.sleep_timer.start(minutes * 60000)
        self.statusBar().showMessage(f"Reading timer: {minutes} minutes" if minutes else "Reading timer off", 4000)

    def read_clipboard(self):
        text = QApplication.clipboard().text()
        if text:
            self.add_document(new_document(text=text, title="Clipboard", dirty=True,
                voice=self.settings.get("last_voice", "")))
            self.play()

    def show_find(self):
        self.find_dialog.show()
        self.find_dialog.raise_()
        self.find_dialog.query.setFocus()

    def edit_command(self, name):
        editor = self.editor()
        if not editor:
            return
        if name == "delete_selection":
            editor.textCursor().removeSelectedText()
        else:
            getattr(editor, name)()

    def update_edit_menu(self):
        editor = self.editor()
        if not editor:
            return
        for name in ("cut", "copy", "delete_selection"):
            self.edit_actions[name].setEnabled(editor.textCursor().hasSelection())
        self.edit_actions["undo"].setEnabled(editor.document().isUndoAvailable())
        self.edit_actions["redo"].setEnabled(editor.document().isRedoAvailable())
        self.edit_actions["paste"].setEnabled(QApplication.clipboard().mimeData().hasText())

    def apply_editor_preferences(self, editor):
        font = QFont(self.settings.get("editor_font", "Segoe UI"), self.settings.get("editor_size", 12))
        editor.setFont(font)
        editor.setLineWrapMode(TextEditor.LineWrapMode.WidgetWidth if self.settings.get("editor_wrap", True) else TextEditor.LineWrapMode.NoWrap)

    def choose_font(self):
        if not self.editor():
            return
        ok, font = QFontDialog.getFont(self.editor().font(), self)
        if ok:
            self.settings.set("editor_font", font.family())
            self.settings.set("editor_size", font.pointSize())
            for editor in self.editors.values():
                self.apply_editor_preferences(editor)

    def zoom(self, delta):
        size = max(8, min(48, self.settings.get("editor_size", 12) + delta))
        self.settings.set("editor_size", size)
        for editor in self.editors.values():
            self.apply_editor_preferences(editor)

    def toggle_wrap(self):
        self.settings.set("editor_wrap", self.wrap_action.isChecked())
        for editor in self.editors.values():
            self.apply_editor_preferences(editor)

    def apply_theme(self, theme):
        from .native_theme import apply_theme
        apply_theme(self, theme)

    def show_settings(self):
        from .native_dialogs import SettingsDialog
        SettingsDialog(self).exec()

    def show_pronunciation(self):
        from .native_dialogs import PronunciationDialog
        PronunciationDialog(self).exec()

    def start_smart_tool(self, request, text, task, language, title):
        self.smart_requests[request] = title
        self.bridge.smart_tool(text, task, language, request)
        self.statusBar().showMessage("Running online smart tool…")

    def smart_done(self, request, text):
        title = self.smart_requests.pop(request, None)
        if title:
            self.add_document(new_document(title=title, text=text, dirty=True,
                voice=self.settings.get("last_voice", "")))

    def smart_error(self, request, message):
        if self.smart_requests.pop(request, None):
            self.show_error(message)

    def export_audio(self, batch=False):
        if not self.document() or self.export_request:
            return
        doc = self.playback_document()
        if batch and doc.get("provider") == "openai":
            self.show_error("Paragraph batch export is available with offline Piper voices. Use Export Speech to Audio for OpenAI.")
            return
        if not doc["voice"] or not doc["text"].strip():
            self.show_error("Choose a voice and enter text before exporting.")
            return
        fmt = self.export_panel.format.currentData()
        bitrate = self.export_panel.bitrate.currentData()
        author = self.export_panel.author.text()
        self.settings.set("id3_author", author)
        if doc.get("provider") == "openai" and not self.settings.get("ai_disclosure_ack", False):
            if QMessageBox.question(self, "Online Audio Export", "Send this bookmark's text to your configured OpenAI provider to generate audio? API charges may apply.") != QMessageBox.StandardButton.Yes:
                return
            self.settings.set("ai_disclosure_ack", True)
        import uuid
        request = "export-" + uuid.uuid4().hex
        self.export_request = request
        self.export_panel.set_busy(True)
        self.bridge.set_pronunciation_rules(json.dumps(doc["effectiveRules"]))
        if batch:
            import re
            paragraphs = [p for p in re.split(r"\n\s*\n", doc["text"]) if p.strip()]
            self.bridge.batch_export(json.dumps(paragraphs), doc["voice"], fmt, 1/doc["speed"],
                doc["volume"], bitrate, author, doc["title"], request, "document:" + doc.get("markdownMode", "auto"))
        elif doc.get("provider") == "openai":
            self.bridge.export_openai(doc["text"], doc["voice"], doc["model"], doc["speed"],
                doc.get("speakingInstructions", ""), fmt, "", doc["title"],
                "document:" + doc.get("markdownMode", "auto"), doc["id"], request)
        else:
            self.bridge.export_audio(doc["text"], doc["voice"], fmt, 1/doc["speed"], doc["volume"],
                bitrate, author, doc["title"], request, "document:" + doc.get("markdownMode", "auto"))

    def cancel_audio_export(self):
        if self.export_request:
            self.bridge.cancel(self.export_request)

    def export_progress(self, request, stage, ratio):
        if request == self.export_request:
            self.statusBar().showMessage(f"Export: {stage} · {ratio:.0%}")
            self.export_panel.feedback.setText(f"Generating audio · {stage} · {ratio:.0%}")
            self.export_panel.progress.setValue(round(ratio * 100))

    def export_done(self, request, path, audio_seconds, synth_seconds):
        if request == self.export_request:
            self.export_request = None
            self.export_panel.set_busy(False)
            self.export_panel.feedback.setText("Saved: " + path)
            self.statusBar().showMessage("Audio exported to " + path)

    def export_error(self, request, message):
        if request == self.export_request:
            self.export_request = None
            self.export_panel.set_busy(False)
            self.export_panel.feedback.setText("Export cancelled." if message == "cancelled" else "Export failed: " + message)
            if message != "cancelled":
                self.show_error(message)

    def show_error(self, message):
        log.error("Application operation failed: %s", message)
        QMessageBox.warning(self, APP_NAME, message)

    def closeEvent(self, event):
        if self.ready:
            # Retain all unsaved documents in recovery, without forcing file exports.
            self.autosave.stop()
            self.save_pool.waitForDone()
            try:
                self.session.save(self.snapshot())
            except Exception as error:
                self.show_error("Your workspace could not be saved. The application will stay open. " + str(error))
                event.ignore()
                return
        self.playback.stop()
        self.cancel_audio_export()
        for request in list(self.bridge._cancels):
            self.bridge.cancel(request)
        self.settings.save_window_geometry(bytes(self.saveGeometry()), bytes(self.saveState()))
        if self.tray:
            self.tray.hide()
        event.accept()
