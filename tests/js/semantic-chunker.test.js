/* Tests for the SemanticChunker (ui/lib/semantic-chunker.js).
 * (C) 2026 JojoLapin Inc.  Run: npm test
 *
 * Core guarantees:
 *   - chunks never exceed maxChars (unless a single protected span is longer);
 *   - boundaries never split a decimal/date/time/initial/abbreviation/URL/email;
 *   - offsets are exact and monotonic; concatenation reproduces the source words.
 */
'use strict';

const { test } = require('node:test');
const assert = require('node:assert');

const { SemanticChunker } = require('../../ui/lib/semantic-chunker.js');

// A protected substring must live entirely within a single chunk (never straddle
// a boundary). We check that some chunk's [start,end) fully contains each hit.
function assertNeverSplit(text, needle, maxChars) {
  const chunks = SemanticChunker.chunk(text, maxChars);
  let from = 0, idx;
  let occurrences = 0;
  while ((idx = text.indexOf(needle, from)) !== -1) {
    occurrences++;
    const s = idx, e = idx + needle.length;
    const containing = chunks.find(c => c.start <= s && c.end >= e);
    assert.ok(containing, `"${needle}" @${s} was split across chunks: ${JSON.stringify(chunks.map(c => [c.start, c.end]))}`);
    from = idx + needle.length;
  }
  assert.ok(occurrences > 0, `needle "${needle}" not present in test text`);
}

test('empty / whitespace text yields no chunks', () => {
  assert.deepStrictEqual(SemanticChunker.chunk('', 100), []);
  assert.deepStrictEqual(SemanticChunker.chunk('   \n\t ', 100), []);
});

test('splits on sentence boundaries', () => {
  const text = 'First sentence. Second sentence! Third sentence?';
  const chunks = SemanticChunker.chunk(text, 20);
  assert.ok(chunks.length >= 3);
  assert.strictEqual(chunks[0].text, 'First sentence.');
});

test('never exceeds maxChars for ordinary prose', () => {
  const text = ('The quick brown fox jumps over the lazy dog. ').repeat(60);
  const chunks = SemanticChunker.chunk(text, 200);
  for (const c of chunks) assert.ok(c.end - c.start <= 200, `chunk too long: ${c.end - c.start}`);
});

test('offsets are monotonic and slice back to the trimmed text', () => {
  const text = 'Alpha beta gamma. Delta epsilon zeta. Eta theta iota.';
  const chunks = SemanticChunker.chunk(text, 25);
  let last = 0;
  for (const c of chunks) {
    assert.ok(c.start >= last, 'starts must be non-decreasing');
    assert.strictEqual(text.slice(c.start, c.end).trim(), c.text);
    last = c.start;
  }
});

// ---- protected spans: the corpus ----------------------------------------

test('decimals are never split', () => {
  const text = 'The value is 3.14159 today. Pi matters. It equals 2.71828 elsewhere.';
  for (const m of ['3.14159', '2.71828']) assertNeverSplit(text, m, 16);
});

test('thousands separators are never split', () => {
  const text = 'We sold 1,234,567 units. Revenue rose. Costs were 89,000 dollars.';
  for (const m of ['1,234,567', '89,000']) assertNeverSplit(text, m, 14);
});

test('dates and times are never split', () => {
  const text = 'Meet on 2026-08-03 sharp. Then again. Or 12/25/2026 at 3:30 works fine.';
  for (const m of ['2026-08-03', '12/25/2026', '3:30']) assertNeverSplit(text, m, 12);
});

test('initials are never split', () => {
  const text = 'The author J.R.R. Tolkien wrote it. Fans agree. So did E.B. White surely.';
  for (const m of ['J.R.R.', 'E.B.']) assertNeverSplit(text, m, 14);
});

test('listed abbreviations do not cause a false sentence break', () => {
  const text = 'Dr. Smith met Mr. Brown today. They talked. See Fig. 4 and Vol. 2 later.';
  const chunks = SemanticChunker.chunk(text, 200);
  // "Dr. Smith met Mr. Brown today." should be one sentence, not four.
  assert.ok(chunks.some(c => c.text.includes('Dr. Smith met Mr. Brown today.')),
    'abbreviation periods must not split the sentence: ' + JSON.stringify(chunks.map(c => c.text)));
});

test('e.g. / i.e. do not cause a false sentence break', () => {
  const text = 'Use fruit, e.g. apples and pears, in the pie. Then bake it slowly.';
  const chunks = SemanticChunker.chunk(text, 200);
  assert.ok(chunks.some(c => c.text.includes('e.g. apples')),
    'e.g. must not split: ' + JSON.stringify(chunks.map(c => c.text)));
});

test('URLs are never split', () => {
  const text = 'Visit https://example.com/path?q=1&x=2 now. It is great. Really good stuff here.';
  assertNeverSplit(text, 'https://example.com/path?q=1&x=2', 20);
});

test('emails are never split', () => {
  const text = 'Email john.doe@example.co.uk please. He replies. Support helps you fast too.';
  assertNeverSplit(text, 'john.doe@example.co.uk', 18);
});

test('a single oversized protected span is kept whole (own chunk)', () => {
  const longUrl = 'https://example.com/' + 'a'.repeat(300);
  const text = `Start here. ${longUrl} End here.`;
  const chunks = SemanticChunker.chunk(text, 50);
  const containing = chunks.find(c => text.slice(c.start, c.end).includes(longUrl));
  assert.ok(containing, 'oversized URL should be preserved in a single chunk');
});

test('paragraph break is a preferred split point when exceeding the limit', () => {
  const text = 'Para one line here.\n\nPara two line here.';
  // Small limit forces a split; it should land on the blank-line boundary.
  const chunks = SemanticChunker.chunk(text, 22);
  assert.ok(chunks.length >= 2);
  assert.ok(chunks.some(c => c.text === 'Para one line here.'),
    'split should occur at the paragraph boundary: ' + JSON.stringify(chunks.map(c => c.text)));
});

test('small paragraphs merge up to maxChars (descend only when needed)', () => {
  const text = 'Para one.\n\nPara two.\n\nPara three.';
  const chunks = SemanticChunker.chunk(text, 500);
  assert.strictEqual(chunks.length, 1, 'tiny paragraphs under the limit merge into one section');
});

test('findChunkAtPosition matches TextChunker semantics', () => {
  const text = 'Alpha beta gamma. Delta epsilon zeta. Eta theta iota kappa.';
  const chunks = SemanticChunker.chunk(text, 20);
  assert.strictEqual(SemanticChunker.findChunkAtPosition(chunks, 0), 0);
  const midIdx = SemanticChunker.findChunkAtPosition(chunks, text.length - 1);
  assert.strictEqual(midIdx, chunks.length - 1);
  assert.strictEqual(SemanticChunker.findChunkAtPosition([], 5), 0);
});

test('large 50k-char document chunks without splitting protected spans', () => {
  const unit = 'On 2026-08-03, Dr. Smith paid $1,234.56 to a.b@c.io via https://x.io/p. ';
  const text = unit.repeat(700); // ~49k chars
  const chunks = SemanticChunker.chunk(text, 1600);
  assert.ok(chunks.length > 20, 'should produce many sections');
  for (const c of chunks) {
    assert.ok(c.end - c.start <= 1600 + 80, 'sections stay near the limit');
  }
  for (const m of ['2026-08-03', '$1,234.56'.slice(1), 'a.b@c.io', 'https://x.io/p']) {
    assertNeverSplit(text, m, 1600);
  }
});
