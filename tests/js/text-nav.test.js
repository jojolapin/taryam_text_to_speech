/* Tests for ui/lib/text-nav.js (sentence/paragraph nav + timing).
 * (C) 2026 JojoLapin Inc.  Run: npm test
 */
'use strict';

const { test } = require('node:test');
const assert = require('node:assert');
const { TextNav } = require('../../ui/lib/text-nav.js');

test('sentenceAt finds the enclosing sentence', () => {
  const text = 'Hello world. Second sentence! Third?';
  const a = TextNav.sentenceAt(text, 3);
  assert.strictEqual(text.slice(a.start, a.end), 'Hello world.');
  const b = TextNav.sentenceAt(text, 20);
  assert.ok(b.start > a.end - 1);
  assert.match(text.slice(b.start, b.end), /Second/);
});

test('decimals do not end a sentence', () => {
  const text = 'Pi is 3.14 today. Done.';
  const a = TextNav.sentenceAt(text, 5);
  assert.ok(a.end > text.indexOf('3.14'));
  assert.match(text.slice(a.start, a.end), /3\.14/);
});

test('next/prev sentence navigation', () => {
  const text = 'One. Two. Three.';
  const mid = TextNav.sentenceAt(text, 0).end; // at/after first end
  const next = TextNav.nextSentenceStart(text, 1);
  assert.ok(next > 0);
  assert.strictEqual(TextNav.sentenceAt(text, next).start, next);
  const back = TextNav.prevSentenceStart(text, next + 1);
  assert.strictEqual(back, next); // still in second sentence -> its start
  const first = TextNav.prevSentenceStart(text, next);
  assert.strictEqual(first, 0);
});

test('paragraphAt splits on blank lines', () => {
  const text = 'Para one.\n\nPara two has more.';
  const a = TextNav.paragraphAt(text, 2);
  assert.match(text.slice(a.start, a.end), /Para one/);
  const b = TextNav.paragraphAt(text, text.indexOf('two'));
  assert.match(text.slice(b.start, b.end), /Para two/);
});

test('next/prev paragraph navigation', () => {
  const text = 'A\n\nB\n\nC';
  const n1 = TextNav.nextParagraphStart(text, 0);
  assert.strictEqual(text[n1], 'B');
  const n2 = TextNav.nextParagraphStart(text, n1);
  assert.strictEqual(text[n2], 'C');
  const p = TextNav.prevParagraphStart(text, n2);
  assert.strictEqual(p, n1);
});

test('wordAt expands to word bounds', () => {
  const text = 'Say hello there';
  const w = TextNav.wordAt(text, 6);
  assert.strictEqual(text.slice(w.start, w.end), 'hello');
});

test('estimateTiming scales with rate and position', () => {
  const a = TextNav.estimateTiming(120, 240, 1.0); // cps=12
  assert.strictEqual(a.elapsedSec, 10);
  assert.strictEqual(a.remainingSec, 10);
  const fast = TextNav.estimateTiming(120, 240, 2.0); // cps=24
  assert.strictEqual(fast.elapsedSec, 5);
  assert.ok(fast.remainingSec < a.remainingSec);
});

test('formatClock pads seconds', () => {
  assert.strictEqual(TextNav.formatClock(65), '1:05');
  assert.strictEqual(TextNav.formatClock(5), '0:05');
  assert.strictEqual(TextNav.formatClock(0), '0:00');
});

// ---- weighted position mapping (highlight <-> audio sync) -----------------

test('charWeight: punctuation costs more than letters, whitespace less', () => {
  assert.ok(TextNav.charWeight('.') > TextNav.charWeight('a'));
  assert.ok(TextNav.charWeight(',') > TextNav.charWeight('a'));
  assert.ok(TextNav.charWeight(' ') < TextNav.charWeight('a'));
});

test('buildWeights: cumulative and total are consistent', () => {
  const text = 'Hi, world.';
  const w = TextNav.buildWeights(text, 0, text.length);
  assert.strictEqual(w.cum.length, text.length);
  assert.ok(w.total > 0);
  assert.strictEqual(w.cum[w.cum.length - 1], w.total);
});

test('offsetForFraction: endpoints map to span bounds', () => {
  const text = 'Hello world.';
  const w = TextNav.buildWeights(text, 0, text.length);
  assert.strictEqual(TextNav.offsetForFraction(w, 0), 0);
  assert.strictEqual(TextNav.offsetForFraction(w, 1), text.length - 1);
});

test('offsetForFraction lingers on a sentence-ending pause vs flat mapping', () => {
  // Text where a period sits early; weighted mapping should keep the marker
  // near the pause for a larger slice of the audio timeline than flat mapping.
  const text = 'Go. ' + 'x'.repeat(20);
  const w = TextNav.buildWeights(text, 0, text.length);
  const periodIdx = text.indexOf('.');
  // At ~30% of the audio, the flat mapping is already well past the period,
  // but the weighted mapping (pause cost on '.') is still at/near it.
  const flat = Math.floor(0.30 * text.length);
  const weighted = TextNav.offsetForFraction(w, 0.30);
  assert.ok(weighted <= periodIdx + 1, `weighted (${weighted}) should linger near period (${periodIdx})`);
  assert.ok(flat > weighted, 'flat mapping runs ahead of the weighted (voice-synced) one');
});

test('fractionForOffset is the inverse of offsetForFraction (round-trip)', () => {
  const text = 'One, two, three. Four!';
  const w = TextNav.buildWeights(text, 0, text.length);
  for (const off of [0, 4, 10, 16, 20]) {
    const f = TextNav.fractionForOffset(w, off);
    const back = TextNav.offsetForFraction(w, f);
    assert.ok(Math.abs(back - off) <= 1, `round-trip off=${off} -> ${back}`);
  }
});

test('buildWeights honours a sub-span (chunk start/end)', () => {
  const text = 'AAAA. BBBB. CCCC.';
  const w = TextNav.buildWeights(text, 6, 11); // "BBBB."
  assert.strictEqual(w.start, 6);
  assert.strictEqual(w.end, 11);
  assert.strictEqual(TextNav.offsetForFraction(w, 0), 6);
  assert.ok(TextNav.offsetForFraction(w, 1) < 11);
});
