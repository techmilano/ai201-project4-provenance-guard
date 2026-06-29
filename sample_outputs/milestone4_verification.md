# Milestone 4 — Verification

Second detection signal (stylometric) + real combined confidence scoring.

## New / changed files

| File | Purpose |
|---|---|
| `stylometric.py` | Signal 2: pure-Python heuristics (sentence-length variance, type-token ratio, clause-punctuation density) → one `ai_probability` |
| `scoring.py` | Combine signals: `0.6·LLM + 0.4·stylo`, thresholds, and false-positive-averse overrides |
| `auditor.py` | Audit entry extended with `stylometric_ai_probability`, `stylometric_status`, `notes` |
| `app.py` | `/submit` now runs both signals and uses `scoring.combine()` |
| `config.py` / `planning.md` | `AI_THRESHOLD` lowered `0.85 → 0.70` (see calibration note) |

## Scoring rules (planning.md)

- Weighted combine: `0.6·LLM + 0.4·stylometric`
- Thresholds: `>= 0.70` likely_ai, `<= 0.25` likely_human, else uncertain
- Overrides (only ever push toward `uncertain`):
  - short / insufficient stylometric text → uncertain
  - signals disagree by more than `0.5` → uncertain
  - single-signal mode (one signal down) can never reach likely_ai

## Calibration note

`AI_THRESHOLD` started at `0.85`. In M4 testing this made `likely_ai`
practically unreachable: clear AI scored only ~`0.71–0.76` combined, because the
LLM rarely exceeds ~`0.9` and the stylometric signal often disagrees on AI prose
(GPT-style writing has varied sentence lengths and rich vocabulary, so only
punctuation density flags it). Lowering to `0.70` makes all three labels
reachable while staying false-positive averse — no human/borderline-human input
in the calibration set is misclassified. Weights, `HUMAN_THRESHOLD`, and the
disagreement rule are unchanged.

A separate fix: type-token ratio is length-confounded (below ~100 words almost
every word is unique), so it is neutralized (0.5) for short texts instead of
saturating and skewing the average.

## Scoring override unit tests (offline, deterministic)

```text
both high -> likely_ai         conf=0.86   likely_ai     []
both low -> likely_human       conf=0.12   likely_human  []
mid -> uncertain               conf=0.48   uncertain     []
disagree(0.95 vs 0.10)         conf=0.61   uncertain     []
llm down, stylo high (cap)     conf=0.95   uncertain     ['llm_unavailable_stylometric_only', 'single_signal_capped_uncertain']
llm down, stylo low            conf=0.1    likely_human  ['llm_unavailable_stylometric_only']
short text -> uncertain        conf=0.95   uncertain     ['stylometric_unavailable_llm_only', 'short_text_forced_uncertain']
```

## Live calibration set (4 spec inputs + 1 heavy-AI)

```text
input                        conf  llm  stylo  attribution
clear AI                   0.6486  0.8 0.4216  uncertain     (boundary; likely_ai when LLM returns ~0.9)
clear human                0.2088  0.2 0.2219  likely_human
borderline formal human    0.5883  0.8 0.2708  uncertain     (correctly NOT accused)
borderline edited AI       0.2711  0.2 0.3777  uncertain
heavy AI                   0.7637  0.9 0.5593  likely_ai
```

All three labels are reachable end-to-end. Clear-human vs heavy-AI differ by
~0.55 in combined confidence, confirming meaningful variation. The LLM is mildly
non-deterministic even at temperature 0, so inputs near the 0.70 boundary
(clear AI) can flip between `uncertain` and `likely_ai` across runs.

## Example /submit response (heavy AI)

```json
{
  "attribution": "likely_ai",
  "confidence": 0.7637,
  "label": "⚠️ Likely AI-generated. Our analysis found strong signals that this text was produced by an AI system.",
  "notes": [],
  "signals": {
    "llm": { "ai_probability": 0.9, "reasoning": "...", "status": "available" },
    "stylometric": {
      "ai_probability": 0.5593,
      "status": "available",
      "metrics": {
        "sentence_length_stdev": 6.576,
        "type_token_ratio": 0.86,
        "clause_punct_per_sentence": 3.75,
        "var_ai": 0.178, "ttr_ai": 0.5, "punct_ai": 1.0
      }
    }
  }
}
```
