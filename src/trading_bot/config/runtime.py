"""Runtime configuration. Mirrors config/runtime.yaml.

Contiene los gates de live trading (DoD fail-fast).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class TradingMode(StrEnum):
    """Bot operating mode. Defaults to PAPER for safety."""

    RESEARCH = "research"
    BACKTEST = "backtest"
    PAPER = "paper"
    SHADOW_LIVE = "shadow_live"
    LIVE = "live"


_HHMM_RE = r"^([01]\d|2[0-3]):[0-5]\d$"
_LOG_LEVEL_RE = r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$"
_LOG_FORMAT_RE = r"^(json|text)$"


class SchedulerActiveHours(BaseModel):
    """Active trading window, HH:MM format each."""

    start: str = Field("00:00", pattern=_HHMM_RE)
    end: str = Field("23:59", pattern=_HHMM_RE)


class Scheduler(BaseModel):
    """Scheduler cadences."""

    timezone: str = "UTC"
    active_hours: SchedulerActiveHours = Field(default_factory=lambda: SchedulerActiveHours())
    scanner_interval_seconds: int = Field(30, ge=1)
    orders_poll_interval_seconds: int = Field(10, ge=1)
    health_interval_seconds: int = Field(60, ge=1)


class Storage(BaseModel):
    """Persistence backend settings."""

    database_url: str = "sqlite:///data/storage/bot.db"
    enable_signal_archive: bool = True
    enable_order_archive: bool = True
    enable_decision_archive: bool = True


class LoggingBlock(BaseModel):
    """Logging config. Named with 'Block' suffix to avoid builtin shadowing."""

    level: str = Field("INFO", pattern=_LOG_LEVEL_RE)
    format: str = Field("json", pattern=_LOG_FORMAT_RE)
    to_file: bool = True
    file_path: str = "logs/app.log"
    rotation: str = "10 MB"
    retention: int = Field(30, ge=1)


class Reports(BaseModel):
    """Reports output config."""

    output_dir: str = "reports"
    daily_summary: bool = True
    backtest_report: bool = True
    paper_report: bool = True


class Metrics(BaseModel):
    """Metrics placeholder for Fase 8."""

    enabled: bool = False
    prometheus_port: int = Field(9_000, ge=1, le=65_535)


class Paths(BaseModel):
    """Important filesystem paths."""

    config_dir: str = "config"
    data_dir: str = "data"
    logs_dir: str = "logs"
    reports_dir: str = "reports"
    evals_dir: str = "evals"


class FeatureFlags(BaseModel):
    """Feature toggles for cross-cutting capabilities."""

    enable_telegram_alerts: bool = False
    enable_dashboard: bool = False
    enable_walk_forward: bool = True
    enable_paper_trading: bool = True


class Runtime(BaseModel):
    """Runtime configuration. Contains the live-trading gate.

    The fail-fast check is implemented as a cross-field validator on
    `i_understand_the_risks`, populated from the env var
    `I_UNDERSTAND_THE_RISKS` (case-insensitive against `AliasChoices`).
    """

    model_config = ConfigDict(populate_by_name=True)

    mode: TradingMode = TradingMode.PAPER
    live_trading_enabled: bool = False
    require_manual_confirmation_for_live: bool = True
    # NOTE: el `validation_alias` de este campo NO es la fuente principal
    # durante `load_settings()`: `FlatEnvAliasSource` en settings.py ya
    # re-mapea `I_UNDERSTAND_THE_RISKS` (plano) hacia este campo. El alias
    # se mantiene aqui para callers que construyan Runtime directamente via
    # `Runtime.model_validate({"I_UNDERSTAND_THE_RISKS": True})` o
    # `Runtime(I_UNDERSTAND_THE_RISKS=True)`.
    i_understand_the_risks: bool = Field(
        False,
        validation_alias=AliasChoices("I_UNDERSTAND_THE_RISKS"),
        description=(
            "Confirmation flag. Mantener False por defecto. Solo se acepta True "
            "tras un ADR documentado en tasks/decisions.md."
        ),
    )
    scheduler: Scheduler = Field(default_factory=lambda: Scheduler())
    storage: Storage = Field(default_factory=lambda: Storage())
    logging: LoggingBlock = Field(default_factory=lambda: LoggingBlock())
    reports: Reports = Field(default_factory=lambda: Reports())
    metrics: Metrics = Field(default_factory=lambda: Metrics())
    paths: Paths = Field(default_factory=lambda: Paths())
    features: FeatureFlags = Field(default_factory=lambda: FeatureFlags())

    @model_validator(mode="after")
    def _check_live_gates(self) -> Runtime:
        """DoD fail-fast: live=true sin I_UNDERSTAND_THE_RISKS aborta el boot."""
        if self.live_trading_enabled and not self.i_understand_the_risks:
            raise ValueError(
                "runtime.live_trading_enabled=True pero I_UNDERSTAND_THE_RISKS "
                "no esta en 'true'. Por seguridad el bot no arranca en modo live "
                "sin confirmacion manual explicita del operador. Cambia el .env o "
                "pasa el ADR correspondiente antes de continuar."
            )
        if self.live_trading_enabled and not self.require_manual_confirmation_for_live:
            raise ValueError(
                "runtime.require_manual_confirmation_for_live debe ser True cuando "
                "live_trading_enabled=True (politica defensiva)."
            )
        if self.mode == TradingMode.LIVE and not self.live_trading_enabled:
            raise ValueError(
                "runtime.mode='live' requiere runtime.live_trading_enabled=True. "
                "Si quieres validar el entorno live sin ejecutar ordenes, usa "
                "'shadow_live'."
            )
        if self.mode == TradingMode.SHADOW_LIVE and self.live_trading_enabled:
            raise ValueError(
                "runtime.mode='shadow_live' no es compatible con "
                "live_trading_enabled=True. shadow_live es para validacion sin "
                "ordenes reales; usa 'live' si realmente quieres operar."
            )
        return self
