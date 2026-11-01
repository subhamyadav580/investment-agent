"""Final assessment: category ratings, red flags and the overall classification. Deterministic - the LLM explains
the business but never decides the outcome.

Classifications (research assessments, not return guarantees or personal advice):
- strong_candidate         fundamentals AND valuation justify further investment consideration
- good_business_expensive  the business looks attractive but the price may leave limited upside
- potential_opportunity    some attractive characteristics, but more investigation is needed
- high_risk                significant financial, business, valuation or governance concerns
- insufficient_evidence    not enough reliable information to conclude

Red flags are listed on their own and force `high_risk`, so a high score elsewhere cannot hide them.
"""

from dataclasses import dataclass, field

from app.schemas.market_data import DataQualityReport
from app.schemas.screening import GovernanceFlag, Metric, RuleResult
from app.services.discovery.rules_config import ScreeningConfig
from app.services.discovery.sector_classifier import FINANCIAL
from app.services.research.valuation import assess_valuation

LABELS = {
    "strong_candidate": "Strong candidate",
    "good_business_expensive": "Good business, expensive valuation",
    "potential_opportunity": "Potential opportunity",
    "high_risk": "High risk",
    "insufficient_evidence": "Insufficient evidence",
}
MEANING = {
    "strong_candidate": "Fundamentals and valuation justify further investment consideration.",
    "good_business_expensive": "The business looks attractive, but its current price may leave limited upside.",
    "potential_opportunity": "Some attractive characteristics, but further investigation is required.",
    "high_risk": "Significant financial, business, valuation, or governance concerns.",
    "insufficient_evidence": "Not enough reliable information to reach a conclusion.",
}

# Metrics behind each rating (the evidence trail links to these keys and to their source documents)
CATEGORY_METRICS = {
    "business_quality": {"non_financial": ["roce_avg_3y", "roce_latest", "operating_margin_avg", "operating_margin_stdev"],
                         FINANCIAL: ["roe_avg_3y", "roe_latest", "roa_latest"]},
    "financial_health": {"non_financial": ["revenue_cagr", "profit_cagr", "profit_positive_ratio", "cfo_to_pat_3y",
                                           "debt_to_equity", "interest_coverage", "net_debt_to_ebitda"],
                         FINANCIAL: ["revenue_cagr", "profit_cagr", "profit_positive_ratio", "capital_adequacy_ratio",
                                     "gross_npa_pct", "net_npa_pct"]},
    "management_governance": {"non_financial": ["promoter_holding_pct", "promoter_pledged_pct",
                                                "promoter_holding_change_1y", "return_on_incremental_capital"]},
    "valuation": {"non_financial": ["pe", "ev_ebitda", "market_cap_cr", "last_price"],
                  FINANCIAL: ["pb", "market_cap_cr", "last_price"]},
}  # fmt: skip
FMT = {"ratio": lambda v: f"{v:.1%}", "pct": lambda v: f"{v:.1f}%", "pp": lambda v: f"{v:+.1f} pp",
       "x": lambda v: f"{v:.2f}x", "days": lambda v: f"{v:.0f} days"}  # fmt: skip
LABEL = {
    "roce_avg_3y": "3y average ROCE", "roce_latest": "ROCE", "operating_margin_avg": "average operating margin",
    "operating_margin_stdev": "margin volatility (std dev)", "roe_avg_3y": "3y average ROE", "roe_latest": "ROE",
    "roa_latest": "ROA", "revenue_cagr": "revenue CAGR", "profit_cagr": "profit CAGR",
    "profit_positive_ratio": "share of profitable years", "cfo_to_pat_3y": "3y operating cash flow / profit",
    "debt_to_equity": "debt/equity", "interest_coverage": "interest cover", "net_debt_to_ebitda": "net debt / EBITDA",
    "capital_adequacy_ratio": "capital adequacy", "gross_npa_pct": "gross NPA", "net_npa_pct": "net NPA",
    "promoter_holding_pct": "promoter holding", "promoter_pledged_pct": "share of promoter holding pledged",
    "promoter_holding_change_1y": "promoter holding change over a year",
    "return_on_incremental_capital": "return on incremental capital",
}  # fmt: skip


HORIZON_LABELS = {"long_term": "Long term", "medium_term": "Medium term"}
OUTLOOK_METRICS = ["revenue_growth_q_yoy", "profit_growth_q_yoy", "profit_growth_q_yoy_prev", "revenue_growth_latest",
                   "profit_growth_latest", "profit_cagr"]  # fmt: skip


