# Voice Reader Pro — Modernization Plan (TextSpeak Pro)

> **Analysis pass only. No production code was changed to produce this document.**
> Evidence-based plan derived from reading the actual repository, running the
> test suite, and verifying the runtime environment.

---

## Implementation status (v1.1.0)

All phases complete. Full suite green: **147 pytest + 83 node:test** passing.

| Phase | Status | Key deliverables |
| --- | --- | --- |
| 0 — Baseline & regression | ✅ Done | Green tests, `.env` ignored, JS + bridge smoke tests |
| 1 — Tabs + document state | ✅ Done | Multi-tab workspace, IndexedDB persistence |
| 2 — Provider abstraction | ✅ Done | `providers.js` / `providers.py`, Piper via interface |
| 3 — OpenAI backend | ✅ Done | Config/.env loader, `openai_provider.py`, bridge slots, status UI |
| 4 — Long-text generation | ✅ Done | Semantic chunking, progress/cancel/retry/cache |
| 5 — Audio export + cache | ✅ Done | OpenAI export, `audio_cache.py`, cache management UI |
| 6 — Playback & highlighting | ✅ Done | Sentence/paragraph nav, weighted highlight sync, rAF ticker |
| 7 — Smart reading & pronunciation | ✅ Done | `pronunciation.py` (global+per-doc, non-destructive, preview), `speaking_styles.py` presets, AI smart tools → new tab |
| 8 — UI polish / a11y / shortcuts | ✅ Done | `:focus-visible`, ARIA labels, reduced-motion, keyboard-shortcuts help dialog (`F1`/`?`), multi-attr i18n |
| 9 — Regression & release | ✅ Done | Full suite green, README refresh, version bump to 1.1.0, security self-review |

---

## 0. Important reality check (read this first)

The modernization brief describes the target as a **Flask + Piper browser web app**
started with `bash start.sh` on `http://127.0.0.1:5005`. **The real repository in this
workspace is not that.**

The actual project is **TextSpeak Pro™** by JojoLapin Inc.: a **PySide6 desktop
application** that embeds a Chromium `QWebEngineView` and talks to Python over a
**`QWebChannel` bridge**. There is:

- **No Flask, no HTTP server, no `localhost:5005`, no `start.sh`.**
- Launchers are `run.bat` (Windows) / `run.sh` (macOS/Linux); packaging is a
  single-file `TextSpeakPro.exe` built by PyInstaller.
- The "browser" is a bundled Chromium view loaded from a local `file://` URL
  (`ui/index.html`), not a served page.

This is a **material difference** that changes several instructions in the brief.
The most important consequence:

- The requested `POST /api/openai/synthesize` **HTTP endpoint does not fit this
  architecture.** The correct equivalent is a **new `QWebChannel` bridge slot**
  (e.g. `synthesize_openai(...)`) that emits a result signal — exactly how the
  existing `synthesize()` Piper path already works. The security intent of the
  brief (key never in the browser, key only in Python) is preserved and is in
  fact *easier* to honor here because the "browser" is a privileged local view.

Every recommendation below is written for the **real** PySide6 + QWebChannel app.
The deliverable file keeps the requested name (`VOICE_READER_MODERNIZATION_PLAN.md`)
but the subject is **TextSpeak Pro**.

---

## 1. Current architecture

### 1.1 Baseline verification (done during this pass)

| Check | Result |
| --- | --- |
| `.venv` present with runtime deps | ✅ `.venv\Scripts\python.exe` (Python 3.14.3) |
| Runtime imports | ✅ `PySide6, piper, lameenc, mutagen, pypdf, requests` all import |
| Test suite | ✅ `44 passed in 0.11s` (`tests/test_text_normalize.py`) |
| Secret scan (`OPENAI`, `sk-…`, `api_key`, `Authorization`, `Bearer`) | ✅ No matches anywhere in repo |
| Git status | Only `M LICENSE` (working tree otherwise clean) |

### 1.2 Major files and responsibilities

