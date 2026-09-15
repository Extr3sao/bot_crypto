"""ARC-01 data-authority binding and certified loaders (primary discovery).

This module performs NO economic computation. It only *loads* the certified
authorities and *proves* (by independent SHA256 recomputation) that the bytes it
feeds into the ARC-01 primary discovery are exactly the bytes frozen by
PREREG_COMMIT ``fa15fb4`` / the data authority ``6e42dd9``.

Frozen bindings (ARC01_SPEC_V1.json:data_authority):

    dataset_sha256                                  5f4845f5...3b62ec
    partition_sha256.BTCUSDT                        700b0c4c...58585
    partition_sha256.ETHUSDT                        2edf501e...93943
    partition_sha256.SOLUSDT                        6b16d13f...08f85
    oi_full_history_dataset_sha256_v2               16779b7d...98d99
    price_authority_sha256_v2                       e1c2462a...52168
    per_asset_sha256.{BTCUSDT,ETHUSDT,SOLUSDT}      41e92386/7c72c0bb/6f147463...

Digest derivations are reproduced from the authoritative builder scripts
(``scripts/normalize_arc01_funding.py``, ``scripts/normalize_oi_full_history_v2.py``,
``scripts/build_price_authority_v2.py``) -- see ``derivation`` fields in the
returned evidence, never trusted from a summary.

PIT contract: reads are strictly timestamp-scoped. ``oi_last_at`` returns the last
observation with ``timestamp_ms <= T`` (byte-equivalent to
``oi_dataset_v2.oi_state_at_ms(T, symbol)[-1]``); the OI day-validity ledger is
used here for *forensic byte-binding only* and never gates decision eligibility.
"""

from __future__ import annotations

import hashlib
import json
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[4]  # <repo>/src/trading_bot/research/arc01/<file>

# ---------------------------------------------------------------- frozen digests
FROZEN = {
    "dataset_sha256": "5f4845f5062e68353ef421b9687bf728a56693951e2f74e17221a8e3373b62ec",
    "canonical_rows_sha256": "34f736b1efdaebcf81c2e7824f776706385f27aee1c564f3dc39f8d1fe993452",
    "partition_sha256": {
        "BTCUSDT": "700b0c4c7e5ffa9dbe82cd84e98be9f505bce6f1792d33d0eae88d07a7585855",
        "ETHUSDT": "2edf501ea69807bbf67cdd519e53de18c8dea25ea8bdf009beb88ef2e2693943",
        "SOLUSDT": "6b16d13f5115f906f9ceb4f5a418f7a541c37609e780cfbad0d52ed565808f85",
    },
    "funding_rows": {"BTCUSDT": 7347, "ETHUSDT": 7347, "SOLUSDT": 6652},
    "oi_full_history_dataset_sha256_v2": "16779b7d2eff0dc9e56015c444c2dbe7b67ef083e6cf1877a024a6de74098d99",
    "price_authority_sha256_v2": "e1c2462a6aa9ba0c921154d259a28c49be1e2fc58a544dbd97af8ecabef52168",
    "price_per_asset_sha256": {
        "BTCUSDT": "41e9238666a0b98c02cffd19d36a590b8463f6556e215c49f068452674ef9027",
        "ETHUSDT": "7c72c0bb55d4aac9460dde54eb73305b5d30bdec99ea4b500eac9e1319ddd7ba",
        "SOLUSDT": "6f147463b504f5026d887e77306cfa629ee5feb8cbdb01923643133091da03ff",
    },
    "common_window_start_ms": 1_638_316_800_000,
    "common_window_end_ms": 1_789_081_200_000,
}

ASSETS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")

