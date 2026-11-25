# TRUSTLAYER Frontend

React 19 + TypeScript + Vite dashboard for the TRUSTLAYER FastAPI backend.

## Run locally

```powershell
npm ci
Copy-Item .env.example .env
npm run dev
```

Set `VITE_API_BASE_URL` to the backend origin only (default `http://localhost:8000`). API requests automatically append `/api/v1`. Do not place DetectifAI, Sarvam, Gemini, webhook or JWT signing secrets in frontend environment variables.

## Backend-backed screens

- Dashboard health and call-session count.
- Bearer-token/local-development auth inspection.
- Consent-based voice enrollment via DetectifAI Eidos REST adapter.
- Live Monitoring call-session creation, microphone PCM16/16 kHz stream relay, optional speaker verification, and dashboard event WebSocket.
- Forensics Aletheia audio detection and short-clip Sarvam/Gemini pipeline.
- Conversation Intelligence audio upload and backend pipeline response.
- Transaction Guard simulated policy evaluation for an existing call ID.

Registration, persistent user profile/password management, real independent customer approval, persistent analytics, and production admin controls are not provided by the current backend contracts. Related UI is demonstrative only.
