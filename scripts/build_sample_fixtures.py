"""Generates data/fixtures/sample_market.json - a SYNTHETIC market of fictional companies.

Each company exercises a different path through screening (strong compounder, leveraged cyclical, bank,
cash-flow divergence, governance event, stale data, short history, illiquid, conflicting sources, SME, ETF).
None of these companies or figures are real.

    uv run python scripts/build_sample_fixtures.py
"""

import json
from pathlib import Path

AS_OF = "2026-10-23"
YEARS = [2021, 2022, 2023, 2024, 2025, 2026]
OUT = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "sample_market.json"


def non_financial(
    rev0, growth, margin, *, dep_pct=0.03, interest=5.0, other_pct=0.01, equity0=400.0, debt=50.0, cash=40.0,
    cfo_ratio=0.95, receivable_days=55, years=YEARS, growth_path=None, margin_path=None, receivable_path=None,
    debt_path=None,
):  # fmt: skip
    out, rev, equity = {}, rev0, equity0
    for i, y in enumerate(years):
        if i:
            rev *= 1 + (growth_path[i] if growth_path else growth)
        m = margin_path[i] if margin_path else margin
        op = rev * m
        dep = rev * dep_pct
        d = debt_path[i] if debt_path else debt
        intr = interest if not debt_path else d * 0.1
        pbt = op - dep - intr + rev * other_pct
        tax = max(pbt, 0) * 0.25
        np_ = pbt - tax
        equity += np_ * 0.8
        rd = receivable_path[i] if receivable_path else receivable_days
        out[f"FY{y}"] = {
            "revenue": round(rev, 2),
            "operating_profit": round(op, 2),
            "depreciation": round(dep, 2),
            "interest": round(intr, 2),
            "pbt": round(pbt, 2),
            "net_profit": round(np_, 2),
            "exceptional_items": 0.0,
            "total_equity": round(equity, 2),
            "total_debt": round(d, 2),
            "cash_and_equivalents": round(cash, 2),
            "total_assets": round(equity + d + rev * 0.3, 2),
            "receivables": round(rev * rd / 365, 2),
            "cfo": round(np_ * cfo_ratio if np_ > 0 else np_ * 0.5, 2),
        }
    return out


def bank(assets0, growth, roa, *, equity_ratio=0.11, gnpa=2.5, car=17.5):
    out, assets = {}, assets0
    for i, y in enumerate(YEARS):
        if i:
            assets *= 1 + growth
        np_ = assets * roa
        out[f"FY{y}"] = {
            "revenue": round(assets * 0.095, 2),
            "net_interest_income": round(assets * 0.042, 2),
            "interest": round(assets * 0.052, 2),
            "pbt": round(np_ / 0.75, 2),
            "net_profit": round(np_, 2),
            "total_equity": round(assets * equity_ratio, 2),
            "total_assets": round(assets, 2),
            "gross_npa_pct": round(gnpa + (0.6 if i < 2 else 0.0), 2),
            "net_npa_pct": round(gnpa * 0.35, 2),
            "capital_adequacy_ratio": car,
        }
    return out


def price_model(annual, shares_cr, target_pe, avg_volume, drift=0.12, vol=0.016):
    latest = annual[max(annual, key=lambda p: int(p[2:]))]
    end_price = target_pe * latest["net_profit"] / shares_cr if latest["net_profit"] > 0 else 50.0
    return {"end_price": round(end_price, 2), "last_date": AS_OF, "days": 1100, "annual_drift": drift,
            "daily_vol": vol, "avg_volume": avg_volume}  # fmt: skip


def holding(promoter, pledged, promoter_year_ago=None):
    return [
        {"period_end": "2025-09-30", "promoter_holding_pct": promoter_year_ago or promoter, "promoter_pledged_pct": pledged},
        {"period_end": "2026-09-30", "promoter_holding_pct": promoter, "promoter_pledged_pct": pledged},
    ]


