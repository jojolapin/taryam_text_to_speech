"""Settings and optional speech tools, separate from the document workspace."""
import copy
import json
import uuid
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QPushButton, QTabWidget, QWidget, QListWidget,
    QDialogButtonBox, QTableWidget, QTableWidgetItem, QCheckBox, QInputDialog, QMessageBox)
from . import speaking_styles
from .openai_provider import OPENAI_MODELS


class SettingsDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window, self.bridge, self.request = window, window.bridge, None
        self.setWindowTitle("Voices and Settings")
        self.resize(660, 510)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        catalog_page = QWidget()
        catalog_layout = QVBoxLayout(catalog_page)
        search = QLineEdit()
        search.setPlaceholderText("Search voices or languages…")
        catalog_layout.addWidget(search)
        self.catalog = QListWidget()
        catalog_layout.addWidget(self.catalog)
        self.feedback = QLabel("Voice downloads are stored locally.")
        self.feedback.setWordWrap(True)
        catalog_layout.addWidget(self.feedback)
        row = QHBoxLayout()
        self.download = QPushButton("Download Selected Voice")
        self.download.clicked.connect(self.download_voice)
        row.addWidget(self.download)
        cancel = QPushButton("Cancel Download")
        cancel.clicked.connect(lambda: self.bridge.catalog_cancel(self.request) if self.request else None)
        row.addWidget(cancel)
        catalog_layout.addLayout(row)
        tabs.addTab(catalog_page, "Offline Voices")
        search.textChanged.connect(self.filter_catalog)
        self.bridge.catalogProgress.connect(self.progress)
        self.bridge.catalogDone.connect(self.done)
        self.bridge.catalogError.connect(self.failed)
        for voice in json.loads(self.bridge.catalog_list())["voices"]:
            self.catalog.addItem(voice["id"] + (" · installed" if voice.get("installed") else ""))
            self.catalog.item(self.catalog.count()-1).setData(Qt.ItemDataRole.UserRole, voice["id"])
        online = QWidget()
        form = QFormLayout(online)
        info = QLabel("Online speech and smart tools send requested text to your configured provider. API charges may apply. Keys are kept out of documents and exports.")
        info.setWordWrap(True)
        form.addRow(info)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("Enter a new API key to replace the configured key")
        form.addRow("API key", self.key)
        self.model = QComboBox()
        self.model.addItems(OPENAI_MODELS)
        self.model.setCurrentText(window.settings.get("openai_model", "gpt-4o-mini-tts"))
        form.addRow("Speech model", self.model)
        self.style = QComboBox()
        for preset in speaking_styles.all_presets():
            self.style.addItem(preset["label_en"], preset["id"])
        doc = window.document() or {}
        self.style.setCurrentIndex(max(0, self.style.findData(doc.get("speakingStyle", "neutral"))))
        form.addRow("Bookmark speaking style", self.style)
        self.instructions = QLineEdit(doc.get("speakingInstructions", ""))
        form.addRow("Custom delivery", self.instructions)
        self.markdown = QComboBox()
        self.markdown.addItems(["auto", "plain", "markdown"])
        self.markdown.setCurrentText({"off":"plain", "on":"markdown"}.get(doc.get("markdownMode"), doc.get("markdownMode", "auto")))
        form.addRow("Bookmark text format", self.markdown)
        tabs.addTab(online, "Speech Settings")
        tools_page = QWidget()
        tool_layout = QVBoxLayout(tools_page)
        tool_layout.addWidget(QLabel("AI transformations open a new bookmark and preserve the original."))
        for task in ("clean", "summarize", "explain", "translate"):
            button = QPushButton(task.title() + "…")
            button.clicked.connect(lambda checked=False, t=task: self.smart_tool(t))
            tool_layout.addWidget(button)
        tool_layout.addStretch()
        cache_button = QPushButton("Clear Generated Audio Cache")
        cache_button.clicked.connect(self.clear_cache)
        tool_layout.addWidget(cache_button)
        tabs.addTab(tools_page, "Smart Tools")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def filter_catalog(self, value):
        for i in range(self.catalog.count()):
            item = self.catalog.item(i)
            item.setHidden(value.casefold() not in item.text().casefold())

    def clear_cache(self):
        result = json.loads(self.bridge.clear_audio_cache("all", ""))
        QMessageBox.information(self, "Audio Cache", f'Cleared {result.get("removedCount", 0)} cached audio entries. Saved documents and exported audio files were preserved.')

    def download_voice(self):
        item = self.catalog.currentItem()
        if not item or self.request:
            return
        self.request = "catalog-" + uuid.uuid4().hex
        self.download.setEnabled(False)
        self.bridge.catalog_download(item.data(Qt.ItemDataRole.UserRole), self.request)

    def progress(self, request, done, total):
        if request == self.request:
            self.feedback.setText(f"Downloading: {done/1048576:.1f} / {total/1048576:.1f} MB")

    def done(self, request, voice):
        if request == self.request:
            self.request = None
            self.download.setEnabled(True)
            self.feedback.setText("Voice installed: " + voice)
            self.window.reload_voices()
            self.window.voice.setCurrentIndex(self.window.voice.findData(voice))

    def failed(self, request, message):
        if request == self.request:
            self.request = None
            self.download.setEnabled(True)
            self.feedback.setText(message)

    def save(self):
        if self.key.text().strip():
            self.bridge.set_openai_key(self.key.text().strip())
            self.key.clear()
        self.window.settings.set("openai_model", self.model.currentText())
        if self.window.document():
            self.window.document().update(speakingStyle=self.style.currentData(),
                speakingInstructions=self.instructions.text(), markdownMode=self.markdown.currentText())
            self.window.schedule_save()
        self.accept()

    def smart_tool(self, task):
        doc = self.window.document()
        if not doc or not doc["text"].strip():
            return
        language = ""
        if task == "translate":
            language, ok = QInputDialog.getText(self, "Translate", "Target language:")
            if not ok or not language.strip():
                return
        if QMessageBox.question(self, "Online Smart Tool", "Send this bookmark's text to the configured OpenAI provider? API charges may apply.") != QMessageBox.StandardButton.Yes:
            return
        request = "smart-" + uuid.uuid4().hex
        self.window.start_smart_tool(request, doc["text"], task, language, doc["title"] + " — " + task.title())


class PronunciationDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("Pronunciation Dictionary")
        self.resize(700, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Substitutions change spoken text only. Document text stays unchanged."))
        self.scope = QComboBox()
        self.scope.addItems(["All bookmarks", "This bookmark"])
        layout.addWidget(self.scope)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Original", "Pronounce as", "Whole word", "Match case", "Regex", "Enabled"])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        self.rules = [copy.deepcopy(window.settings.get_json("pronunciation_rules", [])),
                      copy.deepcopy((window.document() or {}).get("pronunciationRules", []))]
        self.scope_index = 0
        self.scope.currentIndexChanged.connect(self.change_scope)
        row = QHBoxLayout()
        add = QPushButton("Add")
        add.clicked.connect(lambda: self.add_rule({}))
        row.addWidget(add)
        remove = QPushButton("Remove Selected")
        remove.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()) if self.table.currentRow() >= 0 else None)
        row.addWidget(remove)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.populate()

    def add_rule(self, rule):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(rule.get("from", "")))
        self.table.setItem(row, 1, QTableWidgetItem(rule.get("to", "")))
        for column, (field, default) in enumerate([("whole_word", True), ("match_case", False), ("is_regex", False), ("enabled", True)], 2):
            box = QCheckBox()
            box.setChecked(rule.get(field, default))
            self.table.setCellWidget(row, column, box)

    def collect(self):
        result = []
        for row in range(self.table.rowCount()):
            original = self.table.item(row, 0).text()
            if not original:
                continue
            rule = {"from": original, "to": self.table.item(row, 1).text()}
            for column, field in enumerate(["whole_word", "match_case", "is_regex", "enabled"], 2):
                rule[field] = self.table.cellWidget(row, column).isChecked()
            result.append(rule)
        self.rules[self.scope_index] = result

    def populate(self):
        self.table.setRowCount(0)
        for rule in self.rules[self.scope_index]:
            self.add_rule(rule)

    def change_scope(self, index):
        self.collect()
        self.scope_index = index
        self.populate()

    def save(self):
        self.collect()
        self.window.settings.set_json("pronunciation_rules", self.rules[0])
        if self.window.document():
            self.window.document()["pronunciationRules"] = self.rules[1]
            self.window.schedule_save()
        self.accept()
