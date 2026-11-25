/**
 * TRUSTLAYER Guardian — Offscreen Document
 *
 * Runs inside a persistent hidden page (offscreen document).
 * Responsibilities:
 *  - Receive a tab-capture stream ID from the background service worker.
 *  - Open the MediaStream, build an AudioContext + AudioWorklet pipeline.
 *  - Resample to 16 kHz mono, convert Float32 → PCM16LE.
 *  - Open a WebSocket to the backend (/api/v1/calls/ws/<call_id>).
 *  - Send the auth frame then stream raw binary PCM16LE chunks.
 *  - Forward backend WebSocket messages back to the background.
 *  - Cleanly tear everything down on STOP or disconnection.
 */

'use strict';

// ── State ─────────────────────────────────────────────────────────────────────
let currentSession = null; // { ws, audioCtx, source, tracks, callId }

// ── Utility ───────────────────────────────────────────────────────────────────

function notifyBackground(type, payload = {}) {
  chrome.runtime.sendMessage({ type, ...payload }).catch(() => {});
}

function reportStatus(status, extra = {}) {
  notifyBackground('OFFSCREEN_STATUS', { status, ...extra });
}

function generateCallId() {
  const ts = Date.now().toString(36);
  const rnd = Math.random().toString(36).slice(2, 8);
  return `tlg-${ts}-${rnd}`;
}

function buildWsUrl(backendUrl, callId) {
  let base = backendUrl.replace(/\/+$/, '');
  if (base.startsWith('https://')) {
    base = 'wss://' + base.slice('https://'.length);
  } else if (base.startsWith('http://')) {
    base = 'ws://' + base.slice('http://'.length);
  }
  return `${base}/api/v1/calls/ws/${encodeURIComponent(callId)}`;
}

async function createCallSession(backendUrl, callId, token) {
  const url = `${backendUrl.replace(/\/+$/, '')}/api/v1/calls/sessions`;
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const body = JSON.stringify({
    call_id: callId,
    checks_mode: 'deepfake',
    consent_confirmed: false,
  });

  const resp = await fetch(url, { method: 'POST', headers, body });
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const json = await resp.json();
      detail = json?.detail || json?.error?.message || detail;
    } catch (_) {}
    throw new Error(`Failed to create call session: ${detail}`);
  }
  return await resp.json();
}

// ── Main start ────────────────────────────────────────────────────────────────

async function startMonitoring(streamId, backendUrl, token) {
  if (currentSession) {
    await stopMonitoring();
  }

  const callId = generateCallId();

  try {
    // ── 1. Create call session on backend ─────────────────────────────────────
    reportStatus('connecting', { callId });
    await createCallSession(backendUrl, callId, token);

    // ── 2. Open MediaStream from tab capture stream ID ────────────────────────
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        mandatory: {
          chromeMediaSource: 'tab',
          chromeMediaSourceId: streamId,
        },
      },
      video: false,
    });

    const tracks = stream.getAudioTracks();
    if (tracks.length === 0) {
      throw new Error('Tab capture produced no audio tracks');
    }

    // ── 3. Build AudioContext pipeline ────────────────────────────────────────
    const targetSampleRate = 16000;
    const audioCtx = new AudioContext({ sampleRate: targetSampleRate });

    if (audioCtx.state === 'suspended') {
      await audioCtx.resume();
    }

    // Load the AudioWorklet processor
    const workletUrl = chrome.runtime.getURL('audio-processor.js');
    await audioCtx.audioWorklet.addModule(workletUrl);

    const source = audioCtx.createMediaStreamSource(stream);

    // Downmix to mono via channel splitter → merger (or use the worklet directly)
    const workletNode = new AudioWorkletNode(audioCtx, 'pcm16-processor', {
      numberOfInputs: 1,
      numberOfOutputs: 0,
      channelCount: 1,
      channelCountMode: 'explicit',
      channelInterpretation: 'speakers',
    });

    // Connect: source → worklet (no output — worklet sends data via postMessage)
    source.connect(workletNode);

    // ── 4. Open WebSocket to backend ──────────────────────────────────────────
    const wsUrl = buildWsUrl(backendUrl, callId);
    const ws = new WebSocket(wsUrl);
    ws.binaryType = 'arraybuffer';

    await new Promise((resolve, reject) => {
      ws.onopen = () => resolve();
      ws.onerror = (e) => reject(new Error('WebSocket connection failed'));
      setTimeout(() => reject(new Error('WebSocket connection timed out')), 10000);
    });

    // ── 5. Send auth frame if token is provided ───────────────────────────────
    if (token) {
      ws.send(JSON.stringify({ type: 'auth', token }));
    }

    // ── 6. Store session reference ────────────────────────────────────────────
    currentSession = { ws, audioCtx, source, workletNode, tracks, callId, stream };

    // ── 7. Wire up: AudioWorklet → WebSocket binary frames ────────────────────
    const MAX_FRAME_BYTES = 60 * 1024; // Stay safely under 64 KB limit
    workletNode.port.onmessage = (event) => {
      if (!currentSession || currentSession.ws.readyState !== WebSocket.OPEN) return;
      const pcm16Buffer = event.data; // ArrayBuffer of PCM16LE
      if (pcm16Buffer.byteLength === 0) return;
      if (pcm16Buffer.byteLength > MAX_FRAME_BYTES) {
        // Split oversized frames
        let offset = 0;
        while (offset < pcm16Buffer.byteLength) {
          const chunk = pcm16Buffer.slice(offset, offset + MAX_FRAME_BYTES);
          currentSession.ws.send(chunk);
          offset += MAX_FRAME_BYTES;
        }
      } else {
        currentSession.ws.send(pcm16Buffer);
      }
    };

    // ── 8. Handle incoming WebSocket messages from backend ────────────────────
    ws.onmessage = (event) => {
      try {
        const msg = typeof event.data === 'string' ? JSON.parse(event.data) : null;
        if (!msg) return;
        handleBackendMessage(msg, callId);
      } catch (_) {}
    };

    ws.onclose = (event) => {
      console.log(`[TLG offscreen] WS closed code=${event.code} reason=${event.reason}`);
      if (currentSession && currentSession.callId === callId) {
        const wasMonitoring = currentSession !== null;
        cleanup();
        if (wasMonitoring) {
          reportStatus('error', { error: `Connection closed unexpectedly (code ${event.code})`, callId });
        }
      }
    };

    ws.onerror = () => {
      if (currentSession && currentSession.callId === callId) {
        cleanup();
        reportStatus('error', { error: 'WebSocket error — check backend URL and connectivity', callId });
      }
    };

    // Keep the tab audio audible to the user
    const destination = audioCtx.createMediaStreamDestination();
    source.connect(audioCtx.destination); // play through to system output

    reportStatus('monitoring', { callId });
    return { ok: true, callId };

  } catch (err) {
    cleanup();
    throw err;
  }
}

