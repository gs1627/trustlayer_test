# TRUSTLAYER integration status

This file distinguishes working code paths from prototype screens. Provider execution still depends on backend configuration and valid provider credentials.

## Connected frontend-to-backend paths

| Frontend area | Backend contract | Status / boundary |
|---|---|---|
| Dashboard | `GET /api/v1/health`, `GET /api/v1/calls/sessions` | Live health and call-session count; headline metrics remain labeled sample values. |
| Login | `GET /api/v1/auth/me` | Uses local development principal when auth is not configured, or validates a supplied bearer token. This backend does not implement customer email/password login. |
| Voice enrollment | `POST /api/v1/detectif/speakers/enroll` | Consent-gated multipart upload; requires DetectifAI credentials. Operation acceptance is not the same as completed enrollment. |
| Live Monitoring | `POST /api/v1/calls/sessions`, `WS /api/v1/calls/ws/{call_id}`, `WS /api/v1/calls/ws/{call_id}/events`, evidence and latest-assessment GETs | Browser microphone is converted to mono PCM16/16 kHz and sent through FastAPI to DetectifAI. Optional speaker ID enables `deepfake,verify`. Live Sarvam transcription is not yet wired into this socket. |
| Forensics | call-session creation, `POST /api/v1/detectif/deepfake`, `POST /api/v1/intelligence/analyze` | Runs Aletheia request and short-clip Sarvam/Gemini pipeline. The intelligence endpoint is development-only and caller-supplied voice evidence is not trusted. Eidos is not automatically run. |
| Conversation Intelligence | `POST /api/v1/intelligence/analyze` | Uploads audio as multipart. The backend does not expose a transcript-only JSON endpoint. |
| Transaction Guard | `POST /api/v1/calls/sessions/{call_id}/transactions/simulate` | Uses persisted backend trust/evidence policy and returns simulated-only decisions. Requires an existing call ID. |

## Not yet backed by equivalent backend contracts

- Customer registration and password-based login.
- Persistent user profile read/update and password reset.
- Independent customer approval delivery/verification over a real separate channel.
- Real bank transaction execution.
- Persistent analytics aggregation and full dashboard audit feed.
- Admin toggles that change backend security policy.
- Sarvam live transcription tee into the same real-time audio stream as DetectifAI.

These screens should remain clearly marked as demo/local until the corresponding authenticated backend routes and data models are implemented.

## Backend integration fixes in this package

- Implemented the previously empty `resolve_websocket_principal()` using the documented first JSON auth frame. Local development remains open only when no auth credential is configured; production fails closed.
- Removed duplicate `authenticate_websocket()` definitions that shadowed each other.
- Added the missing `HTTPException` import used by the demo-mode dependency.
- Allowed `PUT` and `PATCH` in CORS for future profile/update APIs.
- Consolidated duplicate route imports in `main.py`.

## Validation performed here

- Python syntax compilation: passed (`python -m compileall -q backend/app`).
- Backend pytest: could not collect because this execution environment does not have `aiosqlite` installed. Install `backend/requirements.txt` in the backend virtual environment before running tests.
- Frontend build: not run; npm dependency installation timed out and the local npm cache does not contain all locked packages (`zustand` package missing offline). Run `npm ci` then `npm run build` on a machine with registry access.
- Real DetectifAI, Sarvam and Gemini requests were not run; no credentials were supplied in this environment.
