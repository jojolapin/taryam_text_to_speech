/* Regression tests for TextChunker (ui/lib/text-chunker.js).
 * (C) 2026 JojoLapin Inc.
 * Run: node --test tests/js/   (or: npm test)
 *
 * These lock in the CURRENT chunking behaviour so the Phase 4 semantic chunker
 * can be validated against a known baseline. Do not "fix" expectations to make
 * a future change pass — add new tests for new behaviour instead.
 */
'use strict';

const { test } = require('node:test');
const assert = require('node:assert');
const { TextChunker } = require('../../ui/lib/text-chunker.js');

test('empty string yields no chunks', () => {
  assert.deepStrictEqual(TextChunker.chunk(''), []);
});

test('whitespace-only string yields no chunks', () => {
  assert.deepStrictEqual(TextChunker.chunk('   \n\t  '), []);
});

test('short text is a single chunk with correct offsets', () => {
  const text = 'Hello world.';
  const chunks = TextChunker.chunk(text);
  assert.strictEqual(chunks.length, 1);
  assert.strictEqual(chunks[0].text, 'Hello world.');
  assert.strictEqual(chunks[0].start, 0);
  assert.ok(chunks[0].end <= text.length);
});

test('no chunk is ever empty and offsets are within bounds', () => {
  const text = 'A '.repeat(500) + 'end.';
  const chunks = TextChunker.chunk(text, 120);
  assert.ok(chunks.length > 1, 'expected multiple chunks');
  for (const c of chunks) {
    assert.ok(c.text.length > 0, 'empty chunk text');
    assert.ok(c.start >= 0 && c.end <= text.length, 'offset out of bounds');
    assert.ok(c.end > c.start, 'end must be after start');
    // The stored text is the trimmed slice of the source at [start, end)
    assert.strictEqual(c.text, text.slice(c.start, c.end).trim());
  }
});

test('chunk offsets are non-decreasing and cover the text in order', () => {
  const text = 'Sentence one is here. Sentence two follows it. Sentence three ends things. '.repeat(10);
  const chunks = TextChunker.chunk(text, 100);
  let prevEnd = 0;
  for (const c of chunks) {
    assert.ok(c.start >= prevEnd - 1, 'chunks should progress forward');
    assert.ok(c.end >= c.start);
    prevEnd = c.end;
  }
});

test('prefers sentence boundaries when available', () => {
  // maxChars chosen so the split must land somewhere inside; a sentence end
  // exists comfortably past minChars, so the first chunk should end at it.
  const text = 'First sentence here. Second sentence is a bit longer than the first one.';
  const chunks = TextChunker.chunk(text, 40);
  assert.ok(chunks.length >= 2);
  assert.ok(chunks[0].text.endsWith('.'), `expected sentence-boundary split, got: ${chunks[0].text}`);
});

test('findChunkAtPosition returns the first chunk whose end passes the position', () => {
  const chunks = [
    { text: 'a', start: 0, end: 10 },
    { text: 'b', start: 10, end: 20 },
    { text: 'c', start: 20, end: 30 },
  ];
  assert.strictEqual(TextChunker.findChunkAtPosition(chunks, 0), 0);
  assert.strictEqual(TextChunker.findChunkAtPosition(chunks, 9), 0);
  assert.strictEqual(TextChunker.findChunkAtPosition(chunks, 10), 1);
  assert.strictEqual(TextChunker.findChunkAtPosition(chunks, 25), 2);
});

test('findChunkAtPosition clamps to the last chunk past the end', () => {
  const chunks = [{ text: 'a', start: 0, end: 10 }];
  assert.strictEqual(TextChunker.findChunkAtPosition(chunks, 9999), 0);
});

test('findChunkAtPosition on empty list returns 0', () => {
  assert.strictEqual(TextChunker.findChunkAtPosition([], 5), 0);
});
