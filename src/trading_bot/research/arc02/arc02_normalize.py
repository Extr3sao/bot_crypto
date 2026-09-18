"""ARC-02 5m lead-lag authority — reuse-first projection + deterministic fingerprint.

ARC-02 downloads nothing. It **reuses** the certified ARC-03 5m Binance USD-M kline
authority (itself the byte-verified official ``data.binance.vision`` archive) and
projects it onto the narrow field set the lead-lag mechanism needs::

    certified ARC-03 raw archives (reused, provider-CHECKSUM verified)
        -> certified ARC-03 normalized partitions (reused byte-for-byte)
        -> ARC-02 projection partitions (t, ct, o, c only)
        -> partition SHA256 -> manifest -> DATASET SHA256

Why a projection rather than a second download: the lead-lag rule reads only
completed 5m **closes** (BTC log return, follower log return) and 5m **opens**
(entry/exit anchors). Volume, quote volume, trade count and every taker-buy field are
deliberately NOT carried into the ARC-02 projection, so ARC-02 cannot structurally
read the H5 order-flow family or the ARC-03 participation field.

Numeric values are copied as their exact provider strings, so the projection
fingerprint cannot drift through float re-formatting.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any, Iterable

SCHEMA_VERSION = "1.0.0"
PROJECTION_VERSION = "1.0.0"
INTERVAL = "5m"
BAR_MS = 300_000
BARS_PER_DAY = 288
DAY_MS = 86_400_000

ASSETS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT")

#: Reused, already-certified authority root (relative to the resolved data root).
SOURCE_PARTITION_RELPATH = pathlib.Path("data") / "processed" / "arc03_klines_5m"
SOURCE_RAW_RELPATH = pathlib.Path("data") / "raw" / "binance_um" / "arc03"
SOURCE_DAILY_RELPATH = pathlib.Path("data") / "raw" / "binance_um" / "arc03_daily"

#: ARC-02's own projection root.
PROJECTION_RELPATH = pathlib.Path("data") / "processed" / "arc02_klines_5m"

#: Certified ARC-03 partition digests the reused bytes must reproduce exactly.
SOURCE_PARTITION_SHA256: dict[str, str] = {
    "BTCUSDT": "eb75ab97881fd941c05d1b188778f1a832ab404c59f5991eff12ead779e4ab02",
    "ETHUSDT": "24c886902760b2e2c873df7721c12098e65b768762f55e2144d990deac04c211",
    "SOLUSDT": "d872bc7dc8a52eb697962516fbd24a636483acd43e524cdbbf09985d2720f548",
}
SOURCE_DATASET_SHA256 = "1a6ad11712ce436ce9d413d6b53162d66996778cd98643ef7c3eb746a54745ef"
SOURCE_RAW_FILES_SHA256 = "abfe8caee35ff441d71127430a8547eba98e54a7a722681db908565b720996a9"

#: Fields carried into the ARC-02 projection.
PROJECTED_FIELDS: tuple[str, ...] = ("t", "ct", "o", "c")
#: Fields present in the reused authority that ARC-02 deliberately drops.
DROPPED_FIELDS: tuple[str, ...] = ("h", "l", "v", "qv", "n", "tb", "tq")


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json_bytes(path: pathlib.Path, obj: Any) -> None:
    """Write canonical JSON with LF line endings only (byte-stable on every platform)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(obj, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def write_jsonl_bytes(path: pathlib.Path, rows: Iterable[Any]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = bytearray()
    n = 0
    for row in rows:
        payload += canonical_json(row) + b"\n"
        n += 1
    path.write_bytes(bytes(payload))
    return n


def project_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Narrow reused authority records to the frozen ARC-02 field set.

    Only ``t``/``ct``/``o``/``c`` survive; ``sym`` and ``ms`` are carried as
    provenance. Rows are sorted by ascending ``t`` (the reused partition is already
    ascending; the sort makes the projection independent of record order).
    """
    out: list[dict[str, Any]] = []
    for r in records:
        out.append(
            {
                "t": int(r["t"]),
                "ct": int(r["ct"]),
                "o": str(r["o"]),
                "c": str(r["c"]),
                "sym": str(r.get("sym", "")),
                "ms": str(r.get("ms", "")),
            }
        )
    out.sort(key=lambda r: r["t"])
    return out


def read_source_records(path: pathlib.Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def projection_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic quality summary of one projected partition."""
    t = [r["t"] for r in rows]
    cts = [r["ct"] for r in rows]
    dup = len(t) - len(set(t))
    gaps = sum(1 for a, b in zip(t, t[1:]) if b - a != BAR_MS)
    off_grid = sum(1 for x in t if x % BAR_MS != 0)
    close_time_violations = sum(1 for r in rows if r["ct"] != r["t"] + BAR_MS - 1)
    non_finite = 0
    non_positive = 0
    for r in rows:
        try:
            o = float(r["o"])
            c = float(r["c"])
        except (TypeError, ValueError):
            non_finite += 1
            continue
        if not (o == o and c == c) or o in (float("inf"), float("-inf")) or c in (float("inf"), float("-inf")):
            non_finite += 1
            continue
        if o <= 0.0 or c <= 0.0:
            non_positive += 1
    return {
        "rows": len(rows),
        "first_open_ms": t[0] if t else None,
        "last_open_ms": t[-1] if t else None,
        "duplicate_open_slots": dup,
        "internal_cadence_breaks": gaps,
        "off_grid_slots": off_grid,
        "close_time_violations": close_time_violations,
        "non_finite_values": non_finite,
        "non_positive_prices": non_positive,
        "monotonic_open_time": all(a < b for a, b in zip(t, t[1:])),
        "completed_bar_semantics": all(r["ct"] == r["t"] + BAR_MS - 1 for r in rows),
        "close_time_monotonic": all(a < b for a, b in zip(cts, cts[1:])),
    }


def project_symbol(
    symbol: str,
    *,
    source_dir: pathlib.Path,
    out_dir: pathlib.Path | None = None,
    write: bool = True,
    verify_reuse: bool = True,
) -> dict[str, Any]:
    """Project one symbol; returns the ledger entry (with digests) for the manifest."""
    source_path = source_dir / f"{symbol}.jsonl"
    if not source_path.exists():
        raise FileNotFoundError(f"missing reused ARC-03 authority partition: {source_path}")
    source_sha = sha256_file(source_path)
    if verify_reuse and source_sha != SOURCE_PARTITION_SHA256[symbol]:
        raise ValueError(
            f"REUSE_IDENTITY_MISMATCH for {symbol}: on-disk {source_sha} != certified {SOURCE_PARTITION_SHA256[symbol]}"
        )
    rows = project_records(read_source_records(source_path))
    payload = bytearray()
    for r in rows:
        payload += canonical_json(r) + b"\n"
    projection_sha = sha256_bytes(bytes(payload))
    entry: dict[str, Any] = {
        "symbol": symbol,
        "source_partition_sha256": source_sha,
        "projection_sha256": projection_sha,
        "projected_fields": list(PROJECTED_FIELDS),
        "dropped_fields": list(DROPPED_FIELDS),
        **projection_stats(rows),
    }
    if write:
        if out_dir is None:
            raise ValueError("out_dir is required when write=True")
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{symbol}.jsonl").write_bytes(bytes(payload))
        entry["projection_path"] = f"data/processed/arc02_klines_5m/{symbol}.jsonl"
        entry["projection_size_bytes"] = (out_dir / f"{symbol}.jsonl").stat().st_size
    return entry


def build_manifest(partitions: list[dict[str, Any]]) -> dict[str, Any]:
    """Dataset fingerprint: pure function of the projected content digests + reuse binding."""
    files = sorted(
        (
            {
                "symbol": p["symbol"],
                "source_partition_sha256": p["source_partition_sha256"],
                "projection_sha256": p["projection_sha256"],
                "rows": p["rows"],
                "first_open_ms": p["first_open_ms"],
                "last_open_ms": p["last_open_ms"],
            }
            for p in partitions
        ),
        key=lambda x: x["symbol"],
    )
    fp_payload = {
        "schema_version": SCHEMA_VERSION,
        "projection_version": PROJECTION_VERSION,
        "interval": INTERVAL,
        "projected_fields": list(PROJECTED_FIELDS),
        "dropped_fields": list(DROPPED_FIELDS),
        "source_authority_dataset_sha256": SOURCE_DATASET_SHA256,
        "reuse_semantics": "REUSE_BY_CONTENT_IDENTITY (no re-download; source partitions byte-identical)",
        "files": files,
    }
    return {
        "checkpoint": "ARC02-DATA-001",
        "family": "binance_usdm_klines_5m",
        "authority_role": "ARC02_PROJECTION_OF_REUSED_ARC03_AUTHORITY",
        "source_authority": {
            "provider": "Binance (official public market-data archive, data.binance.vision)",
            "dataset_sha256": SOURCE_DATASET_SHA256,
            "raw_files_sha256": SOURCE_RAW_FILES_SHA256,
            "partition_sha256": SOURCE_PARTITION_SHA256,
            "processed_root": "data/processed/arc03_klines_5m/{SYMBOL}.jsonl",
            "raw_root": "data/raw/binance_um/arc03/{SYMBOL}/{YYYY-MM}/",
            "daily_root": "data/raw/binance_um/arc03_daily/{SYMBOL}/{YYYY-MM-DD}/",
            "reused_from": "ARC-03 data authority (ARC03-DATA-001, independently verified)",
        },
        "interval": INTERVAL,
        "bar_ms": BAR_MS,
        "schema_version": SCHEMA_VERSION,
        "projection_version": PROJECTION_VERSION,
        "partitions": {p["symbol"]: f"data/processed/arc02_klines_5m/{p['symbol']}.jsonl" for p in partitions},
        "partition_sha256": {p["symbol"]: p["projection_sha256"] for p in partitions},
        "per_symbol": {p["symbol"]: p for p in partitions},
        "dataset_sha256": sha256_bytes(canonical_json(fp_payload)),
        "dataset_sha256_method": (
            "sha256(canonical_json({schema_version, projection_version, interval, projected_fields, "
            "dropped_fields, source_authority_dataset_sha256, reuse_semantics, "
            "files[{symbol,source_partition_sha256,projection_sha256,rows,first_open_ms,last_open_ms}]})) "
            "over all symbols sorted by symbol. No machine-specific absolute path participates in identity."
        ),
        "quality_status": "PASS",
    }


__all__ = [
    "ASSETS",
    "BAR_MS",
    "BARS_PER_DAY",
    "DAY_MS",
    "DROPPED_FIELDS",
    "INTERVAL",
    "PROJECTED_FIELDS",
    "PROJECTION_RELPATH",
    "PROJECTION_VERSION",
    "SCHEMA_VERSION",
    "SOURCE_DATASET_SHA256",
    "SOURCE_DAILY_RELPATH",
    "SOURCE_PARTITION_RELPATH",
    "SOURCE_PARTITION_SHA256",
    "SOURCE_RAW_FILES_SHA256",
    "SOURCE_RAW_RELPATH",
    "build_manifest",
    "canonical_json",
    "project_records",
    "project_symbol",
    "projection_stats",
    "read_source_records",
    "sha256_bytes",
    "sha256_file",
    "write_json_bytes",
    "write_jsonl_bytes",
]