| File | Lines | Responsibility |
| --- | --- | --- |
| `main.py` | 71 | Entry point. High-DPI/Chromium env flags, `QApplication`, single-instance `QLockFile`, wires `Settings → Bridge → MainWindow`. |
| `app/__init__.py` | 15 | App constants (`APP_NAME`, `APP_VERSION`, org dirs, copyright). |
| `app/main_window.py` | 350 | Frameless `QMainWindow` + `QWebEngineView`. Registers `bridge` on `QWebChannel`. Mica backdrop, Win11 snap style, native drag/resize, system tray, DnD, geometry persistence. Loads `ui/index.html` via `QUrl.fromLocalFile`. |
| `app/bridge.py` | 642 | **The JS⇄Python API.** All `@Slot`s callable as `window.bridge.<method>()`. Heavy work runs on `QThreadPool` and returns via Qt `Signal`s. Owns cancel tokens keyed by `request_id`. Handles synth, export, batch export, catalog, file/clipboard import, prefs, presets, recents, window chrome. |
| `app/tts_engine.py` | 313 | Piper wrapper. In-memory voice cache (`dict` + `Lock`), WAV/PCM synthesis, MP3 (`lameenc`)/WAV/OGG encoders, full-text export, ID3 tagging via `mutagen`. Includes a PyInstaller "espeak data present?" self-check. |
| `app/text_normalize.py` | 444 | Markdown/HTML → speech-friendly plain text (ordered regex pipeline, idempotent). Format detection + signal sniffing. Options for code/urls/tables. |
| `app/voice_catalog.py` | 193 | Browse/download free Piper voices. Bundled `voice_catalog.json` + optional merge from HuggingFace `rhasspy/piper-voices`. Streamed HTTPS downloads with cancel + progress. Sample fetch/cache. |
| `app/settings.py` | 129 | `QSettings` wrapper (portable INI next to exe, else registry/INI userscope). Typed defaults, JSON list helpers, window geometry, recent-files MRU. |
| `app/paths.py` | 122 | Portable vs installed path resolution; `voices/`, `logs/`, `cache/`, `settings.ini`, bundled-resource lookup (`sys._MEIPASS`). |
| `app/i18n.py` | 148 | **Native Qt chrome** strings (tray, dialogs, about) EN/FR. |
| `app/logging_setup.py` | — | Logging install (rotating file in `logs/`). |
| `app/mica.py`, `app/win_frameless.py`, `app/main_window.py` | — | Windows-specific window styling (Mica, snap). |
| `ui/index.html` | ~1070 | Single-file UI: all CSS inline, full DOM (title bar, status, `#input` textarea, `#render` highlight panel, drawers, wizard, overlays). |
| `ui/app.js` | 1624 | **All frontend logic.** `Logger`, `TextChunker`, `BridgeAPI` (promise wrapper over QWebChannel), `PiperReader` (playback engine), `MarkdownMode`, and the entire UI wiring/boot. |
| `ui/i18n.js` | — | **Web UI** EN/FR string table + `I18N.t()` / `applyAll()`. |
| `voice_catalog.json` | — | Bundled ~50-voice catalog. |
| `tests/test_text_normalize.py` | 330 | 44 unit tests for the normalizer only. |
| Build: `textspeak_pro.spec`, `build_exe.py`, `build.bat/.sh`, `installer/*.iss` | — | PyInstaller onefile packaging + Inno Setup installer. |

### 1.3 Frontend architecture

- **Single-document model.** There is exactly one editor: `<textarea id="input">`
  (`ui/index.html:697`). Text is read directly from `#input.value` everywhere
  (`doPlay`, `doExport`, stats, bookmarks). **There is no document abstraction and
  no concept of tabs.**
- **`BridgeAPI`** (`ui/app.js:90`) wraps the raw QWebChannel object into promises.
  Synthesis is request/response by generated id (`s-1`, `s-2`, …) resolved when
  `synthesizeReady`/`synthesizeError` signals fire. Long ops (export, catalog)
  use listener sets instead of promises.
- **`PiperReader`** (`ui/app.js:253`) is the playback state machine. One instance
  (`const reader = new PiperReader()`, `ui/app.js:471`). Single HTML `<audio>`.
- **`MarkdownMode`** (`ui/app.js:474`) mirrors the Python normalizer's sniffing to
  drive a pill + passes an effective `textFormat` down to synthesis/export.
- **State** lives in module-scoped globals: `PREFS`, `AVAILABLE_VOICES`,
  `BOOKMARKS`, `CATALOG`, `PRESETS`, `findMatches`. Persistence is through
  `BridgeAPI.setPref(...)` → `QSettings`.

### 1.4 "Flask architecture" — N/A

There is no Flask layer. The server-equivalent is `app/bridge.py`. Requests are
**method calls** (`@Slot`) and responses are **Qt signals**; there is no routing,
no JSON HTTP, no CORS. Any brief instruction phrased as "add a Flask endpoint"
maps to "add a bridge slot + result signal."

### 1.5 Piper integration

- `TTSEngine.get_voice(voice_id)` (`app/tts_engine.py:149`) lazy-loads
  `PiperVoice.load(<voices_dir>/<id>.onnx)` under a `Lock` and caches the object
  in `self._cache`. First call pays 0.5–2 s; later calls are instant.
- `_verify_piper_data_bundle()` guards against the frozen-build failure mode where
  `espeak-ng-data/` or `espeakbridge*.pyd` is missing (would otherwise crash the
  process instead of raising).
- Synthesis (`synthesize_wav_bytes`) writes a WAV into a `BytesIO` via
  `wave.open`. It **does not** stream; a chunk is fully synthesized before return.
