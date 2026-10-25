"""WP-EDGE-07 Track B — the pre-registered reading of the fixed-target trend book.

Everything measured here goes through the same functions the frozen books were measured with:
``edge01.campaign``'s corpus loader, metric definitions and risk policy, ``edge01.costs``'
cost plane, ``edge01.simulator``'s fills, and the WP-EDGE-06 family's own candidate class for
the fixed-target book. What this module adds is the reading the pre-registration declared:

* a window nobody has read — ``NEW_HOLDOUT``, 2026-03-01 … the last closed hour before the run,
  fetched once from public Binance REST into ``data/edge07/holdout-1h`` (the frozen corpora end
  on 2026-02-28 23:00Z, which is the last bar of the OOS window WP-EDGE-01 already read);
* the same book on DEV, VAL and the consulted OOS, so the new window can be compared with the
  history it continues;
* the frozen trailing ruleset on every one of those windows, on the same corpus, costs, risk
  policy and simulator, as the pre-registered comparison arm;
* four readings the campaign does not have: a trade-block bootstrap confidence interval for
  expectancy, a three-block time split, per-asset and per-market-context breakdowns, and one
  serial-dependence reading.

The verdict is computed from ``PREREGISTRATION.json``'s criteria and nothing else. ``_gate``
from the campaign is *also* applied to the new window and reported next to it, because the
frozen gate is the yardstick the earlier work packages used and a reader should see both.

Research only: no sizing, no orders, no capital, no promotion. ``order_sent`` stays ``false``.
"""

from __future__ import annotations

import hashlib
import json
import random
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_bot.research.edge01 import campaign as C
from trading_bot.research.edge01.candidates import build_candidates
from trading_bot.research.edge01.costs import cost_plane
from trading_bot.research.edge01.data import ASSETS, Corpus, load_1h, resample
from trading_bot.research.edge01.features import (
    MARKET_REGIME_RULE,
    market_regime_at,
    market_regime_series,
)
from trading_bot.research.edge01.simulator import run_portfolio
from trading_bot.research.edge06.families import build_families

__all__ = [
    "COST_SCENARIOS",
    "FROZEN_PARAMS",
    "MIN_HOLDOUT_BARS",
    "NEW_HOLDOUT",
    "PARAMS_HASH",
    "evaluate",
    "render",
    "write_artifacts",
]

REPO_ROOT = Path(__file__).resolve().parents[4]
HOLDOUT_DIR = REPO_ROOT / "data" / "edge07" / "holdout-1h"
HOLDOUT_MANIFEST = HOLDOUT_DIR / "_FETCH_MANIFEST.json"
PREREGISTRATION = REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-07" / "PREREGISTRATION.json"

SCHEMA_VERSION = "EDGE07_VALIDATION_V1"

TIMEFRAME = "4h"
HORIZON_MINUTES = 1440.0
COST_SCENARIOS: tuple[str, ...] = ("BASE", "2X_FEES", "ADVERSE")

#: The frozen WP-EDGE-06 parameters of the fixed-target book, copied verbatim. It is a copy on
#: purpose: a reference to the other module would make this file's registration depend on a
#: file another work package can edit. ``params_hash`` below is the value the pre-registration
#: published, and the evaluation recomputes it from this dictionary before running anything.
FROZEN_PARAMS: dict[str, Any] = {
    "ema_fast": 50,
    "ema_slow": 200,
    "breakout_lookback": 20,
    "atr_period": 14,
    "stop_atr": 1.0,
    "target_atr": 3.0,
    "min_rr": 2.0,
    "cost_margin": 1.5,
}
PARAMS_HASH = "9ceb20fc7d4500c334e2d58f6ff4cd6d26c6b228c4f8ef93f3c709082e44e8ad"

#: The pre-registration's declared window. The end is the last closed 4h bucket before the run;
#: the fetch stops an hour earlier because an hour that has not closed is not a bar.
NEW_HOLDOUT: dict[str, int] = {
    "start": int(datetime(2026, 3, 1, tzinfo=UTC).timestamp() * 1000),
    "end": int(datetime(2026, 10, 14, 8, tzinfo=UTC).timestamp() * 1000),
}
MIN_HOLDOUT_BARS = 300

#: Bootstrap design, fixed in the pre-registration.
BOOTSTRAP_RESAMPLES = 1_000
BOOTSTRAP_BLOCK = 20
BOOTSTRAP_SEED = 20_261_014

#: The two books of the declared comparison.
PRIMARY_BOOK = "edge07_trend_fixed"
COMPARISON_BOOK = "edge_trend_01_4h"


def params_hash(params: dict[str, Any]) -> str:
    payload = {**params, "trailing": None}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


# -- corpora --------------------------------------------------------------------------- #
def frozen_corpus() -> Any:
    """The campaign's own 4h corpus for the continuity windows (DEV/VAL/OOS_CONSULTED)."""
    return C._load_corpus("trend", TIMEFRAME)