@dataclass
class AssessmentInputs:
    sector_group: str
    metrics: dict[str, Metric]
    values: dict[str, float | None]
    dimension_scores: dict[str, float]
    missing_components: list[str]
    score: float | None
    flags: list[GovernanceFlag]
    rules: list[RuleResult]
    data_quality: DataQualityReport
    valuation: dict
    unverified_material: int
    financial_source_keys: list[str]
    price_source_keys: list[str]
    shareholding_source_keys: list[str]
    narrative_available: bool = True  # False when the business analysis (LLM) step did not produce output
    # horizons
    horizon_scores: dict[str, float] = field(default_factory=dict)
    medium_term_scores: dict[str, float] = field(default_factory=dict)
    medium_term_missing: list[str] = field(default_factory=list)
    earnings_basis: str | None = None
    catalysts: list[dict] = field(default_factory=list)
    primary_horizon: str = "long_term"  # whose classification is the report's headline conclusion
    horizon_years: dict[str, int] = field(default_factory=lambda: {"long_term": 5, "medium_term": 2})


def build_assessment(inp: AssessmentInputs, cfg: ScreeningConfig, evidence_id_for: dict[str, str]) -> dict:
    """`evidence_id_for` maps source keys to report evidence ids (E1, E2, ...)."""
    a = cfg.assessment
    ids = lambda keys: sorted({evidence_id_for[k] for k in keys if k in evidence_id_for}, key=_id_order)  # noqa: E731
    fin_ids, price_ids, holding_ids = ids(inp.financial_source_keys), ids(inp.price_source_keys), ids(inp.shareholding_source_keys)
    group = FINANCIAL if inp.sector_group == FINANCIAL else "non_financial"

    def metric_keys(category: str) -> list[str]:
        by = CATEGORY_METRICS[category]
        return [k for k in by.get(group, by["non_financial"]) if k in inp.metrics]

    red_flags = _red_flags(inp, cfg, ids)
    out: dict = {}

    # Business quality
    bq = inp.dimension_scores.get("business_quality", 0.0)
    out["business_quality"] = _item(_three(bq, a.strong_score, a.weak_score, ("Strong", "Average", "Weak")), bq,
                                    _metric_reasons(inp, metric_keys("business_quality")), metric_keys("business_quality"),
                                    fin_ids)  # fmt: skip

    # Financial health = performance and strength, weighted as in the score
    w = cfg.scoring.weights_for(inp.sector_group)
    perf, strength = inp.dimension_scores.get("financial_performance", 0.0), inp.dimension_scores.get("financial_strength", 0.0)
    fh = round((perf * w["financial_performance"] + strength * w["financial_strength"])
               / (w["financial_performance"] + w["financial_strength"]), 1)  # fmt: skip
    fh_rating = _three(fh, a.strong_score, a.weak_score, ("Strong", "Average", "Weak"))
    fh_reasons = [f"Performance {perf}/100, balance-sheet strength {strength}/100."]
    critical = [r for r in inp.rules if r.hard and r.status == "fail" and r.stage == "quality"]
    if critical:
        fh_rating = "Weak"
        fh_reasons += [f"Failed hard rule: {r.message}" for r in critical]
    out["financial_health"] = _item(fh_rating, fh, fh_reasons + _metric_reasons(inp, metric_keys("financial_health")),
                                    metric_keys("financial_health"), fin_ids)  # fmt: skip

    # Management and governance
    mg = inp.dimension_scores.get("management_governance", 0.0)
    serious = [f for f in inp.flags if f.severity == "serious"]
    warnings = [f for f in inp.flags if f.severity == "warning"]
    if serious:
        mg_rating = "Concerning"
    elif warnings:
        mg_rating = "Concerning" if mg < a.weak_score else "Mixed"
    else:
        mg_rating = _three(mg, a.strong_score, a.weak_score, ("Positive", "Mixed", "Concerning"))
    mg_reasons = ([f"Serious: {f.message}" for f in serious] + [f"Warning: {f.message}" for f in warnings]
                  or ["No governance events or pledge/holding warnings in the lookback window."])  # fmt: skip
    mg_keys = metric_keys("management_governance")
    out["management_governance"] = _item(mg_rating, mg, mg_reasons + _metric_reasons(inp, mg_keys), mg_keys,
                                         sorted(set(ids([f.evidence_key for f in inp.flags if f.evidence_key]) + holding_ids
                                                    + fin_ids), key=_id_order))  # fmt: skip

    # Valuation, per horizon
    val_ids = sorted(set(price_ids + fin_ids), key=_id_order)
    valuations = {}
    for h in inp.horizon_years:
        rating, reasons = assess_valuation(inp.valuation, inp.metrics, cfg.valuation, h)
        valuations[h] = _item(rating, inp.dimension_scores.get("valuation"), reasons, metric_keys("valuation"), val_ids)

    # Data quality
    dq = inp.data_quality
    dq_rating = _three(dq.score, a.data_quality_high, a.data_quality_medium, ("High", "Medium", "Low"))
    dq_reasons = [f"Validation score {dq.score}/100 over {dq.years_available} year(s), latest {dq.latest_period}."]
    dq_reasons += [i.message for i in dq.issues if i.severity in ("error", "warning")]
    if dq.years_available < cfg.eligibility.preferred_years and dq_rating == "High":
        dq_rating = "Medium"
        dq_reasons.append(f"Fewer than {cfg.eligibility.preferred_years} years of history.")
    if inp.unverified_material and dq_rating == "High":
        dq_rating = "Medium"
        dq_reasons.append(f"{inp.unverified_material} material analytical claim(s) could not be verified.")
    if len(inp.missing_components) > a.max_missing_components:
        dq_rating = "Low"
        dq_reasons.append(f"{len(inp.missing_components)} scoring inputs missing: {', '.join(inp.missing_components)}.")
    out["data_quality"] = _item(dq_rating, dq.score, dq_reasons, [], fin_ids)

    horizons: dict[str, dict] = {}
    if "long_term" in inp.horizon_years:
        cls, reasons, gaps = _classify_long(out, valuations["long_term"]["rating"], red_flags, inp, cfg)
        horizons["long_term"] = _horizon("long_term", inp, cls, reasons, gaps, red_flags, out,
                                         {"valuation": valuations["long_term"]})  # fmt: skip
    if "medium_term" in inp.horizon_years:
        outlook = _earnings_outlook(inp, cfg)
        outlook["metric_refs"] = [k for k in OUTLOOK_METRICS if k in inp.metrics]
        outlook["evidence_ids"] = fin_ids
        catalysts = [{**c, "evidence_ids": ids([c.get("evidence_key")])} for c in inp.catalysts]
        catalyst_item = {"rating": "Identified" if catalysts else "None visible", "items": catalysts,
                         "note": "Only catalysts evidenced in filings or industry data; management targets are not "
                                 "treated as outcomes."}  # fmt: skip
        cls, reasons, gaps = _classify_medium(out, valuations["medium_term"]["rating"], outlook["rating"], catalysts,
                                              red_flags, inp, cfg)  # fmt: skip
        horizons["medium_term"] = _horizon("medium_term", inp, cls, reasons, gaps, red_flags, out, {
            "valuation": valuations["medium_term"], "earnings_outlook": outlook, "catalysts": catalyst_item,
            "category_scores": inp.medium_term_scores, "missing_components": inp.medium_term_missing,
        })  # fmt: skip

    primary = inp.primary_horizon if inp.primary_horizon in horizons else next(iter(horizons))
    head = horizons[primary]
    out["valuation"] = head["valuation"]
    out["overall"] = {"classification": head["classification"], "label": head["label"], "meaning": head["meaning"],
                      "score": head["score"], "horizon": primary, "years": head["years"], "reasons": head["reasons"],
                      "main_concern": head["main_concern"]}  # fmt: skip
    out["horizons"] = horizons
    out["red_flags"] = red_flags
    return out


