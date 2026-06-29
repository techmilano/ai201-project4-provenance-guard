"""Confidence scoring — combine the two signals into one calibrated result.

Implements the planning.md rules:
  - weighted combine: 0.6 * LLM + 0.4 * stylometric
  - thresholds: >= 0.85 likely_ai, <= 0.25 likely_human, else uncertain
  - false-positive-averse overrides (all can only move a verdict toward
    uncertain, never toward likely_ai):
      * short / insufficient stylometric text -> uncertain
      * signals disagree by more than DISAGREE_DELTA -> uncertain
      * single-signal mode (one signal down) can never reach likely_ai
"""

from config import (
    AI_THRESHOLD,
    DISAGREE_DELTA,
    HUMAN_THRESHOLD,
    LLM_WEIGHT,
    STYLO_WEIGHT,
)


def _attribution(score: float) -> str:
    if score >= AI_THRESHOLD:
        return "likely_ai"
    if score <= HUMAN_THRESHOLD:
        return "likely_human"
    return "uncertain"


def combine(llm: dict, stylo: dict) -> dict:
    """Combine signal results into {confidence, attribution, notes}."""
    llm_p = llm["ai_probability"]
    stylo_p = stylo["ai_probability"]
    llm_ok = llm["status"] == "available"
    stylo_ok = stylo["status"] == "available"
    notes = []

    # --- weighted combined score (best ai_probability estimate) ---
    if llm_ok and stylo_ok:
        combined = LLM_WEIGHT * llm_p + STYLO_WEIGHT * stylo_p
    elif stylo_ok:
        combined = stylo_p
        notes.append("llm_unavailable_stylometric_only")
    elif llm_ok:
        combined = llm_p
        notes.append("stylometric_unavailable_llm_only")
    else:
        combined = 0.5
        notes.append("both_signals_unavailable")

    combined = round(combined, 4)
    attribution = _attribution(combined)

    # --- overrides (only ever push toward uncertain) ---
    if stylo["status"] == "insufficient_text":
        if attribution != "uncertain":
            notes.append("short_text_forced_uncertain")
        attribution = "uncertain"

    if llm_ok and stylo_ok and abs(llm_p - stylo_p) > DISAGREE_DELTA:
        if attribution != "uncertain":
            notes.append("signal_disagreement_forced_uncertain")
        attribution = "uncertain"

    if not (llm_ok and stylo_ok) and attribution == "likely_ai":
        notes.append("single_signal_capped_uncertain")
        attribution = "uncertain"

    return {"confidence": combined, "attribution": attribution, "notes": notes}
