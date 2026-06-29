"""Detection Signal 2 — stylometric heuristics (pure Python, no API).

Captures *structural* regularity of the prose, independent of the LLM's
*semantic* read. Three metrics, each normalized to a [0,1] "AI-ness"
contribution and averaged into a single ai_probability (1.0 = reads as AI):

  1. Sentence-length variance — AI text is more uniform (low variance).
  2. Type-token ratio (vocabulary diversity) — AI reuses a narrower vocabulary.
  3. Punctuation density (commas per sentence) — AI tends to be evenly,
     heavily punctuated; casual human writing less so.

Reference ranges are rough first-pass calibration (planning.md notes these are
tuned empirically). Below MIN_WORDS the metrics are unstable, so the signal
reports status "insufficient_text" and a neutral 0.5.
"""

import re
import statistics

from config import MIN_WORDS

_SENTENCE_SPLIT = re.compile(r"[.!?]+")
_WORD = re.compile(r"\b\w+\b")

# Type-token ratio is length-confounded: below ~100 words almost every word is
# unique, so TTR can't distinguish AI from human. We neutralize it (0.5) below
# this length rather than let a saturated value skew the average.
_TTR_RELIABLE_WORDS = 100


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def detect_stylometric(text: str) -> dict:
    """Score `text` on structural regularity.

    Returns:
        {"ai_probability": float, "status": str, "word_count": int,
         "metrics": {...}} — status is "available" or "insufficient_text".
    """
    words = _WORD.findall(text.lower())
    word_count = len(words)

    if word_count < MIN_WORDS:
        return {
            "ai_probability": 0.5,
            "status": "insufficient_text",
            "word_count": word_count,
            "metrics": {},
        }

    sentences = [s for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    sentence_count = len(sentences) or 1

    # 1) Sentence-length variance — low std => uniform => AI-like.
    lengths = [len(_WORD.findall(s)) for s in sentences] or [word_count]
    stdev = statistics.pstdev(lengths) if len(lengths) > 1 else 0.0
    var_ai = _clamp(1.0 - stdev / 8.0)  # std >= ~8 words => clearly human

    # 2) Type-token ratio — lower diversity => AI-like (only reliable on
    #    longer texts; neutralized below _TTR_RELIABLE_WORDS).
    ttr = len(set(words)) / word_count
    if word_count >= _TTR_RELIABLE_WORDS:
        ttr_ai = _clamp((0.70 - ttr) / (0.70 - 0.40))  # ttr<=0.40 AI, >=0.70 human
    else:
        ttr_ai = 0.5  # neutral — not enough text for TTR to mean anything

    # 3) Clause-punctuation density — more commas/semicolons/colons per
    #    sentence => denser subordinate structure => AI-like.
    clause_punct = text.count(",") + text.count(";") + text.count(":")
    clause_punct_per_sentence = clause_punct / sentence_count
    punct_ai = _clamp(clause_punct_per_sentence / 1.5)  # >=1.5/sentence => AI

    ai_probability = round((var_ai + ttr_ai + punct_ai) / 3.0, 4)

    return {
        "ai_probability": ai_probability,
        "status": "available",
        "word_count": word_count,
        "metrics": {
            "sentence_length_stdev": round(stdev, 3),
            "type_token_ratio": round(ttr, 3),
            "clause_punct_per_sentence": round(clause_punct_per_sentence, 3),
            "var_ai": round(var_ai, 3),
            "ttr_ai": round(ttr_ai, 3),
            "punct_ai": round(punct_ai, 3),
        },
    }