- Voices are discovered by scanning `voices_dir()` for `*.onnx` + matching
  `*.onnx.json` (`discover_voices`).

### 1.6 Text chunking

Two independent chunkers exist and should not be confused:

1. **Playback chunker — `TextChunker.chunk(text, maxChars=450)`** (`ui/app.js:38`),
   JS, character-window based. For each window it walks backward from the max to
   find, in priority order: a sentence end (`.!?` followed by whitespace), then a
   clause mark (`,;:`), then any whitespace; falls back to the hard window edge.
   It preserves `{text, start, end}` offsets used for progress/highlight mapping.
   `findChunkAtPosition` maps a cursor char index to a chunk index.
2. **Speech normalizer — `text_normalize.normalize()`** (`app/text_normalize.py`),
   Python, converts markdown/HTML to speakable plain text before synthesis. This
   is the module the 44 tests cover.

### 1.7 Playback lifecycle (the sensitive core)

`PiperReader` is guarded by a **monotonic `sessionId`**. Every async continuation
re-checks `this.sessionId !== sid` and bails if stale. Key methods:

- `start(text, opts, fromPosition)` (`:283`): `_hardStop('new session')` →
  bump `sessionId` → capture `sid` → chunk text → prefetch current + next
  (`_ensureChunkLoaded`) → `await _waitForChunk(current)` → `_playCurrent`.
- `_ensureChunkLoaded(idx, sid)` (`:339`): dedupes by `audioCache`/`pendingFetches`,
  calls `BridgeAPI.synthesize`, and on resolve (if `sid` still current) builds a
  Blob → object URL → stores in `audioCache` and resolves any waiters.
- `_waitForChunk` (`:361`) resolves immediately if cached, else registers a waiter
  with a **60 s timeout**; rejects with "stale session" if `sid` changed.
- `_playCurrent(sid)` (`:383`): sets `<audio>.src`, `await audio.play()`, then
  **re-checks `sid` and pauses if stale** (prevents old audio from starting),
  transitions to `playing`, prefetches next.
- `_onChunkEnded` (`:410`): revokes the finished chunk's URL, advances `chunkIdx`,
  prefetches next, plays next.
- `pause/resume/stop/restart/skip` (`:316`–`:336`). `skip` re-`start`s from a new
  char position estimated at `12 * rate` chars/second. Speed/voice change while
  playing calls `doPlay(reader._currentCharIndex())` to restart at position.
- **`_hardStop(reason, silent)`** (`:445`): **bumps `sessionId`**, pauses+unloads
  `<audio>`, clears `pendingFetches`, rejects+clears all `chunkWaiters`, and
  **revokes every object URL in `audioCache`** then clears it. This is the linchpin
  of stale-session and memory safety.

**Cursor-position reading:** `doPlay(fromPosition)` (`ui/app.js:675`) is called with
`#input.selectionStart` (button) or a computed word-start on `dblclick`
(`ui/app.js:1315`). It flows into `start(..., fromPosition)` → `findChunkAtPosition`.

**Server-side cancellation:** `bridge.synthesize` registers a `CancelToken` keyed by
`request_id`; `bridge.cancel(request_id)` sets it. The token is checked after
synthesis completes (`app/bridge.py:242`) — i.e. it prevents emitting a stale
result, but Piper synthesis itself is not preemptible mid-utterance.

### 1.8 State management

- **Server-authoritative prefs** in `QSettings` (`app/settings.py` defaults at
  `:19`). Includes `saved_text`, `saved_position`, `bookmarks`, `presets`,
  `recent_files`, voice/speed/volume, theme/language, markdown flags, export
  format/bitrate, window geometry.
- **Text persistence today:** only when the "save progress" toggle is on
  (`save_text`). On every `input` event, `BridgeAPI.setPref('saved_text', value)`
  is called (`ui/app.js:1309`), and `Settings.set` calls **`QSettings.sync()` on
  every keystroke** (`app/settings.py:82`). Restored at boot (`ui/app.js:1265`).
- Bookmarks/presets/recents stored as **JSON strings inside prefs**.

### 1.9 Current persistence mechanism

`QSettings` (INI in portable mode next to the exe; registry/user-scope INI when
installed). Data dirs resolved by `app/paths.py`. Cache dir exists
(`user_data_dir()/cache`) but currently only holds voice samples.

### 1.10 Existing tests

Only `tests/test_text_normalize.py` (44 tests, all passing). **There are no tests
for the bridge, the engine, the catalog, or any frontend logic** — notably none
for the session/stale-playback guarantees, which are the most sensitive code.

---

## 2. Current risks

### 2.1 Fragile / high-sensitivity code (do not casually rewrite)

