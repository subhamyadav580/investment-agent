"""Research one company from the command line and print the report.

    uv run python scripts/run_research.py SMPLALPHA [--as-of 2026-10-23] [--json]
    uv run python scripts/run_research.py "Research Asian Paints for a 5-year investment"
    uv run python scripts/run_research.py ESDS --horizon medium_term --years 2
    uv run python scripts/run_research.py ESDS --horizon both

Both horizons (long term 5-10 years, medium term 1-3 years) are always assessed; --horizon picks the headline.
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
    p.add_argument("query", nargs="+", help="company name/symbol, optionally with a horizon in words")
    p.add_argument("--horizon", choices=["long_term", "medium_term", "both"], default=None)
    p.add_argument("--years", type=int, default=None, help="investment horizon in years (1-3 or 5-10)")
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
            outcome = ResearchService(deps, build_notifier(settings)).research(
                " ".join(args.query), args.as_of, args.horizon, args.years
            )
        except ResearchError as e:
            sys.exit(f"Research failed: {e}")
        report, _ = ReportRepo(session).get(outcome.report_id)
        doc = report.report_json
        if args.json:
            print(json.dumps(doc, indent=2, default=str))
            return
        print_report(report.id, doc)


def _m(metrics: dict, key: str) -> str:
    m = metrics.get(key)
    if not m or m["value"] is None:
        return "n/a"
    v, unit = m["value"], m["unit"]
    return {"ratio": f"{v:.1%}", "pct": f"{v:.1f}%", "x": f"{v:.1f}x", "pp": f"{v:+.1f} pp"}.get(unit, f"{v:,.2f}")


def _bullets(items, indent="  - "):
    for item in items:
        print(f"{indent}{item}")


def print_report(report_id: int, doc: dict) -> None:
    fa = doc["final_assessment"]
    print(f"\nCOMPANY RESEARCH REPORT #{report_id}: {doc['name']} ({doc['exchange']}:{doc['symbol']}), as of "
          f"{doc['as_of_date']}")  # fmt: skip
    print(f"Sector: {doc['sector'] or 'n/a'} / {doc.get('industry') or 'n/a'}   Research status: {doc['research_status']}")
    for h in fa.get("horizons", {}).values():
        print(f"\n>> {h['horizon_label'].upper()} ({h['years']} years): {h['label'].upper()} - {h['meaning']}")
        print(f"   Main concern: {h['main_concern']}")
    print(doc["executive_summary"])

    co = doc["company_overview"]
    print("\n1. COMPANY OVERVIEW")
    print(f"  What it does: {co['what_it_does'] or 'n/a (narrative analysis unavailable)'}")
    if co["revenue_model"]:
        print(f"  How it makes money: {co['revenue_model']}")
    _bullets([f"Advantage: {a}" for a in co["competitive_advantages"]])
    if co["competitive_position"]:
        print(f"  Position: {co['competitive_position']}")

    fp = doc["financial_performance"]
    hm = fp["headline_metrics"]
    print(f"\n2. FINANCIAL PERFORMANCE ({fp['years_covered']} years of data)")
    print(f"  Revenue CAGR {_m(hm, 'revenue_cagr')} (long run {_m(hm, 'revenue_cagr_long')}), profit CAGR "
          f"{_m(hm, 'profit_cagr')} (long run {_m(hm, 'profit_cagr_long')})")  # fmt: skip
    print(f"  ROCE {_m(hm, 'roce_latest')} (3y avg {_m(hm, 'roce_avg_3y')}), ROE {_m(hm, 'roe_latest')}, operating "
          f"margin {_m(hm, 'operating_margin_latest')}, CFO/PAT 3y {_m(hm, 'cfo_to_pat_3y')}")  # fmt: skip
    print(f"  Debt/equity {_m(hm, 'debt_to_equity')}, net debt/EBITDA {_m(hm, 'net_debt_to_ebitda')}, interest cover "
          f"{_m(hm, 'interest_coverage')}")  # fmt: skip
    peers = doc["peer_comparison"].get("peers") or []
    print(f"  Peers compared: {len(peers)}{' (' + ', '.join(peers[:8]) + ')' if peers else ''}")
    if fp["commentary"]:
        print(f"  {fp['commentary']}")

    v = doc["valuation"]
    print("\n3. VALUATION")
    cur = v.get("current", {})
    x = lambda k: "n/a" if cur.get(k) is None else f"{cur[k]:.1f}x"  # noqa: E731
    print(f"  P/E {x('pe')}, P/B {x('pb')}, EV/EBITDA {x('ev_ebitda')}; vs sector {v.get('vs_sector') or 'n/a'}; "
          f"own history {(v.get('history') or {}).get('position', 'n/a')}")  # fmt: skip
    if fv := v.get("fair_value_range"):
        print(f"  Fair-value range today: {fv['low']:,.2f} / {fv['mid']:,.2f} / {fv['high']:,.2f} vs price {fv['price']:,.2f} "
              f"({fv['basis']})")  # fmt: skip
    for hname, sc in (v.get("scenarios_by_horizon") or {}).items():
        print(f"  {hname.replace('_', '-').capitalize()} scenarios over {sc['years']} year(s) from price {sc['price']} "
              f"({sc['per_share_basis']} {sc['per_share']}):")  # fmt: skip
        for name in ("conservative", "base", "optimistic"):
            x = sc[name]
            print(f"    {name:<12} growth {x['annual_growth']:>6.1%}  exit multiple {x['exit_multiple']:>6.1f}x  value "
                  f"{x['value_per_share_at_horizon']:>10,.2f}  implied {x['implied_annual_price_change']:>6.1%}/yr")  # fmt: skip
        _bullets(sc["assumptions"], "    assumes: ")
    for text in (v.get("commentary"), v.get("scenario_commentary"), v.get("medium_term_view")):
        if text:
            print(f"  {text}")

    mg = doc["management_governance"]
    print("\n4. MANAGEMENT AND GOVERNANCE")
    pr = mg["promoter"]
    print(f"  Promoter holding {_m(pr, 'promoter_holding_pct')} (1y change {_m(pr, 'promoter_holding_change_1y')}), "
          f"pledged {_m(pr, 'promoter_pledged_pct')} of it; return on incremental capital "
          f"{_m(mg['capital_allocation'], 'return_on_incremental_capital')}")  # fmt: skip
    _bullets([f"[{f['severity']}] {f['message']}" for f in mg["flags"]] or ["No governance flags."])
    if mg["commentary"]:
        print(f"  {mg['commentary']}")

    gp = doc["growth_prospects"]
    print("\n5. GROWTH PROSPECTS")
    if t := gp.get("industry_trend"):
        print(f"  Industry ({t['industry']}): median latest-quarter profit growth {t['median_profit_growth_q_yoy']}, "
              f"breadth {t['breadth']}, {'improving' if t['improving'] else 'not improving'}")  # fmt: skip
    if gp["industry_outlook"]:
        print(f"  Outlook: {gp['industry_outlook']}")
    if eo := gp.get("earnings_outlook"):
        print(f"  Earnings outlook (1-3y): {eo['rating']} - {' '.join(eo['reasons'])}")
    if cat := gp.get("catalysts"):
        print(f"  Catalysts: {cat['rating']}")
        _bullets([f"{c.get('date', '')} {c['kind']}: {c['title']}".strip() for c in cat["items"]], "    - ")
    _bullets([f"Driver: {d}" for d in gp["growth_drivers"]] + [f"Filing: {f['date']} {f['title']}" for f in gp["growth_filings"][:5]]
             + [f"Threat: {t}" for t in gp["competitive_threats"]])  # fmt: skip

    rk = doc["risks"]
    print("\n6. RISKS")
    _bullets([f"RED FLAG: {f['message']}" for f in rk["red_flags"]])
    _bullets([f"[{r['severity']}] {r['category']}: {r['description']}" for r in rk["items"]])
    _bullets([f"Downside: {d}" for d in rk["downside_scenarios"]])
    print("  The thesis is invalidated if:")
    _bullets(rk["invalidation_conditions"], "    - ")

    print("\n7. FINAL ASSESSMENT")
    for key, label in (("business_quality", "Business quality"), ("financial_health", "Financial health"),
                       ("management_governance", "Management and governance"), ("valuation", "Valuation"),
                       ("data_quality", "Data quality")):  # fmt: skip
        item = fa[key]
        print(f"  {label:<28} {item['rating']:<11} {' '.join(item['reasons'][:2])[:140]}  [{', '.join(item['evidence_ids'])}]")
    for h in fa.get("horizons", {}).values():
        if len(fa["horizons"]) > 1:
            print(f"  {'Valuation (' + h['horizon_label'].lower() + ')':<28} {h['valuation']['rating']}")
    for h in fa.get("horizons", {}).values():
        print(f"  {'Overall (' + h['horizon_label'].lower() + ', ' + str(h['years']) + 'y)':<28} {h['label']}")
        _bullets(h["reasons"], "    - ")

    unverified = [c for c in doc["claims"] if not c["verified"]]
    print(f"\nClaims: {len(doc['claims'])} total, {len(unverified)} unverified")
    for c in unverified:
        print(f"  ! {c['statement'][:120]} -> {c['problems']}")
    if doc["open_questions"]:
        print("Open questions:")
        _bullets(doc["open_questions"])
    print("Limitations:")
    _bullets(doc["data_quality_limitations"])
    print(f"\n{doc['disclaimer']}")


if __name__ == "__main__":
    main()
