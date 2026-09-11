"""One audio output, explicit document ownership and stale-request rejection."""
from __future__ import annotations

import base64
import copy
import json
import logging
import uuid

from PySide6.QtCore import QObject, Signal, Slot, QBuffer, QIODevice, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from .chunking import chunk

log = logging.getLogger("textspeak.playback")


class AudioOutput(QObject):
    ended = Signal()
    failed = Signal(str)
    started = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = None
        self.buffer = None
        self.output = QAudioOutput(self)

    def play(self, data, mime, volume):
        self.stop()
        self.output.setVolume(volume)
        player = QMediaPlayer(self)
        self.player = player
        self.buffer = QBuffer(self)
        self.buffer.setData(data)
        self.buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        player.setAudioOutput(self.output)
        player.mediaStatusChanged.connect(lambda status: self._status(player, status))
        player.errorOccurred.connect(lambda error, message: self.failed.emit(message) if self.player is player else None)
        player.playbackStateChanged.connect(lambda state: self.started.emit() if self.player is player and state == QMediaPlayer.PlaybackState.PlayingState else None)
        player.setSourceDevice(self.buffer, QUrl("reading.wav" if "wav" in mime else "reading.mp3"))
        player.play()

    def _status(self, player, status):
        if player is self.player and status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.ended.emit()

    def stop(self):
        player, self.player = self.player, None
        if player:
            player.stop()
            player.setSource(QUrl())
            player.deleteLater()
        if self.buffer:
            self.buffer.close()
            self.buffer.deleteLater()
            self.buffer = None

    def pause(self):
        if self.player:
            self.player.pause()

    def resume(self):
        if self.player:
            self.player.play()


class PlaybackManager(QObject):
    changed = Signal()
    passage = Signal(str, int, int)  # document id, actual chunk bounds in source
    position = Signal(str, int)
    error = Signal(str)

    def __init__(self, bridge, audio=None, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self.audio = audio or AudioOutput(self)
        self.active_playback_bookmark_id = None
        self.state = "STOPPED"
        self.document = None
        self.chunks = []
        self.index = 0
        self.requests = {}
        self.cache = {}
        self.current_loaded = False
        bridge.synthesizeReady.connect(self._piper_ready)
        bridge.openaiAudioReady.connect(self._ready)
        bridge.synthesizeError.connect(self._failed)
        bridge.openaiAudioError.connect(self._failed)
        self.audio.ended.connect(self._ended)
        self.audio.failed.connect(self._audio_failed)
        self.audio.started.connect(self._started)

    def play(self, document, start=0, end=None):
        text = document.get("text", "")
        end = len(text) if end is None else min(len(text), end)
        start = max(0, min(start, end))
        if not text[start:end].strip():
            self.error.emit("There is no text to read at this position.")
            return False
        if not document.get("voice"):
            self.error.emit("Select or download a voice before playing.")
            return False
        self.stop()  # Synchronous audio stop BEFORE assigning the new owner.
        self.document = copy.deepcopy(document)
        self.active_playback_bookmark_id = document["id"]
        self.chunks = chunk(text[start:end], 260)
        for section in self.chunks:
            section["start"] += start
            section["end"] += start
        self.index = 0
        self.state = "LOADING"
        self.changed.emit()
        log.info("Playback started; backend=%s", document.get("provider", "piper"))
        self._request(0)
        self._request(1)
        return True

    def _request(self, index):
        if index >= len(self.chunks) or index in self.cache or index in self.requests.values():
            return
        request = "play-" + uuid.uuid4().hex
        self.requests[request] = index
        doc = self.document
        # Freeze effective pronunciation per session, independent of navigation.
        self.bridge.set_pronunciation_rules(json.dumps(doc.get("effectiveRules", [])))
        text = self.chunks[index]["text"]
        if doc.get("provider") == "openai":
            self.bridge.synthesize_openai(text, doc["voice"], doc.get("model", "gpt-4o-mini-tts"),
                doc.get("speed") or 1.0, doc.get("speakingInstructions", ""), "mp3",
                "document:" + doc.get("markdownMode", "auto"), doc["id"], request)
        else:
            self.bridge.synthesize(text, doc["voice"], 1.0 / (doc.get("speed") or 1.0),
                                   1.0, request, "document:" + doc.get("markdownMode", "auto"))

    @Slot(str, str)
    def _piper_ready(self, request, data):
        self._ready(request, data, "audio/wav")

    @Slot(str, str, str)
    def _ready(self, request, data, mime):
        index = self.requests.pop(request, None)
        if index is None:
            return
        try:
            self.cache[index] = (base64.b64decode(data, validate=True), mime)
        except (ValueError, TypeError):
            self._audio_failed("The speech engine returned invalid audio.")
            return
        if index == self.index and self.state != "PAUSED":
            self._play_current()

    def _play_current(self):
        if self.index not in self.cache:
            self.state = "LOADING"
            self.changed.emit()
            return
        data, mime = self.cache.pop(self.index)
        self.current_loaded = True
        section = self.chunks[self.index]
        self.position.emit(self.active_playback_bookmark_id, section["start"])
        self.passage.emit(self.active_playback_bookmark_id, section["start"], section["end"])
        self.audio.play(data, mime, self.document.get("volume", 1.0))

    @Slot()
    def _started(self):
        if self.state == "PAUSED":
            self.audio.pause()
        elif self.active_playback_bookmark_id:
            self.state = "PLAYING"
            self.changed.emit()

    @Slot()
    def _ended(self):
        if not self.active_playback_bookmark_id or not self.current_loaded:
            return
        self.current_loaded = False
        self.position.emit(self.active_playback_bookmark_id, self.chunks[self.index]["end"])
        self.index += 1
        if self.index >= len(self.chunks):
            self.stop()
            return
        if self.state != "PAUSED":
            self._play_current()
        self._request(self.index)
        self._request(self.index + 1)

    def pause(self):
        if self.state in {"PLAYING", "LOADING"}:
            self.state = "PAUSED"
            self.audio.pause()
            self.changed.emit()

    def resume(self):
        if self.state != "PAUSED":
            return
        self.state = "LOADING"
        if self.current_loaded:
            self.audio.resume()
        else:
            self._play_current()
        self.changed.emit()

    def stop(self):
        requests, self.requests = self.requests, {}
        self.audio.stop()
        for request in requests:
            self.bridge.cancel(request)
        self.cache.clear()
        self.current_loaded = False
        self.active_playback_bookmark_id = None
        self.state = "STOPPED"
        self.changed.emit()

    def skip(self, direction):
        if not self.document or not self.chunks:
            return
        index = max(0, min(len(self.chunks) - 1, self.index + direction))
        self.play(self.document, self.chunks[index]["start"])

    @Slot(str, str)
    def _failed(self, request, message):
        if request in self.requests:
            self._audio_failed(message)

    @Slot(str)
    def _audio_failed(self, message):
        if self.active_playback_bookmark_id:
            self.stop()
            log.error("Playback failed: %s", message)
            self.error.emit("Speech playback failed. " + message)
