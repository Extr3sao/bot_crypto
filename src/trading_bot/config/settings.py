"""Root Settings aggregator. Loads 6 YAMLs + .env with pydantic-settings.

Por que un unico YamlDirectorySource en lugar de 6: los YAML cubren
distintos dominios sin colisionar, asi que un solo merge superficial
mantiene la API pydantic-settings simple y garantiza precedencia
(env > YAML > defaults).

Ademas, ``FlatEnvAliasSource`` re-mapea el conjunto estable de nombres
planos que la documentacion publica usa (``.env.example``,
``docker-compose.yml``, ``docs/live-trading-checklist.md`` y los BDDs
en ``bdd/features/*.feature``) hacia su ruta anidada correspondiente
dentro de ``Settings``. Asi la API publica plana sigue funcionando
sin tocar documentacion ni romper los tests existentes, que ya escriben
variables con la forma anidada ``RUNTIME__MODE``.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values
from pydantic import model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from trading_bot.config.exchange import Exchange
from trading_bot.config.indicators import IndicatorsConfig
from trading_bot.config.risk import Risk
from trading_bot.config.runtime import Runtime, TradingMode
from trading_bot.config.strategies import StrategiesConfig
from trading_bot.config.universe import Universe

# Mapeo explicito flat-name -> ruta dentro de ``Settings``. La lista refleja
# literalmente lo que aparece en ``.env.example`` + ``docker-compose.yml`` +
# ``docs/live-trading-checklist.md`` + ``bdd/features/paper_trading.feature``.
# Cualquier nuevo nombre plano que se anada a la documentacion debe
# aparecer aqui tambien; de lo contrario ``load_settings()`` lo ignora
# silenciosamente y devuelve el default del YAML.
FLAT_ENV_ALIASES: dict[str, tuple[str, ...]] = {
    # Modo y live-trading gates (Runtime)
    "TRADING_MODE": ("runtime", "mode"),
    "LIVE_TRADING_ENABLED": ("runtime", "live_trading_enabled"),
    "I_UNDERSTAND_THE_RISKS": ("runtime", "i_understand_the_risks"),
    # Exchange
    "EXCHANGE_ID": ("exchange", "id"),
    "EXCHANGE_API_KEY": ("exchange", "api_key"),
    "EXCHANGE_API_SECRET": ("exchange", "api_secret"),
    "EXCHANGE_PASSWORD": ("exchange", "password"),
    "EXCHANGE_SANDBOX": ("exchange", "sandbox"),
    # Observabilidad (Runtime.Logging)
    "LOG_LEVEL": ("runtime", "logging", "level"),
    "LOG_FORMAT": ("runtime", "logging", "format"),
    "LOG_TO_FILE": ("runtime", "logging", "to_file"),
    "LOG_FILE_PATH": ("runtime", "logging", "file_path"),
    # Persistencia (Runtime.Storage)
    "DATABASE_URL": ("runtime", "storage", "database_url"),
    # Scheduler (Runtime.Scheduler)
    "SCHEDULER_TIMEZONE": ("runtime", "scheduler", "timezone"),
    "ACTIVE_HOURS_START": ("runtime", "scheduler", "active_hours", "start"),
    "ACTIVE_HOURS_END": ("runtime", "scheduler", "active_hours", "end"),
}


class YamlDirectorySource(PydanticBaseSettingsSource):
    """Reads all YAML in `config_dir` and merges their root keys into one dict."""

    FILES: tuple[str, ...] = (
        "assets.yaml",
        "exchange.yaml",
        "risk.yaml",
        "strategies.yaml",
        "indicators.yaml",
        "runtime.yaml",
    )

    def __init__(self, settings_cls: type[BaseSettings], config_dir: Path) -> None:
        super().__init__(settings_cls)
        self.config_dir = config_dir

    def get_field_value(
        self,
        field: Any,
        field_name: str,
    ) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        if not self.config_dir.exists():
            return merged
        for name in self.FILES:
            p = self.config_dir / name
            if not p.exists():
                continue
            with p.open("r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            if not isinstance(data, dict):
                raise ValueError(
                    f"YAML '{p}' debe tener un mapping raiz, no {type(data).__name__}."
                )
            overlap = set(merged.keys()) & set(data.keys())
            if overlap:
                raise ValueError(f"YAML '{p}' redefine keys de un YAML previo: {sorted(overlap)}")
            for k, v in data.items():
                merged[k] = v
        return merged


class FlatEnvAliasSource(PydanticBaseSettingsSource):
    """Re-maps flat documented env vars to nested ``Settings`` paths.

    Lookup is case-insensitive; both ``.env`` file values and
    ``os.environ`` are scanned, with ``os.environ`` winning ties.

    Insertion point in ``settings_customise_sources``: between
    ``dotenv_settings`` and ``file_secret_settings``. Higher-priority
    sources (``init_kwargs``, ``env_settings``, ``dotenv_settings``)
    still override this one, de modo que un valor en forma anidada
    como ``RUNTIME__MODE`` sigue ganando sobre el plano
    ``TRADING_MODE`` si ambos estan definidos.
    """

    ALIASES: dict[str, tuple[str, ...]] = FLAT_ENV_ALIASES

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        env_file: Path | str | Sequence[Path | str] | None,
    ) -> None:
        super().__init__(settings_cls)
        self.env_file = env_file

    def get_field_value(
        self,
        field: Any,
        field_name: str,
    ) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        # Build a unified env-style dict. ``os.environ`` wins over the file.
        raw: dict[str, str] = {}
        if self.env_file is not None:
            env_value: Path | str | None
            if isinstance(self.env_file, Sequence) and not isinstance(self.env_file, (str, bytes)):
                env_value = self.env_file[0] if self.env_file else None
            else:
                env_value = self.env_file
            env_path = Path(env_value) if env_value is not None else None
            if env_path is not None and env_path.exists():
                file_values = dotenv_values(env_path) or {}
                raw.update({k: v for k, v in file_values.items() if v is not None and v != ""})
        raw.update({k: v for k, v in os.environ.items() if v != ""})
        # Normalize to uppercase so the alias map (which is uppercase-by-
        # convention) can be matched case-insensitively.
        uppered = {k.upper(): v for k, v in raw.items()}

        merged: dict[str, Any] = {}
        for flat_key, path in self.ALIASES.items():
            value = uppered.get(flat_key.upper())
            if value is None:
                continue
            current: dict[str, Any] = merged
            for step in path[:-1]:
                current = current.setdefault(step, {})
            current[path[-1]] = value
        return merged


class Settings(BaseSettings):
    """Aggregator: 6 YAML + .env + process env.

    Precedencia (mayor a menor): init kwargs > process env > .env > flat-alias > YAML > defaults.

    Field types point directly to the inner content classes (no `_Config`
    wrapper layer), so user code reads ``settings.risk.max_risk_per_trade_pct``
    rather than ``settings.risk.risk.max_risk_per_trade_pct``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        case_sensitive=False,
    )

    universe: Universe
    exchange: Exchange
    risk: Risk
    strategies: StrategiesConfig
    indicators: IndicatorsConfig
    runtime: Runtime

    @model_validator(mode="after")
    def _check_cross_domain_live_invariants(self) -> Settings:
        """Cross-domain live-trading invariants not enforceable inside a single domain."""
        if self.runtime.mode == TradingMode.LIVE and not self.risk.kill_switch_enabled:
            raise ValueError(
                "runtime.mode='live' requiere risk.kill_switch_enabled=True para "
                "que el kill switch pueda detener el bot en una emergencia."
            )
        return self

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # env_file is read from model_config so the source stays in sync
        # with pydantic-settings' built-in dotenv. Direct Settings()
        # instantiation outside of load_settings() is undocumented and gets
        # the default '.env'; load_settings() routes through _Tuned which
        # overrides model_config with the caller-supplied env_file.
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            FlatEnvAliasSource(settings_cls, settings_cls.model_config.get("env_file")),
            file_secret_settings,
            YamlDirectorySource(settings_cls, Path("config")),
        )


