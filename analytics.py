"""Stretch Feature 1 — Analytics Dashboard.

Pure aggregation over audit-log entries plus a dependency-free HTML view.
Read-only: every number is derived from existing submission/appeal entries, so
the dashboard can never change a classification or write to the log.

`compute()` takes a list of entries and returns the metrics dict (no I/O), so it
is trivially unit-testable. `render_dashboard()` turns that same dict into HTML,
so the JSON and HTML views can never disagree.
"""

from config import RATE_LIMIT

# display order for the three attribution categories
_ATTRIBUTIONS = ["likely_ai", "uncertain", "likely_human"]
_COLORS = {"likely_ai": "#dc2626", "uncertain": "#d97706", "likely_human": "#16a34a"}


def _avg(values):
    """Mean rounded to 4 dp, or None for an empty list."""
    return round(sum(values) / len(values), 4) if values else None


def compute(entries) -> dict:
    """Aggregate audit entries into dashboard metrics (see planning.md)."""
    submissions = [e for e in entries if e.get("event_type") == "submission"]
    appeals = [e for e in entries if e.get("event_type") == "appeal"]
    verifications = [e for e in entries if e.get("event_type") == "verification"]

    total_submissions = len(submissions)
    total_appeals = len(appeals)

    # --- provenance certificate metrics (stretch feature 2) ---
    verified_creators = len(
        {
            e["creator_id"]
            for e in verifications
            if e.get("verification_result") == "granted"
        }
    )
    subs_from_verified = sum(
        1
        for e in submissions
        if (e.get("provenance_certificate") or {}).get("verified_human")
    )
    subs_from_verified_pct = (
        round(subs_from_verified / total_submissions, 4) if total_submissions else 0.0
    )

    counts = {a: 0 for a in _ATTRIBUTIONS}
    for e in submissions:
        if e.get("attribution") in counts:
            counts[e["attribution"]] += 1

    if total_submissions:
        appeal_rate = round(total_appeals / total_submissions, 4)
        most_common = max(_ATTRIBUTIONS, key=lambda a: counts[a])
        avg_conf = _avg([e["confidence"] for e in submissions if "confidence" in e])
        avg_llm = _avg(
            [e["llm_ai_probability"] for e in submissions if "llm_ai_probability" in e]
        )
        avg_stylo = _avg(
            [e["stylometric_ai_probability"] for e in submissions
             if "stylometric_ai_probability" in e]
        )
    else:
        appeal_rate = 0.0
        most_common = None
        avg_conf = avg_llm = avg_stylo = None

    return {
        "total_submissions": total_submissions,
        "total_appeals": total_appeals,
        "appeal_rate": appeal_rate,
        "attribution_counts": counts,
        "average_confidence": avg_conf,
        "average_llm_ai_probability": avg_llm,
        "average_stylometric_ai_probability": avg_stylo,
        "most_common_attribution": most_common,
        "verified_creators": verified_creators,
        "submissions_from_verified_creators": subs_from_verified,
        "submissions_from_verified_creators_pct": subs_from_verified_pct,
        "rate_limit": RATE_LIMIT.replace(";", "; "),
    }


# --------------------------------------------------------------------------- #
# HTML view (no JavaScript, no chart library — CSS bar charts)
# --------------------------------------------------------------------------- #

def _bar(label, width_pct, color, display) -> str:
    return (
        f'<div class="row"><span class="lbl">{label}</span>'
        f'<span class="track"><span class="fill" '
        f'style="width:{width_pct:.1f}%;background:{color};"></span></span>'
        f'<span class="val">{display}</span></div>'
    )


def render_dashboard(metrics) -> str:
    """Render the metrics dict as a self-contained HTML page."""
    counts = metrics["attribution_counts"]
    max_count = max(counts.values()) or 1
    attr_bars = "".join(
        _bar(a.replace("_", " "), counts[a] / max_count * 100, _COLORS[a], counts[a])
        for a in _ATTRIBUTIONS
    )

    def prob_bar(label, v):
        if v is None:
            return _bar(label, 0, "#94a3b8", "—")
        return _bar(label, v * 100, "#2563eb", f"{v:.3f}")

    prob_bars = (
        prob_bar("avg confidence (AI prob)", metrics["average_confidence"])
        + prob_bar("avg LLM signal", metrics["average_llm_ai_probability"])
        + prob_bar("avg stylometric signal", metrics["average_stylometric_ai_probability"])
    )

    mca = (metrics["most_common_attribution"] or "—").replace("_", " ")
    appeal_pct = f'{metrics["appeal_rate"] * 100:.1f}%'
    verified_pct = f'{metrics["submissions_from_verified_creators_pct"] * 100:.1f}%'

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Provenance Guard — Analytics</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 760px; margin: 40px auto; color:#1f2937; padding:0 16px; }}
  h1 {{ margin-bottom: 4px; }}
  .sub {{ color:#6b7280; margin-top:0; }}
  .cards {{ display:flex; gap:12px; flex-wrap:wrap; margin:20px 0; }}
  .card {{ flex:1; min-width:140px; background:#f9fafb; border:1px solid #e5e7eb; border-radius:10px; padding:14px; }}
  .card .n {{ font-size:1.6em; font-weight:700; }}
  .card .k {{ color:#6b7280; font-size:0.85em; }}
  h2 {{ margin-top:28px; font-size:1.05em; }}
  .row {{ display:flex; align-items:center; gap:10px; margin:6px 0; }}
  .lbl {{ width:200px; font-size:0.9em; }}
  .track {{ flex:1; background:#eef2f7; border-radius:6px; height:18px; overflow:hidden; }}
  .fill {{ display:block; height:100%; }}
  .val {{ width:64px; text-align:right; font-variant-numeric:tabular-nums; font-size:0.9em; }}
  footer {{ margin-top:28px; color:#6b7280; font-size:0.85em; }}
</style></head>
<body>
  <h1>Provenance Guard — Analytics</h1>
  <p class="sub">Read-only dashboard derived from the audit log.</p>

  <div class="cards">
    <div class="card"><div class="n">{metrics['total_submissions']}</div><div class="k">submissions</div></div>
    <div class="card"><div class="n">{metrics['total_appeals']}</div><div class="k">appeals</div></div>
    <div class="card"><div class="n">{appeal_pct}</div><div class="k">appeal rate</div></div>
    <div class="card"><div class="n">{mca}</div><div class="k">most common</div></div>
    <div class="card"><div class="n">{metrics['verified_creators']}</div><div class="k">verified creators</div></div>
    <div class="card"><div class="n">{verified_pct}</div><div class="k">subs from verified</div></div>
  </div>

  <h2>Detection patterns (attribution counts)</h2>
  {attr_bars}

  <h2>Average scores (0 = human, 1 = AI)</h2>
  {prob_bars}

  <footer>Rate limit on POST /submit: {metrics['rate_limit']} &middot;
  <a href="/analytics">raw JSON</a></footer>
</body></html>"""
