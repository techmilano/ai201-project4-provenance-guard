# Milestone 5 — Verification

Production layer: appeals workflow, reviewer queue, rate limiting, and complete
audit log.

## New / changed

| File | Change |
|---|---|
| `app.py` | Flask-Limiter (`memory://`) on `POST /submit` only; new `POST /appeal` + `GET /appeals`; `label` now logged; JSON 429 handler |
| `auditor.py` | `find_submission()`, `log_appeal()`, `read_appeals()`; submission entries now include `label` |
| `config.py` | `RATE_LIMIT = "10 per minute;100 per day"` (already present) used by limiter |

## Endpoints

| Method | Path | Rate limited | Purpose |
|---|---|---|---|
| GET | `/health` | no | liveness |
| POST | `/submit` | **yes** (10/min;100/day) | classify + log |
| GET | `/log` | no | recent audit entries |
| POST | `/appeal` | no | contest a classification |
| GET | `/appeals` | no | reviewer queue (under_review) |

## Appeals workflow — verification

Request body requires `content_id`, `creator_id`, `creator_reasoning`. The
endpoint confirms the `content_id` exists and the `creator_id` matches the
original submission, then appends an appeal entry (status `under_review`) that
preserves the original decision.

```text
MISSING reasoning -> 400
BAD content_id    -> 404
WRONG creator     -> 403
VALID APPEAL      -> 200  {"content_id": "...", "status": "under_review",
                           "message": "Appeal received. Content is now under review."}
```

## Rate limiting — verification

12 rapid `POST /submit` requests (Groq stubbed so the burst makes no real API
calls):

```text
submit status codes (12 rapid): [200,200,200,200,200,200,200,200,200,200,429,429]
200s: 10 | 429s: 2
13th submit body: {"error": "Rate limit exceeded: 10 per 1 minute"}
health  x15 -> 15/15 200   (not rate limited)
appeals x15 -> 15/15 200   (not rate limited)
```

## Complete audit log — sample (`logs/audit.jsonl`)

3 submissions (one per attribution category) + 1 appeal. Submission entries
include `label`; the appeal entry preserves the original decision.

```json
{"timestamp":"2026-06-29T00:40:37.102078Z","event_type":"submission","content_id":"eb7d9f41...","creator_id":"casual_human","attribution":"likely_human","confidence":0.1384,"label":"✓ Likely human-written. Our analysis found no strong signals of AI generation.","llm_ai_probability":0.1,"llm_status":"available","stylometric_ai_probability":0.1961,"stylometric_status":"available","notes":[],"status":"classified"}
{"timestamp":"2026-06-29T00:40:37.362751Z","event_type":"submission","content_id":"5b1bebe3...","creator_id":"heavy_AI","attribution":"likely_ai","confidence":0.7625,"label":"⚠️ Likely AI-generated. Our analysis found strong signals that this text was produced by an AI system.","llm_ai_probability":0.9,"llm_status":"available","stylometric_ai_probability":0.5563,"stylometric_status":"available","notes":[],"status":"classified"}
{"timestamp":"2026-06-29T00:40:37.676485Z","event_type":"submission","content_id":"e25128c5...","creator_id":"formal_human","attribution":"uncertain","confidence":0.6133,"label":"❓ Origin uncertain. Our analysis was inconclusive — we can't confidently attribute this text to a human or an AI. The creator can appeal this result.","llm_ai_probability":0.8,"llm_status":"available","stylometric_ai_probability":0.3333,"stylometric_status":"available","notes":[],"status":"classified"}
{"timestamp":"2026-06-29T00:40:37.678239Z","event_type":"appeal","content_id":"5b1bebe3...","creator_id":"heavy_AI","creator_reasoning":"This is my own writing; I just write in a formal corporate style.","status":"under_review","original_attribution":"likely_ai","original_confidence":0.7625,"original_label":"⚠️ Likely AI-generated...","original_llm_ai_probability":0.9,"original_stylometric_ai_probability":0.5563,"original_timestamp":"2026-06-29T00:40:37.362751Z"}
```

## GET /appeals — reviewer queue (one entry shown)

```json
{
  "entries": [
    {
      "content_id": "5b1bebe3-08fc-4992-a471-073e8052e51c",
      "creator_id": "heavy_AI",
      "creator_reasoning": "This is my own writing; I just write in a formal corporate style.",
      "event_type": "appeal",
      "original_attribution": "likely_ai",
      "original_confidence": 0.7625,
      "original_label": "⚠️ Likely AI-generated. Our analysis found strong signals that this text was produced by an AI system.",
      "original_llm_ai_probability": 0.9,
      "original_stylometric_ai_probability": 0.5563,
      "original_timestamp": "2026-06-29T00:40:37.362751Z",
      "status": "under_review",
      "timestamp": "2026-06-29T00:40:37.678239Z"
    }
  ]
}
```

## How to reproduce live

```bash
.venv/bin/python app.py    # http://localhost:5000

# submit -> note the content_id
curl -s -X POST localhost:5000/submit -H "Content-Type: application/json" \
  -d '{"text":"...", "creator_id":"alice"}' | python -m json.tool

# appeal it
curl -s -X POST localhost:5000/appeal -H "Content-Type: application/json" \
  -d '{"content_id":"<id>", "creator_id":"alice", "creator_reasoning":"I wrote this."}' | python -m json.tool

# reviewer queue + full log
curl -s localhost:5000/appeals | python -m json.tool
curl -s localhost:5000/log     | python -m json.tool

# rate limit (expect 200 x10 then 429)
for i in $(seq 1 12); do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:5000/submit \
    -H "Content-Type: application/json" \
    -d '{"text":"rate limit test submission with enough words here","creator_id":"rl"}'
done
```
