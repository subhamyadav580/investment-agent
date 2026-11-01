# Investment Agent: Complete Operating Plan

We'll design the agent around **two investment horizons and two research entry points**. This gives you one system that can research a company you choose or independently discover promising Indian stocks.

The agent will support:

- **Long-term investing:** 5–10 years.
- **Medium-term investing:** 1–3 years.
- **User-directed research:** You provide a company name or stock symbol.
- **Autonomous discovery:** The agent searches eligible listed companies and identifies candidates worth researching.

The key design principle is that both entry points use the same underlying research engine, but the analysis changes depending on the investment horizon.

## 1. The four possible operating modes

| Mode | Who selects the company? | Investment horizon | Main objective |
|---|---|---|---|
| Long-term company research | You | 5–10 years | Determine whether the business is worth owning over the long term and at what valuation |
| Medium-term company research | You | 1–3 years | Evaluate fundamentals, valuation, earnings outlook, and potential catalysts over the next few years |
| Long-term stock discovery | Agent | 5–10 years | Discover high-quality businesses with attractive long-term investment potential |
| Medium-term stock discovery | Agent | 1–3 years | Discover fundamentally sound companies with potential medium-term opportunities |

You can also request **both horizons for the same company or discovery run**.

For example, a company might have excellent long-term prospects but limited medium-term upside because its current valuation is high. The agent should identify that difference rather than giving it the same recommendation for both horizons.

---

# 2. The complete system architecture

The system starts by understanding what you want to research. It then chooses the appropriate workflow.

```text
                    YOU
                     |
                     v
              Research Request
                     |
          +----------+----------+
          |                     |
          v                     v
   Company Provided?       No Company Provided
          |                     |
          v                     v
   Company Research       Stock Discovery
          |                     |
          v                     v
   Resolve Company        Load NSE Universe
          |                     |
          |                     v
          |               Initial Screening
          |                     |
          |                     v
          |               Rank Candidates
          |                     |
          |                     v
          |               Select Candidates
          |                     |
          +----------+----------+
                     |
                     v
             Collect Financial Data
                     |
                     v
               Validate Data
                     |
                     v
           Shared Research Engine
                     |
           +---------+---------+
           |                   |
           v                   v
    Long-Term Analysis   Medium-Term Analysis
         5–10 years          1–3 years
           |                   |
           v                   v
    Long-Term Valuation  Medium-Term Valuation
           |                   |
           +---------+---------+
                     |
                     v
           Risk & Evidence Checks
                     |
                     v
             Final Assessment
                     |
                     v
          Report / Ranked Shortlist
                     |
                     v
             Optional Monitoring
```

The system does not need four separate agents. We can implement a shared research workflow in LangGraph with different entry points, screening strategies, and valuation logic.

# 3. Case A: You provide a company

Suppose you enter:

> Research Asian Paints for a 5-year investment.

The agent follows these steps.

### Step 1: Identify the company

The agent resolves the company name to the correct listed entity and verifies its stock symbol and exchange.

If the name is ambiguous, it asks you to clarify rather than researching the wrong company.

### Step 2: Collect company information

It gathers relevant information, including:

- Historical annual and quarterly financial statements.
- Current and historical share prices.
- Revenue, profits, margins, and cash flows.
- Debt and balance-sheet information.
- Promoter holdings and pledging.
- Annual reports and company disclosures.
- Competitors and industry information.
- Relevant governance and regulatory developments.

It records source references and reporting dates for the information it uses.

### Step 3: Analyze the company

The agent investigates five questions:

1. Is the business fundamentally good?
2. Is its financial performance sustainable?
3. Does management allocate capital responsibly?
4. Is the company financially strong?
5. Is its current share price reasonable?

It then investigates the risks that could undermine its conclusions.

### Step 4: Apply the requested investment strategy

If you requested a 5-year investment, the long-term strategy evaluates the business's prospects over that period.

If you requested a 2-year investment, the medium-term strategy places more emphasis on earnings expectations, valuation changes, industry conditions, and potential catalysts.

