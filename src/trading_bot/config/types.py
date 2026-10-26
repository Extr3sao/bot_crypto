"""Compatibility aliases for the authoritative configuration module.

WP-TDM-07 replaced :mod:`trading_bot.config.settings` with a flat dataclass
stub whose ``load_settings(path=None)`` ignored the ``config/*.yaml``
directory entirely and returned fixed defaults, keeping the public names in
this module. The authoritative implementation is
:mod:`trading_bot.config.settings` (Pydantic v2 over the six YAML files), so
this module now only re-exports it.

There must be exactly one source of configuration truth: an offline path that
hands out a configuration the real runtime never produced would let a run
declare itself valid (and report economics) on data nobody ever configured.
"""

from __future__ import annotations

from trading_bot.config.settings import (
    FLAT_ENV_ALIASES,
    Settings,
    load_settings,
)

__all__ = ["FLAT_ENV_ALIASES", "Settings", "load_settings"]
