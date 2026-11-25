/**
 * TRUSTLAYER Guardian — Extension Test Suite
 *
 * Run with:  node tests/extension.test.js
 *
 * Uses only Node.js built-ins (no external test runner required).
 * Tests are intentionally side-effect free — no real network calls,
 * no DetectifAI credits consumed.
 */

'use strict';

// ── Minimal test framework ────────────────────────────────────────────────────

let _passed = 0;
let _failed = 0;
let _total  = 0;

function test(name, fn) {
  _total++;
  try {
    fn();
    console.log(`  ✅  ${name}`);
    _passed++;
  } catch (err) {
    console.error(`  ❌  ${name}`);
    console.error(`       ${err.message}`);
    _failed++;
  }
}

function assertEqual(actual, expected, msg) {
  if (actual !== expected) {
    throw new Error(msg || `Expected ${JSON.stringify(expected)} but got ${JSON.stringify(actual)}`);
  }
}

function assertApprox(actual, expected, tolerance, msg) {
  if (Math.abs(actual - expected) > tolerance) {
    throw new Error(msg || `Expected ≈${expected} (±${tolerance}) but got ${actual}`);
  }
}

function assertTrue(value, msg) {
  if (!value) throw new Error(msg || `Expected truthy but got ${JSON.stringify(value)}`);
}

function assertFalse(value, msg) {
  if (value) throw new Error(msg || `Expected falsy but got ${JSON.stringify(value)}`);
}

function assertThrows(fn, msgSubstring) {
  let threw = false;
  try { fn(); } catch (err) {
    threw = true;
    if (msgSubstring && !err.message.includes(msgSubstring)) {
      throw new Error(`Expected error containing "${msgSubstring}" but got "${err.message}"`);
    }
  }
  if (!threw) throw new Error('Expected function to throw but it did not');
}

function section(label) {
  console.log(`\n── ${label} ─────────────────────────────────────`);
}

// ═════════════════════════════════════════════════════════════════════════════
// 1. PCM16 Conversion
// ═════════════════════════════════════════════════════════════════════════════

section('PCM16LE Conversion');

/**
 * Re-implement the core conversion logic from audio-processor.js so it can
 * be tested in Node without an AudioWorklet context.
 */
function float32ToPCM16LE(float32Array) {
  const length = float32Array.length;
  const buffer = new ArrayBuffer(length * 2);
  const view   = new DataView(buffer);
  for (let i = 0; i < length; i++) {
    let s = float32Array[i];
    if (s >  1) s =  1;
    if (s < -1) s = -1;
    const intSample = s < 0 ? s * 0x8000 : s * 0x7FFF;
    view.setInt16(i * 2, Math.round(intSample), true);
  }
  return buffer;
}

function readPCM16LE(buffer) {
  const view = new DataView(buffer);
  const out  = [];
  for (let i = 0; i < buffer.byteLength / 2; i++) {
    out.push(view.getInt16(i * 2, true));
  }
  return out;
}

test('Float32 silence (0.0) → PCM16 0', () => {
  const buf = float32ToPCM16LE(new Float32Array([0.0]));
  assertEqual(readPCM16LE(buf)[0], 0);
});

test('Float32 max positive (1.0) → PCM16 32767', () => {
  const buf = float32ToPCM16LE(new Float32Array([1.0]));
  assertEqual(readPCM16LE(buf)[0], 0x7FFF);
});

test('Float32 max negative (-1.0) → PCM16 -32768', () => {
  const buf = float32ToPCM16LE(new Float32Array([-1.0]));
  assertEqual(readPCM16LE(buf)[0], -32768);
});

test('Float32 clamped above 1.0 → PCM16 32767', () => {
  const buf = float32ToPCM16LE(new Float32Array([1.5]));
  assertEqual(readPCM16LE(buf)[0], 0x7FFF);
});

test('Float32 clamped below -1.0 → PCM16 -32768', () => {
  const buf = float32ToPCM16LE(new Float32Array([-2.0]));
  assertEqual(readPCM16LE(buf)[0], -32768);
});