FUNDING_EVIDENCE_DIR = REPO / "docs" / "arc01-data-authority-01"
FUNDING_DATA_DIR = REPO / "data" / "processed" / "arc01_funding"
OI_EVIDENCE_DIR = REPO / "docs" / "external-audit-01" / "oi-full-history-02"
OI_LEDGER_EVIDENCE = OI_EVIDENCE_DIR / "OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl"
PRICE_MANIFEST_EVIDENCE = OI_EVIDENCE_DIR / "PRICE_1H_AUTHORITY_V2_MANIFEST.json"


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(obj: Any) -> bytes:
    """The exact serialization used by every builder script in this repo."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


# ------------------------------------------------------------------- OI / price
def resolve_shared_data_root(repo: Path = REPO) -> Path:
    """Portable data root: the worktree's own ``data/`` if it carries the OI
    dataset, else the shared main checkout (``.research/<wt>`` -> repo root)."""
    local = repo / "data"
    if (local / "processed" / "oi_full_history_v2").is_dir():
        return local
    shared = repo.parents[1] / "data"
    if (shared / "processed" / "oi_full_history_v2").is_dir():
        return shared
    raise FileNotFoundError(
        "certified OI authority not found: expected <repo>/data/processed/oi_full_history_v2 "
        f"or {repo.parents[1] / 'data' / 'processed' / 'oi_full_history_v2'}"
    )


def resolve_funding_source() -> tuple[Path, str]:
    """Funding partitions: prefer the canonical ``data/processed`` copy, else the
    committed byte-identical evidence snapshot under docs/ (verified equal)."""
    if FUNDING_DATA_DIR.is_dir() and any(FUNDING_DATA_DIR.glob("*_funding.jsonl")):
        return FUNDING_DATA_DIR, "data/processed/arc01_funding (canonical)"
    return FUNDING_EVIDENCE_DIR, "docs/arc01-data-authority-01 (committed evidence snapshot)"


def verify_funding(assets: tuple[str, ...] = ASSETS) -> dict[str, Any]:
    """Recompute funding partition SHAs and the aggregate dataset SHA256."""
    src, src_kind = resolve_funding_source()
    parts: list[dict[str, Any]] = []
    per_symbol: dict[str, Any] = {}
    for sym in sorted(assets):
        p = src / f"{sym}_funding.jsonl"
        if not p.exists():
            raise FileNotFoundError(f"missing funding partition: {p}")
        rows = 0
        with p.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    rows += 1
        digest = sha256_file(p)
        per_symbol[sym] = {
            "path": str(p),
            "sha256_recomputed": digest,
            "sha256_expected": FROZEN["partition_sha256"][sym],
            "rows": rows,
            "rows_expected": FROZEN["funding_rows"][sym],
        }
        parts.append({"symbol": sym, "partition_sha256": digest, "rows": rows})
    manifest = json.loads((FUNDING_EVIDENCE_DIR / "ARC01_FUNDING_MANIFEST.json").read_text(encoding="utf-8"))
    payload = {
        "schema_version": manifest["schema_version"],
        "normalizer_version": manifest["normalizer_version"],
        "normalizer_commit": manifest["normalizer_commit"],
        "partitions": parts,
        "funding_units_contract": manifest["funding_units_contract"],
        "pit_invariant": manifest["pit_invariant"],
    }
    dataset_sha = sha256_bytes(canonical_json(payload))
    # canonical rows digest (symbol, funding_time_ms)-sorted canonical JSON of all rows
    all_rows: list[dict[str, Any]] = []
    for sym in sorted(assets):
        with (src / f"{sym}_funding.jsonl").open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    all_rows.append(json.loads(line))
    all_rows.sort(key=lambda r: (r["symbol"], int(r["funding_time_ms"])))
    canonical_sha = sha256_bytes(canonical_json(all_rows))
    ok = (
        all(v["sha256_recomputed"] == v["sha256_expected"] and v["rows"] == v["rows_expected"] for v in per_symbol.values())
        and dataset_sha == FROZEN["dataset_sha256"]
        and canonical_sha == FROZEN["canonical_rows_sha256"]
    )
    return {
        "status": "PASS" if ok else "FAIL",
        "source": src_kind,
        "derivation": "dataset_sha256 = sha256(canonical_json({schema_version, normalizer_version, normalizer_commit, partitions[{symbol,partition_sha256,rows}], funding_units_contract, pit_invariant})) per scripts/normalize_arc01_funding.py",
        "dataset_sha256_recomputed": dataset_sha,
        "dataset_sha256_expected": FROZEN["dataset_sha256"],
        "canonical_rows_sha256_recomputed": canonical_sha,
        "canonical_rows_sha256_expected": FROZEN["canonical_rows_sha256"],
        "per_symbol": per_symbol,
    }


def verify_price(data_root: Path, assets: tuple[str, ...] = ASSETS) -> dict[str, Any]:
    """Recompute the per-asset 1h-price SHAs and the aggregate authority SHA."""
    base = data_root / "processed" / "price_1h_v2"
    per_asset: dict[str, Any] = {}
    digests: dict[str, str] = {}
    for sym in sorted(assets):
        p = base / f"{sym}_1h.jsonl"
        if not p.exists():
            raise FileNotFoundError(f"missing price authority: {p}")
        digest = sha256_file(p)
        digests[sym] = digest
        per_asset[sym] = {
            "path": str(p),
            "sha256_recomputed": digest,
            "sha256_expected": FROZEN["price_per_asset_sha256"][sym],
        }
    agg = sha256_bytes(canonical_json(digests))
    ok = agg == FROZEN["price_authority_sha256_v2"] and all(
        v["sha256_recomputed"] == v["sha256_expected"] for v in per_asset.values()
    )
    return {
        "status": "PASS" if ok else "FAIL",
        "data_root": str(data_root),
        "derivation": "PRICE_AUTHORITY_SHA256_V2 = sha256(canonical_json(sorted {symbol: sha256(file_bytes)})) per scripts/build_price_authority_v2.py",
        "price_authority_sha256_recomputed": agg,
        "price_authority_sha256_expected": FROZEN["price_authority_sha256_v2"],
        "per_asset": per_asset,
    }


def load_oi_ledger(assets: tuple[str, ...] = ASSETS) -> dict[tuple[str, str], dict[str, Any]]:
    """Forensic day-validity ledger (byte-binding only; never an eligibility gate)."""
    ledger: dict[tuple[str, str], dict[str, Any]] = {}
    with OI_LEDGER_EVIDENCE.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            if e.get("symbol") in assets:
                ledger[(str(e["symbol"]), str(e["day"]))] = e
    return ledger


def verify_oi_ledger_fingerprint(assets: tuple[str, ...] = ASSETS) -> dict[str, Any]:
    """Recompute OI_FULL_HISTORY_DATASET_SHA256_V2 from the committed ledger."""
    entries: list[dict[str, Any]] = []
    with OI_LEDGER_EVIDENCE.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    fp_files = [
        {k: e.get(k) for k in ("symbol", "day", "raw_source_sha256", "normalized_sha256", "rows", "dataset_fingerprint", "classification")}
        for e in sorted(entries, key=lambda e: (str(e["symbol"]), str(e["day"])))
    ]
    fp_src = canonical_json({"schema_version": "2.0.1", "normalizer_version": "2.1.0", "files": fp_files})
    digest = sha256_bytes(fp_src)
    ledger_sha = sha256_file(OI_LEDGER_EVIDENCE)
    manifest_src = OI_EVIDENCE_DIR / "OI_FULL_HISTORY_DATASET_MANIFEST_V2.json"
    manifest_match: bool | None = None
    if manifest_src.exists():
        m = json.loads(manifest_src.read_text(encoding="utf-8"))
        manifest_match = m.get("OI_FULL_HISTORY_DATASET_SHA256_V2") == digest
    ok = digest == FROZEN["oi_full_history_dataset_sha256_v2"]
    return {
        "status": "PASS" if ok else "FAIL",
        "ledger_path": str(OI_LEDGER_EVIDENCE),
        "ledger_sha256": ledger_sha,
        "derivation": "OI_FULL_HISTORY_DATASET_SHA256_V2 = sha256(canonical_json({schema_version,normalizer_version,files[{symbol,day,raw_source_sha256,normalized_sha256,rows,dataset_fingerprint,classification}]})) per scripts/normalize_oi_full_history_v2.py",
        "oi_dataset_sha256_recomputed": digest,
        "oi_dataset_sha256_expected": FROZEN["oi_full_history_dataset_sha256_v2"],
        "committed_manifest_cross_check": manifest_match,
    }


# ------------------------------------------------------------------ typed series
@dataclass(frozen=True)
class FundingSeries:
    asset: str
    t: tuple[int, ...]
    rate: tuple[float, ...]
    interval_hours: tuple[int, ...]
    sha256: str
    source_path: str
    rows: int

    def window_slice(self, lo_ms: int, hi_ms: int) -> list[tuple[int, float]]:
        """Closed [lo_ms, hi_ms] slice on funding_time_ms.

        ``self.t`` is sorted ascending (``load_funding`` sorts), so the bisect slice is
        exactly the set ``{ts : lo_ms <= ts <= hi_ms}``; equivalence with the naive filter
        is asserted by the test suite.
        """
        lo = bisect_left(self.t, lo_ms)
        hi = bisect_right(self.t, hi_ms)
        return list(zip(self.t[lo:hi], self.rate[lo:hi]))

    def settlements_between(self, lo_exclusive_ms: int, hi_inclusive_ms: int) -> list[float]:
        """Certified settlements in (lo, hi] -- the frozen cashflow window."""
        lo = bisect_right(self.t, lo_exclusive_ms)
        hi = bisect_right(self.t, hi_inclusive_ms)
        return list(self.rate[lo:hi])


@dataclass(frozen=True)
class Series:
    """Generic (timestamp_ms, value) authority slice for OI / price-open."""

    asset: str
    t: tuple[int, ...]
    v: tuple[float, ...]
    sha256: str
    path: str
    rows: int
    verified_days: int = 0
    unverified_days: list[str] = field(default_factory=list)

    def last_at_or_before(self, t_ms: int) -> tuple[int, float] | None:
        """Last (timestamp, value) with timestamp <= t_ms (causal, exact)."""
        ts = self.t
        lo, hi = 0, len(ts)
        while lo < hi:  # bisect_right on ascending ts, minus one
            mid = (lo + hi) // 2
            if ts[mid] <= t_ms:
                lo = mid + 1
            else:
                hi = mid
        if lo == 0:
            return None
        i = lo - 1
        return (ts[i], self.v[i])

    def first_index_strictly_after(self, t_ms: int) -> int | None:
        """Index of the first bar with open_time > t_ms (or None)."""
        ts = self.t
        lo, hi = 0, len(ts)
        while lo < hi:
            mid = (lo + hi) // 2
            if ts[mid] <= t_ms:
                lo = mid + 1
            else:
                hi = mid
        return lo if lo < len(ts) else None

    def index_of_exact(self, t_ms: int) -> int | None:
        idx = self.first_index_strictly_after(t_ms - 1)
        if idx is not None and self.t[idx] == t_ms:
            return idx
        return None


def load_funding(asset: str) -> FundingSeries:
    src, _ = resolve_funding_source()
    p = src / f"{asset}_funding.jsonl"
    ts: list[int] = []
    rates: list[float] = []
    intervals: list[int] = []
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            ts.append(int(r["funding_time_ms"]))
            rates.append(float(r["funding_rate"]))
            intervals.append(int(r["funding_interval_hours"]))
    order = sorted(range(len(ts)), key=lambda i: ts[i])
    ts = [ts[i] for i in order]
    rates = [rates[i] for i in order]
    intervals = [intervals[i] for i in order]
    return FundingSeries(asset, tuple(ts), tuple(rates), tuple(intervals), sha256_file(p), str(p), len(ts))


def load_price(data_root: Path, asset: str) -> Series:
    p = data_root / "processed" / "price_1h_v2" / f"{asset}_1h.jsonl"
    ts: list[int] = []
    opens: list[float] = []
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            ts.append(int(row[0]))
            opens.append(float(row[1]))
    return Series(asset, tuple(ts), tuple(opens), sha256_file(p), str(p), len(ts))


def load_oi(
    data_root: Path,
    asset: str,
    day_lo: str,
    day_hi: str,
    *,
    verify_days: bool = True,
) -> Series:
    """Load the certified 5m OI shards for [day_lo, day_hi] (inclusive, UTC days).

    Each shard's SHA256 is recomputed and matched against the forensic ledger's
    ``normalized_sha256`` so the loaded bytes are byte-bound to the certified
    authority. A missing ledger entry or a hash mismatch fails closed.
    """
    sym_dir = data_root / "processed" / "oi_full_history_v2" / asset
    if not sym_dir.is_dir():
        raise FileNotFoundError(f"missing OI authority dir: {sym_dir}")
    ledger = load_oi_ledger() if verify_days else {}
    ts: list[int] = []
    vals: list[float] = []
    verified = 0
    unverified: list[str] = []
    loaded_shards: list[str] = []
    for p in sorted(sym_dir.glob(f"{asset}-oi-5m-*.jsonl")):
        day = p.name[len(f"{asset}-oi-5m-") : -len(".jsonl")]
        if day < day_lo or day > day_hi:
            continue
        if verify_days:
            entry = ledger.get((asset, day))
            expected = entry.get("normalized_sha256") if entry else None
            if not expected or sha256_file(p) != expected:
                unverified.append(day)
                continue
            verified += 1
            loaded_shards.append(f"{day}:{expected}")
        with p.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                ts.append(int(r["timestamp_ms"]))
                vals.append(float(r["sum_open_interest"]))
    order = sorted(range(len(ts)), key=lambda i: ts[i])
    ts = [ts[i] for i in order]
    vals = [vals[i] for i in order]
    # deterministic duplicate policy: a conflicting duplicate timestamp fails closed
    seen: dict[int, float] = {}
    for t, v in zip(ts, vals):
        if t in seen and seen[t] != v:
            raise ValueError(f"CONFLICTING_DUPLICATE_OI {asset} ts={t}: {seen[t]} vs {v}")
        seen[t] = v
    digest = sha256_bytes(canonical_json({"asset": asset, "day_range": [day_lo, day_hi], "rows": len(ts), "shards": sorted(loaded_shards)}))
    return Series(asset, tuple(ts), tuple(vals), digest, str(sym_dir), len(ts), verified, unverified)


__all__ = [
    "ASSETS",
    "FROZEN",
    "FundingSeries",
    "Series",
    "canonical_json",
    "load_funding",
    "load_oi",
    "load_price",
    "resolve_funding_source",
    "resolve_shared_data_root",
    "sha256_bytes",
    "sha256_file",
    "verify_funding",
    "verify_oi_ledger_fingerprint",
    "verify_price",
]
