"""RFC-030 §24 — beta diagnostic over the real frozen corpus (evidence only).

Runs the frozen EXP-ARP-023 book construction over the PIT ``ARP-006-UNIVERSE-v1``
universe and measures the distribution of ``beta_book``. It reads **DEV +
VALIDATION only** — the OOS window is never touched — and it changes nothing about
the frozen contract: ``beta_tolerance = 0.10`` is reported, never optimised.

Usage::

    .venv/Scripts/python.exe scripts/rfc030_beta_diagnostic.py

Writes ``reports/rfc030/BETA_DIAGNOSTIC.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

from trading_bot.research.diversified.data import (
    MS_PER_DAY,
    VAL_END_MS,
    available_symbols,
    corpus_digest,
    listing_times,
    load_corpus_range,
)
from trading_bot.research.diversified.universe import DynamicAssetUniverse, UniverseConfig
from trading_bot.research.pair.beta import beta_diagnostic

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports/rfc030/BETA_DIAGNOSTIC.json"

#: frozen EXP-ARP-023 parameters — never overridden for coverage.
FORMATION_DAYS = 30
BETA_WINDOW_DAYS = 60
TOP_K = 10
MIN_MEMBERS = 20
REBALANCE_DAYS = 7
BETA_TOLERANCE = 0.10
MARKET_SYMBOL = "BTCUSDT"

#: diagnostic start: 2021-01-04 00:00 UTC (a Monday), the same start as the prior run.
START_MS = 1_609_718_400_000


def _weekly_decision_times(start_ms: int, end_ms: int) -> list[int]:
    return list(range(start_ms, end_ms, REBALANCE_DAYS * MS_PER_DAY))


def main() -> int:
    symbols = available_symbols()
    bars = load_corpus_range(symbols, 0, VAL_END_MS)  # DEV + VALIDATION only
    closes_by_symbol = {s: {b.timestamp: b.close for b in bs} for s, bs in bars.items()}
    digest = corpus_digest()

    universe = DynamicAssetUniverse(bars, listing_times(), digest, UniverseConfig())

    dev_times = _weekly_decision_times(START_MS, 1_704_067_200_000)  # .. 2024-01-01
    dev_val_times = _weekly_decision_times(START_MS, VAL_END_MS)

    scopes: dict[str, dict[str, object]] = {}
    for name, times in (("DEV", dev_times), ("DEV_VALIDATION", dev_val_times)):
        diag = beta_diagnostic(
            closes_by_symbol,
            times,
            top_k=TOP_K,
            min_members=MIN_MEMBERS,
            formation_days=FORMATION_DAYS,
            beta_window_days=BETA_WINDOW_DAYS,
            beta_tolerance=BETA_TOLERANCE,
            market_symbol=MARKET_SYMBOL,
            universe=universe,
        )
        payload = diag.as_dict()
        payload.pop("betas", None)  # keep the artifact small; distribution is summarised
        scopes[name] = payload
        print(f"[{name}] {json.dumps(payload, indent=2)}")

    report: dict[str, object] = {
        "corpus_digest": digest,
        "universe_version": "ARP-006-UNIVERSE-v1",
        "frozen_params": {
            "formation_days": FORMATION_DAYS,
            "beta_window_days": BETA_WINDOW_DAYS,
            "top_k": TOP_K,
            "min_members": MIN_MEMBERS,
            "rebalance_days": REBALANCE_DAYS,
            "beta_tolerance": BETA_TOLERANCE,
            "market_symbol": MARKET_SYMBOL,
        },
        "oos_opened": False,
        "scopes": scopes,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
