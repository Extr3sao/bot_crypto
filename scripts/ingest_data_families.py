"""Deterministic raw->normalized ingestion for the two admitted data families.

ALPHA-DATA-ADMISSION-01 Tracks D3/E2/G. Reads provider-original zips from
``data/raw/`` (never modified) via the hardened official-source readers
(checksum + schema guards), emits canonical JSONL under ``data/processed/``
plus a manifest carrying full provenance (RAW_SOURCE_SHA256,
NORMALIZER_VERSION, NORMALIZED_SHA256, dataset fingerprint).

DATA-ONLY: emits NO signal, NO performance metric, NO alpha artifact.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from trading_bot.research.data_contracts import SCHEMA_VERSION
from trading_bot.research.data_quality import (
    NORMALIZER_VERSION,
    fingerprint_open_interest,
    fingerprint_trade_flow,
    normalize_open_interest,
    normalize_trade_flow,
)
from trading_bot.research.source_readers import (
    read_agg_trades_zip,
    read_metrics_zip,
    sha256_file,
)

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "data" / "raw" / "binance_um"
NORMALIZED = REPO / "data" / "processed"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
SAMPLE_DAYS = (
    "2026-09-01",
    "2026-09-02",
    "2026-09-03",
    "2026-09-04",
    "2026-09-05",
    "2026-09-06",
    "2026-09-07",
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> str:
    buf = bytearray()
    for row in rows:
        buf += (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
    path.write_bytes(bytes(buf))
    return hashlib.sha256(bytes(buf)).hexdigest()


def _day_end_ms(day: str) -> int:
    dt = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
    return int(dt.timestamp() * 1000)


def ingest_family(
    family: str, normalizer_commit: str = "-", only_symbol: str | None = None
) -> dict[str, object]:
    """Ingest the full bounded sample for one family; returns the manifest."""
    assert family in ("trade_flow", "open_interest")
    symbols = (only_symbol,) if only_symbol else SYMBOLS
    reports: list[dict[str, object]] = []
    for symbol in symbols:
        for day in SAMPLE_DAYS:
            cutoff = _day_end_ms(day)
            if family == "trade_flow":
                zip_path = RAW / "aggTrades" / symbol / f"{symbol}-aggTrades-{day}.zip"
                records = read_agg_trades_zip(zip_path, symbol)
                sample = [
                    {
                        "agg_trade_id": r.agg_trade_id,
                        "price": r.price,
                        "quantity": r.quantity,
                        "first_trade_id": r.first_trade_id,
                        "last_trade_id": r.last_trade_id,
                        "trade_time_ms": r.trade_time_ms,
                        "buyer_is_maker": r.buyer_is_maker,
                        "taker_side": r.taker_side.value,
                        "symbol": r.symbol,
                        "source_file": r.source_file,
                        "source_sha256": r.source_sha256,
                    }
                    for r in records
                ]
                out_path = NORMALIZED / "trade_flow" / f"{symbol}-{day}.jsonl"
                normalized_sha = _write_jsonl(out_path, sample)
                stats = normalize_trade_flow(records, decision_time_ms=cutoff)
                fp = fingerprint_trade_flow(
                    records,
                    asset=symbol,
                    time_range_ms=(stats["time_min_ms"] or 0, stats["time_max_ms"] or 0),
                    schema_version=SCHEMA_VERSION,
                    normalizer_version=NORMALIZER_VERSION,
                    source_file_hashes=[sha256_file(zip_path)],
                )
            else:
                zip_path = RAW / "metrics" / symbol / f"{symbol}-metrics-{day}.zip"
                records = read_metrics_zip(zip_path, symbol)
                sample = [
                    {
                        "timestamp_ms": r.timestamp_ms,
                        "open_interest_contracts": r.open_interest_contracts,
                        "open_interest_value": r.open_interest_value,
                        "period": r.period,
                        "symbol": r.symbol,
                        "source_file": r.source_file,
                        "source_sha256": r.source_sha256,
                    }
                    for r in records
                ]
                out_path = NORMALIZED / "open_interest" / f"{symbol}-{day}.jsonl"
                normalized_sha = _write_jsonl(out_path, sample)
                stats = normalize_open_interest(records, decision_time_ms=cutoff)
                fp = fingerprint_open_interest(
                    records,
                    asset=symbol,
                    time_range_ms=(stats["time_min_ms"] or 0, stats["time_max_ms"] or 0),
                    schema_version=SCHEMA_VERSION,
                    normalizer_version=NORMALIZER_VERSION,
                    source_file_hashes=[sha256_file(zip_path)],
                )

            reports.append(
                {
                    "symbol": symbol,
                    "day": day,
                    "raw_source": str(zip_path.relative_to(REPO)).replace("\\", "/"),
                    "raw_source_sha256": sha256_file(zip_path),
                    "official_checksum_verified": True,
                    "normalized_path": str(out_path.relative_to(REPO)).replace("\\", "/"),
                    "normalized_sha256": normalized_sha,
                    "dataset_fingerprint": fp,
                    "rows_total": stats["rows_total"],
                    "rows_within_pit": stats["rows_within_pit"],
                    "quality_errors": stats["errors"],
                }
            )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "normalizer_version": NORMALIZER_VERSION,
        "normalizer_commit": normalizer_commit,
        "family": family,
        "sample_window_utc": ["2026-09-01", "2026-09-07"],
        "files": reports,
    }
    manifest_path = NORMALIZED / family / "DATASET_MANIFEST.json"
    if only_symbol and manifest_path.exists():
        # staged run: merge this symbol's fresh entries into the existing manifest
        try:
            prev = json.loads(manifest_path.read_text(encoding="utf-8"))
            kept = [f for f in prev.get("files", []) if f.get("symbol") != only_symbol]
            merged = sorted(kept + reports, key=lambda f: (str(f.get("symbol")), str(f.get("day"))))
            manifest["files"] = merged
        except (json.JSONDecodeError, OSError):
            pass
    manifest["files"] = sorted(manifest["files"], key=lambda f: (str(f.get("symbol")), str(f.get("day"))))
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def _normalizer_commit() -> str:
    """HEAD at normalization time (Track G provenance; '-' if unavailable)."""
    try:
        import subprocess

        return (
            subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
                cwd=REPO,
            ).stdout.strip()
        )
    except Exception:
        return "-"


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=("trade_flow", "open_interest", "both"), default="both")
    parser.add_argument("--symbol", choices=SYMBOLS, default=None, help="restrict to one symbol (staged runs)")
    args = parser.parse_args(argv)

    NORMALIZED.mkdir(parents=True, exist_ok=True)
    (NORMALIZED / "trade_flow").mkdir(exist_ok=True)
    (NORMALIZED / "open_interest").mkdir(exist_ok=True)
    commit = _normalizer_commit()
    families = (
        ("trade_flow", "open_interest") if args.family == "both" else (args.family,)
    )
    ingested: dict[str, dict[str, object]] = {}
    for fam in families:
        ingested[fam] = ingest_family(fam, normalizer_commit=commit, only_symbol=args.symbol)
    manifest_path = NORMALIZED / "DATASET_MANIFESTS_PROVENANCE.json"
    manifest_path.write_text(
        json.dumps(
            {
                "normalizer_commit": commit,
                "staged_run": {"family": args.family, "symbol": args.symbol},
                "note": "normalizer commit embedded into family DATASET_MANIFEST.json files at ingestion time",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    summary: dict[str, object] = {}
    # summary always computed from on-disk manifests so staged runs converge
    for fam_key, fam_dir in (("trade_flow", "trade_flow"), ("open_interest", "open_interest")):
        mpath = NORMALIZED / fam_dir / "DATASET_MANIFEST.json"
        if not mpath.exists():
            continue
        try:
            mdata = json.loads(mpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        mfiles: list[dict[str, object]] = mdata.get("files", [])
        summary[f"{fam_key}_files"] = len(mfiles)
        summary[f"{fam_key}_quality_error_files"] = sum(1 for f in mfiles if f.get("quality_errors"))
        summary[f"{fam_key}_rows"] = sum(int(f.get("rows_within_pit", 0)) for f in mfiles)
    (NORMALIZED / "INGESTION_SUMMARY.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
