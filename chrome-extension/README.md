# TRUSTLAYER Guardian — Chrome Extension

> **Real-time deepfake voice detection for browser-based calls.**
>
> TRUSTLAYER Guardian captures audio from the current browser tab and streams it to your TRUSTLAYER backend, which relays it to the DetectifAI live stream. Analysis results are displayed in the popup in real time.

---

## Table of Contents

1. [Installation in Chrome](#1-installation-in-chrome)
2. [Configuring the Backend URL](#2-configuring-the-backend-url)
3. [Configuring Authentication](#3-configuring-authentication)
4. [How to Start Monitoring](#4-how-to-start-monitoring)
5. [Supported Audio Behaviour](#5-supported-audio-behaviour)
6. [Architecture Overview](#6-architecture-overview)
7. [Limitations](#7-limitations)
8. [Troubleshooting](#8-troubleshooting)
9. [Privacy & Security](#9-privacy--security)

---

## 1. Installation in Chrome

1. Open **`chrome://extensions`** in your browser.
2. Enable **Developer mode** (toggle in the top-right corner).
3. Click **Load unpacked**.
4. Navigate to and select this **`chrome-extension/`** folder.
5. The TRUSTLAYER Guardian shield icon (🛡️) will appear in your toolbar.
6. Pin it for easy access: click the puzzle-piece icon → pin TRUSTLAYER Guardian.

---

## 2. Configuring the Backend URL

The extension ships with `http://localhost:8000` as the default backend URL.

**To change it:**

1. Right-click the extension icon → **Options**, or click ⚙️ inside the popup.
2. In the **Backend URL** field, enter the full URL of your TRUSTLAYER backend.
   - Local development: `http://localhost:8000`
   - Deployed instance: `https://your-backend.example.com`
3. Click **Save Settings**.

The extension automatically converts `http://` → `ws://` and `https://` → `wss://` when
opening WebSocket connections. You do **not** need to enter a `ws://` URL.

---

## 3. Configuring Authentication

The extension supports three authentication modes (matching the backend exactly):

| Mode | When it applies | What to paste |
|---|---|---|
| **Dev open** | Local backend with no `BACKEND_ACCESS_TOKEN` or `JWT_SECRET_KEY` | Leave the token field blank |
| **JWT** | Backend has `JWT_SECRET_KEY` configured | Paste the JWT from `POST /api/v1/auth/token` |
| **Shared token** | Backend has `BACKEND_ACCESS_TOKEN` configured | Paste the value from your `.env` file |

**How to obtain a JWT from the backend:**

```bash
curl -X POST http://localhost:8000/api/v1/auth/token \
  -H "Authorization: Bearer YOUR_BACKEND_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"subject":"my-user","role":"user","expires_in_seconds":3600}'
```

Copy the `access_token` from the response and paste it into the extension Settings.

> **Security note:** The token is stored only in `chrome.storage.local` on your device.
> It is not synced to other devices, not embedded in extension files, and never placed in
> WebSocket URL query parameters. It is sent only in the first WebSocket message frame:
> `{"type":"auth","token":"…"}`.

**What NOT to paste:**
- `DETECTIF_API_KEY` — this is a backend server secret, never share it.
- `JWT_SECRET_KEY` — this is a backend signing key, never share it.

---

## 4. How to Start Monitoring

1. Open a browser-based call in a tab (Google Meet, Microsoft Teams web, Zoom web, etc.).
2. Click the TRUSTLAYER Guardian icon.
3. Read the **privacy notice** in the popup.
4. Click **▶ Start Monitoring**.
5. The extension will:
   - Create a call session on the backend.
   - Capture audio from the active tab.
   - Open a WebSocket to the backend.
   - Stream raw 16 kHz mono PCM16LE audio.
6. Live analysis results appear in the popup as they arrive from DetectifAI.
7. Click **⏹ Stop Monitoring** to end the session at any time.

The session also stops automatically if:
- The monitored tab is closed.
- The WebSocket connection drops.
- The DetectifAI stream sends a `completed` message.

---

## 5. Supported Audio Behaviour

| Feature | Behaviour |
|---|---|
| **What is captured** | Audio from the **active browser tab only** |
| **Microphone** | **Not captured** |
| **Desktop/system audio** | **Not captured** |
| **User hears tab audio** | ✅ Tab audio remains audible while being captured |
| **Sample rate** | Resampled to exactly 16,000 Hz |
| **Channels** | Downmixed to mono |
| **Format** | Signed 16-bit little-endian PCM (PCM16LE) |
| **Frame size** | ~100 ms per frame (1,600 samples = 3,200 bytes) |
| **Max frame size** | 60 KB (backend hard limit: 64 KB) |
| **Local recording** | None — audio is never saved to disk |

---

## 6. Architecture Overview

```
┌────────────┐    messages    ┌──────────────────────┐    messages    ┌─────────────────┐
│  popup.js  │◄──────────────│  background.js (SW)  │◄──────────────│  offscreen.js   │
│            │───────────────►│                      │───────────────►│                 │
│  UI/UX     │  START/STOP   │  State manager       │  OFFSCREEN_*  │  AudioContext   │
│            │  GET_STATE    │  tabCapture.getMediaS│               │  AudioWorklet   │
└────────────┘               │  treamId()           │               │  WebSocket      │
                              └──────────────────────┘               └─────────────────┘
                                                                              │
                                                              PCM16LE binary frames
                                                                              │
                                                                              ▼
                                                               ┌─────────────────────────┐
                                                               │  TRUSTLAYER Backend     │
                                                               │  POST /api/v1/calls/    │
                                                               │        sessions         │
                                                               │  WS /api/v1/calls/      │
                                                               │       ws/{call_id}      │
                                                               └─────────────────────────┘
                                                                              │
                                                                     Relay to DetectifAI
                                                                              │
                                                                       Analysis results
                                                                   forwarded to extension
```

**Key design decisions:**

- **Offscreen document** holds the `AudioContext` and `WebSocket`. Without it, the
  Manifest V3 service worker would be killed after ~30 s, stopping recording.
- **`chrome.tabCapture.getMediaStreamId()`** must run in the service worker; the
  resulting stream ID is passed to the offscreen document, which calls
  `navigator.mediaDevices.getUserMedia({ audio: { mandatory: { chromeMediaSource:'tab', … } } })`.
- **AudioWorklet** (`audio-processor.js`) runs on a dedicated audio thread to avoid
  glitches caused by main-thread JavaScript work.
- Tokens are sent in the **first WebSocket JSON frame** (`{"type":"auth","token":"…"}`),
  as required by the backend's `resolve_websocket_principal()` implementation.

---

## 7. Limitations

- **Browser-tab audio only.** Cellular calls, VoIP apps, or native desktop applications
  are not supported in this version.
- **DetectifAI API key required.** The backend must have `DETECTIF_API_KEY` configured;
  without it the backend will close the WebSocket with a stream error.
- **Single session per extension instance.** Only one tab can be monitored at a time.
- **Provisional results.** Early (non-final) DetectifAI results may change as more audio
  is processed. The UI distinguishes provisional from final results.
- **CORS.** If your backend is deployed on a different origin, you must add
  `chrome-extension://<YOUR_EXTENSION_ID>` to the backend's `CORS_ORIGINS` environment
  variable. See the Troubleshooting section below.
- **No audio encoding.** The backend WebSocket expects raw binary PCM16LE, not WebM,
  Opus, or any other encoded format.

---

## 8. Troubleshooting

### "Backend unreachable"
- Confirm the backend is running: `curl http://localhost:8000/api/v1/health`
- Check the Backend URL in Settings (must include `http://` or `https://`).
- If you deployed the backend, ensure HTTPS is enabled and the URL is correct.

### "Failed to create call session: HTTP 401"
- A JWT or shared token is required. Configure it in Settings.
- If running locally in dev mode (no `BACKEND_ACCESS_TOKEN` / `JWT_SECRET_KEY`), leave
  the token field blank — the backend allows anonymous dev access automatically.

### "Failed to create call session: HTTP 422"
- The request body was rejected. This should not happen with the default `deepfake` mode
  since `speaker_id` is not required. Check backend logs.

### "WebSocket connection failed"
- The backend must be reachable via WebSocket. Check firewall rules.
- For HTTPS backends, the WebSocket URL will be `wss://` — ensure TLS is configured.

### CORS errors in the browser console
1. Find your extension ID: `chrome://extensions` → TRUSTLAYER Guardian → ID shown below name.
2. Add this to the backend `.env`:
   ```
   CORS_ORIGINS=http://localhost:5173,chrome-extension://YOUR_EXTENSION_ID_HERE
   ```
3. Restart the backend.

### "Could not obtain tab capture stream ID"
- Some tabs cannot be captured (e.g., `chrome://` pages, the Chrome Web Store, PDF viewer).
- Navigate to a regular HTTPS website or supported web-call application first.

### Tab audio not audible after starting
- This is a known Chrome behaviour on some platforms. The extension connects the source
  to `audioCtx.destination` to keep audio audible. If this does not work, stopping and
  restarting monitoring usually resolves it.

### Results never arrive / always "Awaiting audio…"
- The backend requires a valid `DETECTIF_API_KEY`. Without it, the backend closes the
  stream immediately.
- Check backend logs for `DetectifStreamError`.
- Real DetectifAI analysis requires at least several seconds of audio.

---

## 9. Privacy & Security

| Concern | Safeguard |
|---|---|
| Microphone access | Never requested |
| Tab audio storage | Never saved to disk — streamed live only |
| Token storage | `chrome.storage.local` only — not synced, not in URLs |
| Provider API key | Stored server-side only, never in extension files |
| Other tabs | Only the tab active at the moment **Start** was clicked is captured |
| Stop control | Always accessible; stops immediately on click or tab close |
| Background upload | Extension does not upload audio when popup is closed — the offscreen document is closed |

> **Important:** This extension is a monitoring tool. A single or inconclusive result
> from DetectifAI is not proof that a voice is cloned or authentic. All results should
> be treated as supporting evidence alongside other contextual signals.
