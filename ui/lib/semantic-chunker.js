/* TextSpeak Pro - SemanticChunker
 * (C) 2026 JojoLapin Inc. All rights reserved.
 *
 * Splits long text into playable/synthesizable chunks at natural boundaries
 * (paragraph -> sentence -> clause -> whitespace) while NEVER splitting inside a
 * "protected span": decimals/numbers (3.14, 1,000), dates (2026-08-03, 12/25),
 * times (3:30), initials (J.R.R.), listed abbreviations (Dr., e.g., U.S.), URLs,
 * and emails. Preserves source offsets so highlighting keeps working.
 *
 * Drop-in compatible with TextChunker: chunk(text, maxChars) -> [{text,start,end}]
 * and findChunkAtPosition(chunks, pos). Pure + side-effect free (Node-testable),
 * and exposes window.SemanticChunker in the webview.
 */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.SemanticChunker = api.SemanticChunker;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const ABBREV =
    'Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|etc|Inc|Ltd|Co|Corp|Fig|No|Vol|Gen|Sen|Rev|Hon|Capt|Lt|Sgt|' +
    'Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec|Mon|Tue|Wed|Thu|Fri|Sat|Sun';

  // Mark every boundary position strictly inside a protected span as "unsafe".
  // A boundary at index p sits between text[p-1] and text[p]; edges are safe.
  function buildUnsafe(text) {
    const n = text.length;
    const unsafe = new Uint8Array(n + 1);
    const mark = (s, e) => { e = Math.min(e, n); for (let p = s + 1; p < e; p++) unsafe[p] = 1; };
    const scan = (re, extend) => {
      re.lastIndex = 0;
      let m;
      while ((m = re.exec(text)) !== null) {
        mark(m.index, m.index + m[0].length + (extend || 0));
        if (m.index === re.lastIndex) re.lastIndex++;
      }
    };
    scan(/https?:\/\/\S+/gi);
    scan(/www\.\S+/gi);
    scan(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g);
    scan(/\d[\d.,:/-]*\d/g);                 // 3.14, 1,000, 3:30, 2026-08-03, 12/25
    scan(/\b(?:[A-Za-z]\.){2,}/g, 1);        // J.R.R. (extend to cover trailing boundary)
    scan(new RegExp('\\b(?:' + ABBREV + ')\\.\\s', 'gi')); // "Dr. " incl. the space
    scan(/\b(?:e\.g|i\.e|a\.m|p\.m|U\.S|U\.K|Ph\.D)\.?/gi, 1);
    return unsafe;
  }

  function _sentenceBoundaries(text, isSafe) {
    const n = text.length;
    const set = new Set();
    // Paragraph breaks (blank line) are always chunk boundaries when safe.
    const para = /\n[ \t]*\n/g;
    let pm;
    while ((pm = para.exec(text)) !== null) {
      const p = pm.index + 1;
      if (isSafe(p)) set.add(p);
    }
    for (let i = 0; i < n; i++) {
      const c = text[i];
      if (c === '.' || c === '!' || c === '?' || c === '\u2026') {
        let j = i + 1;
        while (j < n && /[.!?\u2026"'\u201d\u2019)\]]/.test(text[j])) j++;
        if ((j >= n || /\s/.test(text[j])) && isSafe(j)) set.add(j);
      }
    }
    set.add(n);
    return Array.from(set).sort((a, b) => a - b);
  }

  // Split an oversized [s,e) span into pieces <= maxChars, breaking only at safe
  // clause/whitespace boundaries. If a protected span would be broken, the piece
  // is allowed to exceed maxChars rather than split it (e.g. a very long URL).
  function _splitOversize(text, s, e, maxChars, isSafe) {
    const pieces = [];
    let start = s;
    const floor = Math.max(1, Math.floor(maxChars / 4));
    while (e - start > maxChars) {
      const limit = start + maxChars;
      let brk = -1;
      for (let j = limit; j > start + floor; j--) {
        if (/[,;:]/.test(text[j - 1]) && (j >= e || /\s/.test(text[j])) && isSafe(j)) { brk = j; break; }
      }
      if (brk < 0) for (let j = limit; j > start + floor; j--) {
        if (/\s/.test(text[j]) && isSafe(j)) { brk = j; break; }
      }
      if (brk < 0) {
        // No safe break within the window: extend to the next safe whitespace so
        // we never cut through a protected span.
        let j = limit;
        while (j < e && !(/\s/.test(text[j]) && isSafe(j))) j++;
        brk = j < e ? j : e;
      }
      pieces.push([start, brk]);
      start = brk;
      while (start < e && /\s/.test(text[start])) start++;
    }
    if (start < e) pieces.push([start, e]);
    return pieces;
  }

  const SemanticChunker = {
    // Exposed for tests.
    _buildUnsafe: buildUnsafe,

    chunk(text, maxChars = 1600) {
      if (!text || !text.trim()) return [];
      maxChars = Math.max(8, Number(maxChars) || 1600);
      const n = text.length;
      const unsafe = buildUnsafe(text);
      const isSafe = (pos) => pos <= 0 || pos >= n || !unsafe[pos];

      const bounds = _sentenceBoundaries(text, isSafe);
      const sentences = [];
      let prev = 0;
      for (const b of bounds) {
        let s = prev;
        while (s < b && /\s/.test(text[s])) s++;
        if (s < b) sentences.push([s, b]);
        prev = b;
      }

      const segs = [];
      let curS = -1, curE = -1;
      const flush = () => { if (curS >= 0) { segs.push([curS, curE]); curS = -1; curE = -1; } };
      for (const [s, e] of sentences) {
        if (e - s > maxChars) {
          flush();
          for (const p of _splitOversize(text, s, e, maxChars, isSafe)) segs.push(p);
          continue;
        }
        if (curS < 0) { curS = s; curE = e; }
        else if (e - curS <= maxChars) { curE = e; }
        else { flush(); curS = s; curE = e; }
      }
      flush();

      const chunks = [];
      for (const [s, e] of segs) {
        const t = text.slice(s, e).trim();
        if (t) chunks.push({ text: t, start: s, end: e });
      }
      return chunks;
    },

    findChunkAtPosition(chunks, pos) {
      for (let i = 0; i < chunks.length; i++) if (chunks[i].end > pos) return i;
      return Math.max(0, chunks.length - 1);
    },
  };

  return { SemanticChunker };
});
