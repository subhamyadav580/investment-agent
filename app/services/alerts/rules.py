"""Deterministic alert rules (plan section 10). Pure functions: context in, AlertCandidates out."""

import operator
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from app.schemas.alerts import AlertCandidate
from app.schemas.market_data import Announcement
from app.schemas.screening import Metric
from app.services.discovery.rules_config import AlertsCfg

OPS: dict[str, Callable[[float, float], bool]] = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}


@dataclass
class AlertContext:
    symbol: str
    exchange: str
    as_of: date
    since: date  # announcements published on/after this date are "new"
    values: dict[str, float | None]
    prev_values: dict[str, float | None]
    metrics: dict[str, Metric]
    announcements: list[Announcement]
    cfg: AlertsCfg
    sector_group: str = "non_financial"
    valuation_range: dict | None = None
    invalidation_conditions: list[dict] = field(default_factory=list)
    data_quality_warnings: list[str] = field(default_factory=list)


def _period(ctx: AlertContext, key: str) -> str | None:
    m = ctx.metrics.get(key)
    return m.period if m else None


def _metric_evidence(ctx: AlertContext, *keys: str) -> list[dict]:
    return [
        {"type": "metric", "key": k, "value": ctx.metrics[k].value, "period": ctx.metrics[k].period,
         "inputs": ctx.metrics[k].inputs}
        for k in keys if k in ctx.metrics
    ]  # fmt: skip


def _candidate(ctx: AlertContext, **kw) -> AlertCandidate:
    return AlertCandidate(symbol=ctx.symbol, exchange=ctx.exchange, data_quality_warnings=ctx.data_quality_warnings, **kw)


def earnings_deterioration(ctx: AlertContext) -> list[AlertCandidate]:
    out = []
    latest, prev = ctx.values.get("operating_margin_latest"), ctx.values.get("operating_margin_prev")
    if latest is not None and prev is not None and prev - latest > ctx.cfg.margin_drop_pp:
        period = _period(ctx, "operating_margin_latest")
        out.append(_candidate(
            ctx, rule_id="earnings_deterioration", severity="warning",
            trigger="Operating margin fell vs previous period",
            threshold=f"> {ctx.cfg.margin_drop_pp * 100:.1f} pp drop", observed=f"{prev:.1%} -> {latest:.1%}",
            comparison_period=f"{_period(ctx, 'operating_margin_prev')} vs {period}",
            why_it_matters="Margin compression can signal pricing pressure, cost inflation, or mix deterioration.",
            follow_up="Read the management commentary for the period; check raw-material costs and segment mix.",
            evidence=_metric_evidence(ctx, "operating_margin_latest", "operating_margin_prev"),
            fingerprint=f"margin:{period}",
        ))  # fmt: skip
    growth = ctx.values.get("profit_growth_latest")
    if growth is not None and growth < -ctx.cfg.profit_decline:
        period = _period(ctx, "profit_growth_latest")
        out.append(_candidate(
            ctx, rule_id="earnings_deterioration", severity="warning", trigger="Net profit declined year on year",
            threshold=f"< -{ctx.cfg.profit_decline:.0%}", observed=f"{growth:.1%}", comparison_period=period,
            why_it_matters="A sharp profit fall may break growth assumptions in the thesis.",
            follow_up="Separate one-offs (exceptional items, tax) from operating deterioration.",
            evidence=_metric_evidence(ctx, "profit_growth_latest", "exceptional_share_latest"),
            fingerprint=f"profit:{period}",
        ))  # fmt: skip
    return out


def cashflow_warning(ctx: AlertContext) -> list[AlertCandidate]:
    v = ctx.values.get("cfo_to_pat_3y")
    if v is None or v >= ctx.cfg.min_cfo_to_pat:
        return []
    period = _period(ctx, "cfo_to_pat_3y")
    return [_candidate(
        ctx, rule_id="cashflow_warning", severity="warning", trigger="Operating cash flow trails reported profit",
        threshold=f">= {ctx.cfg.min_cfo_to_pat:.0%}", observed=f"{v:.0%}", comparison_period=period,
        why_it_matters="Persistent gaps between profit and cash can indicate aggressive revenue recognition or "
                       "working-capital stress.",
        follow_up="Check receivable days, inventory build-up, and related-party transactions in the annual report.",
        evidence=_metric_evidence(ctx, "cfo_to_pat_3y", "receivable_days_latest", "receivable_days_prev"),
        fingerprint=f"cfo:{period}",
    )]  # fmt: skip


def debt_warning(ctx: AlertContext) -> list[AlertCandidate]:
    if ctx.sector_group == "financial":
        return []
    out = []
    de, icr = ctx.values.get("debt_to_equity"), ctx.values.get("interest_coverage")
    if de is not None and de > ctx.cfg.max_debt_to_equity:
        out.append(_candidate(
            ctx, rule_id="debt_warning", severity="warning", trigger="Leverage above limit",
            threshold=f"<= {ctx.cfg.max_debt_to_equity:.2f}x", observed=f"{de:.2f}x",
            comparison_period=_period(ctx, "debt_to_equity"),
            why_it_matters="Higher leverage reduces resilience to a downturn or rate increases.",
            follow_up="Check debt maturity profile, purpose of borrowing, and covenant disclosures.",
            evidence=_metric_evidence(ctx, "debt_to_equity", "net_debt_cr"),
            fingerprint=f"de:{_period(ctx, 'debt_to_equity')}",
        ))  # fmt: skip
    if icr is not None and icr < ctx.cfg.min_interest_coverage:
        out.append(_candidate(
            ctx, rule_id="debt_warning", severity="critical" if icr < 1.5 else "warning",
            trigger="Interest coverage below limit", threshold=f">= {ctx.cfg.min_interest_coverage:.1f}x",
            observed=f"{icr:.2f}x", comparison_period=_period(ctx, "interest_coverage"),
            why_it_matters="Thin coverage means operating profit barely services debt.",
            follow_up="Review refinancing plans and the trend in operating profit.",
            evidence=_metric_evidence(ctx, "interest_coverage"),
            fingerprint=f"icr:{_period(ctx, 'interest_coverage')}",
        ))  # fmt: skip
    return out


