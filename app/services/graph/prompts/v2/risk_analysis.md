Task: assess management and governance, identify the risks, and say what to monitor.

- `management_assessment`: promoter holding level and trend, pledging, governance events in the context, and capital allocation (use `return_on_incremental_capital`, cash conversion, and leverage trends). Related-party transactions are not in the data unless a document shows them; say so rather than guessing.
- `risks`: financial, governance, regulatory, business, competition, valuation, and data-quality risks that the context supports, the most important first. Include every governance flag and every failed screening rule that is material. Rate severity relative to a long-term holder. Each risk cites its evidence ids and metric keys.
- `downside_scenarios`: two to four concrete ways the investment could perform poorly, grounded in the metrics.
- `catalysts`: upcoming events visible in the context (such as scheduled results) that could change the picture. Leave empty if none are visible.
- `monitor_next`: specific, checkable items for the next results or filings (for example, "receivable days in FY2027 versus 200 days in FY2026").
- `invalidation_conditions`: measurable conditions that would mean the reasons to consider this company no longer hold (for example, "ROCE below 15% for two consecutive years").
