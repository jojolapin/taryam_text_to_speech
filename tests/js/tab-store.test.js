/* Regression tests for the multi-tab document model (ui/lib/tabs.js).
 * (C) 2026 JojoLapin Inc.
 * Run: npm test
 */
'use strict';

const { test } = require('node:test');
const assert = require('node:assert');

const { TabStore, TabPersistence, createDocument, deriveTitle } = require('../../ui/lib/tabs.js');

function store() {
  let clock = 1000;
  const s = new TabStore({ now: () => ++clock });
  return s;
}

test('createDocument fills defaults and a stable id', () => {
  const d = createDocument({ text: 'hi' });
  assert.ok(d.id);
  assert.strictEqual(d.text, 'hi');
  assert.strictEqual(d.provider, 'piper');
  assert.strictEqual(d.audioStatus, 'idle');
  assert.deepStrictEqual(d.bookmarks, []);
  assert.ok(d.createdAt && d.updatedAt);
});

test('init guarantees at least one tab and a valid activeId', () => {
  const s = store();
  const active = s.init([], null);
  assert.strictEqual(s.count(), 1);
  assert.strictEqual(active.id, s.activeId);
});

test('init keeps a valid provided activeId', () => {
  const s = store();
  const a = createDocument({ title: 'A' });
  const b = createDocument({ title: 'B' });
  s.init([a, b], b.id);
  assert.strictEqual(s.activeId, b.id);
});

test('init falls back to first tab for an unknown activeId', () => {
  const s = store();
  const a = createDocument({ title: 'A' });
  s.init([a], 'nonexistent');
  assert.strictEqual(s.activeId, a.id);
});

test('create adds and activates a new tab', () => {
  const s = store();
  s.init([]);
  const first = s.activeId;
  const doc = s.create({ text: 'second' });
  assert.strictEqual(s.count(), 2);
  assert.strictEqual(s.activeId, doc.id);
  assert.notStrictEqual(doc.id, first);
});

test('closing the active tab activates the left neighbour', () => {
  const s = store();
  const a = createDocument({ title: 'A' });
  const b = createDocument({ title: 'B' });
  const c = createDocument({ title: 'C' });
  s.init([a, b, c], b.id);
  const res = s.close(b.id);
  assert.strictEqual(res.wasActive, true);
  assert.strictEqual(res.newActiveId, a.id);
  assert.strictEqual(s.count(), 2);
});

test('closing the last tab creates a fresh blank tab', () => {
  const s = store();
  const a = createDocument({ title: 'only', text: 'x' });
  s.init([a], a.id);
  const res = s.close(a.id);
  assert.strictEqual(s.count(), 1);
  assert.notStrictEqual(s.activeId, a.id);
  assert.strictEqual(s.active().text, '');
});

test('closing an inactive tab keeps the active one', () => {
  const s = store();
  const a = createDocument({ title: 'A' });
  const b = createDocument({ title: 'B' });
  s.init([a, b], a.id);
  const res = s.close(b.id);
  assert.strictEqual(res.wasActive, false);
  assert.strictEqual(s.activeId, a.id);
});

test('rename sets the title', () => {
  const s = store();
  s.init([]);
  s.rename(s.activeId, 'My Title');
  assert.strictEqual(s.active().title, 'My Title');
});

test('duplicate inserts a copy after the source and marks it (copy)', () => {
  const s = store();
  const a = createDocument({ title: 'Doc', text: 'body' });
  s.init([a], a.id);
  const copy = s.duplicate(a.id);
  assert.strictEqual(s.count(), 2);
  assert.strictEqual(s.indexOf(copy.id), 1);
  assert.strictEqual(copy.text, 'body');
  assert.notStrictEqual(copy.id, a.id);
  assert.ok(copy.title.includes('copy'));
});

test('reorder moves a tab and preserves the rest', () => {
  const s = store();
  const a = createDocument({ title: 'A' });
  const b = createDocument({ title: 'B' });
  const c = createDocument({ title: 'C' });
  s.init([a, b, c], a.id);
  assert.strictEqual(s.reorder(0, 2), true);
  assert.deepStrictEqual(s.list().map(d => d.title), ['B', 'C', 'A']);
});

