"""Event-driven discovery (plan source C): exchange filings surface companies that weren't on the radar.

Flow: market-wide announcements for the lookback window -> keep discovery categories (results, order wins,
acquisitions, ...) -> screen just those companies with the same versioned rules -> queue the ones that pass.
An event never qualifies a company by itself; it only earns it a screening pass.
"""

import logging
from collections import Counter, defaultdict
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import ScreeningResult, ScreeningRun
from app.repos.screening_repo import ScreeningRepo
from app.services.data.identity import provider_symbol
from app.services.data.providers.registry import Providers
from app.services.discovery.candidate_queue import enqueue_candidates
from app.services.discovery.company_evaluator import evaluate, prepare
from app.services.discovery.data_enrichment import apply_profile, fetch_company_data, persist_company_data
from app.services.discovery.rules_config import ScreeningConfig
from app.services.discovery.sector_trends import industry_of
from app.services.discovery.universe_loader import load_universe

logger = logging.getLogger(__name__)


class EventFeedUnavailable(Exception):
    pass


def run_event_discovery(
    session: Session,
    providers: Providers,
    cfg: ScreeningConfig,
    as_of: date,
    lookback_days: int | None = None,
    max_companies: int = 100,
) -> ScreeningRun:
    feed = getattr(providers.announcements, "market_announcements", None)
    if feed is None:
        raise EventFeedUnavailable(f"announcements provider '{providers.announcements.name}' has no market-wide feed")
    days = cfg.discovery.event_lookback_days if lookback_days is None else lookback_days
    start = as_of - timedelta(days=days)

    triggers: dict[str, list[str]] = defaultdict(list)
    for a in feed(start, as_of):
        if a.category in cfg.discovery.event_categories:
            triggers[a.symbol].append(f"{a.published_at.date()} {a.category}: {a.title}")

    repo = ScreeningRepo(session)
    universe = load_universe(session, providers.universe, cfg.universe)
    by_symbol = {m.company.symbol: m for m in universe.members}
    run = repo.create_run(as_of.isoformat(), f"events:{start}..{as_of}", cfg.version, kind="events")
    session.commit()

    last = repo.latest_completed_run("universe")
    medians_by_sector = (last.summary or {}).get("sector_medians", {}) if last else {}
    improving = {k for k, t in ((last.summary or {}).get("industry_trends", {}) if last else {}).items() if t["improving"]}

    statuses: Counter[str] = Counter()
    ranked: list[tuple[int, float, float]] = []
    skipped = {"not_in_universe": 0, "excluded": 0}
    for symbol in sorted(triggers, key=lambda s: -len(triggers[s]))[:max_companies]:
        m = by_symbol.get(symbol)
        if m is None:
            skipped["not_in_universe"] += 1
            continue
        if m.exclusion:
            skipped["excluded"] += 1
            continue
        data = fetch_company_data(providers, provider_symbol(m.company), as_of)
        group = apply_profile(m.company, data.profile)
        persist_company_data(session, m.company, data)
        ev = evaluate(prepare(data, m.company.sector, group, as_of, cfg), medians_by_sector.get(m.company.sector or ""),
                      as_of, cfg)  # fmt: skip
        e = ev.evaluation
        statuses[e.status] += 1
        tail = industry_of(ev.prepared) in improving
        repo.add_result(ScreeningResult(
            run_id=run.id, company_id=m.company.id, status=e.status, score=e.score,
            dimension_scores={**e.dimension_scores, "missing_components": e.missing_components,
                              "industry": industry_of(ev.prepared), "industry_improving": tail,
                              "trigger_events": triggers[symbol]},
            passed_rules=[r.model_dump() for r in e.passed], failed_rules=[r.model_dump() for r in e.failed],
            exclusion_reasons=e.exclusion_reasons, data_quality=ev.prepared.data_quality.model_dump(mode="json"),
            metrics={k: v for k, v in ev.values.items() if v is not None},
        ))  # fmt: skip
        if e.status == "candidate":
            ranked.append((m.company.id, e.score, e.score + (cfg.discovery.sector_tailwind_boost if tail else 0.0)))
        session.commit()

    ranked.sort(key=lambda x: -x[2])
    for i, (cid, *_rest) in enumerate(ranked, 1):
        repo.result_for_company(run.id, cid).rank = i
    enqueued = enqueue_candidates(session, run.id, ranked, cfg.research.enqueue_top_n, cfg.research.min_score_for_research)
    run.candidate_count = len(ranked)
    run.universe_count = len(triggers)
    run.status, run.finished_at = "completed", utcnow()
    run.summary = {
        "window": [start.isoformat(), as_of.isoformat()],
        "companies_with_events": len(triggers),
        "status_counts": dict(statuses),
        "skipped": skipped,
        "enqueued_for_research": len(enqueued),
    }
    session.commit()
    logger.info("event discovery completed", extra={"run_id": run.id, **run.summary["status_counts"]})
    return run