def _horizon(name, inp, cls, reasons, gaps, red_flags, out, extra) -> dict:
    return {
        "label": LABELS[cls], "classification": cls, "meaning": MEANING[cls], "horizon_label": HORIZON_LABELS[name],
        "years": inp.horizon_years[name], "score": inp.horizon_scores.get(name, inp.score if name == "long_term" else None),
        "reasons": reasons, "main_concern": _main_concern(cls, gaps, red_flags, out, extra["valuation"]["rating"]),
        **extra,
    }  # fmt: skip


def _gates(r: dict, red_flags: list[dict], inp: AssessmentInputs, summary: str) -> tuple[str, list[str], list[str]] | None:
    """Outcomes that don't depend on the horizon: unusable data and serious risks."""
    if not inp.data_quality.is_eligible:
        errs = [i.message for i in inp.data_quality.errors]
        return "insufficient_evidence", ["Data failed validation:", *errs], errs
    if r["data_quality"] == "Low":
        return "insufficient_evidence", [summary, "Data quality is too low to rely on the analysis."], ["data quality is low"]
    if red_flags:
        return ("high_risk", [summary, "Red flags (reported separately, not offset by other scores):"]
                + [f["message"] for f in red_flags], [])  # fmt: skip
    if r["management_governance"] == "Concerning":
        return "high_risk", [summary, "Management and governance assessment is concerning."], ["governance concerns"]
    if r["financial_health"] == "Weak":
        return "high_risk", [summary, "Financial health is weak."], ["weak financial health"]
    return None