test('Multi-sample 100-sample sine wave produces correct byte length', () => {
  const N   = 100;
  const inp = new Float32Array(N);
  for (let i = 0; i < N; i++) inp[i] = Math.sin(2 * Math.PI * i / N);
  const buf = float32ToPCM16LE(inp);
  assertEqual(buf.byteLength, N * 2, `Expected ${N * 2} bytes, got ${buf.byteLength}`);
});

test('PCM16LE is little-endian (byte order check on 0x7FFF)', () => {
  const buf   = float32ToPCM16LE(new Float32Array([1.0]));
  const bytes = new Uint8Array(buf);
  // Little-endian: low byte first → 0xFF, then 0x7F
  assertEqual(bytes[0], 0xFF);
  assertEqual(bytes[1], 0x7F);
});

test('Frame of 1600 samples (100 ms at 16 kHz) = 3200 bytes', () => {
  const N   = 1600;
  const inp = new Float32Array(N).fill(0.5);
  const buf = float32ToPCM16LE(inp);
  assertEqual(buf.byteLength, 3200);
});

test('Max allowed frame (60 KB) stays under 64 KB backend limit', () => {
  const MAX_BYTES  = 60 * 1024;
  const LIMIT_BYTES = 64 * 1024;
  assertTrue(MAX_BYTES < LIMIT_BYTES);
  // 60 KB PCM16 = 30720 samples
  const nSamples = MAX_BYTES / 2;
  const inp      = new Float32Array(nSamples).fill(0.3);
  const buf      = float32ToPCM16LE(inp);
  assertTrue(buf.byteLength <= LIMIT_BYTES, `Frame ${buf.byteLength} B exceeds 64 KB`);
});

// ═════════════════════════════════════════════════════════════════════════════
// 2. Mono Downmix
// ═════════════════════════════════════════════════════════════════════════════

section('Mono Downmix');

function downmixToMono(channelData) {
  if (!channelData || channelData.length === 0) return null;
  if (channelData.length === 1) return Float32Array.from(channelData[0]);

  const numChannels = channelData.length;
  const numSamples  = channelData[0].length;
  const mono        = new Float32Array(numSamples);
  for (let i = 0; i < numSamples; i++) {
    let sum = 0;
    for (let ch = 0; ch < numChannels; ch++) sum += channelData[ch][i];
    mono[i] = sum / numChannels;
  }
  return mono;
}

test('Single channel → unchanged', () => {
  const ch   = [new Float32Array([0.1, 0.2, 0.3])];
  const mono = downmixToMono(ch);
  assertApprox(mono[0], 0.1, 0.0001);
  assertApprox(mono[1], 0.2, 0.0001);
  assertApprox(mono[2], 0.3, 0.0001);
});

test('Two equal channels → same as one channel', () => {
  const data = new Float32Array([0.4, 0.8, -0.2]);
  const ch   = [data, Float32Array.from(data)];
  const mono = downmixToMono(ch);
  assertApprox(mono[0],  0.4, 0.0001);
  assertApprox(mono[1],  0.8, 0.0001);
  assertApprox(mono[2], -0.2, 0.0001);
});

test('Two opposite channels → mono silence', () => {
  const ch = [new Float32Array([1.0, -0.5]), new Float32Array([-1.0, 0.5])];
  const mono = downmixToMono(ch);
  assertApprox(mono[0], 0, 0.0001);
  assertApprox(mono[1], 0, 0.0001);
});

test('Empty channel array → null', () => {
  assertEqual(downmixToMono([]), null);
});

// ═════════════════════════════════════════════════════════════════════════════
// 3. Backend URL building
// ═════════════════════════════════════════════════════════════════════════════

section('WebSocket URL Building');

