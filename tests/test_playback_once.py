"""Each reading block is synthesized and started once per session."""
import base64

from PySide6.QtCore import QObject, Signal

from app.playback import PlaybackManager


class Bridge(QObject):
    synthesizeReady = Signal(str, str)
    openaiAudioReady = Signal(str, str, str)
    synthesizeError = Signal(str, str)
    openaiAudioError = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.calls = []

    def set_pronunciation_rules(self, _rules):
        return None

    def synthesize(self, *args):
        self.calls.append(args)

    def synthesize_openai(self, *args):
        self.calls.append(args)

    def cancel(self, _request):
        return None


class Audio(QObject):
    ended = Signal()
    failed = Signal(str)
    started = Signal()

    def __init__(self):
        super().__init__()
        self.plays = []
        self.resumes = 0

    def play(self, data, mime, volume):
        self.plays.append(data)

    def stop(self):
        return None

    def pause(self):
        return None

    def resume(self):
        self.resumes += 1
        self.started.emit()


def paragraph(label, size=200):
    body = (label + " ") * ((size // (len(label) + 1)) + 1)
    return body[:size].rstrip() + "."


def document(voice, provider, paragraphs):
    return {
        "id": "doc",
        "text": "\n\n".join(paragraphs),
        "voice": voice,
        "provider": provider,
        "speed": 1.0,
        "volume": 1.0,
        "markdownMode": "auto",
        "effectiveRules": [],
    }


def manager():
    bridge = Bridge()
    audio = Audio()
    playback = PlaybackManager(bridge, audio)
    return playback, bridge, audio


def deliver(playback, index, payload=b"wav"):
    for request, item in list(playback.requests.items()):
        if item[0] == index and item[1] == playback.session:
            playback._piper_ready(request, base64.b64encode(payload).decode())
            return request
    raise AssertionError(f"no request for block {index}")


def play_through(playback, audio):
    order = []
    while playback.state != "STOPPED":
        deliver(playback, playback.index, f"block-{playback.index}".encode())
        order.append(playback.index)
        audio.ended.emit()
    return order


def test_prefetch_does_not_restart_the_current_block():
    playback, bridge, audio = manager()
    paragraphs = [paragraph("Alpha"), paragraph("Beta"), paragraph("Gamma")]
    assert playback.play(document("en_US-lessac-medium", "piper", paragraphs))
    assert len(playback.chunks) == 3
    deliver(playback, 0, b"A")
    deliver(playback, 1, b"B")
    assert audio.plays == [b"A"]
    beta_requests = [call for call in bridge.calls if "Beta" in call[0]]
    audio.ended.emit()
    assert audio.plays == [b"A", b"B"]
    assert [call for call in bridge.calls if "Beta" in call[0]] == beta_requests
    audio.ended.emit()
    deliver(playback, playback.index, b"C")
    assert audio.plays == [b"A", b"B", b"C"]
    audio.ended.emit()
    assert playback.state == "STOPPED"


def test_duplicate_ready_starts_playback_once():
    playback, _bridge, audio = manager()
    assert playback.play(document("en_US-lessac-medium", "piper", [paragraph("Alpha"), paragraph("Beta")]))
    request = next(iter(playback.requests))
    payload = base64.b64encode(b"A").decode()
    playback._ready(request, payload, "audio/wav")
    playback._ready(request, payload, "audio/wav")
    assert audio.plays == [b"A"]


def test_late_result_from_the_previous_session_is_ignored():
    playback, _bridge, audio = manager()
    doc = document("en_US-lessac-medium", "piper", [paragraph("Alpha"), paragraph("Beta")])
    assert playback.play(doc)
    old_session = playback.session
    old_request = next(request for request, item in playback.requests.items() if item[0] == 0)
    assert playback.play(doc)
    assert playback.session != old_session
    playback._ready(old_request, base64.b64encode(b"old").decode(), "audio/wav")
    assert audio.plays == []
    deliver(playback, 0, b"new")
    assert audio.plays == [b"new"]


def test_stop_discards_a_pending_synthesis_result():
    playback, _bridge, audio = manager()
    assert playback.play(document("en_US-lessac-medium", "piper", [paragraph("Alpha")]))
    request = next(iter(playback.requests))
    playback.stop()
    playback._ready(request, base64.b64encode(b"late").decode(), "audio/wav")
    assert audio.plays == []
    assert playback.state == "STOPPED"


def test_repeated_play_and_stop_keep_one_progression():
    playback, bridge, audio = manager()
    doc = document("en_US-lessac-medium", "piper", [paragraph("Alpha"), paragraph("Beta"), paragraph("Gamma")])
    for _ in range(4):
        assert playback.play(doc)
        playback.stop()
        assert playback.active_playback_bookmark_id is None
    assert playback.play(doc)
    assert play_through(playback, audio) == [0, 1, 2]
    assert len(bridge.calls) >= 3


def test_identical_sentences_are_separate_blocks():
    playback, bridge, audio = manager()
    same = paragraph("Hello world", 180)
    assert playback.play(document("en_US-lessac-medium", "piper", [same, same]))
    assert len(playback.chunks) == 2
    assert playback.chunks[0]["text"] == playback.chunks[1]["text"]
    assert play_through(playback, audio) == [0, 1]
    hello_calls = [call for call in bridge.calls if call[0] == playback.chunks[0]["text"]]
    assert len(hello_calls) == 2
    assert audio.plays == [b"block-0", b"block-1"]


def test_piper_kokoro_and_clone_each_play_every_block_once():
    voices = (
        ("en_US-lessac-medium", "piper", 180),
        ("kokoro:af_heart", "kokoro", 500),
        ("clone:abc:en", "clone", 500),
    )
    for voice, provider, size in voices:
        playback, bridge, audio = manager()
        paragraphs = [paragraph("One", size), paragraph("Two", size), paragraph("Three", size)]
        assert playback.play(document(voice, provider, paragraphs))
        assert len(playback.chunks) >= 3
        played = play_through(playback, audio)
        assert played == list(range(len(playback.chunks)))
        assert len(bridge.calls) == len(playback.chunks)
        assert len(audio.plays) == len(playback.chunks)


def test_pause_and_resume_do_not_synthesize_again():
    playback, bridge, audio = manager()
    assert playback.play(document("en_US-lessac-medium", "piper", [paragraph("Alpha"), paragraph("Beta")]))
    deliver(playback, 0, b"A")
    calls = len(bridge.calls)
    playback.pause()
    playback.resume()
    assert audio.resumes == 1
    assert len(bridge.calls) == calls
    assert audio.plays == [b"A"]


def test_a_second_completion_advances_only_once():
    playback, _bridge, audio = manager()
    assert playback.play(document("en_US-lessac-medium", "piper", [paragraph("Alpha"), paragraph("Beta")]))
    deliver(playback, 0, b"A")
    audio.ended.emit()
    audio.ended.emit()
    assert audio.plays == [b"A"]
    assert playback.index == 1
    deliver(playback, 1, b"B")
    assert audio.plays == [b"A", b"B"]
