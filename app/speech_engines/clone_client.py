"""Localhost client for the isolated Pocket TTS process.

This module does not import PyTorch or Pocket TTS. The other interpreter
lives in ``clone_runtime/.venv``.

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from ..paths import logs_dir, user_data_dir
from .clone_errors import CloneError
from .clone_profiles import pocket_model_dir

_HOST = "127.0.0.1"
_PROCESS = None


def clone_home() -> Path | None:
    override = os.environ.get("TEXTSPEAK_CLONE_HOME", "").strip()
    candidates = []
    if override:
        candidates.append(Path(override))
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "clone_runtime")
    else:
        candidates.append(Path(__file__).resolve().parents[2] / "clone_runtime")
    for candidate in candidates:
        if (candidate / "service.py").is_file():
            return candidate
    return None


def clone_python() -> Path | None:
    override = os.environ.get("TEXTSPEAK_CLONE_PYTHON", "").strip()
    if override and Path(override).is_file():
        return Path(override)
    home = clone_home()
    if home is None:
        return None
    for relative in (Path(".venv") / "Scripts" / "python.exe", Path(".venv") / "bin" / "python"):
        candidate = home / relative
        if candidate.is_file():
            return candidate
    return None


def runtime_installed() -> bool:
    return clone_python() is not None and clone_home() is not None


def models_ready() -> bool:
    marker = pocket_model_dir() / "ready.json"
    if not marker.is_file():
        return False
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    languages = data.get("languages") if isinstance(data, dict) else None
    return (
        isinstance(languages, dict)
        and "english" in languages
        and "french_24l" in languages
        and data.get("voice_cloning") is True
    )


def _state_path() -> Path:
    path = user_data_dir() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path / "clone-service.json"


def _read_state() -> dict | None:
    path = _state_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _stop_pid(pid: int) -> None:
    if pid <= 0 or not _pid_alive(pid):
        return
    if sys.platform.startswith("win"):
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
        return
    try:
        os.kill(pid, 15)
    except OSError:
        return


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform.startswith("win"):
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel.OpenProcess(0x1000, False, wintypes.DWORD(pid))
        if not handle:
            return False
        kernel.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def service_status() -> dict | None:
    """Read the local status file. This does not start the service."""
    return _read_state()


class CloneClient:
    """Talks to one localhost Pocket process."""

    def __init__(self):
        self._base = ""
        self._token = ""

    def connect_existing(self) -> bool:
        state = _read_state()
        if not state or not _pid_alive(int(state.get("pid") or 0)):
            return False
        self._base = f"http://{_HOST}:{int(state['port'])}"
        self._token = str(state.get("token") or "")
        try:
            payload = self._request("GET", "/health", timeout=2)
        except CloneError:
            return False
        return bool(payload.get("ok"))

    def ensure_running(self) -> None:
        if self.connect_existing():
            return
        stale = _read_state()
        if stale:
            _stop_pid(int(stale.get("pid") or 0))
        python = clone_python()
        home = clone_home()
        if python is None or home is None:
            raise CloneError("clone-runtime-missing", "")
        token = secrets.token_hex(16)
        state = _state_path()
        if state.exists():
            try:
                state.unlink()
            except OSError:
                pass
        log_path = logs_dir() / "clone-service.log"
        creation = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
        try:
            process = subprocess.Popen(
                [
                    str(python),
                    str(home / "service.py"),
                    "--port", "0",
                    "--token", token,
                    "--model-dir", str(pocket_model_dir()),
                    "--state-file", str(state),
                    "--allowed-root", str(user_data_dir()),
                    "--log", str(log_path),
                    "--idle-seconds", os.environ.get("TEXTSPEAK_CLONE_IDLE", "600"),
                ],
                cwd=str(home),
                creationflags=creation,
            )
        except OSError as exc:
            raise CloneError("clone-service-start", str(exc)) from exc
        global _PROCESS
        _PROCESS = process
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise CloneError("clone-service-start", f"exit {process.returncode}")
            if self.connect_existing():
                return
            time.sleep(0.15)
        raise CloneError("clone-service-start", "timeout")

    def ensure_models(self) -> dict:
        self.ensure_running()
        return self._request(
            "POST",
            "/v1/ensure",
            {"languages": ["english", "french_24l"]},
            timeout=900,
        )

    def decode(self, source: Path, dest: Path) -> None:
        self.ensure_running()
        self._request(
            "POST",
            "/v1/decode",
            {"source": str(source), "dest": str(dest)},
            timeout=120,
        )

    def export_state(self, wav: Path, dest: Path, language: str) -> None:
        self.ensure_running()
        self._request(
            "POST",
            "/v1/export",
            {"wav": str(wav), "dest": str(dest), "language": language},
            timeout=600,
        )

    def synthesize_wav(self, state: Path, text: str, language: str) -> bytes:
        self.ensure_running()
        return self._request(
            "POST",
            "/v1/synthesize",
            {"state": str(state), "text": text, "language": language},
            timeout=180,
            raw=True,
        )

    def unload(self) -> None:
        if not self.connect_existing():
            return
        self._request("POST", "/v1/unload", {}, timeout=30)

    def shutdown(self) -> None:
        if not self.connect_existing():
            return
        try:
            self._request("POST", "/v1/shutdown", {}, timeout=5)
        except CloneError:
            pass
        self._base = ""

    def _request(self, method: str, path: str, payload: dict | None = None, timeout: float = 30, raw: bool = False):
        if not self._base:
            raise CloneError("clone-service-down", "")
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self._base + path,
            data=data,
            method=method,
            headers={
                "X-TextSpeak-Token": self._token,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
                content = response.headers.get("Content-Type", "")
        except TimeoutError as exc:
            raise CloneError("clone-timeout", path) from exc
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            code, message = _error_body(detail)
            raise CloneError(code or "clone-synthesis", message or detail[:400]) from exc
        except urllib.error.URLError as exc:
            raise CloneError("clone-service-down", str(exc.reason)) from exc
        except OSError as exc:
            raise CloneError("clone-service-down", str(exc)) from exc
        if raw or content.startswith("audio/"):
            if not body:
                raise CloneError("clone-synthesis", "empty audio")
            return body
        try:
            parsed = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise CloneError("clone-synthesis", "invalid response") from exc
        if not parsed.get("ok", True):
            error = parsed.get("error") or {}
            raise CloneError(str(error.get("code") or "clone-synthesis"), str(error.get("detail") or ""))
        return parsed


def _error_body(raw: str) -> tuple[str, str]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return "", raw
    error = parsed.get("error") if isinstance(parsed, dict) else None
    if isinstance(error, dict):
        return str(error.get("code") or ""), str(error.get("detail") or "")
    return "", raw


def poll_download_bytes() -> int:
    """Read download progress from a service that is already running."""
    client = CloneClient()
    if not client.connect_existing():
        return 0
    try:
        payload = client._request("GET", "/status", timeout=2)
    except CloneError:
        return 0
    return int(payload.get("download_bytes") or 0)


def shutdown_if_running() -> None:
    try:
        CloneClient().shutdown()
    except Exception:
        return