def governance_event(ctx: AlertContext) -> list[AlertCandidate]:
    return [
        _candidate(
            ctx, rule_id="governance_event", severity="critical", trigger=f"Governance disclosure: {a.category}",
            threshold="any", observed=a.title, comparison_period=a.published_at.date().isoformat(),
            why_it_matters="Auditor, regulatory, or pledge events can signal governance or disclosure problems.",
            follow_up="Read the full exchange filing and any company clarification before relying on reported numbers.",
            evidence=[{"type": "source", "title": a.title, "url": a.source.url,
                       "published_at": a.published_at.isoformat(), "retrieved_at": a.source.retrieved_at.isoformat(),
                       "synthetic": a.source.is_synthetic}],
            fingerprint=f"ann:{a.id}",
        )  # fmt: skip
        for a in ctx.announcements
        if a.category in ctx.cfg.governance_categories and ctx.since <= a.published_at.date() <= ctx.as_of
    ]


def _in_range(v: float | None, low: float, high: float) -> bool:
    return v is not None and low <= v <= high


def valuation_watch(ctx: AlertContext) -> list[AlertCandidate]:
    vr = ctx.valuation_range
    if not vr:
        return []
    metric, low, high = vr["metric"], vr["low"], vr["high"]
    now, before = ctx.values.get(metric), ctx.prev_values.get(metric)
    if not _in_range(now, low, high) or _in_range(before, low, high):
        return []  # only alert on entering the range
    return [_candidate(
        ctx, rule_id="valuation_watch", severity="info", trigger=f"{metric.upper()} entered your watch range",
        threshold=f"{low}-{high}", observed=round(now, 2), comparison_period=_period(ctx, metric),
        why_it_matters=f"Range set with these assumptions: {vr.get('assumptions', 'none recorded')}",
        follow_up="Re-check whether the assumptions behind the range still hold before doing anything.",
        evidence=_metric_evidence(ctx, metric, "last_price"),
        fingerprint=f"val:{metric}:{low}:{high}:{ctx.as_of.isoformat()}",
    )]  # fmt: skip


def results_reminder(ctx: AlertContext) -> list[AlertCandidate]:
    out = []
    for a in ctx.announcements:
        if a.category not in ("board_meeting", "results") or not a.event_date:
            continue
        days = (a.event_date - ctx.as_of).days
        if 0 <= days <= ctx.cfg.results_reminder_days:
            out.append(_candidate(
                ctx, rule_id="results_reminder", severity="info", trigger="Results / board meeting coming up",
                threshold=f"within {ctx.cfg.results_reminder_days} days", observed=a.event_date.isoformat(),
                why_it_matters="New results will update the metrics behind your thesis.",
                follow_up="Note what you expect to see (growth, margins, cash flow) before the results are out.",
                evidence=[{"type": "source", "title": a.title, "url": a.source.url,
                           "published_at": a.published_at.isoformat()}],
                fingerprint=f"results:{a.id}",
            ))  # fmt: skip
    return out


def thesis_review(ctx: AlertContext) -> list[AlertCandidate]:
    out = []
    for cond in ctx.invalidation_conditions:
        metric, op, threshold = cond["metric"], cond["op"], cond["value"]
        value = ctx.values.get(metric)
        desc = cond.get("description") or f"{metric} {op} {threshold}"
        if value is None:
            out.append(_candidate(
                ctx, rule_id="thesis_review", severity="info", trigger=f"Thesis condition cannot be checked: {desc}",
                threshold=f"{op} {threshold}", observed=None,
                why_it_matters="A recorded invalidation condition has no data, so the thesis is unmonitored on it.",
                follow_up=f"Find a source for {metric} or revise the condition.",
                fingerprint=f"thesis-missing:{metric}:{ctx.as_of.isoformat()}",
            ))  # fmt: skip
        elif OPS[op](value, threshold):
            out.append(_candidate(
                ctx, rule_id="thesis_review", severity="critical", trigger=f"Thesis invalidation condition met: {desc}",
                threshold=f"{op} {threshold}", observed=round(value, 4), comparison_period=_period(ctx, metric),
                why_it_matters="A condition you recorded as breaking the investment thesis is now true.",
                follow_up="Review the thesis. This is a prompt for human review, not an instruction to trade.",
                evidence=_metric_evidence(ctx, metric),
                fingerprint=f"thesis:{metric}{op}{threshold}:{_period(ctx, metric)}",
            ))  # fmt: skip
    return out


ALL_RULES = (earnings_deterioration, cashflow_warning, debt_warning, governance_event, valuation_watch,
             results_reminder, thesis_review)  # fmt: skip


def evaluate_alert_rules(ctx: AlertContext) -> list[AlertCandidate]:
    return [c for rule in ALL_RULES for c in rule(ctx)]