def _common_gaps(r: dict, valuation: str, score: float | None, inp: AssessmentInputs, cfg: ScreeningConfig) -> list[str]:
    a = cfg.assessment
    gaps = []
    if valuation not in ("Attractive", "Fair"):
        gaps.append(f"valuation is {valuation.lower()}")
    if r["management_governance"] != "Positive":
        gaps.append("management/governance has open questions")
    if score is None or score < a.strong_candidate_min_score:
        gaps.append(f"score {score} is below {a.strong_candidate_min_score:.0f}")
    if inp.unverified_material:
        gaps.append(f"{inp.unverified_material} material claim(s) failed verification")
    if not inp.narrative_available:
        gaps.append("the business itself has not been analysed (narrative analysis unavailable)")
    illiquid = [x for x in inp.rules if x.rule_id == "liquidity" and x.status != "pass"]
    if illiquid:
        gaps.append(f"liquidity: {illiquid[0].message}")
    return gaps


def _ratings(out: dict) -> dict:
    return {k: out[k]["rating"] for k in ("business_quality", "financial_health", "management_governance", "data_quality")}


def _classify_long(out, valuation, red_flags, inp, cfg) -> tuple[str, list[str], list[str]]:
    r = _ratings(out)
    summary = (f"Business {r['business_quality']}, financial health {r['financial_health']}, management "
               f"{r['management_governance']}, valuation {valuation}, data quality {r['data_quality']}.")  # fmt: skip
    if gated := _gates(r, red_flags, inp, summary):
        return gated
    good_business = r["business_quality"] == "Strong" and r["financial_health"] in ("Strong", "Average")
    if good_business and valuation == "Expensive":
        return ("good_business_expensive", [summary, "Strong business, but the price already reflects much of it; "
                "it becomes more interesting if the price falls or earnings catch up with the multiple."],
                ["limited valuation cushion"])  # fmt: skip
    gaps = ([] if good_business else ["business quality or financial health is not strong enough"])
    gaps += _common_gaps(r, valuation, inp.horizon_scores.get("long_term", inp.score), inp, cfg)
    if not gaps:
        return "strong_candidate", [summary, "Strong fundamentals at an acceptable price."], []
    return "potential_opportunity", [summary, "Not a strong candidate yet because " + "; ".join(gaps) + "."], gaps


def _earnings_outlook(inp: AssessmentInputs, cfg: ScreeningConfig) -> dict:
    a = cfg.assessment
    score = inp.medium_term_scores.get("earnings_outlook", 0.0)
    v = inp.values
    basis = inp.earnings_basis or "annual"
    if basis == "quarterly":
        reasons = [f"Latest quarter YoY: revenue {_pct(v.get('revenue_growth_q_yoy'))}, profit "
                   f"{_pct(v.get('profit_growth_q_yoy'))} (previous quarter {_pct(v.get('profit_growth_q_yoy_prev'))})."]  # fmt: skip
    else:
        reasons = [f"No quarterly data: latest year revenue {_pct(v.get('revenue_growth_latest'))}, profit "
                   f"{_pct(v.get('profit_growth_latest'))} vs 5-year profit CAGR {_pct(v.get('profit_cagr'))}."]  # fmt: skip
    rating = _three(score, a.strong_score, a.weak_score, ("Improving", "Stable", "Weakening"))
    if any(m.startswith("earnings_outlook") for m in inp.medium_term_missing):
        rating = "Unknown" if score == 0 else rating
        reasons.append("Some earnings-momentum inputs are missing.")
    return {"rating": rating, "score": score, "basis": basis, "reasons": reasons}


