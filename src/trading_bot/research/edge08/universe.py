"""WP-EDGE-08 — the two universes, and the data plane that keeps them apart.

Three objects, and the difference between them is the whole point of this work package:

* :func:`known_corpus` — BTC, ETH, SOL from the frozen local corpora, aggregated by the campaign's
  own ``resample``. Read many times by earlier work packages: it is the **screening ground**.
* :func:`cross_section_corpus` — AAVE, UNI, MKR, SNX, CRV, SUSHI from
  ``data/edge08/universe-1h/``, fetched once from public Binance REST with a SHA-256 per shard.
  No committed artefact of this repository has ever been measured on these symbols: it is the
  **evidence**.
* :func:`benchmark_regime_rows` — the market-context label (BULL/BEAR/SIDEWAYS), computed from BTC
  alone by the frozen ``edge01.features`` rule and read *as of* each decision instant. It is a
  label for a breakdown table, never an input to a signal, and it is the same label for every arm.

Nothing here interpolates: a bucket is emitted only when all of its source hours are present and
contiguous (the campaign's ``resample``), so a 4h or 1d bar here is one that could have existed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trading_bot.research.edge01 import campaign as C
from trading_bot.research.edge01.campaign import _Corpus
from trading_bot.research.edge01.data import OHLCVBar, load_1h, resample
from trading_bot.research.edge01.features import (
    MARKET_REGIME_RULE,
    market_regime_at,
    market_regime_series,
)
from trading_bot.research.edge08.registration import (
    HOLDOUT_UNIVERSE,
    KNOWN_UNIVERSE,
    REPO_ROOT,
    UNIVERSE_MANIFEST,
)

__all__ = [
    "UNIVERSE_DIR",
    "benchmark_regime_rows",
    "context_for_trade",
    "coverage",
    "cross_section_corpus",
    "holdout_manifest",
    "known_corpus",
    "local_shards_for",
]

UNIVERSE_DIR = UNIVERSE_MANIFEST.parent


def holdout_manifest() -> dict[str, Any]:
    """The cross-section's provenance: per-shard SHA-256, ranges, counts and gaps."""
    if not UNIVERSE_MANIFEST.is_file():
        return {}
    payload: dict[str, Any] = json.loads(UNIVERSE_MANIFEST.read_text(encoding="utf-8"))
    return payload


def local_shards_for(asset: str) -> list[str]:
    """Every local corpus file holding bars for ``asset``, relative to the repository root.

    Used by the verifier to re-check the holdout claim from disk rather than from the manifest's
    own word: a symbol with a shard outside ``data/edge08`` is not a holdout.
    """
    roots = (
        REPO_ROOT / "reports" / "alpha-expansion-v1" / "data",
        REPO_ROOT / "data" / "raw" / "alpha003" / "price",
        REPO_ROOT / "data" / "edge07" / "holdout-1h",
    )
    found: list[str] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.glob(f"{asset}USDT*")):
            found.append(str(path.relative_to(REPO_ROOT)).replace("\\", "/"))
    return found


def _corpus_from_dir(assets: tuple[str, ...], directory: Path, timeframe: str) -> _Corpus:
    bars_by_asset: dict[str, list[OHLCVBar]] = {}
    provenance: dict[str, Any] = {}
    for asset in assets:
        hourly = load_1h(asset, corpus=directory)
        bars = hourly if timeframe == "1h" else resample(hourly, timeframe)
        bars_by_asset[asset] = list(bars.bars)
        provenance[asset] = {
            "symbol": asset,
            "timeframe": timeframe,
            "bars": len(bars.bars),
            "first_ts": bars.first_ts,
            "last_ts": bars.last_ts,
            "hourly_bars": hourly.n,
            "shard_sha256": bars.sha256,
            "sources": list(bars.sources),
        }
    return _Corpus(bars_by_asset=bars_by_asset, context=None, provenance=provenance)


def known_corpus(timeframe: str) -> _Corpus:
    """BTC/ETH/SOL at ``timeframe``, from the frozen corpora (the screening ground)."""
    return _corpus_from_dir(
        KNOWN_UNIVERSE, REPO_ROOT / "reports" / "alpha-expansion-v1" / "data", timeframe
    )


def cross_section_corpus(timeframe: str) -> _Corpus:
    """The unread cross-section at ``timeframe``, from its own fetched shards."""
    return _corpus_from_dir(HOLDOUT_UNIVERSE, UNIVERSE_DIR, timeframe)


def coverage(corpus: _Corpus, window: dict[str, int]) -> dict[str, int]:
    """Complete bars per asset inside ``window`` — the count the coverage floor is checked on."""
    return {
        asset: sum(1 for bar in bars if window["start"] <= bar.ts <= window["end"])
        for asset, bars in sorted(corpus.bars_by_asset.items())
    }


def benchmark_regime_rows() -> tuple[tuple[Any, ...], dict[str, Any]]:
    """The benchmark's own regime labels, built once from the longest BTC series available.

    The frozen 1h corpus is continued with the cross-section's own BTC... which does not exist:
    this package fetches six other symbols, not BTC, so the benchmark series is the frozen one
    plus the WP-EDGE-07 holdout shards when they are present (they cover 2026-03-01 onwards). The
    label is read as of the decision instant by ``market_regime_at``, so extending the series
    lengthens the history the rule sees; it never looks forward.
    """
    frozen = load_1h("BTC")
    parts: list[OHLCVBar] = list(frozen.bars)
    sources = list(frozen.sources)
    extra = REPO_ROOT / "data" / "edge07" / "holdout-1h"
    if extra.is_dir():
        fresh = load_1h("BTC", corpus=extra)
        parts.extend(fresh.bars)
        sources.extend(fresh.sources)
    daily = resample(
        type(frozen)(
            symbol="BTC",
            timeframe="1h",
            bars=tuple(parts),
            sources=tuple(sources),
            sha256=frozen.sha256,
        ),
        "1d",
    )
    rows = tuple(market_regime_series(list(daily.bars)))
    meta = {
        "benchmark": "BTC",
        "rule": MARKET_REGIME_RULE,
        "timeframe": "1d (complete 24-hour buckets only)",
        "series": (
            "the frozen 1h corpus, continued with the WP-EDGE-07 holdout shards when present"
        ),
        "days": len(rows),
        "sources": sources,
    }
    return rows, meta


def context_for_trade(rows: tuple[Any, ...], decision_ts: int) -> str:
    """The benchmark label as of one decision instant (a reading, never a signal input)."""
    return market_regime_at(rows, decision_ts)


def campaign_metrics(**kwargs: Any) -> dict[str, Any]:
    """The frozen campaign's own metric definitions, re-exported so every arm uses one roll-up."""
    return C._metrics(**kwargs)
