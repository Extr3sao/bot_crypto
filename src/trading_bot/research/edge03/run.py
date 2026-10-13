"""EDGE-03 run — ingest the new bars, read the frozen rulesets, check parity, report.

One function runs the whole lane, and it is the same function the tests drive with a
scripted source: a pipeline that only works from a shell is a pipeline nobody can pin.

The order is deliberate:

1. **the frozen corpora are re-read and must not have moved** (``assert_frozen_corpus``),
   **and the ruleset digest is re-derived and must equal the one the campaign published**
   (``assert_frozen_params``);
2. **the forward store grows** by the bars that closed since the last run, per series,
   with an explicit ``no_new_data`` result when there was nothing to add;
3. **a second ingest at the same instant proves restart safety**: it must append nothing
   and leave every store digest identical;
4. **the shadow** walks the frozen arms over the forward window;
5. **risk parity** feeds both risk engines the same state and intent;
6. **the reports** are written from the artefacts, not from prose.

Nothing in this module talks to an exchange. ``source`` is the only network seam and it is
injected, which is what lets the tests run offline and deterministic.
"""

from __future__ import annotations

import hashlib
import json
import logging
import statistics
import time
from pathlib import Path
from typing import Any

from trading_bot.research.edge01.data import ASSETS, BAR_MS

from . import forward_plan as FP
from .ingest import (
    BinancePublicKlines,
    ForwardStore,
    IngestLedger,
    audit_series,
    default_store_root,
    ingest_series,
    observation_days,
    store_manifest,
)
from .parity import run_parity
from .reporting import observation_verdict, write_observability
from .shadow import run_shadow

__all__ = [
    "FORWARD_SERIES",
    "quiet_runtime_logs",
    "run_forward_observation",
    "write_forward_artifacts",
]

#: (timeframe, symbol): the 1h series feed the 4h/1d arms and the intraday context; the 15m
#: series feed the intraday arms. Both are ingested for every asset the corpus covers.
FORWARD_SERIES: tuple[tuple[str, str], ...] = tuple(
    (timeframe, asset) for timeframe in ("1h", "15m") for asset in ASSETS
)

FROZEN_END: dict[str, int] = {"1h": FP.FROZEN_1H_END_MS, "15m": FP.FROZEN_15M_END_MS}


def quiet_runtime_logs() -> None:
    """Silence the runtime engine's own INFO logging while it is driven in a loop.

    The engine logs every approval through structlog. Driving it a few hundred times in a
    parity sweep is exactly what this lane does, and the log lines are not evidence — the
    decision rows are. Suppressing them keeps the run's own output readable.
    """
    import structlog

    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL),
        cache_logger_on_first_use=False,
    )


def _lag_seconds(rows: list[dict[str, Any]], *, timeframe: str) -> list[float]:
    """Bar close → store, in seconds, for every row that carries its fetch instant."""
    return [
        (int(row["fetched_at_ms"]) - (int(row["ts"]) + BAR_MS[timeframe])) / 1000.0
        for row in rows
        if row.get("fetched_at_ms") is not None
    ]


def _lag_stats(lag: list[float]) -> dict[str, Any]:
    if not lag:
        return {"samples": 0, "min_seconds": None, "median_seconds": None, "max_seconds": None}
    return {
        "samples": len(lag),
        "min_seconds": round(min(lag), 3),
        "median_seconds": round(statistics.median(lag), 3),
        "max_seconds": round(max(lag), 3),
    }