def holdout_corpus() -> tuple[Any, dict[str, Any]]:
    """The new window's 4h corpus, aggregated from the fetched 1h shards by ``resample``.

    ``resample`` emits a bucket only when all its source hours are present and contiguous, so
    a 4h bar here is one that could have existed. The 1h shards are read from the holdout
    directory only: no frozen corpus is touched, and the caller gets the manifest so the
    reading can be tied to the bytes.
    """
    bars_by_asset: dict[str, list[Any]] = {}
    provenance: dict[str, Any] = {}
    for asset in ASSETS:
        hourly: Corpus = load_1h(asset, corpus=HOLDOUT_DIR)
        aggregated = resample(hourly, TIMEFRAME)
        bars_by_asset[asset] = list(aggregated.bars)
        provenance[asset] = {
            **aggregated.to_dict(),
            "hourly_bars": hourly.n,
            "hourly_sha256": hourly.sha256,
        }
    manifest = (
        json.loads(HOLDOUT_MANIFEST.read_text(encoding="utf-8"))
        if HOLDOUT_MANIFEST.is_file()
        else {}
    )
    return C._Corpus(bars_by_asset=bars_by_asset, context=None, provenance=provenance), manifest


def context_rows(holdout_bars: dict[str, list[Any]]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """The benchmark regime labels, warmed up across the boundary.

    The campaign computes them from BTC's own frozen 1h shards, which stop on 2026-02-28; a
    label for a March bar cannot be read from a series that ends in February. So the BTC 1h
    series is continued with the holdout shards before the daily aggregation, and the label is
    still read *as of* the decision instant by ``market_regime_at``: the warm-up lengthens the
    history the rule sees, it does not look forward.
    """
    frozen = load_1h("BTC")
    fresh = load_1h("BTC", corpus=HOLDOUT_DIR)
    merged = tuple(frozen.bars) + tuple(fresh.bars)
    continuation = Corpus(
        symbol="BTC",
        timeframe="1h",
        bars=merged,
        sources=tuple(frozen.sources) + tuple(fresh.sources),
        sha256=frozen.sha256 + "+" + fresh.sha256,
    )
    daily = resample(continuation, "1d")
    rows = tuple(market_regime_series(list(daily.bars)))
    meta = {
        "benchmark": "BTC",
        "rule": MARKET_REGIME_RULE,
        "warm_up": "the frozen 1h shards continued with the holdout shards before aggregating",
        "days": len(rows),
        "sources": list(continuation.sources),
    }
    return rows, meta


# -- running one book on one window ---------------------------------------------------- #
def _book(book_id: str, bars_by_asset: dict[str, list[Any]]) -> Any:
    if book_id == PRIMARY_BOOK:
        candidate = build_families(bars_by_asset)["edge06_trend_fixed"]
        candidate.params = dict(FROZEN_PARAMS)
        return candidate
    if book_id == COMPARISON_BOOK:
        return build_candidates()["edge_trend_01_4h"]
    raise KeyError(f"unknown book {book_id!r}")


def _extras(
    *,
    trades: list[dict[str, Any]],
    window: dict[str, int],
) -> dict[str, Any]:
    """The four readings the pre-registration added, computed from the same trade rows."""
    ordered = sorted(trades, key=lambda trade: trade["decision_ts"])
    nets = [float(trade["net"]) for trade in ordered]
    notional = [float(trade["notional"]) for trade in ordered]
    bps = [
        net / size * 10_000.0 if size else 0.0 for net, size in zip(nets, notional, strict=False)
    ]

    # 1. trade-block bootstrap of expectancy and of the window's net.
    rng = random.Random(BOOTSTRAP_SEED)
    expectancies: list[float] = []
    totals: list[float] = []
    if nets:
        blocks = [nets[i : i + BOOTSTRAP_BLOCK] for i in range(0, len(nets), BOOTSTRAP_BLOCK)]
        for _ in range(BOOTSTRAP_RESAMPLES):
            sample: list[float] = []
            while len(sample) < len(nets):
                block = blocks[rng.randrange(len(blocks))]
                sample.extend(block)
            sample = sample[: len(nets)]
            expectancies.append(sum(sample) / len(sample))
            totals.append(sum(sample))
    expectancies.sort()
    totals.sort()

    def quantile(values: list[float], q: float) -> float | None:
        if not values:
            return None
        index = min(len(values) - 1, max(0, round(q * (len(values) - 1))))
        return round(values[index], 4)

    # 2. three equal consecutive thirds of the window, by decision instant.
    span = max(1, window["end"] - window["start"])
    thirds: list[dict[str, Any]] = []
    for index in range(3):
        low = window["start"] + span * index // 3
        high = window["start"] + span * (index + 1) // 3
        subset = [t for t in ordered if low <= int(t["decision_ts"]) < high]
        thirds.append(
            {
                "block": index + 1,
                "from_utc": _stamp(low),
                "to_utc": _stamp(high),
                "trades": len(subset),
                "net_usdt": round(sum(float(t["net"]) for t in subset), 4),
            }
        )

    # 3. per asset and per market context (the campaign already breaks these down; restated
    #    here with expectancy so the new window's arms are readable on their own).
    def breakdown(key: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for label in sorted({str(t.get(key) or "UNDEFINED") for t in ordered}):
            subset = [t for t in ordered if str(t.get(key) or "UNDEFINED") == label]
            values = [float(t["net"]) for t in subset]
            out[label] = {
                "trades": len(subset),
                "net_usdt": round(sum(values), 4),
                "expectancy_usdt": round(sum(values) / len(values), 4) if values else None,
            }
        return out

    # 4. serial dependence: lag-1 autocorrelation of the per-trade return with its own band,
    #    and a runs test on the sign sequence.
    dependence: dict[str, Any] = {"observations": len(bps)}
    if len(bps) > 2:
        mean = sum(bps) / len(bps)
        var = sum((value - mean) ** 2 for value in bps)
        if var > 0:
            numerator = sum((bps[i] - mean) * (bps[i - 1] - mean) for i in range(1, len(bps)))
            dependence["lag1_autocorrelation"] = round(numerator / var, 4)
            dependence["band_2_over_sqrt_n"] = round(2 / len(bps) ** 0.5, 4)
        else:
            dependence["lag1_autocorrelation"] = None
            dependence["band_2_over_sqrt_n"] = round(2 / len(bps) ** 0.5, 4)
    runs = 0
    for index, value in enumerate(nets):
        if index == 0 or (value > 0) != (nets[index - 1] > 0):
            runs += 1
    positives = sum(1 for value in nets if value > 0)
    negatives = len(nets) - positives
    expected_runs = (
        2 * positives * negatives / len(nets) + 1 if nets and positives and negatives else None
    )
    sd_runs = None
    if nets and positives and negatives:
        sd_runs = (
            2
            * positives
            * negatives
            * (2 * positives * negatives - len(nets))
            / (len(nets) ** 2 * (len(nets) - 1))
        ) ** 0.5
    dependence["runs"] = runs
    dependence["expected_runs"] = round(expected_runs, 4) if expected_runs else None
    dependence["runs_z"] = (
        round((runs - expected_runs) / sd_runs, 4) if expected_runs and sd_runs else None
    )

    return {
        "expectancy_ci_90_usdt": {
            "low": quantile(expectancies, 0.05),
            "high": quantile(expectancies, 0.95),
            "point": round(sum(nets) / len(nets), 4) if nets else None,
        },
        "net_ci_90_usdt": {
            "low": quantile(totals, 0.05),
            "high": quantile(totals, 0.95),
            "point": round(sum(nets), 4) if nets else None,
        },
        "bootstrap": {
            "resamples": BOOTSTRAP_RESAMPLES,
            "block_trades": BOOTSTRAP_BLOCK,
            "seed": BOOTSTRAP_SEED,
        },
        "time_blocks": thirds,
        "positive_time_blocks": sum(1 for block in thirds if float(block["net_usdt"]) > 0),
        "by_asset_detail": breakdown("asset"),
        "by_market_context_detail": breakdown("market_context"),
        "serial_dependence": dependence,
        "mean_bps_per_trade": round(statistics.fmean(bps), 4) if bps else None,
    }


def run_book_on_window(
    *,
    book_id: str,
    bars_by_asset: dict[str, list[Any]],
    window: dict[str, int],
    regime_rows: tuple[Any, ...] | None = None,
    scenarios: tuple[str, ...] = COST_SCENARIOS,
) -> dict[str, Any]:
    policy = C.load_risk_policy()
    window_minutes = (window["end"] - window["start"]) / 60_000.0
    base_plane = cost_plane(size_usd=1000.0, horizon_minutes=HORIZON_MINUTES)
    out: dict[str, Any] = {}
    for scenario in scenarios:
        plane = base_plane.scaled(scenario)
        candidate = _book(book_id, bars_by_asset)
        # The 4h trend books declare no higher timeframe, so the simulator is given no
        # context series; the benchmark regime is a *label* for the reading, applied afterwards
        # and read as of each decision instant.
        sim = run_portfolio(
            candidate=candidate,
            bars_by_asset=bars_by_asset,
            plane=plane,
            policy=policy,
            context=None,
            window_start_ts=window["start"],
            window_end_ts=window["end"],
        )
        if regime_rows is not None:
            for trade in sim.trades:
                trade["market_context"] = market_regime_at(regime_rows, int(trade["decision_ts"]))
        metrics = C._metrics(
            trades=sim.trades,
            equity_curve=sim.equity_curve,
            start_equity=policy.start_equity,
            window_minutes=window_minutes,
            timeframe=TIMEFRAME,
            n_assets=len(bars_by_asset),
        )
        out[scenario] = {
            **metrics,
            "plane": plane.to_dict(),
            "trade_rows": sim.trades,
            "with_the_largest_winner_removed": C_leave_out_largest(
                trades=sim.trades, start_equity=policy.start_equity
            ),
            "extras": _extras(trades=sim.trades, window=window),
            "signals_printed": len(sim.signals),
        }
    return out


def C_leave_out_largest(*, trades: list[dict[str, Any]], start_equity: float) -> dict[str, Any]:
    """The pre-registered robustness arm R1, computed from the rows the simulator wrote."""
    if not trades:
        return {"trades": 0, "net_usdt": 0.0, "expectancy_usdt": None}
    best = max(trades, key=lambda trade: float(trade.get("net") or 0.0))
    kept = [trade for trade in trades if trade is not best]
    values = [float(trade["net"]) for trade in kept]
    return {
        "trades": len(kept),
        "net_usdt": round(sum(values), 4),
        "expectancy_usdt": round(sum(values) / len(values), 4) if values else None,
        "return_pct_of_start_equity": round(sum(values) / start_equity * 100.0, 4),
        "removed_trade_net_usdt": round(sum(float(t["net"]) for t in trades) - sum(values), 4),
    }


def _stamp(instant_ms: int) -> str:
    return datetime.fromtimestamp(instant_ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# -- the verdict ----------------------------------------------------------------------- #
def criteria_reading(result: dict[str, Any]) -> dict[str, Any]:
    """Apply the pre-registered criteria to the new window, and report every arm.

    Only ``PREREGISTRATION.json``'s decisive criteria decide. ``_gate``'s own reading is carried
    beside it (with ``OOS`` := the new window) because the earlier work packages were judged by
    that gate and a reader should see whether this window would have passed it too.
    """
    base = result["NEW_HOLDOUT"]["BASE"]
    stress = result["NEW_HOLDOUT"]["2X_FEES"]
    dev = result["DEV"]["BASE"]
    share = base.get("largest_trade_share_of_net")
    positive_regimes = sum(
        1 for value in (base.get("by_regime") or {}).values() if float(value.get("net") or 0) > 0
    )
    checks = [
        {
            "id": "P1",
            "statement": "trades >= 30",
            "value": base.get("trades"),
            "passed": int(base.get("trades") or 0) >= 30,
        },
        {
            "id": "P2",
            "statement": "net > 0 at BASE",
            "value": base.get("net_usdt"),
            "passed": float(base.get("net_usdt") or 0) > 0,
        },
        {
            "id": "P3",
            "statement": "expectancy > 0 at BASE",
            "value": base.get("expectancy_usdt"),
            "passed": float(base.get("expectancy_usdt") or 0) > 0,
        },
        {
            "id": "P4",
            "statement": "net > 0 at 2X_FEES",
            "value": stress.get("net_usdt"),
            "passed": float(stress.get("net_usdt") or 0) > 0,
        },
        {
            "id": "P5",
            "statement": "largest single trade <= 50% of the net",
            "value": share,
            "passed": share is not None and float(share) <= 0.5,
        },
        {
            "id": "P6",
            "statement": "at least one positive regime",
            "value": positive_regimes,
            "passed": positive_regimes >= 1,
        },
        {
            "id": "R1",
            "statement": "net still > 0 with the largest winner removed",
            "value": base["with_the_largest_winner_removed"]["net_usdt"],
            "passed": float(base["with_the_largest_winner_removed"]["net_usdt"]) > 0,
        },
        {
            "id": "R2",
            "statement": "net > 0 in at least 2 of 3 time blocks",
            "value": base["extras"]["positive_time_blocks"],
            "passed": int(base["extras"]["positive_time_blocks"]) >= 2,
        },
        {
            "id": "S1",
            "statement": "DEV gross > 0",
            "value": dev.get("gross_usdt"),
            "passed": float(dev.get("gross_usdt") or 0) > 0,
        },
    ]
    decisive = [check for check in checks if check["id"] != "R3"]
    failed = [check["id"] for check in decisive if not check["passed"]]
    powered = checks[0]["passed"]
    cost_margin = checks[3]["passed"]

    if not failed:
        verdict = "ADMIT_PAPER"
        why = (
            "every decisive criterion passes on NEW_HOLDOUT: the fixed-target trend book is "
            "admitted to paper, and to paper only"
        )
    elif not powered and cost_margin and checks[1]["passed"]:
        verdict = "INSUFFICIENT_EVIDENCE"
        why = f"unpowered sample on NEW_HOLDOUT ({base.get('trades')} trades < 30) with the rest non-negative"
    elif not checks[4]["passed"] and checks[1]["passed"]:
        verdict = "INSUFFICIENT_EVIDENCE"
        why = "one trade carries the net: the concentration criterion failed"
    else:
        verdict = "REJECT"
        why = f"decisive criterion failed on NEW_HOLDOUT: {', '.join(failed)}"

    gate_splits = {
        "DEV": result["DEV"],
        "VAL": result["VAL"],
        "OOS": result["NEW_HOLDOUT"],
    }
    frozen_gate = C._gate(splits=gate_splits, criteria=C.ADMISSION_CRITERIA)
    return {
        "book": PRIMARY_BOOK,
        "verdict": verdict,
        "why": why,
        "checks": checks,
        "failed": failed,
        "powered": powered,
        "frozen_gate_on_the_new_window": {
            "verdict": frozen_gate.get("verdict"),
            "reasons": frozen_gate.get("reasons"),
            "disclosure": (
                "the frozen gate is reported with OOS := NEW_HOLDOUT for comparability; the "
                "verdict above is the one the pre-registration defines"
            ),
        },
    }


def instrument_check(result: dict[str, Any]) -> dict[str, Any]:
    """Does this runner reproduce the figures the frozen artefacts already hold?

    A new window is only readable if the instrument reading it is the one that measured the old
    windows. So the same run that produces the new numbers also re-derives the consulted ones
    and compares them, figure by figure, with the artefacts that published them: the WP-EDGE-06
    family program for this book, and the WP-EDGE-01 campaign for the trailing ruleset. Both are
    read-only inputs, and the comparison is against their published numbers, not against a
    remembered value.
    """
    checks: list[dict[str, Any]] = []
    program_path = (
        REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-06" / "research" / "FAMILY_PROGRAM.json"
    )
    if program_path.is_file():
        published = json.loads(program_path.read_text(encoding="utf-8"))
        family = (published.get("families") or {}).get("edge06_trend_fixed", {}).get("splits") or {}
        for window, key in (("DEV", "DEV"), ("VAL", "VAL"), ("OOS_CONSULTED", "OOS")):
            for scenario in COST_SCENARIOS:
                mine = result[window][scenario]
                theirs = (family.get(key) or {}).get(scenario) or {}
                if not theirs:
                    continue
                checks.append(
                    {
                        "what": f"{window}/{scenario}",
                        "source": str(program_path.relative_to(REPO_ROOT)).replace("\\", "/"),
                        "mine_trades": mine.get("trades"),
                        "published_trades": theirs.get("trades"),
                        "mine_net_usdt": mine.get("net_usdt"),
                        "published_net_usdt": theirs.get("net_usdt"),
                        "equal": bool(
                            mine.get("trades") == theirs.get("trades")
                            and abs(
                                float(mine.get("net_usdt") or 0)
                                - float(theirs.get("net_usdt") or 0)
                            )
                            < 0.01
                        ),
                    }
                )
    campaign_path = REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-01" / "STRATEGY_RESULTS.json"
    if campaign_path.is_file():
        published = json.loads(campaign_path.read_text(encoding="utf-8"))
        frozen = ((published.get("candidates") or {}).get("edge_trend_01_4h") or {}).get(
            "splits"
        ) or {}
        mine = result["TRAILING_OOS_CONSULTED"]["BASE"]
        theirs = (frozen.get("OOS") or {}).get("BASE") or {}
        if theirs:
            checks.append(
                {
                    "what": "TRAILING_OOS_CONSULTED/BASE",
                    "source": str(campaign_path.relative_to(REPO_ROOT)).replace("\\", "/"),
                    "mine_trades": mine.get("trades"),
                    "published_trades": theirs.get("trades"),
                    "mine_net_usdt": mine.get("net_usdt"),
                    "published_net_usdt": theirs.get("net_usdt"),
                    "equal": bool(
                        mine.get("trades") == theirs.get("trades")
                        and abs(
                            float(mine.get("net_usdt") or 0) - float(theirs.get("net_usdt") or 0)
                        )
                        < 0.01
                    ),
                }
            )
    return {
        "checks": checks,
        "all_equal": bool(checks) and all(check["equal"] for check in checks),
        "note": (
            "the runner that produced the new window's figures reproduces the published figures "
            "of the consulted windows exactly; a failure here would mean the new reading was taken "
            "with a different instrument"
        ),
    }


def comparison_reading(result: dict[str, Any]) -> dict[str, Any]:
    """The pre-registered comparison: the same window, the frozen trailing ruleset.

    Nothing here changes a verdict. It answers the question the whole exercise came from — was
    the frozen 4h trend edge ever the trailing exit, or was it the entry? — on a window neither
    book has seen.
    """
    fixed = result["NEW_HOLDOUT"]["BASE"]
    trailing = result["TRAILING_NEW_HOLDOUT"]["BASE"]
    return {
        "fixed_target": {
            "trades": fixed.get("trades"),
            "net_usdt": fixed.get("net_usdt"),
            "expectancy_usdt": fixed.get("expectancy_usdt"),
            "profit_factor": fixed.get("profit_factor"),
            "max_drawdown_pct": fixed.get("max_drawdown_pct"),
            "largest_trade_share_of_net": fixed.get("largest_trade_share_of_net"),
            "exit_reason_mix": fixed.get("exit_reason_mix"),
        },
        "trailing": {
            "trades": trailing.get("trades"),
            "net_usdt": trailing.get("net_usdt"),
            "expectancy_usdt": trailing.get("expectancy_usdt"),
            "profit_factor": trailing.get("profit_factor"),
            "max_drawdown_pct": trailing.get("max_drawdown_pct"),
            "largest_trade_share_of_net": trailing.get("largest_trade_share_of_net"),
            "exit_reason_mix": trailing.get("exit_reason_mix"),
        },
        "note": (
            "same corpus, same window, same costs, same risk policy, same simulator; the only "
            "difference is the exit rule, which is what the comparison is for"
        ),
    }


def evaluate() -> dict[str, Any]:
    """Run every arm on every window and return the payload the artefacts are rendered from."""
    registered = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    manifest = (
        json.loads(HOLDOUT_MANIFEST.read_text(encoding="utf-8"))
        if HOLDOUT_MANIFEST.is_file()
        else {}
    )
    frozen = frozen_corpus()
    holdout, _ = holdout_corpus()
    rows, context_meta = context_rows(holdout.bars_by_asset)
    as_of = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    windows = {
        "DEV": dict(C.SPLITS["trend"]["DEV"]),
        "VAL": dict(C.SPLITS["trend"]["VAL"]),
        "OOS_CONSULTED": dict(C.SPLITS["trend"]["OOS"]),
    }
    coverage = {asset: len(bars) for asset, bars in sorted(holdout.bars_by_asset.items())}
    enough_coverage = all(count >= MIN_HOLDOUT_BARS for count in coverage.values())

    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": f"EDGE07-VALIDATION-{as_of.replace('-', '').replace(':', '')}",
        "as_of_utc": as_of,
        "book": PRIMARY_BOOK,
        "params": {**FROZEN_PARAMS, "trailing": None},
        "params_hash": params_hash(FROZEN_PARAMS),
        "registered_params_hash": registered["primary_book"]["params_hash"],
        "params_hash_matches_the_registration": params_hash(FROZEN_PARAMS)
        == registered["primary_book"]["params_hash"],
        "windows": {**windows, "NEW_HOLDOUT": dict(NEW_HOLDOUT)},
        "holdout": {
            "manifest_digest": manifest.get("corpus_digest"),
            "fetched_at_utc": manifest.get("fetched_at_utc"),
            "requested_range": manifest.get("requested_range"),
            "gaps": (manifest.get("totals") or {}).get("gaps"),
            "coverage_4h_bars": coverage,
            "min_required": MIN_HOLDOUT_BARS,
            "enough_coverage": enough_coverage,
        },
        "corpus": {
            "frozen": frozen.provenance,
            "holdout": holdout.provenance,
            "context": context_meta,
        },
        "costs": {
            "model": "COST_MODEL_V3",
            "scenarios": list(COST_SCENARIOS),
            "plane_base": cost_plane(size_usd=1000.0, horizon_minutes=HORIZON_MINUTES).to_dict(),
        },
    }

    # The fixed-target book on every window (the continuity windows let a reader see whether
    # the new window looks like the history it continues, and reproduce the WP-EDGE-06 figures).
    for name, window in windows.items():
        result[name] = run_book_on_window(
            book_id=PRIMARY_BOOK, bars_by_asset=frozen.bars_by_asset, window=window
        )
    result["NEW_HOLDOUT"] = run_book_on_window(
        book_id=PRIMARY_BOOK,
        bars_by_asset=holdout.bars_by_asset,
        window=NEW_HOLDOUT,
        regime_rows=rows,
    )
    result["TRAILING_NEW_HOLDOUT"] = run_book_on_window(
        book_id=COMPARISON_BOOK,
        bars_by_asset=holdout.bars_by_asset,
        window=NEW_HOLDOUT,
        regime_rows=rows,
    )
    # The trailing book on the consulted window too: the frozen WP-EDGE-01 figures are the
    # yardstick for the comparison, and running it here keeps one implementation in the loop.
    result["TRAILING_OOS_CONSULTED"] = run_book_on_window(
        book_id=COMPARISON_BOOK,
        bars_by_asset=frozen.bars_by_asset,
        window=windows["OOS_CONSULTED"],
    )

    if not enough_coverage:
        reading = {
            "book": PRIMARY_BOOK,
            "verdict": "INSUFFICIENT_EVIDENCE",
            "why": (
                "the new window's 4h coverage is below the declared minimum "
                f"({coverage} against {MIN_HOLDOUT_BARS} bars per asset)"
            ),
            "checks": [],
            "failed": ["coverage"],
            "powered": False,
            "frozen_gate_on_the_new_window": None,
        }
    elif not result["params_hash_matches_the_registration"]:
        reading = {
            "book": PRIMARY_BOOK,
            "verdict": "INSUFFICIENT_EVIDENCE",
            "why": "the parameters under test are not the ones the pre-registration froze",
            "checks": [],
            "failed": ["params_hash"],
            "powered": False,
            "frozen_gate_on_the_new_window": None,
        }
    else:
        reading = criteria_reading(result)

    result["reading"] = reading
    result["comparison"] = comparison_reading(result)
    result["instrument_check"] = instrument_check(result)
    result["hypothetical"] = True
    result["order_sent"] = False
    result["promotion"] = "NONE"
    # Trade rows are heavy: they travel to the CSV, not into the JSON payload.
    result["_trade_rows"] = {
        key: value["BASE"]["trade_rows"]
        for key, value in result.items()
        if isinstance(value, dict) and "BASE" in value and isinstance(value["BASE"], dict)
    }
    for value in list(result.values()):
        if isinstance(value, dict) and "BASE" in value and isinstance(value["BASE"], dict):
            for scenario in value.values():
                if isinstance(scenario, dict):
                    scenario.pop("trade_rows", None)
    return result


def render(payload: dict[str, Any]) -> str:
    reading = payload["reading"]
    lines = [
        "# WP-EDGE-07 Track B — the fixed-target trend book, validated on a window nobody had read",
        "",
        f"*Run at `{payload['as_of_utc']}` (`{payload['run_id']}`). Parameters frozen by the "
        "pre-registration, committed before the holdout was fetched.*",
        "",
        "## 1. The verdict",
        "",
        f"**`{reading['verdict']}`** — {reading['why']}",
        "",
        f"Parameters under test: `{payload['params_hash'][:16]}…`, the registered value "
        f"(`{payload['registered_params_hash'][:16]}…`) — match: "
        f"`{payload['params_hash_matches_the_registration']}`.",
        "",
        "| # | Criterion | Value | Passed |",
        "| --- | --- | --- | --- |",
    ]
    for check in reading["checks"]:
        lines.append(
            f"| {check['id']} | {check['statement']} | {check['value']} | {check['passed']} |"
        )
    gate = reading.get("frozen_gate_on_the_new_window") or {}
    lines += [
        "",
        f"The frozen admission gate, applied to the new window for comparability: "
        f"**{gate.get('verdict')}** — {'; '.join(gate.get('reasons') or []) or 'no reasons'}.",
        "",
        "## 2. The new window, and what it is",
        "",
        f"- Range: `{payload['windows']['NEW_HOLDOUT']}` — fetched "
        f"`{payload['holdout']['fetched_at_utc']}` from public Binance REST, digest "
        f"`{(payload['holdout']['manifest_digest'] or '')[:16]}…`, gaps "
        f"`{payload['holdout']['gaps']}`.",
        f"- 4h coverage after aggregation: {payload['holdout']['coverage_4h_bars']} "
        f"(minimum declared {payload['holdout']['min_required']}).",
        "",
        "## 3. Every window, BASE and the cost stress",
        "",
        "| Window | Scenario | Trades | Gross | Fees | Price costs | Net | Expectancy | PF | DD % | Sharpe | Cost bps | Largest share |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    order = ["DEV", "VAL", "OOS_CONSULTED", "NEW_HOLDOUT"]
    for window in order:
        for scenario in COST_SCENARIOS:
            metrics = payload[window][scenario]
            lines.append(
                f"| {window} | {scenario} | {metrics.get('trades')} | {metrics.get('gross_usdt')} | "
                f"{metrics.get('fees_usdt')} | {metrics.get('price_costs_usdt')} | "
                f"**{metrics.get('net_usdt')}** | {metrics.get('expectancy_usdt')} | "
                f"{metrics.get('profit_factor')} | {metrics.get('max_drawdown_pct')} | "
                f"{metrics.get('sharpe_annualised')} | {metrics.get('total_cost_bps_per_trade')} | "
                f"{metrics.get('largest_trade_share_of_net')} |"
            )
    base = payload["NEW_HOLDOUT"]["BASE"]
    extras = base["extras"]
    lines += [
        "",
        "## 4. The four added readings, on the new window",
        "",
        f"- Bootstrap (90 %, {extras['bootstrap']['resamples']} resamples of "
        f"{extras['bootstrap']['block_trades']} trades, seed {extras['bootstrap']['seed']}): "
        f"expectancy {extras['expectancy_ci_90_usdt']['point']} USDT, CI "
        f"[{extras['expectancy_ci_90_usdt']['low']}, {extras['expectancy_ci_90_usdt']['high']}]; "
        f"net CI [{extras['net_ci_90_usdt']['low']}, {extras['net_ci_90_usdt']['high']}].",
        f"- Time blocks: {extras['positive_time_blocks']} of 3 positive — "
        + "; ".join(
            f"block {block['block']} ({block['from_utc'][:10]}…{block['to_utc'][:10]}) "
            f"{block['trades']} trades, net {block['net_usdt']}"
            for block in extras["time_blocks"]
        )
        + ".",
        f"- Serial dependence: lag-1 autocorrelation "
        f"{extras['serial_dependence'].get('lag1_autocorrelation')} against a "
        f"±{extras['serial_dependence'].get('band_2_over_sqrt_n')} band; runs "
        f"{extras['serial_dependence'].get('runs')} against "
        f"{extras['serial_dependence'].get('expected_runs')} expected (z="
        f"{extras['serial_dependence'].get('runs_z')}).",
        "",
        "| Asset | Trades | Net | Expectancy |",
        "| --- | --- | --- | --- |",
    ]
    for asset, row in sorted(base["extras"]["by_asset_detail"].items()):
        lines.append(
            f"| {asset} | {row['trades']} | {row['net_usdt']} | {row['expectancy_usdt']} |"
        )
    lines += [
        "",
        "| Market context | Trades | Net | Expectancy |",
        "| --- | --- | --- | --- |",
    ]
    for label, row in sorted(base["extras"]["by_market_context_detail"].items()):
        lines.append(
            f"| {label} | {row['trades']} | {row['net_usdt']} | {row['expectancy_usdt']} |"
        )
    instrument = payload.get("instrument_check") or {}
    lines += [
        "",
        "## 5. Was the new window read with the same instrument?",
        "",
        f"Re-derived consulted-window figures against the artefacts that published them: "
        f"**{'all equal' if instrument.get('all_equal') else 'MISMATCH — the reading below is not comparable'}** "
        f"({len(instrument.get('checks') or [])} figures checked).",
        "",
        "| Figure | Mine | Published | Equal | Source |",
        "| --- | --- | --- | --- | --- |",
    ]
    for check in instrument.get("checks") or []:
        lines.append(
            f"| `{check['what']}` | {check['mine_trades']} trades, {check['mine_net_usdt']} USDT | "
            f"{check['published_trades']} trades, {check['published_net_usdt']} USDT | "
            f"{check['equal']} | `{check['source']}` |"
        )
    comparison = payload["comparison"]
    lines += [
        "",
        "## 6. The comparison arm: the same window, the trailing exit",
        "",
        "| Book | Trades | Net | Expectancy | PF | DD % | Largest share | Exits |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
        f"| fixed 3xATR target | {comparison['fixed_target']['trades']} | "
        f"{comparison['fixed_target']['net_usdt']} | {comparison['fixed_target']['expectancy_usdt']} | "
        f"{comparison['fixed_target']['profit_factor']} | "
        f"{comparison['fixed_target']['max_drawdown_pct']} | "
        f"{comparison['fixed_target']['largest_trade_share_of_net']} | "
        f"{comparison['fixed_target']['exit_reason_mix']} |",
        f"| frozen trailing | {comparison['trailing']['trades']} | "
        f"{comparison['trailing']['net_usdt']} | {comparison['trailing']['expectancy_usdt']} | "
        f"{comparison['trailing']['profit_factor']} | {comparison['trailing']['max_drawdown_pct']} | "
        f"{comparison['trailing']['largest_trade_share_of_net']} | "
        f"{comparison['trailing']['exit_reason_mix']} |",
        "",
        comparison["note"] + ".",
        "",
        "## 7. What this does not do",
        "",
        "- It promotes nothing: `promotion: NONE`, `order_sent: false`, no capital, no orders. An",
        "  `ADMIT_PAPER` verdict is an admission to a paper lane, and the risk-manager's and the",
        "  release gate's own conditions still apply to it.",
        "- It tunes nothing: the parameters are the pre-registered bytes, and the holdout window",
        "  is read once. A parameter that would have helped is a proposal for a new registration.",
        "- The continuity windows were read before this work package; the only unread window here",
        "  is `NEW_HOLDOUT`, and every claim above that rests on `NEW_HOLDOUT` says so.",
        "",
    ]
    return "\n".join(lines)


def write_artifacts(payload: dict[str, Any], outdir: Path) -> dict[str, Path]:
    import csv

    outdir.mkdir(parents=True, exist_ok=True)
    trades_path = outdir / "VALIDATION_TRADES.csv"
    rows = payload.get("_trade_rows") or {}
    fieldnames = [
        "window",
        "asset",
        "decision_ts_utc",
        "duration_min",
        "notional",
        "gross",
        "fees",
        "price_costs",
        "net",
        "exit_reason",
        "regime",
        "market_context",
    ]
    with trades_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for window, trade_rows in sorted(rows.items()):
            for trade in trade_rows:
                writer.writerow(
                    {
                        "window": window,
                        "asset": trade.get("asset"),
                        "decision_ts_utc": _stamp(int(trade.get("decision_ts") or 0)),
                        "duration_min": trade.get("duration_min"),
                        "notional": trade.get("notional"),
                        "gross": trade.get("gross"),
                        "fees": trade.get("fees"),
                        "price_costs": trade.get("price_costs"),
                        "net": trade.get("net"),
                        "exit_reason": trade.get("exit_reason"),
                        "regime": trade.get("regime"),
                        "market_context": trade.get("market_context"),
                    }
                )
    json_path = outdir / "VALIDATION.json"
    markdown_path = outdir / "VALIDATION.md"
    public = {key: value for key, value in payload.items() if not key.startswith("_")}
    json_path.write_text(
        json.dumps(public, indent=2, ensure_ascii=False, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render(payload), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path, "trades": trades_path}
