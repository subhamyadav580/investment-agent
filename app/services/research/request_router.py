"""Request router: turns "Research Asian Paints for a 5-year investment" into (company, horizon, years).

Deterministic parsing only. A horizon can come from the text or from explicit options; explicit options win.
Long term is 5-10 years, medium term 1-3 years; a period between or beyond them is rejected rather than guessed.
"""

import re
from dataclasses import dataclass

from app.services.discovery.rules_config import HorizonsCfg

HORIZONS = ("long_term", "medium_term", "both")
_YEARS = re.compile(r"\b(?:for|over|with)\s+(?:a|an|the\s+next)?\s*(\d{1,2})\s*[- ]?\s*(?:years?|yrs?)\b"
                    r"(?:\s+(?:investment|horizon|holding(?:\s+period)?|view))?", re.I)  # fmt: skip
_NAMED = [
    (re.compile(r"\b(?:for\s+)?(?:both\s+)?(?:(?:long|medium|mid)(?:[- ]term)?\s*(?:and|&|/|,)\s*(?:long|medium|mid)"
                r"[- ]terms?|both\s+horizons?|both)\b", re.I), "both"),
    (re.compile(r"\b(?:for\s+the\s+)?long[- ]term\b", re.I), "long_term"),
    (re.compile(r"\b(?:for\s+the\s+)?(?:medium|mid)[- ]term\b", re.I), "medium_term"),
]  # fmt: skip
_LEAD = re.compile(r"^\s*(?:please\s+)?(?:research|analy[sz]e|evaluate|look\s+at|check)\s*:?\s+", re.I)
_TRAIL = re.compile(r"(?:[\s,.;:-]+(?:for|over|investment|horizon)?)+\s*$", re.I)


class HorizonError(ValueError):
    pass


@dataclass
class ResearchRequestSpec:
    query: str  # company name or symbol
    horizon: str  # long_term | medium_term | both
    years: dict[str, int]  # horizon -> years; always both horizons, so the report can compare them

    @property
    def primary(self) -> str:
        return "medium_term" if self.horizon == "medium_term" else "long_term"


def parse_request(text: str, cfg: HorizonsCfg, horizon: str | None = None, years: int | None = None) -> ResearchRequestSpec:
    query, text_horizon, text_years = text, None, None
    if m := _YEARS.search(query):
        text_years = int(m.group(1))
        query = query[: m.start()] + query[m.end() :]
    for pattern, name in _NAMED:
        if m := pattern.search(query):
            text_horizon = text_horizon or name
            query = query[: m.start()] + query[m.end() :]
    query = _TRAIL.sub("", _LEAD.sub("", query)).strip()
    if not query:
        raise HorizonError("No company name or symbol found in the request.")

    years = years if years is not None else text_years
    horizon = horizon or text_horizon
    if horizon is None:
        horizon = horizon_for_years(years, cfg) if years is not None else "long_term"
    if horizon not in HORIZONS:
        raise HorizonError(f"Unknown horizon {horizon!r}; use long_term, medium_term or both.")

    resolved = {"long_term": cfg.long_term.default_years, "medium_term": cfg.medium_term.default_years}
    if years is not None:
        if horizon == "both":
            raise HorizonError("Give one horizon when stating a number of years, or omit the years for both.")
        bounds = getattr(cfg, horizon)
        if not bounds.min_years <= years <= bounds.max_years:
            raise HorizonError(f"{years} years is outside the {horizon.replace('_', '-')} range "
                               f"({bounds.min_years}-{bounds.max_years} years).")  # fmt: skip
        resolved[horizon] = years
    return ResearchRequestSpec(query=query, horizon=horizon, years=resolved)


def horizon_for_years(years: int, cfg: HorizonsCfg) -> str:
    for name in ("medium_term", "long_term"):
        b = getattr(cfg, name)
        if b.min_years <= years <= b.max_years:
            return name
    raise HorizonError(
        f"{years} years fits neither horizon: medium term is {cfg.medium_term.min_years}-{cfg.medium_term.max_years} "
        f"years, long term {cfg.long_term.min_years}-{cfg.long_term.max_years}. Pick one of those."
    )
