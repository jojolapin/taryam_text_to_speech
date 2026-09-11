# Text Speak Pro engineering review

Baseline: GitHub/local `f63e34a`, 2026-09-10. 147 Python and 83 JavaScript tests pass.
The original application was launched with an isolated profile. Windows computer-use
inspection timed out waiting for app access; this is not a manual acceptance pass.

## Architecture and defects

The application already uses PySide6: a frameless QMainWindow, QtWebEngine,
HTML textarea, and QWebChannel. Piper ONNX synthesis, optional OpenAI synthesis,
pronunciation substitutions, normalization, caching, voice downloads and exports
live in Python. QRunnables perform synthesis/downloads. Browser Audio owns playback.
Document tabs live in IndexedDB (`textspeak/workspace/snapshot`); reading markers
are nested in each document. QSettings stores preferences and legacy single text.
PyInstaller produces a one-file executable; Inno Setup wraps it.

Confirmed defects: tab creation/navigation deliberately stop playback; playback
ownership follows the visible tab; loading a tab changes the playing volume and
pronunciation; imports overwrite text; context menus are disabled; the shared
textarea loses per-document undo history; there is no standard TXT save workflow;
debounced persistence does not await completion on exit; highlighting estimates
word positions without actual backend word boundaries. The spec omits text-nav.js.
The build script deletes the entire dist directory, which can contain portable data.

## Decision

Retain PySide6 and the proven Python synthesis/services. Replace the primary web
workspace with native Qt widgets: QPlainTextEdit per document, standard menus,
native window frame, separate document/persistence/file/playback services.
QPlainTextEdit provides plain text, native clipboard/context menus, undo stacks,
keyboard selection and large-document support. See
[Qt documentation](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QPlainTextEdit.html).
Keep legacy web resources for safe IndexedDB migration and rollback, not as the
new primary workspace. Preserve original storage; commit a native snapshot only
after successful migration. Never interpret a migration failure as an empty library.

Playback owns an immutable text/settings snapshot and a document ID independent
of selection. Stop/cancel happens only on explicit transport commands, playing
another document, deleting the speaker, or shutdown. Stale asynchronous callbacks
are rejected by request identity. Highlight only the actual synthesized passage;
Piper/OpenAI here do not expose reliable word timestamps.

## Existing capabilities to preserve

Offline Piper voices/catalog, optional OpenAI voices, rate/volume, pause/resume,
WAV/MP3 export and cancellation, pronunciation rules, speaking styles, Markdown
normalization, document duplication/reordering, reading markers/positions,
recent files, persistent settings, EN/FR legacy UI, smart tools, cache controls,
tray access, portable deployment. Any unvalidated/native UI gaps must be reported.

## Competitor review

MUST HAVE: reliable editor/clipboard, document library, explicit playback ownership,
voice/rate/volume controls, navigation, keyboard access, recovery and TXT operations.
HIGH VALUE: pronunciation, audio export, reading positions, find/replace, font/theme
controls. NICE TO HAVE: timer, batch conversion, extra imports. NOT APPROPRIATE for
this release: voice cloning, browser extensions, cloud library sync, speculative
pitch or fake word synchronization.

Sources reviewed: [Balabolka](https://cross-plus-a.com/balabolka.htm)
(clipboard, formats, bookmarks, pronunciation, export);
[NaturalReader](https://help.naturalreaders.com/en/articles/8823808-what-features-are-available-in-naturalreader-ai-text-to-speech-personal-version)
(voice settings, pronunciation, timer, reading aids);
[Panopreter](https://www.panopreter.com/en/products/panopreter/index.php)
(clipboard, highlighting, batch export, shortcuts, appearance).
[Speech Central Windows help](https://speechcentral.net/share-to-speech-help/)
(file import and article library) and its
[Windows development status](https://speechcentral.net/2026/08/12/why-speech-central-for-windows-is-still-available/)
were also reviewed. Its current cross-platform sleep features should not be
assumed to exist in the less actively developed Windows version. Adopt a simple
explicit stop timer, not its broader bedtime assistant or content aggregation.

## Acceptance

Results and remaining limitations are recorded in RELEASE_VALIDATION.md as checks
are executed. Passing baseline unit tests alone does not establish release readiness.

## Packaged validation

The candidate passes the real Piper/Qt audio A-to-B smoke test and synthetic legacy
IndexedDB migration as a frozen executable. The initial QtCore import failure came
from a Poppler ICU DLL selected through the machine's broader tools PATH, not the
application's pinned Python environment. The spec now isolates DLL discovery to
Python and Windows; the rebuilt candidate starts and passes both tests. Early
startup exceptions are logged even before application modules can import.
The Windows manual interaction and clean-machine installation gates remain open.
