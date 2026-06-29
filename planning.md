# Provenance Guard Planning

## Project Overview

Provenance Guard is a Flask API backend that classifies submitted text content as likely AI-generated, likely human-written, or uncertain. The system is designed for a creative writing platform that wants to provide attribution transparency without unfairly punishing creators.

The system uses two detection signals: a Groq LLM classification signal and a stylometric heuristic signal. The result is converted into a confidence score, a reader-facing transparency label, and a structured audit-log entry. Creators can appeal classifications, and appealed content is marked as under review.

## Architecture

### Submission Flow

```text
Client
  |
  | POST /submit
  | { text, creator_id }
  v
Flask API
  |
  | validate request + generate content_id
  v
Detection Pipeline
  |
  |--> Signal 1: Groq LLM classification
  |       output: ai_probability score from 0.0 to 1.0
  |
  |--> Signal 2: Stylometric heuristics
          output: ai_probability score from 0.0 to 1.0
  |
  v
Confidence Scoring
  |
  | weighted combined score
  v
Transparency Label Generator
  |
  | label text + attribution category
  v
Audit Log
  |
  | structured decision entry
  v
JSON Response
```

### Appeal Flow

```text
Client (creator)
  |
  | POST /appeal
  | { content_id, creator_id, creator_reasoning }
  v
Flask API
  |
  | validate: content_id exists + belongs to creator
  v
Status Update
  |
  | content status: classified -> under_review
  v
Audit Log
  |
  | append appeal entry linked to original decision
  | (original scores preserved, appeal_reasoning added)
  v
JSON Response
  |
  | { content_id, status: "under_review", message }
  v
Reviewer Queue (GET /appeals)
  | surfaces under_review items with original text,
  | scores, label, and creator_reasoning
```

### Narrative

A submission enters through `POST /submit`, is validated and assigned a `content_id`, then flows through both detection signals in parallel; their `ai_probability` scores are combined into a single weighted confidence score, mapped to an attribution category and a reader-facing transparency label, written to the audit log, and returned as JSON. An appeal enters through `POST /appeal`, is validated against the stored submission (the `content_id` exists and the `creator_id` matches the original submitter), flips that content's status to `under_review`, appends an appeal entry to the same audit log alongside the original decision, and returns a confirmation — no automated re-classification occurs; a human reviewer inspects the queue via `GET /appeals`.

## API Surface

| Method | Path | Accepts | Returns |
|---|---|---|---|
| POST | `/submit` | `{ text, creator_id }` | `{ content_id, attribution, confidence, label, signals }` |
| POST | `/appeal` | `{ content_id, creator_id, creator_reasoning }` | `{ content_id, status, message }` |
| GET | `/log` | — | `{ entries: [...] }` (most recent audit entries) |
| GET | `/appeals` | — | `{ entries: [...] }` (items with status `under_review`) |
| GET | `/analytics` | — | `{ ... }` aggregated metrics (stretch feature 1) |
| GET | `/dashboard` | — | HTML view rendering the analytics (stretch feature 1) |

Rate limiting (`10 per minute; 100 per day`) is applied to `POST /submit`. `GET /log`, `GET /appeals`, `GET /analytics`, and `GET /dashboard` exist for grading/documentation visibility; in production they would require auth.

## Module Structure

Following the file-per-concern layout of the Lab 4 (RepairSafe) starter — one module per pipeline stage, plus a central `config.py` for constants — so each piece can be built and tested in isolation (the M3→M4→M5 sequencing).

```text
ai201-project4-provenance-guard/
├── app.py                  # Flask app: routes, orchestration, Flask-Limiter
├── config.py               # constants (API key, model, weights, thresholds, paths)
├── signal_llm.py           # Signal 1: Groq LLM-as-judge classifier
├── signal_stylometric.py   # Signal 2: pure-Python stylometric heuristics
├── scoring.py              # combine signals -> confidence -> attribution category
├── labels.py               # attribution category -> transparency label text
├── auditor.py              # structured .jsonl audit log writer + reader
├── store.py                # content/status storage (content_id -> record)
├── analytics.py            # stretch 1: aggregate audit log -> dashboard metrics
├── logs/                   # audit.jsonl written here
├── requirements.txt
├── .env                    # GROQ_API_KEY (gitignored)
├── planning.md
└── README.md
```

