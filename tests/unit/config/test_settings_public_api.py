"""Contract of the public configuration loader (WP-TDM-07).

``load_settings(config_dir=..., env_file=...)`` is called from twelve places: the
CLI, ``python -m trading_bot.config``, the autonomous PAPER entrypoint, the replay
harnesses and the config tests. A recovery shim replaced the implementation with
``load_settings(path=None)`` and every one of them died with a ``TypeError``
raised far from the cause.

These tests pin the contract, prove the loader still reads the YAML directory it
is given (i.e. it is not a stub that silently ignores configuration), and check
every call site in the repository against the real signature.
"""

from __future__ import annotations

import ast
import inspect
import shutil
from pathlib import Path

import pytest
import yaml

from trading_bot.config.settings import load_settings
from trading_bot.config.settings_contract import (
    CANONICAL_KEYWORDS,
    SettingsContractError,
    assert_load_settings_contract,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPO_ROOT / "config"


def test_public_signature_accepts_every_documented_keyword() -> None:
    parameters = inspect.signature(load_settings).parameters
    for keyword in CANONICAL_KEYWORDS:
        assert keyword in parameters, f"load_settings must accept {keyword}=..."


def test_real_loader_satisfies_the_contract() -> None:
    assert_load_settings_contract()  # must not raise


def test_the_contract_check_names_the_missing_keyword() -> None:
    def load_settings(path: str | None = None) -> object:
        return object()

    with pytest.raises(SettingsContractError) as excinfo:
        assert_load_settings_contract(load_settings)

    message = str(excinfo.value)
    assert "config_dir" in message
    assert "load_settings(config_dir" in message
    assert "src/trading_bot/config/settings.py" in message


def test_a_kwargs_loader_is_also_acceptable() -> None:
    def load_settings(**kwargs: object) -> object:
        return kwargs

    assert_load_settings_contract(load_settings)


def test_the_loader_reads_the_directory_it_is_given(tmp_path: Path) -> None:
    """A stub that ignores ``config_dir`` would pass a signature test and fail here."""
    target = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, target, ignore=shutil.ignore_patterns("baseline", "realdata"))
    risk_yaml = target / "risk.yaml"
    payload = yaml.safe_load(risk_yaml.read_text(encoding="utf-8"))
    payload["risk"]["max_risk_per_trade_pct"] = 0.37
    risk_yaml.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    loaded = load_settings(config_dir=target, env_file=None)

    assert loaded.risk.max_risk_per_trade_pct == pytest.approx(0.37)


def _calls_to_the_config_loader(tree: ast.Module) -> list[ast.Call]:
    """Calls to the config loader only, resolved through the module's imports.

    A name-based scan would flag unrelated helpers that happen to be called
    ``load_settings``; the contract is about ``trading_bot.config``.
    """
    imported = False
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "trading_bot.config"
        ):
            for alias in node.names:
                if alias.name == "load_settings":
                    imported = True
                    aliases.add(alias.asname or alias.name)
    if not imported:
        return []
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (isinstance(func, ast.Name) and func.id in aliases) or (
            isinstance(func, ast.Attribute) and func.attr == "load_settings"
        ):
            calls.append(node)
    return calls


def test_every_call_site_only_passes_supported_keywords() -> None:
    """The contract is only useful if the real consumers fit inside it."""
    parameters = inspect.signature(load_settings).parameters
    accepts_any = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values())
    offenders: list[str] = []
    scanned = 0
    for root in (REPO_ROOT / "src", REPO_ROOT / "scripts", REPO_ROOT / "tests"):
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            try:
                calls = _calls_to_the_config_loader(ast.parse(path.read_text(encoding="utf-8")))
            except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - generated file
                continue
            scanned += 1
            for call in calls:
                for keyword in call.keywords:
                    if keyword.arg is None or accepts_any:
                        continue
                    if keyword.arg not in parameters:
                        offenders.append(
                            f"{path.relative_to(REPO_ROOT)}:{call.lineno} passes {keyword.arg}="
                        )
    assert scanned > 50, "the scan must actually cover the repository"
    assert offenders == [], "these call sites would break on the canonical loader: " + ", ".join(
        offenders
    )
