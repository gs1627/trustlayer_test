# TRUSTLAYER Member Handoff Contracts

These contracts are the shared interface between Member 1 (backend infrastructure, provider hardening, webhooks, security & persistence), Member 2 (frontend dashboard), and Member 3 (AI pipeline & Trust Engine). Coordinate before changing field names.

## Backend HTTP routes

Base prefix: `/api/v1`

| Method | Route | Role Access | Purpose |
|---|---|---|---|
| GET | `/health` | Public | Backend and database connectivity status |
| POST | `/auth/token` | `admin`, `service` (or `BACKEND_ACCESS_TOKEN`) | Issue short-lived signed HS256 JWT bearer token |
| GET | `/auth/me` | Any authenticated principal | Inspect active principal (`subject`, `role`, `auth_type`) |
| POST | `/detectif/deepfake` | Authenticated (`user` scoped if `call_id` passed) | Upload audio for Aletheia detection (+ optional call attachment) |
| POST | `/detectif/speakers/enroll` | Authenticated (`consent_confirmed=true`) | Eidos enrollment + local `SpeakerProfile` lifecycle tracking |
| POST | `/detectif/speakers/verify` | Authenticated | Eidos verification + optional nested deepfake + call evidence |
| GET | `/detectif/operations` | `admin`, `service`, `operator` | List locally tracked `ProviderOperation` lifecycle records |
| GET | `/detectif/operations/{operation_id}` | Authenticated (`user` scoped by call/speaker) | Poll DetectifAI operation result and synchronize local tracking |
| GET | `/detectif/speakers` | Authenticated | List enrolled speakers from DetectifAI |
| DELETE | `/detectif/speakers/{speaker_id}` | Authenticated (owner or privileged) | Delete provider speaker and mark local profile `deleted` |
| GET | `/detectif/streams/{stream_id}` | Authenticated (owner or privileged) | Retrieve DetectifAI stream record |
| POST | `/calls/sessions` | Authenticated | Create call session + auto-reconcile early unmatched webhooks |
| GET | `/calls/sessions` | Authenticated (`user` filtered to own calls) | List paginated call sessions (`status`, `speaker_id`) |
| GET | `/calls/sessions/{call_id}` | Call owner or privileged | Session details, `evidence_summary`, and latest `TrustAssessment` |
| POST | `/calls/sessions/{call_id}/end` | Call owner or privileged | Idempotently end call session (`ended_at`, `ended_reason`) |
| GET | `/calls/sessions/{call_id}/evidence` | Call owner or privileged | Paginated append-only evidence timeline (`check_type`, `provider`, `is_final`) |
| POST | `/calls/sessions/{call_id}/evidence` | `admin`, `service` (Member 3) | Append normalized evidence with `source_event_key` deduplication |
| POST | `/calls/sessions/{call_id}/trust-assessments` | `admin`, `service` (Member 3) | Persist immutable Trust Engine snapshot |
| GET | `/calls/sessions/{call_id}/trust-assessments/latest` | Call owner or privileged | Retrieve latest Trust Assessment |
| GET | `/calls/sessions/{call_id}/trust-assessments` | Call owner or privileged | Paginated immutable Trust Assessment history |
| POST | `/calls/sessions/{call_id}/transactions/simulate` | Call owner or privileged | Evaluate conservative transaction policy (`allow`, `step_up_verify`, `hold`, `block`) |
| POST | `/webhooks/detectifai` | Standard Webhooks HMAC | Verify signature, ingest webhook atomically, normalize evidence |
| GET | `/webhooks/events` | `admin` | Inspect webhook deliveries (`received`, `processed`, `unmatched`, `failed`, `dead_letter`) |
| POST | `/webhooks/reconcile` | `admin` | Re-run reconciliation over `unmatched` and retryable `failed` events |
| POST | `/webhooks/events/{delivery_id}/reprocess` | `admin` | Manually replay a single webhook delivery (including `dead_letter`) |
| WS | `/calls/ws/{call_id}` | Call owner or privileged (JSON auth frame) | Browser PCM audio relay (`deepfake`, `deepfake,verify`, `deepfake,enroll`) |
| WS | `/calls/ws/{call_id}/events` | Call owner or privileged (JSON auth frame) | Real-time dashboard event feed (`evidence.added`, `trust.updated`, `call.status_changed`) |

