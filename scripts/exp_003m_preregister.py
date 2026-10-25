"""exp_003m_preregister — freeze EXP-003M before anything is measured.

    ./.venv/Scripts/python.exe scripts/exp_003m_preregister.py

EXP-003M asks one question: does a maker fill model built on the *observed* trade tape of
the same market leave the 5m/mean_reversion candidate with a positive net edge? The
candidate itself is frozen: the 47 signals are read from EXP-003L's sealed ledger, the
limit price is re-derived with this experiment's own arithmetic, and nothing about the
signal, the risk policy, the exits or the costs is allowed to change.

This script writes two files and refuses to overwrite either:

* ``analysis/SIGNALS.json`` — the 47 signals, their reference prices, the limit price for
  every pre-registered offset and the order quantity implied by each limit.
* ``design/DESIGN.json`` — scenarios, gates, fill-model parameters, data plan, provenance
  (commit + digests of every EXP-003L input this experiment rests on).

There is no wall clock in either file: the freeze instant is taken from the commit that
is being measured. Two runs on the same commit must produce byte-identical files, or the
experiment is not reproducible and the caller is told so.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.economic_recovery.alpha15 import cost_for  # noqa: E402

OUT = REPO / "reports" / "ai-bots" / "EXP-003M-MAKER-FILL-REALITY-001"
PREDECESSOR = REPO / "reports" / "ai-bots" / "EXP-003L-EXECUTION-ECONOMICS-001"
DATASET = REPO / "reports" / "ai-bots" / "EXP-003K-CANDIDATE-001" / "dataset"

SCHEMA_DESIGN = "AI_BOTS_003M_DESIGN_V1"
SCHEMA_SIGNALS = "AI_BOTS_003M_SIGNALS_V1"

TIMEFRAME = "5m"
STRATEGY_ID = "mean_reversion"
PARTITION = "research"

#: The pre-registered offset grid, copied from EXP-003L's frozen design. It is repeated
#: here rather than imported so that a change on either side breaks the reproduction
#: check instead of silently moving both experiments together.
OFFSETS_BPS = (0.0, 1.0, 2.0)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"[003m] BLOCKED — git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def provenance() -> dict[str, Any]:
    """Commit, commit instant and the full dirty-path list: no truncated listings.

    The list is complete, not a head of a pipe: ``--porcelain`` is asked for untracked
    files in every directory and the digest is taken over the sorted result, so a list
    that was truncated would change the digest rather than pass unnoticed.
    """

    commit = _git("rev-parse", "HEAD")
    commit_date = _git("show", "-s", "--format=%cI", commit)
    porcelain = _git("status", "--porcelain", "-uall")
    dirty_paths = sorted(line[3:] for line in porcelain.splitlines() if len(line) > 3)
    return {
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "commit": commit,
        "commit_date_utc": commit_date,
        "worktree_dirty": bool(dirty_paths),
        "dirty_path_count": len(dirty_paths),
        "dirty_paths": dirty_paths,
        "dirty_paths_sha256": hashlib.sha256(
            "\n".join(dirty_paths).encode("utf-8")
        ).hexdigest(),
    }


def verify_predecessor_seal(directory: Path = PREDECESSOR) -> dict[str, Any]:
    """EXP-003L must still verify against its own seal before it is quoted.

    A predecessor whose seal does not check out cannot supply signals: silently trusting
    it is how a broken experiment becomes the baseline of the next one.
    """

    seal = directory / "SHA256SUMS.txt"
    if not seal.exists():
        raise SystemExit(f"[003m] BLOCKED — {seal} is missing: EXP-003L is unsealed")
    listed = 0
    mismatched: list[str] = []
    missing: list[str] = []
    for line in seal.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split(maxsplit=1)
        relative = relative.lstrip("*").strip()
        target = directory / relative
        listed += 1
        if not target.exists():
            missing.append(relative)
        elif _sha256(target) != expected:
            mismatched.append(relative)
    return {
        "seal": str(seal.relative_to(REPO)),
        "seal_sha256": _sha256(seal),
        "listed": listed,
        "missing": missing,
        "mismatched": mismatched,
        "ok": not missing and not mismatched and listed > 0,
    }


def price_terms(symbol: str, notional: float) -> dict[str, float]:
    """The lane's cost terms at this notional, from the project's own cost model."""

    terms = cost_for(symbol, stake_usdt=max(notional, 1.0))
    return {
        "half_spread_bps": terms.half_spread_bps,
        "slippage_bps": terms.slippage_bps_per_side,
        "impact_bps": terms.impact_bps_per_side,
        "fee_bps": terms.fee_bps_per_side,
        "price_bps_per_side": terms.half_spread_bps
        + terms.slippage_bps_per_side
        + terms.impact_bps_per_side,
    }


def limit_price(reference: float, side: str, improvement_bps: float) -> float:
    """A post-only limit inside the spread, the same anchor EXP-003L used.

    Buying: the limit sits ``improvement_bps`` below the reference. Selling: above it.
    The resting order improves the price it would have paid as a taker; it does not
    choose a different instant, and this experiment does not let it choose a different
    price either.
    """

    factor = 1.0 + improvement_bps / 10_000.0
    return reference / factor if side == "buy" else reference * factor


def ledger_rows(run_dir: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)["entry"]
        for line in (run_dir / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def build_signals() -> dict[str, Any]:
    run_dir = PREDECESSOR / "runs" / TIMEFRAME / STRATEGY_ID / "real" / PARTITION
    ledger = run_dir / "ledger.jsonl"
    if not ledger.exists():
        raise SystemExit(f"[003m] BLOCKED — {ledger} is missing: no frozen candidate")
    rows = ledger_rows(run_dir)
    fills = [row for row in rows if row.get("kind") == "FILL"]
    closes = {row["position_id"]: row for row in rows if row.get("kind") == "CLOSE"}
    if not fills:
        raise SystemExit("[003m] BLOCKED — the frozen run has no fills")

    signals: list[dict[str, Any]] = []
    for index, fill in enumerate(fills, start=1):
        position_id = str(fill["position_id"])
        close = closes.get(position_id)
        if close is None:
            raise SystemExit(f"[003m] BLOCKED — {position_id} never closed; it has no exit path")
        symbol = str(fill["symbol"])
        side = str(fill["side"])
        notional = float(fill["notional_usdt"])
        reference = float(fill["reference_price"])
        terms = price_terms(symbol, notional)
        improvements = {
            f"{offset:g}": terms["half_spread_bps"] + offset for offset in OFFSETS_BPS
        }
        limits = {
            offset: limit_price(reference, side, improvement)
            for offset, improvement in improvements.items()
        }
        decision_ms = int(fill["quote_ts_ms"])
        signals.append(
            {
                "index": index,
                "position_id": position_id,
                "symbol": symbol,
                "side": side,
                "notional_usdt": notional,
                "reference_price": reference,
                "decision_ts_ms": decision_ms,
                "half_spread_bps": terms["half_spread_bps"],
                "improvement_bps": improvements,
                "limit_price": limits,
                "order_qty": {offset: notional / price for offset, price in limits.items()},
                "ledger_exit_reason": close.get("exit_reason"),
                "ledger_exit_ts_ms": int(close["ts_ms"]) if close.get("ts_ms") else None,
                "ledger_net_usdt": float(close["pnl_net_usdt"]),
                "ledger_minutes_held": float(close.get("minutes_held") or 0.0),
            }
        )

    metrics = _read_json(run_dir / "METRICS.json")
    return {
        "schema_version": SCHEMA_SIGNALS,
        "experiment": "EXP-003M-MAKER-FILL-REALITY-001",
        "candidate": {
            "experiment": "EXP-003L-EXECUTION-ECONOMICS-001",
            "run": str(run_dir.relative_to(REPO)).replace("\\", "/"),
            "timeframe": TIMEFRAME,
            "strategy_id": STRATEGY_ID,
            "partition": PARTITION,
            "signals": len(signals),
            "ledger_sha256": _sha256(ledger),
            "ledger_bytes": ledger.stat().st_size,
            "ledger_closes": int(metrics["closes"]),
            "ledger_net_pnl_usdt": float(metrics["net_pnl_usdt"]),
            "ledger_net_per_signal_usdt": float(metrics["expectancy_usdt"]),
            "strategy_version": metrics.get("strategy_version"),
            "decision_every_bars": metrics.get("decision_every_bars"),
            "interval_ms": metrics.get("interval_ms"),
        },
        "signals": signals,
    }


def runtime_config() -> dict[str, Any]:
    """The runtime configuration this experiment rests on, fingerprinted.

    The stop and target levels, the mode and the live flag are not this experiment's to
    choose: they come from ``config/``. Recording their digests is what lets the verifier
    notice that the configuration moved under the numbers.
    """

    import yaml

    risk = yaml.safe_load((REPO / "config" / "risk.yaml").read_text(encoding="utf-8"))
    runtime = yaml.safe_load((REPO / "config" / "runtime.yaml").read_text(encoding="utf-8"))
    risk_block = risk.get("risk") or risk
    runtime_block = runtime.get("runtime") or {}
    return {
        "files": {
            name: _sha256(REPO / "config" / name)
            for name in ("risk.yaml", "runtime.yaml", "vision.yaml")
        },
        "risk": {
            "default_stop_loss_pct": float(risk_block["default_stop_loss_pct"]),
            "default_take_profit_pct": float(risk_block["default_take_profit_pct"]),
            "max_order_notional_usdt": float(risk_block["max_order_notional_usdt"]),
            "max_open_positions": int(risk_block.get("max_open_positions", 0)),
        },
        "runtime": {
            "mode": str(runtime_block.get("mode")),
            "live_trading_enabled": bool(runtime_block.get("live_trading_enabled")),
        },
    }


def build_design(*, signals_doc: dict[str, Any], seal: dict[str, Any], prov: dict[str, Any]) -> dict[str, Any]:
    """The frozen plan. Scenarios, gates and fill parameters are decided here, once."""

    dataset = {
        symbol: {
            "file": f"{symbol}.1m.jsonl.gz",
            "sha256": _sha256(DATASET / f"{symbol}.1m.jsonl.gz"),
        }
        for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    }
    kline_bars = {
        symbol: {
            "bars": 86400,
            "first_open_utc": "2026-06-21T00:00:00Z",
            "last_open_utc": "2026-08-19T23:59:00Z",
        }
        for symbol in dataset
    }
    predecessor_inputs = {
        "design/DESIGN.json": PREDECESSOR / "design" / "DESIGN.json",
        "design/FEE_SCHEDULE.json": PREDECESSOR / "design" / "FEE_SCHEDULE.json",
        "analysis/execution/5m__mean_reversion.json": PREDECESSOR
        / "analysis"
        / "execution"
        / "5m__mean_reversion.json",
        "analysis/METRICS.json": PREDECESSOR / "analysis" / "METRICS.json",
        "analysis/CANDIDATE_SELECTION.json": PREDECESSOR / "analysis" / "CANDIDATE_SELECTION.json",
    }
    return {
        "schema_version": SCHEMA_DESIGN,
        "experiment": "EXP-003M-MAKER-FILL-REALITY-001",
        "question": (
            "Does a maker fill model built on the observed spot trade tape leave the frozen "
            "5m/mean_reversion candidate a positive net edge, or does EXP-003L's touch-to-fill "
            "assumption carry the result?"
        ),
        "provenance": {
            key: prov[key]
            for key in (
                "branch",
                "commit",
                "commit_date_utc",
                "worktree_dirty",
                "dirty_path_count",
                "dirty_paths_sha256",
            )
        },
        "candidate": signals_doc["candidate"],
        "predecessor": {
            "experiment": "EXP-003L-EXECUTION-ECONOMICS-001",
            "seal": seal,
            "inputs": {
                name: {"sha256": _sha256(path), "bytes": path.stat().st_size}
                for name, path in predecessor_inputs.items()
            },
            "reproduction_target": {
                "scenario": "maker_resting__spot_vip0_bnb__h15__o0",
                "fill_rate": 0.93617,
                "net_per_signal_usdt": -0.45225547,
                "net_per_fill_usdt": -0.48309107,
                "gross_per_fill_usdt": 0.26690893,
                "note": "published by EXP-003L; EXP-003M must restate it before it may price anything",
            },
        },
        "dataset": {
            "source": "reports/ai-bots/EXP-003K-CANDIDATE-001/dataset",
            "symbols": dataset,
            "bars": kline_bars,
            "fetched_by": "scripts/exp_003j_dataset.py --fetch against Binance spot /api/v3/klines",
        },
        "runtime_config": runtime_config(),
        "holdout": {
            "start_utc": "2026-08-06T00:00:00Z",
            "end_utc": "2026-08-20T00:00:00Z",
            "status": "CLOSED",
            "rule": (
                "no tape, klines or derived statistic for this window may be downloaded, "
                "stored or summarised in this experiment; the verifier fails if any file "
                "under dataset/ or analysis/ covers it"
            ),
        },
        "market_data_plan": {
            "tape_source": "https://data.binance.vision/data/spot/daily/aggTrades/{symbol}/{symbol}-aggTrades-{day}.zip",
            "klines_source": "https://data.binance.vision/data/spot/daily/klines/{symbol}/1m/{symbol}-1m-{day}.zip",
            "depth_source": "https://data.binance.vision/data/futures/um/daily/bookDepth/{symbol}/{symbol}-bookDepth-{day}.zip",
            "depth_role": (
                "CALIBRATION ONLY. USD-M futures band depth is a different venue and a "
                "different instrument; it is used to size the queue assumption, never to "
                "declare a spot fill."
            ),
            "book_source": (
                "NONE. data.binance.vision publishes aggTrades, trades and klines for spot: "
                "there is no historical spot L2 book. No book is synthesised, and no depth "
                "figure from another venue is presented as a spot book."
            ),
            "window_before_ms": 60_000,
            "window_after_ms": 960_000,
            "selection_rule": (
                "every (symbol, UTC day) that contains at least one pre-registered signal, and "
                "inside it every trade in [decision-60 s, decision+16 min] for those signals. "
                "No filter on price, side or outcome; missed signals are impossible to hide"
            ),
            "credential_used": False,
            "live_orders": False,
        },
        "fill_model": {
            "anchor": "reference_price (the bar open the taker paid), same instant as EXP-003L",
            "limit_rule": "buy: reference/(1+improvement/1e4); sell: reference*(1+improvement/1e4)",
            "improvement": "half_spread_bps (per symbol, from the lane's cost model) + offset_bps",
            "queue_model": (
                "queue ahead of us at the limit is unobservable without an L2 feed. It is a "
                "declared multiple q of our own order quantity; fill fraction is "
                "clamp((aggressor_volume_at_or_through_limit - q*order_qty)/order_qty, 0, 1) "
                "measured from placement (decision + latency) to decision + horizon"
            ),
            "aggressor_side": {
                "buy": "trades with is_buyer_maker true (seller aggressed) at price <= limit",
                "sell": "trades with is_buyer_maker false (buyer aggressed) at price >= limit",
            },
            "partial_fills": "linear: net = fill_fraction * net_of_full_fill, fees included",
            "exit_rules": (
                "unchanged from EXP-003L and from the lane: stop 0.50 %, target 0.75 % off the "
                "fill price, stop_first inside a minute, exits adjudicated from the minute after "
                "the fill minute"
            ),
            "unobservable": [
                "displayed depth at the touch (no spot L2 published)",
                "our queue position when we join",
                "whether a trade at our price actually matched our order",
                "cancel/replace traffic that would have moved us up the queue",
            ],
            "evidence_class": "ESTIMATED_FROM_OBSERVED_TRADE_TAPE",
        },
        "scenarios": {
            "F0_touch_full": {
                "kind": "FILL_UPPER_BOUND",
                "queue_multiple": 0.0,
                "latency_ms": 0,
                "horizon_minutes": 15,
                "offset_bps": 0.0,
                "fee_schedule": "spot_vip0_bnb",
                "note": "EXP-003L's assumption: any touch fills us fully at the limit",
            },
            "F1_tape_base": {
                "kind": "ESTIMATED",
                "queue_multiple": 1.0,
                "latency_ms": 400,
                "horizon_minutes": 15,
                "offset_bps": 0.0,
                "fee_schedule": "spot_vip0_bnb",
                "note": "one order of queue ahead of us, 400 ms to reach the venue",
            },
            "F2_tape_pessimistic": {
                "kind": "ESTIMATED",
                "queue_multiple": 4.0,
                "latency_ms": 2000,
                "horizon_minutes": 5,
                "offset_bps": 2.0,
                "fee_schedule": "spot_vip0",
                "note": "four orders of queue, 2 s latency, 5 min horizon, 2 bp offset: the corner EXP-003L gated on",
            },
            "F3_tape_no_queue": {
                "kind": "TAPE_UPPER_BOUND",
                "queue_multiple": 0.0,
                "latency_ms": 400,
                "horizon_minutes": 15,
                "offset_bps": 0.0,
                "fee_schedule": "spot_vip0_bnb",
                "note": "queue ignored: what the tape alone allows. Brackets F0",
            },
        },
        "sensitivity": {
            "queue_multiple": [0.0, 0.25, 0.5, 1.0, 2.0, 4.0, 10.0, 100.0],
            "latency_ms": [0, 400, 2000],
            "horizon_minutes": 15,
            "offset_bps": 0.0,
            "fee_schedule": "spot_vip0_bnb",
            "note": (
                "queue is unobservable, so it is swept instead of asserted. Every point uses "
                "the same signals, tape, exits and fee schedule"
            ),
        },
        "fee_schedules": {
            "spot_vip0": {"maker_bps": 10.0, "taker_bps": 10.0},
            "spot_vip0_bnb": {"maker_bps": 7.5, "taker_bps": 7.5},
            "futures_vip0": {
                "maker_bps": 2.0,
                "taker_bps": 5.0,
                "note": "NOT EXECUTABLE BY THIS SPOT LANE: a bound, never a plan",
            },
        },
        "economics": {
            "equity_usdt": 10000.0,
            "notional_usdt": 500.0,
            "bootstrap": {
                "method": "moving block, 5-day blocks",
                "resamples": 10000,
                "seed": 20261020,
                "alpha": 0.05,
                "unit": "net PnL per signal (misses count as zero)",
            },
            "halves": "the research window split at its midpoint; both halves must be positive",
        },
        "gates": {
            "G1_reproduces_003l": (
                "F0_touch_full must restate EXP-003L's published maker_resting__spot_vip0_bnb__h15__o0 "
                "fill rate and net/fill to 1e-8, or this experiment is BLOCKED"
            ),
            "G2_dataset_provenance": (
                "the frozen 1-minute bars must match an independent download of the same minutes "
                "from data.binance.vision klines (open, high, low, close)"
            ),
            "G3_tape_integrity": (
                "every tape file must be monotonic in agg_trade_id and time, inside its UTC day, "
                "free of non-positive prices/quantities, and re-hash to its manifest digest"
            ),
            "G4_economics_pessimistic": (
                "F2 net per signal > 0, net per fill > 0 and the 95 % CI lower bound > 0"
            ),
            "G5_optimistic_ceiling": (
                "F0 (every touch fills fully at the improved price) must be net per fill > 0. If "
                "the most generous fill model already loses, fill realism cannot rescue it and no "
                "promotion may cite a better fill rate"
            ),
            "G6_holdout_closed": "no dataset or analysis file covers 2026-08-06 → 2026-08-20",
            "G7_evidence_class": (
                "no live order was placed, so fills are ESTIMATED. Even if G4 and G5 passed, the "
                "ceiling would be INSUFFICIENT_EVIDENCE, never a paper promotion"
            ),
            "G8_no_live_trading": (
                "config/runtime.yaml still declares mode paper with live_trading_enabled false, and "
                "every ledger read reports zero live orders"
            ),
            "G9_config_unchanged": (
                "config/risk.yaml, config/runtime.yaml and config/vision.yaml still hash to the "
                "digests frozen here: the stop/target levels and the fee terms are not this "
                "experiment's to move after the fact"
            ),
        },
        "decision_rule": {
            "REJECT": "G4 or G5 fails on a sample of at least 40 signals",
            "INSUFFICIENT_EVIDENCE": (
                "G4 and G5 pass but the fill evidence class is ESTIMATED, or G1/G2/G3 cannot be "
                "established"
            ),
            "PROMOTE": "impossible in this experiment: it needs observed live fills and a forward window",
            "thresholds_are_not_relaxed": True,
        },
        "prohibitions": [
            "opening the holdout 2026-08-06 → 2026-08-20",
            "modifying the signal, the risk policy, the exits or the fee schedules",
            "presenting an estimate as an observed fill",
            "using another venue's book as a spot book",
            "live orders, private credentials or any move of funds",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--force", action="store_true", help="refreeze (destroys the previous design)")
    args = parser.parse_args(argv)

    out = Path(args.out)
    design_path = out / "design" / "DESIGN.json"
    signals_path = out / "analysis" / "SIGNALS.json"
    if design_path.exists() and not args.force:
        print(f"[003m] design already frozen: {design_path} (--force to refreeze)")
        return 0

    seal = verify_predecessor_seal()
    if not seal["ok"]:
        raise SystemExit(
            f"[003m] BLOCKED — EXP-003L does not verify against its seal: "
            f"missing={seal['missing']} mismatched={seal['mismatched']}"
        )
    prov = provenance()
    signals_doc = build_signals()
    design = build_design(signals_doc=signals_doc, seal=seal, prov=prov)

    _write_json(signals_path, signals_doc)
    _write_json(design_path, design)
    _write_json(
        out / "analysis" / "PROVENANCE.json",
        {
            "schema_version": "AI_BOTS_003M_PROVENANCE_V1",
            "experiment": "EXP-003M-MAKER-FILL-REALITY-001",
            **prov,
            "live_enabled": False,
            "credentials_used": False,
            "predecessor_seal": seal,
        },
    )
    print(
        f"[003m] frozen: {len(signals_doc['signals'])} signals, commit {prov['commit'][:10]}, "
        f"003L seal {seal['listed']} files OK"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