- **`PiperReader` session guard + `_hardStop`** (`ui/app.js:283–455`). Correctness
  of stop/restart/skip/stale-audio depends entirely on the `sessionId` discipline
  and URL revocation. Any refactor must preserve the "check `sid` after every
  `await`" invariant.
- **`_verify_piper_data_bundle()`** (`app/tts_engine.py:39`) — packaging safety net.
- **PyInstaller data collection** in `textspeak_pro.spec` (piper espeak data +
  `espeakbridge.pyd` + onnxruntime DLLs). Adding deps for OpenAI must not break this.

### 2.2 Duplicate logic

- **Two markdown sniffers**: `MarkdownMode.sniff` (JS, `ui/app.js:484`) and
  `text_normalize._looks_like_markdown` (Python). Intentional, but they can drift.
- **Two filename sanitizers**: `_safe_filename` (Python, `app/bridge.py:55`) and
  `generateAudioFilename` (JS, `ui/app.js:865`).
- **Chunking vs. normalization** both exist; the playback chunker is unaware of the
  normalizer's transformations (it chunks the *raw* editor text, normalization
  happens per-chunk in Python).

### 2.3 Race conditions / playback-session risks

- Changing **rate/voice while playing** restarts via `doPlay(reader._currentCharIndex())`
  (`ui/app.js:1337`, `:1346`). Rapid slider drags can spawn many `start()` calls;
  the `sessionId` guard makes this *safe* but wasteful (repeated synth). Debounce
  is desirable.
- `skip`'s char/second model (`12 * rate`) is a heuristic; seek accuracy is coarse.
- `_currentCharIndex` interpolates linearly inside a chunk by audio time ratio;
  fine for highlight, imprecise for exact seek.

### 2.4 Memory / temporary-file concerns

- Object URLs are revoked in `_onChunkEnded` and `_hardStop`, but a chunk that is
  **prefetched and never played** (e.g. user stops before reaching it) is revoked
  only via `_hardStop`'s sweep — which is correct, but the pattern is easy to break.
- Export/batch synthesize the **entire text in one PCM buffer** in memory
  (`synthesize_pcm`, `app/tts_engine.py:203`). Very long documents = large RAM spikes.
- No cache-size management anywhere; the `cache/` dir grows unbounded (samples today,
  OpenAI audio in future).

### 2.5 Security concerns

- **Today: clean.** No secrets in the repo; `requests` only talks to HuggingFace.
- **Future OpenAI risk surface**: env-var key handling, `.env` not yet gitignored,
  ensuring the key never crosses the bridge to JS, and that error signals
  (`synthesizeError.emit(request_id, str(e))`, `app/bridge.py:251`) never include
  auth headers or key material. **`str(e)` on a `requests` exception can include
  the URL and sometimes headers** — must be sanitized before emitting.
- `ui/app.js:1457` fetches arbitrary URLs from the renderer (`fetch(url)`), enabled
  by `LocalContentCanAccessRemoteUrls=True` (`app/main_window.py:98`). Acceptable
  for a user-driven "import from URL," but keep it user-initiated only.

### 2.6 Browser-compatibility concerns

- The UI runs in **one known Chromium** (bundled QtWebEngine), so cross-browser
  concerns are minimal. But: `navigator.clipboard` may be unavailable → code already
  falls back to `BridgeAPI.readClipboard()`. `MediaSession` is feature-detected.
  Keep these guards.

### 2.7 Windows / WSL / cross-platform limitations

- Heavy Windows-specific window code (`mica.py`, `win_frameless.py`) guarded by
  `sys.platform.startswith("win")`. Mica gated behind a "did it actually apply?"
  check to avoid frameless-translucency flicker on old GPUs/VMs/RDP — **do not
  enable translucency unconditionally.**
- OGG export shells out to `oggenc` if present, else falls back to WAV-in-OGG
  (`app/tts_engine.py:240`). No hard failure, but "OGG" may not be real OGG.
- The brief's `bash start.sh` / WSL assumptions don't apply; this is a native
  desktop GUI and won't run headless in WSL without a display + Chromium sandbox
  flags.

### 2.8 Areas that must not change casually (hard list)

1. `PiperReader` session/`_hardStop` semantics.
2. Piper engine cache + `_verify_piper_data_bundle`.
3. `textspeak_pro.spec` data/binary collection.
4. `text_normalize` public API (44 tests pin it).
5. QWebChannel signal/slot contract already consumed by `ui/app.js`.
6. Portable/installed path logic (`app/paths.py`).

---

## 3. Proposed architecture

Adapted to the real QWebChannel desktop app (no Flask):

