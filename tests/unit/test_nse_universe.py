from datetime import date

from app.services.data.providers.nse_universe_provider import parse_equity_list
from app.services.discovery.rules_config import UniverseCfg
from app.services.discovery.universe_loader import exclusion_reason

SAMPLE = b"""SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE
ABCIND,ABC Industries Limited,EQ,08-SEP-1995,10,1,INE000A01011,10
XYZSME,XYZ Agro Limited,SM,15-MAR-2023,10,1,INE000B01012,10
GOLDETF,Some Gold ETF,EQ,01-JAN-2010,1,1,INF000C01013,1
OLDCO,Old Company Ltd,BZ,01-JAN-2001,10,1,INE000D01014,10
"""

CFG = UniverseCfg(include_series=["EQ", "BE"], exclude_sme=True)


def test_parse_equity_list_classifies_instruments():
    entries = {e.symbol: e for e in parse_equity_list(SAMPLE)}
    assert entries["ABCIND"].isin == "INE000A01011"
    assert entries["ABCIND"].listed_on == date(1995, 9, 8)
    assert entries["XYZSME"].is_sme
    assert entries["GOLDETF"].instrument_type == "ETF"


def test_universe_exclusions():
    entries = {e.symbol: e for e in parse_equity_list(SAMPLE)}
    assert exclusion_reason(entries["ABCIND"], CFG) is None
    assert "SME" in exclusion_reason(entries["XYZSME"], CFG)
    assert "ETF" in exclusion_reason(entries["GOLDETF"], CFG)
    assert "series BZ" in exclusion_reason(entries["OLDCO"], CFG)
