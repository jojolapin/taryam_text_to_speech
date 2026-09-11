"""Document lifecycle and file commands, composed into the native window.

The controller owns document/editor maps; the window presents them. Playback is
not touched by navigation or editing. Deleting the speaking document is the only
document lifecycle command that explicitly stops speech.
"""
import copy
from pathlib import Path
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QListWidgetItem, QFileDialog, QMessageBox, QInputDialog
from .documents import new_document, atomic_write, read_txt
from .editor import TextEditor
from .file_import import read_document, editable_source


class DocumentController:
    def __init__(self, window):
        self.window = window
        self.documents = {}
        self.editors = {}

    def add_document(self, doc=None, select=True):
        if doc is None:
            doc = new_document(voice=self.window.settings.get("last_voice", ""),
                speed=self.window.settings.get("last_speed", 1.0), volume=self.window.settings.get("last_volume", 1.0))
        doc = copy.deepcopy(doc)
        self.window.documents[doc["id"]] = doc
        editor = TextEditor()
        editor.setPlainText(doc["text"])
        editor.document().setModified(doc.get("dirty", False))
        self.window.apply_editor_preferences(editor)
        cursor = editor.textCursor()
        limit = editor.document().characterCount() - 1
        cursor.setPosition(min(limit, max(0, int(doc.get("selStart") or 0))))
        cursor.setPosition(min(limit, max(0, int(doc.get("selEnd") or 0))), QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        editor.verticalScrollBar().setValue(int(doc.get("scrollTop") or 0))
        editor.textChanged.connect(lambda d=doc: self.window.text_changed(d))
        editor.cursorPositionChanged.connect(self.window.schedule_save)
        editor.filesDropped.connect(lambda names, d=doc: self.window.import_files(names, d["id"]))
        editor.readSelection.connect(lambda: self.window.play("selection"))
        editor.readFromHere.connect(lambda: self.window.play("cursor"))
        self.window.editors[doc["id"]] = editor
        self.window.stack.addWidget(editor)
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, doc["id"])
        self.window.library.addItem(item)
        self.window.update_item(doc["id"])
        if select:
            self.window.filter.clear()
            self.window.select_id(doc["id"])
            editor.setFocus()
        self.window.schedule_save()
        return doc

    def select_id(self, doc_id):
        for index in range(self.window.library.count()):
            item = self.window.library.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == doc_id:
                self.window.library.setCurrentItem(item)
                return

    def select_document(self, item, previous=None):
        if not item:
            return
        self.window.selected_id = item.data(Qt.ItemDataRole.UserRole)
        doc = self.window.document()
        self.window.stack.setCurrentWidget(self.window.editor())
        blockers = [QSignalBlocker(widget) for widget in (self.window.provider, self.window.voice, self.window.rate, self.window.volume)]
        self.window.provider.setCurrentIndex(max(0, self.window.provider.findData(doc.get("provider", "piper"))))
        self.window.reload_voices()
        self.window.voice.setCurrentIndex(self.window.voice.findData(doc.get("voice")))
        self.window.rate.setValue(doc.get("speed") or 1.0)
        volume = doc.get("volume")
        self.window.volume.setValue(round(100 * (volume if volume is not None else 1.0)))
        del blockers
        self.window.export_panel.refresh_options()
        self.window.document_heading.setText(doc["title"])
        self.window.reflect_playback()
        self.window.schedule_save()

    def text_changed(self, doc):
        editor = self.window.editors[doc["id"]]
        doc["text"] = editor.toPlainText()
        doc["dirty"] = editor.document().isModified()
        doc["playbackPosition"] = min(doc.get("playbackPosition", 0), len(doc["text"]))
        editor.setExtraSelections([])
        self.window.update_item(doc["id"])
        self.window.schedule_save()

    def update_item(self, doc_id):
        doc = self.window.documents[doc_id]
        state = self.window.playback.state if self.window.playback.active_playback_bookmark_id == doc_id else ""
        label = doc["title"] + (" *" if doc.get("dirty") else "")
        if state:
            label += " — " + state.title()
        for index in range(self.window.library.count()):
            item = self.window.library.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == doc_id:
                item.setText(label)
                item.setToolTip(label + ("\n" + doc["path"] if doc.get("path") else ""))
                item.setData(Qt.ItemDataRole.AccessibleTextRole, label)
                break

    def filter_documents(self, query):
        for index in range(self.window.library.count()):
            item = self.window.library.item(index)
            item.setHidden(query.casefold() not in item.text().casefold())

    def rename_document(self):
        doc = self.window.document()
        if not doc:
            return
        title, ok = QInputDialog.getText(self.window, "Rename Bookmark", "Name:", text=doc["title"])
        if ok and title.strip():
            doc["title"] = title.strip()[:200]
            self.window.document_heading.setText(doc["title"])
            self.window.update_item(doc["id"])
            self.window.reflect_playback()
            self.window.schedule_save()

    def duplicate_document(self):
        if self.window.document():
            doc = new_document(**{**self.window.document(), "id": None, "path": "", "dirty": True,
                                   "title": self.window.document()["title"] + " (copy)"})
            self.window.add_document(doc)

    def move_document(self, direction):
        row = self.window.library.currentRow()
        target = max(0, min(self.window.library.count()-1, row + direction))
        if row >= 0 and target != row:
            with QSignalBlocker(self.window.library):
                item = self.window.library.takeItem(row)
                self.window.library.insertItem(target, item)
                self.window.library.setCurrentItem(item)
            self.window.schedule_save()

    def next_document(self, direction):
        if self.window.library.count():
            self.window.library.setCurrentRow((self.window.library.currentRow() + direction) % self.window.library.count())

    def protect_document(self, doc):
        if not doc.get("dirty"):
            return True
        answer = QMessageBox.warning(self.window, "Unsaved text", f'Save changes to “{doc["title"]}” before closing?',
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Save:
            return self.window.save_document(doc_id=doc["id"])
        return answer == QMessageBox.StandardButton.Discard

    def close_document(self):
        doc = self.window.document()
        if not doc or not self.window.protect_document(doc):
            return
        doc_id = doc["id"]
        if self.window.playback.active_playback_bookmark_id == doc_id:
            self.window.playback.stop()
        row = self.window.library.currentRow()
        with QSignalBlocker(self.window.library):
            self.window.library.takeItem(row)
        editor = self.window.editors.pop(doc_id)
        self.window.stack.removeWidget(editor)
        editor.deleteLater()
        del self.window.documents[doc_id]
        self.window.selected_id = None
        if not self.window.documents:
            self.window.add_document()
        else:
            self.window.library.setCurrentRow(max(0, row - 1))
            self.window.select_document(self.window.library.currentItem())
        self.window.schedule_save()

    def snapshot(self):
        docs = []
        for index in range(self.window.library.count()):
            doc = self.window.documents[self.window.library.item(index).data(Qt.ItemDataRole.UserRole)]
            editor = self.window.editors[doc["id"]]
            cursor = editor.textCursor()
            doc.update(cursor=cursor.position(), selStart=cursor.anchor(), selEnd=cursor.position(),
                       scrollTop=editor.verticalScrollBar().value())
            docs.append(copy.deepcopy(doc))
        return dict(schema=2, activeId=self.window.selected_id, docs=docs)

    def open_files(self):
        names, _ = QFileDialog.getOpenFileNames(self.window, "Open Document", "", "Documents (*.txt *.md *.markdown *.pdf *.html *.htm);;Text files (*.txt)")
        if names:
            self.window.import_files(names, self.window.selected_id)

    def import_files(self, names, target_id):
        # Capture destination before async I/O; navigation must never redirect a drop.
        self.window.statusBar().showMessage("Opening text…")
        self.window.run_job(lambda: [(str(Path(name).resolve()), read_document(name)) for name in names],
                     lambda results: self.window.finish_import(results, target_id))

    def finish_import(self, results, target_id):
        for index, (path, text) in enumerate(results):
            target = self.window.documents.get(target_id) if index == 0 else None
            choice = "replace" if target and not target["text"] else "new"
            if target and target["text"]:
                box = QMessageBox(self.window)
                box.setWindowTitle("Open Text File")
                box.setText(f'“{target["title"]}” already contains text. How should {Path(path).name} be opened?')
                replace = box.addButton("Replace Current Text", QMessageBox.ButtonRole.DestructiveRole)
                append = box.addButton("Append", QMessageBox.ButtonRole.ActionRole)
                fresh = box.addButton("Open in New Bookmark", QMessageBox.ButtonRole.AcceptRole)
                box.addButton(QMessageBox.StandardButton.Cancel)
                box.setDefaultButton(fresh)
                box.exec()
                choice = {replace: "replace", append: "append", fresh: "new"}.get(box.clickedButton(), "cancel")
            if choice == "cancel":
                continue
            if choice == "new":
                target = self.window.add_document(new_document(text=text, title=Path(path).stem,
                    path=path if editable_source(path) else "", dirty=not editable_source(path),
                    voice=self.window.settings.get("last_voice", "")))
            else:
                editor = self.window.editors[target["id"]]
                cursor = QTextCursor(editor.document())
                cursor.beginEditBlock()
                if choice == "append":
                    cursor.movePosition(QTextCursor.MoveOperation.End)
                    cursor.insertText(("\n" if target["text"] else "") + text)
                else:
                    cursor.select(QTextCursor.SelectionType.Document)
                    cursor.insertText(text)
                    target.update(title=Path(path).stem, path=path if editable_source(path) else "")
                    editor.document().setModified(not editable_source(path))
                    target["dirty"] = not editable_source(path)
                cursor.endEditBlock()
                self.window.update_item(target["id"])
                if target["id"] == self.window.selected_id:
                    self.window.document_heading.setText(target["title"])
            self.window.settings.add_recent_file(path)
        self.window.schedule_save()
        self.window.statusBar().showMessage("Text loaded", 4000)

    def save_document(self, save_as=False, doc_id=None):
        doc = self.window.documents.get(doc_id or self.window.selected_id)
        if not doc:
            return False
        path = doc.get("path", "")
        if save_as or not path:
            path, _ = QFileDialog.getSaveFileName(self.window, "Save Text", path or doc["title"] + ".txt", "Text files (*.txt)")
            if not path:
                return False
        try:
            atomic_write(Path(path), doc["text"].encode("utf-8"))
        except (OSError, UnicodeError) as error:
            self.window.show_error("Could not save file. " + str(error))
            return False
        doc.update(path=path, dirty=False)
        self.window.editors[doc["id"]].document().setModified(False)
        self.window.update_item(doc["id"])
        self.window.settings.add_recent_file(path)
        self.window.schedule_save()
        self.window.statusBar().showMessage("Text saved", 4000)
        return True

    def populate_recent(self):
        self.window.recent_menu.clear()
        for path in self.window.settings.get_json("recent_files", []):
            self.window.action(self.window.recent_menu, path, lambda p=path: self.window.import_files([p], self.window.selected_id))
