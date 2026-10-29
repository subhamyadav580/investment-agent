"""Screen companies that filed results / order wins / acquisitions etc. in the last few days.

    python -m app.discovery.run_event_discovery [--as-of 2026-10-23] [--days 2]
"""

import argparse
from datetime import date

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import session_scope
from app.repos.screening_repo import ScreeningRepo
from app.services.data.providers.registry import get_providers
from app.services.discovery.event_discovery import run_event_discovery
from app.services.discovery.rules_config import load_screening_config


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    p.add_argument("--days", type=int, default=None, help="lookback window (default from config)")
    p.add_argument("--max-companies", type=int, default=100)
    args = p.parse_args()
    s = get_settings()
    configure_logging(s.log_level, json_logs=False)
    with session_scope() as session:
        run = run_event_discovery(session, get_providers(), load_screening_config(s.screening_rules_path), args.as_of,
                                  args.days, args.max_companies)  # fmt: skip
        print(f"\nEvent discovery run #{run.id}  window={run.summary['window']}  "
              f"companies with events={run.summary['companies_with_events']}")  # fmt: skip
        print(f"Summary: {run.summary['status_counts']}  skipped={run.summary['skipped']}  "
              f"enqueued={run.summary['enqueued_for_research']}\n")  # fmt: skip
        for r, c in ScreeningRepo(session).results_for_run(run.id):
            score = f"{r.score:6.1f}" if r.score is not None else "     -"
            print(f"{c.symbol:<14} {r.status:<18} {score}  {r.dimension_scores.get('trigger_events', [''])[0][:80]}")
            if r.exclusion_reasons:
                print(f"{'':<41}{r.exclusion_reasons[0][:100]}")


if __name__ == "__main__":
    main()
