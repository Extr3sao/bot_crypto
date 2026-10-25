#!/usr/bin/env python
"""WP-EDGE-08A — the cross-section, its provenance, and the proof that it is unread.

Writes ``reports/edge-recovery/WP-EDGE-08/UNIVERSE.{json,md}`` from three readings, none of which
is a strategy result:

1. the fetch manifest — one SHA-256 per shard, the requested range, the bar counts and the gaps;
2. **coverage** — how many complete bars each symbol actually has inside each declared window, on
   each of the three clocks this work package walks. A window with holes is a window whose reading
   would be an artefact of the feed, so the numbers are published before anything is measured;
3. **disjointness** — the holdout claim, checked from disk and from ``git grep`` over tracked files,
   with any violation named rather than argued away.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge08.disjointness import disjointness_report  # noqa: E402
from trading_bot.research.edge08.registration import (  # noqa: E402
    COVERAGE_FLOOR_BARS,
    HOLDOUT_SYMBOLS,
    SCHEMA_VERSION,
    SUPPORTED_CLOCKS,
    WINDOWS,
    WP,
)
from trading_bot.research.edge08.universe import (  # noqa: E402
    cross_section_corpus,
    holdout_manifest,
)

JSON_PATH = WP / "UNIVERSE.json"
MD_PATH = WP / "UNIVERSE.md"


def stamp() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp_ms(instant_ms: int) -> str:
    return datetime.fromtimestamp(instant_ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build() -> dict[str, Any]:
    manifest = holdout_manifest()
    coverage: dict[str, Any] = {}
    for timeframe in SUPPORTED_CLOCKS:
        corpus = cross_section_corpus(timeframe)
        coverage[timeframe] = {
            "per_asset_bars_in_window": {
                window: {
                    asset: sum(
                        1
                        for bar in bars
                        if WINDOWS[window]["start"] <= bar.ts <= WINDOWS[window]["end"]
                    )
                    for asset, bars in sorted(corpus.bars_by_asset.items())
                }
                for window in WINDOWS
            },
            "per_asset_total": {
                asset: len(bars) for asset, bars in sorted(corpus.bars_by_asset.items())
            },
            "screen_failure": None,
        }
    decisive = "OOS"
    for timeframe, reading in coverage.items():
        floor = COVERAGE_FLOOR_BARS[timeframe]
        short = {
            asset: count
            for asset, count in reading["per_asset_bars_in_window"][decisive].items()
            if count < floor
        }
        if short:
            reading["screen_failure"] = {"window": decisive, "floor": floor, "short": short}
    disjoint = disjointness_report(HOLDOUT_SYMBOLS)
    return {
        "schema_version": SCHEMA_VERSION,
        "work_package": "WP-EDGE-08",
        "as_of_utc": stamp(),
        "claim": (
            "these six symbols have never been the input of a committed measurement in this "
            "repository, so their history is an unread cross-section"
        ),
        "source": manifest.get("source"),
        "fetched_at_utc": manifest.get("fetched_at_utc"),
        "requested_range": manifest.get("requested_range"),
        "corpus_digest": manifest.get("corpus_digest"),
        "corpus_directory": "data/edge08/universe-1h",
        "per_symbol": manifest.get("symbols"),
        "totals": manifest.get("totals"),
        "gaps": {
            symbol: {
                "gaps": (entry or {}).get("gaps"),
                "first_examples": (entry or {}).get("gap_examples"),
            }
            for symbol, entry in sorted((manifest.get("symbols") or {}).items())
        },
        "coverage": coverage,
        "disjointness": disjoint,
        "verdict": (
            "HOLDOUT_CLAIM_HOLDS"
            if disjoint["claim_holds"]
            else "HOLDOUT_CLAIM_FAILS: a tracked artefact already reads one of these symbols"
        ),
        "windows": {
            window: {"start_utc": stamp_ms(value["start"]), "end_utc": stamp_ms(value["end"])}
            for window, value in WINDOWS.items()
        },
        "coverage_floor_bars_per_asset": COVERAGE_FLOOR_BARS,
        "limitations": [
            "the corpus is one venue's public REST feed, 1h bars, capped at the last closed hour "
            "before the fetch; gaps are left absent and counted, never filled",
            "the cross-section has no BTC in it by construction: a benchmark series is built from "
            "the frozen BTC corpus, and the label it produces is read out of the run, never into a "
            "signal",
            "no order book is modelled per symbol: the cost plane is venue-level and the ADVERSE "
            "scenario is the sensitivity that speaks to thinner names",
        ],
    }


def render(payload: dict[str, Any]) -> str:
    lines = [
        "# WP-EDGE-08A — the unread cross-section",
        "",
        f"*Read at `{payload['as_of_utc']}` (`{payload['schema_version']}`). Claim: "
        f"{payload['claim']}.*",
        "",
        "## 1. The verdict of the disjointness check",
        "",
        f"**{payload['verdict']}** — {len(payload['disjointness']['violations'])} violation(s), "
        f"allowed kinds: {', '.join(payload['disjointness']['allowed_kinds'])}.",
        "",
        f"Method: {payload['disjointness']['method']}.",
        "",
    ]
    violations = payload["disjointness"]["violations"]
    if violations:
        lines += ["| Symbol | File | Kind |", "| --- | --- | --- |"]
        for row in violations:
            lines.append(f"| {row['symbol']} | `{row['path']}` | {row['kind']} |")
        lines.append("")
    lines += [
        "| Symbol | Tracked files mentioning it | Kinds |",
        "| --- | --- | --- |",
    ]
    for symbol, entries in sorted(payload["disjointness"]["references"].items()):
        kinds = ", ".join(sorted({entry["kind"] for entry in entries})) or "none"
        lines.append(f"| {symbol} | {len(entries)} | {kinds} |")
    lines += [
        "",
        "## 2. What was fetched, and how much of it is there",
        "",
        f"- Source: `{payload['source']}`, fetched `{payload['fetched_at_utc']}`, range "
        f"`{payload['requested_range']}`.",
        f"- Corpus digest (per-shard SHA-256, sorted by symbol): `{payload['corpus_digest']}`.",
        f"- Totals: {payload['totals']}.",
        "",
        "| Symbol | Bars | First | Last | Gaps | Coverage % | Shard bytes | SHA-256 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for symbol, entry in sorted((payload["per_symbol"] or {}).items()):
        lines.append(
            f"| {symbol} | {entry['bars']} | {entry['first_utc']} | {entry['last_utc']} | "
            f"{entry['gaps']} | {entry['coverage_pct']} | {entry['bytes']} | "
            f"`{entry['sha256'][:16]}…` |"
        )
    lines += [
        "",
        "## 3. Complete bars per window, per clock",
        "",
        "A bar exists only where its whole bucket does: the 4h and 1d series are aggregated from "
        "the 1h shards by the campaign's own `resample`, which emits a bucket only when every "
        "source hour is present and contiguous. Below the declared floor the decisive window "
        "cannot carry a verdict for that clock.",
        "",
    ]
    for timeframe, reading in payload["coverage"].items():
        lines += [
            f"### Clock `{timeframe}` (floor {payload['coverage_floor_bars_per_asset'][timeframe]} "
            f"bars per asset on the decisive window)",
            "",
            "| Window | " + " | ".join(sorted(reading["per_asset_bars_in_window"])) + " |",
            "| --- | " + " | ".join("---" for _ in reading["per_asset_bars_in_window"]) + " |",
        ]
        for window, per_asset in reading["per_asset_bars_in_window"].items():
            lines.append(
                f"| `{window}` | "
                + " | ".join(str(per_asset[asset]) for asset in sorted(per_asset))
                + " |"
            )
        lines.append("")
        if reading["screen_failure"]:
            lines.append(f"- **Coverage floor failed**: {reading['screen_failure']}")
            lines.append("")
    lines += [
        "## 4. What this does not say",
        "",
    ]
    for limitation in payload["limitations"]:
        lines.append(f"- {limitation}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args(argv)
    payload = build()
    WP.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    MD_PATH.write_text(render(payload), encoding="utf-8")
    print(f"{payload['verdict']}  digest {(payload['corpus_digest'] or '')[:16]}…")
    for timeframe, reading in payload["coverage"].items():
        total = reading["per_asset_total"]
        print(f"  {timeframe:<3} bars per asset (all windows): {total}")
    print(f"wrote {JSON_PATH.relative_to(REPO_ROOT)} and {MD_PATH.relative_to(REPO_ROOT)}")
    return 0 if payload["disjointness"]["claim_holds"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
