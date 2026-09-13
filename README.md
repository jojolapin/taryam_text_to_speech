# Text Speak Pro

Native Windows text editing with offline Piper speech and optional OpenAI voices.
Version **1.2.0-rc.3** is a release candidate. See [release validation](RELEASE_VALIDATION.md)
for tested behavior and outstanding acceptance checks.

The original blue/violet styling and visible audio export controls have been
restored around the improved native editor. See [interface correction](GUI_CORRECTION.md).

## Running

Use `run.bat`, or the existing environment:

```powershell
.\.venv\Scripts\python.exe main.py
```

The separately built candidate is `dist/branded-candidate/TextSpeakPro.exe`.
The pre-existing `dist/TextSpeakPro.exe` is preserved.

## Document and playback behavior

Each bookmark has its own native plain-text editor, undo history, settings and
reading position. Creating, selecting, editing, importing into or renaming another
bookmark does not stop the speaking bookmark. Pressing Play starts the selected
bookmark and stops the previous audio output first. Pause, Resume and Stop always
control the speaking bookmark, identified by text in the library and status area.

Play reads a selection when present, otherwise the whole document. Speech also
provides Read From Cursor and Continue Saved Position. Highlighting marks the
actual synthesized passage. It does not pretend to offer word timestamps.
Voice, speed and volume changes apply at the next explicit Play.

## Editing and files

Qt provides standard typing, selection, Cut/Copy/Paste, Undo/Redo and the right-click
menu. File offers New, Open, Save and Save As. Edit offers Find/Replace. Drag TXT
files directly into the editor. When text already exists, choose Replace, Append,
Open in New Bookmark or Cancel. Multiple files open as separate bookmarks.

TXT supports UTF-8, BOM, UTF-16 with BOM and Windows-1252 fallback. Saves are UTF-8
and atomic. Markdown, text-based PDF and HTML imports remain available. PDF/HTML
imports are saved as a separate text document; the original file is not overwritten.
Scanned PDFs need external OCR. Import limit: 32 MB per file.

## Shortcuts

| Shortcut | Action |
| --- | --- |
| Ctrl+N / Ctrl+T | Add bookmark |
| Ctrl+O / Ctrl+S / Ctrl+Shift+S | Open / Save / Save As |
| Ctrl+W / F2 | Close / Rename bookmark |
| Ctrl+Tab / Ctrl+Shift+Tab | Next / previous bookmark |
| Ctrl+Enter | Play selected bookmark |
| Ctrl+Shift+Enter | Read from cursor |
| Ctrl+Shift+R | Read selection |
| F6 | Pause/resume active speech, or Play if stopped |
| Ctrl+. | Stop active speech |
| Alt+Left / Alt+Right | Previous / next passage |
| Ctrl+F / Ctrl+H | Find / Replace |
| F3 / Shift+F3 | Next / previous match |
| Ctrl+M | Add reading marker |
| Ctrl++ / Ctrl+- | Editor zoom |

Normal Windows editor shortcuts remain native to the focused editor/control.

## Speech tools

Speech > Voices and Settings downloads Piper voices, configures optional OpenAI
speech, speaking styles and Markdown mode, and offers the existing smart tools.
Pronunciation substitutions can apply globally or to one bookmark. Audio export
supports WAV/MP3; Piper can export separate files per paragraph. A reading timer,
recent files, font/word-wrap preferences and System/Light/Dark themes are available.
Generate Audio, Batch Export, format, MP3 bitrate (64–320 kbps), author tags,
progress and cancellation are together on the main screen. WAV is uncompressed;
OpenAI determines its own encoded bitrate, so that selector applies to Piper MP3.
OpenAI requires a configured key and sends requested text to the configured service;
API charges may apply. Offline Piper playback does not upload document text.
Audio usage rights depend on the voice/provider; consult their terms and model card.

## Storage and migration

Installed data: `%APPDATA%/JojoLapin/TextSpeak Pro/`. Portable mode uses the executable
folder when `portable.flag` exists. Existing QSettings preferences remain compatible.
The native workspace is `workspace-v2.json` with `workspace-v2.backup.json` for recovery.
Unsaved text is automatically retained between sessions; closing a modified bookmark
asks before discarding it. Exiting retains the session without forcing TXT exports.

On first native startup, legacy IndexedDB documents are read from the original
Chromium profile. The original library is retained. A migration failure blocks
workspace editing rather than replacing the saved library with an empty one.
Legacy web resources remain bundled for migration/rollback; the primary editor is native.

## Architecture

- `native_window.py`: window composition and transport presentation.
- `native_menus.py`, `native_dialogs.py`, `editor.py`: native controls and editing.
- `document_controller.py`: document lifecycle and file workflows.
- `documents.py`, `file_import.py`, `legacy_migration.py`: storage and safe imports.
- `playback.py`: independent speaking-document ownership, one audio output, stale callback rejection.
- Existing `bridge.py`, `tts_engine.py`, providers, normalizer, pronunciation, catalog and cache: retained services.
- `workers.py`: background jobs delivered through Qt signals.

## Tests and builds

The Windows installer is `dist/installer/TextSpeakPro-Setup-1.2.0-rc.3.exe`.
It defaults to installing for the current user, offers an optional desktop shortcut,
and includes an uninstaller. Installed documents, preferences and voices stay in
the existing user profile. Quit the tray copy before installing and launching.
This release candidate is not code-signed.

To rebuild the installer after building the branded executable:

```powershell
& 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe' installer\TextSpeakPro.iss
```

`tools/qa_installer.py` tests installation and removal in a temporary project folder;
it refuses to run over an existing registered TextSpeak Pro installation.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/js/*.test.js
.\.venv-build\Scripts\python.exe -m PyInstaller --noconfirm --distpath dist/branded-candidate --workpath build/branded-candidate textspeak_pro.spec
```

`requirements-windows-lock.txt` records the tested build environment. `requirements.txt`
remains the general runtime dependency list. Build on Windows to produce Windows binaries.
The build script preserves output folders because they may contain portable user data.

Explicit offline smoke mode uses generated fixtures in a dedicated directory:

```powershell
.\.venv\Scripts\python.exe main.py --self-test --data-dir build/qa/demo --voice-dir "$env:APPDATA/JojoLapin/TextSpeak Pro/voices"
```

Do not point self-test mode at a valuable document/profile directory. Migration fixtures
and real voice/export tests are provided in `tools/qa_legacy_migration.py` and `tools/qa_audio.py`.

See [engineering review](ENGINEERING_REVIEW.md), [validation](RELEASE_VALIDATION.md),
[LICENSE](LICENSE), and [NOTICE](NOTICE). The older modernization plan is historical.
