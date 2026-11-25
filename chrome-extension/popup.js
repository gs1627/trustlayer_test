
'use strict';

let settings = {
  backendUrl: 'http://127.0.0.1:8000',
  token: ''
};

let activeTabId = null;
let backendAvailable = false;

const $ = (id) => document.getElementById(id);

function normalizeBackendUrl(url) {
  let normalized = (url || 'http://127.0.0.1:8000').trim();
  normalized = normalized.replace(/\/+$/, '');
  normalized = normalized.replace(
    /^http:\/\/localhost(?=:|$)/i,
    'http://127.0.0.1'
  );
  return normalized;
}

async function loadSettings() {
  try {
    const data = await chrome.storage.local.get([
      'backendUrl',
      'token'
    ]);

    settings.backendUrl = normalizeBackendUrl(data.backendUrl);
    settings.token = data.token || '';

    await chrome.storage.local.set({
      backendUrl: settings.backendUrl
    });
  } catch (error) {
    console.error('[TLG popup] Settings load failed:', error);
    settings.backendUrl = 'http://127.0.0.1:8000';
    settings.token = '';
  }
}

async function checkBackendHealth(backendUrl) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);

  try {
    const url =
      `${normalizeBackendUrl(backendUrl)}/api/v1/health`;

    const headers = {};

    if (settings.token) {
      headers.Authorization = `Bearer ${settings.token}`;
    }

    const response = await fetch(url, {
      method: 'GET',
      headers,
      signal: controller.signal
    });

    if (!response.ok) {
      return {
        ok: false,
        detail: `Backend returned HTTP ${response.status}`
      };
    }

    const json = await response.json();

    return {
      ok: true,
      json
    };
  } catch (error) {
    if (error.name === 'AbortError') {
      return {
        ok: false,
        detail: 'Backend request timed out after 5 seconds.'
      };
    }

    return {
      ok: false,
      detail: error.message || 'Unable to connect to backend.'
    };
  } finally {
    clearTimeout(timeout);
  }
}

function sendRuntimeMessage(message, timeoutMs = 4000) {
  return new Promise((resolve, reject) => {
    let settled = false;

    const timeout = setTimeout(() => {
      if (!settled) {
        settled = true;
        reject(new Error('Extension background service timed out.'));
      }
    }, timeoutMs);

    chrome.runtime.sendMessage(message, (response) => {
      if (settled) return;

      settled = true;
      clearTimeout(timeout);

      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }

      resolve(response);
    });
  });
}

function setBackendStatus(connected, detail = '') {
  backendAvailable = connected;

  const statusElement =
    $('backendStatus') ||
    $('backend-status') ||
    $('status');

  if (statusElement) {
    statusElement.textContent = connected
      ? 'Backend connected'
      : 'Backend disconnected';

    statusElement.classList.toggle('connected', connected);
    statusElement.classList.toggle('disconnected', !connected);
  }

  const detailElement =
    $('backendDetail') ||
    $('backend-detail');

  if (detailElement) {
    detailElement.textContent = detail;
  }

  const startButton =
    $('startButton') ||
    $('startBtn') ||
    $('start-monitoring');

  if (startButton) {
    startButton.disabled = !connected;
  }
}

function renderState(state) {
  if (!state) return;

  const monitoring =
    state.monitoring ??
    state.isMonitoring ??
    state.active ??
    false;

  const stateElement =
    $('monitoringStatus') ||
    $('monitoring-status');

  if (stateElement) {
    stateElement.textContent = monitoring
      ? 'Monitoring active'
      : 'Monitoring stopped';
  }

  const startButton =
    $('startButton') ||
    $('startBtn') ||
    $('start-monitoring');

  const stopButton =
    $('stopButton') ||
    $('stopBtn') ||
    $('stop-monitoring');

  if (startButton) {
    startButton.disabled = monitoring || !backendAvailable;
  }

  if (stopButton) {
    stopButton.disabled = !monitoring;
  }
}

function renderResult(result) {
  if (!result) return;

  const resultElement =
    $('result') ||
    $('resultContainer') ||
    $('result-container');

  if (!resultElement) return;

  if (typeof result === 'string') {
    resultElement.textContent = result;
    return;
  }

  resultElement.textContent =
    result.message ||
    result.detail ||
    result.status ||
    JSON.stringify(result, null, 2);
}

async function refreshBackendStatus() {
  setBackendStatus(false, 'Checking backend...');

  const health = await checkBackendHealth(settings.backendUrl);

  if (health.ok) {
    const providerConfigured =
      health.json?.detectif_configured;

    setBackendStatus(
      true,
      providerConfigured === false
        ? 'Backend connected, but DetectifAI is not configured.'
        : 'Backend is reachable.'
    );
  } else {
    setBackendStatus(false, health.detail);
  }

  return health.ok;
}

async function refreshExtensionState() {
  try {
    const response = await sendRuntimeMessage({
      type: 'GET_STATE'
    });

    if (response?.state) {
      renderState(response.state);
    } else if (response) {
      renderState(response);
    }
  } catch (error) {
    console.error('[TLG popup] Could not get extension state:', error);
    renderResult(error.message);
  }
}

async function startMonitoring() {
  if (!backendAvailable) {
    renderResult('Backend is not connected. Start the backend first.');
    return;
  }

  if (!activeTabId) {
    renderResult('No active browser tab was found.');
    return;
  }

  try {
    const response = await sendRuntimeMessage({
      type: 'START_MONITORING',
      tabId: activeTabId,
      backendUrl: settings.backendUrl,
      token: settings.token
    }, 10000);

    if (response?.error) {
      throw new Error(response.error);
    }

    renderResult(response || 'Monitoring started.');
    await refreshExtensionState();
  } catch (error) {
    console.error('[TLG popup] Start failed:', error);
    renderResult(`Could not start monitoring: ${error.message}`);
  }
}

async function stopMonitoring() {
  try {
    const response = await sendRuntimeMessage({
      type: 'STOP_MONITORING'
    }, 10000);

    renderResult(response || 'Monitoring stopped.');
    await refreshExtensionState();
  } catch (error) {
    console.error('[TLG popup] Stop failed:', error);
    renderResult(`Could not stop monitoring: ${error.message}`);
  }
}

async function init() {
  try {
    await loadSettings();

    try {
      const tabs = await chrome.tabs.query({
        active: true,
        currentWindow: true
      });

      activeTabId = tabs?.[0]?.id || null;
    } catch (error) {
      console.error('[TLG popup] Active tab lookup failed:', error);
    }

    // Check backend before waiting for the background service worker.
    await refreshBackendStatus();

    // Do not let a background service worker issue block popup startup.
    await refreshExtensionState();

    const startButton =
      $('startButton') ||
      $('startBtn') ||
      $('start-monitoring');

    const stopButton =
      $('stopButton') ||
      $('stopBtn') ||
      $('stop-monitoring');

    if (startButton) {
      startButton.addEventListener('click', startMonitoring);
    }

    if (stopButton) {
      stopButton.addEventListener('click', stopMonitoring);
    }

    const refreshButton =
      $('refreshButton') ||
      $('refreshBtn') ||
      $('refresh-backend');

    if (refreshButton) {
      refreshButton.addEventListener('click', refreshBackendStatus);
    }

    console.log('[TLG popup] Initialized.');
  } catch (error) {
    console.error('[TLG popup] Initialization failed:', error);
    setBackendStatus(false, error.message);
  }
}

document.addEventListener('DOMContentLoaded', init);
