"""EDGE-03 forward plan — what was declared BEFORE any new bar was fetched.

WP-EDGE-01 and WP-EDGE-02 measured a corpus that stops at a fixed instant. This lane
does the opposite: it stops looking backwards and starts *observing*. Everything that
decides whether an observation counts is written down here, first, so a later reader can
check the rule against the result instead of trusting the order the work happened in.

Three things are frozen and pinned by value, not by convention:

* **the frozen corpus ends.** The 1h shards used by the trend campaign stop at
  ``2026-02-28T23:00:00Z`` (bar OPEN time); the 15m shards stop at
  ``2026-10-07T11:30:00Z``. ``assert_frozen_corpus`` re-reads them and fails loudly if
  the local bytes moved, so a forward bar can never be confused with a frozen one.
* **the ruleset.** ``assert_frozen_params`` re-hashes ``FROZEN_PARAMS`` from scratch and
  compares the result with both the imported constant and the digest the campaign
  published, so a forward run cannot silently measure a tuned rule.
* **the decision rules.** ``FORWARD_DECISION`` restates, before the first fetch, what
  counts as an admissible bar, what a gap is, what the shadow is allowed to claim and
  which observation length is enough to say anything at all.

Nothing in this lane can place an order, and no verdict produced here promotes a
strategy: ``promotion`` is fixed to ``NONE`` and is not a parameter.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from trading_bot.research.edge01.candidates import FROZEN_PARAMS, PARAMS_HASH
from trading_bot.research.edge01.data import ASSETS, load_1h, load_15m

__all__ = [
    "FORWARD_DECISION",
    "FORWARD_PLAN",
    "FROZEN_1H_END_MS",
    "FROZEN_15M_END_MS",
    "FROZEN_SHARD_SHA256",
    "MIN_OBSERVATION_DAYS",
    "PARAMS_HASH_PUBLISHED_BY",
    "SOURCE",
    "assert_frozen_corpus",
    "assert_frozen_params",
    "observation_floor",
]

#: Public, read-only market data. No credentials, no order endpoint, no private host.
SOURCE = "BINANCE_PUBLIC_REST:/api/v3/klines"

#: Where the campaign published the digest of the ruleset it measured. The forward lane
#: pins itself to that file: the ruleset is compared against a value someone else wrote
#: down before this lane existed, not against a value this lane could restate at will.
PARAMS_HASH_PUBLISHED_BY = "reports/edge-recovery/WP-EDGE-01/oos-trend-4h/OOS_TREND.json"

#: The same recipe the candidates module hashes with, restated so the forward lane can
#: re-derive the digest instead of trusting the imported constant.
PARAMS_HASH_RECIPE = "sha256(json.dumps(FROZEN_PARAMS, sort_keys=True, separators=(',', ':')))"

#: Last bar OPEN time of each frozen corpus (ms UTC), read off the shard files that
#: WP-EDGE-01/02 measured. A forward bar is admissible only if it is strictly later.
FROZEN_1H_END_MS = 1_772_319_600_000  # 2026-02-28T23:00:00Z
FROZEN_15M_END_MS = 1_791_372_600_000  # 2026-10-07T11:30:00Z

#: Digest of the exact shard bytes each frozen corpus was read from, per asset. These
#: are the values the earlier WPs' artefacts were tied to; if they move, the forward
#: lane refuses to run rather than compare new bars against a different past.
FROZEN_SHARD_SHA256: dict[str, str] = {
    "1h:BTC": "f4d16c3664c142d1",
    "1h:ETH": "365046d4738aa7b1",
    "1h:SOL": "847d8eb45eafebd8",
    "15m:BTC": "cd1d2ea256a97f7c",
    "15m:ETH": "b8fd5744cc66f635",
    "15m:SOL": "72a268137cbe944b",
}

#: A UTC date counts as one independent observation day for an asset only if the store
#: holds at least this fraction of the bars the calendar expects for it that day: a day
#: the feed cut in half is not a day of evidence.
OBSERVATION_COVERAGE = 0.90

#: Below this many independent observation days the lane reports
#: ``INSUFFICIENT_OBSERVATION`` and refuses to read a metric as anything but provisional.
MIN_OBSERVATION_DAYS = 60

#: Frozen flat spread: one day of 1h bars for the days guard, one bar count for 15m.
BARS_PER_DAY: dict[str, int] = {"1h": 24, "15m": 96}

FORWARD_PLAN: dict[str, Any] = {
    "id": "FWD-EDGE01",
    "question": (
        "Once the frozen corpus stops, do the frozen rulesets keep printing the same "
        "kind of decisions on the bars that close afterwards, and can the whole chain "
        "be run again from scratch without a human in the loop?"
    ),
    "source": SOURCE,
    "assets": list(ASSETS),
    "timeframes": ["1h", "15m"],
    "frozen": {
        "params_hash": PARAMS_HASH,
        "params_hash_published_by": f"{PARAMS_HASH_PUBLISHED_BY}#params_hash",
        "params_hash_recipe": PARAMS_HASH_RECIPE,
        "1h_end_ms": FROZEN_1H_END_MS,
        "15m_end_ms": FROZEN_15M_END_MS,
    },
    "strategies": {
        # The shadow runs the SAME objects the campaign ran, on the SAME cost plane.
        "edge_trend_01_4h": {
            "primary": True,
            "timeframe": "4h",
            "built_by": "resample(1h)",
            "promotion_candidate": True,
            "note": "the candidate WP-EDGE-01/02 put on the table; shadowed as the primary",
        },
        "edge_trend_01_1d": {
            "primary": False,
            "timeframe": "1d",
            "built_by": "resample(1h)",
            "promotion_candidate": False,
            "note": "read for context only; a 1d bar closes once a day, so it rarely prints",
        },
        "edge_intra_01": {
            "primary": False,
            "timeframe": "15m",
            "built_by": "native 15m",
            "promotion_candidate": False,
            "note": "RESEARCH ONLY: the intraday funnel was rejected by the campaign",
        },
        "edge_intra_02": {
            "primary": False,
            "timeframe": "15m",
            "built_by": "native 15m",
            "promotion_candidate": False,
            "note": "RESEARCH ONLY: rejected by the campaign",
        },
        "edge_intra_01r": {
            "primary": False,
            "timeframe": "15m",
            "built_by": "native 15m, plan executed at the level (market arm)",
            "promotion_candidate": False,
            "note": "RESEARCH ONLY: the H6 entry variant, re-read forward, never promoted",
        },
    },
    "cost_plane": {
        "scenarios": ["BASE", "2X_FEES", "ADVERSE"],
        "model": "COST_MODEL_V3 via trading_bot.research.edge01.costs",
        "note": "identical to the campaign: a forward reading is not allowed a cheaper venue",
    },
    "window_rule": (
        "a decision belongs to the forward window only if its bar opened strictly after "
        "the frozen end for its source timeframe; the frozen prefix is still fed to the "
        "candidate so its EMA/ATR warm-up is the same one the campaign used"
    ),
    "promotion": "NONE — this lane reports observations; it cannot admit a strategy",
}

#: Declared before the first fetch. Each entry is a rule a reader can check against the
#: artefacts, not a description of intent.
FORWARD_DECISION: dict[str, Any] = {
    "admissible_bar": (
        "ts is on the timeframe's own UTC grid (ts % interval == 0), ts is strictly "
        "greater than the frozen end of its source timeframe, and the bar is CLOSED at "
        "the instant of the fetch (ts + interval <= server time). An open bar is counted "
        "and dropped, never stored as if it had closed."
    ),
    "no_retrospective_change": (
        "the forward store is append-only: a bar is written once, and a later fetch that "
        "disagrees with a stored bar is recorded as a revision and does NOT overwrite it. "
        "The corpus the earlier WPs measured is never written to at all."
    ),
    "gap": (
        "a missing grid slot between two stored bars is a gap. It is COUNTED and NEVER "
        "filled, interpolated or forward-filled; a decision bar that would sit inside a "
        "gap is still evaluated on the bars that exist, and any candidate that needs the "
        "missing history simply refuses (its own warm-up rule), which is visible."
    ),
    "duplicate": "the same ts seen twice in one fetch, or already stored: counted, kept once.",
    "out_of_order": "a fetched row earlier than the last stored ts: counted and rejected.",
    "stale": (
        "no bar has closed since the last stored bar: the run records "
        "``no_new_data`` with the instant it checked, and reports zero new days."
    ),
    "incomplete": (
        "a row whose OHLC block is internally impossible (high < low, high < open/close, "
        "low > open/close, non-positive price, non-finite) is counted and NOT stored; a "
        "corpus that stores a corrupt bar cannot be audited later."
    ),
    "shadow_is_hypothetical": (
        "every fill the shadow books carries ``hypothetical: true`` and "
        "``order_sent: false``. Nothing in this lane has an exchange client."
    ),
    "observation_day": (
        f"a UTC date with at least {OBSERVATION_COVERAGE:.0%} of the bars the calendar "
        "expects for that timeframe, for that asset."
    ),
    "verdict_vocabulary": {
        "OBSERVATION_RUNNING": (
            f"fewer than {MIN_OBSERVATION_DAYS} independent observation days: the lane "
            "reports what it saw and claims nothing about the edge."
        ),
        "OBSERVATION_STALLED": "no new closed bar existed at the instant of the run.",
        "PARITY_FAILED": "the research budget and the runtime engine disagreed on an "
        "entry the runtime would have refused under a rule the research budget models.",
    },
    "not_claimed": (
        "a working forward pipeline is not evidence of an edge and not an admission: no "
        "metric computed here is compared against an admission criterion."
    ),
}


def observation_floor() -> dict[str, Any]:
    """The declared observation floor, as data (so a report can print it, not paraphrase)."""
    return {
        "min_observation_days": MIN_OBSERVATION_DAYS,
        "coverage_required": OBSERVATION_COVERAGE,
        "bars_per_day": dict(BARS_PER_DAY),
        "note": "below the floor the lane's verdict is INSUFFICIENT_OBSERVATION by construction",
    }


def assert_frozen_corpus() -> dict[str, Any]:
    """Re-read the frozen corpora and refuse to go forward if their bytes moved.

    Returns the observed provenance (``first_ts``/``last_ts``/``sha256`` per series) so
    the caller can publish what it checked rather than asserting it checked.
    """
    seen: dict[str, Any] = {}
    for asset in ASSETS:
        for timeframe, loader, pinned_end in (
            ("1h", load_1h, FROZEN_1H_END_MS),
            ("15m", load_15m, FROZEN_15M_END_MS),
        ):
            corpus = loader(asset)
            key = f"{timeframe}:{asset}"
            digest = corpus.sha256[:16]
            expected = FROZEN_SHARD_SHA256[key]
            if digest != expected:
                raise AssertionError(
                    f"the frozen {timeframe} corpus for {asset} changed: shard digest is "
                    f"{digest}, the frozen value is {expected}. A forward bar must not be "
                    f"compared against a different past; refusing to run."
                )
            if corpus.last_ts != pinned_end:
                raise AssertionError(
                    f"the frozen {timeframe} corpus for {asset} ends at {corpus.last_ts}, "
                    f"the frozen end is {pinned_end}."
                )
            seen[key] = {
                "bars": corpus.n,
                "first_ts": corpus.first_ts,
                "last_ts": corpus.last_ts,
                "sha256_prefix16": digest,
            }
    return seen


def assert_frozen_params(repo_root: Path | None = None) -> dict[str, Any]:
    """Re-derive the ruleset digest and pin it to the value the campaign published.

    A forward lane that claims it cannot measure a tuned rule is worth exactly what it
    enforces, so this function does three things and reports all three:

    * it re-hashes ``FROZEN_PARAMS`` from scratch, with the recipe restated in this module,
      instead of trusting the imported ``PARAMS_HASH`` constant;
    * it compares that digest with the imported constant;
    * it reads the digest the campaign PUBLISHED and compares it again.

    A disagreement raises: it would mean the ruleset loaded in this process is not the
    ruleset whose results WP-EDGE-01/02 recorded, and a forward reading of a different
    ruleset is not a forward reading of the frozen one.

    ``repo_root`` exists for a rehearsal that pins against a copied tree; left out, the
    pin resolves against the checkout this module was loaded from, which is the only tree
    that can answer for the ruleset in memory.
    """
    base = Path(__file__).resolve().parents[4] if repo_root is None else Path(repo_root)
    published_path = base / PARAMS_HASH_PUBLISHED_BY
    canonical = json.dumps(FROZEN_PARAMS, sort_keys=True, separators=(",", ":"))
    rederived = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if rederived != PARAMS_HASH:
        raise AssertionError(
            f"the ruleset digest re-derived here ({rederived}) is not the one the "
            f"candidates module publishes ({PARAMS_HASH}); the frozen parameters moved."
        )
    if not published_path.is_file():
        raise AssertionError(
            f"the published ruleset digest is missing at {PARAMS_HASH_PUBLISHED_BY}: the "
            f"forward lane cannot pin the ruleset against a value nobody wrote down."
        )
    published = json.loads(published_path.read_text(encoding="utf-8"))
    published_hash = published.get("params_hash")
    if published_hash != rederived:
        raise AssertionError(
            f"the campaign published params_hash {published_hash}, this process re-derives "
            f"{rederived}: refusing to read a tuned ruleset forward."
        )
    return {
        "params_hash": rederived,
        "imported_params_hash": PARAMS_HASH,
        "published_params_hash": published_hash,
        "published_by": f"{PARAMS_HASH_PUBLISHED_BY}#params_hash",
        "recipe": PARAMS_HASH_RECIPE,
        "agrees_with_imported_constant": rederived == PARAMS_HASH,
        "agrees_with_publication": published_hash == rederived,
    }
