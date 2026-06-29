# Provenance Guard

A Flask API backend that classifies submitted text as **likely AI-generated**,
**likely human-written**, or **uncertain** — built for a creative-writing
platform that wants to provide attribution transparency without unfairly
punishing creators.

Provenance Guard combines two independent detection signals into a single
confidence score, turns that score into a plain-language transparency label for
readers, records every decision in a structured audit log, and lets creators
appeal a classification they believe is wrong.

> Design principle: on a creative platform, **falsely accusing a human of using
> AI is the worst outcome.** Every scoring and threshold decision in this system
> is deliberately *false-positive averse* — when unsure, it says "uncertain" and
> points the creator to the appeal path rather than making an accusation.

---

## 1. Project Overview

Perfect AI detection is an unsolved problem, so Provenance Guard is built to
**communicate uncertainty honestly** rather than force a binary verdict. It:

- accepts text through a `POST /submit` endpoint,
- scores it with a Groq LLM signal (semantic) **and** a stylometric signal
  (structural),
- combines them into a calibrated confidence score,
- maps the score to one of three transparency labels,
- logs the decision to an append-only JSON Lines audit log, and
- supports an appeals workflow that moves contested content to `under_review`.

The architecture and design decisions are specified in
[planning.md](planning.md), which was written before any implementation code.

---

## 2. Architecture Overview

### Submission path

```
Client
  | POST /submit { text, creator_id }
  v
Flask API ── validate request ── generate content_id (uuid)
  v
Detection signals (run on the same text)
  ├─ Signal 1: Groq LLM classification   -> ai_probability 0.0–1.0
  └─ Signal 2: Stylometric heuristics     -> ai_probability 0.0–1.0
  v
Confidence scoring  ── combined = 0.6*llm + 0.4*stylometric
  v                    (+ false-positive-averse overrides)
Attribution + transparency label  ── likely_ai / uncertain / likely_human
  v
Audit log (logs/audit.jsonl)  ── structured submission entry
  v
JSON response { content_id, attribution, confidence, label, signals, notes }
```

A submission is validated and assigned a unique `content_id`. The text is scored
by both signals; their `ai_probability` outputs are combined into one confidence
score, which is mapped to an attribution category and a reader-facing label. The
decision is appended to the audit log and returned as JSON.

### Appeal path

```
Client (creator)
  | POST /appeal { content_id, creator_id, creator_reasoning }
  v
Flask API ── validate fields
  v
Look up original submission in the audit log (by content_id)
  ├─ not found            -> 404
  ├─ creator_id mismatch  -> 403
  v
Append appeal entry  ── status: under_review, original decision preserved
  v
JSON response { content_id, status: "under_review", message }

Reviewer ── GET /appeals ── queue of under_review items with original decision
```

An appeal is validated against the stored submission (the `content_id` must
exist and the `creator_id` must match the original submitter). A valid appeal
appends an appeal entry that flips the content's status to `under_review` and
preserves the original decision. No automated re-classification occurs — a human
reviewer inspects the queue via `GET /appeals`.

---

## 3. API Endpoints

| Method | Path | Rate limited | Description |
|---|---|---|---|
| GET | `/health` | no | Liveness check. Returns `{"status": "ok"}`. |
| POST | `/submit` | **yes** | Classify text. Body: `{ text, creator_id }`. Returns content_id, attribution, confidence, label, per-signal detail, and scoring notes. |
| POST | `/appeal` | no | Contest a classification. Body: `{ content_id, creator_id, creator_reasoning }`. Flips status to `under_review`. |
| GET | `/log` | no | Most recent audit-log entries (newest first) as `{ "entries": [...] }`. |
| GET | `/appeals` | no | Reviewer queue of `under_review` items as `{ "entries": [...] }`. |
| GET | `/analytics` | no | Aggregated metrics as JSON (stretch feature — see below). |
| GET | `/dashboard` | no | HTML analytics view (stretch feature — see below). |

`GET /log`, `GET /appeals`, `GET /analytics`, and `GET /dashboard` exist for
documentation and grading visibility; in a real deployment they would require
authentication.

---

## 4. Detection Signals

The system uses **two genuinely independent signals** — one semantic, one
structural — so their combination is more informative than either alone. Both
emit a normalized `ai_probability` in `[0.0, 1.0]` (1.0 = strongly reads as AI).

### Signal 1 — Groq LLM classification (semantic / holistic)