def results_notice(symbol, date="2026-10-20", event="2026-10-29"):
    return {"category": "board_meeting", "title": f"{symbol}: board meeting to consider Q2 FY2027 results",
            "published_at": f"{date}T10:00:00+05:30", "event_date": event}  # fmt: skip


def company(sector, industry, annual, shares, target_pe, volume, **extra):
    src = {"source_type": "fixture", "title": "SYNTHETIC sample financials (fictional company)",
           "published_at": "2026-05-20T18:00:00+05:30"}  # fmt: skip
    doc = {"sector": sector, "industry": industry, "unit": "INR_crore", "consolidation": "consolidated",
           "shares_outstanding_cr": shares, "source": src, "annual": annual,
           "price_model": price_model(annual, shares, target_pe, volume)}  # fmt: skip
    doc.update(extra)
    return doc


def build():
    c = {}
    alpha = non_financial(800, 0.15, 0.21, equity0=600, debt=60, interest=6)
    c["SMPLALPHA"] = company("Industrials", "Industrial Machinery", alpha, 12.0, 28, 180_000,
                             shareholding=holding(58.0, 0.0), announcements=[results_notice("SMPLALPHA")])  # fmt: skip
    beta = non_financial(1500, 0.11, 0.19, equity0=900, debt=0, interest=0, cash=300, dep_pct=0.02)
    c["SMPLBETA"] = company("Consumer Staples", "Packaged Foods", beta, 20.0, 62, 300_000,
                            shareholding=holding(65.0, 0.0))  # fmt: skip
    gamma = non_financial(5000, 0.05, 0.12, dep_pct=0.05, equity0=1500,
                          growth_path=[0, 0.25, -0.18, 0.10, -0.05, 0.08],
                          margin_path=[0.16, 0.20, 0.07, 0.12, 0.085, 0.10],
                          debt_path=[2600, 2800, 3000, 3100, 3200, 3300])  # fmt: skip
    c["SMPLGAMMA"] = company("Materials", "Steel", gamma, 50.0, 9, 900_000, shareholding=holding(52.0, 12.0))
    delta = bank(20000, 0.18, 0.016)
    c["SMPLDELTA"] = company("Financial Services", "Small Finance Bank", delta, 80.0, 14, 1_500_000,
                             shareholding=holding(40.0, 0.0))  # fmt: skip
    eps = non_financial(1200, 0.18, 0.14, equity0=700, debt=400, interest=40, cfo_ratio=-0.1,
                        receivable_path=[90, 110, 130, 150, 175, 200])  # fmt: skip
    c["SMPLEPSILON"] = company("Industrials", "Construction & Engineering", eps, 15.0, 22, 400_000,
                               shareholding=holding(55.0, 8.0))  # fmt: skip
    zeta = non_financial(950, 0.13, 0.23, equity0=800, debt=30, interest=3)
    c["SMPLZETA"] = company(
        "Health Care", "Pharmaceuticals", zeta, 10.0, 24, 250_000, shareholding=holding(60.0, 0.0),
        announcements=[{"category": "auditor_resignation",
                        "title": "SMPLZETA: Resignation of statutory auditor citing non-receipt of information",
                        "published_at": "2026-09-12T19:30:00+05:30"}],
    )  # fmt: skip
    eta = non_financial(600, 0.06, 0.12, years=[2021, 2022, 2023])
    c["SMPLETA"] = company("Consumer Discretionary", "Textiles", eta, 8.0, 15, 120_000)
    theta = non_financial(300, 0.30, 0.25, years=[2025, 2026], equity0=500, debt=0, interest=0)
    c["SMPLTHETA"] = company("Information Technology", "IT Services", theta, 6.0, 40, 200_000)
    iota = non_financial(400, 0.12, 0.18, equity0=350, debt=40, interest=4)
    c["SMPLIOTA"] = company("Materials", "Specialty Chemicals", iota, 4.0, 20, 300,
                            shareholding=holding(70.0, 0.0))  # fmt: skip
    kappa = non_financial(2200, 0.14, 0.11, equity0=1100, debt=200, interest=20)
    c["SMPLKAPPA"] = company(
        "Consumer Discretionary", "Retail", kappa, 25.0, 35, 500_000, shareholding=holding(51.0, 0.0),
        alternate_values=[{"period": "FY2025", "metric": "revenue", "value": round(kappa["FY2025"]["revenue"] * 0.88, 2),
                           "source_type": "secondary", "source_title": "Secondary aggregator (synthetic)"}],
    )  # fmt: skip
    mu = non_financial(1800, 0.10, 0.15, equity0=1000, debt=350, interest=30)
    c["SMPLMU"] = company("Consumer Discretionary", "Auto Components", mu, 30.0, 18, 600_000,
                          shareholding=holding(48.0, 32.0, promoter_year_ago=55.0))  # fmt: skip
    nu = non_financial(650, 0.09, 0.13, equity0=500, debt=120, interest=11)
    c["SMPLNU"] = company("Industrials", "Electrical Equipment", nu, 9.0, 21, 350_000,
                          shareholding=holding(62.0, 0.0))  # fmt: skip
    lam = non_financial(80, 0.25, 0.15, equity0=40, debt=10, interest=1)
    c["SMPLLAMBDA"] = company("Consumer Staples", "Agri Products", lam, 1.0, 20, 5_000)

    universe = [
        {"symbol": s, "name": n, "isin": f"INE9{i:02d}X0101{i % 10}", "series": ser, "instrument_type": it,
         "is_sme": ser == "SM", "listed_on": lo}
        for i, (s, n, ser, it, lo) in enumerate([
            ("SMPLALPHA", "Alpha Precision Engineering Ltd (SAMPLE)", "EQ", "EQUITY", "2008-04-10"),
            ("SMPLBETA", "Beta Consumer Brands Ltd (SAMPLE)", "EQ", "EQUITY", "2004-01-15"),
            ("SMPLGAMMA", "Gamma Steel & Alloys Ltd (SAMPLE)", "EQ", "EQUITY", "1996-07-01"),
            ("SMPLDELTA", "Delta Small Finance Bank Ltd (SAMPLE)", "EQ", "EQUITY", "2018-11-20"),
            ("SMPLEPSILON", "Epsilon Infra Projects Ltd (SAMPLE)", "EQ", "EQUITY", "2012-03-05"),
            ("SMPLZETA", "Zeta Pharma Labs Ltd (SAMPLE)", "EQ", "EQUITY", "2010-09-09"),
            ("SMPLETA", "Eta Textiles Ltd (SAMPLE)", "EQ", "EQUITY", "2001-02-02"),
            ("SMPLTHETA", "Theta Software Services Ltd (SAMPLE)", "EQ", "EQUITY", "2024-06-18"),
            ("SMPLIOTA", "Iota Chemicals Ltd (SAMPLE)", "BE", "EQUITY", "2015-05-25"),
            ("SMPLKAPPA", "Kappa Retail Ltd (SAMPLE)", "EQ", "EQUITY", "2017-08-14"),
            ("SMPLMU", "Mu Auto Components Ltd (SAMPLE)", "EQ", "EQUITY", "2006-12-11"),
            ("SMPLNU", "Nu Electricals Ltd (SAMPLE)", "EQ", "EQUITY", "2009-10-01"),
            ("SMPLLAMBDA", "Lambda Agro Ltd (SAMPLE)", "SM", "EQUITY", "2023-03-30"),
            ("SMPLNIFTYETF", "Sample Nifty Index ETF (SAMPLE)", "EQ", "ETF", "2019-01-01"),
        ], 1)
    ]  # fmt: skip
    return {
        "note": "SYNTHETIC DATA. All companies and figures are fictional, for development and testing only.",
        "as_of": AS_OF,
        "universe": universe,
        "companies": c,
    }


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(build(), indent=1))
    print(f"wrote {OUT}")
