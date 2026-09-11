"""Visible audio export controls, shared by the toolbar and File menu."""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QLineEdit, QProgressBar)
from PySide6.QtCore import Qt


class ExportPanel(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.busy = False
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("exportCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        title = QLabel("AUDIO EXPORT")
        title.setObjectName("sectionLabel")
        layout.addWidget(title)
        row = QHBoxLayout()
        self.generate = QPushButton("Generate audio")
        self.generate.setObjectName("primaryButton")
        self.generate.clicked.connect(lambda: window.export_audio())
        row.addWidget(self.generate)
        self.batch = QPushButton("Batch export")
        self.batch.setToolTip("Save each paragraph as a separate audio file in a folder you choose.")
        self.batch.clicked.connect(lambda: window.export_audio(batch=True))
        row.addWidget(self.batch)
        row.addStretch()
        row.addWidget(QLabel("Format"))
        self.format = QComboBox()
        self.format.setAccessibleName("Audio export format")
        for value in ("mp3", "wav"):
            self.format.addItem(value.upper(), value)
        self.format.setCurrentIndex(max(0, self.format.findData(window.settings.get("export_format", "mp3"))))
        row.addWidget(self.format)
        row.addWidget(QLabel("Bitrate"))
        self.bitrate = QComboBox()
        self.bitrate.setAccessibleName("MP3 bitrate")
        for value in (64, 128, 192, 256, 320):
            self.bitrate.addItem(f"{value} kbps", value)
        self.bitrate.setCurrentIndex(max(0, self.bitrate.findData(window.settings.get("mp3_bitrate", 128))))
        row.addWidget(self.bitrate)
        layout.addLayout(row)
        metadata = QHBoxLayout()
        metadata.addWidget(QLabel("MP3 author"))
        self.author = QLineEdit(window.settings.get("id3_author", ""))
        self.author.setAccessibleName("MP3 author tag")
        self.author.setPlaceholderText("Optional artist / author tag")
        self.author.editingFinished.connect(lambda: window.settings.set("id3_author", self.author.text()))
        metadata.addWidget(self.author)
        self.cancel = QPushButton("Cancel export")
        self.cancel.clicked.connect(window.cancel_audio_export)
        self.cancel.setEnabled(False)
        metadata.addWidget(self.cancel)
        layout.addLayout(metadata)
        self.feedback = QLabel("Entire bookmark → one file. Batch → one file per paragraph.")
        self.feedback.setObjectName("mutedLabel")
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(5)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.format.currentIndexChanged.connect(self.options_changed)
        self.bitrate.currentIndexChanged.connect(self.options_changed)
        self.refresh_options()

    def refresh_options(self):
        # OpenAI chooses its encoded MP3 bitrate; do not promise a local setting applies.
        offline = self.window.provider.currentData() == "piper"
        mp3 = self.format.currentData() == "mp3"
        self.bitrate.setEnabled(offline and mp3 and not self.busy)
        self.bitrate.setToolTip("Choose the offline MP3 encoding bitrate." if offline and mp3
            else "WAV is uncompressed; OpenAI controls its own encoded bitrate.")
        self.author.setEnabled(offline and mp3 and not self.busy)

    def options_changed(self):
        self.window.settings.set("export_format", self.format.currentData())
        self.window.settings.set("mp3_bitrate", self.bitrate.currentData())
        self.refresh_options()

    def set_busy(self, busy):
        self.busy = busy
        for widget in (self.generate, self.batch, self.format, self.bitrate, self.author):
            widget.setEnabled(not busy)
        self.cancel.setEnabled(busy)
        self.progress.setVisible(busy)
        if busy:
            self.progress.setValue(0)
            self.feedback.setText("Choose the output location…")
        else:
            self.refresh_options()