```
Chromium UI (ui/index.html + ui/app.js + ui/i18n.js)
    |
    +-- Tab Manager            (ui/tabs.js)          new
    +-- Document Store         (IndexedDB)           new  -> per-tab text/state
    +-- Playback Controller    (PiperReader, extended)    keep + generalize
    +-- Audio Queue            (chunk cache/prefetch)     keep (already inside PiperReader)
    +-- Voice Provider Client  (ui/providers.js)     new  -> {piper, openai}
                |
                v  (QWebChannel signals/slots — NOT HTTP)
        Python Bridge (app/bridge.py)
            |
            +-- PiperVoiceProvider     (wraps existing TTSEngine)      keep
            +-- OpenAIVoiceProvider    (app/openai_provider.py)        new
            +-- Provider Registry      (app/providers.py)              new
            +-- Audio Cache            (app/audio_cache.py)            new -> cache/openai/<hash>
            +-- Document Storage       (optional, app/documents.py)   later -> sqlite mirror
            +-- Config Layer           (app/config.py + .env loader)   new
```

Design principles:

- **One playback controller, many providers.** `PiperReader` keeps ownership of the
  audio queue, session guards, and prefetch. Only the "how do I get bytes for this
  chunk" step is delegated to a provider client that returns `{bytes, mime}`.
  Piper → WAV, OpenAI → MP3; the Blob/`<audio>` path is provider-agnostic.
- **OpenAI lives entirely in Python.** JS calls `bridge.synthesize_openai(...)`;
  Python holds the key, calls `https://api.openai.com/v1/audio/speech` via the
  already-bundled `requests`, caches the MP3, and emits base64 back. No key ever
  enters the renderer.
- **Persistence split:** UI/document state in **IndexedDB** (fast, no per-keystroke
  registry writes, structured, searchable later). A server-side **SQLite** mirror is
  optional and deferred until search/history/audio-metadata actually need it.

---

## 4. Exact file-change plan

Legend — Risk: 🟢 low / 🟡 medium / 🔴 high (touches sensitive core).

### Phase 0 — Baseline & regression protection

| Action | File | Purpose | Risk | Deps | Tests |
| --- | --- | --- | --- | --- | --- |
| Add `.env` + build/venv extras to gitignore | `.gitignore` (modify) | Prevent future secret commits | 🟢 | — | grep repo for secrets |
| Extract pure logic for testability | `ui/lib/reader-core.js` (new, or export from `app.js`) | Make `TextChunker` + session guard testable in Node | 🟡 | — | new JS tests |
| Add JS test harness | `tests/js/` (new), `package.json` (new, dev-only) | Vitest/node tests for chunker + stale-session | 🟢 | node (dev only) | see §Tests |
| Add Python bridge/engine smoke tests | `tests/test_bridge_smoke.py`, `tests/test_engine.py` (new) | Cover cancel-token + discovery without real audio | 🟢 | pytest | green |
| Document current behavior | this file | Baseline | 🟢 | — | — |

### Phase 1 — Tabs + document-state foundation (no OpenAI)

| Action | File | Purpose | Risk | Deps | Tests |
| --- | --- | --- | --- | --- | --- |
| Tab bar + all-tabs menu markup/CSS | `ui/index.html` (modify) | Tab UI, `+`, close, overflow | 🟡 | — | manual + DOM tests |
| Tab manager + document model + IndexedDB persistence | `ui/tabs.js` (new) | Create/close/rename/duplicate/reorder/restore; per-tab state | 🟡 | — | JS unit + persistence |
| Bind editor to active tab; route play/export through active doc | `ui/app.js` (modify: `doPlay`, `doExport`, `updateStats`, boot, `input` handler) | Replace direct `#input.value` reads with active-doc accessor | 🔴 (touches playback entry) | tabs.js | JS + manual |
| Make one-tab-plays-at-a-time explicit | `ui/app.js` (modify: reader ownership; tag session with `tabId`) | Switching/closing a tab hard-stops its playback | 🔴 | PiperReader | stale-audio tests |
| New i18n keys (tabs, menus) | `ui/i18n.js` (modify) | FR+EN strings | 🟢 | — | i18n coverage check |
| Migrate legacy `saved_text` → Tab 1 on first run | `ui/tabs.js` (modify) | No data loss on upgrade | 🟢 | — | upgrade test |

Phase 1 is **frontend-only** by design (IndexedDB), so the sensitive Python bridge
and packaging are untouched. `PiperReader` internals are *extended* (add `tabId` to
the session) but its guard semantics are preserved.

### Phase 2 — Provider abstraction (still Piper only)

| Action | File | Purpose | Risk | Deps | Tests |
| --- | --- | --- | --- | --- | --- |
| Provider client interface | `ui/providers.js` (new) | `listVoices/validate/synthesize/cancel/supportsStreaming/supportsOffline` | 🟡 | — | JS unit |
| Route chunk fetch through provider | `ui/app.js` (modify `_ensureChunkLoaded` to call provider, return `{bytes,mime}`) | Decouple playback from Piper | 🔴 | providers.js | stale-audio + regression |
| Python provider registry + Piper wrapper | `app/providers.py`, `app/piper_provider.py` (new; wrap `TTSEngine`) | Shared shape for future providers | 🟡 | tts_engine | pytest |

