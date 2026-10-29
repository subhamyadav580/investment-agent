"""Deterministic financial metrics. Pure functions over normalized data - no LLM, no I/O.

Conventions:
- Ratios are fractions (0.18 = 18%), except *_pct passthroughs which are percentages as reported.
- A metric that cannot be computed is returned with value=None and a `note` explaining why; it is never
  defaulted or estimated.
- `period` records which period/basis a metric uses (FY2026, TTM to 2026-09-30, ...).
"""

import statistics
from datetime import date, timedelta

from app.schemas.market_data import CompanyData, FinancialStatements, PeriodType, PriceHistory
from app.schemas.screening import Metric
from app.services.discovery.sector_classifier import FINANCIAL

ICR_CAP = 100.0  # interest coverage reported as this when interest expense is zero
CAGR_MAX_YEARS = 5


def cagr(start: float | None, end: float | None, years: float) -> float | None:
    """Compound annual growth. Undefined (None) for non-positive endpoints or zero span."""
    if start is None or end is None or years <= 0 or start <= 0 or end <= 0:
        return None
    return (end / start) ** (1 / years) - 1


def safe_div(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den == 0:
        return None
    return num / den


def _avg(a: float | None, b: float | None) -> float | None:
    if a is None:
        return b
    if b is None:
        return a
    return (a + b) / 2


class _Ctx:
    def __init__(self, fin: FinancialStatements):
        self.fin = fin
        self.periods = fin.periods(PeriodType.FY)
        self.latest = self.periods[-1] if self.periods else None
        self.prev = self.periods[-2] if len(self.periods) > 1 else None
        self._cache: dict[str, dict[str, float | None]] = {}

    def s(self, metric: str) -> dict[str, float | None]:
        if metric not in self._cache:
            self._cache[metric] = self.fin.series(metric)
        return self._cache[metric]

    def v(self, metric: str, period: str | None) -> float | None:
        return self.s(metric).get(period) if period else None


def compute_metrics(data: CompanyData, sector_group: str, as_of: date) -> dict[str, Metric]:
    out: dict[str, Metric] = {}
    if data.financials and data.financials.values:
        ctx = _Ctx(data.financials)
        _growth(ctx, out)
        if sector_group == FINANCIAL:
            _financial_sector(ctx, out)
        else:
            _profitability(ctx, out)
            _health(ctx, out)
            _earnings_quality(ctx, out)
        _returns_on_equity(ctx, out)
        _quarterly_growth(data.financials, out)
        if data.prices and data.prices.bars:
            _valuation(ctx, data.prices, data.financials, sector_group, out)
    if data.prices and data.prices.bars:
        _liquidity(data.prices, as_of, out)
    return out


def _put(out: dict[str, Metric], key: str, value: float | None, unit: str, period=None, note=None, **inputs):
    out[key] = Metric(
        key=key,
        value=None if value is None else round(value, 6),
        unit=unit,
        period=period,
        inputs={k: (round(v, 6) if isinstance(v, float) else v) for k, v in inputs.items()},
        note=note,
    )


# ---------------------------------------------------------------- growth


def _window(ctx: _Ctx) -> tuple[str | None, str | None, int]:
    if len(ctx.periods) < 2:
        return None, None, 0
    window = ctx.periods[-(CAGR_MAX_YEARS + 1) :]
    start, end = window[0], window[-1]
    return start, end, int(end[2:]) - int(start[2:])


def _growth(ctx: _Ctx, out: dict[str, Metric]) -> None:
    start, end, years = _window(ctx)
    for metric, key in (("revenue", "revenue_cagr"), ("net_profit", "profit_cagr")):
        a, b = ctx.v(metric, start), ctx.v(metric, end)
        value = cagr(a, b, years)
        note = None
        if value is None:
            note = "insufficient history" if years == 0 else "undefined for missing or non-positive endpoints"
        _put(out, key, value, "ratio", f"{start}-{end}" if start else None, note, start=a, end=b, years=years)

    for metric, key in (("revenue", "revenue_growth_latest"), ("net_profit", "profit_growth_latest")):
        a, b = ctx.v(metric, ctx.prev), ctx.v(metric, ctx.latest)
        value = None if a is None or b is None or a <= 0 else b / a - 1
        _put(out, key, value, "ratio", ctx.latest, None if value is not None else "previous period missing or "
             "non-positive", previous=a, latest=b)  # fmt: skip

    profits = [p for p in ctx.s("net_profit").values() if p is not None][-CAGR_MAX_YEARS:]
    ratio = (sum(p > 0 for p in profits) / len(profits)) if profits else None
    _put(out, "profit_positive_ratio", ratio, "ratio", ctx.latest, years_counted=len(profits))


# ---------------------------------------------------------------- non-financials


def _ebit(ctx: _Ctx, period: str | None) -> float | None:
    pbt, interest = ctx.v("pbt", period), ctx.v("interest", period)
    if pbt is None or interest is None:
        return None
    return pbt + interest


def _profitability(ctx: _Ctx, out: dict[str, Metric]) -> None:
    margins = {p: safe_div(ctx.v("operating_profit", p), ctx.v("revenue", p)) for p in ctx.periods}
    recent = [m for m in list(margins.values())[-CAGR_MAX_YEARS:] if m is not None]
    _put(out, "operating_margin_latest", margins.get(ctx.latest), "ratio", ctx.latest,
         operating_profit=ctx.v("operating_profit", ctx.latest), revenue=ctx.v("revenue", ctx.latest))  # fmt: skip
    _put(out, "operating_margin_prev", margins.get(ctx.prev) if ctx.prev else None, "ratio", ctx.prev)
    _put(out, "operating_margin_avg", statistics.fmean(recent) if recent else None, "ratio", ctx.latest,
         years=len(recent))  # fmt: skip
    _put(out, "operating_margin_stdev", statistics.pstdev(recent) if len(recent) >= 3 else None, "ratio",
         ctx.latest, years=len(recent))  # fmt: skip
    _put(out, "net_margin_latest", safe_div(ctx.v("net_profit", ctx.latest), ctx.v("revenue", ctx.latest)),
         "ratio", ctx.latest)  # fmt: skip
    _put(out, "net_margin_prev", safe_div(ctx.v("net_profit", ctx.prev), ctx.v("revenue", ctx.prev)),
         "ratio", ctx.prev)  # fmt: skip

    # ROCE = EBIT / average capital employed (equity + debt)
    roces = {}
    for i, p in enumerate(ctx.periods):
        ce = _capital_employed(ctx, p)
        prev_ce = _capital_employed(ctx, ctx.periods[i - 1]) if i > 0 else None
        roces[p] = safe_div(_ebit(ctx, p), _avg(ce, prev_ce))
    latest_ce = _capital_employed(ctx, ctx.latest)
    _put(out, "roce_latest", roces.get(ctx.latest), "ratio", ctx.latest, ebit=_ebit(ctx, ctx.latest),
         capital_employed=latest_ce)  # fmt: skip
    last3 = [r for r in list(roces.values())[-3:] if r is not None]
    _put(out, "roce_avg_3y", statistics.fmean(last3) if last3 else None, "ratio", ctx.latest, years=len(last3))


def _capital_employed(ctx: _Ctx, period: str | None) -> float | None:
    eq, debt = ctx.v("total_equity", period), ctx.v("total_debt", period)
    if eq is None or debt is None:
        return None
    return eq + debt


def _health(ctx: _Ctx, out: dict[str, Metric]) -> None:
    eq, debt, cash = (ctx.v(m, ctx.latest) for m in ("total_equity", "total_debt", "cash_and_equivalents"))
    _put(out, "debt_to_equity", safe_div(debt, eq) if eq and eq > 0 else None, "x", ctx.latest,
         None if eq and eq > 0 else "equity missing or non-positive", total_debt=debt, total_equity=eq)  # fmt: skip
    _put(out, "net_debt_cr", None if debt is None else debt - (cash or 0.0), "INR_crore", ctx.latest,
         None if cash is not None else "cash not reported; net debt equals gross debt", total_debt=debt, cash=cash)  # fmt: skip

    ebit, interest = _ebit(ctx, ctx.latest), ctx.v("interest", ctx.latest)
    if interest == 0 and ebit is not None:
        _put(out, "interest_coverage", ICR_CAP, "x", ctx.latest, "no interest expense; capped", ebit=ebit, interest=0.0)
    else:
        _put(out, "interest_coverage", safe_div(ebit, interest), "x", ctx.latest, ebit=ebit, interest=interest)


def _earnings_quality(ctx: _Ctx, out: dict[str, Metric]) -> None:
    window = ctx.periods[-3:]
    cfo = [ctx.v("cfo", p) for p in window]
    pat = [ctx.v("net_profit", p) for p in window]
    if None in cfo or None in pat or not window:
        _put(out, "cfo_to_pat_3y", None, "ratio", ctx.latest, "CFO or profit missing in window")
    elif sum(pat) <= 0:
        _put(out, "cfo_to_pat_3y", None, "ratio", ctx.latest, "cumulative profit non-positive",
             cfo_sum=sum(cfo), pat_sum=sum(pat))  # fmt: skip
    else:
        _put(out, "cfo_to_pat_3y", sum(cfo) / sum(pat), "ratio", f"{window[0]}-{window[-1]}",
             cfo_sum=sum(cfo), pat_sum=sum(pat))  # fmt: skip

    for period, key in ((ctx.latest, "receivable_days_latest"), (ctx.prev, "receivable_days_prev")):
        rec, rev = ctx.v("receivables", period), ctx.v("revenue", period)
        days = safe_div(rec, rev)
        _put(out, key, None if days is None else days * 365, "days", period, receivables=rec, revenue=rev)

    exc, pat_l = ctx.v("exceptional_items", ctx.latest), ctx.v("net_profit", ctx.latest)
    share = safe_div(exc, pat_l) if pat_l and pat_l > 0 else None
    _put(out, "exceptional_share_latest", share, "ratio", ctx.latest, exceptional_items=exc, net_profit=pat_l)


# ---------------------------------------------------------------- financials & equity returns


def _financial_sector(ctx: _Ctx, out: dict[str, Metric]) -> None:
    np_, ta, ta_prev = ctx.v("net_profit", ctx.latest), ctx.v("total_assets", ctx.latest), ctx.v("total_assets", ctx.prev)
    _put(out, "roa_latest", safe_div(np_, _avg(ta, ta_prev)), "ratio", ctx.latest, net_profit=np_, total_assets=ta)
    for metric in ("gross_npa_pct", "net_npa_pct", "capital_adequacy_ratio"):
        val = ctx.v(metric, ctx.latest)
        _put(out, metric, val, "pct", ctx.latest, None if val is not None else "not reported")
    _put(out, "net_margin_latest", safe_div(np_, ctx.v("revenue", ctx.latest)), "ratio", ctx.latest)


def _returns_on_equity(ctx: _Ctx, out: dict[str, Metric]) -> None:
    roes = {}
    for i, p in enumerate(ctx.periods):
        prev_eq = ctx.v("total_equity", ctx.periods[i - 1]) if i > 0 else None
        avg_eq = _avg(ctx.v("total_equity", p), prev_eq)
        roes[p] = safe_div(ctx.v("net_profit", p), avg_eq) if avg_eq and avg_eq > 0 else None
    _put(out, "roe_latest", roes.get(ctx.latest), "ratio", ctx.latest, net_profit=ctx.v("net_profit", ctx.latest),
         total_equity=ctx.v("total_equity", ctx.latest))  # fmt: skip
    last3 = [r for r in list(roes.values())[-3:] if r is not None]
    _put(out, "roe_avg_3y", statistics.fmean(last3) if last3 else None, "ratio", ctx.latest, years=len(last3))


# ---------------------------------------------------------------- quarterly momentum


def _yoy(series: dict[str, float | None], ends: dict[str, date], period: str) -> tuple[float | None, str | None]:
    """Growth of `period` vs the quarter ending one year earlier."""
    end = ends[period]
    base = next((p for p, e in ends.items() if e.month == end.month and e.year == end.year - 1), None)
    a, b = (series.get(base) if base else None), series.get(period)
    if a is None or b is None or a <= 0:
        return None, base
    return b / a - 1, base


def _quarterly_growth(fin: FinancialStatements, out: dict[str, Metric]) -> None:
    periods = fin.periods(PeriodType.QUARTER)
    if len(periods) < 5:
        return
    ends = {p: fin.period_end(p) for p in periods}
    rev, profit = fin.series("revenue", PeriodType.QUARTER), fin.series("net_profit", PeriodType.QUARTER)
    latest, prev = periods[-1], periods[-2]
    for key, series, period in (("revenue_growth_q_yoy", rev, latest), ("profit_growth_q_yoy", profit, latest),
                                ("profit_growth_q_yoy_prev", profit, prev)):  # fmt: skip
        value, base = _yoy(series, ends, period)
        _put(out, key, value, "ratio", period, None if value is not None else "comparable quarter missing or "
             "non-positive", base_period=base)  # fmt: skip


# ---------------------------------------------------------------- valuation & market


def ttm_net_profit(fin: FinancialStatements) -> tuple[float | None, str | None]:
    """Sum of the last 4 quarters if quarterly data is newer than the latest FY; else latest FY profit."""
    q = fin.series("net_profit", PeriodType.QUARTER)
    fy_periods = fin.periods(PeriodType.FY)
    fy_latest = fy_periods[-1] if fy_periods else None
    q_periods = fin.periods(PeriodType.QUARTER)
    if len(q_periods) >= 4 and fy_latest:
        last4 = q_periods[-4:]
        if fin.period_end(last4[-1]) > fin.period_end(fy_latest) and all(q.get(p) is not None for p in last4):
            return sum(q[p] for p in last4), f"TTM to {fin.period_end(last4[-1])}"
    if fy_latest:
        return fin.series("net_profit").get(fy_latest), fy_latest
    return None, None


def _valuation(ctx: _Ctx, prices: PriceHistory, fin: FinancialStatements, sector_group: str, out) -> None:
    last = prices.bars[-1]
    _put(out, "last_price", last.close, "INR", last.date.isoformat())
    shares = fin.shares_outstanding_cr
    mcap = last.close * shares if shares else None  # price (INR) x shares (crore) = INR crore
    _put(out, "market_cap_cr", mcap, "INR_crore", last.date.isoformat(), None if shares else "share count missing",
         price=last.close, shares_cr=shares)  # fmt: skip

    profit, basis = ttm_net_profit(fin)
    pe = safe_div(mcap, profit) if profit and profit > 0 else None
    _put(out, "pe", pe, "x", basis, None if pe is not None else "earnings missing or non-positive",
         market_cap_cr=mcap, earnings=profit)  # fmt: skip
    eq = ctx.v("total_equity", ctx.latest)
    _put(out, "pb", safe_div(mcap, eq) if eq and eq > 0 else None, "x", ctx.latest, market_cap_cr=mcap, book_value=eq)

    if sector_group != FINANCIAL:
        debt, cash, ebitda = (ctx.v(m, ctx.latest) for m in ("total_debt", "cash_and_equivalents", "operating_profit"))
        ev = None if mcap is None or debt is None else mcap + debt - (cash or 0.0)
        _put(out, "ev_ebitda", safe_div(ev, ebitda) if ebitda and ebitda > 0 else None, "x", ctx.latest,
             enterprise_value=ev, ebitda=ebitda)  # fmt: skip


def _liquidity(prices: PriceHistory, as_of: date, out: dict[str, Metric]) -> None:
    recent = [b for b in prices.bars if b.date <= as_of][-60:]
    traded = [b.close * b.volume / 1e7 for b in recent if b.volume is not None]
    _put(out, "avg_traded_value_cr_60d", statistics.fmean(traded) if traded else None, "INR_crore",
         f"{len(traded)} sessions", None if traded else "volume not available")  # fmt: skip
    year_ago = [b for b in prices.bars if b.date <= as_of - timedelta(days=365)]
    if year_ago and recent:
        _put(out, "price_return_1y", recent[-1].close / year_ago[-1].close - 1, "ratio", recent[-1].date.isoformat())


def historical_pe(fin: FinancialStatements, prices: PriceHistory) -> dict[str, float]:
    """P/E at each fiscal year end using the closing price on/before the date results would be public
    (~60 days after FY end), to avoid look-ahead."""
    shares = fin.shares_outstanding_cr
    if not shares or not prices.bars:
        return {}
    out = {}
    profits = fin.series("net_profit")
    for period in fin.periods(PeriodType.FY):
        end = fin.period_end(period)
        known_at = end + timedelta(days=60)
        bars = [b for b in prices.bars if b.date <= known_at]
        if not bars or bars[-1].date < known_at - timedelta(days=10):
            continue
        p = profits.get(period)
        if p and p > 0:
            out[period] = bars[-1].close * shares / p
    return out


def metrics_to_values(metrics: dict[str, Metric]) -> dict[str, float | None]:
    return {k: m.value for k, m in metrics.items()}
