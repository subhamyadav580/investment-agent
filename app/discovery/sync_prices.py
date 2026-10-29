"""Download exchange daily price files (bhavcopy) into the database.

    python -m app.discovery.sync_prices [--days 400] [--exchanges NSE,BSE] [--end 2026-10-23]

First run backfills `--days` calendar days (~1.5 requests/sec max, so 400 days of NSE ~ 10 minutes); later
runs only fetch days not yet processed.
"""

import argparse
from datetime import date

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import session_scope
from app.services.data.price_sync import sync_prices
from app.services.data.providers.registry import build_http_client


def main() -> None:
    s = get_settings()
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--days", type=int, default=s.price_backfill_days)
    p.add_argument("--exchanges", default=",".join(s.price_sync_exchanges), help="comma-separated: NSE,BSE")
    p.add_argument("--end", type=date.fromisoformat, default=date.today())
    args = p.parse_args()
    configure_logging(s.log_level, json_logs=False)
    with session_scope() as session:
        out = sync_prices(session, build_http_client(s), args.exchanges.upper().split(","), args.days, args.end)
    print(f"loaded files: {out.loaded}  holidays/unpublished: {out.missing}")
    for e in out.errors:
        print(f"  error: {e}")


if __name__ == "__main__":
    main()
