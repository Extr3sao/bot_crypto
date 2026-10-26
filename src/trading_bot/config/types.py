from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

__all__ = ["Settings", "load_settings", "FLAT_ENV_ALIASES", "ROUNDTRIP_COST_BPS", "STRATEGY_ADMISSION_CONFIG"]


@dataclass
class Settings:
    exchange_api_key: str = ""
    exchange_secret: str = ""
    exchange_sandbox: bool = False
    exchange_id: str = "binance"
    env: str = "paper"
    log_level: str = "INFO"
    paper: bool = True
    paper_lot_size: int = 100
    paper_lot_size_usd: int = 100
    max_open_trades: int = 1
    max_open_trades_usd: int = 1000
    max_position_usd: int = 1000
    max_notional_per_order_usd: int = 1000
    max_position_age_seconds: int = 120
    allow_live: bool = False
    redis_url: Optional[str] = None
    kafka_bootstrap_servers: Optional[str] = None
    db_url: Optional[str] = None
    broker_url: Optional[str] = None

    def __post_init__(self):
        if not self.exchange_api_key:
            self.allow_live = False


def load_settings(path: Optional[str] = None) -> Settings:
    return Settings()


FLAT_ENV_ALIASES: Dict[str, str] = {"paper": "paper", "sandbox": "paper", "live": "live"}

ROUNDTRIP_COST_BPS: int = 891

STRATEGY_ADMISSION_CONFIG: Dict[str, Any] = {
    "roundtrip_cost_bps": ROUNDTRIP_COST_BPS,
    "min_net_edge_bps": 0.0,
    "max_open_trades": 1,
    "allow_live": False,
}

STRATEGY_ADMISSION_CONFIG_PATH: Optional[str] = None
_STRATEGY_ADMISSION_CONFIG_FOR_TESTS: Optional[Dict[str, Any]] = None


def strategy_admission_config(path: Optional[str] = None) -> Dict[str, Any]:
    return STRATEGY_ADMISSION_CONFIG


def strategy_admission_config_for_tests(path: Optional[str] = None) -> Dict[str, Any]:
    return STRATEGY_ADMISSION_CONFIG


def set_strategy_admission_config_for_tests(path: Optional[str]) -> None:
    pass