def _latency(
    rows: list[dict[str, Any]], *, timeframe: str, fetched_at_ms: int | None = None
) -> dict[str, Any]:
    """Bar-close → store, in seconds: what the ingestion path costs end to end.

    Two readings, deliberately kept apart. The window figures cover every bar the store
    holds, which on a first run is one long BACKFILL: a bar from March is "late" by months,
    and that is an artefact of when this lane started, not a property of the feed. The
    ``fresh_*`` figures cover only the bars stamped with THIS run's fetch instant — exactly
    the bars this run appended — and that is the lag a scheduled reader actually meets.
    """
    window = _lag_stats(_lag_seconds(rows, timeframe=timeframe))
    fresh_rows = (
        [row for row in rows if row.get("fetched_at_ms") == fetched_at_ms]
        if fetched_at_ms is not None
        else []
    )
    fresh = _lag_stats(_lag_seconds(fresh_rows, timeframe=timeframe))
    return {
        **window,
        "fetch_instants": len(
            {row.get("fetched_at_ms") for row in rows if row.get("fetched_at_ms")}
        ),
        "fetch_instant_ms": fetched_at_ms,
        "fresh_bars": len(fresh_rows),
        "fresh_samples": fresh["samples"],
        "fresh_min_seconds": fresh["min_seconds"],
        "fresh_median_seconds": fresh["median_seconds"],
        "fresh_max_seconds": fresh["max_seconds"],
        "note": (
            "window = every stored bar (a first run backfills, so this figure is not a feed "
            "latency); fresh = the bars this run pulled, measured close → store"
        ),
    }


def default_ledger_dir(repo_root: Path) -> Path:
    """Where the ingest ledger of the WP-EDGE-03 observation is published.

    Named here, not inlined, because the unattended tick of WP-EDGE-04 points at its own
    ledger root: two writers appending to one log would make a reader unable to tell which
    observation a row belongs to.
    """
    return Path(repo_root) / "reports" / "edge-recovery" / "WP-EDGE-03" / "forward-observation"


def _relative_to(path: Path, root: Path) -> str:
    """A repo-relative posix path, or the absolute one when it lives outside the repo."""
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _observation_total(observation: dict[str, Any], *, assets: tuple[str, ...]) -> dict[str, Any]:
    """Independent observation days, counted on the assets the primary arm trades.

    A day counts only if EVERY primary asset was observed densely on it: the trend book is
    a portfolio, so a day where one asset's feed was half missing is not a day the
    portfolio could have been observed.
    """
    per_asset: dict[str, set[str]] = {}
    for asset in assets:
        key = f"1h:{asset}"
        per_asset[asset] = set(observation.get(key, {}).get("days") or [])
    common = set.intersection(*per_asset.values()) if per_asset else set()
    return {
        "per_asset": {asset: len(days) for asset, days in per_asset.items()},
        "common_days": len(common),
        "days": sorted(common),
        "rule": "a day counts only if every primary asset met the declared coverage on it",
    }


def _arm_summary(payload: dict[str, Any], *, detail_cap: int = 20_000) -> dict[str, Any]:
    """The report-facing view of one arm: metrics, funnel and the rows behind them."""
    if payload.get("status") == "no_forward_bars":
        return {
            "status": "no_forward_bars",
            "reason": payload.get("reason"),
            "timeframe": payload.get("timeframe"),
            "scenario": payload.get("scenario"),
            "metrics": {"trades": 0, "net_usdt": 0.0},
            "signal_count": 0,
            "refusal_mix": {},
        }
    return {
        "status": "observed",
        "arm": payload["arm"],
        "timeframe": payload["timeframe"],
        "scenario": payload["scenario"],
        "plane": payload["plane"],
        "window_start_ts": payload["window_start_ts"],
        "window_end_ts": payload["window_end_ts"],
        "window_bars": payload["window_bars"],
        "bars_seen": payload["bars_seen"],
        "metrics": payload["metrics"],
        "signal_count": payload["signal_count"],
        "order_count": payload["order_count"],
        "refusal_mix": payload["refusal_mix"],
        "candidate_bars_evaluated": payload.get("candidate_bars_evaluated"),
        "candidate_warmup_bars": payload.get("candidate_warmup_bars"),
        "signals_detail": payload["signals"][:detail_cap],
        "trades_detail": payload["trades"][:detail_cap],
        "refusals_detail": payload["refusals"][:detail_cap],
        "orders_detail": payload["orders"][:detail_cap],
    }


