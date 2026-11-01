"""Deterministic valuation context: sector-relative, history-relative, and conservative / base / optimistic
scenarios built from explicit assumptions. Never a price target."""

import statistics

from app.schemas.screening import Metric
from app.services.discovery.rules_config import ValuationCfg
from app.services.discovery.sector_classifier import FINANCIAL
from app.services.research.peer_comparison import percentile_rank

MIN_HISTORY_POINTS = 3
SCENARIOS = ("conservative", "base", "optimistic")


def _quantile(values: list[float], q: float) -> float:
    s = sorted(values)
    idx = (len(s) - 1) * q
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


def _history(current: float | None, hist: dict[str, float]) -> dict:
    points = list(hist.values())
    if len(points) < MIN_HISTORY_POINTS:
        return {}
    h = {
        "by_period": {k: round(v, 2) for k, v in hist.items()},
        "median": round(statistics.median(points), 2),
        "p25": round(_quantile(points, 0.25), 2),
        "p75": round(_quantile(points, 0.75), 2),
        "current_percentile": percentile_rank(current, points) if current is not None else None,
    }
    if current is not None:
        h["position"] = "below_history" if current < h["p25"] else "above_history" if current > h["p75"] else "within_history"
    return h


def evaluate_valuation(
    metrics: dict[str, Metric],
    hist_pe: dict[str, float],
    sector_medians: dict[str, float] | None,
    sector_group: str,
    shares_outstanding_cr: float | None,
    cfg: ValuationCfg,
    hist_pb: dict[str, float] | None = None,
    horizons: dict[str, int] | None = None,
) -> dict:
    """`horizons` maps horizon name (long_term | medium_term) to years; each gets its own scenarios."""
    val = lambda k: metrics[k].value if k in metrics else None  # noqa: E731
    primary = "pb" if sector_group == FINANCIAL else "pe"
    sector_medians = sector_medians or {}
    horizons = horizons or {"long_term": cfg.scenario_years}
    result: dict = {
        "primary_metric": primary,
        "current": {k: val(k) for k in ("pe", "pb", "ev_ebitda", "market_cap_cr", "last_price")},
        "earnings_basis": metrics["pe"].period if "pe" in metrics else None,
        "sector_median": {k: sector_medians.get(k) for k in ("pe", "pb", "ev_ebitda")},
        "vs_sector": {},
        "history": {},
        "history_pb": {},
        "fair_value_range": None,
        "scenarios": None,  # the first horizon's scenarios (long-term unless only medium-term was asked for)
        "scenarios_by_horizon": {},
        "assumptions": [],
        "limitations": [],
    }

    for k in ("pe", "pb", "ev_ebitda"):
        if val(k) is not None and sector_medians.get(k):
            result["vs_sector"][k] = round(val(k) / sector_medians[k], 3)
    if not sector_medians:
        result["limitations"].append("No sector peers with usable data; sector-relative valuation unavailable.")

    result["history"] = _history(val("pe"), hist_pe)
    result["history_pb"] = _history(val("pb"), hist_pb or {})
    own = result["history_pb"] if primary == "pb" else result["history"]
    if not own:
        n = len(hist_pb or {}) if primary == "pb" else len(hist_pe)
        result["limitations"].append(
            f"Only {n} historical {primary.upper()} point(s); history-relative valuation needs {MIN_HISTORY_POINTS}."
        )

    anchor = _anchor(result, metrics, own, sector_medians.get(primary), primary, shares_outstanding_cr, cfg)
    if anchor is None:
        return result
    per_share, multiples, common_notes = anchor
    result["fair_value_range"] = {
        "low": round(per_share * multiples[0], 2), "mid": round(per_share * multiples[1], 2),
        "high": round(per_share * multiples[2], 2), "price": val("last_price"),
        "basis": f"current {'EPS' if primary == 'pe' else 'book value per share'} x reference {primary.upper()} "
                 "multiples (no growth assumed)",
    }  # fmt: skip
    for name, years in horizons.items():
        growth, notes = _momentum_growth(metrics, primary, cfg) if name == "medium_term" else (None, [])
        if growth is None:
            growth, notes = _base_growth(metrics, primary, cfg)
        if growth is None:
            result["limitations"].append(f"No usable growth history; {name.replace('_', '-')} scenarios not computed.")
            continue
        result["scenarios_by_horizon"][name] = _scenario_set(per_share, multiples, growth, years, val("last_price"),
                                                             primary, notes + common_notes, cfg)  # fmt: skip
    if result["scenarios_by_horizon"]:
        first = next(iter(result["scenarios_by_horizon"].values()))
        result["scenarios"] = {k: v for k, v in first.items() if k != "assumptions"}
        result["assumptions"] = first["assumptions"]
        result["limitations"].append("The fair-value range applies reference multiples to current earnings; scenarios "
                                     "are sensitivity checks on stated assumptions, not forecasts or price targets.")  # fmt: skip
    return result


