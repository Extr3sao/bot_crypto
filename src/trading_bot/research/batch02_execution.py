"""DISCOVERY-BATCH-02 — deeper-window validation of the two Batch-01 leads
plus the DEF-DISCOVERY-001 carry repair (Track C).

POC02-LAUNCH-AND-DISCOVERY-BATCH-02.  This module is EXECUTION GLUE ONLY:
every economic semantic lives in the committed preregistration module
``trading_bot.research.discovery_batch02_spec`` (fingerprinted in
``docs/external-audit-01/DISCOVERY_BATCH_02_PREREGISTRATION.json``, frozen
BEFORE any batch-02 execution).  The carry spec here is evaluated under the
canonical :class:`~trading_bot.research.funding_units.FundingUnitContract`
with the economically correct direction rule (SHORT receives positive
funding; LONG receives negative funding).

Result states: DISCOVERY_PASS / DISCOVERY_FAIL / INSUFFICIENT_SAMPLE /
INSUFFICIENT_DATA / NOT_APPLICABLE / REDUNDANT_CANDIDATE.  No retuning
after results; failures persisted; PAPER promotions = 0.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from trading_bot.market_data.types import OHLCV
from trading_bot.research.discovery_batch02_spec import (
    BATCH02_EVAL_SPECS,
    COST_RATE,
    SLIPPAGE_BPS,
    batch02_eval_fingerprint,
    carry_funding_v2_signals,
    cross_sectional_v2_signals,
    verify_batch01_spec_unchanged,
    volatility_structure_v2_signals,
)
from trading_bot.research.discovery_execution import (
    DiscoveryCell,
    DiscoveryReport,
)
from trading_bot.research.funding_units import (
    canon_funding_interval_s,
    canon_rate_per_period,
    contract_fingerprint,
)
from trading_bot.research.legacy_retro import LegacyRetroHarness
from trading_bot.research.regime import RegimeEngine
from trading_bot.research.retro_execution import (
    _fingerprint_candles,
    _metrics_payload,
    _regime_label,
)

__all__ = [
    "BATCH02_PREREG_JSON",
    "BATCH02_PREREG_SHA256",
    "execute_batch02",
]

_PREREG_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "external-audit-01"
    / "DISCOVERY_BATCH_02_PREREGISTRATION.json"
)
BATCH02_PREREG_JSON = "DISCOVERY_BATCH_02_PREREGISTRATION.json"


def _prereg_sha256() -> str:
    """SHA-256 of the committed preregistration artifact (fail-closed)."""
    try:
        return hashlib.sha256(_PREREG_PATH.read_bytes()).hexdigest()
    except OSError:
        return "PREREG_ARTIFACT_MISSING"


BATCH02_PREREG_SHA256 = _prereg_sha256()


def funding_by_ms_from_rows(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[int, float], int, dict[str, Any]]:
    """Convert real ccxt funding rows to the canonical spec mapping.

    Returns ``(funding_by_ms, interval_s, meta)`` where ``funding_by_ms``
    maps SETTLEMENT TIME (epoch ms) -> decimal rate per funding interval.
    The interval is taken from the observed median consecutive spacing
    (never assumed, per the unit contract).  Malformed units fail closed.
    """
    if not rows:
        return {}, 0, {"funding_observations": 0}
    ts = [int(r["timestamp"]) for r in rows]
    spacings = [ts[i + 1] - ts[i] for i in range(len(ts) - 1)]
    median_ms = statistics.median(spacings) if spacings else 8 * 3_600_000
    interval_s = canon_funding_interval_s(round(median_ms / 1000))
    by_ms: dict[int, float] = {}
    for t, r in zip(ts, (float(r["fundingRate"]) for r in rows), strict=True):
        by_ms[t] = canon_rate_per_period(r, source_unit="decimal_per_interval")
    meta = {
        "funding_observations": len(by_ms),
        "observed_interval_s": interval_s,
        "observed_interval_h": round(interval_s / 3600.0, 3),
        "source": "binanceusdm.fetch_funding_rate_history",
    }
    return by_ms, interval_s, meta


def execute_batch02(
    *,
    fetcher: Any,
    funding_fetcher: Any,
    harness: LegacyRetroHarness,
    window_end_by_tf: Mapping[str, int],
    assets: tuple[str, ...] = ("BTC", "ETH", "SOL"),
    symbol_of: Mapping[str, str] | None = None,
    timeframes: tuple[str, ...] = ("5m", "1h"),
    window_bars: Mapping[str, int] | int = 1000,
    commission_rate: float = COST_RATE,
    slippage_bps: float = SLIPPAGE_BPS,
) -> DiscoveryReport:
    """Execute the three preregistered v2 candidates on INDEPENDENT windows."""
    symbols = symbol_of or {a: f"{a}/USDT:USDT" for a in assets}
    prereg: dict[str, Any] = {
        "batch": "DISCOVERY-BATCH-02",
        "prereg_note": "specs + window committed BEFORE execution; no retuning",
        "prereg_artifact": BATCH02_PREREG_JSON,
        "prereg_sha256": BATCH02_PREREG_SHA256,
        "frozen_protocol": {
            "commission_rate": commission_rate,
            "slippage_bps": slippage_bps,
        },
        "unit_contract_fingerprint": contract_fingerprint(),
        "batch01_spec_verification": verify_batch01_spec_unchanged(),
        "eval_spec_fingerprints": {
            cat: batch02_eval_fingerprint(cat) for cat in BATCH02_EVAL_SPECS
        },
        "windows": {tf: {"end_utc_exclusive_ms": window_end_by_tf[tf]} for tf in timeframes},
    }
    report = DiscoveryReport(
        batch="DISCOVERY-BATCH-02",
        preregistration=prereg,
        dataset_fingerprint="",
        window_meta={},
    )

    candles_by_key: dict[tuple[str, str], list[OHLCV]] = {}
    for asset in assets:
        for tf in timeframes:
            bars = window_bars[tf] if isinstance(window_bars, Mapping) else window_bars
            fetched = fetcher.fetch_ohlcv(symbols[asset], tf, bars, window_end_by_tf[tf])
            candles = fetched if fetched is not None else []
            if len(candles) < 120:
                continue
            candles_by_key[(asset, tf)] = candles
            report.window_meta[f"{asset}:{tf}"] = (
                f"n={len(candles)} first={candles[0].timestamp} last={candles[-1].timestamp}"
            )
    report.dataset_fingerprint = _fingerprint_candles(
        [c for cs in candles_by_key.values() for c in cs]
    )
    engine = RegimeEngine()

    freq_days: dict[str, set[int]] = {}
    freq_opps: dict[str, int] = {}

    def _emit(
        category: str,
        asset: str,
        tf: str,
        candles: list[OHLCV],
        trades: Sequence[Any],
        extra: dict[str, Any] | None = None,
    ) -> None:
        regime = _regime_label(engine.detect(candles))
        n = len(trades)
        net_returns = [t.net_return for t in trades]
        payload = _metrics_payload(list(trades))
        if payload.get("insufficient_sample"):
            status, reason = "INSUFFICIENT_SAMPLE", f"n={n} < harness MIN_SAMPLE"
        else:
            verdict = harness.evaluate_cell(
                strategy_id=category,
                asset=asset,
                timeframe=tf,
                regime=regime,
                trade_returns=tuple(net_returns),
                n_trades=n,
            )
            status = {
                "VALIDATED_CELL": "DISCOVERY_PASS",
                "FAILED_CELL": "DISCOVERY_FAIL",
            }.get(verdict.status, verdict.status)
            reason = verdict.reason
        if extra:
            payload.update(extra)
        report.cells.append(
            DiscoveryCell(
                category=category,
                asset=asset,
                timeframe=tf,
                regime=regime,
                status=status,
                n_trades=n,
                metrics_json=json.dumps(payload, sort_keys=True),
                reason=reason,
                spec_fingerprint=prereg["eval_spec_fingerprints"][category],
            )
        )
        freq_opps[category] = freq_opps.get(category, 0) + n
        freq_days.setdefault(category, set()).update(t.entry_ts // 86_400_000 for t in trades)

    for (asset, tf), candles in sorted(candles_by_key.items()):
        # volatility_structure_v2 — SAME signal as Batch 01, deeper window
        vs = volatility_structure_v2_signals(
            candles, cost_rate=commission_rate, slippage_bps=slippage_bps
        )
        _emit("volatility_structure_v2", asset, tf, candles, vs.trades)

        # carry_funding_v2 — repaired spec on REAL funding data (C6)
        rows = funding_fetcher(symbols[asset]) or []
        by_ms, interval_s, fmeta = funding_by_ms_from_rows(rows)
        carry_note: dict[str, Any] = {
            "unit_contract": "FUNDING-UNITS-CANONICAL-V1",
            **fmeta,
        }
        if len(by_ms) < 2:
            _emit(
                "carry_funding_v2",
                asset,
                tf,
                candles,
                [],
                {"insufficient_data": "no real funding observations in window", **carry_note},
            )
            continue
        carry = carry_funding_v2_signals(
            candles,
            by_ms,
            cost_rate=commission_rate,
            slippage_bps=slippage_bps,
            funding_interval_s=interval_s,
        )
        _emit(
            "carry_funding_v2",
            asset,
            tf,
            candles,
            carry.trades,
            {
                "direction_rule": "SHORT when mean funding > 0 (true carry); LONG when < 0",
                **carry_note,
            },
        )

    # cross_sectional_v2 per timeframe + preregistered redundancy protocol
    for tf in timeframes:
        series = {a: candles_by_key[(a, tf)] for a in assets if (a, tf) in candles_by_key}
        universe_key = "+".join(assets)
        if len(series) < 2 or len(series) != len(assets):
            report.cells.append(
                DiscoveryCell(
                    category="cross_sectional_v2",
                    asset=universe_key,
                    timeframe=tf,
                    regime="UNCLASSIFIED",
                    status="NOT_APPLICABLE",
                    n_trades=0,
                    metrics_json=json.dumps({"n": 0, "reason": "universe incomplete"}),
                    reason="cross-sectional rotation requires the full >=2-asset universe",
                    spec_fingerprint=prereg["eval_spec_fingerprints"]["cross_sectional_v2"],
                )
            )
            continue
        cs = cross_sectional_v2_signals(
            series, cost_rate=commission_rate, slippage_bps=slippage_bps
        )
        _emit(
            "cross_sectional_v2",
            universe_key,
            tf,
            series[assets[0]],
            cs.trades,
            _redundancy_evidence(series),
        )

    report.frequency = {
        "note": "Track E: raw frequency here; incremental/NO_SIGNAL overlap "
        "analyzed in the batch report",
        "opportunities_by_category": freq_opps,
        "days_with_opportunity_by_category": {k: len(v) for k, v in freq_days.items()},
    }
    return report


def _redundancy_evidence(
    series: Mapping[str, list[OHLCV]],
) -> dict[str, Any]:
    """C4 redundancy protocol: persistence, turnover, momentum correlation."""
    min_len = min(len(v) for v in series.values())
    align = {a: v[len(v) - min_len :] for a, v in series.items()}
    lookback = 24
    leaders: list[str] = []
    for i in range(lookback, min_len):
        rets = {a: align[a][i].close / align[a][i - lookback].close - 1.0 for a in align}
        leaders.append(max(rets, key=lambda a: rets[a]))
    if len(leaders) < 2:
        return {"redundancy": "INSUFFICIENT_DATA"}
    changes = sum(1 for i in range(1, len(leaders)) if leaders[i] != leaders[i - 1])
    persistence = 1.0 - changes / (len(leaders) - 1)
    turnover_per_100 = changes / (len(leaders) - 1) * 100.0
    strat_ret: list[float] = []
    mom_ret: list[float] = []
    for i in range(lookback + 1, min_len):
        held = leaders[i - lookback]
        strat_ret.append(align[held][i].close / align[held][i - 1].close - 1.0)
        mom_ret.append(
            statistics.mean(align[a][i].close / align[a][i - 1].close - 1.0 for a in align)
        )
    corr = _pearson(strat_ret, mom_ret)
    redundant = corr is not None and corr > 0.8 and persistence < 0.6
    return {
        "redundancy": {
            "leader_persistence": round(persistence, 4),
            "turnover_per_100_bars": round(turnover_per_100, 3),
            "momentum_family_correlation": (round(corr, 4) if corr is not None else None),
            "verdict": "REDUNDANT_CANDIDATE" if redundant else "DISTINCT_EVIDENCE",
        }
    }


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    n = min(len(xs), len(ys))
    if n < 10:
        return None
    xs, ys = list(xs)[:n], list(ys)[:n]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    return float(sxy / (sxx * syy) ** 0.5)