def _decisions_digest(decisions: list[dict[str, Any]]) -> str:
    """A digest of the captured decisions, so a second run can be compared byte for byte."""
    digest = hashlib.sha256()
    for row in decisions:
        digest.update(json.dumps(row, sort_keys=True).encode("utf-8"))
    return digest.hexdigest()


def run_forward_observation(
    *,
    repo_root: Path,
    source: Any = None,
    observed_at_ms: int | None = None,
    scenarios: tuple[str, ...] = ("BASE", "2X_FEES", "ADVERSE"),
    sweep_cases: int = 384,
    shadow_case_limit: int | None = 600,
    store_root: Path | None = None,
    ledger_dir: Path | None = None,
    quiet: bool = True,
) -> dict[str, Any]:
    """The whole lane, from the frozen corpora to the observation payload.

    ``store_root`` is the one seam a rehearsal needs: pointing it elsewhere keeps a
    synthetic run out of the published store, which is the only way a rehearsal can be
    harmless to the evidence.

    ``ledger_dir`` is the same seam for the ingest record: left out, the rows go to the
    ledger WP-EDGE-03 published; the unattended tick of WP-EDGE-04 passes its own root so
    its rows never interleave with the observation the earlier work package published.
    """
    if quiet:
        quiet_runtime_logs()
    repo_root = Path(repo_root)
    store = ForwardStore(Path(store_root) if store_root is not None else default_store_root(repo_root))
    ledger_dir = Path(ledger_dir) if ledger_dir is not None else default_ledger_dir(repo_root)
    ledger = IngestLedger(ledger_dir / "INGEST_LEDGER.jsonl")
    klines = source if source is not None else BinancePublicKlines()

    frozen = FP.assert_frozen_corpus()
    # The ruleset belongs to the CODE, not to the tree the store happens to live in, so the
    # pin resolves against the checkout this module was loaded from: a lane driven from a
    # temporary directory still has to measure the published ruleset.
    params_pin = FP.assert_frozen_params()
    now = int(observed_at_ms if observed_at_ms is not None else klines.server_time_ms())

    first: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for timeframe, symbol in FORWARD_SERIES:
        try:
            first.append(
                ingest_series(
                    source=klines,
                    store=store,
                    ledger=ledger,
                    timeframe=timeframe,
                    symbol=symbol,
                    frozen_end_ms=FROZEN_END[timeframe],
                    observed_at_ms=now,
                )
            )
        except Exception as exc:
            errors.append({"series": f"{timeframe}:{symbol}", "stage": "ingest", "error": repr(exc)})
            first.append(
                {
                    "timeframe": timeframe,
                    "symbol": symbol,
                    "outcome": "error",
                    "reason": repr(exc),
                    "appended": 0,
                    "run_at_ms": now,
                }
            )

    # -- restart / recovery proof: the same instant must not move the store
    before = {f"{tf}:{sym}": store.sha256(tf, sym) for tf, sym in FORWARD_SERIES}
    second = [
        ingest_series(
            source=klines,
            store=store,
            ledger=ledger,
            timeframe=timeframe,
            symbol=symbol,
            frozen_end_ms=FROZEN_END[timeframe],
            observed_at_ms=now,
        )
        for timeframe, symbol in FORWARD_SERIES
    ]
    after = {f"{tf}:{sym}": store.sha256(tf, sym) for tf, sym in FORWARD_SERIES}

    quality: dict[str, Any] = {}
    observation: dict[str, Any] = {}
    latency: dict[str, Any] = {}
    duplicate_timestamps = 0
    for timeframe, symbol in FORWARD_SERIES:
        key = f"{timeframe}:{symbol}"
        stored = store.read(timeframe, symbol)
        quality[key] = audit_series(
            stored, timeframe=timeframe, frozen_end_ms=FROZEN_END[timeframe]
        )
        observation[key] = observation_days(
            stored, timeframe=timeframe, coverage=FP.OBSERVATION_COVERAGE
        )
        latency[key] = _latency(stored, timeframe=timeframe, fetched_at_ms=now)
        duplicate_timestamps += int(quality[key]["duplicates"])

    shadow = run_shadow(
        repo_root=repo_root,
        store=store,
        frozen_1h_end_ms=FP.FROZEN_1H_END_MS,
        frozen_15m_end_ms=FP.FROZEN_15M_END_MS,
        scenarios=scenarios,
    )
    parity = run_parity(
        captures=shadow["decisions"],
        sweep_cases=sweep_cases,
        shadow_case_limit=shadow_case_limit,
    )

    primary_key = str(shadow["primary_arm"])
    primary = shadow["arms"].get(primary_key, {})
    primary_trades = primary.get("trades", []) if isinstance(primary, dict) else []
    duplicate_refusals = 0
    if isinstance(primary, dict) and primary.get("refusals"):
        refusal_keys: set[tuple[Any, ...]] = set()
        for refusal in primary["refusals"]:
            refusal_key = (
                refusal.get("symbol"),
                refusal.get("decision_ts"),
                refusal.get("reason"),
            )
            if refusal_key in refusal_keys:
                duplicate_refusals += 1
            refusal_keys.add(refusal_key)

    manifest = store_manifest(store, series=FORWARD_SERIES)
    total_days = _observation_total(observation, assets=ASSETS)
    outcomes: dict[str, int] = {}
    for row in first:
        outcomes[str(row.get("outcome"))] = outcomes.get(str(row.get("outcome")), 0) + 1
    no_new = [f"{row['timeframe']}:{row['symbol']}" for row in first if row.get("outcome") != "ingested"]
    new_bars = sum(int(row.get("appended") or 0) for row in first)

    payload: dict[str, Any] = {
        "run_id": f"FWD-EDGE03-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(now / 1000))}",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "observed_at_ms": now,
        "observed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now / 1000)),
        "plan": FP.FORWARD_PLAN,
        "decision": FP.FORWARD_DECISION,
        "frozen_corpus": frozen,
        "frozen_params": params_pin,
        "ingest": {
            "ledger": first,
            "ledger_path": _relative_to(ledger.path, repo_root),
            "series": [f"{tf}:{sym}" for tf, sym in FORWARD_SERIES],
        },
        "manifest": manifest,
        "quality": quality,
        "observation": observation,
        "latency": latency,
        "restart_proof": {
            "second_run_outcome": sorted({str(row.get("outcome")) for row in second}),
            "second_run_appended": sum(int(row.get("appended") or 0) for row in second),
            "digests_unchanged": before == after,
            "digests": after,
            "duplicate_timestamps": duplicate_timestamps,
            "duplicate_refusals": duplicate_refusals,
            "note": (
                "the second ingest runs at the SAME market instant, so any bar it appends "
                "would be a duplicate; it appends none and leaves every digest identical"
            ),
        },
        "shadow": {
            "primary_arm": shadow["primary_arm"],
            "primary_available": shadow["primary_available"],
            "context_note": shadow["context_note"],
            "provenance": shadow["provenance"],
            "decisions_digest": _decisions_digest(shadow["decisions"]),
            "captured_decisions": len(shadow["decisions"]),
            "arm_summaries": {arm: _arm_summary(body) for arm, body in shadow["arms"].items()},
            "start_equity": 10_000.0,
            "hypothetical": True,
            "order_sent": False,
        },
        "primary_equity_curve": [
            [int(ts), round(float(equity), 6)]
            for ts, equity in (
                primary.get("equity_curve", []) if isinstance(primary, dict) else []
            )
        ],
        # The captured budget states, published as their own JSONL: they are the inputs
        # parity is checked on, so they are evidence and not a debug dump.
        "shadow_decisions": shadow["decisions"],
        "parity": parity,
        "health": {
            "new_bars": new_bars,
            "stored_bars": int(
                sum(int(entry.get("bars") or 0) for entry in manifest["files"].values())
            ),
            "observation_days": total_days["common_days"],
            "observation_days_detail": total_days,
            "ingest_runs": len(first),
            "ingest_outcomes": outcomes,
            "no_new_data_series": no_new,
            "errors": errors,
            "primary_trades": len(primary_trades),
        },
    }
    payload["verdict"] = observation_verdict(payload)
    return payload