def _anchor(
    result: dict, metrics: dict[str, Metric], own: dict, sector_median: float | None, primary: str,
    shares_cr: float | None, cfg: ValuationCfg,
) -> tuple[float, tuple[float, float, float], list[str]] | None:  # fmt: skip
    """(per-share earnings or book value, reference multiples low/mid/high, assumption notes) or None."""
    price = metrics["last_price"].value if "last_price" in metrics else None
    if primary == "pe":
        base_value = metrics["pe"].inputs.get("earnings") if "pe" in metrics else None
        per_share_label, basis = "EPS", result["earnings_basis"]
    else:
        base_value = metrics["pb"].inputs.get("book_value") if "pb" in metrics else None
        per_share_label, basis = "book value per share", metrics["pb"].period if "pb" in metrics else None
    if not (price and shares_cr and base_value and base_value > 0):
        result["limitations"].append(f"Scenarios need a price, share count and positive {per_share_label}; one is missing.")
        return None

    if own:
        multiples = (own["p25"], own["median"], own["p75"])
        multiple_note = f"Exit {primary.upper()} = the company's own 25th / median / 75th percentile historical {primary.upper()}."
    elif sector_median:
        b = cfg.sector_multiple_band
        multiples = (sector_median * (1 - b), sector_median, sector_median * (1 + b))
        multiple_note = (f"Exit {primary.upper()} = sector median {sector_median:.1f}x scaled by {1 - b:.2f} / 1.00 / "
                         f"{1 + b:.2f} (the company's own history is too short).")  # fmt: skip
    else:
        result["limitations"].append("No historical or sector multiple to anchor scenarios; valuation is uncertain.")
        return None
    per_share = base_value / shares_cr
    notes = [
        multiple_note,
        f"Starting {per_share_label} {per_share:.2f} from {basis} (latest reported, not forecast).",
        "Current share count throughout (no dilution or buybacks); dividends excluded.",
        "Historical multiples use the price about 60 days after each fiscal year end.",
    ]
    return per_share, multiples, notes


def _scenario_set(
    per_share: float, multiples: tuple[float, float, float], growth: float, years: int, price: float, primary: str,
    notes: list[str], cfg: ValuationCfg,
) -> dict:  # fmt: skip
    spread = cfg.scenario_growth_spread
    rates = (max(cfg.scenario_min_growth, growth - spread), growth, min(cfg.scenario_max_growth, growth + spread))
    out: dict = {"years": years, "price": price, "per_share_basis": "EPS" if primary == "pe" else "book value per share",
                 "per_share": round(per_share, 2)}  # fmt: skip
    for name, g, m in zip(SCENARIOS, rates, multiples, strict=True):
        future = per_share * (1 + g) ** years * m
        out[name] = {
            "annual_growth": round(g, 4),
            "exit_multiple": round(m, 2),
            "value_per_share_today": round(per_share * m, 2),
            "value_per_share_at_horizon": round(future, 2),
            "implied_annual_price_change": round((future / price) ** (1 / years) - 1, 4),
        }
    out["assumptions"] = [
        *notes,
        f"Conservative / optimistic growth = base -/+ {spread:.0%}, bounded to {cfg.scenario_min_growth:.0%}.."
        f"{cfg.scenario_max_growth:.0%} a year, for {years} year(s).",
    ]
    return out


def _momentum_growth(metrics: dict[str, Metric], primary: str, cfg: ValuationCfg) -> tuple[float | None, list[str]]:
    """Medium-term base growth: recent momentum (latest quarter YoY, else latest year), capped like the long-term
    basis. Lenders keep the book-value basis."""
    if primary == "pb":
        return None, []
    val = lambda k: metrics[k].value if k in metrics else None  # noqa: E731
    lo, hi = cfg.scenario_min_growth, cfg.scenario_max_growth
    for p_key, r_key, label in (("profit_growth_q_yoy", "revenue_growth_q_yoy", "latest-quarter YoY"),
                                ("profit_growth_latest", "revenue_growth_latest", "latest-year")):  # fmt: skip
        profit, revenue = val(p_key), val(r_key)
        if profit is None:
            continue
        g = profit if revenue is None else min(profit, revenue + cfg.scenario_margin_headroom)
        note = f"Base growth = {label} profit growth {profit:.1%}"
        if revenue is not None:
            note += f", capped at revenue growth {revenue:.1%} + {cfg.scenario_margin_headroom:.0%}"
        return max(lo, min(hi, g)), [note + f"; bounded to {lo:.0%}..{hi:.0%}. Recent momentum, not a forecast."]
    return None, []