function buildWsUrl(backendUrl, callId) {
  let base = backendUrl.replace(/\/+$/, '');
  if (base.startsWith('https://')) base = 'wss://' + base.slice('https://'.length);
  else if (base.startsWith('http://')) base = 'ws://' + base.slice('http://'.length);
  return `${base}/api/v1/calls/ws/${encodeURIComponent(callId)}`;
}

test('http → ws', () => {
  const url = buildWsUrl('http://localhost:8000', 'call-123');
  assertTrue(url.startsWith('ws://'), `Got: ${url}`);
});

test('https → wss', () => {
  const url = buildWsUrl('https://api.example.com', 'call-abc');
  assertTrue(url.startsWith('wss://'), `Got: ${url}`);
});

test('Trailing slash stripped', () => {
  const url = buildWsUrl('http://localhost:8000/', 'call-xyz');
  assertFalse(url.includes('//api/'), `Unexpected double slash: ${url}`);
});

test('call_id is URL-encoded', () => {
  const url = buildWsUrl('http://localhost:8000', 'call id/with spaces');
  assertTrue(url.includes('call%20id%2Fwith%20spaces'), `Got: ${url}`);
});

test('Full WS URL path is correct', () => {
  const url = buildWsUrl('http://localhost:8000', 'tlg-abc123');
  assertEqual(url, 'ws://localhost:8000/api/v1/calls/ws/tlg-abc123');
});

// ═════════════════════════════════════════════════════════════════════════════
// 4. Backend Options URL Validation
// ═════════════════════════════════════════════════════════════════════════════

section('Settings URL Validation');

function validateBackendUrl(url) {
  const trimmed = url.trim();
  if (!trimmed) return { ok: false, error: 'Backend URL cannot be empty.' };
  try {
    const parsed = new URL(trimmed);
    if (!['http:', 'https:'].includes(parsed.protocol)) {
      return { ok: false, error: 'URL must start with http:// or https://' };
    }
  } catch (_) {
    return { ok: false, error: 'Invalid URL format.' };
  }
  return { ok: true, value: trimmed };
}

test('Valid http URL passes', () => {
  assertTrue(validateBackendUrl('http://localhost:8000').ok);
});

test('Valid https URL passes', () => {
  assertTrue(validateBackendUrl('https://api.example.com').ok);
});

test('Empty string fails', () => {
  assertFalse(validateBackendUrl('').ok);
});

test('ws:// protocol fails', () => {
  assertFalse(validateBackendUrl('ws://localhost:8000').ok);
});

test('Bare hostname without protocol fails', () => {
  assertFalse(validateBackendUrl('localhost:8000').ok);
});

test('Trimming whitespace works', () => {
  assertTrue(validateBackendUrl('  http://localhost:8000  ').ok);
});

// ═════════════════════════════════════════════════════════════════════════════
// 5. WebSocket Message Parsing (mocked messages)
// ═════════════════════════════════════════════════════════════════════════════

section('WebSocket Message Parsing');

/**
 * Re-implement handleBackendMessage logic from offscreen.js as pure functions.
 */
function parseBackendMessage(msg) {
  switch (msg.type) {
    case 'ready':
      return { action: 'ready', streamId: msg.stream_id };

    case 'deepfake':
      return {
        action: 'deepfake_update',
        verdict: msg.verdict || msg.result || null,
        isFinal: msg.is_final !== undefined ? msg.is_final : (msg.final !== undefined ? msg.final : false),
        isEarly: msg.is_early !== undefined ? msg.is_early : (msg.early !== undefined ? msg.early : null),
        status:  msg.status || 'pending',
        sequence: msg.sequence || null,
        rawScore: msg.score !== undefined ? msg.score : (msg.raw_score !== undefined ? msg.raw_score : null),
      };

    case 'completed':
      return { action: 'completed' };

    case 'error':
      return { action: 'error', message: msg.message || msg.code || 'Unknown error' };

    default:
      return { action: 'unknown', type: msg.type };
  }
}

test('ready message parsed correctly', () => {
  const result = parseBackendMessage({ type: 'ready', stream_id: 'sid-001' });
  assertEqual(result.action, 'ready');
  assertEqual(result.streamId, 'sid-001');
});

