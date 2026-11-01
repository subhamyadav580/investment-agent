"""Environment-driven configuration. Secrets come from env vars / .env only."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    log_level: str = "INFO"
    log_json: bool = True

    # API auth: every non-health endpoint requires X-API-Key to match this value.
    api_key: str = ""

    database_url: str = "postgresql+psycopg://agent:agent@localhost:5432/investment_agent"

    # --- Data providers (see app/services/data/providers/registry.py) ---
    universe_provider: str = "fixture"  # fixture | nse_csv | nse_bse
    fundamentals_provider: str = "fixture"  # fixture | local_files | screener
    market_data_provider: str = "fixture"  # fixture | local_files | exchange_bhavcopy
    announcements_provider: str = "fixture"  # fixture | local_files | nse
    fixture_path: Path = PROJECT_ROOT / "data" / "fixtures" / "sample_market.json"
    local_data_dir: Path = PROJECT_ROOT / "data" / "local"
    nse_equity_list_url: str = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
    nse_equity_list_path: Path | None = None  # use a pre-downloaded CSV instead of the URL
    provider_timeout_seconds: float = 20.0

    # --- Polite fetching of public sources (app/infra/http_client.py) ---
    # Sent on every request so site operators can see who is calling. Add a contact if you like.
    http_user_agent: str = "investment-agent/0.1 (personal research tool; low-volume)"
    http_cache_dir: Path = PROJECT_ROOT / "data" / "cache" / "http"
    http_min_interval_seconds: float = 2.0  # between requests to the same host
    screener_min_interval_seconds: float = 3.0
    screener_cache_hours: float = 72.0  # financials change quarterly; avoid re-downloading pages
    include_bse_only: bool = False  # NSE first; set true to add BSE-only companies (merged by ISIN)
    price_sync_exchanges: list[str] = Field(default_factory=lambda: ["NSE"])  # NSE | BSE
    price_backfill_days: int = 400  # ~1y of sessions for liquidity, 1y return; use ~1100 for historical P/E

    # --- Screening ---
    screening_rules_path: Path = PROJECT_ROOT / "config" / "screening_rules.v1.toml"

    # --- LLM ---
    llm_enabled: bool = True
    llm_provider: str = "openai"  # openai | anthropic  (see app/services/graph/llm_factory.py)
    llm_max_tokens: int = 16000
    # OpenAI (SDK reads OPENAI_API_KEY)
    openai_model: str = "gpt-5.5"
    openai_reasoning_effort: str = "medium"  # none | minimal | low | medium | high | xhigh; "" to omit
    # Anthropic (SDK reads ANTHROPIC_API_KEY)
    llm_model: str = "claude-opus-5-5"
    llm_effort: str = "medium"  # low | medium | high | xhigh | max
    llm_refusal_fallback: bool = True
    prompt_version: str = "v2"

    # --- Research queue ---
    research_batch_size: int = 5
    research_max_attempts: int = 3

    # --- Alerts / notifications ---
    notification_channels: list[str] = Field(default_factory=lambda: ["log"])  # log | telegram | email
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    alert_email_to: str = ""
    alert_quiet_period_hours: int = 72
    alert_max_delivery_attempts: int = 5
    report_base_url: str = "http://localhost:8000"

    # --- Scheduler (cron expressions are evaluated in this timezone) ---
    scheduler_timezone: str = "Asia/Kolkata"
    weekly_screening_cron: str = "0 7 * * sun"
    daily_monitoring_cron: str = "30 19 * * mon-fri"
    research_queue_cron: str = "*/30 * * * *"
    alert_retry_cron: str = "*/15 * * * *"
    price_sync_cron: str = "30 19 * * mon-fri"  # after exchanges publish the day's price files
    event_discovery_cron: str = "0 21 * * mon-fri"


@lru_cache
def get_settings() -> Settings:
    return Settings()