OpenAPI docs: `/docs`.

## Authentication & authorization contracts

- **Bearer Authentication (`Authorization: Bearer <token>`)**:
  - Supports **HS256 JWTs** (when `JWT_SECRET_KEY` is configured) and preserves **legacy `BACKEND_ACCESS_TOKEN`** compatibility (`shared_token` maps to `service` capability).
  - If `APP_ENV=production` and neither `JWT_SECRET_KEY` nor `BACKEND_ACCESS_TOKEN` is set, protected routes fail closed with HTTP `503`.
  - Expired or invalid tokens return HTTP `401` (`token_expired`, `invalid_token`, or `unauthorized`).
  - Role or cross-user ownership denials return HTTP `403` (`forbidden`, `call_access_forbidden`, `speaker_access_forbidden`).
- **WebSocket Auth (no query-string tokens)**:
  - Both `/api/v1/calls/ws/{call_id}` and `/api/v1/calls/ws/{call_id}/events` require `{"type": "auth", "token": "<JWT_OR_SHARED_TOKEN>"}` as the first JSON text frame whenever auth is configured (`4401` unauthorized, `4403` forbidden, `4404` session not found, `4429` connection/rate limit exceeded).
- **Rate limiting**:
  - Sliding-window rate limiting per client IP returns HTTP `429` (`rate_limit_exceeded`, `retryable: true`) with a `Retry-After` header. Webhook limits default higher (`300/min`) so legitimate provider retries are preserved. *(Single-process in-memory; multi-worker setups need Redis.)*

## Pagination & deterministic ordering

All paginated `GET` collection endpoints accept `limit` (default `50`, `1`–`200`) and `offset` (default `0`, `>= 0`) and return:
```json
{
  "items": [],
  "total": 0,
  "limit": 50,
  "offset": 0
}
```
Sort orders:
- `/calls/sessions`: `(created_at DESC, call_id ASC)`
- `/calls/sessions/{call_id}/evidence`: `(created_at ASC, evidence_id ASC)`
- `/calls/sessions/{call_id}/trust-assessments`: `(created_at DESC, assessment_id DESC)`
- `/detectif/operations`: `(created_at DESC, id DESC)`
- `/webhooks/events`: `(received_at DESC, id DESC)`
- `TrustAssessment.evidence_ids`: `(EvidenceItem.created_at ASC, EvidenceItem.evidence_id ASC)`.

## DetectifAI live stream & scenario modes

1. **Unknown caller (`checks_mode: "deepfake"`)**: `speaker_id` optional/omitted. Stream connects cleanly with `checks=deepfake` without failing on missing voiceprint.
2. **Registered caller (`checks_mode: "deepfake,verify"`)**: Requires `speaker_id`. Streams with `checks=deepfake,verify&speaker_id=...`.
3. **Consent-verified enrollment (`checks_mode: "deepfake,enroll"`)**: Requires `speaker_id` and `consent_confirmed=true`. Streams with `checks=deepfake,enroll&speaker_id=...` and tracks `SpeakerProfile` lifecycle (`pending` -> `enrolled` / `failed` / `deleted`).

## Browser & Dashboard WebSockets

### Live Audio WebSocket: `WS /api/v1/calls/ws/{call_id}`
1. Connect first; if auth configured, send `{"type":"auth","token":"..."}`.
2. Send raw mono PCM16LE 16 kHz binary frames (max 64 KB per frame) and `{"type":"stop"}` text control frame when done.
3. Provider frames are relayed with `{"source": "detectifai", ...}` and normalized asynchronously to `EvidenceItem`.

