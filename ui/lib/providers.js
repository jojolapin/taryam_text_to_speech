/* TextSpeak Pro - voice provider clients (frontend)
 * (C) 2026 JojoLapin Inc. All rights reserved.
 *
 * A provider turns a chunk of text into playable audio bytes. The playback core
 * (PiperReader) is provider-agnostic: it calls `provider.synthesize(text, opts)`
 * and receives `{ b64, mime }`, then builds a Blob/<audio> URL. Engine-specific
 * details (Piper's inverse length-scale, OpenAI's speed, output mime) live inside
 * each provider so playback stays identical across engines.
 *
 * Provider contract (duck-typed):
 *   id            : string
 *   supportsOffline() -> bool
 *   supportsStreaming() -> bool
 *   requiresNetwork() -> bool
 *   isAI()        -> bool
 *   validate()    -> { ok: bool, message?: string }
 *   synthesize(text, { voice, rate, volume, textFormat }) -> Promise<{ b64, mime }>
 *   cancel(id?)   -> void
 */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.PiperProvider = api.PiperProvider;
    root.OpenAIProvider = api.OpenAIProvider;
    root.ProviderRegistry = api.ProviderRegistry;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function _clampRate(r) { return Math.max(0.5, Math.min(2.0, Number(r) || 1)); }

  /* Piper: offline, local. Wraps the QWebChannel bridge. Output is WAV. */
  class PiperProvider {
    constructor(deps = {}) {
      this.id = 'piper';
      this._bridge = deps.bridge || (typeof BridgeAPI !== 'undefined' ? BridgeAPI : null);
    }
    supportsOffline() { return true; }
    supportsStreaming() { return false; }
    requiresNetwork() { return false; }
    isAI() { return false; }
    validate() { return { ok: true }; }

    async synthesize(text, opts = {}) {
      const rate = _clampRate(opts.rate);
      // Piper interprets rate as an inverse length scale (slower => larger scale).
      const lengthScale = 1.0 / rate;
      const res = await this._bridge.synthesize(
        text, opts.voice, lengthScale, opts.volume, opts.textFormat || 'plain'
      );
      return { b64: res.wavB64, mime: 'audio/wav' };
    }
    cancel(id) { if (id && this._bridge && this._bridge.cancelSynthesize) this._bridge.cancelSynthesize(id); }
  }

  /* OpenAI: online, AI-generated. Delegates to the bridge; the API key never
   * touches the webview. Output mime is decided by the requested format. */
  class OpenAIProvider {
    constructor(deps = {}) {
      this.id = 'openai';
      this._bridge = deps.bridge || (typeof BridgeAPI !== 'undefined' ? BridgeAPI : null);
    }
    supportsOffline() { return false; }
    supportsStreaming() { return false; }
    requiresNetwork() { return true; }
    isAI() { return true; }
    validate() { return { ok: true }; }

    async synthesize(text, opts = {}) {
      const { b64, mime } = await this._bridge.synthesizeOpenAI(text, {
        voice: opts.voice,
        model: opts.model,
        speed: opts.rate,
        instructions: opts.instructions,
        format: opts.format,
        textFormat: opts.textFormat || 'plain',
        tabId: opts.tabId || '',
      });
      return { b64, mime };
    }
    cancel(id) { if (id && this._bridge && this._bridge.cancelSynthesize) this._bridge.cancelSynthesize(id); }
    // Cancel any in-flight OpenAI requests (called by the reader on stop) so we
    // don't keep generating sections the user will never hear.
    cancelPending() { if (this._bridge && this._bridge.cancelAllOpenAI) this._bridge.cancelAllOpenAI(); }
  }

  /* Registry: name -> provider, with a default fallback (piper). */
  class ProviderRegistry {
    constructor(defaultId = 'piper') {
      this._providers = new Map();
      this._defaultId = defaultId;
    }
    register(provider) { this._providers.set(provider.id, provider); return provider; }
    has(id) { return this._providers.has(id); }
    get(id) { return this._providers.get(id) || this._providers.get(this._defaultId) || null; }
    ids() { return Array.from(this._providers.keys()); }
    get defaultId() { return this._defaultId; }
  }

  return { PiperProvider, OpenAIProvider, ProviderRegistry };
});