def _base_growth(metrics: dict[str, Metric], primary: str, cfg: ValuationCfg) -> tuple[float | None, list[str]]:
    val = lambda k: metrics[k].value if k in metrics else None  # noqa: E731
    lo, hi = cfg.scenario_min_growth, cfg.scenario_max_growth
    clamp = lambda g: max(lo, min(hi, g))  # noqa: E731
    if primary == "pb":
        g = val("book_value_cagr")
        if g is None:
            return None, []
        return clamp(g), [f"Base growth = book value CAGR {g:.1%} ({metrics['book_value_cagr'].period}), "
                          f"bounded to {lo:.0%}..{hi:.0%}."]  # fmt: skip
    profit, revenue = val("profit_cagr"), val("revenue_cagr")
    if profit is not None and revenue is not None:
        cap = revenue + cfg.scenario_margin_headroom
        g = min(profit, cap)
        note = (f"Base growth = profit CAGR {profit:.1%}, capped at revenue CAGR {revenue:.1%} + "
                f"{cfg.scenario_margin_headroom:.0%} because margins cannot expand indefinitely"
                + (" (cap applied)" if profit > cap else "") + ".")  # fmt: skip
    elif profit is not None:
        g, note = profit, f"Base growth = profit CAGR {profit:.1%}."
    elif revenue is not None:
        g, note = revenue, f"Base growth = revenue CAGR {revenue:.1%} (profit CAGR undefined), margins assumed flat."
    else:
        return None, []
    return clamp(g), [note + f" Bounded to {lo:.0%}..{hi:.0%}."]


def assess_valuation(
    valuation: dict, metrics: dict[str, Metric], cfg: ValuationCfg, horizon: str = "long_term"
) -> tuple[str, list[str]]:
    """Attractive / Fair / Expensive / Uncertain for one horizon, with the reasons."""
    if not valuation:
        return "Uncertain", ["Valuation was not computed (data failed validation)."]
    primary = valuation["primary_metric"]
    current = valuation["current"].get(primary)
    if current is None:
        return "Uncertain", [f"No current {primary.upper()} (earnings or book value missing or non-positive)."]
    reasons = [f"Current {primary.upper()} {current:.1f}x."]
    if primary == "pe" and current > cfg.max_pe_absolute:
        return "Expensive", reasons + [f"P/E above the {cfg.max_pe_absolute:.0f}x absolute ceiling."]
    if primary == "pb" and current > cfg.max_pb_financial:
        return "Expensive", reasons + [f"P/B above the {cfg.max_pb_financial:.1f}x ceiling for lenders."]
    if rel := valuation["vs_sector"].get(primary):
        reasons.append(f"{rel:.2f}x the sector median {primary.upper()}.")
    hist = valuation["history_pb"] if primary == "pb" else valuation["history"]
    if hist.get("position"):
        reasons.append(f"{hist['position'].replace('_', ' ')} (own median {hist['median']}x).")

    sc = (valuation.get("scenarios_by_horizon") or {}).get(horizon)
    if sc:
        base, cons = sc["base"]["implied_annual_price_change"], sc["conservative"]["implied_annual_price_change"]
        reasons.append(f"Implied annual price change over {sc['years']}y: conservative {cons:.1%}, base {base:.1%}, "
                       f"optimistic {sc['optimistic']['implied_annual_price_change']:.1%}.")  # fmt: skip
        if base >= cfg.attractive_base_return and cons >= 0:
            return "Attractive", reasons + [f"Base case at or above {cfg.attractive_base_return:.0%} a year and the "
                                            "conservative case does not lose money."]  # fmt: skip
        if base < cfg.expensive_base_return:
            return "Expensive", reasons + [f"Base case below {cfg.expensive_base_return:.0%} a year: the price "
                                           "already reflects the growth assumed."]  # fmt: skip
        return "Fair", reasons
    if rel:
        if rel > cfg.max_pe_vs_sector_median:
            return "Expensive", reasons + ["Well above sector peers; no scenarios to offset it."]
        if rel <= 1 - cfg.sector_multiple_band:
            return "Attractive", reasons + ["Below sector peers (sector-relative only; no own history)."]
        return "Fair", reasons + ["Sector-relative only; the company's own history is too short to compare."]
    return "Uncertain", reasons + ["Neither enough own history nor sector peers to judge the price."]
