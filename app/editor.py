"""Native plain-text editing; Qt owns clipboard, undo, selection and text drops."""
from PySide6.QtCore import Signal
from PySide6.QtGui import QTextCursor, QTextDocument
from PySide6.QtWidgets import QPlainTextEdit, QDialog, QGridLayout, QLabel, QLineEdit, QPushButton, QCheckBox


class TextEditor(QPlainTextEdit):
    filesDropped = Signal(list)
    readSelection = Signal()
    readFromHere = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAccessibleName("Bookmark text editor")
        self.setPlaceholderText("Type or paste text here, or drop a TXT file to begin.")
        self.document().setDocumentMargin(20)
        self.setTabChangesFocus(False)

    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        menu.addSeparator()
        action = menu.addAction("Read Selection", self.readSelection.emit)
        action.setEnabled(self.textCursor().hasSelection())
        menu.addAction("Read From Here", self.readFromHere.emit)
        menu.exec(event.globalPos())
        menu.deleteLater()

    def canInsertFromMimeData(self, source):
        return source.hasUrls() or source.hasText()

    def insertFromMimeData(self, source):
        if source.hasUrls():
            paths = [url.toLocalFile() for url in source.urls() if url.isLocalFile()]
            if paths:
                self.filesDropped.emit(paths)
                return
        if source.hasText():
            self.insertPlainText(source.text())


class FindDialog(QDialog):
    def __init__(self, get_editor, parent=None):
        super().__init__(parent)
        self.get_editor = get_editor
        self.setWindowTitle("Find and Replace")
        layout = QGridLayout(self)
        self.query, self.replacement = QLineEdit(), QLineEdit()
        self.query.setAccessibleName("Find text")
        self.replacement.setAccessibleName("Replacement text")
        layout.addWidget(QLabel("Find"), 0, 0)
        layout.addWidget(self.query, 0, 1, 1, 3)
        layout.addWidget(QLabel("Replace with"), 1, 0)
        layout.addWidget(self.replacement, 1, 1, 1, 3)
        self.case = QCheckBox("Match case")
        self.words = QCheckBox("Whole words")
        layout.addWidget(self.case, 2, 1)
        layout.addWidget(self.words, 2, 2)
        self.feedback = QLabel()
        layout.addWidget(self.feedback, 4, 0, 1, 4)
        for col, (label, callback) in enumerate([
            ("Previous", lambda: self.find(True)), ("Next", self.find),
            ("Replace", self.replace), ("Replace All", self.replace_all)
        ]):
            button = QPushButton(label)
            button.clicked.connect(callback)
            layout.addWidget(button, 3, col)

    def flags(self, backward=False):
        flags = QTextDocument.FindFlag(0)
        if backward:
            flags |= QTextDocument.FindFlag.FindBackward
        if self.case.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        if self.words.isChecked():
            flags |= QTextDocument.FindFlag.FindWholeWords
        return flags

    def find(self, backward=False):
        editor = self.get_editor()
        if not editor or not self.query.text():
            return False
        old = editor.textCursor()
        found = editor.find(self.query.text(), self.flags(backward))
        if not found:
            cursor = editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End if backward else QTextCursor.MoveOperation.Start)
            editor.setTextCursor(cursor)
            found = editor.find(self.query.text(), self.flags(backward))
        if not found:
            editor.setTextCursor(old)
        self.feedback.setText("" if found else "No matches")
        return found

    def replace(self):
        editor = self.get_editor()
        if not editor or not self.query.text():
            return
        cursor = editor.textCursor()
        match = editor.document().find(self.query.text(), cursor.selectionStart(), self.flags())
        if not match.isNull() and match.selectionStart() == cursor.selectionStart() and match.selectionEnd() == cursor.selectionEnd():
            cursor.insertText(self.replacement.text())
        self.find()

    def replace_all(self):
        editor = self.get_editor()
        if not editor or not self.query.text():
            return
        cursor = QTextCursor(editor.document())
        cursor.beginEditBlock()
        count = 0
        while True:
            match = editor.document().find(self.query.text(), cursor, self.flags())
            if match.isNull():
                break
            match.insertText(self.replacement.text())
            cursor.setPosition(match.position())
            count += 1
        cursor.endEditBlock()
        self.feedback.setText(f"Replaced {count} occurrence(s)")
