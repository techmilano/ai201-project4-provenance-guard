# Stretch Feature 1 — Analytics Dashboard — Verification

Read-only analytics derived entirely from the existing audit log
(`logs/audit.jsonl`). No new storage; existing scoring, appeals, and rate
limiting are unchanged.

## New / changed files

| File | Change |
|---|---|
| `analytics.py` | **New** — `compute(entries)` (pure aggregation) + `render_dashboard(metrics)` (dependency-free HTML) |
| `auditor.py` | Added public `read_all()` |
| `app.py` | New routes `GET /analytics` (JSON) and `GET /dashboard` (HTML); neither rate limited |

## Endpoints

| Method | Path | Returns |
|---|---|---|
| GET | `/analytics` | JSON metrics (schema below) |
| GET | `/dashboard` | HTML view (CSS bar charts) rendering the same metrics |

Both call the same `compute()` so the JSON and HTML can never disagree.

## `/analytics` JSON schema

```json
{
  "total_submissions": int,
  "total_appeals": int,
  "appeal_rate": float,
  "attribution_counts": { "likely_ai": int, "uncertain": int, "likely_human": int },
  "average_confidence": float | null,
  "average_llm_ai_probability": float | null,
  "average_stylometric_ai_probability": float | null,
  "most_common_attribution": string | null,
  "rate_limit": "10 per minute; 100 per day"
}
```

- Submission metrics count only `event_type == "submission"`.
- Appeal metrics count only `event_type == "appeal"`.
- Averages round to 4 dp.
- `most_common_attribution` ties resolve deterministically in the order
  `likely_ai` → `uncertain` → `likely_human`.

## Unit tests for `compute()` (deterministic, no API)

### Empty log → zeros and nulls

```json
{
  "total_submissions": 0,
  "total_appeals": 0,
  "appeal_rate": 0.0,
  "attribution_counts": { "likely_ai": 0, "uncertain": 0, "likely_human": 0 },
  "average_confidence": null,
  "average_llm_ai_probability": null,
  "average_stylometric_ai_probability": null,
  "most_common_attribution": null,
  "rate_limit": "10 per minute; 100 per day"
}
```

### Populated log (4 submissions: 2 human, 1 ai, 1 uncertain; 1 appeal)

```json
{
  "total_submissions": 4,
  "total_appeals": 1,
  "appeal_rate": 0.25,
  "attribution_counts": { "likely_ai": 1, "uncertain": 1, "likely_human": 2 },
  "average_confidence": 0.4225,
  "average_llm_ai_probability": 0.5,
  "average_stylometric_ai_probability": 0.3275,
  "most_common_attribution": "likely_human",
  "rate_limit": "10 per minute; 100 per day"
}
```

## Live `GET /analytics` (against the M5 sample log: 3 submissions + 1 appeal)

```json
{
  "total_submissions": 3,
  "total_appeals": 1,
  "appeal_rate": 0.3333,
  "attribution_counts": { "likely_ai": 1, "uncertain": 1, "likely_human": 1 },
  "average_confidence": 0.5047,
  "average_llm_ai_probability": 0.6,
  "average_stylometric_ai_probability": 0.3619,
  "most_common_attribution": "likely_ai",
  "rate_limit": "10 per minute; 100 per day"
}
```

## Live `GET /dashboard`

```text
status 200 | content-type: text/html; charset=utf-8 | ~2.9 KB
contains: <!doctype html>, "Detection patterns", "Average scores", link to /analytics
dashboard x15 -> 15/15 200   (not rate limited)
analytics x15 -> 15/15 200   (not rate limited)
```

The HTML page shows: summary cards (submissions, appeals, appeal rate, most
common attribution), a bar chart of attribution counts (red/amber/green), and
bar gauges for the three average scores on a 0 = human / 1 = AI scale, with a
link to the raw JSON.

## How to reproduce

```bash
.venv/bin/python app.py
curl -s localhost:5000/analytics | python -m json.tool
# open the dashboard in a browser:
xdg-open http://localhost:5000/dashboard   # or just visit the URL
```
