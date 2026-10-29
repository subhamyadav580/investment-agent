# Local data files (`local_files` provider)

Put company data you have collected yourself here: figures transcribed from annual reports, results you
downloaded from NSE/BSE, or exports from a service whose terms allow it. Set:

```
FUNDAMENTALS_PROVIDER=local_files
MARKET_DATA_PROVIDER=local_files
ANNOUNCEMENTS_PROVIDER=local_files
LOCAL_DATA_DIR=./data/local
```

Everything in this directory except this README is git-ignored.

## `fundamentals/<SYMBOL>.json`

```json
{
  "sector": "Industrials",
  "industry": "Industrial Machinery",
  "unit": "INR_crore",
  "consolidation": "consolidated",
  "shares_outstanding_cr": 12.0,
  "source": {
    "source_type": "annual_report",
    "title": "Annual Report FY2026",
    "url": "https://.../annual-report-2026.pdf",
    "published_at": "2026-05-20T18:00:00+05:30"
  },
  "annual": {
    "FY2026": {
      "revenue": 1609.1, "operating_profit": 337.9, "depreciation": 48.3, "interest": 6.0,
      "pbt": 299.7, "net_profit": 224.8, "exceptional_items": 0.0,
      "total_equity": 1580.2, "total_debt": 60.0, "cash_and_equivalents": 40.0,
      "total_assets": 2123.0, "receivables": 242.5, "cfo": 213.6
    }
  },
  "shareholding": [
    {"period_end": "2026-09-30", "promoter_holding_pct": 58.0, "promoter_pledged_pct": 0.0}
  ],
  "alternate_values": [
    {"period": "FY2025", "metric": "revenue", "value": 1399.0, "source_type": "secondary",
     "source_title": "Cross-check source"}
  ]
}
```

- `unit` may be `INR_crore`, `INR_lakh`, `INR_million`, `INR_billion` or `INR`; everything is converted to
  INR crore. Unknown units are rejected rather than guessed.
- Period labels may be `FY2026`, `FY26`, `Mar 2026` or `2026-03`. Indian fiscal years end on 31 March.
- Required for non-financial companies (latest year): `revenue, operating_profit, pbt, net_profit, interest,
  total_equity, total_debt, cfo`. For banks/NBFCs: `revenue, net_profit, total_equity, total_assets`
  (add `gross_npa_pct`, `net_npa_pct`, `capital_adequacy_ratio` when reported).
- At least 3 annual periods are needed for screening; 5 are preferred.
- `alternate_values` lets you record a second source for a figure; disagreements above 2% are flagged.

## `prices/<SYMBOL>.csv`

```
date,close,volume
2026-10-22,512.40,184000
2026-10-23,515.10,201500
```

## `announcements/<SYMBOL>.json`

```json
[
  {"category": "auditor_resignation", "title": "Resignation of statutory auditor",
   "published_at": "2026-09-12T19:30:00+05:30", "url": "https://..."},
  {"category": "board_meeting", "title": "Board meeting to consider Q2 results",
   "published_at": "2026-10-20T10:00:00+05:30", "event_date": "2026-10-29"}
]
```

Categories used by the rules: `auditor_resignation`, `auditor_qualification`, `sebi_order`, `pledge_change`,
`board_meeting`, `results`. Anything else is kept as `other` context.
