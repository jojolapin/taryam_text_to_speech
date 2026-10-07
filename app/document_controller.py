"""Document lifecycle and file commands, composed into the native window.

The controller owns document/editor maps; the window presents them. Playback is
not touched by navigation or editing. Deleting the speaking document is the only
document lifecycle command that explicitly stops speech.
"""
import copy
import re
from pathlib import Path
from PySide6.QtCore import QEvent, QSize, Qt, QSignalBlocker
from PySide6.QtGui import QFont, QFontMetrics, QTextCursor
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QInputDialog, QLabel, QListWidgetItem, QMessageBox,
    QSizePolicy, QToolButton, QWidget,
)
from . import i18n
from .documents import new_document, atomic_write, read_txt
from .editor import TextEditor
from .file_import import read_document, editable_source


def bookmark_display(title: str) -> str:
    """Title text for the list, without Markdown emphasis marks."""
    value = (title or "").strip()
    value = re.sub(r"^#{1,6}\s+", "", value)
    value = value.replace("**", "").replace("__", "").replace("`", "")
    value = re.sub(r"\s+", " ", value).strip()
    return value or (title or "").strip() or "Untitled"


def fit_bookmark_text(text: str, metrics: QFontMetrics, width: int) -> str:
    """One line, cut with an ellipsis so the name cannot paint over the next row."""
    if not text or width < 48:
        return text
    return metrics.elidedText(text, Qt.TextElideMode.ElideRight, width)


_ROW_HEIGHT = 36


class BookmarkRow(QWidget):
    """Title plus a close button for one library entry."""

    def __init__(self, on_delete, on_menu, on_select, on_rename):
        super().__init__()
        self.setObjectName("bookmarkRow")
        self.setFixedHeight(_ROW_HEIGHT)
        self._full = ""
        self._display = ""
        self._on_select = on_select
        self._on_rename = on_rename
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 4, 0)
        layout.setSpacing(8)
        self.title = QLabel()
        self.title.setObjectName("bookmarkTitle")
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setWordWrap(False)
        self.title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.title.setMinimumWidth(0)
        font = QFont("Segoe UI")
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.DemiBold)
        self.title.setFont(font)
        layout.addWidget(self.title, 1)
        self.status = QLabel()
        self.status.setObjectName("bookmarkStatus")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setFixedWidth(14)
        self.status.hide()
        layout.addWidget(self.status, 0, Qt.AlignmentFlag.AlignVCenter)
        self.close = QToolButton()
        self.close.setObjectName("bookmarkClose")
        self.close.setText("×")
        self.close.setAutoRaise(True)
        self.close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close.setFixedSize(22, 22)
        self.close.clicked.connect(lambda _checked=False: on_delete())
        layout.addWidget(self.close, 0, Qt.AlignmentFlag.AlignVCenter)
        self.title.installEventFilter(self)
        for widget in (self, self.title, self.close):
            widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            widget.customContextMenuRequested.connect(lambda pos, source=widget: on_menu(source, pos))

    def eventFilter(self, watched, event):
        if watched is self.title and event.type() == QEvent.Type.MouseButtonDblClick:
            self._on_rename()
            return True
        if watched is self.title and event.type() == QEvent.Type.MouseButtonPress:
            self._on_select()
        return super().eventFilter(watched, event)

    def set_title(self, text: str) -> None:
        self._full = text
        self._display = bookmark_display(text)
        self._elide()

    def set_status(self, text: str) -> None:
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def set_tips(self, delete_tip: str, menu_hint: str) -> None:
        self.close.setToolTip(delete_tip)
        self.close.setAccessibleName(delete_tip)
        self.setToolTip(self._full + "\n" + menu_hint)
        self.title.setToolTip(self._full + "\n" + menu_hint)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        width = self.title.width() - 2
        if width < 48:
            width = max(48, self.width() - self.close.sizeHint().width() - 48)
        self.title.setText(fit_bookmark_text(self._display, QFontMetrics(self.title.font()), width))


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
        self._attach_row(item)
        self.window.update_item(doc["id"])
        if select:
            self.window.filter.clear()
            self.window.select_id(doc["id"])
            editor.setFocus()
        self.window.schedule_save()
        return doc

    def _attach_row(self, item):
        doc_id = item.data(Qt.ItemDataRole.UserRole)
        row = BookmarkRow(
            lambda doc_id=doc_id: self.window.delete_bookmark(doc_id),
            lambda source, pos, doc_id=doc_id: self.window.show_bookmark_menu_for(doc_id, source, pos),
            lambda doc_id=doc_id: self.window.select_id(doc_id),
            lambda doc_id=doc_id: (self.window.select_id(doc_id), self.window.rename_document()),
        )
        self.window.library.setItemWidget(item, row)
        item.setSizeHint(row.sizeHint())

    def repair_bookmark_rows(self):
        """Qt drops the row widget when a list item is taken out and reinserted."""
        for index in range(self.window.library.count()):
            item = self.window.library.item(index)
            if not isinstance(self.window.library.itemWidget(item), BookmarkRow):
                self._attach_row(item)
            self.window.update_item(item.data(Qt.ItemDataRole.UserRole))

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
        self.window.reload_voices(prefer=doc.get("voice"))
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
        shown = bookmark_display(doc["title"])
        status = state.title() if state else ("●" if doc.get("dirty") else "")
        for index in range(self.window.library.count()):
            item = self.window.library.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == doc_id:
                item.setText("")
                item.setData(Qt.ItemDataRole.UserRole + 1, doc["title"] + "\n" + shown)
                item.setSizeHint(QSize(0, _ROW_HEIGHT))
                path = "\n" + doc["path"] if doc.get("path") else ""
                lang = self.window._lang()
                hint = i18n.t("bookmark.menu.hint", lang)
                item.setToolTip(doc["title"] + path + "\n" + hint)
                item.setData(Qt.ItemDataRole.AccessibleTextRole, shown + (" " + status if status else ""))
                row = self.window.library.itemWidget(item)
                if isinstance(row, BookmarkRow):
                    row.set_title(doc["title"])
                    row.set_status(status)
                    if status == "●":
                        row.status.setToolTip(i18n.t("bookmark.unsaved.mark", lang))
                    else:
                        row.status.setToolTip(status)
                    row.set_tips(i18n.t("bookmark.delete.tip", lang), hint + path)
                break

    def filter_documents(self, query):
        folded = query.casefold()
        for index in range(self.window.library.count()):
            item = self.window.library.item(index)
            haystack = str(item.data(Qt.ItemDataRole.UserRole + 1) or "")
            item.setHidden(folded not in haystack.casefold())

    def rename_document(self):
        doc = self.window.document()
        if not doc:
            return
        lang = self.window._lang()
        title, ok = QInputDialog.getText(
            self.window,
            i18n.t("bookmark.rename.title", lang),
            i18n.t("bookmark.rename.label", lang),
            text=doc["title"],
        )
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
            self.repair_bookmark_rows()
            self.window.schedule_save()

    def next_document(self, direction):
        if self.window.library.count():
            self.window.library.setCurrentRow((self.window.library.currentRow() + direction) % self.window.library.count())

    def protect_document(self, doc):
        if not doc.get("dirty"):
            return True
        lang = self.window._lang()
        answer = QMessageBox.warning(
            self.window,
            i18n.t("bookmark.unsaved.title", lang),
            i18n.t("bookmark.unsaved.body", lang, title=doc["title"]),
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