### Live Dashboard Events WebSocket: `WS /api/v1/calls/ws/{call_id}/events`
1. Connect first; send `{"type":"auth","token":"..."}` if auth configured.
2. Receives initial handshake `{"type": "subscribed", "call_id": "...", "status": "..."}`.
3. Receives live `DomainEvent` JSON frames:
   ```json
   {
     "event_id": "evpub_01...",
     "event_type": "evidence.added",
     "call_id": "CALL_001",
     "occurred_at": "2026-11-25T10:00:08Z",
     "payload": {
       "evidence_id": "ev_01...",
       "provider": "detectifai",
       "model": "aletheia",
       "check_type": "deepfake",
       "status": "pending",
       "verdict": "real",
       "is_early": true,
       "is_final": false,
       "source_channel": "websocket"
     }
   }
   ```
   Supported `event_type` values: `evidence.added`, `trust.updated`, `call.status_changed`. *(Single-process `InMemoryEventBus`; multi-worker fan-out requires Redis/external broker implementing `EventPublisher`.)*

## Member 3 AI pipeline & Trust Engine contracts

- Submit Sarvam (`transcription`) and Gemini (`context`) observations via `POST /api/v1/calls/sessions/{call_id}/evidence` using `EvidenceItemCreate` (`source_event_key` enables idempotent HTTP `200` retry handling; new rows return `201`).
- Submit Trust Engine evaluations via `POST /api/v1/calls/sessions/{call_id}/trust-assessments` using `TrustAssessmentCreate` (`trust_score` is a bounded score in `[0.0, 1.0]`, not automatically a calibrated probability).
- Evidence is strictly append-only; provisional updates never overwrite finalized evidence records, and `is_early` / `is_final` remain independent flags.

## Simulated transaction policy contract (`POST /api/v1/calls/sessions/{call_id}/transactions/simulate`)

Request (`SimulatedTransactionRequest`):
```json
{
  "action_type": "fund_transfer",
  "amount": "25000.50",
  "currency": "INR",
  "recipient_ref": "DEMO_01",
  "notes": "Customer requested transfer"
}
```
Response (`SimulatedTransactionResponse`, always `simulated: true`):
```json
{
  "transaction_id": "tx_01...",
  "call_id": "CALL_001",
  "assessment_id": "ta_01...",
  "action_type": "fund_transfer",
  "amount": "25000.50",
  "currency": "INR",
  "decision": "step_up_verify",
  "policy_reasons": ["trust_risk_medium", "high_value_missing_final_context"],
  "evidence_ids": ["ev_01...", "ev_02..."],
  "policy_version": "policy-v1",
  "simulated": true,
  "created_at": "2026-11-25T10:00:12Z"
}
```
Allowed `decision` values follow conservative precedence (`block` > `hold` > `step_up_verify` > `allow`).

## Error envelope & HTTP status codes

Structured domain errors return `ErrorResponse`:
```json
{
  "detail": "Call session 'CALL_MISSING' not found",
  "error": {
    "code": "call_session_not_found",
    "message": "Call session 'CALL_MISSING' not found",
    "provider": null,
    "request_id": null,
    "retryable": false,
    "details": { "call_id": "CALL_MISSING" }
  }
}
```
Common statuses: `401` (`unauthorized`, `token_expired`, `invalid_token`), `403` (`forbidden`, `call_access_forbidden`, `speaker_access_forbidden`), `404` (`call_session_not_found`, `trust_assessment_not_found`, `webhook_event_not_found`), `409` (`call_session_already_exists`), `422` (`cross_call_mismatch`, `evidence_not_found`, `cross_call_evidence_not_allowed`, Pydantic validation), `429` (`rate_limit_exceeded` + `Retry-After`), `503` (`auth_not_configured`, DetectifAI unconfigured).
## REST audio contracts