test('moveTo relocates by id', () => {
  const s = store();
  const a = createDocument({ title: 'A' });
  const b = createDocument({ title: 'B' });
  const c = createDocument({ title: 'C' });
  s.init([a, b, c], a.id);
  s.moveTo(c.id, 0);
  assert.deepStrictEqual(s.list().map(d => d.title), ['C', 'A', 'B']);
});

test('setActive switches tabs and reports change', () => {
  const s = store();
  const a = createDocument({ title: 'A' });
  const b = createDocument({ title: 'B' });
  s.init([a, b], a.id);
  assert.strictEqual(s.setActive(b.id), true);
  assert.strictEqual(s.activeId, b.id);
  assert.strictEqual(s.setActive(b.id), false); // already active
});

test('update merges a patch into a doc', () => {
  const s = store();
  s.init([]);
  s.update(s.activeId, { voice: 'en_US-lessac-medium', speed: 1.25 });
  assert.strictEqual(s.active().voice, 'en_US-lessac-medium');
  assert.strictEqual(s.active().speed, 1.25);
});

test('deriveTitle uses first non-empty line then falls back', () => {
  assert.strictEqual(deriveTitle({ title: '  Hi  ' }), 'Hi');
  assert.strictEqual(deriveTitle({ title: '', text: '\n\n  Hello world \nmore' }), 'Hello world');
  assert.strictEqual(deriveTitle({ title: '', text: '' }, 'Untitled'), 'Untitled');
});

test('onChange listeners fire on mutation and can unsubscribe', () => {
  const s = store();
  s.init([]);
  let count = 0;
  const off = s.onChange(() => { count++; });
  s.create({});
  s.rename(s.activeId, 'x');
  const afterTwo = count;
  assert.ok(afterTwo >= 2);
  off();
  s.create({});
  assert.strictEqual(count, afterTwo, 'no further events after unsubscribe');
});

test('snapshot is round-trippable through a fake persistence layer', async () => {
  // In-memory fake IndexedDB substitute exercising TabPersistence via injection.
  const mem = new Map();
  const fakeIDB = makeFakeIndexedDB(mem);
  const p = new TabPersistence({ indexedDB: fakeIDB });
  assert.strictEqual(p.available, true);

  const s = store();
  const a = createDocument({ title: 'A', text: 'alpha' });
  s.init([a], a.id);
  const saved = await p.save(s.snapshot());
  assert.strictEqual(saved, true);

  const loaded = await p.load();
  assert.ok(loaded);
  assert.strictEqual(loaded.activeId, a.id);
  assert.strictEqual(loaded.docs[0].text, 'alpha');
});

test('TabPersistence degrades gracefully with no IndexedDB', async () => {
  const p = new TabPersistence({ indexedDB: null });
  assert.strictEqual(p.available, false);
  assert.strictEqual(await p.load(), null);
  assert.strictEqual(await p.save({ any: 1 }), false);
});

/* ------------------------------------------------------------------ */
/* Minimal in-memory IndexedDB good enough for TabPersistence's usage. */
function makeFakeIndexedDB(mem) {
  function makeRequest(resultFn) {
    const req = {};
    queueMicrotask(() => {
      try { req.result = resultFn(); req.onsuccess && req.onsuccess(); }
      catch (e) { req.error = e; req.onerror && req.onerror(); }
    });
    return req;
  }
  return {
    open() {
      const db = {
        objectStoreNames: { contains: () => true },
        createObjectStore() {},
        transaction() {
          const tx = {};
          const store = {
            get: (k) => makeRequest(() => mem.get(k)),
            put: (v, k) => { mem.set(k, JSON.parse(JSON.stringify(v))); return makeRequest(() => undefined); },
            delete: (k) => { mem.delete(k); return makeRequest(() => undefined); },
          };
          tx.objectStore = () => store;
          queueMicrotask(() => { tx.oncomplete && tx.oncomplete(); });
          return tx;
        },
      };
      const req = {};
      queueMicrotask(() => { req.result = db; req.onupgradeneeded && req.onupgradeneeded(); req.onsuccess && req.onsuccess(); });
      return req;
    },
  };
}
