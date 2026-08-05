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
from app.main_window import MainWindow
from app.settings import Settings


def _acquire_single_instance_lock() -> QLockFile | None:
    """Prevent a second app instance - surface the first window instead."""
    lock_path = app_paths.user_data_dir() / "textspeak.lock"
    lock = QLockFile(str(lock_path))
    lock.setStaleLockTime(0)
    if lock.tryLock(100):
        return lock
    return None


def main() -> int:
    logging_setup.install()

    QApplication.setOrganizationName(APP_ORG_DIR)
    QApplication.setOrganizationDomain("jojolapin.com")
    QApplication.setApplicationName(APP_NAME)
    QApplication.setApplicationDisplayName(APP_NAME)
    QApplication.setApplicationVersion(APP_VERSION)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    # Single-instance lock (best-effort; a missing lock just means second-instance will open too)
    lock = _acquire_single_instance_lock()
    if lock is None:
        # Another instance is running; nothing we can do to focus it without IPC,
        # so just exit cleanly.
        logging.getLogger("textspeak").info("%s is already running; exiting.", APP_NAME)
        return 0

    settings = Settings()
    bridge = Bridge(settings=settings)
    window = MainWindow(settings=settings, bridge=bridge)

    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
