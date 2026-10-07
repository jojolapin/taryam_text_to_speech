"""TextSpeak Pro - desktop app entry point.

(C) 2026 JojoLapin Inc. All rights reserved.
TextSpeak Pro(TM) - offline neural TTS powered by Piper.
"""
from __future__ import annotations

import json
import logging
import os
import sys


class _NullWriter:
    """Swallow writes when there is no console (windowed PyInstaller build).

    In a ``console=False`` frozen app both ``sys.stdout`` and ``sys.stderr`` are
    ``None``; any stray ``print()`` / ``.write()`` would raise ``AttributeError``
    and abort startup. Substituting a no-op writer keeps the app resilient.
    """

    def write(self, *_a, **_k):
        return 0

    def flush(self):
        pass


if sys.stdout is None:
    sys.stdout = _NullWriter()
if sys.stderr is None:
    sys.stderr = _NullWriter()

# High-DPI on Windows + Chromium sandbox friendliness
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                      os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "") +
                      " --disable-features=UseEcoQoSForBackgroundProcess")

from PySide6.QtCore import QLockFile, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from app import APP_NAME, APP_ORG_DIR, APP_VERSION
from app import logging_setup
from app import paths as app_paths
from app.bridge import Bridge
from app.native_window import MainWindow
from app.settings import Settings


def _acquire_single_instance_lock() -> QLockFile | None:
    """Prevent a second app instance. The caller reveals the first window."""
    lock_path = app_paths.user_data_dir() / "textspeak.lock"
    lock = QLockFile(str(lock_path))
    lock.setStaleLockTime(0)
    if lock.tryLock(100):
        return lock
    return None


def _reveal_running_instance() -> bool:
    """Bring the already-open TextSpeak Pro window to the front.

    ``run.bat`` starts ``pythonw.exe``, so a second launch has no console.
    Returning immediately left the prompt looking like nothing happened.
    """
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.EnumWindows.argtypes = [enum_proc, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.AttachThreadInput.restype = wintypes.BOOL
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    found: dict[str, int] = {"hwnd": 0}

    def _enum(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        if buffer.value == APP_NAME:
            found["hwnd"] = int(hwnd)
            return False
        return True

    user32.EnumWindows(enum_proc(_enum), 0)
    hwnd = found["hwnd"]
    if not hwnd:
        return False

    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    foreground = user32.GetForegroundWindow()
    current_thread = kernel32.GetCurrentThreadId()
    foreground_thread = user32.GetWindowThreadProcessId(foreground, None)
    attached = False
    if foreground_thread and foreground_thread != current_thread:
        attached = bool(user32.AttachThreadInput(current_thread, foreground_thread, True))
    user32.BringWindowToTop(hwnd)
    raised = bool(user32.SetForegroundWindow(hwnd))
    if attached:
        user32.AttachThreadInput(current_thread, foreground_thread, False)
    return raised


def _run_qa_audio() -> int:
    """Synthesize with the real engines and exit. No editor window."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--qa-audio", action="store_true")
    parser.add_argument("--qa-download", action="store_true")
    parser.add_argument("--output", required=True)
    parser.add_argument("--data-dir")
    args = parser.parse_args()
    if args.data_dir:
        os.environ["TEXTSPEAK_DATA_DIR"] = os.path.abspath(args.data_dir)
    logging_setup.install()
    QApplication.setOrganizationName(APP_ORG_DIR)
    QApplication.setOrganizationDomain("jojolapin.com")
    QApplication.setApplicationName(APP_NAME)
    QApplication.setApplicationDisplayName(APP_NAME)
    QApplication.setApplicationVersion(APP_VERSION)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    if args.qa_download:
        from app.qa_audio import run_download

        return run_download(args.output)
    from app.qa_audio import run

    return run(app, args.output)


def main() -> int:
    if "--qa-audio" in sys.argv or "--qa-download" in sys.argv:
        return _run_qa_audio()
    if "--self-test" in sys.argv or "--self-test-migration" in sys.argv:
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--self-test", action="store_true")
        parser.add_argument("--self-test-migration", action="store_true")
        parser.add_argument("--data-dir", required=True)
        parser.add_argument("--voice-dir")
        args = parser.parse_args()
        os.environ["TEXTSPEAK_DATA_DIR"] = os.path.abspath(args.data_dir)
    logging_setup.install()

    QApplication.setOrganizationName(APP_ORG_DIR)
    QApplication.setOrganizationDomain("jojolapin.com")
    QApplication.setApplicationName(APP_NAME)
    QApplication.setApplicationDisplayName(APP_NAME)
    QApplication.setApplicationVersion(APP_VERSION)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # Consistent palette support, including dark mode.
    app.setQuitOnLastWindowClosed(True)

    if "--self-test-migration" in sys.argv:
        from app.qa_smoke import verify_migration
        settings = Settings()
        return verify_migration(app, settings, Bridge(settings=settings), args.data_dir)
    if "--self-test" in sys.argv:
        from app.qa_smoke import run
        settings = Settings()
        return run(app, settings, Bridge(settings=settings), args.data_dir, args.voice_dir)

    # Single-instance lock (best-effort; a missing lock just means second-instance will open too)
    lock = _acquire_single_instance_lock()
    if lock is None:
        revealed = _reveal_running_instance()
        logging.getLogger("textspeak").info(
            "%s is already running; %s.",
            APP_NAME,
            "brought its window forward" if revealed else "could not find its window",
        )
        return 0

    settings = Settings()
    bridge = Bridge(settings=settings)
    window = MainWindow(settings=settings, bridge=bridge)

    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
