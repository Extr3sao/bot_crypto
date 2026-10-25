"""WP-ECONOMIC-BLOCKER-001 — what one round trip costs, and why.

Nothing here is copied from a report. Three independent checks:

1. **Recompute the recorded cost.** The ``CostBreakdown`` blocks the PAPER
   runtime emitted in WP-PAPER-REAL-DATA-001 are extracted with their source
   SHA-256 and fed back into ``CostEngine.evaluate`` at the same size, spread
   and horizon. Recomputed and recorded round trips must agree to 1e-6.
2. **Recompute the published per-asset model.** ``docs/EXECUTION_COST_MODEL_V4.json``
   is re-derived from its own measured inputs through ``asset_cost_v4``.
3. **Decompose and stress it.** Each component keeps its knowledge class
   (KNOWN / OBSERVED / ESTIMATED / ASSUMED); the cost is then swept over size,
   horizon and spread fallback so the *structure* of the barrier is visible
   rather than a single scalar.

The point of (3) is that the verdict should not depend on the uncertain terms:
if the KNOWN taker fees alone already exceed every measured gross edge, then no
re-estimation of slippage can rescue a strategy.

Writes ``COST_MODEL_AUDIT.json`` plus ``COST_OBSERVED.json`` (the extracted
blocks, so the audit is readable without the neighbouring worktree).

Usage::

    uv run python scripts/wp_eco001_cost_audit.py --out <evidence dir> \
        [--runtime-evidence <path to WP-PAPER-REAL-DATA-001>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from trading_bot.autonomous.costs import CostEngine
from trading_bot.research.microstructure.cost_model_v3 import ADMISSION_SCENARIO_ID, VENUE_SPECS
from trading_bot.research.microstructure.cost_model_v4 import (
    ADMISSION_SAFETY_MULTIPLE,
    AssetMarketInput,
    asset_cost_v4,
    required_gross_edge_bps,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME_EVIDENCE = Path(
    r"C:\Users\GVLLFR0035\Downloads\ff-wt-prd001\docs\agentic\paper_reald\WP-PAPER-REAL-DATA-001"
)
V4_RESULTS = Path("docs/EXECUTION_COST_MODEL_V4.json")
V3_RESULTS = Path("docs/STRATEGY_DISCOVERY_V3_RESULTS.json")
TOLERANCE_BPS = 1e-6
EXPECTED_COMPONENTS = (
    "exchange_fee_entry",
    "exchange_fee_exit",
    "spread",
    "slippage",
    "market_impact",
    "adverse_selection",
    "missed_fill_penalty",
    "fill_probability_inflation",
    "funding_carry",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_observed(root: Path) -> list[dict[str, Any]]:
    """Every cost block a PAPER run emitted, with the asset it belonged to."""
    blocks: list[dict[str, Any]] = []
    for trace in sorted(root.glob("raw/runs/*/traces.jsonl")):
        digest = sha256(trace)
        for line in trace.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            found: list[dict[str, Any]] = []

            def walk(node: Any, asset: str | None, sink: list[dict[str, Any]] = found) -> None:
                if isinstance(node, dict):
                    here = node.get("asset") if isinstance(node.get("asset"), str) else asset
                    if "round_trip_bps" in node:
                        sink.append({**node, "asset": here})
                        return
                    for value in node.values():
                        walk(value, here, sink)
                elif isinstance(node, list):
                    for value in node:
                        walk(value, asset, sink)

            walk(json.loads(line), None)
            for block in found:
                blocks.append(
                    {
                        "run": trace.parent.name,
                        "trace": trace.as_posix(),
                        "trace_sha256": digest,
                        "asset": block.get("asset"),
                        "scenario_id": block.get("scenario_id"),
                        "size_usd": block.get("size_usd"),
                        "horizon_minutes": block.get("horizon_minutes"),
                        "spread_bps": block.get("spread_bps"),
                        "spread_knowledge": block.get("spread_knowledge"),
                        "fee_bps": block.get("fee_bps"),
                        "slippage_bps": block.get("slippage_bps"),
                        "impact_bps": block.get("impact_bps"),
                        "funding_bps": block.get("funding_bps"),
                        "round_trip_bps": block.get("round_trip_bps"),
                        "components": block.get("components"),
                    }
                )
    return blocks


def recompute(block: dict[str, Any]) -> dict[str, Any]:
    breakdown = CostEngine(scenario_id=block["scenario_id"]).evaluate(
        size_usd=float(block["size_usd"]),
        horizon_minutes=float(block["horizon_minutes"]),
        spread_bps=float(block["spread_bps"]),
        volatility_bps=0.0,
    )
    delta = breakdown.round_trip_bps - float(block["round_trip_bps"])
    return {
        "asset": block["asset"],
        "run": block["run"],
        "size_usd": block["size_usd"],
        "horizon_minutes": block["horizon_minutes"],
        "spread_bps": block["spread_bps"],
        "spread_knowledge": block["spread_knowledge"],
        "recorded_round_trip_bps": block["round_trip_bps"],
        "recomputed_round_trip_bps": breakdown.round_trip_bps,
        "delta_bps": delta,
        "matches": abs(delta) <= TOLERANCE_BPS,
        "fee_component_matches": abs(
            (breakdown.components[0]["value_bps"] + breakdown.components[1]["value_bps"])
            - float(block["fee_bps"])
        )
        <= TOLERANCE_BPS,
    }


def decomposition(engine: CostEngine, *, size_usd: float, horizon_minutes: float, spread_bps: float | None) -> dict[str, Any]:
    breakdown = engine.evaluate(
        size_usd=size_usd, horizon_minutes=horizon_minutes, spread_bps=spread_bps
    )
    total = breakdown.round_trip_bps
    components = []
    for component in breakdown.components:
        components.append(
            {
                **component,
                "share_pct": round(100.0 * component["value_bps"] / total, 4) if total else 0.0,
            }
        )
    known = sum(c["value_bps"] for c in components if c["knowledge"] == "KNOWN")
    observed = sum(c["value_bps"] for c in components if c["knowledge"] == "OBSERVED")
    estimated = sum(c["value_bps"] for c in components if c["knowledge"] == "ESTIMATED")
    assumed = sum(c["value_bps"] for c in components if c["knowledge"] == "ASSUMED")
    return {
        "size_usd": size_usd,
        "horizon_minutes": horizon_minutes,
        "spread_bps_input": breakdown.spread_bps,
        "spread_knowledge": breakdown.spread_knowledge,
        "round_trip_bps": total,
        "components": components,
        "component_names_covered": sorted(c["name"] for c in components),
        "by_knowledge": {
            "KNOWN_bps": round(known, 6),
            "OBSERVED_bps": round(observed, 6),
            "ESTIMATED_bps": round(estimated, 6),
            "ASSUMED_bps": round(assumed, 6),
            "KNOWN_share_pct": round(100.0 * known / total, 4) if total else 0.0,
            "certain_part_exceeds_max_gross_edge": known,
        },
        "stress": {
            multiple: round(total * multiple, 6) for multiple in (1.0, 1.25, 1.5, 2.0)
        },
        "required_gross_edge_bps_1.0x": round(required_gross_edge_bps(total, 1.0), 6),
        "required_gross_edge_bps_1.5x": round(required_gross_edge_bps(total, 1.5), 6),
        "required_gross_edge_bps_2.0x": round(required_gross_edge_bps(total, 2.0), 6),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", default=str(REPO_ROOT / "docs/agentic/economic_audit/WP-ECONOMIC-BLOCKER-001")
    )
    parser.add_argument("--runtime-evidence", default=str(DEFAULT_RUNTIME_EVIDENCE))
    args = parser.parse_args(argv)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    runtime_root = Path(args.runtime_evidence)

    # -- 1. recorded runtime cost, recomputed ------------------------------
    observed_blocks: list[dict[str, Any]] = []
    runtime_status = "NOT_ASSESSED"
    runtime_reason = "byte-identical evidence directory not found"
    if (runtime_root / "raw/runs").is_dir():
        observed_blocks = extract_observed(runtime_root)
        runtime_status = "ASSESSED" if observed_blocks else "NOT_ASSESSED"
        runtime_reason = "" if observed_blocks else "no cost block found in the traces"
    (out_dir / "COST_OBSERVED.json").write_text(
        json.dumps(
            {
                "wp": "WP-ECONOMIC-BLOCKER-001",
                "artefact": "COST_OBSERVED",
                "source_root": runtime_root.as_posix(),
                "source_status": runtime_status,
                "source_note": runtime_reason,
                "block_count": len(observed_blocks),
                "blocks": observed_blocks,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    recomputed = [recompute(b) for b in observed_blocks]
    engine = CostEngine()

    # The runtime used two distinct spread inputs: the symbol's OBSERVED spread
    # and, when the snapshot had none, the model's ESTIMATED default. Report both.
    by_spread_class: dict[str, list[dict[str, Any]]] = {}
    for row in recomputed:
        by_spread_class.setdefault(str(row["spread_knowledge"]), []).append(row)
    spread_summary = {
        klass: {
            "cases": len(rows),
            "assets": sorted({str(r["asset"]) for r in rows}),
            "round_trip_bps_min": round(min(r["recorded_round_trip_bps"] for r in rows), 6),
            "round_trip_bps_max": round(max(r["recorded_round_trip_bps"] for r in rows), 6),
        }
        for klass, rows in sorted(by_spread_class.items())
    }

    # -- 2. published per-asset model, re-derived --------------------------
    v4 = json.loads((REPO_ROOT / V4_RESULTS).read_text(encoding="utf-8"))
    v4_reference = v4.get("reference_intent") or {}
    v4_checks = []
    for market_raw in v4.get("asset_market_inputs") or []:
        market = AssetMarketInput(
            asset=str(market_raw["asset"]),
            symbol=str(market_raw["symbol"]),
            observed_spread_bps=float(market_raw["observed_spread_bps"]),
            spread_observations=int(market_raw["spread_observations"]),
            spread_source=str(market_raw["spread_source"]),
            realized_vol_bps=float(market_raw["realized_vol_bps"]),
            vol_source=str(market_raw["vol_source"]),
        )
        result = asset_cost_v4(
            market,
            size_usd=float(v4_reference.get("size_usd", 1000.0)),
            horizon_minutes=float(v4_reference.get("horizon_minutes", 75.0)),
        )
        published = next(
            (a for a in v4.get("assets") or [] if a.get("asset") == market.asset), {}
        )
        v4_checks.append(
            {
                "asset": market.asset,
                "published_round_trip_bps": published.get("taker_round_trip_bps"),
                "recomputed_round_trip_bps": round(result.taker_round_trip_bps, 6),
                "published_required_gross_bps": published.get("required_gross_edge_bps"),
                "recomputed_required_gross_bps": round(result.required_gross_edge_bps, 6),
                "matches": abs(
                    float(published.get("taker_round_trip_bps") or 0.0)
                    - result.taker_round_trip_bps
                )
                <= 1e-3,
            }
        )

    # -- 3. decomposition, sweep, barrier gap ------------------------------
    reference_observed_spread = 0.0012
    default_spread = VENUE_SPECS[ADMISSION_SCENARIO_ID].default_taker_spread_bps
    observed_case = decomposition(
        engine, size_usd=1000.0, horizon_minutes=5.0, spread_bps=reference_observed_spread
    )
    fallback_case = decomposition(
        engine, size_usd=1000.0, horizon_minutes=5.0, spread_bps=None
    )
    sweep = [
        decomposition(engine, size_usd=size, horizon_minutes=horizon, spread_bps=default_spread)
        for size in (250.0, 1000.0, 5000.0, 25_000.0)
        for horizon in (5.0, 15.0, 60.0, 240.0)
    ]

    v3 = json.loads((REPO_ROOT / V3_RESULTS).read_text(encoding="utf-8"))
    research_barrier = float((v3.get("cost_model") or {}).get("base_rt_bps") or 0.0)
    max_gross = max(
        float(v.get("expected_gross_edge_bps") or 0.0)
        for v in (json.loads(
            (REPO_ROOT / "config/strategy_admission.json").read_text(encoding="utf-8")
        )["strategies"]).values()
    )

    payload = {
        "wp": "WP-ECONOMIC-BLOCKER-001",
        "artefact": "COST_MODEL_AUDIT",
        "model": "COST_MODEL_V3 / COST_MODEL_V4 (research+marginal path); production execution cost model untouched",
        "scenario_id": ADMISSION_SCENARIO_ID,
        "scenario": {
            "venue": VENUE_SPECS[ADMISSION_SCENARIO_ID].venue,
            "product": VENUE_SPECS[ADMISSION_SCENARIO_ID].product,
            "tier": VENUE_SPECS[ADMISSION_SCENARIO_ID].tier,
            "maker_fee_bps": VENUE_SPECS[ADMISSION_SCENARIO_ID].maker_fee_bps,
            "taker_fee_bps": VENUE_SPECS[ADMISSION_SCENARIO_ID].taker_fee_bps,
            "fee_source_id": VENUE_SPECS[ADMISSION_SCENARIO_ID].fee_source_id,
            "default_taker_spread_bps": default_spread,
            "spread_source_id": VENUE_SPECS[ADMISSION_SCENARIO_ID].spread_source_id,
        },
        "component_inventory": {
            "names": list(EXPECTED_COMPONENTS),
            "knowledge": {
                "exchange_fee_entry": "KNOWN (venue schedule, SRC-01)",
                "exchange_fee_exit": "KNOWN (venue schedule, SRC-01)",
                "spread": "OBSERVED when the snapshot carries spread_bps, else ESTIMATED default",
                "slippage": "ESTIMATED (base 1.0 bps x liquidity x size x volatility)",
                "market_impact": "ESTIMATED (size-driven displacement)",
                "adverse_selection": "ASSUMED, maker-only (not charged on a taker round trip)",
                "missed_fill_penalty": "ASSUMED, maker-only",
                "fill_probability_inflation": "ASSUMED, maker-only",
                "funding_carry": "KNOWN = 0 on spot",
            },
        },
        "recorded_runtime_cost": {
            "status": runtime_status,
            "note": runtime_reason,
            "source_root": runtime_root.as_posix(),
            "block_count": len(observed_blocks),
            "all_recomputed_match": bool(recomputed) and all(r["matches"] for r in recomputed),
            "max_abs_delta_bps": max((abs(r["delta_bps"]) for r in recomputed), default=None),
            "by_spread_knowledge": spread_summary,
            "cases": recomputed,
            "reported_range_bps": sorted(
                {round(r["recorded_round_trip_bps"], 4) for r in recomputed}
            ),
        },
        "published_model_v4_recomputed": {
            "source": V4_RESULTS.as_posix(),
            "source_sha256": sha256(REPO_ROOT / V4_RESULTS),
            "all_match": all(c["matches"] for c in v4_checks),
            "assets": v4_checks,
        },
        "decomposition": {
            "observed_spread": observed_case,
            "estimated_spread_fallback": fallback_case,
        },
        "sweep": [
            {
                "size_usd": s["size_usd"],
                "horizon_minutes": s["horizon_minutes"],
                "round_trip_bps": round(s["round_trip_bps"], 6),
                "known_bps": s["by_knowledge"]["KNOWN_bps"],
                "estimated_bps": s["by_knowledge"]["ESTIMATED_bps"],
                "observed_bps": s["by_knowledge"]["OBSERVED_bps"],
            }
            for s in sweep
        ],
        "barrier": {
            "runtime_round_trip_observed_spread_bps": round(observed_case["round_trip_bps"], 6),
            "runtime_round_trip_estimated_spread_bps": round(fallback_case["round_trip_bps"], 6),
            "required_gross_edge_bps_1.0x": observed_case["required_gross_edge_bps_1.0x"],
            "required_gross_edge_bps_1.5x": observed_case["required_gross_edge_bps_1.5x"],
            "research_admission_barrier_bps": research_barrier,
            "research_barrier_gap_bps": round(
                observed_case["round_trip_bps"] - research_barrier, 6
            ),
            "max_measured_gross_edge_bps": max_gross,
            "max_gross_minus_runtime_cost_bps": round(
                max_gross - observed_case["round_trip_bps"], 6
            ),
            "max_gross_minus_known_fees_bps": round(
                max_gross - observed_case["by_knowledge"]["KNOWN_bps"], 6
            ),
            "known_fees_alone_exceed_every_gross_edge": max_gross
            < observed_case["by_knowledge"]["KNOWN_bps"],
            "safety_multiple_used_by_v4": ADMISSION_SAFETY_MULTIPLE,
        },
    }
    path = out_dir / "COST_MODEL_AUDIT.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"[cost] scenario={ADMISSION_SCENARIO_ID} taker={VENUE_SPECS[ADMISSION_SCENARIO_ID].taker_fee_bps}bps/leg")
    print(
        f"[cost] recorded blocks={len(observed_blocks)} all_match="
        f"{payload['recorded_runtime_cost']['all_recomputed_match']} "
        f"range={payload['recorded_runtime_cost']['reported_range_bps']}"
    )
    print(f"[cost] v4 recomputed all_match={payload['published_model_v4_recomputed']['all_match']}")
    print(
        f"[cost] observed-spread rt={observed_case['round_trip_bps']:.4f}bps "
        f"KNOWN share={observed_case['by_knowledge']['KNOWN_share_pct']}%"
    )
    print(
        f"[cost] research barrier={research_barrier} runtime={observed_case['round_trip_bps']:.4f} "
        f"gap={payload['barrier']['research_barrier_gap_bps']}"
    )
    print(
        f"[cost] max gross={max_gross} -> net={payload['barrier']['max_gross_minus_runtime_cost_bps']} "
        f"(minus known fees only: {payload['barrier']['max_gross_minus_known_fees_bps']})"
    )
    print(f"[cost] -> {path}")
    return 0 if payload["recorded_runtime_cost"]["all_recomputed_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
