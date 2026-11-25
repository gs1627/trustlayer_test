/**
 * TRUSTLAYER Guardian — Options / Settings Script
 */

'use strict';

const $backendUrl     = document.getElementById('backend-url');
const $token          = document.getElementById('token');
const $btnSave        = document.getElementById('btn-save');
const $btnClearToken  = document.getElementById('btn-clear-token');
const $saveMsg        = document.getElementById('save-msg');

// Load saved settings on page open
chrome.storage.local.get(['backendUrl', 'token'], (data) => {
  $backendUrl.value = data.backendUrl || 'http://localhost:8000';
  $token.value = data.token || '';
});

function showMsg(text, isError = false) {
  $saveMsg.textContent = text;
  $saveMsg.className = isError ? 'err' : 'ok';
  $saveMsg.style.display = 'inline';
  setTimeout(() => { $saveMsg.style.display = 'none'; }, 3000);
}

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

$btnSave.addEventListener('click', () => {
  const urlResult = validateBackendUrl($backendUrl.value);
  if (!urlResult.ok) {
    showMsg(urlResult.error, true);
    return;
  }

  const token = $token.value.trim();

  chrome.storage.local.set(
    { backendUrl: urlResult.value, token },
    () => {
      if (chrome.runtime.lastError) {
        showMsg('Failed to save: ' + chrome.runtime.lastError.message, true);
      } else {
        showMsg('✅ Settings saved.');
      }
    }
  );
});

$btnClearToken.addEventListener('click', () => {
  $token.value = '';
  chrome.storage.local.set({ token: '' }, () => {
    showMsg('Token cleared.');
  });
});
