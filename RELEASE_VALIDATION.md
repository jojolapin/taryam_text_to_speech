# Text Speak Pro 1.2.0-rc.3 — release validation

The rc.3 branding update adds TextSpeak Pro™ / JojoLapin Inc. to the header,
About dialog and copyright footer. Functional export/playback changes are from rc.2.

The GUI/export correction is documented in GUI_CORRECTION.md. It restores the
original color palette and visible export controls while keeping the native editor.

## 1. Original architecture

PySide6 QMainWindow embedded Chromium/HTML, with a shared textarea and JavaScript
Audio playback. Python QThreadPool workers provided Piper/OpenAI synthesis, export,
normalization, pronunciation and voice downloads. IndexedDB stored document tabs;
QSettings stored preferences and the earlier single-document session.

Tab creation/navigation called Stop directly, playback indicators followed the
selected tab, the native context menu was disabled, imports overwrote text, and
the shared textarea discarded independent undo history. The prior build script
deleted the entire distribution folder. See ENGINEERING_REVIEW.md for evidence.

## 2. Framework decision

Keep PySide6, replace the primary Chromium editor with native Qt widgets.
QPlainTextEdit provides standard plain-text editing, context menus and separate
undo stacks. Native menus/window chrome replace the custom frameless interface.
Keep the legacy Chromium resources and reader tests for migration and rollback.

## 3. Playback architecture

PlaybackManager owns `active_playback_bookmark_id`, an immutable document/settings
snapshot, a small prefetch cache and unique request IDs. Navigation owns a separate
selected document. A single audio output is stopped synchronously before another
bookmark starts. Late synthesis and stale player callbacks cannot start old audio.
Pause during synthesis remains paused when data arrives. States include STOPPED,
LOADING, PLAYING and PAUSED. The library and status area name the speaking bookmark.
Piper synthesis is serialized because its espeak phonemizer changes global voice state.

## 4. Editor improvements

Native Cut/Copy/Paste, Undo/Redo, selection/navigation, standard context menus,
plain-text MIME handling, Find/Replace, TXT drop and File Open/Save/Save As.
UTF-8/BOM, UTF-16/BOM and Windows-1252 decoding; safe UTF-8 writes.
Imports into existing text offer Replace/Append/New Bookmark/Cancel. Replacement
is undoable. PDF/HTML imports never reuse the original path as a TXT save target.

## 5. Bookmark improvements

Separate editor/undo state per bookmark; Add/Rename/Delete/Duplicate/Reorder/Filter;
dirty and speaking-state text labels; reading markers; saved passage positions.
Closing modified bookmarks asks before discarding. Exiting retains unsaved documents
through an atomic session snapshot and one recovery backup. Migration preserves
legacy document metadata and the original IndexedDB library.

## 6. Additional product work

Native voice/rate/volume controls, explicit selection/cursor/resume commands,
passage highlighting, font/zoom/wrap, light/dark/system themes, reading timer,
recent files, pronunciation, speaking styles, online smart tools, audio cache
controls and WAV/MP3/paragraph exports. Existing provider services are retained.
Export cancellation was repaired; WAV and tagged MP3 writes are staged safely.
The build no longer recursively removes distribution-folder data.

## 7. Competitor research

Balabolka, NaturalReader, Panopreter and Speech Central were reviewed using their
own documentation. Standard editing, clipboard, library navigation, pronunciation,
export and readable playback state were adopted as useful patterns. Complex voice
cloning, cloud synchronization, browser extensions and broad format proliferation
were excluded. Links and MUST/HIGH/NICE/NOT classifications are in ENGINEERING_REVIEW.md.

## 8. Files changed

New: `app/documents.py`, `document_controller.py`, `editor.py`, `file_import.py`,
`legacy_migration.py`, `playback.py`, `workers.py`, `native_window.py`,
`native_menus.py`, `native_dialogs.py`, `native_export.py`, `native_theme.py`, `qa_smoke.py`, `frozen_diagnostics.py`;
`tests/conftest.py`, `tests/test_native_workspace.py`;
`tools/qa_legacy_migration.py`, `tools/qa_audio.py`, `tools/qa_native_export.py`; engineering/release/interface reports and
the Windows dependency lock file.

Updated: entry point, settings/paths, Piper engine, bridge exports/cancellation,
PyInstaller spec, build script, version metadata, installer version, README and
historical modernization-plan pointer. Legacy JS and existing tests remain intact.

