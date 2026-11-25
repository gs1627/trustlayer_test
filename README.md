# TRUSTLAYER — Adaptive Caller Trust & Transaction Security

TRUSTLAYER is a hackathon prototype that combines voice authenticity checks, speaker identity verification, multilingual speech transcription, conversation-risk analysis and a deterministic transaction policy gate.

## Project structure

- `frontend/` — React + TypeScript + Vite dashboard.
- `backend/` — FastAPI, async SQLAlchemy, DetectifAI adapters, evidence store, Trust Engine contracts, webhook handling and simulated transaction policy.
- `docs/MEMBER_HANDOFF_CONTRACTS.md` — authoritative REST/WebSocket and evidence contracts.
- `docs/INTEGRATION_STATUS.md` — what is connected and what remains incomplete.

## Local setup

### 1. Backend

Windows PowerShell:

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Set provider credentials in `backend/.env` only when available. Never commit that file. The backend defaults to local development mode with anonymous local access when no backend token/JWT is configured; do not expose that configuration publicly.

API docs: `http://127.0.0.1:8000/docs`  
Health: `http://127.0.0.1:8000/api/v1/health`

### 2. Frontend

Open a second terminal:

```powershell
cd frontend
npm ci
Copy-Item .env.example .env
npm run dev
```

The default `VITE_API_BASE_URL` is `http://localhost:8000`. If Vite selects a different host/port, add that origin to `CORS_ORIGINS` in `backend/.env` and restart FastAPI.

### 3. Authentication

The current backend provides bearer-token/service authentication (`POST /api/v1/auth/token` and `GET /api/v1/auth/me`), not end-user email/password registration. In local development with no backend credentials configured, the login page can use the backend's local development principal. When `BACKEND_ACCESS_TOKEN` or JWT authentication is configured, paste the bearer token in the login token field. Do not put provider API keys in the frontend.

## Security boundaries

- Browser audio is sent to FastAPI; DetectifAI credentials remain backend-only.
- Live call audio must be mono PCM16LE at 16 kHz. It is a microphone demo stream, not a telephone/PSTN integration.
- The current live WebSocket path relays audio to DetectifAI. Sarvam's realtime transcription pipeline is not yet teed into that WebSocket.
- Conversation Intelligence and Forensics use the backend short-clip endpoint, which expects multipart audio (`call_id`, `voice_evidence_json`, `file`), not a pasted transcript.
- Transaction evaluation is simulated only. No real banking/payment action is executed.
- The registration, profile, customer approval, analytics and several admin settings remain browser/demo experiences because matching secured backend contracts are not implemented.
- Missing evidence is not approval. Aletheia authenticity, Eidos identity, Sarvam transcription and Gemini context are separate evidence dimensions.
