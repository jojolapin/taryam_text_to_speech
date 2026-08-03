/* Regression tests for the PiperReader playback core (ui/lib/piper-reader.js).
 * (C) 2026 JojoLapin Inc.
 * Run: node --test tests/js/   (or: npm test)
 *
 * These pin the SENSITIVE guarantees that must never regress:
 *   - stale audio from a stopped/superseded session never plays;
 *   - _hardStop revokes every object URL (no leaks);
 *   - only the latest session ever reaches playback.
 * Timers are mocked so the 60s chunk-wait watchdog never keeps Node alive.
 */
'use strict';

const { test, mock } = require('node:test');
const assert = require('node:assert');

const { TextChunker } = require('../../ui/lib/text-chunker.js');
const { PiperReader } = require('../../ui/lib/piper-reader.js');

// ---- test doubles ---------------------------------------------------------

function deferred() {
  let resolve, reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function makeBridge() {
  const calls = [];
  return {
    synthesize(text, voice, lengthScale, volume, fmt) {
      const d = deferred();
      calls.push({ text, d });
      return d.promise;
    },
    calls,
    resolveAll(b64 = 'AAAA') { calls.forEach(c => c.d.resolve({ wavB64: b64 })); },
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
  const bridge = makeBridge();
  const url = makeURL();
  const Audio = makeAudioClass(registry);
  const reader = new PiperReader({
    Audio,
    URL: url,
    bridge,
    chunker: TextChunker,
    i18n: { t: (k) => k },
    logger: { info() {}, debug() {}, warn() {}, error() {} },
    b64ToBlob: () => ({ size: 1024 }),
  });
  return { reader, bridge, url, audio: () => registry.instances[0], registry };
}

const LONG = 'First sentence is here and reasonably sized. '
  + 'Second sentence follows and is also a fair length. '
  + 'Third sentence keeps going so we get multiple chunks. '
  + 'Fourth sentence wraps this up nicely for testing.';

// ---------------------------------------------------------------------------

test('happy path: chunk resolves, audio plays the created URL', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { reader, bridge, url, audio } = makeReader();

  const startP = reader.start(LONG, { voice: 'v' });
  assert.strictEqual(reader.state, 'loading');
  bridge.resolveAll();
  await startP;

  assert.strictEqual(reader.state, 'playing');
  assert.ok(url.created.length >= 1, 'a URL should have been created');
  assert.strictEqual(audio().src, url.created[0], 'audio.src should be the first chunk URL');
  assert.ok(audio().playCount >= 1, 'play() should have been called');
});

test('stop() before chunk resolves: stale synth never creates a URL or plays', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { reader, bridge, url, audio } = makeReader();

  const startP = reader.start(LONG, { voice: 'v' });     // session begins, awaiting chunk 0
  const stopped = reader.stop();                          // supersedes the session
  bridge.resolveAll();                                    // stale results arrive late
  const ok = await startP;

  assert.strictEqual(stopped, true);
  assert.strictEqual(ok, false, 'superseded start() must resolve falsy');
  assert.strictEqual(reader.state, 'idle');
  assert.strictEqual(url.created.length, 0, 'no object URL may be created for a stale session');
  assert.strictEqual(audio().playCount, 0, 'stale audio must never play');
});

test('_hardStop revokes a cached URL and clears the cache (no leaks)', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { reader, bridge, url } = makeReader();

  const startP = reader.start(LONG, { voice: 'v' });
  bridge.resolveAll();
  await startP;                                           // now playing, URL(s) live

  const liveBefore = url.live.size;
  assert.ok(liveBefore >= 1, 'expected at least one live URL while playing');

  reader.stop();                                          // triggers _hardStop
  assert.strictEqual(url.live.size, 0, 'every object URL must be revoked on stop');
  assert.strictEqual(reader.audioCache.size, 0, 'audioCache must be cleared');
});

test('starting a new session supersedes the old one; only the latest plays', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { reader, bridge, url, audio } = makeReader();

  const first = reader.start(LONG, { voice: 'v' });       // session A (awaiting)
  const second = reader.start(LONG, { voice: 'v' });      // session B supersedes A
  bridge.resolveAll();                                    // resolve everything

  const rFirst = await first;
  const rSecond = await second;

  assert.strictEqual(rFirst, false, 'the superseded session must not report success');
  assert.strictEqual(rSecond, true, 'the latest session should play');
  assert.strictEqual(reader.state, 'playing');
  // Exactly one live URL is bound to the audio element for the active session.
  assert.ok(url.live.has(audio().src), 'audio.src must be a live (non-revoked) URL');
});

test('reaching end of chunks finishes and revokes everything', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { reader, bridge, url, audio } = makeReader();

  // Single short chunk so one "ended" completes the document.
  const startP = reader.start('Only one short chunk here.', { voice: 'v' });
  bridge.resolveAll();
  await startP;
  assert.strictEqual(reader.state, 'playing');

  audio().fire('ended');                                  // last chunk ends
  assert.strictEqual(reader.state, 'done');
  assert.strictEqual(url.live.size, 0, 'finishing must revoke all URLs');
});