- **File:** [detector.py](detector.py) · model `llama-3.3-70b-versatile`
- **What it measures:** whether the text *reads* as AI- or human-authored,
  judged holistically — semantic coherence, register consistency, templated
  phrasing, and the over-smooth tone characteristic of model output. This is the
  **LLM-as-judge** pattern: a single Groq chat completion, no tools, no history,
  parsed and validated in code.
- **Why chosen:** AI text tends to be globally coherent and evenly hedged; human
  writing carries idiosyncratic voice and asymmetric emphasis. An LLM captures
  this holistic read better than any hand-coded rule.
- **What it misses:** lightly human-edited AI output reads coherent and natural,
  so the LLM under-flags it. It is also a non-deterministic external dependency
  (latency, rate limits, outages) — see *Known Limitations*.
- **Fail-closed:** if the response can't be parsed, the signal returns a neutral
  `0.5` with status `unavailable` instead of inventing a verdict, so a bad
  response can never push a human creator toward `likely_ai`.

### Signal 2 — Stylometric heuristics (structural / statistical)

- **File:** [stylometric.py](stylometric.py) · pure Python, no API
- **What it measures:** structural regularity of the prose via three metrics,
  each normalized to a `[0,1]` "AI-ness" contribution and averaged:
  - **Sentence-length variance** — AI text is more uniform; human text varies more.
  - **Type-token ratio (vocabulary diversity)** — AI reuses a narrower vocabulary.
  - **Clause-punctuation density** (commas/semicolons/colons per sentence) — AI
    tends to be evenly, heavily punctuated.
- **Why chosen:** it is fully independent of the LLM (no shared failure mode, no
  API), and it captures a *different* property — statistical regularity rather
  than meaning. It also serves as a fallback when the LLM is unavailable.
- **What it misses:** a deliberately uniform human writer (formal academic,
  non-native English speaker, technical documentation) scores AI-like; very
  short texts produce unstable metrics. Type-token ratio is length-confounded
  and is neutralized below ~100 words (see *Spec Reflection*).

---

## 5. Confidence Scoring

Scoring logic lives in [scoring.py](scoring.py).

### Combination

```
combined = 0.6 * llm_ai_probability + 0.4 * stylometric_ai_probability
```

The LLM is weighted higher because the holistic semantic read is the stronger
single indicator; the stylometric signal is an independent corroborator and a
fallback. The returned `confidence` field **is** this combined `ai_probability`.

### Thresholds

| Combined score | Attribution | Label |
|---|---|---|
| `>= 0.70` | `likely_ai` | High-confidence AI |
| `0.25 < score < 0.70` | `uncertain` | Uncertain |
| `<= 0.25` | `likely_human` | High-confidence human |

A score of `0.6` means "leans AI but below the bar" → **uncertain**, *not* an
accusation. The uncertain band is intentionally wide.

Note: `confidence` is the system's estimated AI probability, not confidence in
the final label. For example, a `likely_human` result should have a low
confidence value because the score measures AI-likelihood.

### False-positive-averse overrides

These rules can only ever move a verdict *toward* `uncertain`, never toward
`likely_ai`:

- **Signal disagreement:** if `|llm − stylometric| > 0.5`, the signals
  fundamentally conflict → forced `uncertain`, so one confident-but-wrong signal
  can't dominate.
- **Short / insufficient text:** below ~40 words the stylometric signal is
  unstable → forced `uncertain`.
