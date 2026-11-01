"""Mode B output: the shortlist of researched companies, and automatic monitoring of the best of them.

Companies researched from the discovery queue whose classification is in `assessment.auto_watchlist_classes` are
added to an auto-managed watchlist, so the daily monitoring job tracks them for results, governance events and
broken invalidation conditions. Entries you have edited are never overwritten.
"""

from datetime import date

from sqlalchemy.orm import Session

from app.models import Company, WatchlistCompany
from app.repos.report_repo import ReportRepo
from app.repos.watchlist_repo import WatchlistRepo
from app.schemas.research import ShortlistItemOut
from app.services.discovery.rules_config import ScreeningConfig
from app.services.research.assessment import LABELS

RATING_KEYS = ("business_quality", "financial_health", "management_governance", "valuation", "data_quality")


def shortlist(session: Session, cfg: ScreeningConfig, limit: int = 50, horizon: str = "long_term") -> list[ShortlistItemOut]:
    """Ranked shortlist for one horizon: latest report per company whose classification for that horizon is
    shortlisted; best classification first, then that horizon's score."""
    classes = cfg.assessment.shortlist_classes
    order = {c: i for i, c in enumerate(classes)}
    candidates = []
    for r, c in ReportRepo(session).latest_per_company():
        fa = r.report_json.get("final_assessment", {})
        h = fa.get("horizons", {}).get(horizon)
        cls = h["classification"] if h else (r.conclusion if horizon == "long_term" else None)
        if cls in order:
            candidates.append((order[cls], -((h or {}).get("score") or r.report_json.get("screening_score") or 0), r, c, h))
    candidates.sort(key=lambda x: (x[0], x[1]))
    out = []
    for rank, (_, _, r, c, h) in enumerate(candidates[:limit], 1):
        doc = r.report_json
        fa = doc.get("final_assessment", {})
        hz = fa.get("horizons", {})
        cls = h["classification"] if h else r.conclusion
        out.append(ShortlistItemOut(
            rank=rank, report_id=r.id, symbol=c.symbol, name=c.name, sector=c.sector, as_of_date=r.as_of_date,
            conclusion=cls, conclusion_label=LABELS.get(cls, cls),
            score=(h or {}).get("score", doc.get("screening_score")),
            ratings={k: fa[k]["rating"] for k in RATING_KEYS if k in fa},
            red_flags=len(doc.get("risks", {}).get("red_flags", [])),
            main_concern=(h or {}).get("main_concern"),
            long_term=hz.get("long_term", {}).get("label"), medium_term=hz.get("medium_term", {}).get("label"),
            why=(h or {}).get("reasons", doc.get("conclusion_rationale", []))[:2], created_at=r.created_at,
        ))  # fmt: skip
    return out


def monitor_if_shortlisted(session: Session, company: Company, doc: dict, cfg: ScreeningConfig, as_of: date) -> bool:
    """`doc["conclusion"]` is the classification for the horizon the research was run for."""
    """Add a strong discovery result to the auto watchlist. Returns True when a new entry was created."""
    a = cfg.assessment
    if not a.auto_watchlist or doc["conclusion"] not in a.auto_watchlist_classes:
        return False
    repo = WatchlistRepo(session)
    wl = repo.get_by_name(a.auto_watchlist) or repo.create(a.auto_watchlist)
    if repo.get_entry(wl.id, company.id):
        return False
    repo.add_entry(WatchlistCompany(
        watchlist_id=wl.id, company_id=company.id,
        thesis=f"Auto-added by discovery on {as_of}: {doc['conclusion_label']}. Review and replace this with your "
               "own thesis before relying on it.",
        assumptions=doc.get("valuation", {}).get("assumptions", []),
        invalidation_conditions=default_conditions(doc, cfg),
        needs_review=True,
    ))  # fmt: skip
    return True


def default_conditions(doc: dict, cfg: ScreeningConfig) -> list[dict]:
    """Measurable conditions derived from the screening thresholds (checked on every monitoring run)."""
    q = cfg.quality
    if "roe_avg_3y" in doc["final_assessment"]["business_quality"]["metric_refs"]:  # lender
        return [
            {"metric": "roe_latest", "op": "<", "value": q.min_roe_financial, "description": "ROE below threshold"},
            {"metric": "gross_npa_pct", "op": ">", "value": q.max_gross_npa_pct, "description": "Gross NPA too high"},
        ]
    return [
        {"metric": "roce_latest", "op": "<", "value": q.min_roce, "description": "ROCE below threshold"},
        {"metric": "debt_to_equity", "op": ">", "value": q.max_debt_to_equity, "description": "Leverage too high"},
        {"metric": "interest_coverage", "op": "<", "value": q.min_interest_coverage, "description": "Weak interest cover"},
        {"metric": "cfo_to_pat_3y", "op": "<", "value": q.min_cfo_to_pat, "description": "Poor cash conversion"},
    ]
