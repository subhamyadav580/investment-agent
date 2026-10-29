"""Deterministic valuation context: sector-relative, history-relative, and an optional range with
explicit assumptions. Never a price target."""

import statistics

from app.schemas.screening import Metric
from app.services.discovery.sector_classifier import FINANCIAL
from app.services.research.peer_comparison import percentile_rank

MIN_HISTORY_POINTS = 3


def _quantile(values: list[float], q: float) -> float:
    s = sorted(values)
    idx = (len(s) - 1) * q
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


def evaluate_valuation(
    metrics: dict[str, Metric],
    hist_pe: dict[str, float],
    sector_medians: dict[str, float] | None,
    sector_group: str,
    shares_outstanding_cr: float | None,
) -> dict:
    val = lambda k: metrics[k].value if k in metrics else None  # noqa: E731
    primary = "pb" if sector_group == FINANCIAL else "pe"
    sector_medians = sector_medians or {}
    result: dict = {
        "primary_metric": primary,
        "current": {k: val(k) for k in ("pe", "pb", "ev_ebitda", "market_cap_cr", "last_price")},
        "earnings_basis": metrics["pe"].period if "pe" in metrics else None,
        "sector_median": {k: sector_medians.get(k) for k in ("pe", "pb", "ev_ebitda")},
        "vs_sector": {},
        "history": {},
        "range": None,
        "assumptions": [],
        "limitations": [],
    }

    for k in ("pe", "pb", "ev_ebitda"):
        if val(k) is not None and sector_medians.get(k):
            result["vs_sector"][k] = round(val(k) / sector_medians[k], 3)
    if not sector_medians:
        result["limitations"].append("No sector peers with usable data; sector-relative valuation unavailable.")

    pe = val("pe")
    points = list(hist_pe.values())
    if len(points) >= MIN_HISTORY_POINTS:
        result["history"] = {
            "pe_by_period": {k: round(v, 2) for k, v in hist_pe.items()},
            "median": round(statistics.median(points), 2),
            "p25": round(_quantile(points, 0.25), 2),
            "p75": round(_quantile(points, 0.75), 2),
            "current_percentile": percentile_rank(pe, points) if pe is not None else None,
        }
        if pe is not None:
            h = result["history"]
            result["history"]["position"] = (
                "below_history" if pe < h["p25"] else "above_history" if pe > h["p75"] else "within_history"
            )
    else:
        result["limitations"].append(
            f"Only {len(points)} historical P/E point(s); history-relative valuation needs {MIN_HISTORY_POINTS}."
        )

    earnings = metrics["pe"].inputs.get("earnings") if "pe" in metrics else None
    if result["history"] and earnings and earnings > 0 and shares_outstanding_cr and sector_group != FINANCIAL:
        eps = earnings / shares_outstanding_cr
        h = result["history"]
        result["range"] = {
            "metric": "price_per_share",
            "low": round(eps * h["p25"], 2),
            "mid": round(eps * h["median"], 2),
            "high": round(eps * h["p75"], 2),
            "eps": round(eps, 2),
        }
        result["assumptions"] = [
            f"EPS of {eps:.2f} from {result['earnings_basis']} earnings holds (no growth or decline assumed).",
            "The company's own historical P/E band (25th-75th percentile) is a reasonable reference multiple.",
            "Historical P/E uses the CURRENT share count for every year; dilution or buybacks distort it.",
            "Historical P/E uses the price ~60 days after each fiscal year end (when results are typically out).",
        ]
        result["limitations"].append(
            "The range is a sensitivity check on past multiples, not a fair-value estimate or price target."
        )
    return result
