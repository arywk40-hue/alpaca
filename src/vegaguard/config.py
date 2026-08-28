from functools import lru_cache

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    alpaca_api_key: SecretStr | None = None
    alpaca_secret_key: SecretStr | None = None
    alpaca_account_id: str | None = None
    alpaca_paper_trade: bool = True
    alpaca_toolsets: str = "account,trading,assets,stock-data,options-data"
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-5-mini"
    allow_order_execution: bool = False
    dry_run: bool = True
    # Exploration is a separately-labelled, paper-only experiment. It cannot
    # change the production scorer or its 70-point acceptance threshold.
    exploration_mode: bool = False
    exploration_score_threshold: int = Field(default=40, ge=1, lt=70)
    shadow_fee_per_contract_usd: float = Field(default=0.0, ge=0)
    shadow_slippage_per_leg_usd: float = Field(default=0.0, ge=0)
    max_open_positions: int = Field(default=3, ge=1)
    max_contracts_per_trade: int = Field(default=1, ge=1)
    risk_fraction_per_trade: float = Field(default=0.005, gt=0, le=0.02)
    max_trade_risk_usd: float = Field(default=500.0, gt=0)
    max_bid_ask_spread_pct: float = Field(default=0.08, gt=0, le=1)
    max_execution_quote_age_seconds: int = Field(default=60, ge=1, le=300)
    max_plan_debit_change_pct: float = Field(default=0.10, ge=0, le=0.50)
    plan_approval_ttl_seconds: int = Field(default=300, ge=30, le=300)
    quote_derived_risk_free_rate: float = Field(default=0.04, ge=0, le=0.10)
    min_dte: int = Field(default=14, ge=1)
    max_dte: int = Field(default=28, ge=1)
    underlying_universe: str = "SPY,QQQ,IWM"

    @field_validator("max_dte")
    @classmethod
    def dte_window_is_valid(cls, value: int, info) -> int:
        if "min_dte" in info.data and value < info.data["min_dte"]:
            raise ValueError("MAX_DTE must be at least MIN_DTE")
        return value

    @model_validator(mode="after")
    def paper_mode_is_mandatory(self) -> "Settings":
        if not self.alpaca_paper_trade:
            raise ValueError("VegaGuard is permanently restricted to ALPACA_PAPER_TRADE=true")
        return self

    def mcp_environment(self) -> dict[str, str]:
        if not self.alpaca_api_key or not self.alpaca_secret_key:
            raise RuntimeError("Missing ALPACA_API_KEY or ALPACA_SECRET_KEY in .env")
        return {
            "ALPACA_API_KEY": self.alpaca_api_key.get_secret_value(),
            "ALPACA_SECRET_KEY": self.alpaca_secret_key.get_secret_value(),
            "ALPACA_PAPER_TRADE": "true",
            "ALPACA_TOOLSETS": self.alpaca_toolsets,
        }

    @property
    def universe(self) -> list[str]:
        return [
            symbol.strip().upper()
            for symbol in self.underlying_universe.split(",")
            if symbol.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