def _csv(path: Path, rows: list[dict[str, Any]], columns: tuple[str, ...] | None = None) -> None:
    import csv

    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(columns) if columns else list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_forward_artifacts(
    payload: dict[str, Any], outdir: Path, *, ledger_src: Path | None = None
) -> dict[str, Path]:
    """Write the observation artefacts: the summary, the ledgers, the reports."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    summary = {
        key: value
        for key, value in payload.items()
        if key not in {"parity", "shadow_decisions", "daily_arms"}
    }
    summary["parity"] = {
        "verdict": payload["parity"]["verdict"],
        "counts": payload["parity"]["counts"],
        "counts_by_origin": payload["parity"]["counts_by_origin"],
        "captured_reproduction": payload["parity"]["captured_reproduction"],
        "defects": payload["parity"]["defects"],
        "divergence_total": payload["parity"]["divergence_total"],
        "not_claimed": payload["parity"]["not_claimed"],
    }
    path = outdir / "OBSERVATION.json"
    path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    written["observation"] = path

    arms = payload["shadow"]["arm_summaries"]
    detail_arms = {arm: body for arm, body in arms.items() if body.get("status") == "observed"}
    primary = detail_arms.get(str(payload["shadow"]["primary_arm"]), {})
    equity_rows = [
        {"ts": ts, "iso_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts / 1000)), "equity": round(eq, 6)}
        for ts, eq in payload.get("primary_equity_curve", [])
    ]
    if not equity_rows and primary:
        equity_rows = primary.get("equity_curve_rows", [])
    if equity_rows:
        path = outdir / "SHADOW_EQUITY.csv"
        _csv(path, equity_rows, ("ts", "iso_utc", "equity"))
        written["equity"] = path

    signals = [row for body in detail_arms.values() for row in body.get("signals_detail", [])]
    trades = [row for body in detail_arms.values() for row in body.get("trades_detail", [])]
    refusals = [row for body in detail_arms.values() for row in body.get("refusals_detail", [])]
    if signals:
        path = outdir / "SHADOW_SIGNALS.csv"
        _csv(
            path,
            signals,
            (
                "arm",
                "candidate",
                "symbol",
                "decision_ts",
                "decision_timeframe",
                "entry_reference",
                "stop",
                "risk_reward",
                "expected_gross_bps",
                "expected_net_bps",
                "regime",
                "hypothetical",
                "order_sent",
            ),
        )
        written["signals"] = path
    if trades:
        path = outdir / "SHADOW_TRADES.csv"
        _csv(
            path,
            trades,
            (
                "arm",
                "candidate",
                "asset",
                "decision_ts",
                "entry_ts",
                "exit_ts",
                "entry_fill",
                "exit_fill",
                "qty",
                "notional",
                "gross",
                "fees",
                "price_costs",
                "net",
                "exit_reason",
                "regime",
                "hypothetical",
                "order_sent",
            ),
        )
        written["trades"] = path
    if refusals:
        path = outdir / "SHADOW_REFUSALS.csv"
        _csv(path, refusals, ("symbol", "decision_ts", "source", "reason", "candidate"))
        written["refusals"] = path

    path = outdir / "INGEST_LEDGER.jsonl"
    if path.exists():
        written["ledger"] = path

    path = outdir / "SHADOW_DECISIONS.jsonl"
    decisions = payload.get("shadow_decisions") or []
    if decisions:
        path.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in decisions),
            encoding="utf-8",
        )
        written["decisions"] = path

    written.update(write_observability(payload, outdir))
    return written
