"""Windows 11 Mica backdrop + rounded window corners.

Silent no-op on non-Windows or older Windows builds. The Mica effect needs
Windows 11 22H2 (build 22621) or later; rounded corners need 21H2+.

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


log = logging.getLogger("textspeak.mica")


_DWMWA_SYSTEMBACKDROP_TYPE = 38
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20

# Backdrop values
_DWMSBT_MAINWINDOW = 2      # Mica
_DWMSBT_TRANSIENTWINDOW = 3 # Acrylic-like
_DWMSBT_TABBEDWINDOW = 4    # Mica Alt

# Corner preference values
_DWMWCP_DEFAULT = 0
_DWMWCP_DONOTROUND = 1
_DWMWCP_ROUND = 2
_DWMWCP_ROUNDSMALL = 3


def apply_mica(widget: "QWidget", *, dark: bool = True) -> bool:
    """Apply Mica backdrop + rounded corners. Returns True if applied."""
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return False
    try:
        hwnd = int(widget.winId())
    except Exception as e:  # noqa: BLE001
        log.debug("No HWND available: %s", e)
        return False

    dwmapi = ctypes.WinDLL("dwmapi")
    dwmapi.DwmSetWindowAttribute.argtypes = [
        wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD
    ]

    def _set(attr: int, value: int) -> int:
        v = ctypes.c_int(value)
        return int(dwmapi.DwmSetWindowAttribute(
            hwnd, ctypes.c_int(attr), ctypes.byref(v), ctypes.sizeof(v)
        ))

    applied = False

    # Dark-mode title bar first (even though we're frameless, affects shadows)
    try:
        _set(_DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0)
    except Exception as e:  # noqa: BLE001
        log.debug("DWMWA_USE_IMMERSIVE_DARK_MODE failed: %s", e)

    # Mica backdrop (Win11 22H2+)
    try:
        res = _set(_DWMWA_SYSTEMBACKDROP_TYPE, _DWMSBT_MAINWINDOW)
        applied = res == 0
        if not applied:
            log.debug("Mica set returned HRESULT 0x%X", res)
    except Exception as e:  # noqa: BLE001
        log.debug("Mica attribute not supported: %s", e)

    # Rounded corners
    try:
        _set(_DWMWA_WINDOW_CORNER_PREFERENCE, _DWMWCP_ROUND)
    except Exception as e:  # noqa: BLE001
        log.debug("Rounded corners not supported: %s", e)

    return applied


def set_dark_titlebar(widget: "QWidget", dark: bool) -> None:
    """Toggle the immersive dark-mode titlebar (also affects shadow color)."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        from ctypes import wintypes
        dwmapi = ctypes.WinDLL("dwmapi")
        dwmapi.DwmSetWindowAttribute.argtypes = [
            wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD
        ]
        hwnd = int(widget.winId())
        v = ctypes.c_int(1 if dark else 0)
        dwmapi.DwmSetWindowAttribute(
            hwnd, ctypes.c_int(_DWMWA_USE_IMMERSIVE_DARK_MODE),
            ctypes.byref(v), ctypes.sizeof(v)
        )
    except Exception as e:  # noqa: BLE001
        log.debug("set_dark_titlebar failed: %s", e)
