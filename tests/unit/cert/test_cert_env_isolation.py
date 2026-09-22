"""CP-PO-003.1 STEP 4 — permanent hermetic certification environment guard.

Guard contract (uses existing config contracts, no invented counters):

- ``guard_hermetic()`` FAILS LOUDLY (RuntimeError) if any external shell
  variable attempts to select LIVE / a real exchange / load credentials,
  or if the committed defaults are not paper + sandbox + no credentials.
- The wrapper ``scripts/cert_env.sh`` unsets every live-selecting and
  credential variable and exports ``CERT_HERMETIC=1``; the guard reads
  settings with ``env_file=None`` so an operator's real ``.env`` can never
  influence certification.

Enumerated live/credential sources (both the flat ``FLAT_ENV_ALIASES``
names and the pydantic-settings nested ``RUNTIME__*`` / ``EXCHANGE__*``
forms) mirror the wrapper's scrub list; a dedicated test prevents the two
lists from drifting apart.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from trading_bot.config.runtime import TradingMode
from trading_bot.config.settings import load_settings

LIVE_SELECTING_VARS: tuple[str, ...] = (
    "TRADING_MODE",
    "LIVE_TRADING_ENABLED",
    "I_UNDERSTAND_THE_RISKS",
    "EXCHANGE_ID",
    "RUNTIME_EXCHANGE_ID",
    "EXCHANGE_SANDBOX",
    "RUNTIME__MODE",
    "RUNTIME__LIVE_TRADING_ENABLED",
    "RUNTIME__EXCHANGE_ID",
    "RUNTIME__I_UNDERSTAND_THE_RISKS",
    "EXCHANGE__ID",
    "EXCHANGE__SANDBOX",
)

CREDENTIAL_VARS: tuple[str, ...] = (
    "EXCHANGE_API_KEY",
    "EXCHANGE_API_SECRET",
    "EXCHANGE_PASSWORD",
    "EXCHANGE__API_KEY",
    "EXCHANGE__API_SECRET",
    "EXCHANGE__PASSWORD",
    "BITUNIX_API_KEY",
    "BITUNIX_API_SECRET",
    "API_KEY",
    "API_SECRET",
)

ALL_GUARDED_VARS: tuple[str, ...] = LIVE_SELECTING_VARS + CREDENTIAL_VARS

WRAPPER_PATH = Path(__file__).resolve().parents[3] / "scripts" / "cert_env.sh"


def _scrub_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mirror cert_env.sh inside the test: remove every guarded variable."""
    for var in ALL_GUARDED_VARS:
        monkeypatch.delenv(var, raising=False)


def guard_hermetic() -> dict[str, Any]:
    """Certification guard — fails loudly when the env is not hermetic.

    Checks (against committed YAML defaults, env_file=None):
      1. runtime.mode == PAPER
      2. live_trading_enabled is False
      3. exchange.sandbox is True
      4. exchange api_key / api_secret / password are empty
    and raises RuntimeError listing every offending variable otherwise.
    """
    offenders = [v for v in ALL_GUARDED_VARS if os.environ.get(v, "") != ""]
    settings = load_settings(env_file=None)
    probe = {
        "mode": settings.runtime.mode,
        "live_trading_enabled": settings.runtime.live_trading_enabled,
        "sandbox": settings.exchange.sandbox,
        "api_key": settings.exchange.api_key,
        "api_secret": settings.exchange.api_secret,
        "password": settings.exchange.password,
    }
    if not offenders and (
        probe["mode"] == TradingMode.PAPER
        and probe["live_trading_enabled"] is False
        and probe["sandbox"] is True
        and probe["api_key"] == ""
        and probe["api_secret"] == ""
        and probe["password"] == ""
    ):
        return probe
    problems: list[str] = []
    if offenders:
        problems.append("live/credential env vars present: " + ", ".join(offenders))
    if probe["mode"] != TradingMode.PAPER:
        problems.append(f"mode={probe['mode']!r}")
    if probe["live_trading_enabled"] is not False:
        problems.append(f"live_trading_enabled={probe['live_trading_enabled']!r}")
    if probe["sandbox"] is not True:
        problems.append(f"sandbox={probe['sandbox']!r}")
    if probe["api_key"] or probe["api_secret"] or probe["password"]:
        problems.append("production credentials loaded")
    raise RuntimeError("HERMETIC_CERT_ENV_VIOLATION: " + "; ".join(problems))


def test_guard_raises_when_external_var_selects_live(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every guarded var must trip the guard loudly (fail-closed).

    A non-empty value must never pass silently. Depending on the variable it
    either trips ``guard_hermetic``'s RuntimeError or pydantic-settings
    rejects the value outright (ValidationError on enum/bool fields) — both
    are loud, deterministic failures. The invariant checked here is: with the
    variable present, certification can never obtain a silent PASS.
    """
    from pydantic import ValidationError

    _scrub_env(monkeypatch)
    for var in ALL_GUARDED_VARS:
        monkeypatch.setenv(var, "x")
        try:
            guard_hermetic()
        except (RuntimeError, ValidationError) as exc:
            # expected: loud failure of one of the two allowed kinds
            assert (
                "HERMETIC_CERT_ENV_VIOLATION" in str(exc) or "ValidationError" in type(exc).__name__
            )
        else:
            raise AssertionError(
                f"guard silently accepted {var}=x — certification could "
                "inherit a live-selecting/credential variable"
            )
        monkeypatch.delenv(var, raising=False)


def test_guard_passes_on_committed_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """With a scrubbed env the committed defaults satisfy the guard."""
    _scrub_env(monkeypatch)
    probe = guard_hermetic()
    assert probe["mode"] == TradingMode.PAPER
    assert probe["live_trading_enabled"] is False
    assert probe["sandbox"] is True
    assert probe["api_key"] == ""
    assert probe["api_secret"] == ""
    assert probe["password"] == ""


def test_wrapper_scrub_list_covers_guarded_vars() -> None:
    """The wrapper's list must not drift from the guard's list."""
    wrapper = WRAPPER_PATH.read_text(encoding="utf-8")
    for var in ALL_GUARDED_VARS:
        assert var in wrapper, f"cert_env.sh missing {var!r} in scrub list"


def test_wrapper_sets_hermetic_marker() -> None:
    """cert_env.sh must export CERT_HERMETIC=1 for certification runs."""
    wrapper = WRAPPER_PATH.read_text(encoding="utf-8")
    assert "export CERT_HERMETIC=1" in wrapper
