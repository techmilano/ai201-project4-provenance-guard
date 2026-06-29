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


def _append(entry: dict) -> dict:
    """Append one JSON object as a line to the audit log."""
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def _read_all() -> list:
    """Return every audit entry in chronological (oldest-first) order."""
    if not os.path.exists(LOG_FILE):
        return []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def log_submission(
    content_id: str,
    creator_id: str,
    attribution: str,
    confidence: float,
    label: str,
    llm_ai_probability: float,
    llm_status: str,
    stylometric_ai_probability: float,
    stylometric_status: str,
    notes=None,
) -> dict:
    """Append a structured submission entry to the audit log and return it."""
    entry = _append(
        {
            "timestamp": _timestamp(),
            "event_type": "submission",
            "content_id": content_id,
            "creator_id": creator_id,
            "attribution": attribution,
            "confidence": confidence,
            "label": label,
            "llm_ai_probability": llm_ai_probability,
            "llm_status": llm_status,
            "stylometric_ai_probability": stylometric_ai_probability,
            "stylometric_status": stylometric_status,
            "notes": notes or [],
            "status": "classified",
        }
    )
    print(
        f"[LOGGED] submission {attribution} conf={confidence} "
        f"content_id={content_id} llm={llm_status}"
    )
    return entry


def find_submission(content_id: str):
    """Return the submission entry for `content_id`, or None if not found."""
    for entry in _read_all():
        if entry.get("event_type") == "submission" and entry.get("content_id") == content_id:
            return entry
    return None


def log_appeal(content_id: str, creator_id: str, creator_reasoning: str,
               original: dict) -> dict:
    """Append an appeal entry that preserves the original decision and return it."""
    entry = _append(
        {
            "timestamp": _timestamp(),
            "event_type": "appeal",
            "content_id": content_id,
            "creator_id": creator_id,
            "creator_reasoning": creator_reasoning,
            "status": "under_review",
            # original decision fields, preserved for the reviewer queue
            "original_attribution": original.get("attribution"),
            "original_confidence": original.get("confidence"),
            "original_label": original.get("label"),
            "original_llm_ai_probability": original.get("llm_ai_probability"),
            "original_stylometric_ai_probability": original.get("stylometric_ai_probability"),
            "original_timestamp": original.get("timestamp"),
        }
    )
    print(f"[LOGGED] appeal content_id={content_id} -> under_review")
    return entry


def read_log(limit: int = 50) -> list:
    """Return the most recent audit entries (newest first), up to `limit`."""
    return _read_all()[-limit:][::-1]


def read_appeals() -> list:
    """Return appealed (under_review) items, newest first, one per content_id."""
    latest = {}
    for entry in _read_all():
        if entry.get("event_type") == "appeal":
            latest[entry["content_id"]] = entry  # last appeal per content wins
    return sorted(latest.values(), key=lambda e: e["timestamp"], reverse=True)