def _classify_medium(out, valuation, outlook, catalysts, red_flags, inp, cfg) -> tuple[str, list[str], list[str]]:
    r = _ratings(out)
    bfq = _three(inp.medium_term_scores.get("business_financial_quality", 0.0), cfg.assessment.strong_score,
                 cfg.assessment.weak_score, ("Strong", "Average", "Weak"))  # fmt: skip
    summary = (f"Business and financial quality {bfq}, earnings outlook {outlook}, catalysts "
               f"{'identified' if catalysts else 'none visible'}, valuation {valuation}, management "
               f"{r['management_governance']}.")  # fmt: skip
    if gated := _gates(r, red_flags, inp, summary):
        return gated
    if bfq == "Strong" and valuation == "Expensive":
        return ("good_business_expensive", [summary, f"Over {inp.horizon_years['medium_term']} year(s) the current "
                "multiple leaves little room: returns depend on the market paying even more."],
                ["limited valuation cushion over the horizon"])  # fmt: skip
    gaps = ["business and financial quality is weak"] if bfq == "Weak" else []
    if outlook != "Improving":
        gaps.append(f"earnings outlook is {outlook.lower()}")
    gaps += _common_gaps(r, valuation, inp.horizon_scores.get("medium_term"), inp, cfg)
    if not gaps:
        return "strong_candidate", [summary, "Sound business with improving earnings at an acceptable price."], []
    reasons = [summary, "Not a strong candidate yet because " + "; ".join(gaps) + "."]
    if catalysts and outlook != "Improving":
        reasons.append("The case depends on the identified catalysts translating into earnings; track them.")
    return "potential_opportunity", reasons, gaps


def _main_concern(cls: str, gaps: list[str], red_flags: list[dict], out: dict, valuation: str) -> str:
    if red_flags:
        return red_flags[0]["message"]
    if gaps:
        return gaps[0][0].upper() + gaps[0][1:]
    if valuation == "Fair":
        return "Valuation is fair rather than cheap: returns depend on the business delivering."
    weakest = min(("business_quality", "financial_health", "management_governance"),
                  key=lambda k: out[k]["score"] if out[k]["score"] is not None else 0)  # fmt: skip
    return f"Weakest area: {weakest.replace('_', ' ')} ({out[weakest]['rating']})."


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:+.1%}"


def _red_flags(inp: AssessmentInputs, cfg: ScreeningConfig, ids) -> list[dict]:
    a = cfg.assessment
    v = inp.values
    flags = [{"code": f.code, "category": "governance", "message": f.message, "evidence_ids": ids([f.evidence_key])}
             for f in inp.flags if f.severity == "serious"]  # fmt: skip
    fin_ids = ids(inp.financial_source_keys)

    def add(code: str, category: str, message: str, metric: str | None = None):
        flags.append({"code": code, "category": category, "message": message, "evidence_ids": fin_ids,
                      "metric_refs": [metric] if metric else []})  # fmt: skip

    for r in inp.rules:
        if r.hard and r.status == "fail" and r.stage == "quality":
            add(r.rule_id, "financial", r.message)
    net_margin = v.get("net_margin_latest")
    if net_margin is not None and net_margin < 0:
        add("loss_making", "financial", f"Loss-making in the latest year (net margin {net_margin:.1%}).", "net_margin_latest")
    if inp.sector_group == FINANCIAL:
        npa = v.get("gross_npa_pct")
        if npa is not None and npa > a.red_flag_max_gross_npa_pct:
            add("asset_quality", "financial", f"Gross NPA {npa:.1f}% above {a.red_flag_max_gross_npa_pct:.0f}%.", "gross_npa_pct")
    else:
        de = v.get("debt_to_equity")
        if de is not None and de > a.red_flag_max_debt_to_equity:
            add("high_leverage", "financial", f"Debt/equity {de:.2f}x above {a.red_flag_max_debt_to_equity:.1f}x.",
                "debt_to_equity")  # fmt: skip
        cfo = v.get("cfo_to_pat_3y")
        if cfo is not None and cfo < a.red_flag_min_cfo_to_pat:
            add("cash_flow_divergence", "financial", f"Only {cfo:.0%} of 3-year reported profit came in as operating "
                "cash flow: earnings quality is in doubt.", "cfo_to_pat_3y")  # fmt: skip
    return flags


def _item(rating: str, score: float | None, reasons: list[str], metric_refs: list[str], evidence_ids: list[str]) -> dict:
    return {"rating": rating, "score": score, "reasons": reasons, "metric_refs": metric_refs, "evidence_ids": evidence_ids}


def _three(value: float, high: float, low: float, labels: tuple[str, str, str]) -> str:
    return labels[0] if value >= high else labels[1] if value >= low else labels[2]


def _metric_reasons(inp: AssessmentInputs, keys: list[str]) -> list[str]:
    out = []
    for k in keys:
        m = inp.metrics[k]
        if m.value is None:
            out.append(f"{LABEL.get(k, k)}: not available{f' ({m.note})' if m.note else ''}.")
        else:
            fmt = FMT.get(m.unit, lambda v: f"{v:,.2f}")
            out.append(f"{LABEL.get(k, k)} {fmt(m.value)}{f' ({m.period})' if m.period else ''}.")
    return out


def _id_order(evidence_id: str) -> int:
    return int(evidence_id[1:]) if evidence_id[1:].isdigit() else 0
