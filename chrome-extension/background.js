/**
 * TRUSTLAYER Guardian — Background Service Worker (Manifest V3)
 *
 * Responsibilities:
 *  - Manage the offscreen document lifecycle (create once, reuse).
 *  - Relay messages between the popup and the offscreen document.
 *  - Hold the monitoring state so the popup can read it on open.
 *  - Obtain the tab capture stream ID via chrome.tabCapture (requires
 *    service-worker context; tabCapture is not available in offscreen docs).
 */

'use strict';

// ── Monitoring state (persisted across popup open/close) ──────────────────────
let monitoringState = {
  status: 'idle',      // idle | connecting | monitoring | stopping | completed | error
  callId: null,
  error: null,
  latestResult: null,
  tabId: null,
};

// Track whether an offscreen document is currently open
let offscreenReady = false;
let offscreenCreating = false;

// ── Helpers ───────────────────────────────────────────────────────────────────

function setState(patch) {
  monitoringState = { ...monitoringState, ...patch };
  // Broadcast to any open popups
  chrome.runtime.sendMessage({ type: 'STATE_UPDATE', state: monitoringState }).catch(() => {
    // Popup may not be open — ignore
  });
}

async function ensureOffscreenDocument() {
  if (offscreenReady) return;
  if (offscreenCreating) {
    // Wait for creation to complete
    await new Promise((resolve) => {
      const interval = setInterval(() => {
        if (offscreenReady) { clearInterval(interval); resolve(); }
      }, 50);
    });
    return;
  }

  offscreenCreating = true;
  try {
    // Check if already exists (service worker can be restarted)
    const existing = await chrome.offscreen.getContexts({
      contextTypes: ['OFFSCREEN_DOCUMENT'],
    }).catch(() => []);
    if (existing && existing.length > 0) {
      offscreenReady = true;
      offscreenCreating = false;
      return;
    }

    await chrome.offscreen.createDocument({
      url: 'offscreen.html',
      reasons: ['USER_MEDIA'],
      justification: 'Capture tab audio stream for deepfake voice detection',
    });
    offscreenReady = true;
  } catch (err) {
    console.error('[TLG background] Failed to create offscreen document:', err);
  } finally {
    offscreenCreating = false;
  }
}

async function closeOffscreenDocument() {
  offscreenReady = false;
  try {
    await chrome.offscreen.closeDocument();
  } catch (_) {
    // May already be gone
  }
}

// ── Tab capture ───────────────────────────────────────────────────────────────

/**
 * Obtain a tab capture stream ID for the given tab.
 * chrome.tabCapture.getMediaStreamId() must be called from the service worker.
 */
function getTabCaptureStreamId(tabId) {
  return new Promise((resolve, reject) => {
    chrome.tabCapture.getMediaStreamId(
      { consumerTabId: tabId, targetTabId: tabId },
      (streamId) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
        } else if (!streamId) {
          reject(new Error('Could not obtain tab capture stream ID'));
        } else {
          resolve(streamId);
        }
      }
    );
  });
}

// ── Message handler ───────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  handleMessage(message).then(sendResponse).catch((err) => {
    sendResponse({ ok: false, error: err.message });
  });
  return true; // async response
});