### Step 5: Estimate valuation

Where sufficient data exists, the agent estimates a reasonable valuation under conservative, base, and optimistic assumptions.

It calculates potential returns over your chosen horizon and explains the assumptions behind those estimates.

### Step 6: Generate the report

You receive a company-specific report containing:

- Business quality.
- Financial performance.
- Management and governance.
- Valuation.
- Potential returns.
- Risks and warning signs.
- Supporting evidence.
- Final assessment.
- What to monitor going forward.

**The result:** You can investigate any eligible listed company without manually collecting its financial data and researching every aspect yourself.

---

# 4. Case B: The agent independently discovers companies

This is the more autonomous part of the system.

Instead of researching one company, the agent searches the eligible Indian equity universe for promising candidates.

Suppose you enter:

> Find promising Indian stocks for the next 5 years.

The agent follows a different initial workflow.

### Step 1: Build the company universe

The system loads eligible listed equities from official exchange sources.

It normalizes stock symbols and company identifiers, handles duplicate listings, and excludes instruments outside the agreed scope.

We should begin with NSE-listed equities and expand coverage when the data and identity mapping are reliable.

### Step 2: Collect screening data

The system retrieves available financial information for the eligible universe.

To control cost and processing time, it initially collects the metrics required for screening rather than conducting expensive, in-depth AI research on every company.

### Step 3: Apply screening rules

The screening engine evaluates factors such as:

- Revenue and profit growth.
- Profitability and returns on capital.
- Debt and financial stability.
- Cash-flow quality.
- Valuation.
- Governance concerns.
- Data completeness and liquidity.

The rules must account for sector differences. A bank and a manufacturing company cannot be evaluated using exactly the same financial ratios.

The system records why each company passed, failed, or requires further investigation.

### Step 4: Rank candidates

The system assigns explainable scores and flags important risks.

It then selects a manageable group of candidates for deeper research.

The number selected should depend on data coverage, research cost, and available processing capacity rather than a fixed assumption that the highest-scoring companies are automatically the best investments.

### Step 5: Conduct deeper research

The selected companies enter the same research workflow used when you provide a company yourself.

The agent investigates their businesses, financial statements, management, valuations, competitors, and risks.

### Step 6: Produce a ranked shortlist

The output might look like this:

| Rank | Company | Research conclusion | Main concern |
|---|---|---|---|
| 1 | Company A | Strong fundamentals; valuation merits further examination | Growth may slow |
| 2 | Company B | Attractive business with reasonable valuation | Industry cyclicality |
| 3 | Company C | Potential opportunity if earnings improve | Recovery remains uncertain |
| 4 | Company D | Strong business but expensive valuation | Limited valuation cushion |
| 5 | Company E | Worth further investigation | Incomplete financial evidence |

These are illustrative examples, not actual stock recommendations.

The agent explains why each company was selected and why it ranks above or below other candidates.

**The result:** You don't need to know which companies to research. The agent identifies candidates and explains its reasoning.

---

# 5. How the long-term and medium-term strategies differ

The discovery process can be similar for both horizons, but the definition of a promising investment changes.

## Strategy 1: Long-term investing — 5–10 years

**Objective:** Identify durable businesses with sustainable growth, sound finances, responsible management, and attractive valuations.

The agent focuses on:

| Area | What it investigates |
|---|---|
| Business quality | Competitive advantage, customer relationships, market position |
| Growth | Long-term demand, expansion opportunities, sustainable earnings growth |
| Financial performance | Multi-year revenue, profits, margins, and returns on capital |
| Financial strength | Debt, liquidity, and cash generation |
| Management | Capital allocation, governance, and shareholder interests |
| Valuation | Whether today's price offers an adequate margin of safety |
| Long-term risks | Disruption, competition, industry changes, and deteriorating fundamentals |

### Example

Imagine two hypothetical companies.

- **Company A:** Excellent business, strong growth prospects, but extremely expensive.
- **Company B:** Good business, consistent financial performance, reasonable valuation, and manageable debt.

