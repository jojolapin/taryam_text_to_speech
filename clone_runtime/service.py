"""Pocket TTS localhost service for TextSpeak Pro.

Run this with the interpreter in ``clone_runtime/.venv``. The main application
never imports this file. The socket accepts connections on 127.0.0.1 only.

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import argparse
import faulthandler
import json
import logging
import os
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


log = logging.getLogger("textspeak.pocket")

LANGUAGES = {"english", "french_24l"}


def _rss_bytes() -> int:
    try:
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.K32GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD,
        ]
        kernel.K32GetProcessMemoryInfo.restype = wintypes.BOOL
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if not kernel.K32GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return 0
        return int(counters.WorkingSetSize)
    except Exception:
        return 0


def _dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def _use_existing_hf_token() -> None:
    """Use the signed-in Hugging Face account without printing the token.

    The service keeps its own HF_HOME, so the Hub would otherwise ignore the
    token already stored for this Windows user.
    """
    if os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN"):
        return
    for path in (
        Path.home() / ".cache" / "huggingface" / "token",
        Path.home() / ".huggingface" / "token",
    ):
        try:
            token = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if token:
            os.environ["HF_TOKEN"] = token
            return


def _parse_hf_url(url: str) -> tuple[str, str, str]:
    rest = url.strip().removeprefix("hf://")
    path, revision = rest.rsplit("@", 1)
    org, name, filename = path.split("/", 2)
    return f"{org}/{name}", filename, revision


def _cloning_weight_url(language: str) -> str:
    import pocket_tts

    config = Path(pocket_tts.__file__).resolve().parent / "config" / f"{language}.yaml"
    for line in config.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("weights_path:"):
            return stripped.split(":", 1)[1].strip()
    raise RuntimeError(f"Pocket config for {language} has no cloning weights")


def _require_cloning_weights(language: str) -> None:
    """Stop before Pocket substitutes its public non-cloning weights.

    pocket-tts 2.1.0 catches a failed download of ``kyutai/pocket-tts`` and
    silently loads ``kyutai/pocket-tts-without-voice-cloning``. That model
    cannot build a voice profile.
    """
    from huggingface_hub import get_hf_file_metadata, hf_hub_url, try_to_load_from_cache

    repo, filename, revision = _parse_hf_url(_cloning_weight_url(language))
    cached = try_to_load_from_cache(repo, filename, revision=revision)
    if isinstance(cached, str):
        return
    try:
        get_hf_file_metadata(hf_hub_url(repo, filename, revision=revision))
    except Exception as exc:
        text = f"{type(exc).__name__}: {exc}".lower()
        if any(word in text for word in ("gated", "401", "403", "restricted", "unauthorized")):
            raise RuntimeError(
                "Hugging Face gated repo kyutai/pocket-tts refused the voice-cloning weights. "
                "Sign in and accept access at https://huggingface.co/kyutai/pocket-tts"
            ) from exc
        raise


def _clear_incomplete(path: Path) -> None:
    if not path.exists():
        return
    for item in path.rglob("*.incomplete"):
        try:
            item.unlink()
        except OSError:
            pass


class PocketService:
    def __init__(self, model_dir: Path, allowed_root: Path, idle_seconds: float):
        self.model_dir = model_dir
        self.allowed_root = allowed_root.resolve()
        self.idle_seconds = idle_seconds
        self.models = {}
        self.states = {}
        self.lock = threading.Lock()
        self.last_used = time.monotonic()
        self.busy = 0
        self.phase = "idle"
        self.error = ""
        self.versions = {"pocket_tts": "", "torch": ""}

    def touch(self) -> None:
        self.last_used = time.monotonic()

    def idle_expired(self) -> bool:
        return self.busy == 0 and (time.monotonic() - self.last_used) >= self.idle_seconds

    def _inside(self, path: Path) -> Path:
        resolved = path.resolve()
        try:
            resolved.relative_to(self.allowed_root)
        except ValueError as exc:
            raise PermissionError(str(path)) from exc
        return resolved

    def status(self) -> dict:
        cached = []
        marker = self.model_dir / "ready.json"
        if marker.is_file():
            try:
                data = json.loads(marker.read_text(encoding="utf-8"))
                cached = sorted((data.get("languages") or {}).keys())
            except (OSError, json.JSONDecodeError):
                cached = []
        return {
            "ok": True,
            "service": "textspeak-pocket",
            "pid": os.getpid(),
            "phase": self.phase,
            "pocket_tts": self.versions["pocket_tts"],
            "torch": self.versions["torch"],
            "models_loaded": sorted(self.models),
            "models_cached": cached,
            "download_bytes": _dir_size(self.model_dir),
            "rss_bytes": _rss_bytes(),
            "idle_seconds": self.idle_seconds,
            "error": self.error,
        }

    def _versions(self) -> None:
        from importlib.metadata import version

        import torch

        self.versions["pocket_tts"] = version("pocket-tts")
        self.versions["torch"] = torch.__version__

    def _load(self, language: str):
        if language not in LANGUAGES:
            raise ValueError(language)
        if language in self.models:
            return self.models[language]
        import inspect

        from pocket_tts import TTSModel

        self.phase = f"loading:{language}"
        _require_cloning_weights(language)
        signature = inspect.signature(TTSModel.load_model)
        if "language" in signature.parameters:
            model = TTSModel.load_model(language=language)
        else:
            model = TTSModel.load_model(language)
        if not getattr(model, "has_voice_cloning", False):
            raise RuntimeError(
                "Pocket TTS loaded the public model without voice cloning because "
                "Hugging Face refused kyutai/pocket-tts."
            )
        self.models[language] = model
        return model

    def ensure(self, languages: list[str]) -> dict:
        os.environ.setdefault("HF_HOME", str(self.model_dir / "huggingface"))
        os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(self.model_dir / "huggingface" / "hub"))
        self.model_dir.mkdir(parents=True, exist_ok=True)
        wanted = [item for item in languages if item in LANGUAGES] or ["english", "french_24l"]
        with self.lock:
            self.busy += 1
            self.touch()
            try:
                self._versions()
                sizes = {}
                for language in wanted:
                    try:
                        model = self._load(language)
                    except Exception:
                        self.models.clear()
                        _clear_incomplete(self.model_dir)
                        ready = self.model_dir / "ready.json"
                        try:
                            ready.unlink()
                        except OSError:
                            pass
                        self.phase = "error"
                        raise
                    sizes[language] = int(getattr(model, "sample_rate", 0) or 0)
                marker = {
                    "pocket_tts": self.versions["pocket_tts"],
                    "torch": self.versions["torch"],
                    "languages": {language: {"sample_rate": sizes[language]} for language in wanted},
                    "cache_bytes": _dir_size(self.model_dir),
                    "voice_cloning": True,
                }
                ready = self.model_dir / "ready.json"
                temporary = ready.with_suffix(".json.part")
                temporary.write_text(json.dumps(marker, indent=2), encoding="utf-8")
                temporary.replace(ready)
                self.phase = "ready"
                self.error = ""
                return self.status()
            finally:
                self.busy -= 1
                self.touch()

    def decode(self, source: Path, dest: Path) -> dict:
        source = self._inside(source)
        dest = self._inside(dest)
        samples, rate = _read_audio(source)
        _write_wav(dest, samples, rate)
        return {"ok": True, "sample_rate": rate, "samples": int(samples.shape[0])}

    def export(self, wav: Path, dest: Path, language: str) -> dict:
        wav = self._inside(wav)
        dest = self._inside(dest)
        if language not in LANGUAGES:
            raise ValueError(language)
        from pocket_tts import export_model_state

        with self.lock:
            self.busy += 1
            self.touch()
            try:
                self.phase = f"export:{language}"
                model = self._load(language)
                if not getattr(model, "has_voice_cloning", True):
                    raise RuntimeError("voice cloning weights are not available")
                state = model.get_state_for_audio_prompt(wav, truncate=True)
                dest.parent.mkdir(parents=True, exist_ok=True)
                export_model_state(state, dest)
                self.states[(str(dest), language)] = state
                self.phase = "ready"
                return {"ok": True, "bytes": dest.stat().st_size, "language": language}
            finally:
                self.busy -= 1
                self.touch()

    def synthesize(self, state_path: Path, text: str, language: str) -> bytes:
        state_path = self._inside(state_path)
        if language not in LANGUAGES:
            raise ValueError(language)
        text = (text or "").strip()
        if not text:
            raise ValueError("empty text")
        with self.lock:
            self.busy += 1
            self.touch()
            try:
                self.phase = f"speak:{language}"
                model = self._load(language)
                key = (str(state_path), state_path.stat().st_mtime_ns, language)
                state = self.states.get(key)
                if state is None:
                    state = model.get_state_for_audio_prompt(state_path)
                    self.states[key] = state
                audio = model.generate_audio(state, text, copy_state=True)
                self.phase = "ready"
                return _tensor_wav(audio, int(model.sample_rate))
            finally:
                self.busy -= 1
                self.touch()

    def unload(self) -> dict:
        with self.lock:
            self.models.clear()
            self.states.clear()
            self.phase = "unloaded"
        import gc

        gc.collect()
        return self.status()


def _read_audio(path: Path):
    import numpy as np

    suffix = path.suffix.lower()
    if suffix == ".wav":
        import wave

        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            rate = handle.getframerate()
            frames = handle.readframes(handle.getnframes())
        if width != 2:
            raise ValueError("wav sample width is not 16-bit")
        samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
        if channels > 1:
            samples = samples.reshape(-1, channels).mean(axis=1)
        return samples, rate
    import miniaudio

    decoded = miniaudio.decode_file(str(path), output_format=miniaudio.SampleFormat.FLOAT32)
    samples = np.asarray(decoded.samples, dtype=np.float32)
    if decoded.nchannels > 1:
        samples = samples.reshape(-1, decoded.nchannels).mean(axis=1)
    return samples, int(decoded.sample_rate)


def _write_wav(path: Path, samples, rate: int) -> None:
    import wave

    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(rate))
        handle.writeframes(pcm)


def _tensor_wav(audio, sample_rate: int) -> bytes:
    import io
    import wave

    import numpy as np

    array = audio.detach().cpu().float().numpy().reshape(-1)
    pcm = (np.clip(array, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)
    return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        log.info("%s - %s", self.address_string(), fmt % args)

    def _authorized(self) -> bool:
        import hmac

        expected = self.server.token.encode("utf-8")
        given = (self.headers.get("X-TextSpeak-Token") or "").encode("utf-8")
        return hmac.compare_digest(expected, given)

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, code: str, detail: str, status: int = 400) -> None:
        log.error("%s %s", code, detail)
        self._json({"ok": False, "error": {"code": code, "detail": detail[:500]}}, status)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(data, dict):
            raise ValueError("json object required")
        return data

    def do_GET(self) -> None:  # noqa: N802
        service = self.server.service
        service.touch()
        if self.path.split("?", 1)[0] == "/health":
            self._json({"ok": True, "service": "textspeak-pocket"})
            return
        if not self._authorized():
            self._error("clone-service-down", "forbidden", 403)
            return
        if self.path.split("?", 1)[0] == "/status":
            self._json(service.status())
            return
        self._error("clone-synthesis", "not found", 404)

    def do_POST(self) -> None:  # noqa: N802
        service = self.server.service
        service.touch()
        if not self._authorized():
            self._error("clone-service-down", "forbidden", 403)
            return
        path = self.path.split("?", 1)[0]
        try:
            payload = self._body()
            if path == "/v1/ensure":
                self._json(service.ensure(list(payload.get("languages") or [])))
            elif path == "/v1/decode":
                self._json(service.decode(Path(payload["source"]), Path(payload["dest"])))
            elif path == "/v1/export":
                self._json(service.export(Path(payload["wav"]), Path(payload["dest"]), str(payload["language"])))
            elif path == "/v1/synthesize":
                wav = service.synthesize(Path(payload["state"]), str(payload.get("text") or ""), str(payload["language"]))
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(wav)))
                self.end_headers()
                self.wfile.write(wav)
            elif path == "/v1/unload":
                self._json(service.unload())
            elif path == "/v1/shutdown":
                self._json({"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self._error("clone-synthesis", "not found", 404)
        except PermissionError as exc:
            self._error("clone-profile-corrupt", str(exc), 403)
        except FileNotFoundError as exc:
            self._error("clone-state-missing", str(exc), 404)
        except Exception as exc:  # noqa: BLE001
            code = "clone-model-download" if path == "/v1/ensure" else "clone-synthesis"
            message = f"{type(exc).__name__}: {exc}"
            lowered = message.lower()
            if any(word in lowered for word in ("gated", "restricted", "authorized list", "without voice cloning")):
                code = "clone-model-gated"
            elif "consent" in lowered or "401" in lowered or "403" in lowered:
                code = "clone-model-download"
            if any(word in lowered for word in ("corrupt", "safetensor", "invalid json")):
                _clear_incomplete(service.model_dir)
            log.error("%s\n%s", message, traceback.format_exc())
            self._error(code, message, 500)


def _write_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".part")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(path)


def _preload_runtime() -> None:
    """Import PyTorch on the main thread.

    Loading the Windows CPU wheel from an HTTP worker thread can abort the
    process before Python can report an error.
    """
    import torch
    from pocket_tts import TTSModel, export_model_state

    log.info(
        "runtime ready torch=%s cuda=%s export=%s load=%s",
        torch.__version__,
        bool(torch.cuda.is_available()),
        callable(export_model_state),
        callable(TTSModel.load_model),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="TextSpeak Pro Pocket TTS service")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--allowed-root", required=True)
    parser.add_argument("--log", default="")
    parser.add_argument("--idle-seconds", type=float, default=600)
    args = parser.parse_args()
    logging.basicConfig(
        filename=args.log or None,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if args.log:
        faulthandler.enable(open(args.log, "a", encoding="utf-8"))
    model_dir = Path(args.model_dir)
    os.environ["HF_HOME"] = str(model_dir / "huggingface")
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(model_dir / "huggingface" / "hub")
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    _use_existing_hf_token()
    try:
        _preload_runtime()
    except Exception:
        log.exception("Pocket runtime failed to import")
        return 1
    service = PocketService(model_dir, Path(args.allowed_root), args.idle_seconds)
    service._versions()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.token = args.token
    server.service = service
    host, port = server.server_address
    if host != "127.0.0.1":
        log.error("refusing non-loopback bind %s", host)
        return 2
    _write_state(Path(args.state_file), {"pid": os.getpid(), "port": port, "token": args.token})
    log.info("listening on 127.0.0.1:%s", port)

    def idle() -> None:
        while True:
            time.sleep(5)
            if service.idle_expired():
                log.info("idle timeout, exiting")
                threading.Thread(target=server.shutdown, daemon=True).start()
                return

    threading.Thread(target=idle, daemon=True).start()
    try:
        server.serve_forever()
    finally:
        server.server_close()
        try:
            Path(args.state_file).unlink()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