### Phase 3 — OpenAI backend integration

| Action | File | Purpose | Risk | Deps | Tests |
| --- | --- | --- | --- | --- | --- |
| Config layer + `.env` loader | `app/config.py` (new) | Load `OPENAI_API_KEY`, `OPENAI_TTS_MODEL`, default voice; never log key | 🟡 | (optional python-dotenv, or built-in parser) | pytest |
| `.env.example` | `.env.example` (new) | Safe template (empty key) | 🟢 | — | — |
| OpenAI provider | `app/openai_provider.py` (new) | Call `/v1/audio/speech` via `requests`; sanitize errors | 🟡 | requests (bundled) | mocked pytest |
| Bridge slots + signals | `app/bridge.py` (modify) | `synthesize_openai(...)`, `openai_status()`, `openaiSynthesizeReady/Error` | 🟡 | openai_provider, config | mocked pytest |
| Provider selector + status UI | `ui/index.html`, `ui/app.js`, `ui/i18n.js` (modify) | Engine toggle, "Configured / not configured", offline/charges badges | 🟢 | providers.js | manual |
| Packaging: ensure `.env` **not** bundled; deps present | `textspeak_pro.spec` (modify only if adding python-dotenv) | Keep exe clean | 🟡 | — | build check |

### Phase 4 — Long-text generation

| Action | File | Purpose | Risk | Deps | Tests |
| --- | --- | --- | --- | --- | --- |
| Semantic chunker (section→para→sentence→clause→char) with protected spans (decimals, dates, initials, abbrevs, URLs, emails) | `ui/lib/semantic-chunker.js` (new) + `app/chunking.py` (new, mirror for export) | Robust boundaries; configurable limits | 🟡 | — | extensive JS/py unit |
| Progress/cancel/retry/resume for OpenAI chunks | `ui/app.js`, `app/openai_provider.py` (modify) | "section 4 of 12", retry failed chunk | 🔴 | providers | stale + retry tests |

### Phase 5 — Audio export

| Action | File | Purpose | Risk | Deps | Tests |
| --- | --- | --- | --- | --- | --- |
| OpenAI export (full + selection) + join strategy | `app/bridge.py`, `app/openai_provider.py` (modify) | `Generate Audio File` for OpenAI | 🟡 | cache | mocked pytest |
| Audio cache module | `app/audio_cache.py` (new) | content-hash cache, size accounting, clear-by-tab | 🟡 | paths | pytest |
| Cache management UI | `ui/index.html`, `ui/app.js` (modify) | size, clear OpenAI/Piper, per-tab | 🟢 | — | manual |

### Phase 6 — Playback & highlighting

| Action | File | Purpose | Risk | Deps | Tests |
| --- | --- | --- | --- | --- | --- |
| Sentence/paragraph nav, seek intervals, elapsed/remaining | `ui/app.js`, `ui/index.html` (modify) | Richer transport | 🔴 | reader | regression |
| Sentence-level highlight + optional auto-scroll | `ui/app.js` (modify `updateHighlight`) | Better sync | 🟡 | chunker | manual |

### Phase 7 — Smart reading & pronunciation

| Action | File | Purpose | Risk | Deps | Tests |
| --- | --- | --- | --- | --- | --- |
| Pronunciation dictionary (global + per-doc) | `app/pronunciation.py` (new), `ui/app.js`, `ui/tabs.js` (modify) | Non-destructive narration substitutions + preview | 🟡 | normalizer | pytest |
| Smart tools (clean/translate/summarize/explain) → new tab | `app/openai_provider.py`, `ui/app.js` (modify) | Optional, preview-then-accept, never mutate original | 🟡 | openai | mocked |
| Speaking-style presets | `app/speaking_styles.py` or `voice_catalog`-style JSON (new) | Central preset→instruction map | 🟢 | — | pytest |

### Phase 8 — UI polish / accessibility / shortcuts

| `ui/index.html`, `ui/app.js`, `ui/i18n.js` (modify), plus a shortcuts help dialog. 🟢/🟡 |

### Phase 9 — Regression & release

| `README.md`, `tests/*`, security review, installer/version bumps. 🟢 |

---

## 5. Phased implementation plan (summary + order)

- **Phase 0 — Baseline & regression protection.** Green tests, gitignore `.env`,
  add JS + bridge smoke tests that *lock in* stale-session/cancel behavior before
  touching anything.
- **Phase 1 — Tabs + persistence (frontend/IndexedDB only).** Highest user value,
  lowest backend risk. No OpenAI.
- **Phase 2 — Provider abstraction.** Wrap Piper; keep playback identical.
- **Phase 3 — OpenAI backend (bridge slot, config, status).** Short-text only,
  mocked tests.
