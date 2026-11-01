"""Prompt loading and context rendering for the analysis nodes."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.graph.state import ResearchState

PROMPTS_DIR = Path(__file__).parent / "prompts"


@lru_cache
def load_prompt(version: str, name: str) -> str:
    return (PROMPTS_DIR / version / f"{name}.md").read_text().strip()


def system_prompt(version: str, task: str) -> str:
    return f"{load_prompt(version, 'system')}\n\n{load_prompt(version, task)}"


def _fmt(v: Any, unit: str) -> str:
    if v is None:
        return "n/a"
    if unit == "ratio":
        return f"{v * 100:.2f}%"
    if unit == "pct":
        return f"{v:.2f}%"
    if unit == "x":
        return f"{v:.2f}x"
    return f"{v:,.2f} {unit}"


def render_context(state: ResearchState, *, include_valuation: bool = True) -> str:
    """Deterministic, stably-ordered text block (stable ordering keeps prompt caching effective)."""
    ev = state["evaluated"]
    dq = state["data_quality"]
    lines = [
        f"COMPANY: {state['company_name']} ({state['exchange']}:{state['symbol']})",
        f"SECTOR: {state.get('sector') or 'unknown'} | industry: {state.get('industry') or 'unknown'} | "
        f"group: {state['sector_group']} | as of {state['as_of_date']}",
        f"SCREENING: status={ev.evaluation.status} long-term score={ev.evaluation.score} "
        f"dimensions={json.dumps(ev.evaluation.dimension_scores)}",
        f"HORIZONS: requested={state.get('horizon') or 'long_term'} years={json.dumps(state.get('horizon_years') or {})} "
        f"medium-term score={ev.evaluation.horizon_scores.get('medium_term')} "
        f"medium-term categories={json.dumps(ev.evaluation.medium_term_scores)}",
        "CATALYSTS (from filings/industry data only): "
        + (json.dumps([{k: v for k, v in c.items() if k != 'evidence_key'} for c in ev.evaluation.catalysts])
           if ev.evaluation.catalysts else "none evidenced"),
        "",
        "METRICS (key | value | period | note):",
    ]
    for key, m in sorted(state["metrics"].items()):
        note = f" | {m['note']}" if m.get("note") else ""
        lines.append(f"- {key} | {_fmt(m['value'], m['unit'])} | {m.get('period') or ''}{note}")

    lines += ["", "ANNUAL FINANCIALS (INR crore):"]
    fin = ev.prepared.data.financials
    if fin:
        periods = fin.periods()
        lines.append("metric | " + " | ".join(periods))
        for metric in sorted({v.metric for v in fin.values}):
            series = fin.series(metric)
            lines.append(f"{metric} | " + " | ".join(_cell(series.get(p)) for p in periods))

    lines += ["", "SHAREHOLDING (period end | promoter % | % of promoter holding pledged):"]
    holdings = ev.prepared.data.shareholding[-8:]
    lines += [f"- {h.period_end} | {_cell(h.promoter_holding_pct)} | {_cell(h.promoter_pledged_pct)}" for h in holdings]
    lines += [] if holdings else ["- not available"]

    lines += ["", "INDUSTRY TREND (latest-quarter YoY across listed peers in the same industry):"]
    trend = state.get("industry_trend")
    lines.append(json.dumps(trend, default=str) if trend else "- not available (no universe screening run covering "
                 "enough companies in this industry)")  # fmt: skip

    lines += ["", "SCREENING RULES:"]
    for r in ev.rules:
        lines.append(f"- {r.rule_id} [{r.stage}] {r.status}: {r.message}")
    lines += ["", "GOVERNANCE FLAGS:"] + ([f"- {f.severity}: {f.code}: {f.message}" for f in ev.flags] or ["- none"])
    lines += ["", f"DATA QUALITY: score {dq.score}, {dq.years_available} years, latest {dq.latest_period}"]
    lines += [f"- {i.severity}: {i.code}: {i.message}" for i in dq.issues] or ["- no issues"]

    if include_valuation:
        lines += ["", "VALUATION:", json.dumps(state["valuation"], default=str, indent=1)]
        lines += ["", "PEER COMPARISON:", json.dumps(state["peer_comparison"], default=str, indent=1)]

    lines += ["", "EVIDENCE:"]
    for e in state["evidence"]:
        synthetic = " [SYNTHETIC]" if e["is_synthetic"] else ""
        lines.append(f"- {e['id']}: {e['source_type']} | {e.get('title')} | published {e.get('published_at')}{synthetic}")

    anns = ev.prepared.data.announcements
    if anns:
        lines += ["", "DOCUMENTS:"]
        key_to_id = {v: k for k, v in state["evidence_key_by_id"].items()}
        for a in anns:
            lines.append(
                f'<untrusted_document evidence_id="{key_to_id.get(a.source.key)}" category="{a.category}">\n'
                f"{a.title}\n{a.summary or ''}\npublished: {a.published_at.isoformat()}"
                f"{f' | event date: {a.event_date}' if a.event_date else ''}\n</untrusted_document>"
            )
    return "\n".join(lines)


def _cell(v: float | None) -> str:
    return "n/a" if v is None else f"{v:,.2f}"
