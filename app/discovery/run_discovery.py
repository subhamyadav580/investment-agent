"""Mode B end to end: find promising companies without being told which ones.

    python -m app.discovery.run_discovery [--as-of 2026-10-23] [--limit 200] [--research-top 5] [--no-llm]
                                          [--horizon long_term|medium_term|both]

1. Load the eligible universe          4. Rank with the five-category score
2. Collect financial and market data   5. Research the top N in depth (LLM: 3 calls per company)
3. Apply quality and risk filters      6. Print the shortlist with each company's ratings
                                       7. Strong results join the "Auto shortlist" watchlist for monitoring
"""

import argparse
from datetime import date

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import session_scope
from app.services.alerts.notifier import build_notifier
from app.services.data.providers.registry import get_providers
from app.services.discovery.rules_config import load_screening_config
from app.services.discovery.screening_service import run_screening
from app.services.graph.deps import GraphDeps
from app.services.graph.llm_factory import build_llm
from app.services.research.research_service import ResearchService
from app.services.research.shortlist import shortlist


def main() -> None:
    p = argparse.ArgumentParser(description="Screen the universe, research the best candidates, print the shortlist.")
    p.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    p.add_argument("--limit", type=int, default=None, help="screen at most N companies (most liquid first)")
    p.add_argument("--symbols", default=None, help="only screen these companies, comma-separated")
    p.add_argument("--research-top", type=int, default=5, help="research this many top-ranked candidates")
    p.add_argument("--no-llm", action="store_true", help="deterministic research only (no LLM calls, no cost)")
    p.add_argument("--horizon", choices=["long_term", "medium_term", "both"], default="long_term",
                   help="which horizon ranks candidates (both: rank long term, show both)")
    args = p.parse_args()

    settings = get_settings()
    if args.no_llm:
        settings = settings.model_copy(update={"llm_enabled": False})
    configure_logging(settings.log_level, json_logs=False)
    cfg = load_screening_config(settings.screening_rules_path)
    providers = get_providers()

    with session_scope() as session:
        symbols = [x.strip() for x in args.symbols.split(",")] if args.symbols else None
        rank_by = "medium_term" if args.horizon == "medium_term" else "long_term"
        run = run_screening(session, providers, cfg, args.as_of, args.research_top, symbols, args.limit, rank_by)
        session.commit()
        print(f"Screening run #{run.id}: {run.summary['status_counts']}; queued {run.summary['enqueued_for_research']} "
              "for research.")  # fmt: skip

        deps = GraphDeps(
            session=session, providers=providers, cfg=cfg, llm=build_llm(settings),
            prompt_version=settings.prompt_version, quiet_hours=settings.alert_quiet_period_hours,
            report_base_url=settings.report_base_url,
        )  # fmt: skip
        out = ResearchService(deps, build_notifier(settings), settings.alert_max_delivery_attempts).process_queue(
            args.research_top, settings.research_max_attempts, args.as_of, args.horizon
        )
        print(f"Researched {out.processed}: {out.succeeded} succeeded, {out.failed} failed. "
              f"Now monitoring: {', '.join(out.newly_monitored) or 'none new'}.\n")  # fmt: skip

        rows = shortlist(session, cfg, horizon=rank_by)
        if not rows:
            print("Shortlist is empty: no researched company is currently classified as a candidate.")
            return
        print(f"Ranked shortlist ({rank_by.replace('_', ' ')}):")
        print(f"{'#':>2} {'SYMBOL':<12} {'LONG TERM':<36} {'MEDIUM TERM':<36} {'SCORE':>5}  MAIN CONCERN")
        for r in rows:
            score = f"{r.score:5.1f}" if r.score is not None else "    -"
            print(f"{r.rank:>2} {r.symbol:<12} {(r.long_term or '-'):<36} {(r.medium_term or '-'):<36} {score}  "
                  f"{(r.main_concern or '')[:70]}")  # fmt: skip
        print("\nResearch assessments only, not investment advice. Open a report with: "
              "uv run python scripts/run_research.py <SYMBOL>  (or GET /research/reports/{id})")  # fmt: skip


if __name__ == "__main__":
    main()
