from datetime import UTC, date, datetime

import pytest

from app.services.data.normalization import (
    UnknownUnitError,
    normalize_fy_period,
    normalize_symbol,
    parse_company_document,
    to_crore,
)


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [(5.0, "INR_crore", 5.0), (250.0, "lakh", 2.5), (30.0, "INR_million", 3.0), (2.0, "billion", 200.0),
     (12_345_678.0, "INR", 1.2345678)],
)  # fmt: skip
def test_unit_conversion_to_crore(value, unit, expected):
    assert to_crore(value, unit) == pytest.approx(expected)


def test_unknown_unit_is_rejected_not_guessed():
    with pytest.raises(UnknownUnitError):
        to_crore(1.0, "thousand-ish")


@pytest.mark.parametrize("label", ["FY2026", "FY26", "2026", "Mar 2026", "March-2026", "2026-03", "2026-03-31"])
def test_fy_labels(label):
    assert normalize_fy_period(label) == ("FY2026", date(2026, 3, 31))


def test_bad_period_label():
    with pytest.raises(ValueError):
        normalize_fy_period("Q2 2026")


def test_symbol_normalization():
    assert normalize_symbol(" reliance.ns ") == "RELIANCE"
    assert normalize_symbol("TCS-EQ") == "TCS"


def test_document_parse_converts_units_and_keeps_percentages():
    doc = {
        "unit": "INR_lakh",
        "consolidation": "standalone",
        "annual": {"FY25": {"revenue": 10_000, "gross_npa_pct": 3.2}},
        "alternate_values": [{"period": "FY2025", "metric": "revenue", "value": 99, "unit": "INR_crore"}],
    }
    _, fin, _, _ = parse_company_document("X", doc, provider="t", retrieved_at=datetime.now(UTC))
    rev = [v for v in fin.values if v.metric == "revenue"]
    assert {v.value for v in rev} == {100.0, 99.0}
    assert len(fin.sources) == 2  # alternate value keeps its own source
    npa = next(v for v in fin.values if v.metric == "gross_npa_pct")
    assert npa.value == 3.2 and npa.unit == "pct"
    assert all(v.consolidation.value == "standalone" for v in fin.values)
