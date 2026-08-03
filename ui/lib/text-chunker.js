/* TextSpeak Pro - TextChunker
 * (C) 2026 JojoLapin Inc. All rights reserved.
 *
 * Splits text at natural boundaries while preserving source offsets. Pure and
 * side-effect free so it can be unit-tested under Node (see tests/js/) and
 * loaded as a plain <script> in the webview (exposes window.TextChunker).
 *
 * Behaviour is intentionally identical to the original inline implementation in
 * app.js; do not change semantics here without updating the regression tests.
 */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.TextChunker = api.TextChunker;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const TextChunker = {
    chunk(text, maxChars = 450) {
      const minChars = Math.floor(maxChars / 3);
      const chunks = [];
      const len = text.length;
      let i = 0;
      while (i < len) {
        while (i < len && /\s/.test(text[i])) i++;
        if (i >= len) break;
        const start = i;
        let end = Math.min(start + maxChars, len);
        if (end < len) {
          let found = -1;
          for (let j = end; j >= start + minChars; j--) {
            const c = text[j - 1];
            if (/[.!?]/.test(c) && (j >= len || /\s/.test(text[j]))) { found = j; break; }
          }
          if (found === -1) for (let j = end; j >= start + minChars; j--) {
            const c = text[j - 1];
            if (/[,;:]/.test(c) && (j >= len || /\s/.test(text[j]))) { found = j; break; }
          }
          if (found === -1) for (let j = end; j >= start + minChars; j--) {
            if (/\s/.test(text[j])) { found = j; break; }
          }
          if (found !== -1) end = found;
        }
        const chunkText = text.slice(start, end).trim();
        if (chunkText) chunks.push({ text: chunkText, start, end });
        i = end;
      }
      return chunks;
    },
    findChunkAtPosition(chunks, pos) {
      for (let i = 0; i < chunks.length; i++) if (chunks[i].end > pos) return i;
      return Math.max(0, chunks.length - 1);
    }
  };

  return { TextChunker };
});
