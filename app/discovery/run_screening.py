"""CLI entrypoint for the first milestone:

    python -m app.discovery.run_screening [--as-of 2026-10-23] [--top 20] [--enqueue-top-n 30]
                                         [--symbols ESDS,TCS] [--limit 50]
"""

import argparse
from datetime import date

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import session_scope
from app.repos.screening_repo import ScreeningRepo
from app.services.data.providers.registry import get_providers
from app.services.discovery.rules_config import load_screening_config
from app.services.discovery.screening_service import run_screening


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a deterministic screening pass over the equity universe.")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--top", type=int, default=25, help="rows to print")
    parser.add_argument("--enqueue-top-n", type=int, default=None, help="override research queue size")
    parser.add_argument("--symbols", default=None, help="only these companies, comma-separated")
    parser.add_argument("--limit", type=int, default=None, help="fetch at most N companies (most liquid first)")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level, json_logs=False)
    cfg = load_screening_config(settings.screening_rules_path)

    with session_scope() as session:
        symbols = [x.strip() for x in args.symbols.split(",")] if args.symbols else None
        run = run_screening(session, get_providers(), cfg, args.as_of, args.enqueue_top_n, symbols, args.limit)
        rows = ScreeningRepo(session).results_for_run(run.id)
        print(f"\nScreening run #{run.id}  as_of={run.as_of_date}  rules={run.rules_version}  "
              f"universe={run.universe_version}  status={run.status}")  # fmt: skip
        print(f"Summary: {run.summary['status_counts']}  enqueued={run.summary['enqueued_for_research']}\n")
        print(f"{'#':>3}  {'SYMBOL':<14} {'STATUS':<20} {'SCORE':>6}  REASONS / TOP FAILED RULES")
        for result, company in rows[: args.top]:
            reasons = result.exclusion_reasons or [f"{r['rule_id']}: {r['message']}" for r in result.failed_rules]
            score = f"{result.score:6.1f}" if result.score is not None else "     -"
            print(f"{result.rank or '':>3}  {company.symbol:<14} {result.status:<20} {score}  "
                  f"{(reasons[0] if reasons else 'all rules passed')[:110]}")  # fmt: skip
            for extra in reasons[1:3]:
                print(f"{'':>48}{extra[:110]}")
        trends = run.summary.get("industry_trends") or {}
        if trends:
            print("\nIndustry earnings trends (latest quarter, median YoY profit growth):")
            for name, t in list(trends.items())[:10]:
                flag = "IMPROVING" if t["improving"] else ""
                pct = lambda v: "n/a" if v is None else f"{v:+.0%}"  # noqa: E731
                print(f"  {name[:34]:<34} n={t['companies']:<3} now {pct(t['median_profit_growth_q_yoy']):>6} "
                      f"prev {pct(t['median_profit_growth_q_yoy_prev']):>6} breadth {t['breadth'] or 0:.0%} {flag}")


if __name__ == "__main__":
    main()
