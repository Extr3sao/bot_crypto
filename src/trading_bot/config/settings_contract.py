"""Public contract of ``load_settings`` (WP-TDM-07).

Twelve call sites — the CLI, ``python -m trading_bot.config``, the autonomous
PAPER entrypoint, the replay harnesses and the config tests — call
``load_settings(config_dir=..., env_file=...)``. A recovery shim that replaces
``config/settings.py`` with ``load_settings(path=None)`` therefore breaks every
one of them with a ``TypeError`` raised far from the cause.

This module states the contract once and checks it *before* the call, so a drifted
implementation produces one actionable error naming the missing keyword, the
canonical signature and the evidence path — instead of a bare ``TypeError``.

It deliberately does **not** fall back to a stub: a checkout whose configuration
loader ignores the YAML is not a valid PAPER runtime, and silently running it
would report economics (891 bps constant, admission disabled) that the real
runtime never produced.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

__all__ = [
    "CANONICAL_KEYWORDS",
    "CANONICAL_SIGNATURE",
    "SettingsContractError",
    "assert_load_settings_contract",
]

#: Keywords every real consumer passes or may pass.
CANONICAL_KEYWORDS: tuple[str, ...] = ("config_dir", "env_file")

CANONICAL_SIGNATURE = "load_settings(config_dir: Path | str = 'config', env_file: Path | str | None = '.env') -> Settings"


class SettingsContractError(RuntimeError):
    """The installed ``load_settings`` cannot serve its documented consumers."""


def assert_load_settings_contract(
    loader: Callable[..., Any] | None = None,
) -> None:
    """Raise ``SettingsContractError`` when ``loader`` drifts from the contract.

    ``loader`` defaults to the runtime ``load_settings``; tests pass a fake one to
    prove the check itself catches a narrowed signature.
    """
    resolved: Callable[..., Any]
    if loader is None:
        from trading_bot.config.settings import load_settings as default_loader

        resolved = default_loader
    else:
        resolved = loader
    loader = resolved

    try:
        signature = inspect.signature(loader)
    except (TypeError, ValueError) as exc:  # pragma: no cover - non-introspectable
        raise SettingsContractError(
            f"load_settings({loader!r}) is not introspectable: {exc}"
        ) from exc

    parameters = signature.parameters
    accepts_kwargs = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values())
    missing = [
        name
        for name in CANONICAL_KEYWORDS
        if name not in parameters and not accepts_kwargs
    ]
    if not missing:
        return

    module = getattr(loader, "__module__", "?")
    qualname = getattr(loader, "__qualname__", repr(loader))
    raise SettingsContractError(
        "config API drift: "
        f"{module}.{qualname}{signature} does not accept {', '.join(missing)}. "
        f"Every consumer calls {CANONICAL_SIGNATURE}. "
        "The authoritative implementation lives in git at "
        "src/trading_bot/config/settings.py (HEAD); a recovery shim that ignores "
        "the YAML directory cannot serve PAPER. Restore that file (see "
        "reports/trading-decision-monitor/WP-TDM-07/integrity_analysis.md) before "
        "running the runtime."
    )