The agent might rank Company B higher for long-term investment consideration because the purchase price matters even when the underlying business is excellent.

It should also explain the circumstances under which Company A's valuation might become more attractive.

### Long-term output

For each company, the report includes:

- Business quality assessment.
- Long-term growth assumptions.
- Financial health.
- Estimated fair-value range.
- Conservative, base, and optimistic scenarios.
- Potential annualized returns over the chosen horizon.
- Key risks and thesis-invalidation conditions.

The agent should distinguish business quality from investment attractiveness: a good company is not necessarily a good investment at every price.

## Strategy 2: Medium-term investing — 1–3 years

**Objective:** Identify companies whose fundamentals, valuation, and identifiable developments could create attractive opportunities over the next few years.

The agent focuses on:

| Area | What it investigates |
|---|---|
| Financial quality | Whether the business is fundamentally sound |
| Earnings outlook | Expected changes in revenue, profits, and margins |
| Valuation | Whether current expectations are already reflected in the share price |
| Catalysts | Capacity expansion, product launches, industry recovery, or other identifiable developments |
| Market expectations | Whether available evidence suggests expectations are overly optimistic or pessimistic |
| Risks | Earnings disappointments, failed catalysts, and valuation contraction |

### Example

Imagine a hypothetical company that is expanding production capacity.

The agent investigates:

1. Is the expansion actually happening?
2. What evidence supports the expected increase in capacity?
3. How much additional revenue and profit could it generate?
4. When might the financial impact become visible?
5. Is the expected growth already reflected in the share price?
6. What happens if the expansion is delayed or demand is weaker than expected?

The company might be a potential medium-term opportunity even if it isn't the strongest candidate for a 10-year investment.

However, the agent should not invent catalysts or treat management's growth targets as guaranteed outcomes.

### Medium-term output

The report includes:

- Current business and financial quality.
- Earnings outlook and its supporting evidence.
- Identifiable catalysts and expected timelines.
- Valuation scenarios at the end of the investment horizon.
- Potential annualized returns.
- Downside scenarios.
- Events or financial results that would invalidate the thesis.

The system should use reliable forecasts where available and clearly distinguish them from its own estimates.

---

# 6. What happens when you ask for both horizons?

You should be able to request:

> Find promising Indian stocks and evaluate each for both 2-year and 7-year investments.

The agent first discovers candidates using a shared screening process. It then evaluates each selected company separately under both strategies.

Its output might look like this:

| Company | Medium-term assessment | Long-term assessment |
|---|---|---|
| Company A | Attractive if earnings recovery materializes | Uncertain long-term competitive position |
| Company B | Limited near-term upside | Strong business with long-term potential |
| Company C | Valuation appears demanding | Worth watching if its price becomes more reasonable |
| Company D | Potential opportunity, but catalyst-dependent | Requires more evidence on business durability |

These examples are hypothetical.

This comparison is useful because **a company's investment attractiveness depends on both its price and the time horizon over which you expect the business to develop**.

The agent should not force every company into one category. Some companies may be attractive for both horizons, while others may suit neither.

---

# 7. The scoring and decision system

The agent should maintain two separate scores.

### Long-term score

| Component | Initial weight |
|---|---:|
| Business quality | 25% |
| Financial performance | 25% |
| Financial strength | 15% |
| Valuation | 20% |
| Management and governance | 15% |

### Medium-term score

| Component | Initial weight |
|---|---:|
| Business and financial quality | 20% |
| Earnings growth outlook | 20% |
| Financial strength | 10% |
| Valuation | 20% |
| Catalysts | 15% |
| Management, governance, and risks | 15% |

These are starting weights that we should validate, not established formulas for predicting investment returns.

The system must also apply separate warning flags for serious governance problems, unreliable data, and significant financial risks. A high numerical score should never conceal a critical concern.

### Final classifications

Each strategy should produce one of these research outcomes:

