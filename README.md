# Investment Agent

An AI research agent that investigates Indian listed companies and helps you decide whether a company is worth
considering for long-term investment. It works in two ways:

Every company is assessed for **two investment horizons**: long term (5-10 years) and medium term (1-3 years). An
excellent business can be a fine 7-year holding and still have little 2-year upside at today's price, so each
horizon gets its own score, scenarios and classification.

- **Mode A: research a company you name.** `scripts/run_research.py "Research Asian Paints for a 5-year
  investment"` (or `POST /research`) reads the horizon from the request, verifies
  the company, analyses its business, financials, management, valuation, risks and scenarios, checks the findings
  against the evidence, and writes a report ending in one of five classifications.
- **Mode B: discover companies on its own.** `python -m app.discovery.run_discovery` loads the NSE universe,
  collects data, filters and ranks companies with transparent rules, researches the best in depth, prints a
  shortlist, and adds strong results to a watchlist that is monitored for changes.

Numbers come from code; an LLM (OpenAI by default, or Claude) only interprets them, and never decides the
classification. **You make the final decision.** It places no trades, and nothing it produces is investment advice.

## Quick start (no data subscriptions needed)

The default providers serve a bundled **synthetic** market of 14 fictional companies (`SMPL*` symbols), each
built to exercise a different path: strong compounder, leveraged cyclical, bank, cash-flow divergence,
auditor resignation, stale data, short history, illiquid, conflicting sources, SME, ETF.

```bash
uv sync
cp .env.example .env            # set API_KEY; optionally OPENAI_API_KEY

# Database: Docker, or any Postgres you point DATABASE_URL at
docker compose up -d db
uv run alembic upgrade head

# Milestone 1: deterministic screening with inclusion/exclusion reasons
uv run python -m app.discovery.run_screening --as-of 2026-10-23

# Mode A: deep research on one company (works without an API key: you get a deterministic-only "partial" report)
uv run python scripts/run_research.py SMPLALPHA --as-of 2026-10-23

uv run python scripts/run_research.py "SMPLALPHA for the next 2 years" --as-of 2026-10-23   # medium-term headline
uv run python scripts/run_research.py SMPLALPHA --horizon both --as-of 2026-10-23

# Mode B: screen, research the top 5, print the ranked shortlist (--no-llm: deterministic only, no API cost)
uv run python -m app.discovery.run_discovery --as-of 2026-10-23 --research-top 5 --no-llm --horizon both

# API + scheduled worker
uv run uvicorn app.main:app --reload
uv run python -m app.jobs.worker
```

Then open http://localhost:8000/ui/ (or just http://localhost:8000/) and paste your `API_KEY` on the Settings
page. The web UI covers research (with horizon), full reports (sections 1-7, final assessment, evidence), the
ranked shortlist per horizon, discovery (screening runs and the research queue), watchlists and alerts. It is
plain HTML/JS in `app/web/static/` served by FastAPI: no Node toolchain or build step. The key is kept in the
browser's local storage and sent as `X-API-Key`; the static files themselves contain no data.

Or run everything in containers: `docker compose up --build` (db, migrations, api, worker).

The synthetic prices end on 2026-10-23. Running with a later `--as-of` correctly flags them as stale.

## How a company is judged

Five categories, each scored 0-100 from deterministic metrics and combined with these weights:

| Category | Weight | Lenders | What it evaluates (from the numbers) |
|---|---|---|---|
| Business quality | 25% | 20% | Sustained ROCE, margin level and stability (lenders: ROE, ROA) |
| Financial performance | 25% | 20% | Revenue and profit growth, consistency, ROCE, cash-flow quality |
| Financial strength | 15% | 25% | Debt/equity, interest cover, net debt/EBITDA (lenders: capital adequacy, NPAs) |
| Valuation | 20% | 20% | P/E (lenders: P/B) against sector peers and absolute ceilings |
| Management and governance | 15% | 15% | Governance events, promoter pledging and holding trend, return on incremental capital |

The weights are starting points in [config/screening_rules.v1.toml](config/screening_rules.v1.toml)
(`[scoring.weights]` and `[scoring.weights_financial]`). The LLM adds the qualitative side (how the company makes
money, competitive advantages, industry outlook, threats), but it doesn't change scores.

