"""RFC-021 Part A — ledger PIT remediation, adversarial poisoning, re-baseline.

Builds a walk-forward admission ledger from the per-trade outcome CSVs, proves
that poisoning every outcome AFTER ``T`` leaves every decision at ``<= T``
unchanged (§9), and re-executes the frozen step=60 baseline with the corrected
ledger (§10).

Usage:
    python scripts/rfc021_ledger_pit.py --out-dir reports/rfc021
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.autonomous.admission_ledger import AdmissionLedger  # noqa: E402
from trading_bot.autonomous.pit_ledger import PitAdmissionLedger  # noqa: E402

DATA = REPO / "reports" / "strategy-baseline" / "data"
TRADES = REPO / "reports" / "strategy-baseline"
FAMILIES = ("breakout", "ema_crossover", "mean_reversion", "momentum", "trend", "volatility")
MIN_SAMPLE = 30
TF_MS = {"5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000}


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


def load_outcomes() -> tuple[dict[str, list[tuple[int, float]]], dict[str, str]]:
    """strategy_id -> [(exit_ts_ms, gross_bps)], + {file: sha256} provenance."""
    import csv

    outcomes: dict[str, list[tuple[int, float]]] = {}
    hashes: dict[str, str] = {}
    for path in sorted(TRADES.glob("TRADES_*.csv")):
        stem = path.stem[len("TRADES_") :]
        if stem == "DISCOVERY":
            continue
        tf = "5m"
        family = stem
        for suf, t in (("_15m", "15m"), ("_30m", "30m"), ("_1h", "1h")):
            if stem.endswith(suf):
                family, tf = stem[: -len(suf)], t
                break
        if family not in FAMILIES:
            continue
        strategy_id = f"{family}@{tf}"
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        rows: list[tuple[int, float]] = []
        with path.open(encoding="utf-8") as fh:
            for rec in csv.DictReader(fh):
                if str(rec.get("scenario", "BASE")) != "BASE":
                    continue
                try:
                    rows.append((int(rec["exit_ts"]), float(rec["gross"])))
                except (KeyError, ValueError):
                    continue
        outcomes.setdefault(strategy_id, []).extend(rows)
    return outcomes, hashes


def poison_after(
    outcomes: dict[str, list[tuple[int, float]]], t_ms: int, factor: float = -5.0
) -> dict[str, list[tuple[int, float]]]:
    return {
        sid: [(ts, g * factor if ts > t_ms else g) for ts, g in rows]
        for sid, rows in outcomes.items()
    }


def build_runtime(
    *,
    ledger: Any,
    strategy_map: dict[str, dict[str, Any]],
    bars: dict[str, list[Any]],
    clock: Any,
    run_dir: Path,
    assets: list[str],
    timeframe: str,
) -> Any:
    from trading_bot.autonomous.runtime import AutonomousPaperRuntime
    from trading_bot.config.settings import load_settings
    from trading_bot.config.universe import PairSpec
    from trading_bot.paper.broker import PaperBroker
    from trading_bot.paper.snapshot_history import FetcherBarReader
    from trading_bot.research.families import (
        BreakoutFamily,
        EmaCrossoverFamily,
        MeanReversionFamily,
        MomentumFamily,
        TrendFamily,
        VolatilityFamily,
    )
    from trading_bot.risk.manager import RiskManager
    from trading_bot.scanner.mode_filters import build_filter_set_per_mode
    from trading_bot.scanner.scanner import UniverseScanner

    settings = load_settings(config_dir="config/realdata")
    pairs = [PairSpec(symbol=f"{a}/USDT", enabled=True) for a in assets]
    universe = settings.universe.model_copy(update={"pairs": pairs, "timeframes": [timeframe]})
    settings = settings.model_copy(update={"universe": universe})
    source = H.ReplayMarketSource(bars, clock, spread_bps=1.0)

    def scanner_factory() -> Any:
        scan_settings = settings.model_copy(
            update={"risk": settings.risk.model_copy(update={"kill_switch_enabled": False})}
        )
        return UniverseScanner(
            source=source,
            registry_per_mode=build_filter_set_per_mode(scan_settings),
            settings=scan_settings,
        )

    reader = FetcherBarReader(source, timeframe=timeframe)
    broker = PaperBroker(equity=10_000.0)
    risk = RiskManager(risk=settings.risk, equity=10_000.0, _clock=clock.seconds)
    families = {
        "ema_crossover": EmaCrossoverFamily(),
        "momentum": MomentumFamily(),
        "breakout": BreakoutFamily(),
        "trend": TrendFamily(),
        "mean_reversion": MeanReversionFamily(),
        "volatility": VolatilityFamily(),
    }
    return AutonomousPaperRuntime(
        settings=settings,
        scanner_factory=scanner_factory,
        history_reader=reader,
        broker=broker,
        risk_manager=risk,
        families=families,
        strategy_map=strategy_map,
        ledger=ledger,
        run_dir=run_dir,
        assets=assets,
        timeframe=timeframe,
        size_usd=1_000.0,
        lookback_bars=120,
        shadow_evaluation_enabled=True,
        environment="rfc021-pit-replay",
        now_fn=clock,
        routing_mode="LEGACY",
    )


def projection(run_dir: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for line in (run_dir / "traces.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        prop = row.get("proposal") or {}
        out[f"{row.get('decision_time_ms')}|{row.get('asset')}"] = {
            "decision_time_ms": row.get("decision_time_ms"),
            "mode": row.get("mode"),
            "classification": row.get("classification"),
            "no_trade_kind": row.get("no_trade_kind"),
            "regime": row.get("regime"),
            "strategy": prop.get("strategy_id"),
            "gross": prop.get("expected_gross_edge_bps"),
            "cost": prop.get("expected_cost_bps"),
            "net": prop.get("expected_net_edge_bps"),
            "order_created": row.get("order_created"),
        }
    return out


async def run_pit(*, run_id: str, ledger: Any, bars: dict[str, list[Any]], instants: list[int],
                  strategy_map: dict[str, dict[str, Any]], assets: list[str], timeframe: str) -> dict[str, Any]:
    run_dir = REPO / "reports" / "rfc010" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    for name in ("traces.jsonl", "outcomes.jsonl", "performance.json"):
        p = run_dir / name
        if p.exists():
            p.unlink()
    clock = H.ReplayClock(instants[0])
    runtime = build_runtime(
        ledger=ledger, strategy_map=strategy_map, bars=bars, clock=clock, run_dir=run_dir,
        assets=assets, timeframe=timeframe,
    )
    ledger_states: dict[int, str] = {}
    cycles: list[Any] = []
    errors: list[str] = []
    for i, instant in enumerate(instants, start=1):
        clock.now_ms = instant
        ledger.advance_to(instant)
        snap = {sid: ledger.expected_gross_edge_bps(sid) for sid in ledger.strategy_ids()}
        ledger_states[instant] = hashlib.sha256(
            json.dumps(snap, sort_keys=True).encode()
        ).hexdigest()
        try:
            cycles.append(await runtime.run_cycle(cycle=i))
        except Exception as exc:  # pragma: no cover - visible failure
            errors.append(f"cycle {i}: {type(exc).__name__}: {exc}")
    summary = runtime.finalize_summary(
        run_id=run_id, started_at_ms=instants[0], cycle_reports=cycles, errors=errors
    )
    broker = runtime._broker
    return {
        "run_id": run_id,
        "decision_instants": len(instants),
        "cycles_completed": len(cycles),
        "cycles_failed": len(errors),
        "totals": summary.totals(),
        "final_equity": broker.equity,
        "closed_trades": len(broker.closed_trades),
        "ledger_states": ledger_states,
        "projection": projection(run_dir),
    }


async def main_async(args: argparse.Namespace) -> dict[str, Any]:
    outcomes, hashes = load_outcomes()
    base = AdmissionLedger.load(REPO / "config" / "strategy_admission.json")
    assets = ["BTC", "ETH", "SOL"]
    timeframe = "5m"
    interval_ms = TF_MS[timeframe]
    bars_all = H.load_bars(assets, ["W1", "W2", "W3", "W4"])
    stamps = sorted({b.timestamp for bars in bars_all.values() for b in bars})
    instants = [
        t + interval_ms for i, t in enumerate(stamps) if i % 60 == 0
    ]
    t_end = instants[-1]

    # strategy universe from the base ledger (stable set), PIT ledger drives edges
    from trading_bot.autonomous.strategy_state import StrategyRegistry

    registry = StrategyRegistry.from_ledger(base, assets=assets)
    strategy_map = registry.strategy_map(timeframe)

    # RUN A — real outcomes
    ledger_a = PitAdmissionLedger(base, outcomes, min_sample=MIN_SAMPLE)
    run_a = await run_pit(
        run_id="RFC021-PIT-A", ledger=ledger_a, bars=bars_all, instants=instants,
        strategy_map=strategy_map, assets=assets, timeframe=timeframe,
    )

    # RUN B — every outcome AFTER T poisoned
    ledger_b = PitAdmissionLedger(
        base, poison_after(outcomes, t_end), min_sample=MIN_SAMPLE
    )
    run_b = await run_pit(
        run_id="RFC021-PIT-B", ledger=ledger_b, bars=bars_all, instants=instants,
        strategy_map=strategy_map, assets=assets, timeframe=timeframe,
    )

    # adversarial comparison for decisions <= T
    proj_a, proj_b = run_a["projection"], run_b["projection"]
    mismatches = [k for k, v in proj_a.items() if proj_b.get(k) != v]
    ledger_state_mismatch = [
        ts for ts, h in run_a["ledger_states"].items() if run_b["ledger_states"].get(ts) != h
    ]

    # RFC-010B comparison
    ref = json.loads((REPO / "reports" / "rfc010" / "baseline_dev.json").read_text(encoding="utf-8"))
    keys = ("asset_cycle_evaluations", "shadow_trades", "paper_trades", "orders_created")
    baseline_compare = {
        k: {"rfc021_pit": run_a["totals"].get(k), "rfc010b": ref["totals"].get(k)}
        for k in keys
    }

    edge_samples = {
        sid: ledger_a.observables(sid) for sid in ("mean_reversion@5m", "momentum@5m", "trend@5m")
    }

    return {
        "schema": "rfc021.ledger_pit_remediation.v1",
        "min_sample": MIN_SAMPLE,
        "outcome_files": hashes,
        "strategies_with_outcomes": sorted(outcomes),
        "outcome_rows": sum(len(v) for v in outcomes.values()),
        "T_end_ms": t_end,
        "run_a": {k: run_a[k] for k in ("decision_instants", "cycles_completed", "cycles_failed",
                                        "totals", "final_equity", "closed_trades")},
        "run_b": {k: run_b[k] for k in ("totals",)},
        "poisoning": {
            "decisions_compared": len(proj_a),
            "decision_mismatches": len(mismatches),
            "mismatch_samples": mismatches[:5],
            "ledger_state_mismatches": len(ledger_state_mismatch),
            "PASS": len(mismatches) == 0 and len(ledger_state_mismatch) == 0
            and set(proj_a) == set(proj_b),
        },
        "baseline_compare": baseline_compare,
        "edge_as_of_samples": edge_samples,
        "final_edge_snapshot": {
            sid: ledger_a.expected_gross_edge_bps(sid) for sid in ("mean_reversion@5m", "momentum@5m")
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", default="reports/rfc021")
    args = ap.parse_args()
    report = asyncio.run(main_async(args))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "LEDGER_PIT_REMEDIATION.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    poisoning = {
        "schema": "rfc021.ledger_future_poisoning.v1",
        "T_end_ms": report["T_end_ms"],
        **report["poisoning"],
    }
    (out / "LEDGER_FUTURE_POISONING.json").write_text(
        json.dumps(poisoning, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "strategies_with_outcomes": len(report["strategies_with_outcomes"]),
        "outcome_rows": report["outcome_rows"],
        "poisoning": report["poisoning"]["PASS"],
        "run_a_totals": report["run_a"]["totals"],
        "baseline_compare": report["baseline_compare"],
    }, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
