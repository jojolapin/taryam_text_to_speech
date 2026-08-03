/* TextSpeak Pro - webview app logic
 * (C) 2026 JojoLapin Inc. All rights reserved.
 * Bridges Chromium <-> Python (PySide6) via QWebChannel. No HTTP, no server.
 */
'use strict';

/* =======================================================================
   Logger (in-page, with listener hook for the debug panel)
======================================================================= */
const Logger = (() => {
  const buffer = [];
  const MAX = 500;
  const listeners = [];
  function log(level, ...args) {
    const t = new Date();
    const time = t.toTimeString().slice(0, 8) + '.' + String(t.getMilliseconds()).padStart(3, '0');
    const msg = args.map(a => typeof a === 'string' ? a : JSON.stringify(a)).join(' ');
    const entry = { time, level, msg };
    buffer.push(entry);
    if (buffer.length > MAX) buffer.shift();
    (console[level] || console.log)(`[${time}] ${msg}`);
    listeners.forEach(fn => { try { fn(entry); } catch {} });
  }
  return {
    debug: (...a) => log('debug', ...a),
    info:  (...a) => log('info',  ...a),
    warn:  (...a) => log('warn',  ...a),
    error: (...a) => log('error', ...a),
    onEntry(fn) { listeners.push(fn); },
    getAll() { return buffer.slice(); },
    clear() { buffer.length = 0; listeners.forEach(fn => { try { fn(null); } catch {} }); }
  };
})();

/* =======================================================================
   TextChunker - loaded from lib/text-chunker.js (window.TextChunker).
   Extracted for unit testing; behaviour is unchanged. See tests/js/.
======================================================================= */

/* =======================================================================
   Base64 -> Blob helper
======================================================================= */
function b64ToBlob(b64, mime = 'audio/wav') {
  const bin = atob(b64);
  const len = bin.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i++) bytes[i] = bin.charCodeAt(i);
  return new Blob([bytes], { type: mime });
}

/* =======================================================================
   BridgeAPI: promise-wrapped QWebChannel bridge
======================================================================= */
const BridgeAPI = (() => {
  let bridge = null;
  let rid = 0;
  const pending = new Map();       // id -> { resolve, reject }
  const exportListeners = new Set();
  const catalogListeners = new Set();
  const sampleWaiters = new Map();
  const dropListeners = new Set();
  const themeListeners = new Set();
  const langListeners = new Set();
  const voicesChangedListeners = new Set();
  const readClipListeners = new Set();
  const stopListeners = new Set();

  function nextId(prefix) { return prefix + '-' + (++rid); }

  function connect() {
    return new Promise((resolve) => {
      /* eslint-disable no-undef */
      new QWebChannel(qt.webChannelTransport, (channel) => {
        bridge = channel.objects.bridge;
        wireSignals();
        resolve(bridge);
      });
      /* eslint-enable no-undef */
    });
  }

  function wireSignals() {
    bridge.synthesizeReady.connect((id, b64) => {
      const p = pending.get(id); if (!p) return;
      pending.delete(id);
      p.resolve({ wavB64: b64 });
    });
    bridge.synthesizeError.connect((id, msg) => {
      const p = pending.get(id); if (!p) return;
      pending.delete(id);
      p.reject(new Error(msg));
    });
    bridge.exportProgress.connect((id, stage, ratio) => {
      exportListeners.forEach(fn => fn({ id, type: 'progress', stage, ratio }));
    });
    bridge.exportDone.connect((id, path, audioSec, synthSec) => {
      exportListeners.forEach(fn => fn({ id, type: 'done', path, audioSec, synthSec }));
    });
    bridge.exportError.connect((id, msg) => {
      exportListeners.forEach(fn => fn({ id, type: 'error', message: msg }));
    });
    bridge.catalogProgress.connect((id, done, total) => {
      catalogListeners.forEach(fn => fn({ id, type: 'progress', done, total }));
    });
    bridge.catalogDone.connect((id, voiceId) => {
      catalogListeners.forEach(fn => fn({ id, type: 'done', voiceId }));
    });
    bridge.catalogError.connect((id, msg) => {
      catalogListeners.forEach(fn => fn({ id, type: 'error', message: msg }));
    });
    bridge.sampleReady.connect((id, voiceId, b64) => {
      const waiter = sampleWaiters.get(id); if (!waiter) return;
      sampleWaiters.delete(id);
      waiter({ voiceId, b64 });
    });
    bridge.themeChanged.connect((scheme) => themeListeners.forEach(fn => fn(scheme)));
    bridge.languageChanged.connect((lang) => langListeners.forEach(fn => fn(lang)));
    bridge.voicesChanged.connect(() => voicesChangedListeners.forEach(fn => fn()));
    bridge.fileDropped.connect((pathsJson) => {
      let paths = [];
      try { paths = JSON.parse(pathsJson); } catch {}
      dropListeners.forEach(fn => fn(paths));
    });
    bridge.readClipboardRequested.connect(() => readClipListeners.forEach(fn => fn()));
    bridge.stopRequested.connect(() => stopListeners.forEach(fn => fn()));
  }

  return {
    connect,
    get raw() { return bridge; },
    appInfo() { return bridge.app_info().then(JSON.parse); },
    listVoices() { return bridge.list_voices().then(JSON.parse); },
    getPrefs() { return bridge.get_prefs().then(JSON.parse); },
    setPref(k, v) { return bridge.set_pref(k, v); },
    setPortable(v) { return bridge.set_portable(v); },

    synthesize(text, voice, lengthScale, volume, textFormat) {
      const id = nextId('s');
      return new Promise((resolve, reject) => {
        pending.set(id, { resolve, reject });
        bridge.synthesize(text, voice, lengthScale, volume, id, textFormat || 'plain');
      });
    },
    cancelSynthesize(id) { if (id) bridge.cancel(id); },

    normalizeText(text, textFormat) {
      return bridge.normalize_text(text || '', textFormat || 'auto').then(JSON.parse);
    },

    exportAudio(text, voice, fmt, lengthScale, volume, bitrate, author, suggestedName, textFormat) {
      const id = nextId('e');
      bridge.export_audio(text, voice, fmt, lengthScale, volume, bitrate, author || '', suggestedName || '', id, textFormat || 'plain');
      return id;
    },
    batchExport(paragraphs, voice, fmt, lengthScale, volume, bitrate, author, prefix, textFormat) {
      const id = nextId('b');
      bridge.batch_export(JSON.stringify(paragraphs), voice, fmt, lengthScale, volume, bitrate, author || '', prefix || 'part', id, textFormat || 'plain');
      return id;
    },
    onExport(fn) { exportListeners.add(fn); return () => exportListeners.delete(fn); },

    catalogList() { return bridge.catalog_list().then(JSON.parse); },
    catalogRefresh() {
      const id = nextId('cr');
      bridge.catalog_refresh(id); return id;
    },
    catalogDownload(voiceId) {
      const id = nextId('cd');
      bridge.catalog_download(voiceId, id); return id;
    },
    catalogCancel(id) { bridge.catalog_cancel(id); },
    catalogDelete(voiceId) { return bridge.catalog_delete(voiceId); },
    onCatalog(fn) { catalogListeners.add(fn); return () => catalogListeners.delete(fn); },

    playSample(voiceId) {
      const id = nextId('sm');
      return new Promise((resolve) => {
        sampleWaiters.set(id, resolve);
        bridge.catalog_play_sample(voiceId, id);
      });
    },

    openVoicesFolder() { bridge.open_voices_folder(); },
    openLogsFolder() { bridge.open_logs_folder(); },
    openDataFolder() { bridge.open_data_folder(); },

    readTextFile(path) { return bridge.read_text_file(path).then(JSON.parse); },
    readClipboard() { return bridge.read_clipboard(); },
    setClipboard(text) { bridge.set_clipboard(text); },

    recentFiles() { return bridge.recent_files().then(JSON.parse); },
    recentClear() { bridge.recent_clear(); },

    presetsList() { return bridge.presets_list().then(JSON.parse); },
    presetSave(name, data) { bridge.preset_save(name, JSON.stringify(data)); },
    presetDelete(name) { bridge.preset_delete(name); },

    minimize() { bridge.minimize_window(); },
    toggleMaximize() { bridge.toggle_maximize(); },
    close() { bridge.close_window(); },
    quit() { bridge.quit_app(); },
    beginDrag() { bridge.begin_window_drag(); },
    beginResize(edges) { bridge.begin_window_resize(edges); },

    onThemeChanged(fn) { themeListeners.add(fn); return () => themeListeners.delete(fn); },
    onLanguageChanged(fn) { langListeners.add(fn); return () => langListeners.delete(fn); },
    onVoicesChanged(fn) { voicesChangedListeners.add(fn); return () => voicesChangedListeners.delete(fn); },
    onFileDropped(fn) { dropListeners.add(fn); return () => dropListeners.delete(fn); },
    onReadClipboardRequested(fn) { readClipListeners.add(fn); return () => readClipListeners.delete(fn); },
    onStopRequested(fn) { stopListeners.add(fn); return () => stopListeners.delete(fn); },
  };
})();