- **Phase 4 — Long-text semantic chunking + progress/cancel/retry/cache.**
- **Phase 5 — Audio export for OpenAI + cache management.**
- **Phase 6 — Playback + highlighting improvements.**
- **Phase 7 — Smart reading + pronunciation + speaking styles.**
- **Phase 8 — UI/accessibility/shortcuts polish.**
- **Phase 9 — Full regression + release prep.**

Each phase must remain **buildable, runnable, and testable**, and must not remove
any existing feature (Piper, cursor reading, bookmarks, FR support, speed/volume,
imports, stale-session protection).

---

## 6. Acceptance criteria (measurable, per phase)

- **Phase 0:** `pytest` = 44+ green; new JS tests prove: after `stop()`/new
  `start()`, a late-resolving previous-session chunk never sets `<audio>.src` and is
  URL-revoked; `cancel(request_id)` prevents `synthesizeReady` emission. Repo secret
  scan returns 0.
- **Phase 1:** Can create ≥5 tabs; rename/duplicate/reorder/close work; switching
  tabs preserves each tab's text, cursor, scroll, and voice/speed/volume; after full
  app restart all tabs + active tab restore; closing a playing tab stops its audio
  within one session tick and no audio from a closed tab ever plays. No per-keystroke
  registry writes (verified: writes are debounced/IndexedDB).
- **Phase 2:** With only Piper, behavior is byte-for-byte equivalent to today
  (same chunking, same stale guards); provider client passes unit tests.
- **Phase 3:** `openai_status()` returns `Configured`/`API key not configured` with
  **no key material**; with a mocked key, a short string returns playable MP3;
  with no key, UI shows the offline/retry message and Piper still works; grep of
  built artifact + logs shows no key/`Authorization`.
- **Phase 4:** A 50k-char document generates sequentially with visible
  "section N of M", supports cancel (no orphan audio), retries a forced-failed
  chunk, and never plays a stale chunk; chunk boundaries never split a decimal,
  date, initial, listed abbreviation, URL, or email (unit-tested corpus).
- **Phase 5:** Identical (text+provider+model+voice+style+format) request is served
  from cache (no network call, asserted via mock); changing voice or instructions
  produces a cache miss; cache size is reported and clearable per-tab; clearing
  audio never deletes tab text.
- **Phase 6:** Highlight stays synchronized across pause/resume/seek/skip/speed
  change/cursor-start/tab-switch/restart; auto-scroll toggle honored.
- **Phase 7:** Pronunciation rules change spoken output but never the visible
  editor text; smart transforms always land in a new tab after a preview+confirm.
- **Phase 8:** WCAG-AA contrast in both themes; all controls keyboard reachable
  with visible focus; shortcuts dialog lists every binding; no UI freeze during
  generation.
- **Phase 9:** Full manual checklist + automated suite green; security review clean;
  README updated with OpenAI setup + upgrade/rollback notes.

---

## 7. Open questions and assumptions

**Assumptions (safe to proceed on):**

- OpenAI calls go through a **QWebChannel bridge slot**, not an HTTP endpoint
  (dictated by the real architecture). The brief's `/api/openai/synthesize` is
  interpreted as this slot.
- Persistence is **IndexedDB in the renderer, local-only forever** (confirmed by
  user). No server-side SQLite document store will be built; `AudioAsset` metadata
  also lives in IndexedDB. This keeps the privacy-first promise and avoids touching
  sensitive Python paths. (The current per-keystroke `QSettings.sync()` is unsuitable
  for multi-tab autosave anyway.)
- OpenAI HTTP uses the already-bundled **`requests`** (no new heavy SDK) plus a
  **tiny built-in `.env` parser** (no `python-dotenv` dependency) — chosen default to
  keep the frozen exe lean and the PyInstaller spec untouched.
- Model/voice defaults come from config (`gpt-4o-mini-tts`, `coral`) and are
  overridable via env; exact model/voice/limits will be re-verified against current
  OpenAI docs at Phase-3 implementation time (not hard-coded permanently).

**Decisions (resolved with the user — 2026-08-03):**

1. **OpenAI account & budget — RESOLVED.** A key is available. No hard spend cap;
   use **warning-only cost awareness** with the configurable safeguards from
   Feature 18 (max chars per job, confirm-above-threshold, max concurrent jobs,
   cancellation, daily local usage stats, no background regeneration). A hard cap
   can be added later if requested.
2. **Persistence scope — RESOLVED.** **Local-only forever.** IndexedDB is the single
   source of truth for documents + `AudioAsset` metadata. `documents.py` / server
   SQLite is **out of scope** and removed from the plan.
