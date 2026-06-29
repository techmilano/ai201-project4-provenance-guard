# Stretch Feature 2 — Provenance Certificate: verification record

Evidence for the **Verified Human** credential (live writing challenge). A
creator earns a creator-level credential by writing a response to a random
prompt that the system scores with its own detection pipeline. The credential is
displayed on the creator's content but **never overrides content attribution**.

Config: `VERIFY_MIN_WORDS = 80`, `VERIFY_MAX_AI_PROBABILITY = 0.30`,
`CHALLENGE_EXPIRES_MINUTES = 15`. Run against a temp data dir so the real store
stays clean.

---

## 1. Submit BEFORE verification → no badge

`POST /submit { text, creator_id: "alice" }`

```json
"provenance_certificate": { "verified_human": false, "badge": null, "verified_at": null }
```

## 2. Request a challenge

`POST /verification-challenge { "creator_id": "alice" }` → `200`

```json
{
  "creator_id": "alice",
  "challenge_id": "10d497fe-926c-4f84-880c-4f96f0e2c14c",
  "prompt": "Write 80 to 150 words about a small real-world moment from your day.",
  "expires_at": "2026-06-29T03:14:27.426660Z"
}
```

## 3. Verify with a too-short response → 403

`POST /verify { creator_id, challenge_id, response_text: "I wrote this myself." }`

```json
{ "error": "response_text must be at least 80 words", "word_count": 4 }
```

## 4. Verify with a genuine human passage → granted

`POST /verify { creator_id: "alice", challenge_id, response_text: <~95-word casual passage> }` → `200`

```json
{
  "creator_id": "alice",
  "verified_human": true,
  "badge": "✓ Verified Human Creator",
  "verified_at": "2026-06-29T02:59:27.748523Z",
  "method": "live_writing_challenge",
  "challenge_score": 0.2366
}
```

The response scored `0.2366` ≤ `0.30`, so the credential was granted. (A
**second scored attempt on the same challenge returns 403 `challenge has already
been used`** — one attempt per challenge.)

## 5. Check status

`GET /creators/alice` → `200`

```json
{
  "creator_id": "alice",
  "verified_human": true,
  "badge": "✓ Verified Human Creator",
  "verified_at": "2026-06-29T02:59:27.748523Z",
  "method": "live_writing_challenge"
}
```

`GET /creators/bob` (never verified) →
`{ "creator_id": "bob", "verified_human": false, "badge": null, "verified_at": null }`

## 6. Submit AFTER verification → badge attached

```json
"provenance_certificate": {
  "verified_human": true,
  "badge": "✓ Verified Human Creator",
  "verified_at": "2026-06-29T02:59:27.748523Z"
}
```

## 7. The key case — verified creator submits AI-like text

A verified creator submits clearly-AI prose. The badge is shown **and** the
content is still flagged `likely_ai` — the certificate does not launder the
content.

`POST /submit { text: <clearly-AI paragraph>, creator_id: "alice" }` → `200`

```json
{
  "attribution": "likely_ai",
  "confidence": 0.8243,
  "label": "⚠️ Likely AI-generated. Our analysis found strong signals that this text was produced by an AI system.",
  "provenance_certificate": {
    "verified_human": true,
    "badge": "✓ Verified Human Creator",
    "verified_at": "2026-06-29T02:59:27.748523Z"
  }
}
```

**Creator-level credential (`verified_human: true`) and content-level
attribution (`likely_ai`) coexist.** This is the central design guarantee.

## 8. Analytics picks up the credential metrics

`GET /analytics` (excerpt):

```json
{
  "total_submissions": 3,
  "attribution_counts": { "likely_ai": 1, "uncertain": 2, "likely_human": 0 },
  "verified_creators": 1,
  "submissions_from_verified_creators": 2,
  "submissions_from_verified_creators_pct": 0.6667
}
```

---

## Audit trail

Every verification attempt is logged with `event_type: "verification"`
(`verification_result` granted/rejected, `ai_probability`, `word_count`,
`reason`), alongside the `submission` and `appeal` events — so the credential
trail is fully auditable.

## Note on calibration / non-determinism

`VERIFY_MAX_AI_PROBABILITY = 0.30` is a deliberately strict bar: it is safer to
**under-grant** a "verified human" badge than to over-grant one. Because Groq is
mildly non-deterministic even at temperature 0, a *thoughtful/formal* human
passage that sits near the boundary can score ~0.30–0.35 and be rejected on some
runs; a clearly casual passage (as above) scores well under the bar and passes
reliably. This is the same false-positive-averse philosophy as the core
detector, applied to credential issuance.
