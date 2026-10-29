# Investment Agent

A personal research and alerting assistant for Indian equities (NSE/BSE). It discovers companies from the
listed universe, screens them with deterministic and versioned rules, researches the most promising ones with
a controlled LangGraph workflow (using an LLM - OpenAI by default, or Claude - to interpret, never to calculate), monitors a watchlist, and
sends deduplicated alerts.

**It is a research tool only.** It does not place trades and has no broker integration. Scores rank what to
research next; they do not predict returns. Nothing it produces is investment advice.

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

# Deep research on one company (works without an API key: you get a deterministic-only "partial" report)
uv run python scripts/run_research.py SMPLALPHA --as-of 2026-10-23

# API + scheduled worker
uv run uvicorn app.main:app --reload
uv run python -m app.jobs.worker
```

Or run everything in containers: `docker compose up --build` (db, migrations, api, worker).

The synthetic prices end on 2026-10-23. Running with a later `--as-of` correctly flags them as stale.

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
  invalid data -> generate_report   (no LLM call on unusable data; conclusion = insufficient_evidence)
  valid data   -> analyze_business -> evaluate_valuation -> analyze_risks -> verify_evidence -> generate_report
generate_report -> persist_report -> evaluate_alerts
```

### Guarantees the code enforces

- **Numbers come from code.** Every metric is computed deterministically with its inputs and period recorded.
  Missing inputs produce `None` plus a note; nothing is estimated.
- **Missing data never passes.** A rule with no input returns `missing`, and a missing score component
  scores 0 and is listed in `missing_components`.
- **Serious governance flags are not averaged away.** Auditor resignation or qualification, SEBI orders, and
  promoter pledges above 50% send a company to `governance_review` and cap the conclusion at `watch`.
- **Sector-aware rules.** Banks and NBFCs are judged on ROE, asset quality, and P/B; debt and cash-flow rules
  are marked `not_applicable` for them.
- **Claims are verified.** Every LLM claim must cite evidence ids and/or metric keys. Unknown ids, null
  metrics, unsupported material claims, and percentages or multiples that match nothing the model was shown
  are flagged. Any unverified material claim makes the report `partial` and blocks a `worth_deeper_research`
  conclusion.
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
```

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
set, the API refuses requests instead of running open. Interactive docs are at `/docs`.

| Method | Path | Purpose |
|---|---|---|
| POST | `/screening/runs` | Run screening (`as_of_date`, `enqueue_top_n`) |
| GET | `/screening/runs`, `/screening/runs/{id}?result_status=candidate` | Ranked results with reasons |
| POST | `/research` | Research a company now (`query`: symbol or name) |
| POST | `/research/queue/{symbol}`, `/research/queue/process` | Queue a company, or process queued research |
| GET | `/research/reports?symbol=`, `/research/reports/{id}` | Stored reports |
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
- Prompts: `app/services/graph/prompts/<PROMPT_VERSION>/`. To change prompts, copy the folder to `v2` and set
  `PROMPT_VERSION=v2`, so earlier reports still identify the prompts that produced them.
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
uv run pytest            # 134 tests: unit, integration (pipeline + API), graph (fake LLM + mocked SDK transport)
uv run ruff check app tests scripts
uv run python scripts/build_sample_fixtures.py   # regenerate the synthetic market
uv run alembic revision --autogenerate -m "..."  # after changing app/models
```

## Status against the MVP acceptance criteria

- [x] Load and maintain an eligible equity universe (NSE list, SME/ETF exclusion, aliases, inactive marking)
- [x] Discover candidates without supplying tickers (screening run, then research queue)
- [x] Explain why companies passed or failed (per-rule results and exclusion reasons)
- [x] Deterministic, tested metrics
- [x] Evidence-backed reports (evidence registry and claim verification)
- [x] Research history, sources, and model, prompt, and rule versions stored
- [x] Scheduled watchlist monitoring
- [x] Relevant, deduplicated alerts (dedup keys, quiet periods, retries, delivery status)
- [x] Safe handling of stale data, missing fields, and provider failures
- [x] No trade execution

Not done yet: verifying Screener figures against the XBRL results filed with the exchanges, announcements for
BSE-only companies (BSE's API refuses honest automated requests), news-based discovery, the React dashboard
and Telegram bot commands, and backtesting.
