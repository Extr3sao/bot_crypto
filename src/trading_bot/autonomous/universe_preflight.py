"""Asset-universe preflight — ``configured ∩ provider ∩ strategy`` (§39, DEF-AUTO-2).

The defect this closes was silent: the configured universe could name an asset
the runtime had no AssetAgent for, and every cycle would then report a per-asset
``CONTEXT_ERROR: no AssetAgent registered for asset: X``. The run looked busy
and evaluated nothing, and the only person who could tell was whoever read a
thousand trace rows.

So the intersection is computed *before the loop starts*, per asset, with the
reason each asset is unusable, and the entrypoint refuses to start when the
configured universe is not fully serviceable. An asset that cannot be evaluated
is a configuration error, not a market state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "UniverseSupport",
    "preflight_universe",
    "research_universe_from_sources",
]


@dataclass(frozen=True, slots=True)
class UniverseSupport:
    """Per-layer view of which configured assets can actually be evaluated."""

    configured: tuple[str, ...]
    asset_agent_supported: tuple[str, ...]
    strategy_supported: tuple[str, ...]
    provider_supported: tuple[str, ...] | None
    effective: tuple[str, ...]
    unsupported: dict[str, str]
    strategy_universe_source: str
    provider_verified: bool
    ok: bool
    blocking_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "configured": list(self.configured),
            "asset_agent_supported": list(self.asset_agent_supported),
            "strategy_supported": list(self.strategy_supported),
            "provider_supported": (
                None if self.provider_supported is None else list(self.provider_supported)
            ),
            "effective": list(self.effective),
            "unsupported": dict(sorted(self.unsupported.items())),
            "strategy_universe_source": self.strategy_universe_source,
            "provider_verified": self.provider_verified,
            "ok": self.ok,
            "blocking_reason": self.blocking_reason,
        }


def preflight_universe(
    *,
    configured: tuple[str, ...] | list[str],
    asset_agents: tuple[str, ...] | list[str],
    strategy_assets: tuple[str, ...] | list[str] | None = None,
    provider_supported: tuple[str, ...] | list[str] | None = None,
    strategy_universe_source: str = "UNDECLARED",
) -> UniverseSupport:
    """Intersect the three layers and explain every exclusion.

    ``provider_supported=None`` means "not verified in this run" and is reported
    as such — it is never silently treated as "everything is supported", and it
    is never silently treated as a failure either. The layers that *can* be
    checked offline are hard requirements.
    """
    configured_list = tuple(dict.fromkeys(str(a).upper() for a in configured))
    agents = frozenset(str(a).upper() for a in asset_agents)
    strategies = (
        None
        if strategy_assets is None
        else frozenset(str(a).upper() for a in strategy_assets)
    )
    providers = (
        None
        if provider_supported is None
        else frozenset(str(a).upper() for a in provider_supported)
    )

    reasons: dict[str, str] = {}
    effective: list[str] = []
    for asset in configured_list:
        problems: list[str] = []
        if asset not in agents:
            problems.append("no AssetAgent registered (the runtime cannot build a context)")
        if strategies is not None and asset not in strategies:
            problems.append("no strategy evidence was researched on this asset")
        if providers is not None and asset not in providers:
            problems.append("provider does not list this market")
        if problems:
            reasons[asset] = "; ".join(problems)
        else:
            effective.append(asset)

    blocking = None
    if reasons:
        blocking = "unsupported assets: " + ", ".join(
            f"{asset} ({reason})" for asset, reason in sorted(reasons.items())
        )
    return UniverseSupport(
        configured=configured_list,
        asset_agent_supported=tuple(sorted(agents)),
        strategy_supported=tuple(sorted(strategies)) if strategies is not None else (),
        provider_supported=None if providers is None else tuple(sorted(providers)),
        effective=tuple(effective),
        unsupported=reasons,
        strategy_universe_source=strategy_universe_source,
        provider_verified=providers is not None,
        ok=not reasons,
        blocking_reason=blocking,
    )


def research_universe_from_sources(
    sources: tuple[dict[str, str], ...] | list[dict[str, str]],
    *,
    repo_root: Path | str = ".",
) -> tuple[tuple[str, ...], str]:
    """Read the asset universe the admission evidence was measured on (§36).

    The registry must be able to say *which assets a strategy was researched on*
    rather than inheriting the assets the operator happened to configure: those
    are different claims, and only the first one is about the strategy.

    Returns ``(assets, source)``; an unreadable or silent artifact yields an
    empty tuple and ``"UNDECLARED"`` so the caller can see that the layer could
    not be checked instead of assuming it passed.
    """
    root = Path(repo_root)
    for source in sources:
        path_raw = source.get("path", "")
        if not path_raw:
            continue
        path = root / path_raw
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        dataset = payload.get("dataset")
        if isinstance(dataset, dict):
            assets = dataset.get("assets")
            if isinstance(assets, list) and assets:
                return (
                    tuple(dict.fromkeys(str(a).upper() for a in assets)),
                    path_raw,
                )
    return (), "UNDECLARED"
