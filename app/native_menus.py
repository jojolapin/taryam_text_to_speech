"""Standard menus and playback toolbar for the native workspace."""
from PySide6.QtWidgets import QToolBar, QMessageBox, QStyle
from PySide6.QtCore import Qt
from . import APP_NAME, APP_TRADEMARK, APP_AUTHOR, APP_YEAR

def build_menus(window):
    file_menu = window.menuBar().addMenu("&File")
    window.action(file_menu, "&New Bookmark", window.add_document, "Ctrl+N")
    window.action(file_menu, "&Open…", window.open_files, "Ctrl+O")
    window.recent_menu = file_menu.addMenu("Recent Files")
    window.recent_menu.aboutToShow.connect(window.populate_recent)
    window.action(file_menu, "&Save", window.save_document, "Ctrl+S")
    window.action(file_menu, "Save &As…", lambda: window.save_document(save_as=True), "Ctrl+Shift+S")
    file_menu.addSeparator()
    window.action(file_menu, "Export Speech to Audio…", window.export_audio)
    window.action(file_menu, "Export Paragraphs as Separate Audio Files…", lambda: window.export_audio(batch=True))
    window.cancel_export = window.action(file_menu, "Cancel Audio Export", window.cancel_audio_export)
    window.action(file_menu, "&Close Bookmark", window.close_document, "Ctrl+W")
    window.action(file_menu, "E&xit", window.close, "Alt+F4")
    edit = window.menuBar().addMenu("&Edit")
    window.edit_actions = {}
    for label, method, shortcut in [("Undo", "undo", "Ctrl+Z"), ("Redo", "redo", "Ctrl+Y"),
            ("Cut", "cut", "Ctrl+X"), ("Copy", "copy", "Ctrl+C"), ("Paste", "paste", "Ctrl+V"),
            ("Delete", "delete_selection", None), ("Select All", "selectAll", "Ctrl+A")]:
        # Widget shortcuts stay with the focused native edit control; menu actions
        # have display-only hints to avoid stealing Ctrl+C from Find, rename, etc.
        action = window.action(edit, label + ("\t" + shortcut if shortcut else ""), lambda m=method: window.edit_command(m))
        window.edit_actions[method] = action
    edit.aboutToShow.connect(window.update_edit_menu)
    edit.addSeparator()
    window.action(edit, "Find…", window.show_find, "Ctrl+F")
    window.action(edit, "Find Next", window.find_dialog.find, "F3")
    window.action(edit, "Find Previous", lambda: window.find_dialog.find(True), "Shift+F3")
    window.action(edit, "Replace…", window.show_find, "Ctrl+H")
    bookmark = window.menuBar().addMenu("&Bookmarks")
    window.action(bookmark, "Add Bookmark", window.add_document, "Ctrl+T")
    window.action(bookmark, "Rename…", window.rename_document, "F2")
    window.action(bookmark, "Duplicate", window.duplicate_document)
    window.action(bookmark, "Delete…", window.close_document)
    window.action(bookmark, "Move Up", lambda: window.move_document(-1), "Ctrl+Shift+Up")
    window.action(bookmark, "Move Down", lambda: window.move_document(1), "Ctrl+Shift+Down")
    window.action(bookmark, "Next Bookmark", lambda: window.next_document(1), "Ctrl+Tab")
    window.action(bookmark, "Previous Bookmark", lambda: window.next_document(-1), "Ctrl+Shift+Tab")
    window.action(bookmark, "Add Reading Marker", window.add_marker, "Ctrl+M")
    window.markers_menu = bookmark.addMenu("Reading Markers")
    window.markers_menu.aboutToShow.connect(window.populate_markers)
    speech = window.menuBar().addMenu("&Speech")
    toolbar = QToolBar("Playback", window)
    toolbar.setObjectName("playbackToolbar")
    toolbar.setMovable(False)
    toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    window.transport_layout.addWidget(toolbar)
    window.play_action = window.action(speech, "Play", window.play, "Ctrl+Return")
    window.pause_action = window.action(speech, "Pause", window.playback.pause)
    window.resume_action = window.action(speech, "Resume", window.playback.resume)
    window.stop_action = window.action(speech, "Stop", window.playback.stop, "Ctrl+.")
    for action, name, icon in ((window.play_action, "playButton", QStyle.StandardPixmap.SP_MediaPlay),
            (window.pause_action, "pauseButton", QStyle.StandardPixmap.SP_MediaPause),
            (window.resume_action, "resumeButton", QStyle.StandardPixmap.SP_MediaPlay),
            (window.stop_action, "stopButton", QStyle.StandardPixmap.SP_MediaStop)):
        action.setIcon(window.style().standardIcon(icon))
        toolbar.addAction(action)
        toolbar.widgetForAction(action).setObjectName(name)
    cursor_action = window.action(speech, "From cursor", lambda: window.play("cursor"))
    toolbar.addAction(cursor_action)
    window.action(speech, "Play / Pause", window.toggle_playback, "F6")
    window.action(speech, "Read Selection", lambda: window.play("selection"), "Ctrl+Shift+R")
    window.action(speech, "Read From Cursor", lambda: window.play("cursor"), "Ctrl+Shift+Return")
    window.action(speech, "Continue Saved Position", lambda: window.play("position"))
    window.action(speech, "Previous Passage", lambda: window.playback.skip(-1), "Alt+Left")
    window.action(speech, "Next Passage", lambda: window.playback.skip(1), "Alt+Right")
    window.action(speech, "Read Clipboard in New Bookmark", window.read_clipboard)
    timer = speech.addMenu("Reading Timer")
    for minutes in (0, 10, 20, 30):
        window.action(timer, "Off" if not minutes else f"Stop after {minutes} minutes", lambda m=minutes: window.set_timer(m))
    window.action(speech, "Voices and Settings…", window.show_settings)
    window.action(speech, "Pronunciation Dictionary…", window.show_pronunciation)
    view = window.menuBar().addMenu("&View")
    window.action(view, "Editor Font…", window.choose_font)
    window.action(view, "Zoom In", lambda: window.zoom(1), "Ctrl++")
    window.action(view, "Zoom Out", lambda: window.zoom(-1), "Ctrl+-")
    window.wrap_action = window.action(view, "Word Wrap", window.toggle_wrap)
    window.wrap_action.setCheckable(True)
    window.wrap_action.setChecked(window.settings.get("editor_wrap", True))
    theme = view.addMenu("Theme")
    for value in ("system", "light", "dark"):
        window.action(theme, value.title(), lambda v=value: window.apply_theme(v))
    help_menu = window.menuBar().addMenu("&Help")
    window.action(help_menu, "Open Logs Folder", window.bridge.open_logs_folder)
    window.action(help_menu, "About Text Speak Pro", lambda: QMessageBox.about(window, APP_NAME,
        f"{APP_TRADEMARK}\n© {APP_YEAR} {APP_AUTHOR}\nNative Windows text editing and speech.\n\nPiper reads locally; OpenAI sends the text you choose to its configured provider.\nAudio usage rights depend on the selected voice and provider.\n\nHighlighting marks the current synthesized passage, not estimated words."))