- **Single-signal mode:** if one signal is unavailable, the result can never
  reach `likely_ai` (we don't accuse on one signal alone).

### Example submissions (noticeably different scores)

From the Milestone 4/5 calibration runs
([sample_outputs/milestone4_verification.md](sample_outputs/milestone4_verification.md)):

| Input | LLM | Stylometric | Combined | Attribution |
|---|---|---|---|---|
| Casual human ("ok so i finally tried that new ramen place…") | 0.10 | 0.20 | **0.14** | `likely_human` |
| Heavy AI ("In today's rapidly evolving digital landscape…") | 0.90 | 0.56 | **0.76** | `likely_ai` |

The two cases differ by ~0.62 in combined confidence, confirming the score
produces meaningful variation rather than a constant.

---

## 6. Transparency Label

The label is shown to a reader and must be meaningful to a non-technical
audience. The **exact verbatim text** of all three variants:

| Attribution | Verbatim label text |
|---|---|
| `likely_ai` | `⚠️ Likely AI-generated. Our analysis found strong signals that this text was produced by an AI system.` |
| `likely_human` | `✓ Likely human-written. Our analysis found no strong signals of AI generation.` |
| `uncertain` | `❓ Origin uncertain. Our analysis was inconclusive — we can't confidently attribute this text to a human or an AI. The creator can appeal this result.` |

The `uncertain` label explicitly names the appeal path, reinforcing the
false-positive asymmetry: when unsure, the system declines to accuse and points
the creator to recourse.

---

## 7. Appeals Workflow

Implemented in [app.py](app.py) (`/appeal`) and [auditor.py](auditor.py).

- **Who can appeal:** the original submitter. The appeal's `creator_id` must
  match the `creator_id` stored on the original submission. Any classification
  can be appealed, including `uncertain`.
- **Validation:** `content_id`, `creator_id`, and `creator_reasoning` are all
  required and non-empty (missing → `400`).
- **Lookup:** the `content_id` is looked up in the audit log
  (not found → `404`).
- **Ownership:** a mismatched `creator_id` returns **`403`**.
- **Status update:** a valid appeal appends an appeal entry with status
  `under_review`.
- **Original decision preserved:** the appeal entry stores the original
  attribution, confidence, label, both signal scores, and original timestamp, so
  a reviewer sees the full context.
- **Reviewer queue:** `GET /appeals` returns all `under_review` items (latest
  appeal per `content_id`), newest first.

Validation evidence
([sample_outputs/milestone5_verification.md](sample_outputs/milestone5_verification.md)):

```text
MISSING reasoning -> 400
BAD content_id    -> 404
WRONG creator     -> 403
VALID APPEAL      -> 200  {"content_id": "...", "status": "under_review",
                           "message": "Appeal received. Content is now under review."}
```

---

## 8. Rate Limiting

Implemented with Flask-Limiter (`storage_uri="memory://"`), applied **only to
`POST /submit`**:

```
10 per minute; 100 per day
```

`/health`, `/log`, `/appeal`, and `/appeals` are **not** rate limited.

**Reasoning.** On a writing platform a genuine creator submits their own work
occasionally — a handful of pieces in a session, rarely more than a few dozen in
a day. `10/minute` comfortably covers real human use (including re-submitting
edits) while stopping a script from flooding the (paid, latency-bound) Groq
endpoint. `100/day` is a backstop against sustained low-rate abuse that stays
under the per-minute cap. The two read/queue endpoints are unmetered because
they are cheap, local, and don't call any external API.

**Evidence** — 12 rapid submissions (Groq stubbed so the burst makes no real API
calls):

```text
submit status codes (12 rapid): [200,200,200,200,200,200,200,200,200,200,429,429]
200s: 10 | 429s: 2
13th submit body: {"error": "Rate limit exceeded: 10 per 1 minute"}
health  x15 -> 15/15 200   (not rate limited)
appeals x15 -> 15/15 200   (not rate limited)
```

---

## 9. Audit Log

Every decision is appended to **`logs/audit.jsonl`** — one JSON object per line
(JSON Lines), append-only. Timestamps are UTC ISO 8601. Recording both
individual signal scores and statuses is what makes a degraded or miscalibrated
decision diagnosable after the fact. Full samples are in
[sample_outputs/milestone5_verification.md](sample_outputs/milestone5_verification.md).

**Submission entry fields:**

| Field | Description |
|---|---|
| `timestamp` | UTC ISO 8601 |
| `event_type` | `"submission"` |
| `content_id` | uuid for this submission |
| `creator_id` | submitter id |
| `attribution` | `likely_ai` / `uncertain` / `likely_human` |
| `confidence` | combined ai_probability |
| `label` | verbatim transparency label shown |
| `llm_ai_probability` | Signal 1 score |
| `llm_status` | `available` / `unavailable` |
| `stylometric_ai_probability` | Signal 2 score |
| `stylometric_status` | `available` / `insufficient_text` |
| `notes` | scoring overrides that fired (may be empty) |
| `status` | `"classified"` |

**Appeal entry fields:**

| Field | Description |
|---|---|
| `timestamp` | appeal time (UTC ISO 8601) |
| `event_type` | `"appeal"` |
| `content_id` | id of the appealed content |
| `creator_id` | appealing creator (matched to original) |
| `creator_reasoning` | the creator's explanation |
| `status` | `"under_review"` |
| `original_attribution`, `original_confidence`, `original_label`, `original_llm_ai_probability`, `original_stylometric_ai_probability`, `original_timestamp` | the preserved original decision |

Example log (3 submissions covering all three categories + 1 appeal):

```json
{"event_type":"submission","attribution":"likely_human","confidence":0.1384,"llm_ai_probability":0.1,"stylometric_ai_probability":0.1961,"status":"classified", ...}
{"event_type":"submission","attribution":"likely_ai","confidence":0.7625,"llm_ai_probability":0.9,"stylometric_ai_probability":0.5563,"status":"classified", ...}
{"event_type":"submission","attribution":"uncertain","confidence":0.6133,"llm_ai_probability":0.8,"stylometric_ai_probability":0.3333,"status":"classified", ...}
{"event_type":"appeal","content_id":"5b1bebe3...","creator_reasoning":"This is my own writing...","status":"under_review","original_attribution":"likely_ai","original_confidence":0.7625, ...}
```

---

## 10. Known Limitations

Detection is intentionally honest about uncertainty. Specific content this
system handles poorly:

- **Short poetry / repetitive writing.** A minimalist poem with heavy repetition
  and simple vocabulary produces low type-token ratio and low sentence-length
  variance — the stylometric signal reads this as AI-like uniformity and may
  false-flag a human poet. Mitigations: the LLM usually recognizes creative
  voice, the wide uncertain band, and the appeal path.
- **Formal or non-native-English human writing.** Uniform, formal, low-variance
  prose can lean AI on *both* signals. The false-positive-averse thresholds push
  these toward `uncertain` rather than `likely_ai`, and the label names the
  appeal route — but this is the system's hardest case.
- **LLM non-determinism near the threshold.** Groq is mildly non-deterministic
  even at temperature 0, so an input sitting right on the `0.70` boundary (e.g.
  a borderline formal essay the model scores 0.8–0.9) can flip between
  `uncertain` and `likely_ai` between runs. Unambiguous cases are stable.
- **Groq API dependency.** Signal 1 is an external service. On failure the
  pipeline degrades to stylometric-only and caps the result so it can never
  reach `likely_ai` on a single signal, recording `llm_status: "unavailable"` in
  the audit log — but detection quality is reduced while Groq is down.

---

## 11. Spec Reflection

**How [planning.md](planning.md) helped.** Writing the spec first forced the
hard decisions — the two signals and their blind spots, the combination weights,
the threshold bands, the three label strings, and the full appeal flow — *before*
any code existed. Each implementation milestone (M3–M5) then consumed a specific
section of the spec, so the code had a concrete contract to implement against
rather than being improvised.

**Where the implementation diverged.**

- **AI_THRESHOLD lowered `0.85 → 0.70`.** The spec's original `0.85` bar proved
  practically unreachable during Milestone 4 testing: clear AI examples scored
  only ~`0.71–0.76` combined (the LLM rarely exceeds ~0.9 and the stylometric
  signal often disagrees on AI prose). At `0.85` the system would only ever emit
  `uncertain` or `likely_human`. Lowering to `0.70` makes all three labels
  reachable while staying false-positive averse — no human/borderline-human
  input in the calibration set is misclassified. planning.md was updated with a
  calibration note.
- **Type-token ratio neutralized below ~100 words.** TTR is length-confounded —
  below ~100 words almost every word is unique, so AI and human text both score
  ~0.88 and the metric discriminates nothing. It is now neutralized (0.5) for
  short inputs instead of saturating and skewing the stylometric average.

---

## 12. AI Usage

This project was implemented with **Claude Code** (Claude Opus), milestone by
milestone, with the spec as the source of truth. Specific instances:

- **Flask structure.** Directed Claude Code to generate the Flask app skeleton,
  config module, and route layout from the planning.md architecture section.
- **Groq signal.** Directed it to implement the LLM-as-judge detector
  ([detector.py](detector.py)) returning structured `{ai_probability, reasoning,
  status}` with a fail-closed fallback.
- **Stylometric + scoring.** Directed it to implement the three stylometric
  metrics ([stylometric.py](stylometric.py)) and the combination/override logic
  ([scoring.py](scoring.py)) against the spec's weights and thresholds.
- **Appeals + rate limiting.** Directed it to implement `POST /appeal`,
  `GET /appeals`, and Flask-Limiter on `/submit` only.
- **What I reviewed / overrode instead of accepting blindly.** During M4
  calibration the live scores didn't match intuition, so I had it diagnose the
  signals rather than ship as-is — that surfaced the unreachable `0.85`
  threshold and the length-confounded TTR. I made the calibration call (lower to
  `0.70`, neutralize TTR) and had the spec and code updated to match, rather than
  accepting the initial output. Every milestone was tested and verified before
  moving on.

---

## 13. How to Run

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate          # Mac/Linux
# .venv\Scripts\activate           # Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create a .env file with your Groq API key (never commit it)
echo "GROQ_API_KEY=your_key_here" > .env

# 4. Run the app
python app.py                      # serves on http://localhost:5000
```

### Curl examples

```bash
# health
curl -s localhost:5000/health | python -m json.tool

# submit  (note the content_id in the response)
curl -s -X POST localhost:5000/submit \
  -H "Content-Type: application/json" \
  -d '{"text": "The sun dipped below the horizon, painting the sky in hues of amber and rose. I sat on the porch, coffee in hand, watching the neighborhood slowly go quiet.", "creator_id": "alice"}' \
  | python -m json.tool

# appeal  (use a content_id from a previous /submit response)
curl -s -X POST localhost:5000/appeal \
  -H "Content-Type: application/json" \
  -d '{"content_id": "PASTE-CONTENT-ID", "creator_id": "alice", "creator_reasoning": "I wrote this myself from personal experience."}' \
  | python -m json.tool

# audit log (newest first)
curl -s localhost:5000/log | python -m json.tool

# reviewer queue (under_review items)
curl -s localhost:5000/appeals | python -m json.tool

# rate limit demo (expect 200 x10 then 429 x2)
for i in $(seq 1 12); do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:5000/submit \
    -H "Content-Type: application/json" \
    -d '{"text": "rate limit test submission with enough words to pass validation", "creator_id": "rl"}'
done
```

---

## 14. Portfolio Walkthrough

A short (~2 minute) video tour of the system. It shows:

- A `POST /submit` for clearly human text → `likely_human` with a low confidence
  score and the human-written label.
- A `POST /submit` for clearly AI text → `likely_ai` with a high confidence
  score and the AI-generated label.
- The per-signal breakdown (LLM vs stylometric) and how they combine.
- Filing a `POST /appeal` and the content moving to `under_review`, then viewing
  it in the `GET /appeals` reviewer queue.
- The `GET /log` audit trail showing submission and appeal entries.
- The rate-limit demo: 12 rapid submissions returning ten `200`s then two `429`s.
- A quick note on the key design decision — false-positive aversion and why the
  threshold was calibrated to `0.70`.

---

## Stretch Feature: Analytics Dashboard

A read-only operator view summarizing what the system has been doing. It is
derived **entirely from the existing audit log** (`logs/audit.jsonl`) — it adds
no new storage and cannot change a classification, so it is fully additive to the
core system. Implemented in [analytics.py](analytics.py): a pure `compute()`
function does the aggregation and both endpoints share it, so the JSON and HTML
views can never disagree.

**`GET /analytics`** returns the metrics as JSON:

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

**`GET /dashboard`** renders the same numbers as a dependency-free HTML page
(no JavaScript, no chart library): summary cards, a bar chart of attribution
counts, and bar gauges for the three average scores on a 0 = human / 1 = AI
scale, with a link to the raw JSON.

What it shows:

- **Detection patterns** — how many submissions fell into each attribution
  category (`likely_ai` / `uncertain` / `likely_human`).
- **Appeal rate** — `total_appeals / total_submissions`, surfacing how often
  creators contest a classification.
- **Average scores** (the additional metric) — the mean combined confidence and
  the mean of each individual signal. Because confidence is AI-likelihood, a
  healthy system shows low averages when human content dominates; a drift upward
  is an early warning of miscalibration. The mean per-signal scores also reveal
  whether the LLM and stylometric signals are pulling in the same direction.

Submission metrics count only `event_type == "submission"` and appeal metrics
only `event_type == "appeal"`. With an empty log, counts are `0`, averages and
`most_common_attribution` are `null`, and there is no division by zero. Neither
endpoint is rate limited. See
[sample_outputs/stretch_analytics_verification.md](sample_outputs/stretch_analytics_verification.md)
for full example output.

---

## Repository Layout

```
app.py           # Flask app: routes, orchestration, rate limiting
config.py        # constants: model, log path, weights, thresholds, labels
detector.py      # Signal 1 — Groq LLM classification
stylometric.py   # Signal 2 — stylometric heuristics
scoring.py       # combine signals -> confidence -> attribution
auditor.py       # structured .jsonl audit log: submissions + appeals
analytics.py     # stretch feature — analytics dashboard (/analytics, /dashboard)
logs/            # audit.jsonl (gitignored)
planning.md      # the pre-implementation spec (source of truth)
sample_outputs/  # per-milestone + stretch verification records
requirements.txt
```
