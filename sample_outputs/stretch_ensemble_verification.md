# Stretch Feature 3 — Ensemble Detection: verification record

Evidence for the **three-signal ensemble** with weighted combination and a
voting rule. Signal 3 is the phrase-pattern signal ([phrase_signal.py](../phrase_signal.py)).

- **Weights:** `combined = 0.55*llm + 0.30*stylometric + 0.15*phrase` (renormalized
  if a signal is unavailable).
- **Thresholds:** `>= 0.70` likely_ai, `<= 0.25` likely_human, else uncertain.
- **Voting rule:** `likely_ai` requires `combined >= 0.70` **and** at least **two
  of the three** signals individually `>= 0.60`; otherwise forced `uncertain`.

---

## 1. AI-like text (many phrase matches) → `likely_ai`

`POST /submit` with a paragraph dense in AI-style markers:

```json
{
  "attribution": "likely_ai",
  "confidence": 0.7617,
  "label": "⚠️ Likely AI-generated. Our analysis found strong signals that this text was produced by an AI system.",
  "notes": [],
  "signals": {
    "llm":         { "ai_probability": 0.9,    "status": "available" },
    "stylometric": { "ai_probability": 0.3889, "status": "available" },
    "phrase": {
      "ai_probability": 1.0,
      "status": "available",
      "matched_phrases": [
        "it is important to note", "rapidly evolving", "in today's",
        "transformative", "paradigm shift", "furthermore", "stakeholders",
        "ethical implications", "responsible deployment", "delve into",
        "robust", "seamless", "leverage", "unlock"
      ],
      "reasoning": "Matched 14 common AI-style phrase(s) (25.0 per 100 words): ..."
    }
  }
}
```

**Why `likely_ai`:** combined `0.7617 >= 0.70`, and two signals clear `0.60`
(LLM `0.90` and phrase `1.0`). The stylometric signal alone scored this flowing
paragraph low (`0.39`); the ensemble's third signal is what supplies the second
corroborating vote.

## 2. Human-like text (no phrase matches) → `likely_human`

```json
{
  "attribution": "likely_human",
  "confidence": 0.1858,
  "label": "✓ Likely human-written. Our analysis found no strong signals of AI generation.",
  "notes": [],
  "signals": {
    "llm":         { "ai_probability": 0.2,    "status": "available" },
    "stylometric": { "ai_probability": 0.2527, "status": "available" },
    "phrase":      { "ai_probability": 0.0, "status": "available", "matched_phrases": [],
                     "reasoning": "No common AI-style phrases detected." }
  }
}
```

## 3. Audit log includes all three signal scores

The submission entry for case 1 (`logs/audit.jsonl`):

```json
{
  "event_type": "submission",
  "attribution": "likely_ai",
  "confidence": 0.7617,
  "llm_ai_probability": 0.9,            "llm_status": "available",
  "stylometric_ai_probability": 0.3889, "stylometric_status": "available",
  "phrase_ai_probability": 1.0,         "phrase_status": "available",
  "matched_phrases": ["it is important to note", "rapidly evolving", "...14 total..."],
  "notes": [],
  "status": "classified"
}
```

## 4. Voting rule unit checks (deterministic, no LLM)

`combine(llm, stylo, phrase)` with synthetic signal values:

| llm | stylo | phrase | combined | votes ≥0.60 | attribution | note |
|----:|------:|-------:|---------:|:-----------:|---|---|
| 0.90 | 0.70 | 0.50 | 0.78 | 2 | `likely_ai` | — |
| 0.95 | 0.55 | 0.55 | 0.77 | 1 | `uncertain` | `ensemble_insufficient_votes_forced_uncertain` |
| 0.10 | 0.20 | 0.00 | 0.115 | 0 | `likely_human` | — |

Row 2 is the false-positive-averse case: the combined score clears `0.70`, but
only one signal reaches `0.60`, so the verdict is forced to `uncertain` rather
than accusing on a single strong signal.

## 5. Phrase-signal conservatism

| input | matched | ai_probability |
|---|---|---|
| one phrase ("robust") in ~66 words | 1 | `0.30` (single-match cap) |
| 14 markers in ~64 words | 14 | `1.0` |
| casual sentence, no markers | 0 | `0.0` |

A single incidental phrase is capped at `0.30` (below the `0.60` voting
threshold), so it can never on its own count as an AI vote.

---

## Design note — pairwise disagreement override removed

The two-signal version forced `uncertain` whenever the LLM and stylometric
signals disagreed by more than `0.5`. With three signals that rule actively
blocked correct AI verdicts (case 1: LLM `0.9` and phrase `1.0` agree it's AI,
but stylometric `0.39` would have vetoed it). The voting rule is a stronger,
more general guard — it requires two independent signals to corroborate before
accusing — so it **replaces** the pairwise disagreement override. The
short-text → uncertain override is unchanged.