### Aletheia
`multipart/form-data`: `file`
Optional header: `Idempotency-Key`

### Eidos enrollment
`multipart/form-data`: `speaker_id`, `file`, `consent_confirmed=true`, optional `display_name`.

Provider requirements: 15–60 seconds total audio and at least 10 seconds of speech. Up to five enrolled samples per speaker.

### Eidos verification
`multipart/form-data`: `speaker_id`, `file`, optional `detect_deepfake=true`.

Provider requirements: 3–60 seconds total audio and at least 2 seconds of speech.

## Browser WebSocket contract

1. Create a session using `POST /api/v1/calls/sessions` with `{ "call_id": "CALL_001", "speaker_id": "CUSTOMER_001" }`.
2. If `BACKEND_ACCESS_TOKEN` is set, send a first text frame `{ "type": "auth", "token": "YOUR_TOKEN" }`.
3. Connect to `ws://localhost:8000/api/v1/calls/ws/CALL_001`. (Browser WebSocket clients connect first, then send the auth frame.)
4. Send binary frames containing raw mono PCM16LE audio at 16 kHz. Each frame must be at most 64 KB.
5. Send a text frame `{ "type": "stop" }` to end the stream.
6. Backend forwards DetectifAI messages to the browser as JSON with `source: "detectifai"`.

Expected provider message types include `ready`, `deepfake`, `verification`, `completed`, and `error`. The final `completed` message contains final check results. The early verdict and live updates are provisional.

## Member 3 evidence contract

Use the provider-neutral `EvidenceItem` in `app/schemas/contracts.py`. Core fields:

- `call_id`: local call identifier.
- `provider`: provider name, e.g. `detectifai`, `sarvam`, `gemini`, `aasist`.
- `model`: model identifier.
- `check_type`: `deepfake`, `speaker_verification`, `transcription`, or `context`.
- `status`: `pending`, `completed`, `failed`, or `inconclusive`.
- `verdict`: provider decision such as `real`, `fake`, `match`, `no_match`; do not reinterpret a score as a probability.
- `raw_score`: provider-returned score where available.
- `score_type`: semantic label for the score.
- `is_final`: whether this is a final result rather than an early/live update.
- `provider_operation_id`: provider trace identifier where available.
- `details`: provider-specific metadata after removing secrets and unnecessary personal data.

Member 3 owns the Trust Engine. Member 1 owns provider transport and session infrastructure.

## Member 2 frontend contract

- Use REST endpoints for enrollment, file checks, speaker management and session creation.
- Use the browser WebSocket for live call audio and live DetectifAI messages.
- Never call DetectifAI directly from browser code; the API key is backend-only.
- Treat `early: true` and non-final stream updates as provisional. Display final results separately.
- Display `inconclusive`, `failed` and `unavailable` distinctly from `real` or `match`.

## Important boundaries

- The optional `BACKEND_ACCESS_TOKEN` is only a shared development gate, not customer login/RBAC. Do not deploy publicly until proper authentication, authorization, rate limiting and secure deployment configuration are added.
- The browser WebSocket is a development integration path. Production needs authenticated sessions and allowed-origin validation.
- No real bank transaction execution is implemented. The transaction interface must use simulated data until authorised integration exists.

## Development-only demo routes

- `POST /api/v1/intelligence/analyze` accepts an audio file, call ID and optional caller-supplied DetectifAI voice evidence. Caller-supplied evidence is untrusted; use synthetic/test data only.
- `POST /api/v1/transactions/challenges` and `POST /api/v1/transactions/simulate` provide a local demo of policy and one-use challenge checks. Customer IDs and trust decisions are caller-supplied, the challenge token is returned directly to the demo client, and no real transaction is executed.
- These routes are disabled when `APP_ENV=production`. They are not a substitute for customer authentication, trusted server-side evidence, or an independent approval channel.
