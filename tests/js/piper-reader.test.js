/* Regression tests for the PiperReader playback core (ui/lib/piper-reader.js).
 * (C) 2026 JojoLapin Inc.
 * Run: npm test
 *
 * These pin the SENSITIVE guarantees that must never regress:
 *   - stale audio from a stopped/superseded session never plays;
 *   - _hardStop revokes every object URL (no leaks);
 *   - only the latest session ever reaches playback.
 * The reader is provider-agnostic: it calls provider.synthesize(text, opts) and
 * expects { b64, mime }. Timers are mocked so the 60s watchdog never keeps Node alive.
 */
'use strict';

const { test, mock } = require('node:test');
const assert = require('node:assert');

const { TextChunker } = require('../../ui/lib/text-chunker.js');
const { TextNav } = require('../../ui/lib/text-nav.js');
const { PiperReader } = require('../../ui/lib/piper-reader.js');

// ---- test doubles ---------------------------------------------------------

function deferred() {
  let resolve, reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function makeProvider() {
  const calls = [];
  return {
    id: 'test',
    synthesize(text, opts) {
      const d = deferred();
      calls.push({ text, opts, d });
      return d.promise;
    },
    calls,
    resolveAll(b64 = 'AAAA', mime = 'audio/wav') { calls.forEach(c => c.d.resolve({ b64, mime })); },
  };
}

function makeURL() {
  let n = 0;
  const live = new Set();
  const created = [];
  const revoked = [];
  return {
    createObjectURL() { const u = 'blob:mock/' + (++n); live.add(u); created.push(u); return u; },
    revokeObjectURL(u) { live.delete(u); revoked.push(u); },
    live, created, revoked,
  };
}

function makeAudioClass(registry) {
  return class FakeAudio {
    constructor() {
      this.handlers = {};
      this.volume = 1;
      this.src = '';
      this.duration = NaN;
      this.currentTime = 0;
      this.playCount = 0;
      this.pauseCount = 0;
      registry.instances.push(this);
    }
    addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); }
    removeAttribute(attr) { if (attr === 'src') this.src = ''; }
    load() {}
    play() { this.playCount++; return Promise.resolve(); }
    pause() { this.pauseCount++; }
    fire(type) { (this.handlers[type] || []).forEach(fn => fn()); }
  };
}

function makeReader() {
  const registry = { instances: [] };
  const provider = makeProvider();
  const url = makeURL();
  const Audio = makeAudioClass(registry);
  const reader = new PiperReader({
    Audio,
    URL: url,
    provider,
    chunker: TextChunker,
    nav: TextNav,
    i18n: { t: (k) => k },
    logger: { info() {}, debug() {}, warn() {}, error() {} },
    b64ToBlob: () => ({ size: 1024 }),
  });
  return { reader, provider, url, audio: () => registry.instances[0], registry };
}

const LONG = 'First sentence is here and reasonably sized. '
  + 'Second sentence follows and is also a fair length. '
  + 'Third sentence keeps going so we get multiple chunks. '
  + 'Fourth sentence wraps this up nicely for testing.';

// ---------------------------------------------------------------------------

test('happy path: chunk resolves, audio plays the created URL', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { reader, provider, url, audio } = makeReader();

  const startP = reader.start(LONG, { voice: 'v' });
  assert.strictEqual(reader.state, 'loading');
  provider.resolveAll();
  await startP;

  assert.strictEqual(reader.state, 'playing');
  assert.ok(url.created.length >= 1, 'a URL should have been created');
  assert.strictEqual(audio().src, url.created[0], 'audio.src should be the first chunk URL');
  assert.ok(audio().playCount >= 1, 'play() should have been called');
});

test('provider receives normalized per-chunk options', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { reader, provider } = makeReader();
  const startP = reader.start(LONG, { voice: 'en_US-x', rate: 1.25, volume: 0.8, textFormat: 'markdown' });
  provider.resolveAll();
  await startP;
  const first = provider.calls[0];
  assert.strictEqual(first.opts.voice, 'en_US-x');
  assert.strictEqual(first.opts.rate, 1.25);
  assert.strictEqual(first.opts.volume, 0.8);
  assert.strictEqual(first.opts.textFormat, 'markdown');
});

test('start() with no provider emits an error and does not play', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const registry = { instances: [] };
  const url = makeURL();
  const Audio = makeAudioClass(registry);
  const errors = [];
  const reader = new PiperReader({ Audio, URL: url, chunker: TextChunker, i18n: { t: (k) => k }, b64ToBlob: () => ({ size: 1 }) });
  reader.on('error', (e) => errors.push(e));
  const ok = await reader.start(LONG, { voice: 'v' }); // no provider supplied
  assert.strictEqual(ok, false);
  assert.strictEqual(url.created.length, 0);
  assert.ok(errors.length >= 1);
});

