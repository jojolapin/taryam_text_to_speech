"""Main window: frameless QMainWindow wrapping a QWebEngineView.

The window itself is frameless and translucent so Mica can show through on
Windows 11. The title bar, menus, and all UI chrome are rendered *inside*
the webview (HTML/CSS). The Python side only provides:

- frameless window resize + drag (via JS); on Windows, ``WS_THICKFRAME``
  is restored at show time so Win+Arrow / drag-to-edge participate in DWM snap
- system tray (native)
- single-instance lock
- DnD files onto the window
- native Save/Open dialogs
- Mica backdrop

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import json
import logging
import sys
import urllib.parse
from pathlib import Path

from PySide6.QtCore import QEvent, QFileInfo, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QGuiApplication, QIcon
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow, QMenu, QSystemTrayIcon

from . import APP_COPYRIGHT, APP_NAME
from . import i18n, mica
from . import paths as app_paths
from .bridge import Bridge
from .settings import Settings


log = logging.getLogger("textspeak.window")


def _icon() -> QIcon:
    """Best-effort load of the app icon from any of the known locations."""
    candidates = [
        app_paths.resources_dir() / "icon.ico",
        app_paths.resources_dir() / "icon.png",
        app_paths.bundled_resource("app.ico"),
    ]
    for p in candidates:
        if p.exists():
            return QIcon(str(p))
    return QIcon()


class MainWindow(QMainWindow):
    """Frameless main window with an embedded QWebEngineView."""

    dropReceived = Signal(str)

    def __init__(self, settings: Settings, bridge: Bridge) -> None:
        super().__init__()
        self.settings = settings
        self.bridge = bridge

        self.setWindowTitle(APP_NAME)
        icon = _icon()
        if not icon.isNull():
            self.setWindowIcon(icon)

        # Frameless window. We deliberately do NOT enable translucency up front:
        # if Mica is unavailable (older Windows, VMs, remote desktop, weak GPU)
        # a translucent frameless window that never gets composited produces a
        # nasty per-frame flicker while moving/resizing. We only flip on
        # translucency AFTER apply_mica() confirms the backdrop took effect
        # (see showEvent). On other platforms we stay fully opaque.
        # System menu + min/max hints keep Win32 caption affordances for DWM;
        # chrome stays custom inside the webview. Min width <= ~500 epx is required
        # for Win11 snap zones on typical layouts (see MS snap-layout guidance).
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinMaxButtonsHint
        )
        self.setMinimumSize(QSize(500, 480))
        self.resize(1200, 820)
        self.setAcceptDrops(True)
        self._mica_applied: bool = False
        self._mica_attempted: bool = False
        self._win_snap_style_applied: bool = False

        # Web view
        self.view = QWebEngineView(self)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.setCentralWidget(self.view)

        page_settings = self.view.settings()
        page_settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        page_settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        page_settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)
        page_settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        page_settings.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
        page_settings.setAttribute(QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, False)

        # Channel
        self.channel = QWebChannel(self)
        self.channel.registerObject("bridge", bridge)
        self.view.page().setWebChannel(self.channel)

        # Wire bridge -> window controls
        bridge.minimizeRequested.connect(self.showMinimized)
        bridge.toggleMaximizeRequested.connect(self._toggle_maximize)
        bridge.closeRequested.connect(self.close)
        bridge.quitRequested.connect(lambda: QApplication.instance().quit())
        bridge.beginDragRequested.connect(self._begin_drag)
        bridge.beginResizeRequested.connect(self._begin_resize)

        # Theme signal hook into native titlebar dark mode
        bridge.themeChanged.connect(self._on_theme_changed)

        # Load UI. Once the page is ready we can safely flip the "no-mica"
        # CSS class on <html> - before that, documentElement may not exist
        # yet and runJavaScript would be a no-op.
        self.view.loadFinished.connect(self._on_view_load_finished)
        ui_index = app_paths.ui_dir() / "index.html"
        self.view.load(QUrl.fromLocalFile(str(ui_index)))

        # Restore geometry
        geom, state = settings.load_window_geometry()
        if geom:
            self.restoreGeometry(geom)
        if state:
            self.restoreState(state)

        # Tray
        self._tray: QSystemTrayIcon | None = None
        self._install_tray()

    # ---- events ----

    def _apply_mica_once(self) -> None:
        """Apply Mica one time on first show. If it succeeds, enable the
        translucent background so the backdrop shows through. If it fails,
        leave the window opaque: frameless + translucent-without-Mica is
        exactly what causes the visible 'trembling' on older hardware.
        """
        if self._mica_attempted:
            return
        self._mica_attempted = True
        theme = self.settings.get("theme", "system")
        dark = theme == "dark" or (theme == "system" and self._system_dark())
        applied = mica.apply_mica(self, dark=dark)
        self._mica_applied = bool(applied)
        if applied:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
            # Tell the webview it's OK to draw with transparency
            try:
                from PySide6.QtGui import QColor
                self.view.page().setBackgroundColor(QColor(0, 0, 0, 0))
            except Exception:  # noqa: BLE001
                log.debug("setBackgroundColor transparent failed", exc_info=True)
        # Let the webview know so CSS can adapt (heavy blur/animations on
        # plain solid backgrounds look jittery on weak GPUs).
        self._broadcast_backdrop(self._mica_applied)

    def _broadcast_backdrop(self, mica_on: bool) -> None:
        """Inject a data attribute + CSS class on <html> once the page is
        ready, so the UI can tone down blurs and animations when we don't
        have a compositor backdrop to lean on. Safe to call before or after
        loadFinished: we cache the flag and replay it from the load handler.
        """
        self._pending_backdrop = bool(mica_on)
        flag = "true" if mica_on else "false"
        js = (
            "(function(){"
            "  var d = document.documentElement;"
            "  if (!d) return;"
            "  d.dataset.mica = '%s';"
            "  d.classList.toggle('no-mica', %s);"
            "})();"
        ) % (flag, "false" if mica_on else "true")
        try:
            self.view.page().runJavaScript(js)
        except Exception:  # noqa: BLE001
            log.debug("runJavaScript backdrop flag failed", exc_info=True)

    def _on_view_load_finished(self, ok: bool) -> None:
        if not ok:
            return
        if hasattr(self, "_pending_backdrop"):
            self._broadcast_backdrop(self._pending_backdrop)

    def showEvent(self, ev: QEvent) -> None:  # noqa: N802
        super().showEvent(ev)
        self._apply_mica_once()
        if sys.platform.startswith("win") and not self._win_snap_style_applied:
            self._win_snap_style_applied = True
            try:
                from . import win_frameless as wf

                wf.apply_snap_friendly_window_style(int(self.winId()))
            except Exception:  # noqa: BLE001
                log.debug("Windows snap-friendly style failed", exc_info=True)

    def changeEvent(self, ev: QEvent) -> None:  # noqa: N802
        super().changeEvent(ev)
        # We deliberately do NOT re-apply Mica on WindowStateChange: the DWM
        # attribute is sticky across minimize/maximize on Win11 22H2+, and
        # calling DwmSetWindowAttribute repeatedly during state transitions
        # was the second source of the "trembling" the user reported.

        # Defensive: if Qt re-applied its FramelessWindowHint style after a
        # state change and stripped WS_THICKFRAME, put it back. We log when
        # this fires so we can tell whether Qt is fighting us.
        # ``changeEvent`` can fire from inside ``__init__`` (e.g. setWindowTitle
        # raises WindowTitleChange before our attributes exist) so guard with
        # getattr instead of assuming the attribute is set.
        if sys.platform.startswith("win") and getattr(self, "_win_snap_style_applied", False):
            if ev.type() in (
                QEvent.Type.WindowStateChange,
                QEvent.Type.ActivationChange,
            ):
                try:
                    from . import win_frameless as wf

                    wf.reapply_snap_style_if_lost(int(self.winId()))
                except Exception:  # noqa: BLE001
                    log.debug("reapply_snap_style_if_lost failed", exc_info=True)

    def closeEvent(self, ev: QEvent) -> None:  # noqa: N802
        self.settings.save_window_geometry(bytes(self.saveGeometry()), bytes(self.saveState()))
        super().closeEvent(ev)

    # ---- Drag & drop ----

    def dragEnterEvent(self, ev) -> None:  # noqa: N802
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev) -> None:  # noqa: N802
        urls = ev.mimeData().urls()
        if not urls:
            return
        paths = [u.toLocalFile() for u in urls if u.isLocalFile()]
        paths = [p for p in paths if p]
        if paths:
            self.bridge.fileDropped.emit(json.dumps(paths))
            ev.acceptProposedAction()

    # ---- helpers ----

    def _toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _begin_drag(self) -> None:
        wh = self.windowHandle()
        if wh is not None:
            try:
                wh.startSystemMove()
            except Exception as e:  # noqa: BLE001
                log.debug("startSystemMove failed: %s", e)

    def _begin_resize(self, edges: int) -> None:
        wh = self.windowHandle()
        if wh is None:
            return
        try:
            wh.startSystemResize(Qt.Edges(int(edges)))
        except Exception as e:  # noqa: BLE001
            log.debug("startSystemResize failed: %s", e)

    def _system_dark(self) -> bool:
        try:
            hints = QGuiApplication.styleHints()
            return hints.colorScheme() == Qt.ColorScheme.Dark
        except Exception:  # noqa: BLE001
            return True

    def _on_theme_changed(self, scheme: str) -> None:
        dark = scheme == "dark" or (scheme == "system" and self._system_dark())
        mica.set_dark_titlebar(self, dark)

    # ---- Tray ----

    def _install_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.info("System tray not available on this platform")
            return
        icon = _icon()
        self._tray = QSystemTrayIcon(icon if not icon.isNull() else self.windowIcon(), self)
        lang = i18n.resolve_lang(self.settings.get("language", "system"))
        self._tray.setToolTip(i18n.t("tray.tooltip", lang))

        menu = QMenu()
        self._tray_actions = {
            "show": QAction(i18n.t("tray.show", lang), self),
            "hide": QAction(i18n.t("tray.hide", lang), self),
            "read_clip": QAction(i18n.t("tray.read_clipboard", lang), self),
            "stop": QAction(i18n.t("tray.stop", lang), self),
            "quit": QAction(i18n.t("tray.quit", lang), self),
        }
        self._tray_actions["show"].triggered.connect(self._on_tray_show)
        self._tray_actions["hide"].triggered.connect(self.hide)
        self._tray_actions["read_clip"].triggered.connect(self._on_tray_read_clip)
        self._tray_actions["stop"].triggered.connect(self.bridge.stopRequested.emit)
        self._tray_actions["quit"].triggered.connect(lambda: QApplication.instance().quit())

        menu.addAction(self._tray_actions["show"])
        menu.addAction(self._tray_actions["hide"])
        menu.addSeparator()
        menu.addAction(self._tray_actions["read_clip"])
        menu.addAction(self._tray_actions["stop"])
        menu.addSeparator()
        menu.addAction(self._tray_actions["quit"])
        self._tray.setContextMenu(menu)

        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

        # Re-label when the user changes language
        self.bridge.languageChanged.connect(self._retranslate_tray)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._on_tray_show()

    def _on_tray_show(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_tray_read_clip(self) -> None:
        self._on_tray_show()
        self.bridge.readClipboardRequested.emit()

    def _retranslate_tray(self, _lang: str) -> None:
        lang = i18n.resolve_lang(self.settings.get("language", "system"))
        if not self._tray:
            return
        self._tray.setToolTip(i18n.t("tray.tooltip", lang))
        self._tray_actions["show"].setText(i18n.t("tray.show", lang))
        self._tray_actions["hide"].setText(i18n.t("tray.hide", lang))
        self._tray_actions["read_clip"].setText(i18n.t("tray.read_clipboard", lang))
        self._tray_actions["stop"].setText(i18n.t("tray.stop", lang))
        self._tray_actions["quit"].setText(i18n.t("tray.quit", lang))
