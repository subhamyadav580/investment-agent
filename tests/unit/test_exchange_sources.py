import io
import zipfile
from datetime import UTC, date, datetime

import pytest

from app.services.data.announcement_classifier import classify_announcement
from app.services.data.providers.bhavcopy import bse_url, nse_url, parse_bse, parse_nse
from app.services.data.providers.nse_announcements_provider import (
    parse_announcements,
    parse_board_meetings,
    parse_pledge,
)

UDIFF_HEADER = ("TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,StrkPric,"
                "OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,"
                "ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4")  # fmt: skip


def udiff_row(fid, isin, sym, series, name, close, vol, val, tp="STK"):
    return (f"2026-10-23,2026-10-23,CM,NSE,{tp},{fid},{isin},{sym},{series},,,,,{name},1,1,1,{close},{close},1,,1,,,"
            f"{vol},{val},10,F1,1,,,,,")  # fmt: skip


def zipped(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("f.csv", text)
    return buf.getvalue()


def test_urls():
    assert nse_url(date(2026, 10, 23)).endswith("BhavCopy_NSE_CM_0_0_0_20261023_F_0000.csv.zip")
    assert nse_url(date(2024, 1, 5)).endswith("/2024/JAN/cm05JAN2024bhav.csv.zip")
    assert bse_url(date(2026, 10, 23)).endswith("BhavCopy_BSE_CM_0_0_0_20261023_F_0000.CSV")
    assert bse_url(date(2024, 1, 5)) is None


def test_parse_nse_udiff_keeps_equity_only():
    csv_text = "\n".join([UDIFF_HEADER,
                          udiff_row(1, "INE1", "ABC", "EQ", "ABC LTD", "100.5", "1000", "100500"),
                          udiff_row(2, "IN0020", "GS2030", "GS", "GOVT BOND", "99", "5", "495"),
                          udiff_row(3, "INF1", "NIFTYBEES", "EQ", "ETF", "250", "10", "2500", tp="ETF")])  # fmt: skip
    rows = parse_nse(zipped(csv_text))
    assert [(r.security_key, r.close, r.volume, r.traded_value) for r in rows] == [("ABC", 100.5, 1000, 100500)]


def test_block_deal_rows_and_duplicates_are_dropped():
    from app.services.data.providers.bhavcopy import dedupe

    text = "\n".join([UDIFF_HEADER, udiff_row(1, "INE1", "ABC", "EQ", "ABC", "100", "1000", "100000"),
                      udiff_row(1, "INE1", "ABC", "BL", "ABC", "98", "50000", "4900000"),
                      udiff_row(1, "INE1", "ABC", "BE", "ABC", "100", "10", "1000")])  # fmt: skip
    rows = dedupe(parse_nse(zipped(text)))
    assert [(r.series, r.close) for r in rows] == [("EQ", 100.0)]


def test_parse_nse_legacy():
    text = ("SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,\n"
            "ABC,EQ,1,1,1,101,101,100,500,50500,05-JAN-2024,10,INE1,\n"
            "1018GS2026,GS,1,1,1,121,121,125,321,40547,05-JAN-2024,56,IN0020010081,\n")  # fmt: skip
    rows = parse_nse(zipped(text))
    assert [(r.symbol, r.close, r.isin) for r in rows] == [("ABC", 101.0, "INE1")]


def test_parse_bse_groups():
    text = "\n".join([UDIFF_HEADER,
                      udiff_row(500002, "INE117A01022", "ABB", "A", "ABB INDIA LIMITED", "6140", "20083", "123751767"),
                      udiff_row(540001, "INE9SME", "TINYSME", "M", "TINY SME LTD", "50", "100", "5000"),
                      udiff_row(970001, "INE9DEBT", "DEBT1", "F", "SOME DEBENTURE", "1000", "1", "1000")])  # fmt: skip
    rows = {r.security_key: r for r in parse_bse(text.encode())}
    assert set(rows) == {"500002", "540001"} and rows["500002"].symbol == "ABB" and rows["540001"].series == "M"


@pytest.mark.parametrize(
    ("subject", "text", "expected"),
    [
        ("Change in Auditors", "Resignation of M/s ABC & Co as Statutory Auditors", "auditor_resignation"),
        ("Change in Management", "Intimation regarding Resignation of Internal Auditor", "management_change"),
        ("Action(s) initiated or orders passed", "Disclosure under Regulation 30 of SEBI Listing Regulations",
         "regulatory_action"),
        ("Updates", "Order passed by the Securities and Exchange Board of India imposing a penalty", "sebi_order"),
        ("Corporate Insolvency Resolution Process", "8th CoC meeting", "insolvency"),
        ("Credit Rating", "CRISIL has downgraded the long term rating", "credit_rating_downgrade"),
        ("Credit Rating", "ICRA has upgraded the rating", "credit_rating_upgrade"),
        ("Outcome of Board Meeting", "Board approved the Financial Results for the quarter", "results"),
        ("Financial Result Updates", "Audited results with unmodified opinion", "results"),
        ("Statement on Impact of Audit Qualifications", "Auditor has expressed a qualified opinion", "auditor_qualification"),
        ("Bagging/Receiving of orders/contracts", "Order worth Rs 100 crore", "order_win"),
        ("Allotment of Securities", "allotment of 25365 NCDs", "debt_issue"),
        ("Copy of Newspaper Publication", "Newspaper advertisement", "other"),
    ],
)  # fmt: skip
def test_classifier(subject, text, expected):
    assert classify_announcement(subject, text) == expected


def test_parse_nse_payloads():
    at = datetime(2026, 10, 24, tzinfo=UTC)
    anns = parse_announcements([{"an_dt": "14-Oct-2026 17:38:03", "desc": "Change in Auditors", "symbol": "ABC",
                                 "attchmntText": "Resignation of statutory auditor", "seq_id": "1",
                                 "attchmntFile": "https://nsearchives.nseindia.com/corporate/x.pdf"},
                                {"desc": "missing date", "symbol": "ABC"}], at)  # fmt: skip
    assert len(anns) == 1 and anns[0].category == "auditor_resignation"
    assert anns[0].published_at.utcoffset().total_seconds() == 5.5 * 3600
    assert anns[0].source.url.endswith("x.pdf") and anns[0].source.source_type == "exchange_filing"

    bm = parse_board_meetings([{"bm_symbol": "ABC", "bm_date": "06-Nov-2026", "bm_purpose": "Financial Results",
                                "bm_timestamp": "21-Oct-2026 23:26:44"}], at)  # fmt: skip
    assert bm[0].category == "board_meeting" and bm[0].event_date == date(2026, 11, 6)

    pledge = parse_pledge({"data": [{"shp": "30-Sep-2026", "percPromoterHolding": "    24.00",
                                     "percPromoterShares": "    72.99"}]}, "ABC", at)  # fmt: skip
    assert (pledge.period_end, pledge.promoter_holding_pct, pledge.promoter_pledged_pct) == (date(2026, 9, 30), 24.0, 72.99)
    assert parse_pledge({"data": []}, "ABC", at) is None