3. **Audio storage location — RESOLVED (default chosen).** Two distinct locations:
   - **Reusable OpenAI cache** (internal, content-hash-named, deduped): lives under
     the portable-aware app data dir at **`<data>/cache/audio/`** (via
     `app/paths.py`; sits next to the exe in portable mode). Not user-facing;
     managed/cleared from Settings.
   - **User "Generate Audio File" exports** (deliverables the user keeps): default
     output folder **`<Music>/TextSpeak Pro/`** — i.e. `%USERPROFILE%\Music\TextSpeak Pro`
     on Windows, `~/Music/TextSpeak Pro` on macOS/Linux (XDG `XDG_MUSIC_DIR` when
     set), auto-created on first export. In **portable mode** it defaults to
     `<exe_dir>/audio/` to keep everything self-contained. Always overridable via the
     Save dialog, with the last-used folder remembered (`last_export_dir`, existing).
4. **Dependency tolerance — RESOLVED (default chosen).** Keep it minimal: bundled
   `requests` + a small built-in `.env` parser. No new heavy SDK, no change to
   `textspeak_pro.spec`.
5. **AI-voice disclosure & branding — RESOLVED (choice made).** Reframe the tagline
   from "100% offline" to **"Offline-first"**: Piper remains the default and the app
   is **fully usable with zero internet**. OpenAI is presented as a clearly-labeled,
   opt-in **"Online voice (OpenAI)"** provider carrying badges — *Requires internet ·
   May incur OpenAI charges · AI-generated voice* — plus a one-time disclosure notice
   in the provider panel ("This voice is generated by AI via OpenAI; it is not a
   recording of a real person"). README updated accordingly: *"100% offline with
   Piper; optional high-quality OpenAI voices when you want them."* No voice cloning
   or impersonation (per Feature 19).

**Remaining open questions:** none blocking. All items required to start Phase 0 and
Phase 1 are resolved.

---

## Appendix A — Concise summary of the existing application

TextSpeak Pro is a polished **offline neural TTS desktop app** (PySide6 + embedded
Chromium via QWebChannel — **not** Flask). A single `<textarea>` feeds a
session-guarded JS playback engine (`PiperReader`) that chunks text (~450 chars at
natural boundaries), prefetches the next chunk, and plays WAV produced off-thread by
a cached Piper engine in Python. It supports play/pause/resume/stop/restart, skip,
cursor-start & double-click reading, speed/volume, voice catalog download from
HuggingFace, MP3/WAV/OGG export (+ batch by paragraph), bookmarks, presets, recent
files, drag-and-drop and clipboard/URL/PDF import, full EN/FR i18n, light/dark/system
themes with Win11 Mica, system tray, media-key control, and a markdown-aware
speech normalizer (the only tested module: 44/44 green).

## Appendix B — Files that would change in Phase 1

- `ui/index.html` — tab bar, `+` button, per-tab close, overflow/all-tabs menu, CSS.
- `ui/tabs.js` *(new)* — tab manager, document model, IndexedDB persistence,
  legacy `saved_text` migration.
- `ui/app.js` — bind editor + `doPlay`/`doExport`/`updateStats`/boot/`input` handler
  to the active document; tag `PiperReader` sessions with `tabId`; hard-stop on tab
  switch/close.
- `ui/i18n.js` — new EN + FR strings for tabs/menus.
- `.gitignore` — already covered in Phase 0 (`.env`).

*(No Python bridge, engine, or packaging changes in Phase 1 — deliberately.)*

## Appendix C — Tests that must pass before Phase 1 begins

1. `pytest -q tests/` → **44 passed** (already verified this pass).
2. New Phase-0 JS tests (must be added and green first):
   - `TextChunker.chunk` preserves offsets and never emits empty chunks.
   - After `reader.stop()` then a new `reader.start()`, a late resolve of the old
     session's chunk does **not** set `<audio>.src` and its object URL is revoked.
   - `reader.skip()` during an in-flight prefetch produces exactly one live session.
   - `BridgeAPI.cancel(request_id)` prevents a `synthesizeReady` from resolving a
     pending promise.
3. New Phase-0 Python smoke tests green:
   - `TTSEngine.discover_voices()` on an empty voices dir returns `[]` (no crash).
   - `Bridge.cancel` flips the matching `CancelToken` and is a no-op for unknown ids.
4. Manual regression checklist recorded (Piper play, cursor read, bookmarks, FR
   voice, speed/volume, import) — baseline before any tab work.

## Appendix D — Blockers requiring user input

**None.** All five §7 items are resolved (2026-08-03): OpenAI key available
(warning-only cost safeguards), documents stay local-only forever, audio cache →
`<data>/cache/audio/` and exports default to `<Music>/TextSpeak Pro/`, minimal
dependencies (requests + built-in `.env` parser), and "offline-first" branding with
an opt-in AI-voice disclosure. Phase 0 and Phase 1 are ready to begin.