def load_settings(
    config_dir: Path | str = "config",
    env_file: Path | str | None = ".env",
) -> Settings:
    """Public entry point.

    Constructs a Settings subclass whose ``YamlDirectorySource`` reads from
    the caller-supplied ``config_dir``. This avoids relying on the working
    directory for tests and alternative config layouts. ``env_file`` is
    passed both to pydantic-settings' built-in ``dotenv`` source (via the
    ``_env_file`` kwarg) and to ``FlatEnvAliasSource`` (via closure).
    """

    class _Tuned(Settings):
        # Override model_config.env_file with the caller-supplied path so
        # pydantic-settings' built-in dotenv source and FlatEnvAliasSource
        # (which reads from model_config in Settings.settings_customise_sources)
        # agree on the SAME file for both flat and nested name lookups.
        model_config = SettingsConfigDict(
            env_file=str(env_file) if env_file is not None else None,
            env_file_encoding="utf-8",
            env_nested_delimiter="__",
            extra="ignore",
            case_sensitive=False,
        )

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (
                init_settings,
                env_settings,
                dotenv_settings,
                FlatEnvAliasSource(settings_cls, settings_cls.model_config.get("env_file")),
                file_secret_settings,
                YamlDirectorySource(settings_cls, Path(config_dir)),
            )

    # Single source of truth for env_file: _Tuned.model_config (definido
    # arriba) lo enruta a BOTH dotenv_settings y FlatEnvAliasSource. El
    # antiguo `_Tuned(_env_file=...)` instance-kwarg pasaba el mismo path
    # por una segunda via redundante; ya no hace falta.
    # YAML/dotenv/env populated at runtime via Settings.model_config + customise_sources.
    # The prior `# type: ignore[call-arg]` directive is obsolete after the
    # TSK-200 pydantic.mypy plugin was promoted to global [tool.mypy]
    # (see pyproject.toml); _Tuned() now type-checks cleanly without it.
    return _Tuned()  # YAML/dotenv/env populated at runtime