`config.py` centralizes the tunable decisions so the scoring code and the AI-generated functions reference one source of truth (mirrors RepairSafe's `config.py` with `LLM_MODEL` / `VALID_TIERS`):

```python
GROQ_API_KEY   = os.getenv("GROQ_API_KEY")
LLM_MODEL      = "llama-3.3-70b-versatile"   # same model as Labs 1–3 / RepairSafe
LOG_FILE       = "logs/audit.jsonl"
LLM_WEIGHT     = 0.6
STYLO_WEIGHT   = 0.4
AI_THRESHOLD   = 0.70       # >= this -> likely_ai (lowered from 0.85 in M4; see note below)
HUMAN_THRESHOLD = 0.25      # <= this -> likely_human
DISAGREE_DELTA = 0.50       # |llm - stylo| > this -> force uncertain
MIN_WORDS      = 40         # below this, stylometry is unstable -> uncertain
VALID_ATTRIBUTIONS = {"likely_ai", "uncertain", "likely_human"}
```

## Detection Signals

The pipeline uses two **genuinely independent** signals — one semantic, one structural — so their combination is more informative than either alone. Both emit a normalized `ai_probability` in `[0.0, 1.0]` (1.0 = strongly reads as AI).

### Signal 1 — Groq LLM classification (semantic / holistic)

- **Measures:** whether the text reads as human- or AI-authored, assessed holistically — semantic coherence, register consistency, "templated" phrasing, and the over-smooth tone characteristic of model output.
- **Why it differs:** AI text tends to be globally coherent and evenly hedged; human writing carries idiosyncratic voice, asymmetric emphasis, and topical leaps.
- **Output:** the model is prompted to return a structured JSON object `{ "ai_probability": float, "reasoning": string }`; we consume `ai_probability`.
- **Pattern:** this is the **LLM-as-judge** pattern carried over from Lab 4's `classify_safety_tier()` — a single Groq chat completion, no tools, no history, with the response parsed and validated in code. Same API call and parsing approach; the difference is the output type (a continuous `ai_probability`, not a discrete tier).
- **Fail closed, not open:** if the response can't be parsed or `ai_probability` is out of range, the function does **not** invent an AI verdict. Per RepairSafe's "failing open is more dangerous than failing closed" rule — and our false-positive asymmetry — the LLM signal returns a neutral `0.5` and the pipeline records `llm_status: "parse_error"`, so an unparseable response can never push a human creator toward `likely_ai`.
- **Blind spot:** lightly human-edited AI output reads coherent and natural, so the LLM under-flags it (false human). It is also a non-deterministic external dependency (latency, rate limits, outages).

### Signal 2 — Stylometric heuristics (structural / statistical)

- **Measures:** measurable statistical regularity of the prose via three metrics:
  - **Sentence-length variance** — AI text is more uniform; human text varies more.
  - **Type-token ratio (vocabulary diversity)** — AI text often reuses a narrower vocabulary in long-form.
  - **Punctuation density** — distribution and rate of punctuation differ between hand-written and generated prose.
- **Combination into one score:** each metric is normalized to `[0,1]` against rough human/AI reference ranges, then averaged into a single `ai_probability`. (Equal weighting initially; revisit after M4 testing.)
- **Why it differs:** AI generation regresses toward statistical regularity; human writing is structurally noisier.
- **Blind spot:** a deliberately uniform human writer (formal academic, non-native English speaker, technical documentation) scores AI-like; very short texts produce unstable metrics.

### Combining the signals

```text
combined = 0.6 * llm_ai_probability + 0.4 * stylometric_ai_probability
```

The LLM is weighted higher because the holistic semantic read is the stronger single indicator; the stylometric signal acts as an independent corroborator and a fallback when the LLM is unavailable. **Disagreement rule:** if `abs(llm - stylometric) > 0.5`, the signals fundamentally conflict — the result is forced to **uncertain** regardless of the weighted average, so a confident-but-wrong single signal cannot dominate.

## Uncertainty Representation

The system never forces a binary verdict. The returned `confidence` field **is** the combined `ai_probability` (probability the text is AI-authored); the attribution category is derived from where it falls.

### Thresholds (false-positive averse)

A false positive — labeling a human's work as AI — is the worst outcome on a creative-writing platform, so the bar to declare "AI" is deliberately high and the uncertain band is wide:

| Combined score | Attribution | Category |
|---|---|---|
| `>= 0.70` | `likely_ai` | High-confidence AI |
| `0.25 < score < 0.70` | `uncertain` | Uncertain |
| `<= 0.25` | `likely_human` | High-confidence human |

Plus the disagreement rule above, which can force `uncertain` from inside either confident band.

> **Calibration note (M4).** The AI threshold started at `0.85`. During Milestone 4 testing this made `likely_ai` practically unreachable on real text: clear AI examples scored only ~`0.71–0.76` combined, because the LLM rarely returns above ~`0.9` and the stylometric signal often *disagrees* on AI prose (GPT-style writing has varied sentence lengths and rich vocabulary, so only punctuation density flags it). With the bar at `0.85` the system would only ever output `uncertain` or `likely_human`. Lowering the bar to `0.70` makes all three labels reachable while remaining false-positive averse — on the calibration set no human or borderline-human input is misclassified (borderline formal human scored `0.59` → still `uncertain`). `HUMAN_THRESHOLD` (`0.25`), the weights (`0.6/0.4`), and the disagreement rule are unchanged.

### What a given score means

- **0.95** → strong, corroborated AI signal → high-confidence AI label.
- **0.6** → leans AI but below the 0.70 bar → **uncertain** label, *not* an AI accusation. This is the design intent of hint #2: 0.5–0.6 means "we don't know," shown honestly rather than rounded into a verdict.
- **0.15** → both signals read human → high-confidence human label.

Calibration is validated empirically in M4 using the four spec-provided test inputs (clear AI, clear human, two borderline) plus printing both raw signal scores to confirm the combined score moves meaningfully across them rather than clustering.

## Transparency Label

Three variants, plain-language and confidence-meaningful for a non-technical reader. **Verbatim text:**

- **High-confidence AI** (`likely_ai`):
  > "⚠️ Likely AI-generated. Our analysis found strong signals that this text was produced by an AI system."

- **High-confidence human** (`likely_human`):
  > "✓ Likely human-written. Our analysis found no strong signals of AI generation."

- **Uncertain** (`uncertain`):
  > "❓ Origin uncertain. Our analysis was inconclusive — we can't confidently attribute this text to a human or an AI. The creator can appeal this result."

The uncertain label explicitly names the appeal path, reflecting the false-positive asymmetry: when unsure, the system declines to accuse and points the creator to recourse.

The label layer is a category→config lookup (mirroring RepairSafe's `TIER_CONFIG`), so the API can return both the verbatim text and presentation hints:

```python
LABELS = {
    "likely_ai":    {"icon": "⚠️", "text": "Likely AI-generated. Our analysis found strong signals that this text was produced by an AI system."},
    "likely_human": {"icon": "✓",  "text": "Likely human-written. Our analysis found no strong signals of AI generation."},
    "uncertain":    {"icon": "❓", "text": "Origin uncertain. Our analysis was inconclusive — we can't confidently attribute this text to a human or an AI. The creator can appeal this result."},
}
```

## Appeals Workflow

- **Who can appeal:** the creator who submitted the content (`creator_id` on the appeal must match the stored submission). Any classification can be appealed, including `uncertain`.
- **What they provide:** `content_id`, `creator_id`, and `creator_reasoning` (free-text explanation, e.g. "I wrote this myself; I'm a non-native speaker so my style reads formal"). The `creator_id` is required so the system can verify the appeal comes from the original submitter.
- **What the system does:** validates the `content_id` exists; updates that content's status from `classified` to `under_review`; appends an appeal entry to the audit log that preserves the original decision (scores, label, timestamp) and adds `appeal_reasoning` and an appeal timestamp; returns a confirmation. **No automated re-classification.**
- **What a reviewer sees** (`GET /appeals`): the queue of `under_review` items, each showing the original text, both signal scores, combined confidence, the assigned label, the creator's reasoning, and both timestamps — enough to make a manual judgment.

## Audit Log

Every attribution decision and every appeal is appended to a structured **`.jsonl`** log at `logs/audit.jsonl` — one JSON object per line, append-only. This is the exact format and approach from Lab 4's `log_interaction()` (`auditor.py`); per the RepairSafe→Project 4 connect doc, `.jsonl` fully satisfies the "structured audit log" requirement. It's trivial to append, line-parseable, and works with standard log tooling. Timestamps are UTC ISO 8601 via `datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")`.

**Submission entry** (written by every `POST /submit`):

```json
{
  "event": "classification",
  "content_id": "3f7a2b1e-...",
  "creator_id": "test-user-1",
  "timestamp": "2026-06-28T14:32:10.123Z",
  "attribution": "likely_ai",
  "confidence": 0.78,
  "llm_score": 0.81,
  "stylometric_score": 0.73,
  "llm_status": "ok",
  "status": "classified"
}
```

**Appeal entry** (appended by `POST /appeal`, preserving the original decision):

```json
{
  "event": "appeal",
  "content_id": "3f7a2b1e-...",
  "creator_id": "test-user-1",
  "timestamp": "2026-06-28T15:01:44.907Z",
  "appeal_reasoning": "I wrote this myself; I'm a non-native speaker so my style reads formal.",
  "original_attribution": "likely_ai",
  "original_confidence": 0.78,
  "status": "under_review"
}
```

Recording both individual signal scores (`llm_score`, `stylometric_score`) and `llm_status` is what makes a degraded or miscalibrated decision diagnosable after the fact — the same "error detection / accountability" rationale RepairSafe gives for its log fields.

## Anticipated Edge Cases

1. **Minimalist / repetitive poetry.** A short poem with heavy repetition and simple vocabulary produces a low type-token ratio and low sentence-length variance — the stylometric signal reads this as AI-like uniformity and false-flags a human poet. *Mitigation:* the LLM signal (weighted 0.6) usually recognizes creative voice; the 0.70 AI bar and wide uncertain band keep most such cases out of `likely_ai`; the appeal path is the backstop.

2. **Non-native-English or formal/academic human writing.** Uniform, formal, low-variance prose (the exact profile of the M5 appeal test case) leans AI on *both* signals, so the disagreement rule won't save it. *Mitigation:* false-positive-averse thresholds push borderline results to `uncertain` rather than `likely_ai`; the uncertain label names the appeal route.

3. **Groq API failure / timeout / rate limit.** Signal 1 is an external dependency that can be slow or down. *Mitigation:* on LLM failure the pipeline degrades to **stylometric-only**, caps the result so it can never reach `likely_ai` on a single signal (forces at most `uncertain`), and records `llm_status: "unavailable"` in the audit log so the degraded decision is auditable. Empty/whitespace-only or sub-minimum-length text (e.g. < 40 words) is rejected or returned as `uncertain`, since stylometry is unstable on tiny inputs.

## AI Tool Plan

For each implementation milestone: the spec sections fed to the AI tool, what it's asked to generate, and how the output is verified.

### M3 — Submission endpoint + first signal

- **Spec provided:** Detection Signals (Signal 1) + Architecture (submission diagram) + API Surface + Module Structure + Audit Log.
- **Ask the AI to generate:** `config.py`, the Flask `app.py` with the `POST /submit` route stub (hardcoded response first), `signal_llm.py` returning `{ ai_probability, reasoning }`, and `auditor.py` (the `.jsonl` writer) + `GET /log`. The Groq LLM-as-judge call can be adapted directly from Lab 4's `classify_safety_tier()` — same client init, single completion, parse-and-validate — changing only the prompt and output type.
- **Verify:** call the Signal 1 function directly on a few inputs and inspect that the output shape matches the spec contract *before* wiring it into the route; confirm the fail-closed fallback returns `0.5` on an unparseable response; confirm the route returns `content_id`, attribution, placeholder confidence, and placeholder label; confirm each submit appends one `.jsonl` line.

### M4 — Second signal + confidence scoring

- **Spec provided:** Detection Signals (Signal 2 + combination) + Uncertainty Representation + diagram.
- **Ask the AI to generate:** the stylometric Signal 2 function (the three metrics → one `ai_probability`) and the scoring function that applies `0.6/0.4` weighting, the disagreement rule, and the threshold table.
- **Verify:** run the four spec-provided test inputs (clear AI, clear human, two borderline); confirm scores diverge meaningfully and that the generated thresholds/weights **exactly match** this spec (AI tools often silently drift to plausible-but-different cutoffs); print both raw signal scores to locate any misbehaving signal; extend the audit log to record both individual scores.

### M5 — Production layer

- **Spec provided:** Transparency Label (the three verbatim variants) + Appeals Workflow + diagram.
- **Ask the AI to generate:** the label-generation function mapping confidence → the correct verbatim label, the `POST /appeal` endpoint (accepting `content_id`, `creator_id`, `creator_reasoning` and validating the `creator_id` matches the stored submission), and `GET /appeals`.
- **Verify:** ask the label function to emit all three variants and confirm the text matches this spec character-for-character; submit inputs that land in each band to confirm all three labels are reachable; file an appeal with a real `content_id` and confirm status flips to `under_review` and the appeal appears in `GET /log` with `appeal_reasoning` populated; confirm rate limiting returns `429` after the 10/minute limit.

## Relationship to Lab 4 (RepairSafe)

This project extends the RepairSafe lab (`ai201-lab4-repairsafe-starter`). Documenting the lineage here both guides implementation and feeds the README's required spec-reflection.

**Carries over directly:**

- **LLM-as-judge → Detection Signal 1.** `classify_safety_tier()` and `signal_llm.py` are the same pattern — single Groq completion, no tools/history, parse-and-validate, fail-closed fallback. Reuse the structure; change the prompt and the output type.
- **`.jsonl` audit log → Audit Log.** Same append-only one-object-per-line format, same UTC timestamp idiom, same `auditor.py` shape and rationale (error detection, accountability).
- **`config.py` constants module.** Same convention (`LLM_MODEL`, central tunables) extended with weights/thresholds.
- **Spec-before-code.** Lab 4 ships specs with blank decision fields; this `planning.md` is the from-scratch equivalent — same discipline, no template.

**New in this project (no Lab 4 precedent):**

- A second, **non-LLM stylometric signal** (pure Python, no API).
- **Continuous confidence scoring** representing uncertainty, versus RepairSafe's discrete tier.
- **Transparency labels, appeals workflow, rate limiting, and a Flask API** (RepairSafe used a Gradio UI with no appeals or rate limiting).

One deliberate divergence: RepairSafe fails closed toward `caution` (its safe-by-default tier); we fail closed toward `uncertain`/neutral, because on a creative platform the harm to avoid is falsely accusing a human, not under-warning about risk.

## Stretch Feature 1 — Analytics Dashboard

A simple operator-facing view summarizing what the system has been doing:
detection patterns, appeal rates, and one additional metric. This is the
"Analytics dashboard" stretch feature from the project brief (tracked on branch
`stretch_feature1`).

### Goal

Give a platform operator a one-glance picture of detection behavior and where
creators are pushing back, so they can spot a miscalibrated classifier or an
abnormal appeal rate without reading the raw audit log line by line.

### Data source

The dashboard is **read-only and derived entirely from the existing audit log**
(`logs/audit.jsonl`) — no new storage. It reads every entry (submissions and
appeals) and aggregates them in memory on each request. This keeps the feature
additive: it cannot change a classification or write to the log.

A small `analytics.py` module computes the metrics; `app.py` exposes them. The
audit reader (`auditor._read_all()`) is reused to load entries.

### Metrics

**1. Detection patterns** — the distribution of attributions across all
submissions:

- count and percentage for each of `likely_ai`, `uncertain`, `likely_human`.

**2. Appeal rate** — how often creators contest a classification:

- `appeal_rate = total_appeals / total_submissions` (reported as a percentage).
- `appeals_by_original_attribution` — how many appeals originated from each
  attribution category. This shows *which verdicts get contested most* (we
  expect `likely_ai` to draw the most appeals), which is the most actionable
  signal for spotting false positives.

**3. Additional metric (chosen): average confidence score** — the mean combined
`ai_probability`, reported overall and per attribution category. Because
`confidence` is AI-likelihood, this shows how *decisive* the system is: a healthy
system should show low average confidence for `likely_human`, high for
`likely_ai`, and mid-range for `uncertain`. A drift here (e.g. `likely_human`
average creeping up) is an early warning of miscalibration.

> Operational bonus (not the required "additional metric"): the dashboard also
> reports the **LLM availability rate** — the share of submissions where
> `llm_status == "available"` — so an operator can see when results were running
> degraded (stylometric-only).

### Endpoints

- **`GET /analytics`** → JSON, the machine-readable aggregates:

  ```json
  {
    "total_submissions": 12,
    "total_appeals": 3,
    "appeal_rate_pct": 25.0,
    "attribution_counts": {"likely_ai": 4, "uncertain": 5, "likely_human": 3},
    "attribution_pct": {"likely_ai": 33.3, "uncertain": 41.7, "likely_human": 25.0},
    "appeals_by_original_attribution": {"likely_ai": 2, "uncertain": 1, "likely_human": 0},
    "avg_confidence_overall": 0.46,
    "avg_confidence_by_attribution": {"likely_ai": 0.78, "uncertain": 0.55, "likely_human": 0.16},
    "llm_availability_pct": 100.0
  }
  ```

- **`GET /dashboard`** → a minimal self-contained **HTML view** rendering the
  same numbers as labeled sections with simple text/CSS bar charts (no
  JavaScript, no chart library, no new dependency). It calls the same
  `analytics.compute()` function so the two endpoints never disagree.

Neither endpoint is rate limited (read-only, no external API calls).

### Edge cases

- **Empty / missing log** → every count is `0`, `appeal_rate_pct` is `0.0`, and
  the averages are `null` (or `0.0`); no division-by-zero.
- **Appeals only counted against real submissions** — appeals reference a
  `content_id` that exists in the log (guaranteed by the M5 `/appeal`
  validation), so `appeals_by_original_attribution` always resolves.
- **Percentages** are rounded to one decimal place for display.

### AI Tool Plan (this stretch)

- **Spec provided:** this section + the Audit Log section (entry field names) +
  Module Structure.
- **Ask the AI to generate:** `analytics.py` with a pure `compute(entries)`
  function (no I/O — takes a list of entries, returns the metrics dict) plus the
  two Flask routes (`/analytics` returning `jsonify(compute(...))`, `/dashboard`
  rendering an HTML template string).
- **Verify:** unit-test `compute()` on a hand-built list of entries (including
  the empty-log case) so the math is checked without the LLM; then load
  `/dashboard` in a browser against the real audit log and confirm the numbers
  match `/analytics`.

### Documentation

Per the brief, completing a stretch feature requires documenting it in the
README (what it does and how it works) in addition to this planning entry.

## Stretch Feature 2 — Provenance Certificate (Verified Human)

### Goal

A creator can earn a **"Verified Human" credential** through an additional
verification step, and that credential is displayed on their submitted content.

This is a **creator-level** credential, deliberately separate from the
**content-level** attribution. Attribution answers *"was this text
AI-generated?"*; the certificate answers *"has this creator proven they're a real
human author?"* The two are shown together but **the certificate never overrides
attribution or confidence** — a verified creator who submits AI-like text still
gets a `likely_ai` result. That separation is the central design decision (it
prevents the badge from becoming a laundering channel for AI content).

### Earning method — live writing challenge

The credential is *earned*, not asserted, by reusing the system's own detection
pipeline:

1. The creator requests a challenge; the system issues a random writing prompt
   and a `challenge_id` with a short expiry.
2. The creator writes an original response on the spot and submits it.
3. The system runs the response through the **same** pipeline (Groq + stylometric
   + `scoring.combine`). If it is long enough and scores human enough, the
   credential is granted.

**Blind spot (documented honestly):** the challenge is gameable by pasting
human-written or lightly-edited text the creator didn't author live. A real
deployment would add liveness/proctoring; here it demonstrates the *mechanism*.
The one-attempt-per-challenge rule (a challenge is consumed when scored) and the
short expiry raise the cost of brute-forcing.

### Storage

Creator and challenge state are **keyed, mutable** records — a poor fit for the
append-only audit log — so they live in two small JSON files (the existing
`store.py`-style local-JSON approach):

- `data/creators.json` — `creator_id -> certificate record`
- `data/challenges.json` — `challenge_id -> pending challenge`

Both are runtime state and are git-ignored; `data/.gitkeep` keeps the directory.
Every verification *attempt* (granted or rejected) is additionally logged to the
audit log as an `event_type: "verification"` entry, so the credential trail is
auditable alongside submissions and appeals.

### Config additions

```python
CREATORS_FILE            = "data/creators.json"
CHALLENGES_FILE          = "data/challenges.json"
VERIFY_MIN_WORDS         = 80     # challenge response must be a real piece of writing
VERIFY_MAX_AI_PROBABILITY = 0.30  # response must score human enough to pass
CHALLENGE_EXPIRES_MINUTES = 15
CHALLENGE_PROMPTS = [ ... ]        # random prompt per challenge
```

### Endpoints

| Method | Path | Accepts | Returns |
|---|---|---|---|
| POST | `/verification-challenge` | `{ creator_id }` | `{ creator_id, challenge_id, prompt, expires_at }` (or current status if already verified) |
| POST | `/verify` | `{ creator_id, challenge_id, response_text }` | granted credential, or `403` with reason |
| GET | `/creators/<creator_id>` | — | the creator's certificate status |

`POST /verify` validation order: required fields (`400`) → challenge exists
(`404`) → challenge belongs to creator / not expired / not used (`403`) →
`>= VERIFY_MIN_WORDS` (`403`) → pipeline score `<= VERIFY_MAX_AI_PROBABILITY`
(grant, else `403`). The challenge is consumed once a scored attempt runs.

### Display on content

`POST /submit` looks up the creator and attaches a `provenance_certificate`
block to **both** the JSON response and the submission audit entry:

```json
"provenance_certificate": { "verified_human": true, "badge": "✓ Verified Human Creator", "verified_at": "...Z" }
```

Unverified creators get `{ "verified_human": false, "badge": null, "verified_at": null }`.
`GET /appeals` surfaces the original submission's certificate where available, and
`/analytics` gains `verified_creators` and `submissions_from_verified_creators`
(count + percentage).

### Edge cases

- **Already verified:** `/verification-challenge` returns the existing status
  instead of issuing a new challenge (idempotent).
- **Expired / used / wrong-creator challenge:** rejected at `/verify` (`403`).
- **Verified but flagged:** a verified creator's `likely_ai` submission is shown
  with the badge *and* the AI attribution — surfaced, not silently trusted.
- **Concurrent writes:** JSON files are written via temp-file + atomic
  `os.replace` to avoid partial writes.

### AI Tool Plan (this stretch)

Provide this section + the Detection Signals/scoring sections. Ask the AI to
generate `verification.py` (JSON storage, challenge issue/validate, grant) and
the three routes, reusing `detect_ai` / `detect_stylometric` / `combine` rather
than re-implementing detection. Verify with the documented curl sequence:
unverified submit → challenge → too-short reject → successful verify → status →
verified submit shows badge → verified creator's AI-like text still scores
`likely_ai`.

### Documentation

Documented in the README stretch section and in
`sample_outputs/stretch_certificate_verification.md`.

## Stretch Feature 3 — Ensemble Detection (third signal + voting)

### Goal

Move from two signals to a **three-signal ensemble** with a documented weighting
**and** a voting rule, satisfying the "3+ signals" stretch. The third signal is a
cheap, fully independent lexical check that complements the existing semantic
(LLM) and structural (stylometric) signals.

### Signal 3 — Phrase-pattern signal

- **File:** `phrase_signal.py` (pure Python, no API — always `available`).
- **Measures:** density of common AI-style filler phrases / markers (e.g.
  *"it is important to note"*, *"rapidly evolving"*, *"paradigm shift"*,
  *"furthermore"*, *"leverage"*, *"delve into"*). These are lexical tells that are
  independent of both the holistic semantic read and the structural metrics.
- **Output:**
  ```json
  { "ai_probability": float, "status": "available",
    "matched_phrases": [...], "reasoning": "..." }
  ```
- **Normalization (conservative):** score is based on the **number of distinct
  matched phrases relative to text length** (matches per ~100 words), scaled so
  it takes several markers to approach a high score. A **single phrase is capped
  low** (≤ ~0.30) so one incidental match can never, by itself, push the ensemble
  toward `likely_ai`.
- **Blind spot:** keyword lists are easily evaded (synonyms, paraphrase) and can
  false-positive on legitimate formal/academic human writing that happens to use
  these connectives — which is exactly why its weight is small and the voting
  rule requires corroboration.

### Updated combination (three-signal weighting)

```text
combined = 0.55 * llm + 0.30 * stylometric + 0.15 * phrase_pattern
```

The LLM remains the strongest signal; stylometric is the independent
corroborator; the phrase signal is a light-weight lexical tie-breaker. Thresholds
are unchanged: `>= 0.70` → `likely_ai`, `<= 0.25` → `likely_human`, else
`uncertain`. When a signal is unavailable (LLM down, or stylometric on
short text), the remaining signal weights are renormalized.

### False-positive-averse ensemble (voting) rule

`likely_ai` now requires **both**:

1. `combined >= 0.70`, **and**
2. **at least two of the three signals individually `>= 0.60`.**

If `combined >= 0.70` but fewer than two signals clear `0.60`, the verdict is
forced to `uncertain` with note `ensemble_insufficient_votes_forced_uncertain`.
This means a single strong signal (or one strong signal plus weak corroboration)
can never produce an AI accusation — corroboration by independent signals is
required. The existing overrides remain (short-text → uncertain, LLM/stylometric
disagreement → uncertain); like before, every override only ever moves a verdict
*toward* uncertain.

### Integration

`/submit` (and the `/verify` challenge scorer) run all three signals and call the
updated `combine(llm, stylo, phrase)`. The response `signals` block gains a
`phrase` entry (`ai_probability`, `status`, `matched_phrases`), and the audit log
gains `phrase_ai_probability`, `phrase_status`, and `matched_phrases`. Appeals and
rate limiting are unchanged.

### Documentation

README scoring section (updated weights + voting rule + Signal 3) and
`sample_outputs/stretch_ensemble_verification.md`.

## Stretch Feature 4 — Multi-Modal Support (structured metadata)

### Goal

Extend the pipeline to handle a **second content type** — structured creation
**metadata** — in addition to free text. Instead of classifying a finished piece
of writing, this analyzes the *context a creator declares about how a work was
made* (title, description, creation notes, tools used, and a self-declaration of
AI assistance).

Second content type is **structured metadata, not image files.**

### Design choice — reuse the ensemble, do not add modality-specific markers

The free-text fields of the metadata are normalized into a single
`analysis_text` string and passed through the **existing LLM + stylometric +
phrase ensemble unchanged**. We deliberately do **not** add modality-specific
lexical markers (e.g. image-caption phrases): those would be normal description
language, not reliable AI-authorship signals, and would raise false positives and
require fresh calibration. Keeping one scoring model across content types keeps
the system consistent and the comparison meaningful.

### New endpoint

`POST /submit-metadata`

```json
{
  "creator_id": "alice",
  "title": "...",
  "description": "...",
  "creation_notes": "...",
  "tools_used": ["notebook", "Google Docs"],
  "declared_ai_assistance": false
}
```

**Validation:** `creator_id`, `title`, `description` required; `tools_used` must
be a list if provided; `declared_ai_assistance` must be boolean if provided.

### Two sub-analyses, blended

1. **Text ensemble.** `analysis_text = "{title}. {description} {creation_notes}"`
   runs through `detect_ai` + `detect_stylometric` + `detect_phrases` +
   `combine()` → `text_confidence`.
2. **Metadata context signal** (`metadata_signal.py`), a transparent heuristic
   over the structured fields:
   - start at `0.5`
   - `declared_ai_assistance` is true → `+0.35`
   - `tools_used` contains an AI tool (chatgpt, claude, gemini, copilot, openai,
     groq) → `+0.25`
   - `creation_notes` missing or `< 20` chars → `+0.10`
   - `creation_notes` detailed (`> 80` chars) → `-0.15`
   - `description` very generic (`< 6` words) → `+0.10`
   - clamp to `[0.0, 1.0]`; returns the score **and** a breakdown of which
     factors fired.

**Blend:** `confidence = 0.5 * text_confidence + 0.5 * metadata_score`. The
ensemble catches AI-sounding prose; the metadata context catches declared /
tool-based / under-documented signals; neither alone is authoritative, so they
are weighted equally. (Weight is a single constant, easy to tune.)

### Classification & honesty

Same thresholds (`>= 0.70` likely_ai, `<= 0.25` likely_human, else uncertain).
Because metadata is weaker evidence than analyzing the work itself, every
metadata result carries a note that **metadata analysis is contextual and not
proof of authorship.**

### Response & audit

Response: `{ content_id, content_type: "metadata", creator_id, attribution,
confidence, label, metadata_signals: { metadata_context, text_analysis }, notes }`.
Audit: `event_type: "metadata_submission"` with `content_type`, `content_id`,
`creator_id`, `attribution`, `confidence`, the metadata signal details + text
ensemble scores, `label`, `notes`, `status: "classified"`. Appeals, rate
limiting, and the text `/submit` endpoint are unchanged.

### Documentation

README multi-modal section and `sample_outputs/stretch_metadata_verification.md`
(no-AI + detailed notes; declared AI assistance; missing creation notes).