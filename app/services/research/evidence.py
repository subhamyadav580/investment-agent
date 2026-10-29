"""Evidence registry and claim verification.

Every LLM claim must cite evidence ids (sources we actually retrieved) and/or metric keys (values we actually
computed). Verification is deterministic: unknown ids, unknown/null metrics, unsupported material claims, and
percentages or multiples that match no computed metric are all flagged - never silently accepted.
"""

import re
from collections.abc import Iterable

from app.schemas.market_data import SourceRef
from app.schemas.research import Claim, EvidenceItem, RiskItem, VerifiedClaim
from app.schemas.screening import Metric

_ORDER = {"annual_report": 0, "fixture": 0, "secondary_aggregator": 0, "quarterly_result": 1, "secondary": 2, "shareholding_pattern": 3,
          "exchange_filing": 4, "price_feed": 5}  # fmt: skip

_PCT_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s?%")
_MULT_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s?x\b", re.IGNORECASE)

PCT_ABS_TOL = 0.6  # percentage points
REL_TOL = 0.05


def build_evidence(sources: dict[str, SourceRef]) -> tuple[list[EvidenceItem], dict[str, str]]:
    ordered = sorted(sources.values(), key=lambda s: (_ORDER.get(s.source_type, 9), s.key))
    items, key_by_id = [], {}
    for i, ref in enumerate(ordered, 1):
        eid = f"E{i}"
        key_by_id[eid] = ref.key
        items.append(
            EvidenceItem(
                id=eid, source_type=ref.source_type, provider=ref.provider, title=ref.title, url=ref.url,
                published_at=ref.published_at, retrieved_at=ref.retrieved_at, is_synthetic=ref.is_synthetic,
            )
        )  # fmt: skip
    return items, key_by_id


def _metric_numbers(metrics: Iterable[Metric]) -> tuple[list[float], list[float]]:
    """Returns (percentages, multiples) representations of the given metrics."""
    pcts, mults = [], []
    for m in metrics:
        if m.value is None:
            continue
        if m.unit == "ratio":
            pcts.append(m.value * 100)
        elif m.unit == "pct":
            pcts.append(m.value)
        elif m.unit == "x":
            mults.append(m.value)
    return pcts, mults


def _matches(n: float, candidates: list[float], pct: bool) -> bool:
    for c in candidates:
        if pct and abs(n - c) <= PCT_ABS_TOL:
            return True
        if abs(n - c) <= REL_TOL * max(abs(c), 1e-9):
            return True
    return False


def verify_claim(
    section: str,
    statement: str,
    evidence_ids: list[str],
    metric_refs: list[str],
    materiality: str,
    known_evidence: set[str],
    metrics: dict[str, Metric],
    reference_numbers: Iterable[float] = (),
) -> VerifiedClaim:
    problems = []
    unknown_ev = [e for e in evidence_ids if e not in known_evidence]
    if unknown_ev:
        problems.append(f"cites unknown evidence ids {unknown_ev}")
    unknown_m = [k for k in metric_refs if k not in metrics]
    if unknown_m:
        problems.append(f"cites unknown metrics {unknown_m}")
    null_m = [k for k in metric_refs if k in metrics and metrics[k].value is None]
    if null_m:
        problems.append(f"relies on metrics with no value {null_m}")
    valid_ev = [e for e in evidence_ids if e in known_evidence]
    valid_m = [k for k in metric_refs if k in metrics and metrics[k].value is not None]
    if materiality == "material" and not valid_ev and not valid_m:
        problems.append("material claim without valid supporting evidence or metric")

    cited_p, cited_x = _metric_numbers(metrics[k] for k in valid_m)
    all_p, all_x = _metric_numbers(metrics.values())
    # Thresholds, peer medians, and valuation-band figures the model was shown are legitimate numbers too.
    refs = [r for n in reference_numbers for r in (n, n * 100)]
    all_p, all_x = all_p + refs, all_x + refs
    for raw in _PCT_RE.findall(statement):
        n = float(raw)
        if not _matches(n, cited_p, pct=True) and not _matches(n, all_p, pct=True):
            problems.append(f"{raw}% does not match any computed metric")
    for raw in _MULT_RE.findall(statement):
        n = float(raw)
        if not _matches(n, cited_x, pct=False) and not _matches(n, all_x, pct=False):
            problems.append(f"{raw}x does not match any computed metric")

    return VerifiedClaim(
        section=section, statement=statement, evidence_ids=evidence_ids, metric_refs=metric_refs,
        materiality=materiality, verified=not problems, problems=problems,
    )  # fmt: skip


def verify_claims(
    section: str,
    claims: list[Claim],
    known_evidence: set[str],
    metrics: dict[str, Metric],
    reference_numbers: Iterable[float] = (),
) -> list[VerifiedClaim]:
    refs = list(reference_numbers)
    return [
        verify_claim(section, c.statement, c.evidence_ids, c.metric_refs, c.materiality, known_evidence, metrics, refs)
        for c in claims
    ]


def verify_risks(
    risks: list[RiskItem], known_evidence: set[str], metrics: dict[str, Metric], reference_numbers: Iterable[float] = ()
) -> list[VerifiedClaim]:
    refs = list(reference_numbers)
    return [
        verify_claim(f"risk:{r.category}", r.description, r.evidence_ids, r.metric_refs,
                     "material" if r.severity != "low" else "minor", known_evidence, metrics, refs)  # fmt: skip
        for r in risks
    ]


def numeric_leaves(obj: object) -> list[float]:
    """All numbers nested in dicts/lists (used to collect reference figures shown to the model)."""
    if isinstance(obj, bool):
        return []
    if isinstance(obj, int | float):
        return [float(obj)]
    if isinstance(obj, dict):
        return [n for v in obj.values() for n in numeric_leaves(v)]
    if isinstance(obj, list | tuple):
        return [n for v in obj for n in numeric_leaves(v)]
    return []
