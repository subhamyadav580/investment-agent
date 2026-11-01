"""End-to-end screening run (plan section 16):
load universe -> exclude instruments -> enrich -> validate -> metrics -> rules -> score -> rank -> persist -> enqueue.
"""

import logging
from collections import Counter
from datetime import date

from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import ScreeningResult, ScreeningRun
from app.repos.screening_repo import ScreeningRepo
from app.services.data.identity import provider_symbol
from app.services.data.providers.registry import Providers
from app.services.discovery.candidate_queue import enqueue_candidates
from app.services.discovery.company_evaluator import EvaluatedCompany, PreparedCompany, evaluate, prepare
from app.services.discovery.data_enrichment import apply_profile, fetch_company_data, persist_company_data
from app.services.discovery.rules_config import ScreeningConfig
from app.services.discovery.sector_trends import compute_industry_trends, industry_of
from app.services.discovery.universe_loader import UniverseMember, load_universe
from app.services.research.peer_comparison import sector_medians

logger = logging.getLogger(__name__)

COMMIT_EVERY = 50


def run_screening(
    session: Session,
    providers: Providers,
    cfg: ScreeningConfig,
    as_of: date,
    enqueue_top_n: int | None = None,
    symbols: list[str] | None = None,
    limit: int | None = None,
    horizon: str = "long_term",
) -> ScreeningRun:
    """`symbols` restricts the run to those companies; `limit` caps how many in-scope companies are fetched
    (most liquid first when prices are synced). Both are for partial/test runs. `horizon` (long_term |
    medium_term) chooses which score ranks the candidates and orders the research queue."""
    repo = ScreeningRepo(session)
    universe = load_universe(session, providers.universe, cfg.universe)
    run = repo.create_run(as_of.isoformat(), universe.version, cfg.version)
    run.universe_count = len(universe.members)
    session.commit()  # the run record must exist even if processing fails later

    try:
        _process(session, providers, cfg, as_of, run, universe, enqueue_top_n, symbols, limit, horizon)
    except Exception as e:
        session.rollback()
        run = repo.get_run(run.id)
        run.status, run.error, run.finished_at = "failed", f"{type(e).__name__}: {e}", utcnow()
        session.commit()
        logger.exception("screening run failed", extra={"run_id": run.id})
        raise
    return run


def _liquidity_prefilter(providers: Providers, members: list[UniverseMember], cfg: ScreeningConfig, as_of: date):
    """Split members into (to_fetch, rejected_with_reason) using synced exchange prices, so we don't fetch
    fundamentals for stocks the liquidity rule would reject anyway. No-op when prices aren't synced."""
    snapshot = getattr(providers.market_data, "liquidity_snapshot", None)
    if not cfg.discovery.liquidity_prefilter or snapshot is None:
        return members, []
    liq = snapshot(as_of)
    if not liq:
        return members, []
    has_bse = any(k.isdigit() for k in liq)
    floor = cfg.liquidity.min_avg_traded_value_cr
    keep, rejected = [], []
    for m in members:
        key = provider_symbol(m.company)
        if key.isdigit() and not has_bse:
            keep.append(m)  # BSE prices not synced: can't judge, so don't pre-reject
            continue
        value = liq.get(key)
        if value is None or value < floor:
            shown = "no trades" if value is None else f"{value:.2f}"
            rejected.append((m, f"liquidity pre-filter: avg daily traded value (INR cr) {shown} < {floor:.2f}"))
        else:
            keep.append(m)
    keep.sort(key=lambda m: -liq.get(provider_symbol(m.company), 0.0))
    return keep, rejected


