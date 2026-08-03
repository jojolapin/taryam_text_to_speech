/* Regression tests for the frontend voice providers (ui/lib/providers.js).
 * (C) 2026 JojoLapin Inc.
 * Run: npm test
 */
'use strict';

const { test } = require('node:test');
const assert = require('node:assert');

const { PiperProvider, OpenAIProvider, ProviderRegistry } = require('../../ui/lib/providers.js');

function fakeBridge() {
  const calls = [];
  return {
    synthesize(text, voice, lengthScale, volume, fmt) {
      calls.push({ text, voice, lengthScale, volume, fmt });
      return Promise.resolve({ wavB64: 'AAAA' });
    },
    cancelled: [],
    cancelSynthesize(id) { this.cancelled.push(id); },
    calls,
  };
}

test('PiperProvider advertises offline, non-AI, non-streaming', () => {
  const p = new PiperProvider({ bridge: fakeBridge() });
  assert.strictEqual(p.id, 'piper');
  assert.strictEqual(p.supportsOffline(), true);
  assert.strictEqual(p.requiresNetwork(), false);
  assert.strictEqual(p.isAI(), false);
  assert.strictEqual(p.supportsStreaming(), false);
  assert.deepStrictEqual(p.validate(), { ok: true });
});

test('PiperProvider maps rate to inverse length scale and returns {b64,mime}', async () => {
  const bridge = fakeBridge();
  const p = new PiperProvider({ bridge });
  const out = await p.synthesize('hi', { voice: 'v', rate: 2.0, volume: 0.5, textFormat: 'plain' });
  assert.deepStrictEqual(out, { b64: 'AAAA', mime: 'audio/wav' });
  assert.strictEqual(bridge.calls.length, 1);
  assert.strictEqual(bridge.calls[0].lengthScale, 0.5, 'rate 2.0 => lengthScale 0.5');
  assert.strictEqual(bridge.calls[0].voice, 'v');
});

test('PiperProvider clamps rate into the supported range', async () => {
  const bridge = fakeBridge();
  const p = new PiperProvider({ bridge });
  await p.synthesize('hi', { voice: 'v', rate: 5.0, volume: 1 });   // clamps to 2.0
  assert.strictEqual(bridge.calls[0].lengthScale, 0.5);
  await p.synthesize('hi', { voice: 'v', rate: 0.1, volume: 1 });   // clamps to 0.5
  assert.strictEqual(bridge.calls[1].lengthScale, 2.0);
});

test('PiperProvider.cancel forwards to the bridge', () => {
  const bridge = fakeBridge();
  const p = new PiperProvider({ bridge });
  p.cancel('req-9');
  assert.deepStrictEqual(bridge.cancelled, ['req-9']);
});

test('ProviderRegistry registers, looks up, and falls back to default', () => {
  const reg = new ProviderRegistry('piper');
  const piper = reg.register(new PiperProvider({ bridge: fakeBridge() }));
  const openai = reg.register(new OpenAIProvider({ bridge: fakeOpenAIBridge() }));
  assert.strictEqual(reg.get('piper'), piper);
  assert.strictEqual(reg.get('openai'), openai);
  assert.strictEqual(reg.has('openai'), true);
  assert.strictEqual(reg.get('unknown'), piper, 'unknown id falls back to default');
  assert.deepStrictEqual(reg.ids(), ['piper', 'openai']);
  assert.strictEqual(reg.defaultId, 'piper');
});

function fakeOpenAIBridge() {
  const calls = [];
  return {
    synthesizeOpenAI(text, opts) {
      calls.push({ text, opts });
      return Promise.resolve({ b64: 'MP3', mime: 'audio/mpeg' });
    },
    cancelled: [],
    cancelSynthesize(id) { this.cancelled.push(id); },
    calls,
  };
}

test('OpenAIProvider advertises online, AI, non-offline', () => {
  const p = new OpenAIProvider({ bridge: fakeOpenAIBridge() });
  assert.strictEqual(p.id, 'openai');
  assert.strictEqual(p.supportsOffline(), false);
  assert.strictEqual(p.requiresNetwork(), true);
  assert.strictEqual(p.isAI(), true);
  assert.strictEqual(p.supportsStreaming(), false);
});

test('OpenAIProvider forwards rate as speed plus model/instructions/format', async () => {
  const bridge = fakeOpenAIBridge();
  const p = new OpenAIProvider({ bridge });
  const out = await p.synthesize('hi', {
    voice: 'nova', rate: 1.25, model: 'gpt-4o-mini-tts',
    instructions: 'whisper', format: 'mp3', textFormat: 'markdown',
  });
  assert.deepStrictEqual(out, { b64: 'MP3', mime: 'audio/mpeg' });
  const sent = bridge.calls[0].opts;
  assert.strictEqual(sent.speed, 1.25);
  assert.strictEqual(sent.voice, 'nova');
  assert.strictEqual(sent.model, 'gpt-4o-mini-tts');
  assert.strictEqual(sent.instructions, 'whisper');
  assert.strictEqual(sent.format, 'mp3');
  assert.strictEqual(sent.textFormat, 'markdown');
});
