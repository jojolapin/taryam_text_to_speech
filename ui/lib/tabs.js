/* TextSpeak Pro - multi-tab document workspace
 * (C) 2026 JojoLapin Inc. All rights reserved.
 *
 * Two pieces:
 *   - TabStore: a pure, framework-free document/tab model (create/close/rename/
 *     duplicate/reorder/switch/update). No DOM, no storage - fully unit-testable.
 *   - TabPersistence: an IndexedDB-backed async loader/saver used by app.js.
 *
 * Documents are the source of truth for per-tab state (text, cursor, scroll,
 * bookmarks, voice/speed/volume, markdown mode, playback position, audio status).
 * Persistence is local-only forever (privacy-first) - see the modernization plan.
 */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.TabStore = api.TabStore;
    root.TabPersistence = api.TabPersistence;
    root.createDocument = api.createDocument;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const SCHEMA_VERSION = 1;

  function _uid() {
    // Prefer crypto.randomUUID when available (webview + modern Node).
    try {
      if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
    } catch {}
    return 'doc-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
  }

  /* Canonical document shape. Unknown/missing fields are filled with defaults so
   * older persisted docs upgrade cleanly. */
  function createDocument(overrides = {}, now = Date.now) {
    const ts = now();
    const base = {
      id: _uid(),
      title: '',                 // empty => UI shows a derived/placeholder title
      text: '',
      cursor: 0,                 // caret index
      selStart: 0,
      selEnd: 0,
      scrollTop: 0,
      bookmarks: [],             // [{id, position, preview, timestamp}]
      markdownMode: 'auto',      // auto | on | off
      provider: 'piper',         // piper | openai
      voice: null,
      speakingStyle: 'neutral',  // OpenAI delivery preset id
      speakingInstructions: '',  // optional free-text override
      pronunciationRules: [],    // per-document non-destructive rules
      speed: null,               // null => fall back to global default
      volume: null,
      playbackPosition: 0,
      audioStatus: 'idle',       // idle | generating | ready | error
      createdAt: ts,
      updatedAt: ts,
    };
    const doc = Object.assign(base, overrides);
    // Never let overrides drop the id or timestamps.
    if (!doc.id) doc.id = base.id;
    if (!doc.createdAt) doc.createdAt = ts;
    if (!doc.updatedAt) doc.updatedAt = ts;
    if (!Array.isArray(doc.bookmarks)) doc.bookmarks = [];
    if (!Array.isArray(doc.pronunciationRules)) doc.pronunciationRules = [];
    if (!doc.speakingStyle) doc.speakingStyle = 'neutral';
    if (typeof doc.speakingInstructions !== 'string') doc.speakingInstructions = '';
    return doc;
  }

  /* Derive a human-friendly title from a document (first non-empty line). */
  function deriveTitle(doc, fallback = 'Untitled') {
    if (doc.title && doc.title.trim()) return doc.title.trim();
    const firstLine = (doc.text || '').split('\n').map(s => s.trim()).find(Boolean) || '';
    const t = firstLine.replace(/\s+/g, ' ').slice(0, 40).trim();
    return t || fallback;
  }

  class TabStore {
    /**
     * @param {object} opts
     * @param {() => number} [opts.now] clock injection (tests)
     */
    constructor(opts = {}) {
      this._now = opts.now || Date.now;
      this.docs = [];
      this.activeId = null;
      this._listeners = new Set();
    }

    // ---- events ----
    onChange(fn) { this._listeners.add(fn); return () => this._listeners.delete(fn); }
    _emit(reason) { this._listeners.forEach(fn => { try { fn({ reason, docs: this.docs, activeId: this.activeId }); } catch {} }); }

    // ---- lifecycle ----
    /** Seed the store. Always guarantees >=1 doc and a valid activeId. */
    init(docs = [], activeId = null) {
      this.docs = (Array.isArray(docs) ? docs : []).map(d => createDocument(d, this._now));
      if (!this.docs.length) this.docs = [createDocument({}, this._now)];
      this.activeId = this.docs.some(d => d.id === activeId) ? activeId : this.docs[0].id;
      this._emit('init');
      return this.active();
    }

    // ---- queries ----
    list() { return this.docs; }
    count() { return this.docs.length; }
    indexOf(id) { return this.docs.findIndex(d => d.id === id); }
    get(id) { return this.docs.find(d => d.id === id) || null; }
    active() { return this.get(this.activeId); }
    titleOf(doc, fallback) { return deriveTitle(doc, fallback); }

    // ---- mutations ----
    create(overrides = {}, { activate = true } = {}) {
      const doc = createDocument(overrides, this._now);
      this.docs.push(doc);
      if (activate) this.activeId = doc.id;
      this._emit('create');
      return doc;
    }

    /** Close a tab. Returns { closedId, wasActive, newActiveId }. Never leaves
     * the workspace empty: closing the last tab creates a fresh blank one. */
    close(id) {
      const idx = this.indexOf(id);
      if (idx === -1) return { closedId: null, wasActive: false, newActiveId: this.activeId };
      const wasActive = this.activeId === id;
      this.docs.splice(idx, 1);
      if (!this.docs.length) {
        const fresh = createDocument({}, this._now);
        this.docs.push(fresh);
        this.activeId = fresh.id;
      } else if (wasActive) {
        // Activate the neighbour to the left (or the new first tab).
        const neighbour = this.docs[Math.max(0, idx - 1)];
        this.activeId = neighbour.id;
      }
      this._emit('close');
      return { closedId: id, wasActive, newActiveId: this.activeId };
    }

    rename(id, title) {
      const doc = this.get(id);
      if (!doc) return null;
      doc.title = (title || '').slice(0, 120);
      doc.updatedAt = this._now();
      this._emit('rename');
      return doc;
    }

    duplicate(id, { activate = true } = {}) {
      const src = this.get(id);
      if (!src) return null;
      const copy = createDocument({
        ...src,
        id: undefined,               // force a fresh id
        title: (deriveTitle(src, 'Untitled')) + ' (copy)',
        createdAt: undefined,
        updatedAt: undefined,
        audioStatus: 'idle',
      }, this._now);
      const idx = this.indexOf(id);
      this.docs.splice(idx + 1, 0, copy);
      if (activate) this.activeId = copy.id;
      this._emit('duplicate');
      return copy;
    }

    /** Move the tab at fromIdx to toIdx (both clamped). */
    reorder(fromIdx, toIdx) {
      const n = this.docs.length;
      if (fromIdx < 0 || fromIdx >= n) return false;
      toIdx = Math.max(0, Math.min(n - 1, toIdx));
      if (fromIdx === toIdx) return false;
      const [moved] = this.docs.splice(fromIdx, 1);
      this.docs.splice(toIdx, 0, moved);
      this._emit('reorder');
      return true;
    }

    /** Move a tab identified by id to a target index. */
    moveTo(id, toIdx) { return this.reorder(this.indexOf(id), toIdx); }

    setActive(id) {
      if (id === this.activeId) return false;
      if (this.indexOf(id) === -1) return false;
      this.activeId = id;
      this._emit('activate');
      return true;
    }

    /** Merge a patch into a document. Does NOT emit by default (autosave is
     * driven by the caller on a debounce) unless emit=true. */
    update(id, patch = {}, { emit = false, touch = true } = {}) {
      const doc = this.get(id);
      if (!doc) return null;
      Object.assign(doc, patch);
      if (touch) doc.updatedAt = this._now();
      if (emit) this._emit('update');
      return doc;
    }

    setAudioStatus(id, status) {
      const doc = this.get(id);
      if (!doc) return null;
      doc.audioStatus = status;
      this._emit('audiostatus');
      return doc;
    }

    /** Serializable snapshot for persistence. */
    snapshot() {
      return { schema: SCHEMA_VERSION, activeId: this.activeId, docs: this.docs };
    }
  }

  /* ---------------------------------------------------------------------------
   * IndexedDB persistence. Stores a single snapshot record so load/save are
   * simple and atomic. Falls back to a no-op store when IndexedDB is missing.
   * ------------------------------------------------------------------------- */
  class TabPersistence {
    constructor({ dbName = 'textspeak', storeName = 'workspace', key = 'snapshot', indexedDB = null } = {}) {
      this.dbName = dbName;
      this.storeName = storeName;
      this.key = key;
      this._idb = indexedDB || (typeof globalThis !== 'undefined' ? globalThis.indexedDB : null);
      this._dbPromise = null;
    }

    get available() { return !!this._idb; }

    _open() {
      if (!this._idb) return Promise.reject(new Error('IndexedDB unavailable'));
      if (this._dbPromise) return this._dbPromise;
      this._dbPromise = new Promise((resolve, reject) => {
        const req = this._idb.open(this.dbName, 1);
        req.onupgradeneeded = () => {
          const db = req.result;
          if (!db.objectStoreNames.contains(this.storeName)) db.createObjectStore(this.storeName);
        };
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error || new Error('IndexedDB open failed'));
      });
      return this._dbPromise;
    }

    async load() {
      if (!this._idb) return null;
      try {
        const db = await this._open();
        return await new Promise((resolve, reject) => {
          const tx = db.transaction(this.storeName, 'readonly');
          const req = tx.objectStore(this.storeName).get(this.key);
          req.onsuccess = () => resolve(req.result || null);
          req.onerror = () => reject(req.error);
        });
      } catch {
        return null;
      }
    }

    async save(snapshot) {
      if (!this._idb) return false;
      try {
        const db = await this._open();
        return await new Promise((resolve, reject) => {
          const tx = db.transaction(this.storeName, 'readwrite');
          tx.objectStore(this.storeName).put(snapshot, this.key);
          tx.oncomplete = () => resolve(true);
          tx.onerror = () => reject(tx.error);
          tx.onabort = () => reject(tx.error || new Error('tx aborted'));
        });
      } catch {
        return false;
      }
    }

    async clear() {
      if (!this._idb) return;
      try {
        const db = await this._open();
        await new Promise((resolve, reject) => {
          const tx = db.transaction(this.storeName, 'readwrite');
          tx.objectStore(this.storeName).delete(this.key);
          tx.oncomplete = () => resolve();
          tx.onerror = () => reject(tx.error);
        });
      } catch {}
    }
  }

  return { TabStore, TabPersistence, createDocument, deriveTitle, SCHEMA_VERSION };
});
