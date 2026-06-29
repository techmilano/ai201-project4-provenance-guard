"""Structured audit log — append-only JSONL at logs/audit.jsonl.

One JSON object per line (the RepairSafe `.jsonl` convention). Every
attribution decision is recorded so a degraded or miscalibrated result is
diagnosable after the fact.
"""

import json
import os
from datetime import datetime, timezone

from config import LOG_FILE


def _timestamp() -> str:
    """UTC ISO 8601, e.g. 2026-06-28T14:32:10.123456Z."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def log_submission(
    content_id: str,
    creator_id: str,
    attribution: str,
    confidence: float,
    llm_ai_probability: float,
    llm_status: str,
) -> dict:
    """Append a structured submission entry to the audit log and return it."""
    entry = {
        "timestamp": _timestamp(),
        "event_type": "submission",
        "content_id": content_id,
        "creator_id": creator_id,
        "attribution": attribution,
        "confidence": confidence,
        "llm_ai_probability": llm_ai_probability,
        "llm_status": llm_status,
        "status": "classified",
    }

    # Create logs/ on first write if it doesn't exist yet.
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    print(
        f"[LOGGED] {attribution} conf={confidence} "
        f"content_id={content_id} llm={llm_status}"
    )
    return entry


def read_log(limit: int = 50) -> list:
    """Return the most recent audit entries (newest first), up to `limit`."""
    if not os.path.exists(LOG_FILE):
        return []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        entries = [json.loads(line) for line in f if line.strip()]
    return entries[-limit:][::-1]
