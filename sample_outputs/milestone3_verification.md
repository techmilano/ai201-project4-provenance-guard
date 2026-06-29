# Milestone 3 — Verification

Submission endpoint + first detection signal (Groq LLM) + structured audit log.

## Files

| File | Purpose |
|---|---|
| `app.py` | Flask app: `GET /health`, `POST /submit`, `GET /log` + attribution/label helpers |
| `config.py` | Constants — model, log path, thresholds, weights, rate limit, verbatim `LABELS` |
| `detector.py` | Signal 1: Groq LLM-as-judge, lazy client, JSON output, safe fallback |
| `auditor.py` | `.jsonl` audit writer + reader (`logs/audit.jsonl`) |
| `logs/.gitkeep` | keeps `logs/` in the repo |

## Verification results (all passing)

- `GET /health` → `200 {"status":"ok"}`
- Validation → `400` for missing text, whitespace-only text, and missing `creator_id`
- Attribution thresholds → `0.9 → likely_ai`, `0.5 → uncertain`, `0.1 → likely_human`
- Live `POST /submit` → `200`, Groq returned `ai_probability 0.2` (`status: available`)
- `GET /log` → `{entries:[...]}`, newest-first, all 9 required fields present
- Fallback path: any Groq error returns `0.5 / "unavailable"` without crashing the API

## Sample outputs

### `GET /health`

```json
{ "status": "ok" }
```

### Validation (`POST /submit`)

```text
NO_TEXT     400 {"error": "Field 'text' is required and cannot be empty."}
WS_TEXT     400 {"error": "Field 'text' is required and cannot be empty."}
NO_CREATOR  400 {"error": "Field 'creator_id' is required."}
```

### Live `POST /submit`

Request:

```json
{
  "text": "The sun dipped below the horizon, painting the sky in hues of amber and rose. I sat on the porch, coffee in hand, watching the neighborhood slowly go quiet.",
  "creator_id": "test-user-1"
}
```

Response (`200`):

```json
{
  "attribution": "likely_human",
  "confidence": 0.2,
  "content_id": "662a237f-298f-4567-84b4-4ac04288ec46",
  "label": "✓ Likely human-written. Our analysis found no strong signals of AI generation.",
  "signals": {
    "llm": {
      "ai_probability": 0.2,
      "reasoning": "The text has a poetic tone but lacks overly templated phrasing and maintains a human-like descriptive style.",
      "status": "available"
    }
  }
}
```

### Audit log entry (`logs/audit.jsonl`, surfaced via `GET /log`)

```json
{
  "timestamp": "2026-06-28T23:55:16.496249Z",
  "event_type": "submission",
  "content_id": "662a237f-298f-4567-84b4-4ac04288ec46",
  "creator_id": "test-user-1",
  "attribution": "likely_human",
  "confidence": 0.2,
  "llm_ai_probability": 0.2,
  "llm_status": "available",
  "status": "classified"
}
```

## How to reproduce

```bash
.venv/bin/python app.py    # serves on http://localhost:5000

curl -s -X POST http://localhost:5000/submit \
  -H "Content-Type: application/json" \
  -d '{"text": "The sun dipped below the horizon...", "creator_id": "test-user-1"}' \
  | python -m json.tool

curl -s http://localhost:5000/log | python -m json.tool
```

## Not in M3 (later milestones)

Stylometric signal + score combination (M4); appeals, `GET /appeals`, rate limiting (M5).
The transparency-label-by-confidence path is wired but currently driven by the single Groq score.
