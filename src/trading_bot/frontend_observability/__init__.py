"""Read-only frontend observability over committed runtime artifacts.

Package import is intentionally side-effect free (DEF-FE-003): submodules
are re-exported lazily via PEP 562 ``__getattr__`` so that
``python -m trading_bot.frontend_observability.server`` does not preload
the ``server`` submodule during package import (which previously triggered
runpy's premature-import RuntimeWarning).
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = [
    "agent_timeline",
    "assets_view",
    "create_server",
    "decisions",
    "funnel",
    "main",
    "overview",
    "replay_status",
    "report_content",
    "report_list",
    "strategies",
    "trades",
]

# Public name -> owning submodule (resolved lazily, cached on first access).
_LAZY_EXPORTS: dict[str, str] = {
    "agent_timeline": "projections",
    "assets_view": "projections",
    "create_server": "server",
    "decisions": "projections",
    "funnel": "projections",
    "main": "server",
    "overview": "projections",
    "replay_status": "projections",
    "report_content": "projections",
    "report_list": "projections",
    "strategies": "projections",
    "trades": "projections",
}


def __getattr__(name: str) -> Any:  # PEP 562
    submodule = _LAZY_EXPORTS.get(name)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    obj = getattr(importlib.import_module(f"{__name__}.{submodule}"), name)
    globals()[name] = obj  # cache for subsequent lookups
    return obj


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
