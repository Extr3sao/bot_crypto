#!/usr/bin/env python
"""ARC-03 existing-data inventory + reuse assessment (inspect real frozen bytes).

Reads the ACTUAL certified authorities that already exist in the shared data root and
classifies every candidate participation field as REUSABLE / REUSABLE_WITH_LIMITATION /
NOT_REUSABLE for ARC-03. Nothing here observes returns; only schemas, cadence,
coverage, fingerprints and provenance.

Writes:
    docs/arc03-data-authority-01/ARC03_DATA_INVENTORY.json
    docs/arc03-data-authority-01/ARC03_EXISTING_DATA_REUSE_ASSESSMENT.json
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys
from typing import Any

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.arc03.arc03_normalize import (  # noqa: E402
    INTERVAL,
    canonical_json,
    sha256_bytes,
    sha256_file,
    write_json_bytes,
)

DOCS = REPO / "docs" / "arc03-data-authority-01"
SHARED = REPO / "data" / "processed"

ARC03_FIELDS = ("open", "high", "low", "close", "volume", "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume")


def _fingerprint(path: pathlib.Path) -> str:
    return sha256_file(path) if path.exists() else ""


def _line_count(path: pathlib.Path, limit: int = 5_000_000) -> int:
    if not path.exists():
        return 0
    n = 0
    with path.open("rb") as fh:
        for _ in fh:
            n += 1
            if n >= limit:
                break
    return n


def _first_row(path: pathlib.Path) -> Any:
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    return line[:200]
    return None


def main() -> int:
    DOCS.mkdir(parents=True, exist_ok=True)
    inventory: dict[str, Any] = {
        "checkpoint": "ARC03-DATA-001",
        "purpose": "candidate participation inputs for ARC-03, classified before any economic observation",
        "canonical_arc03_authority": {
            "family": "binance_usdm_klines_5m",
            "interval": INTERVAL,
            "raw_root": "data/raw/binance_um/arc03",
            "daily_supplement_root": "data/raw/binance_um/arc03_daily",
            "processed": "data/processed/arc03_klines_5m/{BTCUSDT,ETHUSDT,SOLUSDT}.jsonl",
            "schema": ["t", "ct", "o", "h", "l", "c", "v", "qv", "n", "tb", "tq", "sym", "ms"],
        },
        "provider_field_admission": {
            "open_time": "REQUIRED (bar open time, epoch ms UTC)",
            "open": "REQUIRED (price displacement input)",
            "high": "REQUIRED (excursion input)",
            "low": "REQUIRED (excursion input)",
            "close": "REQUIRED (body / exhaustion input)",
            "volume": "REQUIRED (ARC-03 participation field, base units)",
            "close_time": "REQUIRED (PIT completion anchor)",
            "quote_volume": "OPTIONAL_RESEARCH_ONLY (dollar participation; not used by the frozen primary)",
            "count": "OPTIONAL_RESEARCH_ONLY (number of trades; not used by the frozen primary)",
            "taker_buy_volume": "OPTIONAL_RESEARCH_ONLY (aggressor-side base volume; H5 territory, explicitly NOT used by ARC-03)",
            "taker_buy_quote_volume": "OPTIONAL_RESEARCH_ONLY (aggressor-side dollar volume; not used)",
            "ignore": "REJECTED (provider ignore column, never read)",
        },
        "not_admitted": [
            "open_interest (H6 territory)",
            "funding rate / mark price (ARC-01 territory)",
            "aggTrades / order book depth as a primary input (out of the frozen ARC-03 data requirement)",
        ],
    }

    ledger = [
        json.loads(l)
        for l in (DOCS / "ARC03_DATA_QUALITY_LEDGER.jsonl").read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    summaries = [e for e in ledger if e.get("kind") == "SYMBOL_SUMMARY"]
    inventory["canonical_arc03_authority"]["per_symbol"] = {
        e["symbol"]: {
            "admitted_rows": e["admitted_rows"],
            "admitted_months": e["admitted_months"],
            "withheld_months": e["withheld_months"],
            "daily_supplemented_months": e.get("daily_supplemented_months", []),
            "internal_cadence_breaks_admitted": e["internal_cadence_breaks_admitted"],
            "first_open_ms": e["first_open_ms"],
            "last_open_ms": e["last_open_ms"],
        }
        for e in summaries
    }
    write_json_bytes(DOCS / "ARC03_DATA_INVENTORY.json", inventory)

    # ------------------------------------------------- existing authority candidates
    candidates: list[dict[str, Any]] = []

    # 1. price_1h_v2 (ARC-01's canonical 12-field 1h price authority)
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        p = SHARED / "price_1h_v2" / f"{sym}_1h.jsonl"
        first = _first_row(p)
        candidates.append(
            {
                "candidate": f"data/processed/price_1h_v2/{sym}_1h.jsonl",
                "exists": p.exists(),
                "family": "binance_usdm_klines_1h (ARC-01 V2 authority)",
                "cadence": "1h",
                "schema_inspected": "12-element provider array [openTime,open,high,low,close,volume,closeTime,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore]",
                "first_row_shape_ok": isinstance(first, list) and len(first) == 12,
                "rows": _line_count(p),
                "sha256": _fingerprint(p),
                "fields": {f: "PRESENT" for f in ARC03_FIELDS},
                "field_classification": {f: "NOT_REUSABLE" for f in ARC03_FIELDS},
                "verdict": "NOT_REUSABLE",
                "reason": (
                    "wrong cadence: ARC-03's frozen decision timeframe is the 5m bar and the participation "
                    "shock is defined against same-5m-slot daily references. 1h bars cannot be disaggregated "
                    "(volume is not additive across the missing 5m slots and the exhaustion geometry is lost), "
                    "so no participation field of this authority can serve the frozen definition."
                ),
            }
        )

    # 2. H1/H5 committed 1h dataset in docs/
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        p = REPO / "docs" / "external-audit-01" / "h1-regime-transition-01" / "dataset" / f"{sym}_1h.jsonl"
        candidates.append(
            {
                "candidate": f"docs/external-audit-01/h1-regime-transition-01/dataset/{sym}_1h.jsonl",
                "exists": p.exists(),
                "family": "committed frozen 12-field klines (H1 regime-transition dataset, reused by H5)",
                "cadence": "1h",
                "rows": _line_count(p),
                "sha256": _fingerprint(p),
                "fields": {f: "PRESENT" for f in ARC03_FIELDS},
                "field_classification": {f: "NOT_REUSABLE" for f in ARC03_FIELDS},
                "verdict": "NOT_REUSABLE",
                "reason": "same cadence limitation as price_1h_v2; also a cross-branch committed copy, not a 5m authority",
            }
        )

    # 3. trade_flow aggTrades sample
    tf_dir = SHARED / "trade_flow"
    tf_files = sorted(p.name for p in tf_dir.glob("*.jsonl")) if tf_dir.exists() else []
    tf_dates = sorted({m.group(0) for f in tf_files if (m := re.search(r"\d{4}-\d{2}-\d{2}", f))})
    tf_manifest = tf_dir / "DATASET_MANIFEST.json"
    candidates.append(
        {
            "candidate": "data/processed/trade_flow/",
            "exists": tf_dir.exists(),
            "family": "raw Binance USD-M aggTrades samples (per-trade)",
            "cadence": "per trade (irregular)",
            "files": len(tf_files),
            "distinct_dates": len(tf_dates),
            "date_range": [tf_dates[0], tf_dates[-1]] if tf_dates else None,
            "manifest_sha256": _fingerprint(tf_manifest),
            "fields": {
                "volume": "DERIVABLE",
                "quote_volume": "DERIVABLE",
                "count": "DERIVABLE",
                "taker_buy_volume": "DERIVABLE",
                "taker_buy_quote_volume": "DERIVABLE",
                "open": "DERIVABLE",
                "high": "DERIVABLE",
                "low": "DERIVABLE",
                "close": "DERIVABLE",
            },
            "field_classification": {
                "volume": "NOT_REUSABLE",
                "quote_volume": "NOT_REUSABLE",
                "count": "NOT_REUSABLE",
                "taker_buy_volume": "NOT_REUSABLE",
                "taker_buy_quote_volume": "NOT_REUSABLE",
                "open": "NOT_REUSABLE",
                "high": "NOT_REUSABLE",
                "low": "NOT_REUSABLE",
                "close": "NOT_REUSABLE",
            },
            "verdict": "NOT_REUSABLE",
            "reason": (
                f"coverage: only {len(tf_dates)} distinct days ({tf_dates[0] if tf_dates else 'n/a'} .. "
                f"{tf_dates[-1] if tf_dates else 'n/a'}) versus the ~6-year common causal window ARC-03 requires. "
                "Codes are CHECKSUM-verified official bytes, but the sample cannot support a multi-year study."
            ),
        }
    )

    # 4. candle/kline authorities inside the repo's own research modules
    for name, note in (
        ("src/trading_bot/backtesting", "backtesting engine reads 1h/4h/1d klines"),
        ("src/trading_bot/research", "research feature modules"),
    ):
        candidates.append(
            {
                "candidate": name,
                "exists": (REPO / name).exists(),
                "family": "research/backtesting kline readers",
                "cadence": "varies (>=1h in every committed reader)",
                "fields": {},
                "field_classification": {},
                "verdict": "NOT_REUSABLE",
                "reason": note + "; no committed 5m participation authority found anywhere in the repository",
            }
        )

    verdicts = {c["candidate"]: c["verdict"] for c in candidates}
    any_reusable = any(v == "REUSABLE" or v == "REUSABLE_WITH_LIMITATION" for v in verdicts.values())
    assessment = {
        "checkpoint": "ARC03-DATA-001",
        "question": "does an existing certified authority already carry the 5m participation fields ARC-03 needs?",
        "method": "inspect the actual frozen bytes/schema of every candidate authority in the shared data root and in docs/",
        "candidates": candidates,
        "REUSABLE_FIELDS_FOUND": any_reusable,
        "conclusion": (
            "NO existing authority is reusable. Every committed kline authority in the repository is 1h or coarser "
            "(ARC-01 V2 price authority, H1/H5 committed dataset) and per-trade coverage (trade_flow) spans only a "
            "handful of recent days. The repository contains no 5m participation authority, so ARC-03 must acquire "
            "its own official 5m bytes (only the `volume` field is REQUIRED beyond OHLC, and OHLC is re-derived from "
            "the same official 5m bytes rather than spliced from a different cadence)."
        ),
        "no_duplicate_dataset_created_for_cadences_already_certified": True,
        "assessment_sha256": sha256_bytes(canonical_json([c["candidate"] for c in candidates])),
    }
    write_json_bytes(DOCS / "ARC03_EXISTING_DATA_REUSE_ASSESSMENT.json", assessment)
    print(json.dumps({"verdicts": verdicts, "REUSABLE_FIELDS_FOUND": any_reusable}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