/* =======================================================================
   PiperReader - loaded from lib/piper-reader.js (window.PiperReader).
   Session-guarded, prefetched playback pipeline. Extracted verbatim (with a
   dependency-injection seam) so the session/stale-audio guarantees can be
   regression-tested under Node. See tests/js/piper-reader.test.js.
======================================================================= */

/* =======================================================================
   UI
======================================================================= */
const $  = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

let APP_INFO = null;
let PREFS = null;
let AVAILABLE_VOICES = [];
const reader = new PiperReader();

/* ---------- Markdown mode (client-side pill + format plumbing) ---------- */
const MarkdownMode = (() => {
  // Cheap signal detection — mirrors the more thorough one in text_normalize.py
  // so the pill lights up as soon as the user types/pastes markdown.
  const _RX_HEADING = /^[ \t]{0,3}#{1,6}[ \t]+\S/m;
  const _RX_LIST    = /^[ \t]{0,8}(?:[-*+]|\d{1,3}[.)])[ \t]+\S/m;
  const _RX_FENCE   = /^[ \t]{0,3}(?:```+|~~~+)/m;
  const _RX_EMPH    = /\*\*\S|__\S|(?<!\w)\*\S|(?<!\w)_\S/;
  const _RX_LINK    = /\[[^\]\n]+\]\([^)\s]+\)/;
  const _RX_TABLE   = /^[ \t]{0,3}\|?[ \t]*:?-{3,}:?[ \t]*\|/m;

  function sniff(text) {
    if (!text) return false;
    const sample = text.slice(0, 8000);
    let hits = 0;
    for (const rx of [_RX_HEADING, _RX_LIST, _RX_FENCE, _RX_EMPH, _RX_LINK, _RX_TABLE]) {
      if (rx.test(sample)) { hits += 1; if (hits >= 2) return true; }
    }
    return false;
  }

  let state = {
    mode: 'auto',          // auto | on | off
    sourceHint: null,      // null | 'markdown' | 'html' | 'plain' (from file import)
    detected: false,       // last sniff result
  };

  function isEffectivelyOn() {
    if (state.mode === 'on') return true;
    if (state.mode === 'off') return false;
    // auto
    return state.sourceHint === 'markdown' || state.detected;
  }

  function effectiveFormat() {
    if (state.mode === 'off') return 'plain';
    if (state.mode === 'on') return 'markdown';
    if (state.sourceHint === 'markdown') return 'markdown';
    if (state.sourceHint === 'html') return 'html';
    if (state.detected) return 'markdown';
    return 'plain';
  }

  function updatePill() {
    const pill = document.getElementById('chipMarkdown');
    if (!pill) return;
    // Visible only when mode is on/off OR when markdown has been detected
    const visible = state.mode !== 'auto' || state.detected || state.sourceHint === 'markdown';
    pill.hidden = !visible;
    pill.classList.remove('on', 'off', 'auto');
    const on = isEffectivelyOn();
    if (state.mode === 'on') pill.classList.add('on');
    else if (state.mode === 'off') pill.classList.add('off');
    else pill.classList.add(on ? 'on' : 'auto');

    let titleKey;
    if (state.mode === 'on') titleKey = 'hdr.md.title.on';
    else if (state.mode === 'off') titleKey = 'hdr.md.title.off';
    else titleKey = 'hdr.md.title.auto';
    pill.title = I18N.t(titleKey, { state: on ? 'ON' : 'OFF' });
  }

  function refresh(text) {
    state.detected = sniff(text || '');
    updatePill();
  }

  function setMode(mode) {
    if (!['auto', 'on', 'off'].includes(mode)) mode = 'auto';
    state.mode = mode;
    const mdSel = document.getElementById('mdMode');
    if (mdSel && mdSel.value !== mode) mdSel.value = mode;
    updatePill();
  }

  function setSourceHint(fmt) {
    state.sourceHint = (fmt === 'markdown' || fmt === 'html') ? fmt : null;
    updatePill();
  }

  function cycle() {
    const next = state.mode === 'auto' ? 'on' : state.mode === 'on' ? 'off' : 'auto';
    setMode(next);
    BridgeAPI.setPref('markdown_mode', next);
    const toastKey = next === 'on' ? 'toast.md.on' : next === 'off' ? 'toast.md.off' : 'toast.md.auto';
    toast(I18N.t(toastKey), next === 'off' ? '' : 'success', 1800);
  }

  return {
    refresh, setMode, setSourceHint, cycle, updatePill,
    get mode() { return state.mode; },
    get effective() { return effectiveFormat(); },
    get isOn() { return isEffectivelyOn(); },
  };
})();

/* ---------- Toast ---------- */
let toastTimer = null;
function toast(msg, type = '', ms = 2800) {
  const el = $('#toast');
  el.textContent = msg;
  el.className = 'toast show' + (type ? ' ' + type : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), ms);
}

/* ---------- Theme + language wiring ---------- */
function effectiveTheme(pref) {
  if (pref === 'light' || pref === 'dark') return pref;
  return (APP_INFO && APP_INFO.system_theme) || 'dark';
}
function applyTheme(pref) {
  const theme = effectiveTheme(pref);
  document.documentElement.setAttribute('data-theme', theme);
  document.body.setAttribute('data-theme', theme);
}
function applyLang(pref) {
  let lang = pref;
  if (pref === 'system' || !pref) lang = (APP_INFO && APP_INFO.system_lang) || 'en';
  if (lang !== 'en' && lang !== 'fr') lang = 'en';
  I18N.setLang(lang);
  I18N.applyAll();
  // Re-render dynamic bits
  renderRecent();
  renderBookmarks();
  renderPresets();
  renderCatalog();
  MarkdownMode.updatePill();
}

/* ---------- Voices ---------- */
async function loadInstalledVoices() {
  try {
    const voices = await BridgeAPI.listVoices();
    if (voices && voices.error) {
      toast(voices.error, 'error', 5000);
      AVAILABLE_VOICES = [];
    } else {
      AVAILABLE_VOICES = Array.isArray(voices) ? voices : [];
    }
  } catch (e) {
    Logger.error('list_voices failed: ' + e.message);
    AVAILABLE_VOICES = [];
  }
  populateVoiceSelect();
  const noVoices = AVAILABLE_VOICES.length === 0;
  $('#noVoices').classList.toggle('visible', noVoices);
  $('#playBtn').disabled = noVoices;
  $('#playFromCursor').disabled = noVoices;
  if (noVoices && !PREFS.wizard_complete) showWizard();
}

function populateVoiceSelect() {
  const sel = $('#voiceSelect');
  sel.innerHTML = '';
  if (!AVAILABLE_VOICES.length) {
    const opt = document.createElement('option');
    opt.textContent = I18N.t('set.voice.none');
    sel.appendChild(opt);
    return;
  }
  const groups = {};
  AVAILABLE_VOICES.forEach(v => {
    const k = (v.language || 'other').toUpperCase();
    (groups[k] ||= []).push(v);
  });
  Object.keys(groups).sort().forEach(k => {
    const og = document.createElement('optgroup');
    og.label = k;
    groups[k].forEach(v => {
      const o = document.createElement('option');
      o.value = v.id;
      o.textContent = `${v.name} (${v.language || '?'})`;
      og.appendChild(o);
    });
    sel.appendChild(og);
  });
  const savedVoice = PREFS && PREFS.last_voice;
  if (savedVoice && AVAILABLE_VOICES.some(v => v.id === savedVoice)) sel.value = savedVoice;
}

/* ---------- Stats ---------- */
function updateStats() {
  const text = $('#input').value || '';
  const words = text.trim() ? text.trim().split(/\s+/).length : 0;
  $('#wordCount').textContent = words.toLocaleString();
  $('#charCount').textContent = text.length.toLocaleString();
  // Reading time at current speed
  const rate = parseFloat($('#rateSlider').value) || 1;
  $('#readTime').textContent = Math.max(1, Math.ceil(words / (200 * rate)));
  if ($('#hlToggle').checked) { $('#render').classList.add('visible'); $('#render').textContent = text; }
}

/* ---------- Player controls ---------- */
function getOpts() {
  return {
    voice: $('#voiceSelect').value,
    rate: parseFloat($('#rateSlider').value) || 1,
    volume: parseFloat($('#volumeSlider').value) || 1,
    textFormat: MarkdownMode.effective,
  };
}
function doPlay(fromPosition = 0) {
  const text = $('#input').value;
  if (!text.trim()) { toast(I18N.t('toast.noText')); return; }
  const voice = $('#voiceSelect').value;
  if (!voice || voice === 'Loading voices...' || !AVAILABLE_VOICES.some(v => v.id === voice)) {
    toast(I18N.t('toast.noVoice'), 'error');
    return;
  }
  BridgeAPI.setPref('last_voice', voice);
  BridgeAPI.setPref('last_speed', parseFloat($('#rateSlider').value));
  BridgeAPI.setPref('last_volume', parseFloat($('#volumeSlider').value));
  if ($('#hlToggle').checked) { $('#render').classList.add('visible'); updateHighlight(fromPosition); }
  reader.start(text, getOpts(), fromPosition);
}
function updateButtons(state) {
  const active = state === 'loading' || state === 'playing' || state === 'paused';
  $('#playBtn').disabled = active || AVAILABLE_VOICES.length === 0;
  $('#playFromCursor').disabled = active || AVAILABLE_VOICES.length === 0;
  $('#pauseBtn').disabled = state !== 'playing';
  $('#resumeBtn').disabled = state !== 'paused';
  $('#stopBtn').disabled = !active;
  $('#restartBtn').disabled = !active;
  $('#skipBack').disabled = !active;
  $('#skipForward').disabled = !active;
}

/* ---------- Highlight ---------- */
function updateHighlight(pos) {
  if (!$('#hlToggle').checked) return;
  const text = $('#input').value;
  pos = Math.max(0, Math.min(pos, text.length));
  let left = pos, right = pos;
  while (left > 0 && /[\w\u00C0-\u017F'-]/.test(text[left - 1])) left--;
  while (right < text.length && /[\w\u00C0-\u017F'-]/.test(text[right])) right++;
  $('#render').innerHTML =
    escapeHtml(text.slice(0, left)) +
    '<mark class="hl">' + (escapeHtml(text.slice(left, right)) || '&nbsp;') + '</mark>' +
    escapeHtml(text.slice(right));
  if ($('#autoScroll').checked) {
    const mark = $('#render').querySelector('.hl');
    if (mark) mark.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
}
function clearHighlight() { if ($('#hlToggle').checked) $('#render').textContent = $('#input').value; }

/* ---------- Drawers ---------- */
function closeAllDrawers() { $$('.drawer').forEach(d => d.classList.remove('open')); }
function openDrawer(id) {
  closeAllDrawers();
  $('#' + id).classList.add('open');
}

/* ---------- Status ---------- */
function setStatus(state, reason) {
  const s = $('#status');
  s.className = 'status ' + state;
  const map = {
    loading: 'status.loading',
    playing: 'status.playing',
    paused: 'status.paused',
    done: 'status.done',
    idle: 'status.idle',
    error: 'status.error',
    ready: 'status.ready',
  };
  const key = map[state] || 'status.ready';
  $('#statusText').textContent = I18N.t(key);
  $('#statusDetail').textContent = reason || '';
}

/* ---------- Import ---------- */
async function loadTextFromFile(path, nameHint) {
  try {
    const res = await BridgeAPI.readTextFile(path);
    if (res.error) throw new Error(res.error);
    $('#input').value = res.text || '';
    MarkdownMode.setSourceHint(res.format || 'plain');
    MarkdownMode.refresh(res.text || '');
    updateStats();
    toast(I18N.t('toast.fileLoaded', { name: res.name || nameHint || path }), 'success');
    closeAllDrawers();
    renderRecent();
  } catch (e) {
    toast(I18N.t('toast.fileReadError', { error: e.message }), 'error', 4000);
  }
}

function renderRecent() {
  const host = $('#recentList');
  BridgeAPI.recentFiles().then(list => {
    if (!list.length) {
      host.innerHTML = `<span style="color:var(--muted);font-size:12px">${escapeHtml(I18N.t('imp.recent.empty'))}</span>`;
      return;
    }
    host.innerHTML = list.map(p => {
      const parts = p.split(/[\\/]/);
      const name = parts[parts.length - 1];
      const parent = parts.slice(0, -1).join('/');
      return `<div class="recent-item" data-path="${escapeHtml(p)}">
        <span>&#128196;</span>
        <div><div class="name">${escapeHtml(name)}</div><div class="path">${escapeHtml(parent)}</div></div>
      </div>`;
    }).join('');
    host.querySelectorAll('.recent-item').forEach(el => {
      el.addEventListener('click', () => loadTextFromFile(el.dataset.path));
    });
  });
}

/* ---------- Bookmarks (stored in prefs via JSON key) ---------- */
let BOOKMARKS = [];
function loadBookmarks() {
  BOOKMARKS = PREFS && PREFS.bookmarks ? (function () { try { return JSON.parse(PREFS.bookmarks); } catch { return []; } })() : [];
}
function saveBookmarks() {
  BridgeAPI.setPref('bookmarks', JSON.stringify(BOOKMARKS));
}
function renderBookmarks() {
  const host = $('#bookmarkList');
  if (!BOOKMARKS.length) {
    host.innerHTML = `<span style="color:var(--muted);font-size:12px">${escapeHtml(I18N.t('bm.empty'))}</span>`;
    return;
  }
  host.innerHTML = BOOKMARKS.map(b => `
    <div class="bookmark" data-id="${b.id}" data-pos="${b.position}">
      <span>&#128205;</span>
      <span class="preview">${escapeHtml(b.preview)}</span>
      <span class="del" data-id="${b.id}">&times;</span>
    </div>`).join('');
  host.querySelectorAll('.bookmark').forEach(el => {
    el.addEventListener('click', e => {
      if (e.target.classList.contains('del')) return;
      const pos = parseInt(el.dataset.pos, 10);
      $('#input').focus();
      $('#input').setSelectionRange(pos, pos);
      doPlay(pos);
    });
  });
  host.querySelectorAll('.del').forEach(el => {
    el.addEventListener('click', e => {
      e.stopPropagation();
      const id = parseInt(el.dataset.id, 10);
      BOOKMARKS = BOOKMARKS.filter(b => b.id !== id);
      saveBookmarks();
      renderBookmarks();
      toast(I18N.t('toast.bookmarkRemoved'));
    });
  });
}

/* ---------- Debug log ---------- */
function wireDebugLog() {
  const host = $('#debugLog');
  Logger.onEntry(entry => {
    if (!entry) { host.innerHTML = ''; return; }
    const div = document.createElement('div');
    div.className = 'log-line';
    div.innerHTML = `<span class="log-time">${entry.time}</span><span class="log-level-${entry.level}">[${entry.level}]</span> ${escapeHtml(entry.msg)}`;
    host.appendChild(div);
    host.scrollTop = host.scrollHeight;
    while (host.children.length > 500) host.removeChild(host.firstChild);
  });
}

/* ---------- Export overlay ---------- */
let exportActiveId = null;
let exportTimer = null;
function formatDuration(seconds) {
  seconds = Math.max(0, Math.round(seconds));
  if (seconds < 60) return seconds + 's';
  const m = Math.floor(seconds / 60), s = seconds % 60;
  return m + 'm ' + String(s).padStart(2, '0') + 's';
}
function openExportOverlay(chars, rate) {
  $('#exportTitle').textContent = I18N.t('export.title');
  $('#exportSubtitle').textContent = I18N.t('export.synth', { chars: chars.toLocaleString() });
  const eta = Math.max(3, Math.round((chars / (15 * rate)) / 10));
  $('#exportEta').textContent = '~' + formatDuration(eta);
  $('#exportElapsed').textContent = '0s';
  $('#exportOverlay').classList.add('visible');
  const t0 = Date.now();
  clearInterval(exportTimer);
  exportTimer = setInterval(() => { $('#exportElapsed').textContent = formatDuration((Date.now() - t0) / 1000); }, 500);
}
function closeExportOverlay() {
  $('#exportOverlay').classList.remove('visible');
  clearInterval(exportTimer); exportTimer = null;
}

/* ---------- Export audio ---------- */
function generateAudioFilename(text, ext) {
  const first = text.trim().slice(0, 50).replace(/\s+/g, '_').replace(/[^\w\-]/g, '').slice(0, 40);
  const ts = new Date().toISOString().slice(0, 10);
  return (first || 'textspeak-reading') + '-' + ts + '.' + ext;
}
BridgeAPI.onExport(evt => {
  if (!exportActiveId || evt.id !== exportActiveId) return;
  if (evt.type === 'done') {
    const name = (evt.path || '').split(/[\\/]/).pop() || 'file';
    toast(I18N.t('export.saved', { name }), 'success', 4500);
    closeExportOverlay(); exportActiveId = null;
    $('#downloadAudioBtn').disabled = false; $('#batchExportBtn').disabled = false;
  } else if (evt.type === 'error') {
    if (evt.message !== 'cancelled') {
      toast(I18N.t('export.failed', { error: evt.message }), 'error', 5000);
    }
    closeExportOverlay(); exportActiveId = null;
    $('#downloadAudioBtn').disabled = false; $('#batchExportBtn').disabled = false;
  }
});

function doExport(batch) {
  const text = $('#input').value;
  if (!text.trim()) { toast(I18N.t('toast.noText')); return; }
  const voice = $('#voiceSelect').value;
  if (!AVAILABLE_VOICES.some(v => v.id === voice)) { toast(I18N.t('toast.noVoice'), 'error'); return; }
  const rate = parseFloat($('#rateSlider').value) || 1;
  const volume = parseFloat($('#volumeSlider').value) || 1;
  const fmt = $('#exportFormat').value;
  const bitrate = parseInt($('#exportBitrate').value, 10) || 128;
  const author = (PREFS && PREFS.id3_author) || '';
  const textFmt = MarkdownMode.effective;
  $('#downloadAudioBtn').disabled = true; $('#batchExportBtn').disabled = true;
  openExportOverlay(text.length, rate);
  if (batch) {
    const paras = text.split(/\n\s*\n/).map(p => p.trim()).filter(Boolean);
    exportActiveId = BridgeAPI.batchExport(paras, voice, fmt, 1.0 / rate, volume, bitrate, author, 'part', textFmt);
  } else {
    const suggested = generateAudioFilename(text, fmt);
    exportActiveId = BridgeAPI.exportAudio(text, voice, fmt, 1.0 / rate, volume, bitrate, author, suggested, textFmt);
  }
}

/* ---------- Voice catalog ---------- */
let CATALOG = [];
let CATALOG_DOWNLOADS = new Map(); // voiceId -> { reqId, progress }

function qualityOrder(q) {
  return { 'high': 0, 'medium': 1, 'low': 2, 'x_low': 3 }[q] ?? 4;
}

async function loadCatalog() {
  try {
    const res = await BridgeAPI.catalogList();
    CATALOG = res.voices || [];
    // Populate language filter
    const langs = Array.from(new Set(CATALOG.map(v => v.language).filter(Boolean))).sort();
    const filter = $('#catalogLangFilter');
    filter.innerHTML = `<option value="">${escapeHtml(I18N.t('vc.filter.all'))}</option>` +
      langs.map(l => `<option value="${escapeHtml(l)}">${escapeHtml(l)}</option>`).join('');
    renderCatalog();
  } catch (e) {
    Logger.error('catalog failed: ' + e.message);
  }
}

function renderCatalog() {
  const host = $('#catalogList');
  if (!CATALOG.length) {
    host.innerHTML = `<span style="color:var(--muted)">${escapeHtml(I18N.t('vc.empty'))}</span>`;
    return;
  }
  const search = ($('#catalogSearch').value || '').toLowerCase();
  const lang = $('#catalogLangFilter').value || '';
  const qual = $('#catalogQualityFilter').value || '';
  const filtered = CATALOG.filter(v => {
    if (lang && v.language !== lang) return false;
    if (qual && v.quality !== qual) return false;
    if (search) {
      const hay = [v.id, v.language, v.country, v.speaker].join(' ').toLowerCase();
      if (!hay.includes(search)) return false;
    }
    return true;
  });
  filtered.sort((a, b) => {
    const i = Number(b.installed === true) - Number(a.installed === true);
    if (i !== 0) return i;
    const l = (a.language || '').localeCompare(b.language || '');
    if (l !== 0) return l;
    return qualityOrder(a.quality) - qualityOrder(b.quality);
  });
  if (!filtered.length) {
    host.innerHTML = `<span style="color:var(--muted)">${escapeHtml(I18N.t('vc.empty'))}</span>`;
    return;
  }
  host.innerHTML = filtered.map(v => {
    const dl = CATALOG_DOWNLOADS.get(v.id);
    const installedBadge = v.installed ? `<span class="badge ok">${escapeHtml(I18N.t('vc.installed'))}</span>` : '';
    const qKey = v.quality ? 'vc.quality.' + v.quality : '';
    const qLabel = v.quality ? (I18N.t(qKey) || v.quality) : '';
    const qualityBadge = v.quality ? `<span class="badge">${escapeHtml(qLabel)}</span>` : '';
    const sizeBadge = v.size_mb ? `<span class="badge">${escapeHtml(I18N.t('vc.size', { size: v.size_mb }))}</span>` : '';
    const genderBadge = v.gender ? `<span class="badge">${v.gender}</span>` : '';
    let actions = '';
    if (dl) {
      const pct = dl.total ? Math.round(dl.done * 100 / dl.total) : 0;
      actions = `
        <div class="dl-progress"><div style="width:${pct}%"></div></div>
        <div style="display:flex;gap:6px;align-items:center">
          <span style="font-size:11px;color:var(--muted)">${pct}%</span>
          <button class="btn sm danger" data-vc-cancel="${escapeHtml(v.id)}">${escapeHtml(I18N.t('vc.cancel'))}</button>
        </div>`;
    } else {
      const main = v.installed
        ? `<button class="btn sm danger" data-vc-delete="${escapeHtml(v.id)}">${escapeHtml(I18N.t('vc.delete'))}</button>`
        : `<button class="btn primary sm" data-vc-download="${escapeHtml(v.id)}">${escapeHtml(I18N.t('vc.download'))}</button>`;
      actions = `
        <div style="display:flex;gap:6px">
          <button class="btn sm" data-vc-sample="${escapeHtml(v.id)}">&#9658; ${escapeHtml(I18N.t('vc.sample'))}</button>
          ${main}
        </div>`;
    }
    return `<div class="voice-card ${v.installed ? 'installed' : ''}">
      <div class="row1">
        <span class="name">${escapeHtml(v.id)}</span>
        <span class="lang">${escapeHtml(v.country || v.language || '')}</span>
        <span class="badges">${installedBadge}${qualityBadge}${genderBadge}${sizeBadge}</span>
      </div>
      <div class="actions">${actions}</div>
    </div>`;
  }).join('');

  host.querySelectorAll('[data-vc-download]').forEach(b => b.addEventListener('click', () => downloadCatalogVoice(b.dataset.vcDownload)));
  host.querySelectorAll('[data-vc-cancel]').forEach(b => b.addEventListener('click', () => cancelCatalogDownload(b.dataset.vcCancel)));
  host.querySelectorAll('[data-vc-delete]').forEach(b => b.addEventListener('click', () => deleteCatalogVoice(b.dataset.vcDelete)));
  host.querySelectorAll('[data-vc-sample]').forEach(b => b.addEventListener('click', () => playCatalogSample(b.dataset.vcSample)));
}

function downloadCatalogVoice(voiceId) {
  const reqId = BridgeAPI.catalogDownload(voiceId);
  CATALOG_DOWNLOADS.set(voiceId, { reqId, done: 0, total: 0 });
  renderCatalog();
}
function cancelCatalogDownload(voiceId) {
  const dl = CATALOG_DOWNLOADS.get(voiceId);
  if (!dl) return;
  BridgeAPI.catalogCancel(dl.reqId);
}
async function deleteCatalogVoice(voiceId) {
  if (!confirm(I18N.t('vc.confirmDelete', { voice: voiceId }))) return;
  const ok = await BridgeAPI.catalogDelete(voiceId);
  if (ok) {
    toast(I18N.t('toast.voiceDeleted', { voice: voiceId }), 'success');
    const v = CATALOG.find(x => x.id === voiceId); if (v) v.installed = false;
    renderCatalog();
    await loadInstalledVoices();
  }
}
async function playCatalogSample(voiceId) {
  const { b64 } = await BridgeAPI.playSample(voiceId);
  if (!b64) { toast(I18N.t('toast.sampleUnavailable')); return; }
  const blob = b64ToBlob(b64, 'audio/mpeg');
  const url = URL.createObjectURL(blob);
  const a = new Audio(url);
  a.play().catch(() => {});
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}

BridgeAPI.onCatalog(evt => {
  // evt.id is the request id; find matching voiceId
  let voiceId = null;
  for (const [vid, info] of CATALOG_DOWNLOADS) {
    if (info.reqId === evt.id) { voiceId = vid; break; }
  }
  if (evt.type === 'progress' && voiceId) {
    const info = CATALOG_DOWNLOADS.get(voiceId);
    info.done = evt.done; info.total = evt.total;
    renderCatalog();
  } else if (evt.type === 'done' && voiceId) {
    CATALOG_DOWNLOADS.delete(voiceId);
    const v = CATALOG.find(x => x.id === voiceId); if (v) v.installed = true;
    toast(I18N.t('toast.voiceInstalled', { voice: voiceId }), 'success');
    renderCatalog();
    loadInstalledVoices();
  } else if (evt.type === 'error' && voiceId) {
    CATALOG_DOWNLOADS.delete(voiceId);
    if (evt.message !== 'cancelled') {
      toast(evt.message, 'error', 4000);
    }
    renderCatalog();
  } else if (evt.type === 'done' && !voiceId) {
    // refresh done
    loadCatalog();
    toast('Catalog refreshed', 'success');
  }
});

BridgeAPI.onVoicesChanged(() => loadInstalledVoices());

/* ---------- Presets ---------- */
let PRESETS = [];
async function reloadPresets() {
  PRESETS = await BridgeAPI.presetsList();
  renderPresets();
}
function renderPresets() {
  const host = $('#presetList');
  if (!PRESETS.length) {
    host.innerHTML = `<span style="color:var(--muted);font-size:12px">${escapeHtml(I18N.t('settings.preset.empty'))}</span>`;
    return;
  }
  host.innerHTML = PRESETS.map(p => `
    <div style="display:flex;gap:6px;align-items:center;margin-bottom:6px">
      <button class="btn sm" data-preset-apply="${escapeHtml(p.name)}" style="flex:1;text-align:left">
        <b>${escapeHtml(p.name)}</b>
        <span style="color:var(--muted);font-weight:400;margin-left:8px;font-size:11px">${escapeHtml(p.voice || '')} &middot; ${(p.speed || 1).toFixed(2)}&times; &middot; ${Math.round((p.volume || 1) * 100)}%</span>
      </button>
      <button class="btn sm danger" data-preset-del="${escapeHtml(p.name)}">&times;</button>
    </div>`).join('');
  host.querySelectorAll('[data-preset-apply]').forEach(b => b.addEventListener('click', () => applyPreset(b.dataset.presetApply)));
  host.querySelectorAll('[data-preset-del]').forEach(b => b.addEventListener('click', () => { BridgeAPI.presetDelete(b.dataset.presetDel); toast(I18N.t('toast.presetDeleted')); reloadPresets(); }));
}
function applyPreset(name) {
  const p = PRESETS.find(x => x.name === name);
  if (!p) return;
  if (p.voice && AVAILABLE_VOICES.some(v => v.id === p.voice)) $('#voiceSelect').value = p.voice;
  if (p.speed) { $('#rateSlider').value = p.speed; $('#rateValue').textContent = p.speed.toFixed(2) + '\u00d7'; }
  if (p.volume != null) { $('#volumeSlider').value = p.volume; $('#volumeValue').textContent = Math.round(p.volume * 100) + '%'; }
  if (p.language) { $('#langSelect').value = p.language; BridgeAPI.setPref('language', p.language); applyLang(p.language); }
}

/* ---------- Find in text ---------- */
let findMatches = [];
let findIdx = 0;
function doFind(query) {
  findMatches = []; findIdx = 0;
  if (!query) { $('#findCount').textContent = ''; return; }
  const text = $('#input').value;
  const q = query.toLowerCase();
  let i = 0;
  while (true) {
    const idx = text.toLowerCase().indexOf(q, i);
    if (idx < 0) break;
    findMatches.push(idx);
    i = idx + Math.max(1, q.length);
  }
  $('#findCount').textContent = findMatches.length ? I18N.t('find.count', { current: 1, total: findMatches.length }) : '0';
  if (findMatches.length) selectMatch(0);
}
function selectMatch(idx) {
  if (!findMatches.length) return;
  findIdx = (idx + findMatches.length) % findMatches.length;
  const start = findMatches[findIdx];
  $('#input').focus();
  $('#input').setSelectionRange(start, start + $('#findInput').value.length);
  $('#findCount').textContent = I18N.t('find.count', { current: findIdx + 1, total: findMatches.length });
}

/* ---------- Wizard ---------- */
const WIZ = {
  open: false,
  lang: 'system',
  theme: 'system',
  picks: new Set(),
};
function showWizard() {
  WIZ.open = true;
  WIZ.lang = PREFS.language || 'system';
  WIZ.theme = PREFS.theme || 'system';
  markWizSelected();
  // Default picks: en_US-lessac-medium + fr_FR-siwis-medium if fr locale
  WIZ.picks = new Set();
  WIZ.picks.add('en_US-lessac-medium');
  if ((APP_INFO && APP_INFO.system_lang) === 'fr') WIZ.picks.add('fr_FR-siwis-medium');
  renderWizVoices();
  wizGotoStep(0);
  $('#wizardOverlay').classList.add('visible');
}
function hideWizard() { $('#wizardOverlay').classList.remove('visible'); WIZ.open = false; }
function wizGotoStep(n) {
  $$('.wiz-step').forEach(el => { el.style.display = parseInt(el.dataset.step, 10) === n ? '' : 'none'; });
  $$('.step-dot').forEach(el => { el.classList.toggle('active', parseInt(el.dataset.step, 10) <= n); });
}
function markWizSelected() {
  $$('#wizLangChoices .choice').forEach(c => c.classList.toggle('selected', c.dataset.value === WIZ.lang));
  $$('#wizThemeChoices .choice').forEach(c => c.classList.toggle('selected', c.dataset.value === WIZ.theme));
}
function renderWizVoices() {
  const list = [
    'en_US-lessac-medium', 'en_US-ryan-medium',
    'fr_FR-siwis-medium', 'fr_FR-upmc-medium',
    'es_ES-davefx-medium', 'de_DE-thorsten-medium',
    'it_IT-paola-medium', 'pt_BR-faber-medium',
  ].map(id => CATALOG.find(v => v.id === id) || { id, size_mb: 63, language: id.split('-')[0], country: '' });
  $('#wizVoicePicks').innerHTML = list.map(v => `
    <label class="voice-pick">
      <input type="checkbox" data-wiz-voice="${escapeHtml(v.id)}" ${WIZ.picks.has(v.id) ? 'checked' : ''}>
      <span>${escapeHtml(v.id)}</span>
      <span class="sz">${v.size_mb || 63} MB</span>
    </label>`).join('');
  $$('#wizVoicePicks [data-wiz-voice]').forEach(cb => cb.addEventListener('change', () => {
    if (cb.checked) WIZ.picks.add(cb.dataset.wizVoice);
    else WIZ.picks.delete(cb.dataset.wizVoice);
    updateWizTotal();
  }));
  updateWizTotal();
}
function updateWizTotal() {
  const total = Array.from(WIZ.picks).reduce((acc, id) => acc + ((CATALOG.find(v => v.id === id) || {}).size_mb || 63), 0);
  $('#wizTotal').textContent = I18N.t('wiz.voices.total', { size: Math.round(total) });
}
async function wizardStartDownloads() {
  wizGotoStep(2);
  const picks = Array.from(WIZ.picks);
  for (let i = 0; i < picks.length; i++) {
    const id = picks[i];
    $('#wizDlTitle').textContent = I18N.t('wiz.voices.downloading', { name: id });
    $('#wizDlSub').textContent = `${i + 1} / ${picks.length}`;
    const reqId = BridgeAPI.catalogDownload(id);
    await new Promise(resolve => {
      const off = BridgeAPI.onCatalog(evt => {
        if (evt.id !== reqId) return;
        if (evt.type === 'done' || evt.type === 'error') { off(); resolve(); }
      });
    });
  }
  BridgeAPI.setPref('wizard_complete', true);
  BridgeAPI.setPref('language', WIZ.lang);
  BridgeAPI.setPref('theme', WIZ.theme);
  applyLang(WIZ.lang); applyTheme(WIZ.theme);
  hideWizard();
  loadInstalledVoices();
  loadCatalog();
}

/* ---------- Title bar drag (native OS move via startSystemMove) ---------- */
function wireTitleBarDrag() {
  const drag = $('#titleDrag');
  drag.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    BridgeAPI.beginDrag();
    e.preventDefault();
  });
  drag.addEventListener('dblclick', () => BridgeAPI.toggleMaximize());
}

/* ---------- Frameless window resize (native via startSystemResize) ---------- */
function wireResizeGrips() {
  document.querySelectorAll('.resize-grip').forEach((el) => {
    const edges = parseInt(el.dataset.edges, 10);
    if (Number.isNaN(edges)) return;
    el.addEventListener('mousedown', (e) => {
      if (e.button !== 0) return;
      BridgeAPI.beginResize(edges);
      e.preventDefault();
    });
  });
}

/* =======================================================================
   Boot
======================================================================= */
async function boot() {
  Logger.info('TextSpeak Pro (C) 2026 JojoLapin Inc. - booting');
  await BridgeAPI.connect();
  APP_INFO = await BridgeAPI.appInfo();
  PREFS = await BridgeAPI.getPrefs();

  // Apply saved prefs to UI
  $('#rateSlider').value = PREFS.last_speed || 1;
  $('#rateValue').textContent = (PREFS.last_speed || 1).toFixed(2) + '\u00d7';
  $('#volumeSlider').value = PREFS.last_volume != null ? PREFS.last_volume : 1;
  $('#volumeValue').textContent = Math.round((PREFS.last_volume != null ? PREFS.last_volume : 1) * 100) + '%';
  $('#hlToggle').checked = !!PREFS.highlight;
  $('#autoScroll').checked = PREFS.auto_scroll !== false;
  $('#saveProgress').checked = !!PREFS.save_text;
  $('#themeSelect').value = PREFS.theme || 'system';
  $('#langSelect').value = PREFS.language || 'system';
  $('#defExportFormat').value = PREFS.export_format || 'mp3';
  $('#defExportBitrate').value = String(PREFS.mp3_bitrate || 128);
  $('#exportFormat').value = PREFS.export_format || 'mp3';
  $('#exportBitrate').value = String(PREFS.mp3_bitrate || 128);
  $('#id3Author').value = PREFS.id3_author || '';
  $('#portableToggle').checked = !!APP_INFO.portable;
  $('#settingsVersion').textContent = I18N.t('settings.version', { version: APP_INFO.version });
  $('#aboutVersion').textContent = 'v' + APP_INFO.version;

  // Markdown reading
  const mdMode = (PREFS.markdown_mode || 'auto');
  $('#mdMode').value = mdMode;
  $('#mdReadCode').checked = !!PREFS.md_read_code;
  $('#mdReadUrls').checked = !!PREFS.md_read_urls;
  $('#mdReadTables').checked = PREFS.md_read_tables !== false;
  MarkdownMode.setMode(mdMode);

  // Theme + language
  applyTheme(PREFS.theme || 'system');
  applyLang(PREFS.language || 'system');

  // Load persisted text
  if (PREFS.save_text && PREFS.saved_text) $('#input').value = PREFS.saved_text;
  MarkdownMode.refresh($('#input').value);

  // Bookmarks
  loadBookmarks();

  // Voices + catalog + presets
  await loadInstalledVoices();
  loadCatalog();
  reloadPresets();
  renderRecent();

  // Wire everything
  wireUI();
  wireTitleBarDrag();
  wireResizeGrips();
  wireDebugLog();

  updateStats();
  setStatus('ready');
  updateButtons('idle');
}

function wireUI() {
  // Title bar
  $('#winMinimize').addEventListener('click', () => BridgeAPI.minimize());
  $('#winMaximize').addEventListener('click', () => BridgeAPI.toggleMaximize());
  $('#winClose').addEventListener('click', () => BridgeAPI.close());

  // Chips -> drawers
  $('#chipImport').addEventListener('click', () => openDrawer('drawerImport'));
  $('#chipBookmarks').addEventListener('click', () => { openDrawer('drawerBookmarks'); renderBookmarks(); });
  $('#chipDebug').addEventListener('click', () => openDrawer('drawerDebug'));
  $('#chipVoices').addEventListener('click', () => openDrawer('drawerVoices'));
  $('#chipSettings').addEventListener('click', () => openDrawer('drawerSettings'));
  $('#openCatalogFromBanner').addEventListener('click', () => openDrawer('drawerVoices'));
  $$('[data-drawer-close]').forEach(el => el.addEventListener('click', closeAllDrawers));

  // Editor
  const input = $('#input');
  input.addEventListener('input', () => {
    updateStats();
    MarkdownMode.setSourceHint(null);
    MarkdownMode.refresh(input.value);
    if ($('#saveProgress').checked) BridgeAPI.setPref('saved_text', input.value);
  });

  // Markdown pill (auto -> on -> off -> auto)
  const mdChip = document.getElementById('chipMarkdown');
  if (mdChip) mdChip.addEventListener('click', () => MarkdownMode.cycle());
  input.addEventListener('dblclick', () => {
    const pos = input.selectionStart || 0;
    let start = pos;
    while (start > 0 && /\S/.test(input.value[start - 1])) start--;
    doPlay(start);
  });

  // Player
  $('#playBtn').addEventListener('click', () => doPlay(0));
  $('#playFromCursor').addEventListener('click', () => doPlay($('#input').selectionStart || 0));
  $('#pauseBtn').addEventListener('click', () => reader.pause());
  $('#resumeBtn').addEventListener('click', () => reader.resume());
  $('#stopBtn').addEventListener('click', () => { reader.stop(); clearHighlight(); $('#progressFill').style.width = '0%'; });
  $('#restartBtn').addEventListener('click', () => { clearHighlight(); doPlay(0); });
  $('#skipBack').addEventListener('click', () => reader.skip(-10));
  $('#skipForward').addEventListener('click', () => reader.skip(10));

  // Sliders
  $('#rateSlider').addEventListener('input', () => {
    const v = parseFloat($('#rateSlider').value);
    $('#rateValue').textContent = v.toFixed(2) + '\u00d7';
    updateStats();
    if (['playing', 'paused', 'loading'].includes(reader.state)) doPlay(reader._currentCharIndex());
  });
  $('#volumeSlider').addEventListener('input', () => {
    const v = parseFloat($('#volumeSlider').value);
    $('#volumeValue').textContent = Math.round(v * 100) + '%';
    reader.setVolume(v);
  });
  $('#voiceSelect').addEventListener('change', () => {
    BridgeAPI.setPref('last_voice', $('#voiceSelect').value);
    if (['playing', 'paused', 'loading'].includes(reader.state)) doPlay(reader._currentCharIndex());
  });
  $$('.preset').forEach(btn => btn.addEventListener('click', () => {
    $('#rateSlider').value = btn.dataset.speed;
    $('#rateSlider').dispatchEvent(new Event('input'));
  }));

  // Checkboxes
  $('#hlToggle').addEventListener('change', () => {
    BridgeAPI.setPref('highlight', $('#hlToggle').checked);
    if ($('#hlToggle').checked) { $('#render').classList.add('visible'); $('#render').textContent = $('#input').value; }
    else $('#render').classList.remove('visible');
  });
  $('#autoScroll').addEventListener('change', () => BridgeAPI.setPref('auto_scroll', $('#autoScroll').checked));
  $('#saveProgress').addEventListener('change', () => {
    BridgeAPI.setPref('save_text', $('#saveProgress').checked);
    if ($('#saveProgress').checked) BridgeAPI.setPref('saved_text', $('#input').value);
  });

  // Export
  $('#downloadAudioBtn').addEventListener('click', () => doExport(false));
  $('#batchExportBtn').addEventListener('click', () => doExport(true));
  $('#exportFormat').addEventListener('change', () => BridgeAPI.setPref('export_format', $('#exportFormat').value));
  $('#exportBitrate').addEventListener('change', () => BridgeAPI.setPref('mp3_bitrate', parseInt($('#exportBitrate').value, 10)));
  $('#exportCancel').addEventListener('click', () => {
    if (exportActiveId) BridgeAPI.cancelSynthesize(exportActiveId);
    closeExportOverlay(); exportActiveId = null;
    $('#downloadAudioBtn').disabled = false; $('#batchExportBtn').disabled = false;
  });

  // Settings drawer
  $('#themeSelect').addEventListener('change', () => { BridgeAPI.setPref('theme', $('#themeSelect').value); applyTheme($('#themeSelect').value); });
  $('#langSelect').addEventListener('change', () => { BridgeAPI.setPref('language', $('#langSelect').value); applyLang($('#langSelect').value); });
  $('#defExportFormat').addEventListener('change', () => { BridgeAPI.setPref('export_format', $('#defExportFormat').value); $('#exportFormat').value = $('#defExportFormat').value; });
  $('#defExportBitrate').addEventListener('change', () => { BridgeAPI.setPref('mp3_bitrate', parseInt($('#defExportBitrate').value, 10)); $('#exportBitrate').value = $('#defExportBitrate').value; });
  $('#id3Author').addEventListener('change', () => BridgeAPI.setPref('id3_author', $('#id3Author').value));
  $('#portableToggle').addEventListener('change', () => {
    BridgeAPI.setPortable($('#portableToggle').checked);
    toast(I18N.t($('#portableToggle').checked ? 'toast.portableOn' : 'toast.portableOff'));
  });

  // Markdown reading controls
  $('#mdMode').addEventListener('change', () => {
    const mode = $('#mdMode').value;
    MarkdownMode.setMode(mode);
    BridgeAPI.setPref('markdown_mode', mode);
  });
  $('#mdReadCode').addEventListener('change', () => BridgeAPI.setPref('md_read_code', $('#mdReadCode').checked));
  $('#mdReadUrls').addEventListener('change', () => BridgeAPI.setPref('md_read_urls', $('#mdReadUrls').checked));
  $('#mdReadTables').addEventListener('change', () => BridgeAPI.setPref('md_read_tables', $('#mdReadTables').checked));
  $('#openVoicesFolder').addEventListener('click', () => BridgeAPI.openVoicesFolder());
  $('#openLogsFolder').addEventListener('click', () => BridgeAPI.openLogsFolder());
  $('#openDataFolder').addEventListener('click', () => BridgeAPI.openDataFolder());
  $('#aboutBtn').addEventListener('click', () => $('#aboutOverlay').classList.add('visible'));
  $('#aboutClose').addEventListener('click', () => $('#aboutOverlay').classList.remove('visible'));

  // Presets
  $('#savePresetBtn').addEventListener('click', () => { $('#presetName').value = ''; $('#presetOverlay').classList.add('visible'); $('#presetName').focus(); });
  $('#presetCancel').addEventListener('click', () => $('#presetOverlay').classList.remove('visible'));
  $('#presetOk').addEventListener('click', () => {
    const name = ($('#presetName').value || '').trim();
    if (!name) return;
    BridgeAPI.presetSave(name, {
      voice: $('#voiceSelect').value,
      speed: parseFloat($('#rateSlider').value),
      volume: parseFloat($('#volumeSlider').value),
      language: $('#langSelect').value,
    });
    $('#presetOverlay').classList.remove('visible');
    toast(I18N.t('toast.presetSaved'), 'success');
    reloadPresets();
  });

  // Bookmarks
  $('#addBookmark').addEventListener('click', () => {
    const pos = reader._currentCharIndex() || $('#input').selectionStart || 0;
    const preview = ($('#input').value.slice(pos, pos + 50).replace(/\s+/g, ' ') + '...').trim();
    BOOKMARKS.push({ id: Date.now(), position: pos, preview, timestamp: new Date().toLocaleString() });
    saveBookmarks(); renderBookmarks();
    toast(I18N.t('toast.bookmarkAdded'), 'success');
  });

  // Debug
  $('#clearLog').addEventListener('click', () => Logger.clear());
  $('#copyLog').addEventListener('click', async () => {
    const all = Logger.getAll().map(e => `[${e.time}] [${e.level}] ${e.msg}`).join('\n');
    try { await navigator.clipboard.writeText(all); toast(I18N.t('toast.copied'), 'success'); }
    catch { BridgeAPI.setClipboard(all); toast(I18N.t('toast.copied'), 'success'); }
  });

  // Import
  const dropZone = $('#dropZone');
  const fileInput = $('#fileInput');
  dropZone.addEventListener('click', () => fileInput.click());
  dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
  dropZone.addEventListener('drop', async e => {
    e.preventDefault(); dropZone.classList.remove('dragover');
    const file = e.dataTransfer.files[0];
    if (!file) return;
    // Drops inside the webview only expose File; for real paths we rely on window-level DnD (bridge.fileDropped)
    const r = new FileReader();
    r.onload = ev => { $('#input').value = ev.target.result || ''; updateStats(); toast(I18N.t('toast.fileLoaded', { name: file.name }), 'success'); };
    r.readAsText(file);
  });
  fileInput.addEventListener('change', () => {
    const file = fileInput.files[0]; if (!file) return;
    const r = new FileReader();
    r.onload = ev => { $('#input').value = ev.target.result || ''; updateStats(); toast(I18N.t('toast.fileLoaded', { name: file.name }), 'success'); };
    r.readAsText(file);
  });
  $('#fetchUrl').addEventListener('click', async () => {
    const url = $('#urlInput').value.trim();
    if (!url) return;
    try {
      toast('Fetching...');
      const res = await fetch(url);
      let text = await res.text();
      if (text.includes('<')) {
        const tmp = document.createElement('div');
        tmp.innerHTML = text;
        tmp.querySelectorAll('script, style, nav, header, footer').forEach(el => el.remove());
        text = tmp.textContent || tmp.innerText;
      }
      $('#input').value = text.trim(); updateStats();
      toast('Content loaded', 'success');
      closeAllDrawers();
    } catch (e) {
      toast(I18N.t('toast.urlFetchError'), 'error', 4000);
    }
  });
  $('#pasteClipboard').addEventListener('click', async () => {
    try {
      const text = await navigator.clipboard.readText();
      $('#input').value = text; updateStats();
      toast(I18N.t('toast.pastedClipboard'), 'success');
    } catch {
      const txt = await BridgeAPI.readClipboard();
      if (txt) { $('#input').value = txt; updateStats(); toast(I18N.t('toast.pastedClipboard'), 'success'); }
      else toast(I18N.t('toast.clipboardError'), 'error');
    }
  });
  $('#clearText').addEventListener('click', () => {
    $('#input').value = ''; updateStats(); reader.stop();
    clearHighlight(); $('#progressFill').style.width = '0%';
    toast(I18N.t('toast.textCleared'));
  });

  // Catalog
  $('#catalogSearch').addEventListener('input', renderCatalog);
  $('#catalogLangFilter').addEventListener('change', renderCatalog);
  $('#catalogQualityFilter').addEventListener('change', renderCatalog);
  $('#catalogRefresh').addEventListener('click', () => BridgeAPI.catalogRefresh());

  // Wizard
  $$('#wizLangChoices .choice').forEach(el => el.addEventListener('click', () => { WIZ.lang = el.dataset.value; markWizSelected(); }));
  $$('#wizThemeChoices .choice').forEach(el => el.addEventListener('click', () => { WIZ.theme = el.dataset.value; markWizSelected(); }));
  $('#wizSkip').addEventListener('click', () => { BridgeAPI.setPref('wizard_complete', true); hideWizard(); });
  $('#wizNext1').addEventListener('click', () => wizGotoStep(1));
  $('#wizBack1').addEventListener('click', () => wizGotoStep(0));
  $('#wizDownload').addEventListener('click', wizardStartDownloads);

  // Find
  document.addEventListener('keydown', e => {
    if (e.ctrlKey && !e.shiftKey && e.key.toLowerCase() === 'f') {
      e.preventDefault();
      $('#findBar').classList.add('visible');
      $('#findInput').focus(); $('#findInput').select();
      return;
    }
    if (e.ctrlKey && !e.shiftKey && e.key === 'Enter') { e.preventDefault(); $('#playBtn').click(); return; }
    if (e.ctrlKey && e.shiftKey && e.key === 'Enter') { e.preventDefault(); $('#playFromCursor').click(); return; }
    if (e.key === 'Escape') {
      if ($('#findBar').classList.contains('visible')) { $('#findBar').classList.remove('visible'); return; }
      if (document.querySelectorAll('.drawer.open').length) { closeAllDrawers(); return; }
      if ($('#aboutOverlay').classList.contains('visible')) { $('#aboutOverlay').classList.remove('visible'); return; }
      if ($('#presetOverlay').classList.contains('visible')) { $('#presetOverlay').classList.remove('visible'); return; }
      e.preventDefault(); $('#stopBtn').click(); return;
    }
    if (e.code === 'Space' && document.activeElement !== $('#input') && !isInInput(document.activeElement)) {
      e.preventDefault();
      if (reader.state === 'paused') $('#resumeBtn').click();
      else if (reader.state === 'playing') $('#pauseBtn').click();
      return;
    }
    if (document.activeElement !== $('#input') && !isInInput(document.activeElement)) {
      if (e.key === 'ArrowLeft')  { e.preventDefault(); $('#skipBack').click(); }
      if (e.key === 'ArrowRight') { e.preventDefault(); $('#skipForward').click(); }
    }
  });
  $('#findInput').addEventListener('input', () => doFind($('#findInput').value));
  $('#findInput').addEventListener('keydown', e => {
    if (e.key === 'Enter') { selectMatch(findIdx + (e.shiftKey ? -1 : 1)); e.preventDefault(); }
  });
  $('#findPrev').addEventListener('click', () => selectMatch(findIdx - 1));
  $('#findNext').addEventListener('click', () => selectMatch(findIdx + 1));
  $('#findClose').addEventListener('click', () => $('#findBar').classList.remove('visible'));

  // Bridge-level signals
  BridgeAPI.onThemeChanged((scheme) => applyTheme(scheme));
  BridgeAPI.onLanguageChanged((lang) => applyLang(lang));
  BridgeAPI.onFileDropped(async (paths) => {
    if (paths && paths.length) {
      await loadTextFromFile(paths[0]);
    }
  });
  BridgeAPI.onReadClipboardRequested(async () => {
    const text = await BridgeAPI.readClipboard();
    if (text) { $('#input').value = text; updateStats(); setTimeout(() => doPlay(0), 50); }
  });
  BridgeAPI.onStopRequested(() => { reader.stop(); clearHighlight(); $('#progressFill').style.width = '0%'; });

  // Reader events -> UI
  reader.on('state', ({ state, reason }) => {
    setStatus(state, reason);
    updateButtons(state);
    updateMediaSession(state);
    $('#progressFill').classList.toggle('shimmer', state === 'loading');
    if (state === 'done') toast(I18N.t('toast.readingComplete'), 'success');
  });
  reader.on('progress', ({ charIndex, totalChars, chunkIdx, totalChunks }) => {
    if (totalChars > 0) $('#progressFill').style.width = (charIndex / totalChars * 100).toFixed(1) + '%';
    $('#chunkProgress').textContent = `${Math.min(chunkIdx + 1, totalChunks)} / ${totalChunks}`;
    if ($('#hlToggle').checked) updateHighlight(charIndex);
    if ($('#saveProgress').checked) BridgeAPI.setPref('saved_position', charIndex);
  });
  reader.on('error', ({ message }) => toast(message, 'error', 4000));

  // Beforeunload
  window.addEventListener('beforeunload', () => reader.stop());
}

function isInInput(el) {
  if (!el) return false;
  const tag = el.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || el.isContentEditable;
}

/* Media session: native keyboard/headset controls */
function updateMediaSession(state) {
  if (!('mediaSession' in navigator)) return;
  if (state === 'playing') {
    if (!navigator.mediaSession.metadata || !navigator.mediaSession.metadata.title) {
      const snippet = ($('#input').value || '').slice(0, 80).replace(/\s+/g, ' ').trim() || 'Reading';
      try {
        navigator.mediaSession.metadata = new MediaMetadata({
          title: snippet + ($('#input').value.length > 80 ? '...' : ''),
          artist: 'TextSpeak Pro',
          album: $('#voiceSelect').value ? $('#voiceSelect').value.replace(/_/g, ' ') : 'Piper TTS',
        });
      } catch {}
    }
    navigator.mediaSession.playbackState = 'playing';
  } else if (state === 'paused') {
    navigator.mediaSession.playbackState = 'paused';
  } else if (['idle', 'done', 'error'].includes(state)) {
    navigator.mediaSession.playbackState = 'none';
    navigator.mediaSession.metadata = null;
  }
}
if ('mediaSession' in navigator) {
  const ms = navigator.mediaSession;
  const tryHandler = (action, fn) => { try { ms.setActionHandler(action, fn); } catch {} };
  tryHandler('play',         () => { if (reader.state === 'paused') reader.resume(); });
  tryHandler('pause',        () => { if (reader.state === 'playing') reader.pause(); });
  tryHandler('stop',         () => { if (reader.state !== 'idle') { reader.stop(); clearHighlight(); $('#progressFill').style.width = '0%'; } });
  tryHandler('seekbackward', () => reader.skip(-10));
  tryHandler('seekforward',  () => reader.skip(10));
  tryHandler('previoustrack',() => reader.skip(-10));
  tryHandler('nexttrack',    () => reader.skip(10));
}

/* Go! */
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}