test('stop() before chunk resolves: stale synth never creates a URL or plays', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { reader, provider, url, audio } = makeReader();

  const startP = reader.start(LONG, { voice: 'v' });     // session begins, awaiting chunk 0
  const stopped = reader.stop();                          // supersedes the session
  provider.resolveAll();                                  // stale results arrive late
  const ok = await startP;

  assert.strictEqual(stopped, true);
  assert.strictEqual(ok, false, 'superseded start() must resolve falsy');
  assert.strictEqual(reader.state, 'idle');
  assert.strictEqual(url.created.length, 0, 'no object URL may be created for a stale session');
  assert.strictEqual(audio().playCount, 0, 'stale audio must never play');
});

test('_hardStop revokes a cached URL and clears the cache (no leaks)', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { reader, provider, url } = makeReader();

  const startP = reader.start(LONG, { voice: 'v' });
  provider.resolveAll();
  await startP;                                           // now playing, URL(s) live

  const liveBefore = url.live.size;
  assert.ok(liveBefore >= 1, 'expected at least one live URL while playing');

  reader.stop();                                          // triggers _hardStop
  assert.strictEqual(url.live.size, 0, 'every object URL must be revoked on stop');
  assert.strictEqual(reader.audioCache.size, 0, 'audioCache must be cleared');
});

test('starting a new session supersedes the old one; only the latest plays', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { reader, provider, url, audio } = makeReader();

  const first = reader.start(LONG, { voice: 'v' });       // session A (awaiting)
  const second = reader.start(LONG, { voice: 'v' });      // session B supersedes A
  provider.resolveAll();                                  // resolve everything

  const rFirst = await first;
  const rSecond = await second;

  assert.strictEqual(rFirst, false, 'the superseded session must not report success');
  assert.strictEqual(rSecond, true, 'the latest session should play');
  assert.strictEqual(reader.state, 'playing');
  assert.ok(url.live.has(audio().src), 'audio.src must be a live (non-revoked) URL');
});

test('reaching end of chunks finishes and revokes everything', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { reader, provider, url, audio } = makeReader();

  const startP = reader.start('Only one short chunk here.', { voice: 'v' });
  provider.resolveAll();
  await startP;
  assert.strictEqual(reader.state, 'playing');

  audio().fire('ended');                                  // last chunk ends
  assert.strictEqual(reader.state, 'done');
  assert.strictEqual(url.live.size, 0, 'finishing must revoke all URLs');
});

test('retries a transient chunk failure, then succeeds', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const registry = { instances: [] };
  const url = makeURL();
  const Audio = makeAudioClass(registry);
  let calls = 0;
  const provider = {
    id: 'x',
    synthesize() {
      calls++;
      if (calls <= 2) return Promise.reject(new Error('Could not reach OpenAI. Check your internet connection.'));
      return Promise.resolve({ b64: 'AAAA', mime: 'audio/mpeg' });
    },
  };
  const reader = new PiperReader({
    Audio, URL: url, provider, chunker: TextChunker, maxRetries: 3, retryBaseMs: 100,
    schedule: (fn) => fn(),   // run backoff immediately for deterministic testing
    i18n: { t: (k) => k }, b64ToBlob: () => ({ size: 1 }),
  });
  const startP = reader.start('Short text here.', { voice: 'v' });
  for (let k = 0; k < 12; k++) await Promise.resolve();
  const ok = await startP;
  assert.strictEqual(ok, true, 'should eventually play after retries');
  assert.strictEqual(calls, 3, 'two failures then one success');
  assert.strictEqual(reader.state, 'playing');
});

test('does not retry a non-retryable error (unauthorized)', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const registry = { instances: [] };
  const url = makeURL();
  const Audio = makeAudioClass(registry);
  let calls = 0;
  const provider = {
    id: 'x',
    synthesize() { calls++; return Promise.reject(new Error('OpenAI rejected the API key (unauthorized).')); },
  };
  const errors = [];
  const reader = new PiperReader({
    Audio, URL: url, provider, chunker: TextChunker, maxRetries: 3, retryBaseMs: 100,
    i18n: { t: (k) => k }, b64ToBlob: () => ({ size: 1 }),
  });
  reader.on('error', (e) => errors.push(e));
  const ok = await reader.start('Short text here.', { voice: 'v' });
  assert.strictEqual(ok, false);
  assert.strictEqual(calls, 1, 'must not retry a deterministic auth error');
  assert.ok(errors.length >= 1);
});