def _process(session, providers, cfg, as_of, run, universe, enqueue_top_n, symbols=None, limit=None,
             horizon="long_term") -> None:  # fmt: skip
    repo = ScreeningRepo(session)
    statuses: Counter[str] = Counter()

    members = universe.members
    if symbols:
        wanted = {s.upper() for s in symbols}
        members = [m for m in members if m.company.symbol in wanted or (m.company.bse_code or "") in wanted]
    for m in members:
        if m.exclusion:
            repo.add_result(ScreeningResult(run_id=run.id, company_id=m.company.id, status="excluded_instrument",
                                            exclusion_reasons=[m.exclusion]))  # fmt: skip
            statuses["excluded_instrument"] += 1

    in_scope, prefiltered = _liquidity_prefilter(providers, [m for m in members if m.exclusion is None], cfg, as_of)
    for m, reason in prefiltered:
        repo.add_result(ScreeningResult(run_id=run.id, company_id=m.company.id, status="rejected",
                                        exclusion_reasons=[reason]))  # fmt: skip
        statuses["rejected"] += 1
    if limit is not None:
        in_scope = in_scope[:limit]

    # Pass 1: fetch, persist provenance, validate, compute metrics.
    prepared: dict[int, PreparedCompany] = {}
    for i, m in enumerate(in_scope, 1):
        data = fetch_company_data(providers, provider_symbol(m.company), as_of)
        group = apply_profile(m.company, data.profile)
        persist_company_data(session, m.company, data)
        prepared[m.company.id] = prepare(data, m.company.sector, group, as_of, cfg)
        if i % COMMIT_EVERY == 0:
            session.commit()
            logger.info("screening progress", extra={"run_id": run.id, "prepared": i, "total": len(in_scope)})

    # Pass 2: peer context from data-eligible companies only.
    eligible = {cid: p for cid, p in prepared.items() if p.data_quality.is_eligible}
    medians = sector_medians({p.symbol: p.values for p in eligible.values()}, {p.symbol: p.sector for p in eligible.values()})
    trends = compute_industry_trends(prepared.values(), cfg.discovery.min_industry_companies)
    improving = {ind for ind, t in trends.items() if t["improving"]}

    # Pass 3: rules + scoring.
    tailwind = {cid: industry_of(p) in improving for cid, p in prepared.items()}
    evaluated: dict[int, EvaluatedCompany] = {
        cid: evaluate(p, medians.get(p.sector or ""), as_of, cfg, tailwind[cid]) for cid, p in prepared.items()
    }
    ranked = sorted(
        ((cid, e.evaluation.horizon_scores.get(horizon, e.evaluation.score)) for cid, e in evaluated.items()
         if e.evaluation.status == "candidate"),
        key=lambda x: -x[1],
    )  # fmt: skip
    rank_of = {cid: i for i, (cid, _) in enumerate(ranked, 1)}

    for cid, e in evaluated.items():
        ev = e.evaluation
        statuses[ev.status] += 1
        repo.add_result(
            ScreeningResult(
                run_id=run.id,
                company_id=cid,
                status=ev.status,
                score=ev.score,
                rank=rank_of.get(cid),
                dimension_scores={**ev.dimension_scores, "missing_components": ev.missing_components,
                                  "industry": industry_of(e.prepared), "industry_improving": tailwind[cid],
                                  "horizon_scores": ev.horizon_scores, "medium_term": ev.medium_term_scores},  # fmt: skip
                passed_rules=[r.model_dump() for r in ev.passed],
                failed_rules=[r.model_dump() for r in ev.failed],
                exclusion_reasons=ev.exclusion_reasons,
                data_quality=e.prepared.data_quality.model_dump(mode="json"),
                metrics={k: v for k, v in e.values.items() if v is not None},
            )
        )

    top_n = cfg.research.enqueue_top_n if enqueue_top_n is None else enqueue_top_n
    boost = cfg.discovery.sector_tailwind_boost
    prioritized = sorted(((cid, score, score + (boost if tailwind[cid] else 0.0)) for cid, score in ranked),
                         key=lambda x: -x[2])  # fmt: skip
    enqueued = enqueue_candidates(session, run.id, prioritized, top_n, cfg.research.min_score_for_research)

    run.candidate_count = len(ranked)
    run.status = "completed"
    run.finished_at = utcnow()
    run.summary = {
        "status_counts": dict(statuses),
        "in_scope": len(in_scope) + len(prefiltered),
        "fetched": len(in_scope),
        "liquidity_prefiltered": len(prefiltered),
        "enqueued_for_research": len(enqueued),
        "ranked_by": horizon,
        "sector_medians": medians,
        "industry_trends": trends,
    }
    session.commit()
    logger.info("screening run completed", extra={"run_id": run.id, **run.summary["status_counts"]})