- **Strong candidate:** Merits serious further investment consideration.
- **Promising but expensive:** Business fundamentals look attractive, but valuation is a concern.
- **Potential opportunity:** The investment case depends on specific developments or assumptions.
- **High risk:** Material risks undermine the investment case.
- **Insufficient evidence:** Available data is not sufficient to support a reliable conclusion.

These are research classifications, not automatic buy or sell instructions.

---

# 8. How the agent will operate technically

I recommend using LangGraph to coordinate the research steps.

We don't need a collection of completely independent agents that communicate without structure. A controlled workflow will be easier to test and debug.

| Component | Responsibility |
|---|---|
| Request router | Determines whether you specified a company, requested discovery, or want both horizons |
| Company resolver | Identifies the correct listed company |
| Universe loader | Retrieves eligible listed equities |
| Data collectors | Retrieve financials, prices, disclosures, and company information |
| Data validator | Checks dates, units, missing data, and conflicting figures |
| Screening engine | Calculates metrics and applies deterministic rules |
| Research workflow | Investigates business quality, management, and industry |
| Valuation engine | Calculates fair-value scenarios and potential returns |
| Risk evaluator | Identifies material risks and thesis-invalidation conditions |
| Evidence verifier | Checks important conclusions against their sources |
| Report generator | Produces the final report or ranked shortlist |
| Monitoring service | Reassesses tracked companies when material information changes |

**Technology stack:** Python, LangGraph, FastAPI, Pandas, NumPy, PostgreSQL, and an authorized financial-data provider.

An LLM will interpret evidence and explain conclusions. Python will calculate financial metrics, valuations, and scores. This division is essential for auditability.

---

# 9. What happens after the initial report?

The agent should preserve its original research so it can evaluate whether the investment thesis has changed.

For example, if you add a company to your watchlist, the system can:

1. Save its original research report.
2. Store the assumptions behind its valuation.
3. Record the reasons it was considered promising.
4. Monitor quarterly financial results and material disclosures.
5. Compare new results with the original assumptions.
6. Flag deterioration, improving fundamentals, or significant changes in valuation.
7. Generate an updated research report when necessary.

You can receive alerts such as:

> **Thesis review required:** Revenue growth has slowed, and operating cash flow has weakened relative to reported profit. Review the latest filings to determine whether the change is temporary or indicates a deterioration in earnings quality.

The agent will explain the evidence and potential implications. It will not automatically trade.

---

# 10. The implementation roadmap

I would build the project in five milestones.

| Milestone | What we build | Success criteria |
|---|---|---|
| 1. Company research | Research a company you specify | Produces a reliable report with verified financial data and sources |
| 2. Valuation | Add fair-value and return scenarios | Calculates reproducible scenarios with explicit assumptions |
| 3. Investment strategies | Add separate 1–3-year and 5–10-year analysis | The same company can receive different assessments for each horizon |
| 4. Automatic discovery | Screen listed companies and rank candidates | Produces an explainable shortlist and deep-researches selected companies |
| 5. Monitoring | Save reports and track material changes | Detects meaningful developments and provides evidence-backed updates |

Before treating the ranking system as useful, we should also evaluate it against historical data using point-in-time information, accounting for survivorship bias, corporate actions, transaction costs where relevant, and the possibility that historical performance won't persist.

We should validate the data provider early because data coverage, cost, licensing, and historical availability will affect the entire implementation.

## Recommended first version

For the first working version, I would keep the scope to these capabilities:

1. Research any eligible NSE-listed company you provide.
2. Evaluate it under either or both investment horizons.
3. Produce an evidence-backed report with valuation scenarios.
4. Discover promising companies automatically.
5. Return a ranked shortlist with separate long-term and medium-term assessments.

We can defer dashboards, Telegram alerts, and continuous monitoring until the research engine is reliable.

**The end goal is one investment research system that works in both directions:** you can ask it to investigate a company you already have in mind, or you can ask it to find companies you may never have considered. In both cases, it follows the same evidence-driven process and adapts its analysis to your investment horizon.