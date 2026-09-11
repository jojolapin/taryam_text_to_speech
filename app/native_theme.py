"""The original blue/violet visual identity, expressed through native Qt widgets."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette, QPainter, QIcon, QFont
from PySide6.QtWidgets import QApplication, QStyle


def apply_theme(window, theme):
    window.settings.set("theme", theme)
    dark = theme == "dark" or (theme == "system" and
        QApplication.instance().styleHints().colorScheme() == Qt.ColorScheme.Dark)
    bg, card, field, text, muted, border, selected = (
        ("#0a0d18", "#161c30", "#101629", "#e8ebf4", "#a3aec9", "#303b5a", "#293e68") if dark else
        ("#eef2fb", "#ffffff", "#f7f9ff", "#0e1324", "#5a6682", "#d6dff0", "#e0eaff"))
    palette = QPalette()
    for role, value in ((QPalette.ColorRole.Window, card), (QPalette.ColorRole.Base, field),
            (QPalette.ColorRole.Text, text), (QPalette.ColorRole.WindowText, text),
            (QPalette.ColorRole.Button, card), (QPalette.ColorRole.ButtonText, text),
            (QPalette.ColorRole.Highlight, "#517bce"), (QPalette.ColorRole.HighlightedText, "#ffffff")):
        palette.setColor(role, QColor(value))
    window.setPalette(palette)
    window.setFont(QFont("Segoe UI", 10))
    for action, standard, color in ((window.play_action, QStyle.StandardPixmap.SP_MediaPlay, "#ffffff"),
            (window.pause_action, QStyle.StandardPixmap.SP_MediaPause, "#fcd34d" if dark else "#865600"),
            (window.resume_action, QStyle.StandardPixmap.SP_MediaPlay, "#6ee7b7" if dark else "#087449"),
            (window.stop_action, QStyle.StandardPixmap.SP_MediaStop, "#fda4af" if dark else "#b32442")):
        pixmap = window.style().standardIcon(standard).pixmap(20, 20)
        painter = QPainter(pixmap)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), QColor(color))
        painter.end()
        action.setIcon(QIcon(pixmap))
    window.setStyleSheet(f"""
        QWidget {{ color: {text}; }}
        QMainWindow, QWidget#workspace {{ background: {bg}; }}
        QDialog, QMenu {{ background: {card}; }}
        QWidget#brandHeader {{ border: 1px solid {border}; border-radius: 16px;
            background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {selected},stop:1 {card}); }}
        QWidget#libraryCard, QWidget#editorPane, QWidget#exportCard {{
            background: {card}; border: 1px solid {border}; border-radius: 16px; }}
        QLabel {{ background: transparent; border: none; }}
        QLabel#brandTitle {{ font-size: 25px; font-weight: 700; }}
        QLabel#sectionLabel {{ color: {muted}; font-size: 11px; font-weight: 700; letter-spacing: 1px; }}
        QLabel#mutedLabel {{ color: {muted}; font-size: 12px; }}
        QLabel#documentTitle {{ font-size: 18px; font-weight: 600; padding: 3px 0 8px; }}
        QLabel#playbackStatus {{ color: {muted}; padding: 5px 0; }}
        QMenuBar {{ background: {bg}; padding: 3px 12px; }}
        QMenuBar::item {{ padding: 5px 9px; background: transparent; }}
        QMenuBar::item:selected, QMenu::item:selected {{ background: {selected}; border-radius: 5px; }}
        QMenu {{ border: 1px solid {border}; padding: 6px; }}
        QMenu::item {{ padding: 7px 22px; }}
        QPlainTextEdit, QListWidget, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
        QTableWidget {{ background: {field}; color: {text}; border: 1px solid {border};
            border-radius: 9px; padding: 7px; selection-background-color: #517bce; selection-color: white; }}
        QPlainTextEdit {{ padding: 14px; }}
        QComboBox {{ padding-right: 23px; min-height: 20px; }}
        QComboBox::drop-down {{ border: none; width: 22px; }}
        QComboBox QAbstractItemView {{ background: {card}; color: {text}; selection-background-color: {selected}; }}
        QListWidget {{ border: none; background: transparent; padding: 0; }}
        QListWidget::item {{ padding: 13px 9px; margin-bottom: 5px; border-radius: 9px; }}
        QListWidget::item:selected {{ background: {selected}; color: {text}; }}
        QListWidget::item:hover {{ background: {selected}; }}
        QToolBar {{ border: none; background: transparent; spacing: 7px; padding: 4px 0; }}
        QToolButton, QPushButton {{ background: {card}; border: 1px solid {border};
            border-radius: 9px; padding: 9px 13px; font-weight: 600; }}
        QToolButton:hover, QPushButton:hover {{ background: {selected}; border-color: #6aa2ff; }}
        QPushButton#primaryButton, QToolButton#playButton {{ color: white; border: none;
            background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #3978d8,stop:1 #8654d8); }}
        QToolButton#resumeButton:enabled {{ color: {('#6ee7b7' if dark else '#087449')}; border-color: #258367; }}
        QToolButton#pauseButton:enabled {{ color: {('#fcd34d' if dark else '#865600')}; border-color: #967b38; }}
        QToolButton#stopButton:enabled {{ color: {('#fda4af' if dark else '#b32442')}; border-color: #a84a62; }}
        QPushButton:disabled, QToolButton:disabled {{ color: {muted}; background: {field}; border-color: {border}; }}
        QComboBox:disabled, QLineEdit:disabled {{ color: {muted}; }}
        QLineEdit:focus, QPlainTextEdit:focus, QPushButton:focus, QToolButton:focus {{ border: 1px solid #6aa2ff; }}
        QSplitter::handle {{ background: transparent; width: 12px; }}
        QStatusBar {{ background: {bg}; color: {muted}; padding: 3px 14px; font-size: 11px; }}
        QProgressBar {{ background: {field}; border: none; border-radius: 2px; }}
        QProgressBar::chunk {{ background: #8b5cf6; border-radius: 2px; }}
        QTabWidget::pane {{ border: 1px solid {border}; }}
        QTabBar::tab {{ background: {field}; padding: 9px 14px; }}
        QTabBar::tab:selected {{ background: {selected}; }}
        QToolTip {{ background: {card}; color: {text}; border: 1px solid {border}; padding: 5px; }}
    """)