async function handleMessage(message) {
  switch (message.type) {

    case 'GET_STATE':
      return { ok: true, state: monitoringState };

    case 'START_MONITORING': {
      const { tabId, backendUrl, token } = message;
      if (monitoringState.status !== 'idle' && monitoringState.status !== 'completed' && monitoringState.status !== 'error') {
        return { ok: false, error: 'Already monitoring. Stop the current session first.' };
      }

      setState({ status: 'connecting', callId: null, error: null, latestResult: null, tabId });

      try {
        // 1. Get a tab capture stream ID (must happen here in the service worker)
        const streamId = await getTabCaptureStreamId(tabId);

        // 2. Ensure the offscreen document exists
        await ensureOffscreenDocument();

        // 3. Tell the offscreen document to start
        const resp = await chrome.runtime.sendMessage({
          type: 'OFFSCREEN_START',
          streamId,
          backendUrl,
          token: token || null,
        });

        if (!resp || !resp.ok) {
          setState({ status: 'error', error: resp?.error || 'Offscreen start failed' });
          return { ok: false, error: resp?.error || 'Offscreen start failed' };
        }

        setState({ status: 'monitoring', callId: resp.callId });
        return { ok: true, callId: resp.callId };

      } catch (err) {
        setState({ status: 'error', error: err.message });
        return { ok: false, error: err.message };
      }
    }

    case 'STOP_MONITORING': {
      if (monitoringState.status === 'idle') {
        return { ok: true };
      }
      setState({ status: 'stopping' });
      try {
        await chrome.runtime.sendMessage({ type: 'OFFSCREEN_STOP' });
      } catch (_) {
        // Offscreen may already be gone
      }
      await closeOffscreenDocument();
      setState({ status: 'idle', callId: null });
      return { ok: true };
    }

    // ── Messages relayed from offscreen ──────────────────────────────────────

    case 'OFFSCREEN_STATUS': {
      // Offscreen reports a status/result update
      const { status, callId, result, error } = message;
      const patch = {};
      if (status) patch.status = status;
      if (callId) patch.callId = callId;
      if (result !== undefined) patch.latestResult = result;
      if (error !== undefined) patch.error = error;
      setState(patch);

      if (status === 'completed' || status === 'error') {
        await closeOffscreenDocument();
      }
      return { ok: true };
    }

    default:
      return { ok: false, error: `Unknown message type: ${messa
/**
 * TRUSTLAYER Guardian — Background Service Worker (Manifest V3)
 *
 * Responsibilities:
 *  - Manage the offscreen document lifecycle.
 *  - Relay messages between popup and offscreen document.
 *  - Hold monitoring state.
 *  - Obtain tab capture stream IDs.
 */

'use strict';

let monitoringState = {
  status: 'idle',
  callId: null,
  error: null,
  latestResult: null,
  tabId: null,
};

let offscreenReady = false;
let offscreenCreating = false;

function setState(patch) {
  monitoringState = { ...monitoringState, ...patch };

  chrome.runtime.sendMessage({
    type: 'STATE_UPDATE',
    state: monitoringState
  }).catch(() => {});
}

async function ensureOffscreenDocument() {
  if (offscreenReady) return;

  if (offscreenCreating) {
    while (offscreenCreating) {
      await new Promise(resolve => setTimeout(resolve, 50));
    }

    if (offscreenReady) return;
    throw new Error('Offscreen document creation failed');
  }

  offscreenCreating = true;

  try {
    // FIX: getContexts belongs to chrome.runtime, not chrome.offscreen.
    const existing = await chrome.runtime.getContexts({
      contextTypes: ['OFFSCREEN_DOCUMENT'],
    });

    if (existing && existing.length > 0) {
      offscreenReady = true;
      return;
    }

    await chrome.offscreen.createDocument({
      url: 'offscreen.html',
      reasons: ['USER_MEDIA'],
      justification: 'Capture tab audio stream for deepfake voice detection',
    });

    offscreenReady = true;

    console.log('[TLG background] Offscreen document created');

  } catch (err) {
    console.error(
      '[TLG background] Failed to create offscreen document:',
      err
    );

    throw err;

  } finally {
    offscreenCreating = false;
  }
}

async function closeOffscreenDocument() {
  offscreenReady = false;

  try {
    const existing = await chrome.runtime.getContexts({
      contextTypes: ['OFFSCREEN_DOCUMENT'],
    });

    if (existing && existing.length > 0) {
      await chrome.offscreen.closeDocument();
    }
  } catch (err) {
    console.warn('[TLG background] Offscreen close:', err.message);
  }
}

function getTabCaptureStreamId(tabId) {
  return new Promise((resolve, reject) => {
    chrome.tabCapture.getMediaStreamId(
      {
        consumerTabId: tabId,
        targetTabId: tabId
      },
      (streamId) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
        } else if (!streamId) {
          reject(new Error('Could not obtain tab capture stream ID'));
        } else {
          resolve(streamId);
        }
      }
    );
  });
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  handleMessage(message)
    .then(sendResponse)
    .catch((err) => {
      sendResponse({
        ok: false,
        error: err.message
      });
    });

  return true;
});

async function handleMessage(message) {
  switch (message.type) {

    case 'GET_STATE':
      return {
        ok: true,
        state: monitoringState
      };

    case 'START_MONITORING': {
      const { tabId, backendUrl, token } = message;

      if (
        !['idle', 'completed', 'error'].includes(monitoringState.status)
      ) {
        return {
          ok: false,
          error: 'Already monitoring. Stop the current session first.'
        };
      }

      setState({
        status: 'connecting',
        callId: null,
        error: null,
        latestResult: null,
        tabId
      });

      try {
        // 1. Obtain tab capture stream ID.
        const streamId = await getTabCaptureStreamId(tabId);

        // 2. Create or reuse offscreen document.
        await ensureOffscreenDocument();

        // 3. Start audio processing in offscreen document.
        const resp = await chrome.runtime.sendMessage({
          type: 'OFFSCREEN_START',
          streamId,
          backendUrl,
          token: token || null
        });

        if (!resp || !resp.ok) {
          throw new Error(resp?.error || 'Offscreen start failed');
        }

        setState({
          status: 'monitoring',
          callId: resp.callId
        });

        return {
          ok: true,
          callId: resp.callId
        };

      } catch (err) {
        console.error('[TLG background] Start failed:', err);

        setState({
          status: 'error',
          error: err.message
        });

        return {
          ok: false,
          error: err.message
        };
      }
    }

    case 'STOP_MONITORING': {
      if (monitoringState.status === 'idle') {
        return { ok: true };
      }

      setState({ status: 'stopping' });

      try {
        await chrome.runtime.sendMessage({
          type: 'OFFSCREEN_STOP'
        });
      } catch (_) {
        // Offscreen document may already be closed.
      }

      await closeOffscreenDocument();

      setState({
        status: 'idle',
        callId: null,
        error: null
      });

      return { ok: true };
    }

    case 'OFFSCREEN_STATUS': {
      const { status, callId, result, error } = message;

      const patch = {};

      if (status) patch.status = status;
      if (callId) patch.callId = callId;
      if (result !== undefined) patch.latestResult = result;
      if (error !== undefined) patch.error = error;

      setState(patch);

      if (status === 'completed' || status === 'error') {
        await closeOffscreenDocument();
      }

      return { ok: true };
    }

    default:
      return {
        ok: false,
        error: `Unknown message type: ${message.type}`
      };
  }
}

chrome.tabs.onRemoved.addListener((tabId) => {
  if (
    monitoringState.tabId === tabId &&
    monitoringState.status !== 'idle'
  ) {
    console.log(
      '[TLG background] Monitored tab closed — stopping monitoring'
    );

    handleMessage({
      type: 'STOP_MONITORING'
    });
  }
});

console.log('[TLG background] Service worker initialised');
ge.type}` };
  }
}

// ── Clean up if the tab being monitored is closed ────────────────────────────

chrome.tabs.onRemoved.addListener((tabId) => {
  if (monitoringState.tabId === tabId && monitoringState.status !== 'idle') {
    console.log('[TLG background] Monitored tab closed — stopping monitoring');
    handleMessage({ type: 'STOP_MONITORING' });
  }
});

console.log('[TLG background] Service worker initialised');
