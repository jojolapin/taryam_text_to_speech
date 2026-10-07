"""Voice library and the clone-my-voice dialog.

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import shutil
import threading
import wave
from pathlib import Path

from PySide6.QtCore import QEventLoop, QObject, QTimer, Qt, QUrl, Signal
from PySide6.QtMultimedia import QAudioFormat, QAudioOutput, QAudioSource, QMediaDevices, QMediaPlayer
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit, QProgressDialog,
    QPushButton, QVBoxLayout, QWidget,
)

from . import i18n
from .paths import user_data_dir
from .speech_engines.clone_client import CloneClient, models_ready, poll_download_bytes, runtime_installed
from .speech_engines.clone_errors import CloneError
from .speech_engines.clone_profiles import (
    build_profile, delete_profile, list_profiles, split_voice_id, storage_id,
)
from .speech_engines.reference_audio import analyze_wav
from .speech_engines.router import is_clone_voice


def _lang(window) -> str:
    return i18n.resolve_lang(window.settings.get("language", "system"))


def format_report(report, lang: str) -> str:
    lines = [
        i18n.t(f"clone.audio.{report.level}", lang),
        i18n.t("clone.audio.duration", lang, seconds=f"{report.duration_s:.1f}"),
        i18n.t("clone.audio.rate", lang, rate=report.sample_rate, channels=report.channels),
    ]
    for note in report.notes:
        lines.append(i18n.t(f"clone.audio.{note}", lang))
    return "\n".join(lines)


def _import_dir(window) -> Path:
    path = user_data_dir() / "cache" / "clone-import"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_clone_ready(window, voice_id: str) -> bool:
    """Start Pocket only for an explicit cloned voice. Ask before the first download."""
    if not is_clone_voice(voice_id):
        return True
    lang = _lang(window)
    if not runtime_installed():
        window.show_error(i18n.t("clone.error.clone-runtime-missing", lang))
        return False
    if not models_ready():
        answer = QMessageBox.question(
            window,
            i18n.t("clone.download.title", lang),
            i18n.t("clone.download.body", lang),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
    return _run_service(window, lambda client: client.ensure_models())


def _run_service(window, work) -> bool:
    lang = _lang(window)
    progress = QProgressDialog(
        i18n.t("clone.download.progress", lang),
        i18n.t("clone.download.cancel", lang),
        0, 1000, window,
    )
    progress.setWindowTitle(i18n.t("clone.download.title", lang))
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setValue(0)
    cancel = threading.Event()
    outcome = {"ok": False, "error": ""}

    class _Relay(QObject):
        tick = Signal(int)
        finished = Signal(bool, str)

    relay = _Relay(window)

    def on_tick(value: int) -> None:
        progress.setValue(value)
        progress.setLabelText(i18n.t("clone.download.progress", lang))

    def runner() -> None:
        try:
            client = CloneClient()
            work(client)
            relay.finished.emit(True, "")
        except CloneError as exc:
            relay.finished.emit(False, i18n.t(f"clone.error.{exc.code}", lang, detail=exc.detail))
        except Exception as exc:  # noqa: BLE001
            relay.finished.emit(False, str(exc))

    loop = QEventLoop(window)

    def finish(ok: bool, message: str) -> None:
        outcome["ok"] = ok
        outcome["error"] = message
        progress.reset()
        loop.quit()

    timer = QTimer(window)
    timer.setInterval(500)

    def poll() -> None:
        if cancel.is_set():
            return
        downloaded = poll_download_bytes()
        if downloaded:
            relay.tick.emit(min(990, int(downloaded / (1500 * 1024 * 1024) * 1000)))

    relay.tick.connect(on_tick)
    relay.finished.connect(finish)
    def on_cancel() -> None:
        cancel.set()
        CloneClient().shutdown()

    progress.canceled.connect(on_cancel)
    timer.timeout.connect(poll)
    timer.start()
    threading.Thread(target=runner, name="pocket-service", daemon=True).start()
    loop.exec()
    timer.stop()
    if cancel.is_set() and not outcome["ok"]:
        CloneClient().shutdown()
        return False
    if not outcome["ok"] and outcome["error"]:
        window.show_error(outcome["error"])
    return bool(outcome["ok"])


class VoiceLibraryDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        lang = _lang(window)
        self.setWindowTitle(i18n.t("clone.library.title", lang))
        self.resize(460, 360)
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        layout.addWidget(self.list)
        self.empty = QLabel(i18n.t("clone.library.empty", lang))
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        buttons = QHBoxLayout()
        add = QPushButton(i18n.t("clone.library.add", lang))
        remove = QPushButton(i18n.t("clone.library.delete", lang))
        add.clicked.connect(self.add_voice)
        remove.clicked.connect(self.remove_voice)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        self.reload()

    def reload(self) -> None:
        lang = _lang(self.window)
        self.list.clear()
        profiles = list_profiles()
        for profile in profiles:
            name = profile.get("display_name") or profile.get("voice_id")
            languages = ", ".join(i18n.t(f"clone.lang.{item}", lang) for item in profile.get("supported_languages") or [])
            self.list.addItem(f"{name} — {languages}")
            self.list.item(self.list.count() - 1).setData(Qt.ItemDataRole.UserRole, profile.get("voice_id"))
        self.empty.setVisible(not profiles)
        self.window.reload_voices()

    def add_voice(self) -> None:
        dialog = CloneVoiceDialog(self.window)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.created_id:
            lang = "fr" if _lang(self.window) == "fr" else "en"
            voice = storage_id(dialog.created_id, lang)
            self.window.provider.setCurrentIndex(max(0, self.window.provider.findData("clone")))
            self.window.reload_voices(prefer=voice)
            self.window.controls_changed()
        self.reload()

    def remove_voice(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        lang = _lang(self.window)
        voice_id = item.data(Qt.ItemDataRole.UserRole)
        name = item.text()
        answer = QMessageBox.question(
            self,
            i18n.t("confirm.delete_voice.title", lang),
            i18n.t("confirm.delete_voice.body", lang, voice=name),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        delete_profile(str(voice_id))
        self.reload()


class CloneVoiceDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.created_id = ""
        self._source = ""
        self._kind = "import"
        self._report = None
        self._profile = None
        self._accepted_voice = False
        self._recorder = None
        self._capture = None
        self._pcm = bytearray()
        self._record_rate = 24000
        self._record_channels = 1
        lang = _lang(window)
        self.setWindowTitle(i18n.t("clone.dialog.title", lang))
        self.resize(520, 460)
        root = QVBoxLayout(self)
        self.form = QWidget()
        form = QFormLayout(self.form)
        self.name = QLineEdit(i18n.t("clone.default_name", lang))
        form.addRow(i18n.t("clone.name", lang), self.name)
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        self.import_button = QPushButton(i18n.t("clone.import", lang))
        self.record_button = QPushButton(i18n.t("clone.record", lang))
        self.import_button.clicked.connect(self.import_audio)
        self.record_button.clicked.connect(self.toggle_record)
        row_layout.addWidget(self.import_button)
        row_layout.addWidget(self.record_button)
        form.addRow(row)
        self.file_label = QLabel("")
        self.file_label.setWordWrap(True)
        form.addRow(self.file_label)
        self.analysis = QPlainTextEdit()
        self.analysis.setReadOnly(True)
        self.analysis.setMinimumHeight(120)
        form.addRow(self.analysis)
        self.transcript = QLineEdit()
        self.transcript.setPlaceholderText(i18n.t("clone.transcript.hint", lang))
        form.addRow(i18n.t("clone.transcript", lang), self.transcript)
        self.consent = QCheckBox()
        consent_text = QLabel(i18n.t("clone.consent", lang))
        consent_text.setWordWrap(True)
        consent_row = QWidget()
        consent_layout = QHBoxLayout(consent_row)
        consent_layout.setContentsMargins(0, 0, 0, 0)
        consent_layout.addWidget(self.consent)
        consent_layout.addWidget(consent_text, 1)
        form.addRow(consent_row)
        root.addWidget(self.form)
        self.preview_box = QWidget()
        preview_layout = QVBoxLayout(self.preview_box)
        self.preview_label = QLabel(i18n.t("clone.preview.playing", lang))
        self.preview_label.setWordWrap(True)
        preview_layout.addWidget(self.preview_label)
        self.preview_box.hide()
        root.addWidget(self.preview_box)
        self.buttons = QDialogButtonBox()
        self.create_button = self.buttons.addButton(i18n.t("clone.create", lang), QDialogButtonBox.ButtonRole.AcceptRole)
        self.use_button = self.buttons.addButton(i18n.t("clone.accept", lang), QDialogButtonBox.ButtonRole.AcceptRole)
        self.retry_button = self.buttons.addButton(i18n.t("clone.retry", lang), QDialogButtonBox.ButtonRole.ResetRole)
        self.buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.use_button.hide()
        self.retry_button.hide()
        self.create_button.clicked.connect(self.create_voice)
        self.use_button.clicked.connect(self.keep_voice)
        self.retry_button.clicked.connect(self.retry)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)
        self._player = QMediaPlayer(self)
        self._output = QAudioOutput(self)
        self._player.setAudioOutput(self._output)
        self._clock = QTimer(self)
        self._clock.setInterval(200)
        self._clock.timeout.connect(self._update_recording)
        if not QMediaDevices.audioInputs():
            self.record_button.setEnabled(False)
            self.record_button.setToolTip(i18n.t("clone.record.none", lang))

    def import_audio(self) -> None:
        lang = _lang(self.window)
        path, _filter = QFileDialog.getOpenFileName(
            self,
            i18n.t("clone.import", lang),
            "",
            "Audio (*.wav *.mp3)",
        )
        if not path:
            return
        self._stop_recording()
        self._kind = "import"
        self._load_source(Path(path))

    def _load_source(self, path: Path) -> None:
        lang = _lang(self.window)
        self._source = str(path)
        self.file_label.setText(path.name)
        suffix = path.suffix.lower()
        if suffix == ".wav":
            try:
                self._report = analyze_wav(path)
            except (OSError, wave.Error, ValueError) as exc:
                self._report = None
                self.analysis.setPlainText(str(exc))
                return
            self.analysis.setPlainText(format_report(self._report, lang))
            return
        if suffix == ".mp3":
            self._report = None
            try:
                from mutagen.mp3 import MP3

                info = MP3(path).info
                seconds = f"{float(info.length):.1f}"
            except Exception:
                seconds = "?"
            self.analysis.setPlainText(
                i18n.t("clone.audio.duration", lang, seconds=seconds) + "\n" + i18n.t("clone.audio.mp3", lang)
            )
            return
        self._report = None
        self.analysis.setPlainText(i18n.t("clone.error.clone-audio-rejected", lang, detail=suffix))

    def toggle_record(self) -> None:
        if self._recorder is not None:
            self._finish_recording()
            return
        lang = _lang(self.window)
        device = QMediaDevices.defaultAudioInput()
        if device.isNull():
            QMessageBox.information(self, i18n.t("clone.dialog.title", lang), i18n.t("clone.record.none", lang))
            return
        fmt = QAudioFormat()
        fmt.setSampleRate(24000)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not device.isFormatSupported(fmt):
            QMessageBox.information(self, i18n.t("clone.dialog.title", lang), i18n.t("clone.record.none", lang))
            return
        self._pcm = bytearray()
        self._record_rate = 24000
        self._recorder = QAudioSource(device, fmt, self)
        self._capture = self._recorder.start()
        if self._capture is None:
            self._recorder = None
            QMessageBox.information(self, i18n.t("clone.dialog.title", lang), i18n.t("clone.record.none", lang))
            return
        self._capture.readyRead.connect(self._read_audio)
        self.record_button.setText(i18n.t("clone.record.stop", lang))
        self._clock.start()

    def _read_audio(self) -> None:
        if self._capture is not None:
            self._pcm.extend(bytes(self._capture.readAll()))

    def _update_recording(self) -> None:
        lang = _lang(self.window)
        frames = len(self._pcm) // 2
        seconds = frames / self._record_rate if self._record_rate else 0
        self.file_label.setText(i18n.t("clone.audio.duration", lang, seconds=f"{seconds:.1f}"))

    def _finish_recording(self) -> None:
        self._clock.stop()
        if self._capture is not None:
            self._pcm.extend(bytes(self._capture.readAll()))
        if self._recorder is not None:
            self._recorder.stop()
        self._recorder = None
        self._capture = None
        self.record_button.setText(i18n.t("clone.record", _lang(self.window)))
        if len(self._pcm) < 4:
            return
        dest = _import_dir(self.window) / "recording.wav"
        with wave.open(str(dest), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(self._record_rate)
            handle.writeframes(bytes(self._pcm))
        self._kind = "record"
        self._load_source(dest)

    def _stop_recording(self) -> None:
        if self._recorder is not None:
            self._clock.stop()
            self._recorder.stop()
            self._recorder = None
            self._capture = None
            self.record_button.setText(i18n.t("clone.record", _lang(self.window)))

    def create_voice(self) -> None:
        lang = _lang(self.window)
        if not self.consent.isChecked():
            self.window.show_error(i18n.t("clone.error.clone-consent", lang))
            return
        if not self._source:
            self.window.show_error(i18n.t("clone.error.clone-audio-rejected", lang, detail=""))
            return
        if self._report is not None and self._report.level == "error":
            self.analysis.setPlainText(format_report(self._report, lang))
            return
        display_name = self.name.text().strip()
        if not display_name:
            return
        self._stop_recording()
        if not runtime_installed():
            self.window.show_error(i18n.t("clone.error.clone-runtime-missing", lang))
            return
        if not models_ready():
            answer = QMessageBox.question(
                self,
                i18n.t("clone.download.title", lang),
                i18n.t("clone.download.body", lang),
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        transcript = self.transcript.text()
        presented = i18n.t("clone.consent", lang)
        kind = self._kind
        holder = {"profile": None}

        def work(client: CloneClient) -> None:
            source = self._prepared_wav(client)
            status = client.ensure_models()
            holder["profile"] = build_profile(
                display_name=display_name,
                source_wav=source,
                source_kind=kind,
                transcript=transcript,
                consent=True,
                presented=presented,
                locale=lang,
                engine_version=str(status.get("pocket_tts") or ""),
                service=client,
                ui_language=lang,
            )

        if not _run_service(self.window, work) or holder["profile"] is None:
            return
        self._show_preview(holder["profile"])

    def _prepared_wav(self, client: CloneClient) -> Path:
        source = Path(self._source)
        if source.suffix.lower() != ".mp3":
            return source
        folder = _import_dir(self.window)
        copied = folder / "source.mp3"
        shutil.copyfile(source, copied)
        decoded = folder / "decoded.wav"
        client.decode(copied, decoded)
        report = analyze_wav(decoded)
        if report.level == "error":
            raise CloneError("clone-audio-rejected", ",".join(report.notes))
        return decoded

    def _show_preview(self, profile: dict) -> None:
        self._profile = profile
        self.form.hide()
        self.preview_box.show()
        self.create_button.hide()
        self.use_button.show()
        self.retry_button.show()
        folder_id, _language = split_voice_id(str(profile["voice_id"]))
        preview = user_data_dir() / "voices" / "cloned" / folder_id / str(profile.get("preview_file") or "preview.wav")
        self._player.setSource(QUrl.fromLocalFile(str(preview)))
        self._player.play()

    def keep_voice(self) -> None:
        if not self._profile:
            return
        self._accepted_voice = True
        self.created_id = split_voice_id(str(self._profile["voice_id"]))[0]
        self._player.stop()
        self.accept()

    def retry(self) -> None:
        self._player.stop()
        if self._profile is not None:
            delete_profile(str(self._profile["voice_id"]))
            self._profile = None
        self.preview_box.hide()
        self.form.show()
        self.use_button.hide()
        self.retry_button.hide()
        self.create_button.show()

    def reject(self) -> None:
        self._stop_recording()
        self._player.stop()
        if self._profile is not None and not self._accepted_voice:
            delete_profile(str(self._profile["voice_id"]))
        super().reject()
