
/**
 * TRUSTLAYER Guardian — Background Service Worker
 * Manifest V3
 */

'use strict';

let monitoringState = {
  status: 'idle',
  callId: null,
  error: null,
  latestResult: null,
  tabId: null
};

let offscreenReady = false;
let offscreenCreating = null;

// --------------------------------------------------
// STATE MANAGEMENT
// --------------------------------------------------

function setState(patch) {
  monitoringState = {
    ...monitoringState,
    ...patch
  };

  chrome.runtime.sendMessage({
    type: 'STATE_UPDATE',
    state: monitoringState
  }).catch(() => {});
}

// --------------------------------------------------
// OFFSCREEN DOCUMENT MANAGEMENT
// --------------------------------------------------

async function ensureOffscreenDocument() {

  if (offscreenReady) {
    return;
  }

  if (offscreenCreating) {
    await offscreenCreating;
    return;
  }

  offscreenCreating = (async () => {

    try {

      // Check whether an offscreen document already exists.
      // getContexts belongs to chrome.runtime, NOT chrome.offscreen.

      if (typeof chrome.runtime.getContexts === 'function') {

        const contexts = await chrome.runtime.getContexts({
          contextTypes: ['OFFSCREEN_DOCUMENT']
        });

        if (contexts.length > 0) {
          offscreenReady = true;
          console.log('[TLG background] Existing offscreen document found');
          return;
        }
      }

      // Create the offscreen document.
      await chrome.offscreen.createDocument({
        url: 'offscreen.html',
        reasons: ['USER_MEDIA'],
        justification: 'Capture tab audio for real-time deepfake voice detection'
      });

      offscreenReady = true;

      console.log('[TLG background] Offscreen document created');

    } catch (error) {

      // If another operation already created it, verify that it exists.
      if (typeof chrome.runtime.getContexts === 'function') {

        const contexts = await chrome.runtime.getContexts({
          contextTypes: ['OFFSCREEN_DOCUMENT']
        }).catch(() => []);

        if (contexts.length > 0) {
          offscreenReady = true;
          return;
        }
      }

      console.error(
        '[TLG background] Offscreen creation failed:',
        error
      );

      throw error;

    } finally {
      offscreenCreating = null;
    }

  })();

  await offscreenCreating;
}

async function closeOffscreenDocument() {

  offscreenReady = false;

  try {

    if (typeof chrome.runtime.getContexts === 'function') {

      const contexts = await chrome.runtime.getContexts({
        contextTypes: ['OFFSCREEN_DOCUMENT']
      });

      if (contexts.length === 0) {
        return;
      }
    }

    await chrome.offscreen.closeDocument();

    console.log('[TLG background] Offscreen document closed');

  } catch (error) {

    console.warn(
      '[TLG background] Offscreen close warning:',
      error.message
    );
  }
}

// --------------------------------------------------
// TAB AUDIO CAPTURE
// --------------------------------------------------

function getTabCaptureStreamId(tabId) {

  return new Promise((resolve, reject) => {

    chrome.tabCapture.getMediaStreamId(
      {
        consumerTabId: tabId,
        targetTabId: tabId
      },
      (streamId) => {

        if (chrome.runtime.lastError) {
          reject(
            new Error(chrome.runtime.lastError.message)
          );

        } else if (!streamId) {
          reject(
            new Error('Could not obtain tab capture stream ID')
          );

        } else {
          resolve(streamId);
        }
      }
    );
  });
}

// --------------------------------------------------
// MESSAGE LISTENER
// --------------------------------------------------

chrome.runtime.onMessage.addListener(
  (message, sender, sendResponse) => {

    handleMessage(message)
      .then(sendResponse)
      .catch((error) => {

        console.error('[TLG background] Message error:', error);

        sendResponse({
          ok: false,
          error: error.message
        });
      });

    return true;
  }
);

// --------------------------------------------------
// MESSAGE HANDLER
// --------------------------------------------------

async function handleMessage(message) {

  switch (message.type) {

    case 'GET_STATE':

      return {
        ok: true,
        state: monitoringState
      };

    // ----------------------------------------------
    // START MONITORING
    // ----------------------------------------------

    case 'START_MONITORING': {

      const {
        tabId,
        backendUrl,
        token
      } = message;

      if (
        !['idle', 'completed', 'error'].includes(
          monitoringState.status
        )
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

        console.log('[TLG background] Obtaining tab audio stream');

        // 1. Obtain tab capture stream ID.
        const streamId = await getTabCaptureStreamId(tabId);

        // 2. Create or reuse offscreen document.
        await ensureOffscreenDocument();

        // 3. Start audio processing.
        console.log('[TLG background] Starting offscreen audio processing');

        const response = await chrome.runtime.sendMessage({

          type: 'OFFSCREEN_START',

          streamId,

          backendUrl,

          token: token || null

        });

        if (!response || !response.ok) {

          throw new Error(
            response?.error || 'Offscreen start failed'
          );
        }

        setState({
          status: 'monitoring',
          callId: response.callId
        });

        console.log('[TLG background] Monitoring started');

        return {
          ok: true,
          callId: response.callId
        };

      } catch (error) {

        console.error(
          '[TLG background] Monitoring start failed:',
          error
        );

        setState({
          status: 'error',
          error: error.message
        });

        return {
          ok: false,
          error: error.message
        };
      }
    }

    // ----------------------------------------------
    // STOP MONITORING
    // ----------------------------------------------

    case 'STOP_MONITORING': {

      if (monitoringState.status === 'idle') {
        return { ok: true };
      }

      setState({
        status: 'stopping'
      });

      try {

        await chrome.runtime.sendMessage({
          type: 'OFFSCREEN_STOP'
        });

      } catch (error) {

        console.warn(
          '[TLG background] Offscreen stop warning:',
          error.message
        );
      }

      await closeOffscreenDocument();

      setState({
        status: 'idle',
        callId: null,
        error: null
      });

      return { ok: true };
    }

    // ----------------------------------------------
    // OFFSCREEN STATUS UPDATES
    // ----------------------------------------------

    case 'OFFSCREEN_STATUS': {

      const {
        status,
        callId,
        result,
        error
      } = message;

      const patch = {};

      if (status) patch.status = status;
      if (callId) patch.callId = callId;

      if (result !== undefined) {
        patch.latestResult = result;
      }

      if (error !== undefined) {
        patch.error = error;
      }

      setState(patch);

      if (
        status === 'completed' ||
        status === 'error'
      ) {

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

// --------------------------------------------------
// TAB CLOSE CLEANUP
// --------------------------------------------------

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