## 9–10. Tests executed and results

| Check | Result / evidence |
| --- | --- |
| Original Python baseline | 147 passed |
| Original JavaScript baseline | 83 passed |
| Current Python suite | 182 passed (35 new native/storage/export cases) |
| Current JavaScript suite | 83 passed |
| A plays; create/select/edit/paste B | Automated Qt regression passed |
| TXT/BOM/Unicode drop into B while A plays | Automated MIME/editor regression passed |
| Play B stops A; late A requests ignored | Mocked regression and real Qt audio smoke passed |
| Pause/resume, stop, loading pause, rapid restart | Passed |
| Delete non-speaking bookmark | Passed |
| Native editor keyboard/context menu commands | Passed with QTest and QAction invocation |
| Per-document undo; Unicode selection offsets | Passed |
| Find/Replace and one-step Replace All undo | Passed |
| Modified import cancel/append/new/replace | Passed; replacement undo verified |
| Atomic save failure preserves existing file | Passed |
| Recovery backup and unknown legacy fields | Passed |
| Real IndexedDB → native migration | Separate seed/verify processes passed |
| Large document | Approximately 1.1 million characters, editing/find/switch round-trip under 10 seconds; 1.4 million-character import fixture also passed |
| Real Piper playback/source application | Passed six checks; `build/qa/native-final/smoke-result.json` |
| Real voice and audio export | All six installed voices produced valid WAV and MP3; `build/qa/real-voices/audio-results.json` |
| Restored export controls / actual bitrates | Eight real scenarios passed; MP3 at 64/128/192/256/320, WAV, paragraph batch MP3/WAV; tags and file counts checked in `build/qa/gui-export-final/export-results.json` |
| Light/dark visual inspection | Native screenshots inspected; dark rendering corrected |
| Packaged rc.3 executable / real audio | Six smoke checks passed, exit 0, no errors; `build/qa/trademark-packaged/smoke-result.json` |
| Packaged legacy migration (rc.1) | Passed, exit 0; `build/qa/packaged-migration/migration-result.json` |

Voice checks: en_US-joe-medium, en_US-kathleen-low, en_US-lessac-medium,
en_US-ryan-high, fr_FR-siwis-low, fr_FR-siwis-medium. The low French model logged
missing-phoneme warnings but produced playable output. This is a model-quality
limitation; waveform validity does not establish pronunciation quality.

## 11. Packaging

PyInstaller produced a separate `dist/branded-candidate/TextSpeakPro.exe`; the
previous candidates and pre-existing executable are preserved. QtMultimedia, QtWebEngine migration resources,
Piper/espeak data, ONNX libraries and license notices are included. Both real-audio
and legacy-migration tests passed in the packaged executable on this Windows machine.
The first build failed because PyInstaller collected an incompatible Poppler ICU DLL
from an unrelated tool directory on PATH. The spec now restricts dependency search
to the build's Python environment and Windows directories. Rebuilding resolved the
QtCore startup failure. An early startup diagnostic hook preserves future errors.
The separate portable ZIP contains the candidate, portable flag, license notices and
reports; SHA-256 files identify both artifacts. Existing distribution files are preserved.
The Inno Setup compiler was not found on PATH; no installer acceptance is claimed.
Its script targets the candidate and rejects an executable with the old version.

## 12. Remaining issues / explicit limits

- Computer-use app access timed out. No manual Explorer-to-editor drag gesture,
  cross-application clipboard matrix, screen-reader pass, or Windows display-scaling
  matrix is claimed. QTest/MIME integration and widget screenshots are separate evidence.
- OpenAI behavior is covered by mocked provider/bridge regressions, not live paid API calls.
- Native chrome is currently English; legacy French settings and voice support survive,
  but the native interface has not been fully localized.
- Native UI does not reproduce every legacy convenience: saved voice-preset UI,
  browser MediaSession headset bindings and time-based seeking remain legacy-only.
- Passage highlighting and saved passage starts are intentional; no fabricated word timings.
- A second clean Windows machine and installer installation/uninstallation are untested.
- TXT import limit is 32 MB; the largest automated editor fixture is much smaller.
- Generated executables, user profiles and distribution backups are excluded from Git; the repository contains application source, tests and build recipes.

## 13. Verdict

**NOT READY** for release sign-off while mandatory manual acceptance and clean-machine
installation gates remain unresolved. The native implementation and source/packaged regression
results are reviewable; this report is not a declaration that every acceptance item passed.
