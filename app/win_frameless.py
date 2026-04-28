"""Windows-only style tweak so a Qt frameless window participates in DWM snap.

Qt's ``FramelessWindowHint`` strips the ``WS_THICKFRAME`` / min-max style bits
that DWM uses to decide whether the window is snappable (Win+Arrow, drag-to-edge
zones). We OR them back onto the HWND once, after the window is shown.

We intentionally do NOT subclass the WndProc or override ``WM_NCCALCSIZE`` /
``WM_NCHITTEST`` here. The chrome (title bar + min/max/close buttons) lives
inside ``QWebEngineView``'s child Chromium HWND, which consumes mouse input
before our parent window can hit-test it. Returning ``HTMAXBUTTON`` from a
parent-level ``WM_NCHITTEST`` therefore breaks the HTML buttons without giving
us the maximize-hover Snap Layouts flyout. A proper hover flyout requires a
native overlay widget for the caption area; that is out of scope here.

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

log = logging.getLogger("textspeak.win_frameless")

# ctypes.wintypes does not expose LONG_PTR. Pointer-sized signed integer is
# what GetWindowLongPtrW / SetWindowLongPtrW return.
LONG_PTR = ctypes.c_ssize_t

GWL_STYLE = -16
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_THICKFRAME = 0x00040000
WS_SYSMENU = 0x00080000

SWP_FRAMECHANGED = 0x0020
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004


_WS_FLAG_NAMES = {
    0x80000000: "WS_POPUP",
    0x40000000: "WS_CHILD",
    0x10000000: "WS_VISIBLE",
    0x08000000: "WS_DISABLED",
    0x04000000: "WS_CLIPSIBLINGS",
    0x02000000: "WS_CLIPCHILDREN",
    0x01000000: "WS_MAXIMIZE",
    0x00C00000: "WS_CAPTION",
    0x00800000: "WS_BORDER",
    0x00400000: "WS_DLGFRAME",
    0x00200000: "WS_VSCROLL",
    0x00100000: "WS_HSCROLL",
    0x00080000: "WS_SYSMENU",
    0x00040000: "WS_THICKFRAME",
    0x00020000: "WS_MINIMIZEBOX",
    0x00010000: "WS_MAXIMIZEBOX",
}


def _decode_style(style: int) -> str:
    parts: list[str] = []
    for bit, name in _WS_FLAG_NAMES.items():
        if (style & bit) == bit and bit != 0:
            parts.append(name)
    return " | ".join(parts) if parts else "(none)"


def apply_snap_friendly_window_style(hwnd: int) -> None:
    """OR back the Win32 style bits ``FramelessWindowHint`` removed.

    Logs the before/after style at INFO level so we can verify Qt is not
    immediately stripping our changes back out.
    """
    if not sys.platform.startswith("win") or not hwnd:
        return
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongPtrW.restype = LONG_PTR
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, LONG_PTR]
        user32.SetWindowLongPtrW.restype = LONG_PTR
        user32.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_uint,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL

        before = int(user32.GetWindowLongPtrW(hwnd, GWL_STYLE))
        log.info(
            "snap-style BEFORE hwnd=0x%X style=0x%08X [%s]",
            int(hwnd), before & 0xFFFFFFFF, _decode_style(before),
        )

        target = before | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_THICKFRAME | WS_SYSMENU
        ctypes.set_last_error(0)
        prev = int(user32.SetWindowLongPtrW(hwnd, GWL_STYLE, target))
        err_set = ctypes.get_last_error()

        ctypes.set_last_error(0)
        ok = bool(user32.SetWindowPos(
            hwnd, None, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
        ))
        err_swp = ctypes.get_last_error()

        after = int(user32.GetWindowLongPtrW(hwnd, GWL_STYLE))
        log.info(
            "snap-style AFTER  hwnd=0x%X style=0x%08X [%s] "
            "(SetWindowLongPtr prev=0x%X err=%d, SetWindowPos ok=%s err=%d)",
            int(hwnd), after & 0xFFFFFFFF, _decode_style(after),
            prev & 0xFFFFFFFF, err_set, ok, err_swp,
        )

        if (after & WS_THICKFRAME) != WS_THICKFRAME:
            log.warning(
                "snap-style: WS_THICKFRAME did NOT stick — Qt is overriding our style. "
                "DWM snap will likely refuse to recognise the window."
            )
    except Exception:  # noqa: BLE001
        log.exception("apply_snap_friendly_window_style failed")


def reapply_snap_style_if_lost(hwnd: int) -> bool:
    """Re-OR the snap style bits if they have been stripped. Returns True if any
    change was made. Cheap to call — used as a defensive hook from focus events.
    """
    if not sys.platform.startswith("win") or not hwnd:
        return False
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongPtrW.restype = LONG_PTR
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, LONG_PTR]
        user32.SetWindowLongPtrW.restype = LONG_PTR
        user32.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_uint,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL

        cur = int(user32.GetWindowLongPtrW(hwnd, GWL_STYLE))
        needed = WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_THICKFRAME | WS_SYSMENU
        if (cur & needed) == needed:
            return False
        user32.SetWindowLongPtrW(hwnd, GWL_STYLE, cur | needed)
        user32.SetWindowPos(
            hwnd, None, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
        )
        log.info(
            "snap-style RE-APPLIED hwnd=0x%X (was missing 0x%X)",
            int(hwnd), needed & ~cur & 0xFFFFFFFF,
        )
        return True
    except Exception:  # noqa: BLE001
        log.exception("reapply_snap_style_if_lost failed")
        return False
