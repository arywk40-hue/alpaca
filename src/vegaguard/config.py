from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    alpaca_api_key: SecretStr | None = None
    alpaca_secret_key: SecretStr | None = None
    alpaca_paper_trade: bool = True
    alpaca_toolsets: str = "account,trading,assets,stock-data,options-data"
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-5-mini"
    allow_order_execution: bool = False
    max_open_positions: int = Field(default=3, ge=1)
    max_contracts_per_trade: int = Field(default=1, ge=1)
    risk_fraction_per_trade: float = Field(default=0.005, gt=0, le=0.02)
    max_trade_risk_usd: float = Field(default=500.0, gt=0)
    max_bid_ask_spread_pct: float = Field(default=0.08, gt=0, le=1)
    min_dte: int = Field(default=14, ge=1)
    max_dte: int = Field(default=28, ge=1)
    underlying_universe: str = "SPY,QQQ,IWM"

    @field_validator("max_dte")
    @classmethod
    def dte_window_is_valid(cls, value: int, info) -> int:
        if "min_dte" in info.data and value < info.data["min_dte"]:
            raise ValueError("MAX_DTE must be at least MIN_DTE")
        return value

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
