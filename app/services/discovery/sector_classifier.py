"""Maps provider sector/industry labels to the sector groups that screening rules branch on."""

FINANCIAL = "financial"
NON_FINANCIAL = "non_financial"

_FINANCIAL_KEYWORDS = ("bank", "financ", "nbfc", "insurance", "lending", "housing finance", "capital markets")
_CYCLICAL_KEYWORDS = (
    "metal", "steel", "mining", "cement", "auto", "chemical", "oil", "gas", "real estate",
    "construction", "infra", "capital goods", "commodit", "sugar", "textile",
)  # fmt: skip


def classify_sector_group(sector: str | None, industry: str | None, name: str | None = None) -> tuple[str, bool]:
    """Returns (sector_group, inferred). `inferred` is True when we fell back to the company name."""
    label = f"{sector or ''} {industry or ''}".lower().strip()
    if label:
        return (FINANCIAL if any(k in label for k in _FINANCIAL_KEYWORDS) else NON_FINANCIAL), False
    lowered = (name or "").lower()
    if any(k in lowered for k in ("bank", "finance", "insurance", "financial")):
        return FINANCIAL, True
    return NON_FINANCIAL, True


def is_cyclical(sector: str | None, industry: str | None) -> bool:
    label = f"{sector or ''} {industry or ''}".lower()
    return any(k in label for k in _CYCLICAL_KEYWORDS)
