"""Metadata context signal (stretch feature 4 — multi-modal support).

A transparent heuristic over a creator's *structured creation metadata* — what
they declare about how a work was made — rather than the work's prose. It is a
*contextual* signal: weaker than analyzing the text itself, and explicitly not
proof of authorship. It returns both a score and a breakdown of which factors
fired, so the result is fully explainable.
"""

# Tool names (substring, case-insensitive) that indicate AI assistance.
AI_TOOLS = ["chatgpt", "claude", "gemini", "copilot", "openai", "groq"]


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def score_metadata(
    description: str,
    creation_notes,
    tools_used,
    declared_ai_assistance: bool,
) -> dict:
    """Score creation metadata for AI-assistance likelihood.

    Returns:
        {"score": float (0.0–1.0), "breakdown": [ {factor, delta}, ... ]}
    """
    score = 0.5
    breakdown = [{"factor": "base", "delta": 0.5}]

    def add(factor, delta):
        nonlocal score
        score += delta
        breakdown.append({"factor": factor, "delta": delta})

    if declared_ai_assistance:
        add("declared_ai_assistance", 0.35)

    tools = tools_used or []
    matched_tools = [
        t for t in tools
        if any(ai in str(t).lower() for ai in AI_TOOLS)
    ]
    if matched_tools:
        add("ai_tools_used:" + ",".join(matched_tools), 0.25)

    notes = creation_notes or ""
    if len(notes.strip()) < 20:
        add("creation_notes_missing_or_short", 0.10)
    elif len(notes.strip()) > 80:
        add("creation_notes_detailed", -0.15)

    if len((description or "").split()) < 6:
        add("description_generic", 0.10)

    final = round(_clamp(score), 4)
    return {"score": final, "breakdown": breakdown}
