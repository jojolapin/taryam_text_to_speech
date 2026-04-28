"""Rotating log configuration for TextSpeak Pro.

Creates ``<user_data>/logs/textspeak-YYYYMMDD.log`` and keeps 7 days.

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from . import APP_NAME
from . import paths as app_paths


_INSTALLED = False


def install() -> Path:
    """Install the logging configuration. Returns the path to today's log file."""
    global _INSTALLED
    log_dir = app_paths.logs_dir()
    log_file = log_dir / "textspeak.log"

    if _INSTALLED:
        return log_file

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Rotating file handler - daily rotation, keep 7 days
    try:
        fh = logging.handlers.TimedRotatingFileHandler(
            filename=str(log_file),
            when="midnight", interval=1, backupCount=7, encoding="utf-8",
        )
        fh.setFormatter(fmt)
        fh.setLevel(logging.INFO)
        root.addHandler(fh)
    except OSError:
        pass

    # Also stream to stderr when running from a console
    if sys.stderr and not getattr(sys, "frozen", False):
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        sh.setLevel(logging.INFO)
        root.addHandler(sh)

    logging.getLogger("textspeak").info("%s logging initialised at %s", APP_NAME, log_file)
    _INSTALLED = True
    return log_file
