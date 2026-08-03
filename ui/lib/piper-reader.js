/* TextSpeak Pro - PiperReader (session-guarded, prefetched playback pipeline)
 * (C) 2026 JojoLapin Inc. All rights reserved.
 *
 * This is the sensitive playback core. Correctness of stop / restart / skip and
 * the "no stale audio ever plays" guarantee depends entirely on the monotonic
 * `sessionId` discipline and on `_hardStop` revoking every object URL. The logic
 * here is identical to the original inline implementation; the ONLY addition is a
 * dependency-injection seam (`constructor(deps)`) whose defaults resolve to the
 * exact same browser globals, so behaviour in the webview is unchanged while the
 * class becomes unit-testable under Node (see tests/js/piper-reader.test.js).
 *
 * Do not change the session/`_hardStop` semantics without updating those tests.
 */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.PiperReader = api.PiperReader;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  /* Default base64 -> Blob helper (mirrors app.js). Overridable via deps. */
  function defaultB64ToBlob(b64, mime = 'audio/wav') {
    const bin = atob(b64);
    const len = bin.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) bytes[i] = bin.charCodeAt(i);
    return new Blob([bytes], { type: mime });
  }

  const _noopLogger = { info() {}, debug() {}, warn() {}, error() {} };

  class PiperReader {
    constructor(deps = {}) {
      // Dependency seam: defaults reproduce the original browser globals.
      this._AudioCtor = deps.Audio || (typeof Audio !== 'undefined' ? Audio : null);
      this._URL = deps.URL || (typeof URL !== 'undefined' ? URL : (typeof globalThis !== 'undefined' ? globalThis.URL : null));
      // A provider turns text -> { b64, mime }. Supplied per-session via
      // start(opts.provider); this is only a fallback for tests/direct use.
      this._provider = deps.provider || null;
      this._chunker = deps.chunker || (typeof TextChunker !== 'undefined' ? TextChunker : null);
      this._i18n = deps.i18n || (typeof I18N !== 'undefined' ? I18N : { t: (k) => k });
      this._logger = deps.logger || (typeof Logger !== 'undefined' ? Logger : _noopLogger);
      this._b64ToBlob = deps.b64ToBlob || defaultB64ToBlob;

      this.audio = new this._AudioCtor();
      this.audio.preload = 'auto';
      this.state = 'idle';
      this.sessionId = 0;
      this.text = '';
      this.chunks = [];
      this.chunkIdx = 0;
      this.opts = { voice: null, rate: 1.0, volume: 1.0 };
      this.audioCache = new Map();     // idx -> { url }
      this.pendingFetches = new Map(); // idx -> { promise, cancel }
      this.chunkWaiters = new Map();
      this._listeners = { state: [], progress: [], error: [] };
      this._attachAudio();
    }
    on(event, fn) { (this._listeners[event] ||= []).push(fn); return this; }
    _emit(event, payload) { (this._listeners[event] || []).forEach(fn => { try { fn(payload); } catch {} }); }
    _transition(newState, details = {}) {
      const prev = this.state;
      this.state = newState;
      if (prev !== newState) this._logger.info(`state: ${prev} -> ${newState}${details.reason ? ' (' + details.reason + ')' : ''}`);
      this._emit('state', { state: newState, prev, ...details });
    }
    _attachAudio() {
      this.audio.addEventListener('timeupdate', () => this._onTimeUpdate());
      this.audio.addEventListener('ended',      () => this._onChunkEnded());
      this.audio.addEventListener('error',      () => this._onAudioError());
    }

    async start(text, opts = {}, fromPosition = 0) {
      if (!text || !text.trim()) { this._emit('error', { message: this._i18n.t('toast.noText') }); return false; }
      if (!opts.voice) { this._emit('error', { message: this._i18n.t('toast.noVoice') }); return false; }
      this._hardStop('new session');
      this.sessionId += 1;
      const sid = this.sessionId;
      this.text = text;
      this.opts = {
        voice: opts.voice,
        rate: Math.max(0.5, Math.min(2.0, Number(opts.rate) || 1.0)),
        volume: Math.max(0, Math.min(1, Number(opts.volume) || 1.0)),
      };
      this.opts.textFormat = opts.textFormat || 'plain';
      this.opts.provider = opts.provider || this._provider;
      // Opaque per-provider extras (e.g. OpenAI model/instructions/format).
      this.opts.providerOptions = opts.providerOptions || {};
      if (!this.opts.provider || typeof this.opts.provider.synthesize !== 'function') {
        this._emit('error', { message: 'No voice provider available' });
        return false;
      }
      this.audio.volume = this.opts.volume;
      this.chunks = this._chunker.chunk(text, 450);
      if (!this.chunks.length) { this._emit('error', { message: 'No chunks.' }); return false; }
      this.chunkIdx = this._chunker.findChunkAtPosition(this.chunks, Math.max(0, Math.min(fromPosition, text.length)));
      this._transition('loading', { reason: `fetching chunk ${this.chunkIdx + 1}/${this.chunks.length}` });
      this._ensureChunkLoaded(this.chunkIdx, sid);
      this._ensureChunkLoaded(this.chunkIdx + 1, sid);
      try {
        await this._waitForChunk(this.chunkIdx, sid);
        if (this.sessionId !== sid) return false;
        await this._playCurrent(sid);
        return true;
      } catch (e) {
        if (this.sessionId !== sid) return false;
        this._logger.error('Start failed:', e.message);
        this._emit('error', { message: e.message });
        this._transition('error', { reason: e.message });
        return false;
      }
    }
    pause() { if (this.state !== 'playing') return false; this.audio.pause(); this._transition('paused'); return true; }
    async resume() {
      if (this.state !== 'paused') return false;
      try { await this.audio.play(); this._transition('playing'); return true; }
      catch (e) { this._emit('error', { message: e.message }); return false; }
    }
    stop() {
      if (this.state === 'idle') return false;
      this._hardStop('user stop');
      this._transition('idle');
      this._emit('progress', { charIndex: 0, totalChars: this.text.length, chunkIdx: 0, totalChunks: this.chunks.length });
      return true;
    }
    restart() { const t = this.text, o = { ...this.opts }; this._hardStop('restart'); return this.start(t, o, 0); }
    skip(seconds) {
      if (this.state !== 'playing' && this.state !== 'paused') return false;
      const cps = 12 * this.opts.rate;
      const delta = Math.round(seconds * cps);
      const newPos = Math.max(0, Math.min(this.text.length - 1, this._currentCharIndex() + delta));
      return this.start(this.text, this.opts, newPos);
    }
    setVolume(v) { this.opts.volume = Math.max(0, Math.min(1, Number(v) || 0)); this.audio.volume = this.opts.volume; }

    _ensureChunkLoaded(idx, sid) {
      if (idx < 0 || idx >= this.chunks.length) return;
      if (this.audioCache.has(idx)) return;
      if (this.pendingFetches.has(idx)) return;
      const chunk = this.chunks[idx];
      const promise = this.opts.provider.synthesize(chunk.text, {
        voice: this.opts.voice,
        rate: this.opts.rate,
        volume: this.opts.volume,
        textFormat: this.opts.textFormat || 'plain',
        ...this.opts.providerOptions,
      });
      this.pendingFetches.set(idx, { promise });
      promise.then(({ b64, mime }) => {
        if (this.sessionId !== sid) return;
        const blob = this._b64ToBlob(b64, mime || 'audio/wav');
        const url = this._URL.createObjectURL(blob);
        this.audioCache.set(idx, { url });
        this._logger.debug(`chunk ${idx + 1} loaded (${(blob.size / 1024).toFixed(1)} KB)`);
        this._resolveChunkWaiters(idx, null);
      }).catch(e => {
        if (this.sessionId !== sid) return;
        this._logger.error(`chunk ${idx + 1} failed: ${e.message}`);
        this._resolveChunkWaiters(idx, e);
      }).finally(() => {
        this.pendingFetches.delete(idx);
      });
    }
    _waitForChunk(idx, sid) {
      return new Promise((resolve, reject) => {
        if (this.sessionId !== sid) { reject(new Error('stale session')); return; }
        if (this.audioCache.has(idx)) { resolve(); return; }
        if (!this.chunkWaiters.has(idx)) this.chunkWaiters.set(idx, []);
        this.chunkWaiters.get(idx).push({ resolve, reject, sid });
        setTimeout(() => {
          if (this.sessionId !== sid) return;
          if (this.audioCache.has(idx)) return;
          this._resolveChunkWaiters(idx, new Error(`Timeout waiting for chunk ${idx + 1}`));
        }, 60000);
      });
    }
    _resolveChunkWaiters(idx, err) {
      const waiters = this.chunkWaiters.get(idx);
      if (!waiters) return;
      this.chunkWaiters.delete(idx);
      waiters.forEach(({ resolve, reject, sid }) => {
        if (this.sessionId !== sid) { reject(new Error('stale session')); return; }
        if (err) reject(err); else resolve();
      });
    }
    async _playCurrent(sid) {
      if (this.sessionId !== sid) return;
      if (this.chunkIdx >= this.chunks.length) { this._finish(); return; }
      const entry = this.audioCache.get(this.chunkIdx);
      if (!entry) {
        this._transition('loading', { reason: `waiting for chunk ${this.chunkIdx + 1}` });
        try { await this._waitForChunk(this.chunkIdx, sid); } catch (e) { if (this.sessionId !== sid) return; throw e; }
        if (this.sessionId !== sid) return;
        return this._playCurrent(sid);
      }
      this.audio.src = entry.url;
      this.audio.volume = this.opts.volume;
      try {
        await this.audio.play();
        if (this.sessionId !== sid) { this.audio.pause(); return; }
        this._transition('playing', { reason: `chunk ${this.chunkIdx + 1}/${this.chunks.length}` });
        this._ensureChunkLoaded(this.chunkIdx + 1, sid);
      } catch (e) {
        if (this.sessionId !== sid) return;
        this._emit('error', { message: 'Playback error: ' + e.message });
        this._transition('error', { reason: e.message });
      }
    }
    _onTimeUpdate() {
      if (this.state !== 'playing' && this.state !== 'paused') return;
      this._emitProgress();
    }
    _onChunkEnded() {
      if (this.state !== 'playing') return;
      const sid = this.sessionId;
      const entry = this.audioCache.get(this.chunkIdx);
      if (entry) { this._URL.revokeObjectURL(entry.url); this.audioCache.delete(this.chunkIdx); }
      this.chunkIdx += 1;
      if (this.chunkIdx >= this.chunks.length) { this._finish(); return; }
      this._ensureChunkLoaded(this.chunkIdx + 1, sid);
      this._playCurrent(sid);
    }
    _onAudioError() {
      if (this.state === 'idle') return;
      this._emit('error', { message: 'Audio element error' });
    }
    _currentCharIndex() {
      if (this.chunkIdx >= this.chunks.length) return this.text.length;
      const chunk = this.chunks[this.chunkIdx]; if (!chunk) return 0;
      const dur = this.audio.duration;
      if (!Number.isFinite(dur) || dur <= 0) return chunk.start;
      const progress = Math.max(0, Math.min(1, this.audio.currentTime / dur));
      return chunk.start + Math.floor(progress * (chunk.end - chunk.start));
    }
    _emitProgress() {
      this._emit('progress', {
        charIndex: this._currentCharIndex(),
        totalChars: this.text.length,
        chunkIdx: this.chunkIdx,
        totalChunks: this.chunks.length,
      });
    }
    _finish() {
      this._hardStop('finished', true);
      this._transition('done', { reason: 'end of text' });
      this._emit('progress', { charIndex: this.text.length, totalChars: this.text.length, chunkIdx: this.chunks.length, totalChunks: this.chunks.length });
    }
    _hardStop(reason, silent = false) {
      if (!silent) this._logger.debug('hard stop: ' + reason);
      this.sessionId += 1;
      try { this.audio.pause(); } catch {}
      try { this.audio.removeAttribute('src'); this.audio.load(); } catch {}
      this.pendingFetches.clear();
      this.chunkWaiters.forEach(waiters => waiters.forEach(({ reject }) => { try { reject(new Error('stopped')); } catch {} }));
      this.chunkWaiters.clear();
      this.audioCache.forEach(e => { try { this._URL.revokeObjectURL(e.url); } catch {} });
      this.audioCache.clear();
    }
  }

  return { PiperReader, defaultB64ToBlob };
});
