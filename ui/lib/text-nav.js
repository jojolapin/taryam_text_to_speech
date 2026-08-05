/* TextSpeak Pro - sentence/paragraph navigation + timing estimates
 * (C) 2026 JojoLapin Inc. All rights reserved.
 *
 * Pure helpers used by PiperReader seek/nav and by the highlight panel.
 * Sentence boundaries intentionally match the semantic chunker's spirit
 * (abbreviations / decimals are not treated as hard sentence ends when
 * followed by a letter), but stay simple enough for live UI use.
 */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.TextNav = api.TextNav;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const _ABBREV = /^(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|etc|Inc|Ltd|Co|e\.g|i\.e|U\.S|U\.K|Ph\.D)$/i;

  function _isSentenceEnd(text, i) {
    const c = text[i];
    if (c !== '.' && c !== '!' && c !== '?' && c !== '\u2026') return false;
    // Don't split decimals / versions: digit . digit
    if (c === '.' && i > 0 && /\d/.test(text[i - 1]) && i + 1 < text.length && /\d/.test(text[i + 1])) {
      return false;
    }
    // Don't split initials: single capital letter before the dot
    if (c === '.' && i > 0 && /[A-Z]/.test(text[i - 1]) && (i < 2 || /\s/.test(text[i - 2]))) {
      // Still a sentence end if end-of-text or followed by whitespace + capital
      // (handled below); but "J.R.R." mid-token is not.
      let j = i + 1;
      while (j < text.length && /[.]/.test(text[j])) j++;
      if (j < text.length && /[A-Za-z]/.test(text[j])) return false;
    }
    // Listed abbreviations: look back for the token before the dot
    if (c === '.') {
      let s = i - 1;
      while (s >= 0 && /[A-Za-z.]/.test(text[s])) s--;
      const token = text.slice(s + 1, i);
      if (_ABBREV.test(token.replace(/\.$/, ''))) {
        // Abbreviation only if followed by space + lowercase (or more of the abbr)
        let j = i + 1;
        while (j < text.length && /["'\u201d\u2019)\]]/.test(text[j])) j++;
        if (j < text.length && /\s/.test(text[j])) {
          let k = j;
          while (k < text.length && /\s/.test(text[k])) k++;
          if (k < text.length && /[a-z]/.test(text[k])) return false;
        }
      }
    }
    let j = i + 1;
    while (j < text.length && /[.!?\u2026"'\u201d\u2019)\]]/.test(text[j])) j++;
    return j >= text.length || /\s/.test(text[j]);
  }

  /** Sorted list of sentence-end offsets (index just after the terminator / trail). */
  function sentenceEnds(text) {
    const n = (text || '').length;
    const out = [];
    for (let i = 0; i < n; i++) {
      if (_isSentenceEnd(text, i)) {
        let j = i + 1;
        while (j < n && /[.!?\u2026"'\u201d\u2019)\]]/.test(text[j])) j++;
        out.push(j);
        i = j - 1;
      }
    }
    if (!out.length || out[out.length - 1] !== n) out.push(n);
    return out;
  }

  function sentenceAt(text, pos) {
    text = text || '';
    const n = text.length;
    pos = Math.max(0, Math.min(pos | 0, n));
    const ends = sentenceEnds(text);
    let start = 0;
    for (let i = 0; i < ends.length; i++) {
      const end = ends[i];
      if (pos < end || (pos === end && i === ends.length - 1)) {
        // Trim leading whitespace for nicer highlight bounds
        let s = start;
        while (s < end && /\s/.test(text[s])) s++;
        let e = end;
        while (e > s && /\s/.test(text[e - 1])) e--;
        if (s >= e) { s = start; e = end; }
        return { start: s, end: e, index: i };
      }
      start = end;
    }
    return { start: 0, end: n, index: 0 };
  }

  function paragraphAt(text, pos) {
    text = text || '';
    const n = text.length;
    pos = Math.max(0, Math.min(pos | 0, n));
    let start = 0;
    let index = 0;
    const re = /\n[ \t]*\n/g;
    let m;
    while ((m = re.exec(text)) !== null) {
      const end = m.index;
      if (pos <= end) {
        let s = start;
        while (s < end && /\s/.test(text[s])) s++;
        let e = end;
        while (e > s && /\s/.test(text[e - 1])) e--;
        return { start: s < e ? s : start, end: e > s ? e : end, index };
      }
      start = m.index + m[0].length;
      index += 1;
    }
    let s = start;
    while (s < n && /\s/.test(text[s])) s++;
    return { start: s < n ? s : start, end: n, index };
  }

  function wordAt(text, pos) {
    text = text || '';
    const n = text.length;
    pos = Math.max(0, Math.min(pos | 0, n));
    let left = pos, right = pos;
    while (left > 0 && /[\w\u00C0-\u017F'-]/.test(text[left - 1])) left--;
    while (right < n && /[\w\u00C0-\u017F'-]/.test(text[right])) right++;
    return { start: left, end: right };
  }

  function nextSentenceStart(text, pos) {
    const cur = sentenceAt(text, pos);
    const n = (text || '').length;
    if (cur.end >= n) return n;
    // Advance past whitespace to the next sentence start
    let p = cur.end;
    while (p < n && /\s/.test(text[p])) p++;
    return p < n ? p : n;
  }

  function prevSentenceStart(text, pos) {
    const cur = sentenceAt(text, pos);
    // First press: snap to start of the current sentence when we've moved into it.
    if (pos > cur.start) return cur.start;
    if (cur.start <= 0) return 0;
    // Already at the start — jump to the previous sentence.
    let p = cur.start - 1;
    while (p > 0 && /\s/.test(text[p])) p--;
    return sentenceAt(text, p).start;
  }

  function nextParagraphStart(text, pos) {
    const cur = paragraphAt(text, pos);
    const n = (text || '').length;
    if (cur.end >= n) return n;
    let p = cur.end;
    while (p < n && /\s/.test(text[p])) p++;
    return p < n ? p : n;
  }

  function prevParagraphStart(text, pos) {
    const cur = paragraphAt(text, pos);
    if (pos > cur.start) return cur.start;
    if (cur.start <= 0) return 0;
    let p = cur.start - 1;
    while (p > 0 && /\s/.test(text[p])) p--;
    return paragraphAt(text, p).start;
  }

  /** Rough timing from the same chars/sec heuristic used by skip(). */
  function estimateTiming(charIndex, totalChars, rate) {
    const cps = 12 * Math.max(0.5, Math.min(2, Number(rate) || 1));
    const total = Math.max(0, Number(totalChars) || 0);
    const idx = Math.max(0, Math.min(total, Number(charIndex) || 0));
    const elapsedSec = cps > 0 ? idx / cps : 0;
    const remainingSec = cps > 0 ? Math.max(0, (total - idx) / cps) : 0;
    return { elapsedSec, remainingSec, totalSec: elapsedSec + remainingSec, cps };
  }

  function formatClock(seconds) {
    seconds = Math.max(0, Math.round(Number(seconds) || 0));
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return m + ':' + String(s).padStart(2, '0');
  }

  /* ---------------------------------------------------------------------------
   * Weighted position mapping (highlight <-> audio time sync).
   *
   * A chunk's audio time does NOT progress linearly with character count: spaces
   * and quotes are near-instant, while sentence/clause punctuation introduce
   * pauses. Mapping audio time straight onto character COUNT makes the marker run
   * ahead in dense text and lag around pauses. Instead we give each character an
   * approximate "spoken cost" and map the audio-time fraction onto cumulative
   * cost, so the marker lingers at pauses and tracks the voice much closer.
   *
   * Costs are heuristic (no TTS timestamps are available for Piper or OpenAI),
   * but empirically track far better than a flat per-character rate.
   * ------------------------------------------------------------------------- */
  function charWeight(ch) {
    if (ch === undefined) return 0;
    if (/\s/.test(ch)) return 0.35;                       // inter-word gap (short)
    if (ch === '.' || ch === '!' || ch === '?' || ch === '\u2026') return 7;   // sentence pause
    if (ch === ',' || ch === ';' || ch === ':') return 3.2;                     // clause pause
    if (ch === '\u2014' || ch === '\u2013' || ch === '-') return 1.4;           // dash pause
    if (/["'\u201c\u201d\u2018\u2019(){}\[\]]/.test(ch)) return 0.5;            // brackets/quotes
    return 1;                                              // letters, digits, etc.
  }

  /** Cumulative spoken-cost profile for text[start,end). Cache on the chunk. */
  function buildWeights(text, start, end) {
    text = text || '';
    start = Math.max(0, start | 0);
    end = Math.min(text.length, end | 0);
    const n = Math.max(0, end - start);
    const cum = new Float64Array(n);
    let acc = 0;
    for (let i = 0; i < n; i++) { acc += charWeight(text[start + i]); cum[i] = acc; }
    return { cum, total: acc, start, end };
  }

  /** Character offset for an audio-time fraction (0..1) within a weighted span. */
  function offsetForFraction(weights, fraction) {
    if (!weights || !weights.cum.length || weights.total <= 0) {
      return weights ? weights.start : 0;
    }
    const target = Math.max(0, Math.min(1, Number(fraction) || 0)) * weights.total;
    const cum = weights.cum;
    let lo = 0, hi = cum.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (cum[mid] < target) lo = mid + 1; else hi = mid;
    }
    return weights.start + lo;
  }

  /** Inverse of offsetForFraction: audio-time fraction at the start of `offset`. */
  function fractionForOffset(weights, offset) {
    if (!weights || !weights.cum.length || weights.total <= 0) return 0;
    const i = Math.max(0, Math.min(weights.cum.length - 1, (offset - weights.start) | 0));
    const before = i > 0 ? weights.cum[i - 1] : 0;
    return Math.max(0, Math.min(1, before / weights.total));
  }

  const TextNav = {
    sentenceEnds, sentenceAt, paragraphAt, wordAt,
    nextSentenceStart, prevSentenceStart,
    nextParagraphStart, prevParagraphStart,
    estimateTiming, formatClock,
    charWeight, buildWeights, offsetForFraction, fractionForOffset,
  };
  return { TextNav };
});
