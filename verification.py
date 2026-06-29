"""Stretch Feature 2 — Provenance Certificate (live writing challenge).

A creator-level "Verified Human" credential, separate from content-level
attribution. A creator earns it by completing a live writing challenge: the
system issues a random prompt, the creator writes a response, and that response
is scored by the SAME detection pipeline (the scoring happens in the route, which
passes the resulting ai_probability to `grant()` — so this module stays pure
storage + challenge bookkeeping and never imports the detectors).

State lives in two small JSON files — keyed, mutable records, unlike the
append-only audit log:
  - data/creators.json    creator_id -> certificate record
  - data/challenges.json  challenge_id -> pending challenge
"""

import json
import os
import random
import uuid
from datetime import datetime, timedelta, timezone

from config import (
    CHALLENGE_EXPIRES_MINUTES,
    CHALLENGE_PROMPTS,
    CHALLENGES_FILE,
    CREATORS_FILE,
)

BADGE = "✓ Verified Human Creator"
METHOD = "live_writing_challenge"


# --------------------------------------------------------------------------- #
# Time helpers
# --------------------------------------------------------------------------- #

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _parse(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


# --------------------------------------------------------------------------- #
# JSON storage (temp-file + atomic replace to avoid partial writes)
# --------------------------------------------------------------------------- #

def _load(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


# --------------------------------------------------------------------------- #
# Creator credential lookups
# --------------------------------------------------------------------------- #

def is_verified(creator_id: str) -> bool:
    return bool(_load(CREATORS_FILE).get(creator_id, {}).get("verified_human"))


def certificate_for(creator_id: str) -> dict:
    """Compact certificate block embedded in /submit responses and audit entries."""
    rec = _load(CREATORS_FILE).get(creator_id)
    if rec and rec.get("verified_human"):
        return {
            "verified_human": True,
            "badge": rec["badge"],
            "verified_at": rec["verified_at"],
        }
    return {"verified_human": False, "badge": None, "verified_at": None}


def get_creator_status(creator_id: str) -> dict:
    """Full status for GET /creators/<creator_id>."""
    rec = _load(CREATORS_FILE).get(creator_id)
    if rec and rec.get("verified_human"):
        return {
            "creator_id": creator_id,
            "verified_human": True,
            "badge": rec["badge"],
            "verified_at": rec["verified_at"],
            "method": rec["method"],
        }
    return {
        "creator_id": creator_id,
        "verified_human": False,
        "badge": None,
        "verified_at": None,
    }


# --------------------------------------------------------------------------- #
# Challenge lifecycle
# --------------------------------------------------------------------------- #

def create_challenge(creator_id: str) -> dict:
    """Issue a new writing challenge and persist it."""
    challenge_id = str(uuid.uuid4())
    prompt = random.choice(CHALLENGE_PROMPTS)
    expires_at = _iso(_now() + timedelta(minutes=CHALLENGE_EXPIRES_MINUTES))

    challenges = _load(CHALLENGES_FILE)
    challenges[challenge_id] = {
        "challenge_id": challenge_id,
        "creator_id": creator_id,
        "prompt": prompt,
        "created_at": _iso(_now()),
        "expires_at": expires_at,
        "used": False,
    }
    _save(CHALLENGES_FILE, challenges)

    return {
        "creator_id": creator_id,
        "challenge_id": challenge_id,
        "prompt": prompt,
        "expires_at": expires_at,
    }


def validate_challenge(creator_id: str, challenge_id: str):
    """Return (challenge, error). error is None when the challenge is usable.

    Errors map to: missing -> 404 (caller), others -> 403 (caller).
    """
    challenge = _load(CHALLENGES_FILE).get(challenge_id)
    if challenge is None:
        return None, "challenge not found"
    if challenge["creator_id"] != creator_id:
        return None, "challenge does not belong to this creator_id"
    if challenge.get("used"):
        return None, "challenge has already been used"
    if _now() > _parse(challenge["expires_at"]):
        return None, "challenge has expired"
    return challenge, None


def consume_challenge(challenge_id: str) -> None:
    """Mark a challenge used — one scored attempt per challenge (anti-gaming)."""
    challenges = _load(CHALLENGES_FILE)
    if challenge_id in challenges:
        challenges[challenge_id]["used"] = True
        _save(CHALLENGES_FILE, challenges)


def grant(creator_id: str, challenge_id: str, challenge_score: float) -> dict:
    """Record and return the verified-human credential for a creator."""
    record = {
        "creator_id": creator_id,
        "verified_human": True,
        "badge": BADGE,
        "verified_at": _iso(_now()),
        "method": METHOD,
        "challenge_id": challenge_id,
        "challenge_score": challenge_score,
    }
    creators = _load(CREATORS_FILE)
    creators[creator_id] = record
    _save(CREATORS_FILE, creators)
    return record
