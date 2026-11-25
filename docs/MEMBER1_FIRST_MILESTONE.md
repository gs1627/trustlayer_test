# Member 1 — First milestone checklist

## Before coding with real credentials
- [ ] Create DetectifAI account and verify email.
- [ ] Create a scoped API key with `deepfake:detect`, `speakers:enroll`, `speakers:verify` permissions.
- [ ] Confirm remaining hackathon credits.
- [ ] Use only the team's own consented audio samples.

## Backend foundation
- [ ] Create virtual environment.
- [ ] Install requirements.
- [ ] Copy `.env.example` to `.env`.
- [ ] Start FastAPI.
- [ ] Confirm `/api/v1/health`.
- [ ] Run tests.

## Real API verification
- [ ] Test Aletheia on a suitable audio sample.
- [ ] Enroll a consenting teammate using a 15–60 second sample with at least 10 seconds of speech.
- [ ] Verify a fresh 3–60 second sample with at least 2 seconds of speech.
- [ ] Record provider `request_id`, `operation_id`, result and credit usage. Never record API keys.

## Live stream verification
- [ ] Create a call session.
- [ ] Connect browser audio as PCM16LE, mono, 16 kHz.
- [ ] Confirm DetectifAI `ready` message.
- [ ] Confirm deepfake and verification events.
- [ ] Confirm final stream result.

## Webhooks
- [ ] Configure a public HTTPS tunnel.
- [ ] Register `/api/v1/webhooks/detectifai`.
- [ ] Store the signing secret in `.env`.
- [ ] Send `webhook.test` from the provider dashboard.
- [ ] Confirm duplicate delivery is acknowledged without a second database row.

## Handoff to teammates
- [ ] Share OpenAPI docs URL with Person 2.
- [ ] Share `EvidenceItem` contract with Person 3.
- [ ] Confirm call ID and speaker ID conventions.
