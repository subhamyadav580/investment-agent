"""Research one company from the command line and print the report.

    uv run python scripts/run_research.py SMPLALPHA [--as-of 2026-10-23] [--json]
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

# Running a file under scripts/ puts scripts/ (not the project root) on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.db.session import session_scope  # noqa: E402
from app.repos.report_repo import ReportRepo  # noqa: E402
from app.services.alerts.notifier import build_notifier  # noqa: E402
from app.services.data.providers.registry import get_providers  # noqa: E402
from app.services.discovery.rules_config import load_screening_config  # noqa: E402
from app.services.graph.deps import GraphDeps  # noqa: E402
from app.services.graph.llm_factory import build_llm  # noqa: E402
from app.services.research.research_service import ResearchError, ResearchService  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("query")
    p.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    p.add_argument("--json", action="store_true", help="print the full report JSON")
    args = p.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level, json_logs=False)
    with session_scope() as session:
        deps = GraphDeps(
            session=session, providers=get_providers(), cfg=load_screening_config(settings.screening_rules_path),
            llm=build_llm(settings), prompt_version=settings.prompt_version,
            quiet_hours=settings.alert_quiet_period_hours, report_base_url=settings.report_base_url,
        )  # fmt: skip
        try:
            outcome = ResearchService(deps, build_notifier(settings)).research(args.query, args.as_of)
        except ResearchError as e:
            sys.exit(f"Research failed: {e}")
        report, _ = ReportRepo(session).get(outcome.report_id)
        doc = report.report_json
        if args.json:
            print(json.dumps(doc, indent=2, default=str))
            return
        print(f"\nReport #{report.id} - {doc['name']} ({doc['exchange']}:{doc['symbol']}) as of {doc['as_of_date']}")
        print(f"Status: {doc['research_status']}   Conclusion: {doc['conclusion']}\n")
        print(doc["executive_summary"], "\n")
        for line in doc["conclusion_rationale"]:
            print(f"  - {line}")
        if doc.get("business_overview"):
            print(f"\nBusiness: {doc['business_overview']}")
        if doc.get("valuation_commentary"):
            print(f"\nValuation: {doc['valuation_commentary']}")
        if doc["risks"]:
            print("\nRisks:")
            for r in doc["risks"]:
                print(f"  - [{r['severity']}] {r['category']}: {r['description']}")
        unverified = [c for c in doc["claims"] if not c["verified"]]
        print(f"\nClaims: {len(doc['claims'])} total, {len(unverified)} unverified")
        for c in unverified:
            print(f"  ! {c['statement'][:120]} -> {c['problems']}")
        print("\nLimitations:")
        for line in doc["data_quality_limitations"]:
            print(f"  - {line}")
        print(f"\n{doc['disclaimer']}")


if __name__ == "__main__":
    main()