test('deepfake genuine result parsed', () => {
  const result = parseBackendMessage({
    type: 'deepfake',
    verdict: 'genuine',
    is_final: false,
    is_early: true,
    status: 'completed',
    score: 0.12,
    sequence: 3,
  });
  assertEqual(result.action, 'deepfake_update');
  assertEqual(result.verdict, 'genuine');
  assertFalse(result.isFinal);
  assertTrue(result.isEarly);
  assertEqual(result.rawScore, 0.12);
  assertEqual(result.sequence, 3);
});

test('deepfake FINAL deepfake result parsed', () => {
  const result = parseBackendMessage({
    type: 'deepfake',
    verdict: 'deepfake',
    is_final: true,
    score: 0.97,
  });
  assertEqual(result.verdict, 'deepfake');
  assertTrue(result.isFinal);
  assertApprox(result.rawScore, 0.97, 0.0001);
});

test('completed message parsed', () => {
  const result = parseBackendMessage({ type: 'completed' });
  assertEqual(result.action, 'completed');
});

test('error message parsed', () => {
  const result = parseBackendMessage({ type: 'error', code: 'rate_limited', message: 'Too many frames' });
  assertEqual(result.action, 'error');
  assertEqual(result.message, 'Too many frames');
});

test('unknown message type returns action=unknown', () => {
  const result = parseBackendMessage({ type: 'stream_id', value: 'x' });
  assertEqual(result.action, 'unknown');
  assertEqual(result.type, 'stream_id');
});

test('deepfake missing verdict → null', () => {
  const result = parseBackendMessage({ type: 'deepfake', status: 'processing' });
  assertEqual(result.verdict, null);
});

// ═════════════════════════════════════════════════════════════════════════════
// 6. Call Session Payload Validation
// ═════════════════════════════════════════════════════════════════════════════

section('Call Session Payload');

function buildCallSessionPayload(callId) {
  return {
    call_id: callId,
    checks_mode: 'deepfake',
    consent_confirmed: false,
  };
}

test('Payload has required fields', () => {
  const p = buildCallSessionPayload('tlg-test-001');
  assertTrue('call_id' in p);
  assertTrue('checks_mode' in p);
  assertTrue('consent_confirmed' in p);
});

test('checks_mode is deepfake (unknown caller mode)', () => {
  const p = buildCallSessionPayload('tlg-test-001');
  assertEqual(p.checks_mode, 'deepfake');
});

test('consent_confirmed defaults to false for deepfake-only mode', () => {
  const p = buildCallSessionPayload('tlg-test-001');
  assertEqual(p.consent_confirmed, false);
});

test('call_id is preserved exactly', () => {
  const p = buildCallSessionPayload('my-call-abc-123');
  assertEqual(p.call_id, 'my-call-abc-123');
});

// ═════════════════════════════════════════════════════════════════════════════
// 7. Start/Stop lifecycle (state machine)
// ═════════════════════════════════════════════════════════════════════════════

section('State Machine');

function makeStateMachine() {
  let state = { status: 'idle', callId: null, error: null, latestResult: null };

  return {
    get: () => ({ ...state }),
    start: (callId) => {
      if (state.status !== 'idle' && state.status !== 'completed' && state.status !== 'error') {
        return { ok: false, error: 'Already monitoring' };
      }
      state = { status: 'connecting', callId, error: null, latestResult: null };
      return { ok: true };
    },
    wsOpen: () => {
      state.status = 'monitoring';
    },
    result: (r) => {
      state.latestResult = r;
      state.status = 'analyzing';
    },
    stop: () => {
      state = { status: 'idle', callId: null, error: null, latestResult: null };
      return { ok: true };
    },
    complete: () => {
      state.status = 'completed';
    },
    error: (msg) => {
      state.status = 'error';
      state.error = msg;
    },
  };
}