**The medium-term (1-3 year) score** uses its own weights: business and financial quality 20% (the long-term
quality and performance scores), earnings outlook 20% (latest-quarter growth and acceleration, or the latest year
against the 5-year trend when there's no quarterly data), financial strength 10%, valuation 20%, catalysts 15%,
and management and risks 15%. Catalysts are only the ones evidenced in filings in the last 180 days (orders,
capacity additions, acquisitions, rating upgrades) plus an improving industry; management targets never count.
Configure it in `[horizons.medium_term]`.

**Horizon in the request.** "for a 5-year investment" means long term and "for the next 2 years" means medium
term; "long-term", "medium-term" and "both" also work, as do `--horizon` and `--years` (or `horizon` and `years`
in the API). Both horizons are always computed; the requested one is the headline `conclusion`. A period that
fits neither range (for example 4 years) is rejected rather than guessed.

**Red flags are kept separate.** Serious governance events (auditor resignation or qualification, SEBI orders,
insolvency, pledges above 50%), a failed critical interest-cover floor, losses, debt/equity above 2x, or operating
cash flow below 30% of profit are listed on their own and make the company "high risk", whatever the score.

**A great business can be a poor investment at the wrong price.** Valuation is rated separately using
conservative, base and optimistic scenarios. Each states its growth rate (historical profit CAGR, capped at
revenue CAGR + 5 pp and at 25% a year), its exit multiple (the company's own 25th/median/75th percentile P/E, or
the sector median x 0.8/1.0/1.2) and the horizon's length. Medium-term scenarios start from recent momentum
(latest-quarter, else latest-year profit growth, capped the same way). The report also gives a fair-value range:
current earnings at those reference multiples, with no growth. The ratings are Attractive (base case at least 12% a year,
and the conservative case doesn't lose money), Expensive (base case below 5%, or P/E above 80), Fair, or Uncertain.

Every report ends with one classification:

| Classification | When |
|---|---|
| (per horizon) | |
| Strong candidate | Strong business, financial health not weak, positive management, attractive or fair valuation, score at least 65, no red flags, every material claim verified, business analysis completed |
| Good business, expensive valuation | Strong business and finances, but valuation rated Expensive |
| Potential opportunity | Some attractive characteristics; the rationale lists what is missing (medium term: also when the case depends on catalysts or earnings are not improving) |
| High risk | Any red flag, concerning management/governance, or weak financial health |
| Insufficient evidence | Data failed validation, data quality is low, or too many inputs are missing |

## Report format

1. **Company overview:** what it does, how it makes money, competitive advantages and position
2. **Financial performance:** 5-12 years where available (5-year and long-run CAGRs), margins, returns, debt,
   cash flow, and comparison with sector peers
3. **Valuation:** current multiples, own-history and peer comparison, the three scenarios with their assumptions
4. **Management and governance:** promoter holding, pledging and trend, governance events, capital allocation.
   Related-party transactions are not in the structured data, and the report says so.
5. **Growth prospects:** industry earnings trend across listed peers, expansion filings (orders, acquisitions,
   capacity), growth drivers and competitive threats
6. **Risks:** red flags, ranked risks, downside scenarios, and the conditions that would invalidate the thesis
7. **Final assessment** (per horizon, each with its main concern): business quality (Strong/Average/Weak), financial health (Strong/Average/Weak),
   management and governance (Positive/Mixed/Concerning), valuation (Attractive/Fair/Expensive/Uncertain), data
   quality (High/Medium/Low), and the overall classification. Each rating lists its reasons, the metric keys it
   rests on, and the evidence ids (E1, E2, ...) of the source documents.

## Architecture

```
routes/            path -> handler registration only
api/handlers/      HTTP concerns: DTOs, status codes, error mapping
services/          all domain logic, framework-agnostic
  data/            provider interfaces + registry (Strategy/Factory), normalization, validation
  discovery/       universe loader, enrichment, screening rules, scoring, candidate queue
  research/        deterministic metrics, valuation, peers, evidence verification, research service
  graph/           LangGraph workflow: state, nodes, prompts (versioned Markdown), LLM wrappers + factory
  alerts/          alert rules, dedup/quiet periods, notifier fan-out, monitoring
  watchlist/       watchlists and theses
repos/             thin persistence wrappers
db/, models/       engine/session, ORM entities, Alembic migrations
jobs/              APScheduler worker
config/            versioned screening + alert thresholds (TOML)
```

### Research graph

```
resolve_company -> fetch_company_data (retries on provider errors) -> validate_data -> calculate_metrics
  invalid data -> generate_report   (no LLM call on unusable data; classification = insufficient_evidence)
  valid data   -> analyze_business -> evaluate_valuation -> analyze_risks -> verify_evidence -> generate_report
generate_report -> persist_report -> evaluate_alerts
```

### Guarantees the code enforces

- **Numbers come from code.** Every metric is computed deterministically with its inputs and period recorded.
  Missing inputs produce `None` plus a note; nothing is estimated.
- **Missing data never passes.** A rule with no input returns `missing`, and a missing score component
  scores 0 and is listed in `missing_components`.
- **Serious governance flags are not averaged away.** Auditor resignation or qualification, SEBI orders, and
  promoter pledges above 50% send a company to `governance_review`, are listed as red flags, and make the
  classification `high_risk`.
- **Sector-aware rules.** Banks and NBFCs are judged on ROE, asset quality, and P/B; debt and cash-flow rules
  are marked `not_applicable` for them.
- **Claims are verified.** Every LLM claim must cite evidence ids and/or metric keys. Unknown ids, null
  metrics, unsupported material claims, and percentages or multiples that match nothing the model was shown
  are flagged. Any unverified material claim makes the report `partial` and blocks a `strong_candidate`
  classification.
- **Retrieved text is untrusted.** Announcements reach the model inside `<untrusted_document>` tags with an
  instruction to ignore embedded instructions. The model has no tools and never sees credentials.
- **Fails safe.** No API key, rate limits, refusals, truncation, or invalid output all degrade to a
  deterministic-only `partial` report rather than an error.
- **Point in time.** Data dated after `as_of` is dropped. Historical P/E uses prices from about 60 days after
  each fiscal year end, when results are typically public.
- **Reproducible.** Every screening run stores its universe version and rules version, and every report stores
  the rules, prompt, and model versions plus the source ids and hashes it used.

## Using real data (live NSE/BSE sources)

Set the four providers in `.env` (see `.env.example`), then:

```bash
uv run python -m app.discovery.sync_prices --days 400          # one-time backfill of NSE daily price files
uv run python -m app.discovery.run_screening --symbols ESDS,TCS # screen specific companies
uv run python -m app.discovery.run_screening --limit 100        # 100 most liquid companies
uv run python -m app.discovery.run_screening                    # whole universe (slow: ~3 s per company)
uv run python -m app.discovery.run_event_discovery --days 3     # companies with recent results/orders/deals
uv run python scripts/run_research.py ESDS
uv run python -m app.discovery.run_discovery --limit 200 --research-top 5   # Mode B on live data
```

The universe is NSE-only by default. Set `INCLUDE_BSE_ONLY=true` to add companies listed only on BSE
(dual-listed companies are merged into one record by ISIN). Live research costs 3 LLM calls per company, so
`--research-top 5` means 15 calls.

Where each kind of candidate comes from:

| Source | Provider | What it gives |
|---|---|---|
| A. Listed universe | `nse_bse` | NSE `EQUITY_L.csv` plus BSE-only companies from BSE's daily price file, merged by ISIN. SME and non-equity instruments are excluded. |
| B. Financials and screening | `screener`, `exchange_bhavcopy` | Up to 12 years of P&L, balance sheet, cash flow and ratios, about 12 quarters, shareholding, sector; prices and volume from exchange price files. |
| C. Filings and events | `nse` | Announcements classified into results, order wins, acquisitions, capacity additions, auditor resignations or qualifications, SEBI orders, insolvency, rating changes and pledges; board-meeting dates; promoter pledge %. |
| D. Sector discovery | computed | Industries whose latest-quarter profit growth is positive, accelerating and broad-based. These get a research-priority boost, and `/discovery/industries` lists them. |

How the fetching behaves:

- **Honest:** every request carries `HTTP_USER_AGENT`. The client never imitates a browser, and a 401 or 403 is treated as "no" and never retried or worked around. BSE's JSON API refuses such requests, so it isn't used.
- **robots.txt:** checked for every host. Screener's chart API is disallowed there, which is why prices come from exchange files instead.
- **Rate-limited and cached:** at least 2 s between requests to the same host (3 s for Screener), and company pages are cached for 72 h.
- **Screening fetches less:** with prices synced, companies below the liquidity floor are rejected before their financials are fetched.
- **Secondary-source warning:** Screener.in aggregates company filings, so reports carry a data note to verify material figures against the filing. The project includes no scraper of exchange HTML pages.
- **Terms of use:** you are responsible for following the NSE, BSE and Screener.in terms for your own usage.

`local_files` (format in [data/local/README.md](data/local/README.md)) and `fixture` (the synthetic `SMPL*`
market) still work offline.

## API

Every endpoint except `GET /health` requires an `X-API-Key` header matching `API_KEY`. If `API_KEY` is not
set, the API refuses requests instead of running open. Interactive docs are at `/docs`; the web UI is at `/ui/`.

| Method | Path | Purpose |
|---|---|---|
| POST | `/screening/runs` | Run screening (`as_of_date`, `enqueue_top_n`, `horizon` to rank by) |
| GET | `/screening/runs`, `/screening/runs/{id}?result_status=candidate` | Ranked results with reasons |
| POST | `/research` | Research a company now (`query`: symbol or name, optionally with a horizon; `horizon`, `years`) |
| POST | `/research/queue/{symbol}`, `/research/queue/process` | Queue a company, or process queued research |
| GET | `/research/reports?symbol=`, `/research/reports/{id}` | Stored reports |
| GET | `/research/shortlist?horizon=long_term` | Ranked shortlist: both horizons' classifications, ratings, main concern, why |
| POST/GET | `/watchlists`, `/watchlists/{id}` | Watchlists |
| PUT/DELETE | `/watchlists/{id}/companies[/{symbol}]` | Thesis, invalidation conditions, valuation range, alert overrides |
| GET | `/alerts?symbol=&delivery_status=` | Alert history |
| POST | `/alerts/monitor`, `/alerts/deliver` | Run monitoring now, retry failed deliveries |
| POST | `/discovery/events?days=` | Event-driven discovery from recent filings |
| GET | `/discovery/industries?improving_only=true` | Industry earnings trends from the latest screening run |
| POST | `/discovery/prices/sync?days=` | Sync recent exchange price files |

An example thesis entry, where conditions are checked on every monitoring run:

```json
{
  "symbol": "SMPLALPHA",
  "thesis": "Capital-efficient machinery maker compounding at mid-teens",
  "invalidation_conditions": [
    {"metric": "roce_latest", "op": "<", "value": 0.15, "description": "ROCE below 15%"},
    {"metric": "cfo_to_pat_3y", "op": "<", "value": 0.7}
  ],
  "valuation_range": {"metric": "pe", "low": 18, "high": 24, "assumptions": "12% EPS growth, no re-rating"},
  "alert_overrides": {"max_debt_to_equity": 0.5}
}
```

## Configuration

- Screening and alert thresholds: [config/screening_rules.v1.toml](config/screening_rules.v1.toml). Bump
  `version` with every change, because it is stamped on runs and reports.
- Prompts: `app/services/graph/prompts/<PROMPT_VERSION>/` (default `v2`). To change prompts, copy the folder to `v3` and set
  `PROMPT_VERSION=v3`, so earlier reports still identify the prompts that produced them.
- LLM: `LLM_PROVIDER=openai` (default) or `anthropic`. A full research run makes 3 structured calls, and token
  usage per report is stored in `research_reports.llm_usage`.
  - OpenAI: `OPENAI_API_KEY`, `OPENAI_MODEL` (default `gpt-5.5`), `OPENAI_REASONING_EFFORT` (default `medium`;
    leave empty for models that don't support reasoning). Uses the Responses API with a strict JSON schema
    and `store=false`.
  - Anthropic: `ANTHROPIC_API_KEY`, `LLM_MODEL` (default `claude-opus-5-5`), `LLM_EFFORT`, and
    `LLM_REFUSAL_FALLBACK` for the API's server-side refusal fallback.
  - Adding another provider means one wrapper in `app/services/graph/` and one branch in `llm_factory.py`.
- Notifications: `NOTIFICATION_CHANNELS=["log","telegram","email"]` plus the matching credentials. Delivery
  failures are retried by the worker up to `ALERT_MAX_DELIVERY_ATTEMPTS`.
- Schedules: the `*_CRON` variables, evaluated in `SCHEDULER_TIMEZONE` (default Asia/Kolkata).

## Development

```bash
uv run pytest            # 157 tests: unit, integration (pipeline + API), graph (fake LLM + mocked SDK transport)
uv run ruff check app tests scripts
uv run python scripts/build_sample_fixtures.py   # regenerate the synthetic market
uv run alembic revision --autogenerate -m "..."  # after changing app/models
```

## Status against the MVP acceptance criteria

- [x] Load and maintain an eligible equity universe (NSE list, SME/ETF exclusion, aliases, inactive marking)
- [x] Discover candidates without supplying tickers (screening, research queue, shortlist, auto-monitoring)
- [x] Five-category weighted assessment, separate red flags, and the five classifications
- [x] Conservative / base / optimistic valuation scenarios with explicit assumptions, and a fair-value range
- [x] Long-term (5-10y) and medium-term (1-3y) horizons with separate scores and classifications
- [x] Explain why companies passed or failed (per-rule results and exclusion reasons)
- [x] Deterministic, tested metrics
- [x] Evidence-backed reports (evidence registry and claim verification)
- [x] Research history, sources, and model, prompt, and rule versions stored
- [x] Scheduled watchlist monitoring
- [x] Relevant, deduplicated alerts (dedup keys, quiet periods, retries, delivery status)
- [x] Safe handling of stale data, missing fields, and provider failures
- [x] No trade execution

Not done yet: backtesting the ranking against point-in-time history (survivorship bias, corporate actions),
analyst consensus forecasts for the medium-term earnings outlook (only reported numbers are used), automatic
re-research when monitoring flags a change (it alerts and marks the thesis for review instead), historical EV/EBITDA (only P/E and P/B history), related-party transactions, reading annual-report
text (business descriptions come from filings and metrics only), verifying Screener figures against the XBRL
results filed with the exchanges, announcements for
BSE-only companies (BSE's API refuses honest automated requests), news-based discovery, the React dashboard
and Telegram bot commands, and backtesting.