test('stop() asks the provider to cancel pending requests', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const registry = { instances: [] };
  const url = makeURL();
  const Audio = makeAudioClass(registry);
  let cancelPendingCalls = 0;
  const provider = {
    id: 'x',
    synthesize: () => Promise.resolve({ b64: 'AAAA', mime: 'audio/wav' }),
    cancelPending() { cancelPendingCalls++; },
  };
  const reader = new PiperReader({
    Audio, URL: url, provider, chunker: TextChunker,
    i18n: { t: (k) => k }, b64ToBlob: () => ({ size: 1 }),
  });
  await reader.start('Short.', { voice: 'v' });
  reader.stop();
  assert.ok(cancelPendingCalls >= 1, 'provider.cancelPending should be invoked on stop');
});

test('start() uses an injected chunker and maxChars', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const registry = { instances: [] };
  const url = makeURL();
  const Audio = makeAudioClass(registry);
  const provider = makeProvider();
  const seen = [];
  const fakeChunker = {
    chunk(text, maxChars) { seen.push(maxChars); return [{ text, start: 0, end: text.length }]; },
    findChunkAtPosition() { return 0; },
  };
  const reader = new PiperReader({
    Audio, URL: url, provider, chunker: TextChunker,
    i18n: { t: (k) => k }, b64ToBlob: () => ({ size: 1 }),
  });
  const startP = reader.start('Some text.', { voice: 'v', chunker: fakeChunker, maxChars: 1600 });
  provider.resolveAll();
  await startP;
  assert.deepStrictEqual(seen, [1600], 'injected chunker + maxChars should be used');
});

test('provider-supplied mime is used to build the blob', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const registry = { instances: [] };
  const url = makeURL();
  const Audio = makeAudioClass(registry);
  const provider = makeProvider();
  const seen = [];
  const reader = new PiperReader({
    Audio, URL: url, provider, chunker: TextChunker,
    i18n: { t: (k) => k },
    b64ToBlob: (b64, mime) => { seen.push(mime); return { size: 1 }; },
  });
  const startP = reader.start('Short.', { voice: 'v' });
  provider.resolveAll('AAAA', 'audio/mpeg');
  await startP;
  assert.ok(seen.includes('audio/mpeg'), 'blob should be built with the provider mime');
});

test('seekToChar within the current chunk updates currentTime (no new session)', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { reader, provider, audio } = makeReader();
  const text = 'AAAAAAAAAA BBBBBBBBBB CCCCCCCCCC'; // one chunk typically
  const startP = reader.start(text, { voice: 'v', maxChars: 500 });
  provider.resolveAll();
  await startP;
  const sid = reader.sessionId;
  const a = audio();
  a.duration = 10;
  a.currentTime = 0;
  const mid = Math.floor(text.length / 2);
  const ok = reader.seekToChar(mid);
  assert.strictEqual(ok, true);
  assert.strictEqual(reader.sessionId, sid, 'intra-chunk seek must keep the session');
  assert.ok(a.currentTime > 0, 'audio.currentTime should advance');
});

test('skipSentence jumps forward and emits progress with timing', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { reader, provider } = makeReader();
  const text = 'First sentence here. Second sentence follows. Third ends it.';
  const events = [];
  reader.on('progress', (p) => events.push(p));
  const startP = reader.start(text, { voice: 'v', maxChars: 500 });
  provider.resolveAll();
  await startP;
  // Force known duration so char index can move with seek
  // (FakeAudio from makeReader)
  const a = reader.audio;
  a.duration = 30;
  a.currentTime = 0;
  const before = reader._currentCharIndex();
  reader.skipSentence(1);
  const after = reader._currentCharIndex();
  assert.ok(after >= before, 'should move forward or stay at boundary');
  const last = events[events.length - 1];
  assert.ok(last && typeof last.elapsedSec === 'number', 'progress includes elapsedSec');
  assert.ok(last && typeof last.remainingSec === 'number', 'progress includes remainingSec');
  assert.ok(typeof last.sentenceStart === 'number');
});

test('pause then resume keeps highlight position via progress charIndex', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { reader, provider, audio } = makeReader();
  const startP = reader.start(LONG, { voice: 'v' });
  provider.resolveAll();
  await startP;
  audio().duration = 20;
  audio().currentTime = 5;
  reader._emitProgress();
  const atPause = reader._currentCharIndex();
  reader.pause();
  assert.strictEqual(reader.state, 'paused');
  await reader.resume();
  assert.strictEqual(reader.state, 'playing');
  // Position unchanged on resume (currentTime still 5)
  assert.strictEqual(reader._currentCharIndex(), atPause);
});