test('Initial state is idle', () => {
  const sm = makeStateMachine();
  assertEqual(sm.get().status, 'idle');
});

test('Start transitions to connecting', () => {
  const sm = makeStateMachine();
  sm.start('call-001');
  assertEqual(sm.get().status, 'connecting');
  assertEqual(sm.get().callId, 'call-001');
});

test('Cannot start while already monitoring', () => {
  const sm = makeStateMachine();
  sm.start('call-001');
  sm.wsOpen();
  const r = sm.start('call-002');
  assertFalse(r.ok);
  assertTrue(r.error.includes('Already monitoring'));
});

test('Stop from monitoring → idle', () => {
  const sm = makeStateMachine();
  sm.start('call-001');
  sm.wsOpen();
  sm.stop();
  assertEqual(sm.get().status, 'idle');
  assertEqual(sm.get().callId, null);
});

test('Error state can restart', () => {
  const sm = makeStateMachine();
  sm.start('call-001');
  sm.error('something went wrong');
  assertEqual(sm.get().status, 'error');
  const r = sm.start('call-002');
  assertTrue(r.ok, 'Should allow restart after error');
  assertEqual(sm.get().status, 'connecting');
});

test('Completed → idle is allowed for restart', () => {
  const sm = makeStateMachine();
  sm.start('call-001');
  sm.wsOpen();
  sm.complete();
  const r = sm.start('call-002');
  assertTrue(r.ok);
});

// ═════════════════════════════════════════════════════════════════════════════
// 8. Chunk size safety
// ═════════════════════════════════════════════════════════════════════════════

section('Chunk Size Safety');

const BACKEND_LIMIT = 64 * 1024;
const EXTENSION_MAX = 60 * 1024;

test('Extension max frame < backend 64 KB limit', () => {
  assertTrue(EXTENSION_MAX < BACKEND_LIMIT);
});

test('100 ms at 16 kHz = 1600 samples = 3200 bytes → well under limit', () => {
  const bytes = 1600 * 2;
  assertTrue(bytes < BACKEND_LIMIT);
  assertEqual(bytes, 3200);
});

test('Oversized frame split logic produces chunks ≤ EXTENSION_MAX', () => {
  // Simulate splitting a 150 KB PCM16 buffer
  const fakeSize = 150 * 1024;
  const chunks = [];
  let offset = 0;
  while (offset < fakeSize) {
    const end = Math.min(offset + EXTENSION_MAX, fakeSize);
    chunks.push(end - offset);
    offset += EXTENSION_MAX;
  }
  for (const c of chunks) {
    assertTrue(c <= EXTENSION_MAX, `Chunk size ${c} exceeds EXTENSION_MAX`);
    assertTrue(c <= BACKEND_LIMIT, `Chunk size ${c} exceeds BACKEND_LIMIT`);
  }
  // Verify all bytes accounted for
  const total = chunks.reduce((s, v) => s + v, 0);
  assertEqual(total, fakeSize);
});

// ═════════════════════════════════════════════════════════════════════════════
// 9. CORS Extension Origin
// ═════════════════════════════════════════════════════════════════════════════

section('CORS Origin Notes');

test('Extension origin format is chrome-extension://<ID>', () => {
  // The extension ID is dynamic; we just verify the scheme pattern
  const pattern = /^chrome-extension:\/\/[a-z]{32}$/;
  // Synthetic test ID
  const exampleOrigin = 'chrome-extension://abcdefghijklmnopqrstuvwxyzabcdef';
  assertTrue(pattern.test(exampleOrigin), `Unexpected pattern: ${exampleOrigin}`);
});

// ═════════════════════════════════════════════════════════════════════════════
// Summary
// ═════════════════════════════════════════════════════════════════════════════

console.log(`\n${'═'.repeat(55)}`);
console.log(`  Results: ${_passed}/${_total} passed, ${_failed} failed`);
console.log(`${'═'.repeat(55)}`);

if (_failed > 0) {
  process.exit(1);
}
