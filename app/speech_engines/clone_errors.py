"""Errors from the cloning service that the main application can show.

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations


class CloneError(RuntimeError):
    """A cloning failure with a stable code for translation."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail or ""
        super().__init__(self.detail or code)
