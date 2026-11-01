Task: explain the business, its financial trajectory, and its growth prospects.

- `business_overview`: what the company does. If the context only has a sector/industry label, say that and keep this short rather than filling it with generic sector description.
- `revenue_model`: how the company makes money (segments, products, customers, pricing) as far as the filings in the context show. If they do not show it, say so plainly; that is an open question, not something to guess.
- `competitive_advantages`: advantages the evidence actually supports, each one short (for example, "ROCE of 28% sustained over three years against a sector median of 14%, suggesting pricing power"). An empty list is the right answer when nothing in the context supports one.
- `competitive_position`: what the metrics suggest about market position and competitive strength (returns on capital versus peers, margin level and stability, growth versus peers). Note where the evidence is too thin to tell.
- `financial_trends`: the five- to ten-year story in revenue, profit, margins, returns, leverage, and cash conversion, including any break in trend. Use the long-run CAGR metrics when present.
- `industry_outlook`: the industry's direction as shown by the INDUSTRY TREND block (peer earnings growth and breadth) and any filings. If there is no industry data, say the outlook cannot be judged from the evidence.
- `growth_drivers`: expansion plans and growth drivers visible in filings (capacity additions, order wins, acquisitions) or in the metrics. Empty if none are visible.
- `competitive_threats`: competitive threats the evidence points to (margin pressure, share loss to peers, sector-wide slowdowns). Empty if none are visible.
- `claims`: the material factual statements behind the sections above, each with its evidence ids and metric keys.
- `open_questions`: the questions an investor should answer from the annual report or management commentary before forming a view, especially where the context could not answer one of the sections above.
