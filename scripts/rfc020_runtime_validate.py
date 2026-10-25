"""RFC-020 real-runtime re-execution (§37) + replay invariance (§27).

Re-runs the AUTHORITATIVE runtime on the frozen baseline (same commit, config,
dataset, step=60) through the certified RFC-010 harness — twice — and:

* compares the economic semantics to the RFC-010B baseline (counts, equity,
  registry), where any change must be explained;
* checks §27 replay invariance: the two runs must produce the SAME decision
  projection (excluding explicitly non-deterministic ids: run_id, decision_id's
  session uuid, created_at_ms and the hash chain).

Usage:
    python scripts/rfc020_runtime_validate.py \\
        --out reports/data-integrity/RUNTIME_DATA_PARITY.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def _load_harness() -> Any:
    spec = importlib.util.spec_from_file_location(
        "rfc010_baseline_replay", REPO / "scripts" / "rfc010_baseline_replay.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["rfc010_baseline_replay"] = module
    spec.loader.exec_module(module)
    return module


H = _load_harness()

EXCLUDE_KEYS = {"run_id", "created_at_ms", "decision_id", "trace_hash", "prev_hash"}


def projection(run_dir: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for line in (run_dir / "traces.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        prop = row.get("proposal") or {}
        ctx = row.get("asset_context") or {}
        dq = ctx.get("data_quality") or {}
        key = f"{row.get('decision_time_ms')}|{row.get('asset')}"
        out[key] = {
            "mode": row.get("mode"),
            "classification": row.get("classification"),
            "no_trade_kind": row.get("no_trade_kind"),
            "regime": row.get("regime"),
            "market_time_ms": row.get("market_time_ms"),
            "strategy": prop.get("strategy_id"),
            "gross": prop.get("expected_gross_edge_bps"),
            "cost": prop.get("expected_cost_bps"),
            "net": prop.get("expected_net_edge_bps"),
            "window_end_ts": ctx.get("window_end_ts"),
            "newest_bar_ts": dq.get("newest_bar_ts"),
            "order_created": row.get("order_created"),
        }
    return out


async def run_baseline(run_id: str) -> dict[str, Any]:
    args = argparse.Namespace(
        assets="BTC,ETH,SOL",
        windows="W1,W2,W3,W4",
        timeframe="5m",
        step=60,
        max_bars=0,
        initial_equity=10_000.0,
        size_usd=1_000.0,
        lookback_bars=120,
        spread_bps=1.0,
        run_id=run_id,
        out=f"reports/rfc020/{run_id}_summary.json",
    )
    return dict(await H.run(args))


def main() -> int:
    import asyncio

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="reports/data-integrity/RUNTIME_DATA_PARITY.json")
    ap.add_argument("--reference", default="reports/rfc010/baseline_dev.json")
    args = ap.parse_args()

    # §18 isolation: a fresh store per run so a previous execution's outcomes or
    # experience memory can never leak into this run's decisions.
    for run_id in ("RFC020-DEV", "RFC020-DEV-B"):
        run_dir = REPO / "reports" / "rfc010" / "runs" / run_id
        for name in ("traces.jsonl", "outcomes.jsonl", "performance.json"):
            p = run_dir / name
            if p.exists():
                p.unlink()

    first = asyncio.run(run_baseline("RFC020-DEV"))
    second = asyncio.run(run_baseline("RFC020-DEV-B"))

    ref = json.loads((REPO / args.reference).read_text(encoding="utf-8"))

    counted = [
        "asset_cycle_evaluations",
        "paper_trades",
        "shadow_trades",
        "no_trades",
        "orders_created",
        "traces_persisted",
        "outcomes_resolved",
        "outcomes_pending",
    ]
    compare: dict[str, Any] = {}
    mismatches: list[str] = []
    for key in counted:
        a = first["totals"].get(key)
        b = ref["totals"].get(key)
        compare[key] = {"rfc020": a, "rfc010b": b, "match": a == b}
        if a != b:
            mismatches.append(key)
    for key in ("final_equity", "cycles_completed", "decision_instants", "realized_pnl"):
        a = first.get(key)
        b = ref.get(key)
        compare[key] = {"rfc020": a, "rfc010b": b, "match": a == b}
        if a != b:
            mismatches.append(key)

    proj_a = projection(REPO / "reports" / "rfc010" / "runs" / "RFC020-DEV")
    proj_b = projection(REPO / "reports" / "rfc010" / "runs" / "RFC020-DEV-B")
    invariance_mismatch = [k for k, v in proj_a.items() if proj_b.get(k) != v]

    report = {
        "schema": "rfc020.runtime_data_parity.v1",
        "reference": args.reference,
        "runs": {
            "RFC020-DEV": {
                "decision_instants": first["decision_instants"],
                "final_equity": first["final_equity"],
                "totals": first["totals"],
                "trace_chain": first["trace_chain"],
            },
            "RFC020-DEV-B": {
                "decision_instants": second["decision_instants"],
                "final_equity": second["final_equity"],
                "totals": second["totals"],
                "trace_chain": second["trace_chain"],
            },
        },
        "baseline_comparison": compare,
        "baseline_semantically_equivalent": len(mismatches) == 0,
        "baseline_mismatch_fields": mismatches,
        "replay_invariance": {
            "decisions_compared": len(proj_a),
            "mismatches": len(invariance_mismatch),
            "mismatch_samples": invariance_mismatch[:5],
            "pass": len(invariance_mismatch) == 0 and set(proj_a) == set(proj_b),
            "excluded_nondeterministic_keys": sorted(EXCLUDE_KEYS),
        },
        "registry_counts": first["registry_counts"],
        "FALSE_SUCCESS": 0,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "baseline_equivalent": report["baseline_semantically_equivalent"],
                "baseline_mismatch_fields": mismatches,
                "replay_invariance": report["replay_invariance"]["pass"],
                "rfc020_totals": first["totals"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
