"""Child process for the restart E2E test (GATE STRAT-PERSIST-003 §17).

Not a test module: invoked as ``python _restart_child.py save|load-abrupt <path>``
so that "persist" and "recover" happen in *different OS processes*, which is what
makes the restart evidence real rather than in-memory.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from trading_bot.strategy_lifecycle.contracts import (
    ContextKey,
    LifecycleState,
    PromotionRecord,
)
from trading_bot.strategy_lifecycle.ecosystem import DynamicStrategyEcosystem
from trading_bot.strategy_lifecycle.lifecycle import LifecycleDecision
from trading_bot.strategy_lifecycle.persistence import (
    ecosystem_state_hash,
    load_ecosystem,
    save_ecosystem,
)

STATES = ("shadow", "eligible", "active", "degraded", "throttled", "paused", "retired")
CHAINS = {
    "shadow": [],
    "eligible": [LifecycleState.ELIGIBLE],
    "active": [LifecycleState.ELIGIBLE, LifecycleState.ACTIVE],
    "degraded": [LifecycleState.ELIGIBLE, LifecycleState.ACTIVE, LifecycleState.DEGRADED],
    "throttled": [
        LifecycleState.ELIGIBLE,
        LifecycleState.ACTIVE,
        LifecycleState.DEGRADED,
        LifecycleState.THROTTLED,
    ],
    "paused": [LifecycleState.PAUSED],
    "retired": [LifecycleState.RETIRED],
}
EVIDENCE_EDGES = {
    (LifecycleState.SHADOW, LifecycleState.ELIGIBLE),
    (LifecycleState.ELIGIBLE, LifecycleState.ACTIVE),
}


def _descriptor(sid: str):
    from trading_bot.strategy_lifecycle.contracts import StrategyDescriptor

    return StrategyDescriptor(
        strategy_id=sid,
        strategy_version="v1",
        family="momentum",
        assets=("BTC",),
        timeframes=("5m",),
        supported_regimes=("TREND_UP",),
        runtime_implementation="trading_bot.research.families.momentum",
        lifecycle_state=LifecycleState.SHADOW,
    )


def _advance(eco, sid, target, ts):
    src = eco.registry.state_of(sid)
    promo = None
    if (src, target) in EVIDENCE_EDGES:
        promo = PromotionRecord(
            promotion_id=f"{sid}:{src.value}->{target.value}:{ts}",
            strategy_id=sid,
            from_state=src,
            to_state=target,
            evidence=("e2e",),
            policy_version="v1",
        )
    eco.registry.apply(
        LifecycleDecision(
            strategy_id=sid,
            context=ContextKey(sid, "BTC", "5m", "TREND_UP"),
            from_state=src,
            to_state=target,
            reason_codes=("E2E",),
            metrics_snapshot={},
            evidence=("e2e",),
            policy_version="v1",
            promotion=promo,
            timestamp_ms=ts,
        )
    )


def build() -> DynamicStrategyEcosystem:
    eco = DynamicStrategyEcosystem()
    ts = 1000
    for name in STATES:
        sid = f"s-{name}"
        eco.register(_descriptor(sid))
        for step in CHAINS[name]:
            _advance(eco, sid, step, ts)
            ts += 1
    return eco


def _summary(eco) -> dict:
    return {
        "state_hash": ecosystem_state_hash(eco),
        "states": {sid: eco.registry.state_of(sid).value for sid in eco.registry.strategy_ids()},
        "active": eco.registry.active_ids(),
    }


def main(argv: list[str]) -> int:
    mode = argv[1]
    path = Path(argv[2])
    if mode == "save":
        eco = build()
        save_ecosystem(path, eco, run_id="e2e", commit_sha="c", persisted_at_ms=1)
        print(json.dumps(_summary(eco)))
        return 0
    if mode == "save-abrupt":
        # Persist, then exit without any graceful cleanup (simulated crash).
        eco = build()
        save_ecosystem(path, eco, run_id="e2e", commit_sha="c", persisted_at_ms=1)
        sys.stdout.write(json.dumps(_summary(eco)))
        sys.stdout.flush()
        os._exit(0)
    if mode == "load":
        eco = DynamicStrategyEcosystem()
        load_ecosystem(path, eco)
        print(json.dumps(_summary(eco)))
        return 0
    raise SystemExit(f"unknown mode {mode}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
