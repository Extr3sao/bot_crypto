"""WP-EDGE-08 — the registration (RFC-EDGE-008), in machine-readable form.

This module is the code-side copy of ``reports/edge-recovery/WP-EDGE-08/PREREGISTRATION.json``:
the windows, the tracks, the criteria and the multiplicity live here so a runner cannot invent a
window or a threshold, and so a reader can see the registered rule and the executed rule in the
same place. The JSON is the authoritative one — the regression self-test in ``scripts/edge08_verify.py``
re-derives this module's values against it and fails if the two ever drift apart.

The one thing this package is built around: **the resource being read is a cross-section**. Every
time window this project could read on BTC/ETH/SOL has been read (see ``RFC-EDGE-008.md`` §2), but
six liquid majors — AAVE, UNI, MKR, SNX, CRV, SUSHI — have never been the input of a committed
measurement. Their history, 2021-01-01 onwards, is the holdout; their bars live in
``data/edge08/universe-1h/`` with one SHA-256 per shard.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_bot.research.edge01.data import ASSETS

__all__ = [
    "COVERAGE_FLOOR_BARS",
    "CRITERIA",
    "EXISTING_CORPORA",
    "HOLDOUT_SYMBOLS",
    "HOLDOUT_UNIVERSE",
    "KNOWN_UNIVERSE",
    "MIN_TRADES",
    "MULTIPLICITY",
    "PREREGISTRATION",
    "REPO_ROOT",
    "SCHEMA_VERSION",
    "SUPPORTED_CLOCKS",
    "UNIVERSE_MANIFEST",
    "WINDOWS",
    "WP",
]

REPO_ROOT = Path(__file__).resolve().parents[4]
WP = REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-08"
PREREGISTRATION = WP / "PREREGISTRATION.json"
UNIVERSE_MANIFEST = REPO_ROOT / "data" / "edge08" / "universe-1h" / "_FETCH_MANIFEST.json"

SCHEMA_VERSION = "EDGE08_V1"

#: The corpora this repository already holds. A symbol with a shard in one of these is not a
#: holdout: it is a re-read. ``scripts/edge08_fetch_universe.py`` refuses to fetch such a symbol
#: and ``scripts/edge08_verify.py`` re-checks the claim from the manifest.
EXISTING_CORPORA: tuple[str, ...] = (
    "reports/alpha-expansion-v1/data",
    "data/raw/alpha003/price",
    "data/edge07/holdout-1h",
)

#: The unread cross-section: Binance spot majors with no local corpus anywhere in this repository.
#: The first draft carried MKRUSDT; the coverage pre-check in ``scripts/edge08_fetch_universe.py``
#: dropped it *before the registration was committed* because MKR stops trading on 2025-09-15 (the
#: SKY migration) and cannot cover the decisive window 2025-01-01 onwards. KSMUSDT took its place.
HOLDOUT_SYMBOLS: tuple[str, ...] = (
    "AAVEUSDT",
    "UNIUSDT",
    "KSMUSDT",
    "SNXUSDT",
    "CRVUSDT",
    "SUSHIUSDT",
)
HOLDOUT_UNIVERSE: tuple[str, ...] = tuple(symbol[: len(symbol) - 4] for symbol in HOLDOUT_SYMBOLS)

#: The universe every earlier Edge work package measured. Read many times; it is the screening
#: ground here, never the evidence.
KNOWN_UNIVERSE: tuple[str, ...] = tuple(ASSETS)

#: The clocks this work package registers, with the timeframe each book is walked on.
SUPPORTED_CLOCKS: tuple[str, ...] = ("1h", "4h", "1d")


def _ms(year: int, month: int, day: int, hour: int = 0) -> int:
    return int(datetime(year, month, day, hour, tzinfo=UTC).timestamp() * 1000)


#: The three windows of RFC-EDGE-008, declared before any figure of the cross-section existed.
#: They are deliberately the same three windows on both universes, so a screen taken on the known
#: universe and a reading taken on the cross-section are comparable period by period. The decisive
#: one is ``OOS``: 2025-01-01 onwards, unread for the cross-section's symbols.
WINDOWS: dict[str, dict[str, int]] = {
    "DEV": {"start": _ms(2021, 1, 1), "end": _ms(2023, 12, 31, 23)},
    "VAL": {"start": _ms(2024, 1, 1), "end": _ms(2024, 12, 31, 23)},
    "OOS": {"start": _ms(2025, 1, 1), "end": _ms(2026, 10, 14, 8)},
}

#: ``extras`` reads three equal consecutive thirds of a window; the windows above are what it
#: splits, so the labels below are for the report only.
WINDOW_ORDER: tuple[str, ...] = ("DEV", "VAL", "OOS")

#: Minimum trades for the decisive window to carry a verdict at all.
MIN_TRADES = 30

#: Complete bars per asset the decisive window must hold on each clock, before any verdict is
#: computed. Below the floor the reading is ``INSUFFICIENT_EVIDENCE`` for coverage, not measured
#: around (the same rule WP-EDGE-07 applied to its holdout window).
COVERAGE_FLOOR_BARS: dict[str, int] = {"1h": 8_000, "4h": 1_500, "1d": 400}

#: Declared in advance: how many arms this work package reads. Six proposed books plus the three
#: frozen books the comparison needs, all of them reported with their own numbers.
MULTIPLICITY: dict[str, Any] = {
    "proposed": 6,
    "current_comparison": 3,
    "total": 9,
    "note": (
        "every arm is reported; no book is re-parameterised after seeing a result, and a book "
        "that fails the gross screen is not read on the cross-section at all"
    ),
}

#: The registered criteria. ``tracks`` says which track a criterion applies to; a criterion whose
#: ``decisive`` flag is false is reported and never decides.
CRITERIA: dict[str, dict[str, Any]] = {
    "P1": {
        "statement": "trades >= 30 on the decisive window",
        "decisive": True,
        "tracks": ("QUALITY", "ACTIVE"),
    },
    "P2": {
        "statement": "net > 0 at BASE",
        "decisive": True,
        "tracks": ("QUALITY", "ACTIVE"),
    },
    "P3": {
        "statement": "expectancy > 0 at BASE",
        "decisive": True,
        "tracks": ("QUALITY", "ACTIVE"),
    },
    "P4": {
        "statement": "net > 0 at 2X_FEES",
        "decisive": True,
        "tracks": ("QUALITY", "ACTIVE"),
    },
    "P5": {
        "statement": "largest single trade <= 50% of the net",
        "decisive": True,
        "tracks": ("QUALITY", "ACTIVE"),
    },
    "P6": {
        "statement": "at least one positive market context",
        "decisive": True,
        "tracks": ("QUALITY", "ACTIVE"),
    },
    "R1": {
        "statement": "net still > 0 with the largest winner removed",
        "decisive": True,
        "tracks": ("QUALITY", "ACTIVE"),
    },
    "R2": {
        "statement": "net > 0 in at least 2 of the 3 equal time blocks",
        "decisive": True,
        "tracks": ("QUALITY", "ACTIVE"),
    },
    "S1": {
        "statement": "DEV gross > 0 on the cross-section: the entry, not the exit, carries it",
        "decisive": True,
        "tracks": ("QUALITY", "ACTIVE"),
    },
    "F1": {
        "statement": "ACTIVE only: trades/day across the universe >= 3.0",
        "decisive": True,
        "tracks": ("ACTIVE",),
    },
    "F2": {
        "statement": (
            "QUALITY only: trades/day across the universe >= 0.05 (about one trade per asset "
            "every twenty days), reported and decisive as a floor on viability"
        ),
        "decisive": True,
        "tracks": ("QUALITY",),
    },
}

#: The gross screen (C0), applied on the KNOWN universe before the cross-section is read at all.
#: A setup that loses money before any fee cannot be repaired by a fee, so measuring it on unread
#: data would only spend the cross-section — the rule WP-EDGE-07 Track C wrote down.
GROSS_SCREEN: dict[str, Any] = {
    "id": "C0",
    "statement": "gross expectancy > 0 on the known universe's DEV window",
    "consequence": (
        "a book that fails C0 gets REJECT_NO_GROSS_EDGE and is NOT read on the cross-section; "
        "its holdout rows are absent, not zero"
    ),
    "tracks": ("QUALITY", "ACTIVE"),
}

#: Frequency targets, one per track: the same mission number the ACTIVE track was given, and a
#: floor for the QUALITY track that only says the book is not a museum piece.
FREQUENCY_TARGETS: dict[str, float] = {"ACTIVE": 3.0, "QUALITY": 0.05}

#: What each verdict means, and what none of them means.
VERDICTS: dict[str, str] = {
    "ADMIT_PAPER": (
        "every decisive criterion passes on the cross-section's OOS window: admission to paper "
        "only; no live trading, no capital, no promotion beyond a paper lane, and the "
        "risk-manager's and the release gate's own conditions still apply"
    ),
    "REJECT": (
        "a decisive criterion failed with power on the cross-section; the family is reported with "
        "its numbers and is not tuned and re-run on the same window"
    ),
    "INSUFFICIENT_EVIDENCE": (
        "the measurement cannot support a conclusion (unpowered sample with the rest "
        "non-negative, one trade carrying the net, or coverage below the declared floor)"
    ),
    "REJECT_NO_GROSS_EDGE": (
        "the book lost money before any fee on the known universe, so the cross-section was not "
        "read with it"
    ),
}
