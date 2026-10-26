"""Effective behaviour of the configuration loader after the WP-TDM-07 repair.

The branch shipped a flat dataclass stub whose ``load_settings(path=None)``
ignored ``config/*.yaml`` entirely: the signature tests kept passing while the
runtime silently read fixed defaults (including a hardcoded
``ROUNDTRIP_COST_BPS = 891`` admission claim nobody ever configured). These
tests pin the *behaviour* instead of the signature — every one of the six YAML
files must reach the resulting object, the offline aliases must resolve to the
same authoritative loader, and no stub constant may survive.
"""

from __future__ import annotations

import inspect
import shutil
from pathlib import Path

import pytest
import yaml

import trading_bot.config.settings as settings_module
import trading_bot.config.types as types_module
from trading_bot.config import settings as package_settings
from trading_bot.config.settings import Settings, get_settings, load_settings
from trading_bot.config.types import Settings as TypesSettings

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPO_ROOT / "config"

#: One observable key per YAML file: the six files that ``YamlDirectorySource``
#: must merge for the loader to be the real one.
PROBES: tuple[tuple[str, tuple[str, ...], object, object], ...] = (
    ("assets.yaml", ("universe", "name"), "u19_assets_probe", lambda s: s.universe.name),
    ("exchange.yaml", ("exchange", "rate_limit_ms"), 1234, lambda s: s.exchange.rate_limit_ms),
    (
        "indicators.yaml",
        ("indicators", "global", "require_min_candles"),
        42,
        lambda s: s.indicators.global_.require_min_candles,
    ),
    (
        "risk.yaml",
        ("risk", "max_risk_per_trade_pct"),
        0.37,
        lambda s: s.risk.max_risk_per_trade_pct,
    ),
    (
        "runtime.yaml",
        ("runtime", "logging", "level"),
        "DEBUG",
        lambda s: s.runtime.logging.level,
    ),
    (
        "strategies.yaml",
        ("strategies", "global", "require_min_trades_for_promotion"),
        777,
        lambda s: s.strategies.global_.require_min_trades_for_promotion,
    ),
)


def _patch_yaml(source: Path, target: Path, path: tuple[str, ...], value: object) -> None:
    payload = yaml.safe_load((source / target.name).read_text(encoding="utf-8"))
    node = payload
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    target.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_each_of_the_six_yaml_files_reaches_the_loaded_settings(tmp_path: Path) -> None:
    """A loader that ignores the directory would leave every probe untouched."""
    target = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, target, ignore=shutil.ignore_patterns("baseline", "realdata"))
    for file_name, path, value, _ in PROBES:
        _patch_yaml(CONFIG_DIR, target / file_name, path, value)

    loaded = load_settings(config_dir=target, env_file=None)

    missed: list[str] = []
    for file_name, path, expected, read in PROBES:
        observed = read(loaded)
        if observed != expected:
            missed.append(f"{file_name}:{'.'.join(path)} -> {observed!r} (esperado {expected!r})")
    assert missed == [], "el loader no leyó estos YAML: " + "; ".join(missed)


def test_types_module_reexports_the_authoritative_objects() -> None:
    """Single source of truth: the offline aliases must not define their own."""
    assert TypesSettings is settings_module.Settings
    assert types_module.load_settings is settings_module.load_settings
    assert types_module.FLAT_ENV_ALIASES is settings_module.FLAT_ENV_ALIASES


def test_types_load_settings_still_serves_the_canonical_keywords() -> None:
    """``exchange_connector``'s fallback imports the names from ``types``."""
    from trading_bot.config.types import FLAT_ENV_ALIASES, load_settings as types_loader

    assert types_loader is load_settings
    parameters = inspect.signature(types_loader).parameters
    assert "config_dir" in parameters and "env_file" in parameters
    assert FLAT_ENV_ALIASES  # the real alias table, not an empty stub


def test_get_settings_returns_a_real_loaded_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The compat getter must read ``./config``, not return fixed defaults."""
    monkeypatch.chdir(REPO_ROOT)
    configured = yaml.safe_load(
        (CONFIG_DIR / "risk.yaml").read_text(encoding="utf-8")
    )["risk"]["max_risk_per_trade_pct"]

    loaded = get_settings()

    assert isinstance(loaded, Settings)
    assert loaded.risk.max_risk_per_trade_pct == pytest.approx(configured)
    assert loaded.runtime.mode in {"research", "backtest", "paper", "shadow-live", "live"}


def test_get_settings_and_load_settings_agree(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both entry points must produce the same effective configuration.

    ``load_settings`` builds a fresh ``_Tuned`` subclass per call, so the
    objects compare unequal by type; the effective data is what must match.
    """
    monkeypatch.chdir(REPO_ROOT)
    assert get_settings().model_dump() == load_settings().model_dump()


def test_no_stub_admission_constants_are_exposed() -> None:
    """The stub invented economics (891 bps) that no YAML ever declared.

    Such constants let an offline run report profitability on data the real
    runtime never produced, so their absence is part of the contract.
    """
    for module in (settings_module, types_module, package_settings):
        assert not hasattr(module, "ROUNDTRIP_COST_BPS"), (
            f"{module.__name__} expone ROUNDTRIP_COST_BPS: constante del stub"
        )
        assert not hasattr(module, "STRATEGY_ADMISSION_CONFIG"), (
            f"{module.__name__} expone STRATEGY_ADMISSION_CONFIG: constante del stub"
        )
    assert not hasattr(settings_module, "_COMPAT_DEFAULT_SETTINGS")


def test_settings_is_the_pydantic_aggregator_not_a_flat_dataclass() -> None:
    from pydantic_settings import BaseSettings

    assert issubclass(Settings, BaseSettings)
    fields = set(Settings.model_fields)
    for nested in ("universe", "exchange", "risk", "strategies", "indicators", "runtime"):
        assert nested in fields, f"Settings debe exponer el dominio {nested}"
    for flat_stub_field in ("allow_live", "paper_lot_size", "max_open_trades_usd"):
        assert flat_stub_field not in fields, (
            f"{flat_stub_field} pertenece al dataclass plano del stub"
        )
