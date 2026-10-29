"""Exchange daily price files ("bhavcopy"): URLs and parsers. Pure functions, no I/O.

NSE publishes a common-format (UDiFF) file since 8 Jul 2024 and a legacy format before that.
BSE's UDiFF file is used for dates from 8 Jul 2024 onwards.
"""

import csv
import io
import zipfile
from dataclasses import dataclass
from datetime import date

NSE_UDIFF_START = date(2024, 7, 8)
BSE_UDIFF_START = date(2024, 7, 8)

# Series/groups that are listed equity. Debt, ETFs, REITs/InvITs, govt securities etc. are skipped.
# BL (block-deal window) is excluded: those trades aren't the regular market price and duplicate the symbol.
NSE_EQUITY_SERIES = {"EQ", "BE", "BZ", "SM", "ST", "SZ"}
BSE_MAIN_GROUPS = {"A", "B", "T", "X", "XT", "Z", "ZP", "P"}
BSE_SME_GROUPS = {"M", "MT", "MS"}
BSE_EQUITY_GROUPS = BSE_MAIN_GROUPS | BSE_SME_GROUPS


@dataclass(frozen=True)
class PriceRow:
    security_key: str  # NSE symbol / BSE scrip code
    symbol: str
    name: str | None
    isin: str | None
    series: str
    close: float
    volume: float | None
    traded_value: float | None  # INR


def nse_url(d: date) -> str:
    if d >= NSE_UDIFF_START:
        return f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
    mon = d.strftime("%b").upper()
    return f"https://nsearchives.nseindia.com/content/historical/EQUITIES/{d.year}/{mon}/cm{d:%d}{mon}{d.year}bhav.csv.zip"


def bse_url(d: date) -> str | None:
    if d < BSE_UDIFF_START:
        return None  # older BSE formats are not supported
    return f"https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{d:%Y%m%d}_F_0000.CSV"


def _unzip_or_raw(content: bytes) -> str:
    if content[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            return z.read(z.namelist()[0]).decode("utf-8-sig", errors="replace")
    return content.decode("utf-8-sig", errors="replace")


def _f(v: str | None) -> float | None:
    v = (v or "").strip()
    try:
        return float(v) if v else None
    except ValueError:
        return None


def parse_nse(content: bytes) -> list[PriceRow]:
    text = _unzip_or_raw(content)
    reader = csv.DictReader(io.StringIO(text))
    fields = {f.strip() for f in reader.fieldnames or []}
    out = []
    if "TckrSymb" in fields:  # UDiFF
        for r in reader:
            series = (r.get("SctySrs") or "").strip()
            if r.get("FinInstrmTp", "").strip() != "STK" or series not in NSE_EQUITY_SERIES:
                continue
            close = _f(r.get("ClsPric"))
            if close is None:
                continue
            sym = r["TckrSymb"].strip()
            out.append(PriceRow(sym, sym, (r.get("FinInstrmNm") or "").strip() or None, (r.get("ISIN") or "").strip() or None,
                                series, close, _f(r.get("TtlTradgVol")), _f(r.get("TtlTrfVal"))))  # fmt: skip
    else:  # legacy cmDDMONYYYYbhav.csv
        for r in reader:
            r = {k.strip(): v for k, v in r.items() if k}
            series = (r.get("SERIES") or "").strip()
            if series not in NSE_EQUITY_SERIES or _f(r.get("CLOSE")) is None:
                continue
            sym = r["SYMBOL"].strip()
            out.append(PriceRow(sym, sym, None, (r.get("ISIN") or "").strip() or None, series, _f(r["CLOSE"]),
                                _f(r.get("TOTTRDQTY")), _f(r.get("TOTTRDVAL"))))  # fmt: skip
    return out


def parse_bse(content: bytes) -> list[PriceRow]:
    reader = csv.DictReader(io.StringIO(_unzip_or_raw(content)))
    out = []
    for r in reader:
        group = (r.get("SctySrs") or "").strip()
        if r.get("FinInstrmTp", "").strip() != "STK" or group not in BSE_EQUITY_GROUPS:
            continue
        close = _f(r.get("ClsPric"))
        if close is None:
            continue
        out.append(PriceRow((r.get("FinInstrmId") or "").strip(), (r.get("TckrSymb") or "").strip(),
                            (r.get("FinInstrmNm") or "").strip() or None, (r.get("ISIN") or "").strip() or None,
                            group, close, _f(r.get("TtlTradgVol")), _f(r.get("TtlTrfVal"))))  # fmt: skip
    return out


def dedupe(rows: list[PriceRow]) -> list[PriceRow]:
    """One row per security per day: keep the most-traded one if a file lists a security twice."""
    best: dict[str, PriceRow] = {}
    for r in rows:
        cur = best.get(r.security_key)
        if cur is None or (r.traded_value or 0) > (cur.traded_value or 0):
            best[r.security_key] = r
    return list(best.values())