// ── Handle backend messages ───────────────────────────────────────────────────

function handleBackendMessage(msg, callId) {
  const msgType = msg.type;

  switch (msgType) {
    case 'ready':
      reportStatus('monitoring', { callId, result: { type: 'ready', streamId: msg.stream_id } });
      break;

    case 'deepfake': {
      const result = {
        type: 'deepfake',
        source: 'detectifai',
        checkType: 'deepfake',
        status: msg.status || 'pending',
        verdict: msg.verdict || msg.result || null,
        isEarly: msg.is_early !== undefined ? msg.is_early : (msg.early !== undefined ? msg.early : null),
        isFinal: msg.is_final !== undefined ? msg.is_final : (msg.final !== undefined ? msg.final : false),
        sequence: msg.sequence || null,
        rawScore: msg.score !== undefined ? msg.score : (msg.raw_score !== undefined ? msg.raw_score : null),
        provider: msg.provider || 'detectifai',
        model: msg.model || 'aletheia',
        details: msg.details || {},
        raw: msg,
      };
      reportStatus('analyzing', { callId, result });
      break;
    }

    case 'completed': {
      const result = {
        type: 'completed',
        source: 'detectifai',
        callId,
        raw: msg,
      };
      cleanup();
      reportStatus('completed', { callId, result });
      break;
    }

    case 'error': {
      const errMsg = msg.message || msg.code || 'Backend reported an error';
      cleanup();
      reportStatus('error', { callId, error: errMsg, result: { type: 'error', raw: msg } });
      break;
    }

    default:
      // Forward all other messages as-is
      reportStatus('monitoring', { callId, result: { type: msgType, raw: msg } });
  }
}

// ── Stop & cleanup ────────────────────────────────────────────────────────────

async function stopMonitoring() {
  if (!currentSession) return;

  const { ws, audioCtx, source, workletNode, tracks } = currentSession;
  currentSession = null;

  // Send stop control frame to backend
  if (ws && ws.readyState === WebSocket.OPEN) {
    try { ws.send(JSON.stringify({ type: 'stop' })); } catch (_) {}
    // Give backend a moment to send the final `completed` message
    await new Promise((r) => setTimeout(r, 500));
    ws.close(1000, 'User stopped monitoring');
  }

  // Disconnect audio graph
  try { if (workletNode) workletNode.disconnect(); } catch (_) {}
  try { if (source) source.disconnect(); } catch (_) {}
  try { if (audioCtx && audioCtx.state !== 'closed') await audioCtx.close(); } catch (_) {}

  // Release media tracks
  if (tracks) {
    for (const t of tracks) { try { t.stop(); } catch (_) {} }
  }
}

function cleanup() {
  if (!currentSession) return;
  const sess = currentSession;
  currentSession = null;

  if (sess.ws && sess.ws.readyState === WebSocket.OPEN) {
    try { sess.ws.close(); } catch (_) {}
  }
  try { if (sess.workletNode) sess.workletNode.disconnect(); } catch (_) {}
  try { if (sess.source) sess.source.disconnect(); } catch (_) {}
  try { if (sess.audioCtx && sess.audioCtx.state !== 'closed') sess.audioCtx.close(); } catch (_) {}
  if (sess.tracks) {
    for (const t of sess.tracks) { try { t.stop(); } catch (_) {} }
  }
}

// ── Message handler (from background service worker) ─────────────────────────

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === 'OFFSCREEN_START') {
    startMonitoring(message.streamId, message.backendUrl, message.token)
      .then((result) => sendResponse(result))
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.type === 'OFFSCREEN_STOP') {
    stopMonitoring()
      .then(() => sendResponse({ ok: true }))
      .catch(() => sendResponse({ ok: true }));
    return true;
  }
});

console.log('[TLG offscreen] Offscreen document ready');
