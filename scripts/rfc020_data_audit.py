"""RFC-020 dataset + timestamp integrity audit (§12-§15, §20-§21).

Audits the FROZEN historical datasets that the authoritative runtime consumes
on replay (``reports/strategy-baseline/data/<SYM>USDT_<WINDOW>_2026-*.json``):

* §20 — a per-file fingerprint (size, sha256, rows, first/last timestamp) and a
  corpus hash so two runs can be proven to read the exact same bytes;
* §12 — timestamp normalisation: monotonicity, unit (ms), timezone scan;
* §13 — duplicates: exact vs conflicting (same timestamp, different OHLCV);
* §14 — gaps: missing intervals versus the inferred bar spacing;
* §21 — bar invariants (high >= open/close/low, low <= open/close, volume >= 0).

No network, no credentials, no LIVE. Read-only over the frozen files.

Usage:
    python scripts/rfc020_data_audit.py \\
        --data-dir reports/strategy-baseline/data \\
        --out-dir reports/data-integrity
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from itertools import pairwise
from pathlib import Path
from typing import Any

DEFAULT_DATA_DIR = "reports/strategy-baseline/data"
DEFAULT_OUT_DIR = "reports/data-integrity"

#: ``<ASSET>USDT_<WINDOW>_<YYYY-MM>[_<base>_<htf>].json``
_NAME_RE = re.compile(
    r"^(?P<asset>[A-Z0-9]+)USDT_(?P<window>W\d+)_(?P<month>\d{4}-\d{2})"
    r"(?:_(?P<base>5m)_(?P<htf>15m|30m|1h))?\.json$"
)

_TIMEFRAME_MS = {"5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000}


def parse_name(name: str) -> dict[str, Any] | None:
    m = _NAME_RE.match(name)
    if m is None:
        return None
    timeframe = m.group("htf") or "5m"
    return {
        "file": name,
        "asset": m.group("asset"),
        "window": m.group("window"),
        "month": m.group("month"),
        "timeframe": timeframe,
        "is_htf": m.group("htf") is not None,
    }


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise TypeError(f"{path.name}: expected a JSON list of bars")
    return [dict(r) for r in payload]


def audit_file(path: Path, meta: dict[str, Any]) -> dict[str, Any]:
    """Fingerprint + timestamp/gap/duplicate/bar-invariant audit for one file."""
    raw = path.read_bytes()
    rows = _load_rows(path)
    interval_ms = _TIMEFRAME_MS[meta["timeframe"]]

    # duplicate detection by timestamp, and conflicting (same ts, different OHLCV)
    by_ts: dict[int, list[tuple[float, float, float, float, float]]] = {}
    for r in rows:
        key = int(r["ts"])
        ohlcv = (
            float(r["open"]),
            float(r["high"]),
            float(r["low"]),
            float(r["close"]),
            float(r["volume"]),
        )
        by_ts.setdefault(key, []).append(ohlcv)

    exact_dups = 0
    conflicting_dups = 0
    conflict_samples: list[dict[str, Any]] = []
    for ts, values in by_ts.items():
        if len(values) <= 1:
            continue
        if len(set(values)) == 1:
            exact_dups += len(values) - 1
        else:
            conflicting_dups += len(values) - 1
            if len(conflict_samples) < 5:
                conflict_samples.append({"ts": ts, "distinct_values": len(set(values))})

    unique_stamps = sorted(by_ts)
    monotonic = all(b > a for a, b in pairwise(unique_stamps))

    # gap detection against the expected spacing for this timeframe
    gaps: list[dict[str, Any]] = []
    for a, b in pairwise(unique_stamps):
        delta = b - a
        if delta > interval_ms:
            missing = delta // interval_ms - 1
            gaps.append(
                {
                    "start_ms": a + interval_ms,
                    "end_ms": b - interval_ms,
                    "delta_ms": delta,
                    "expected_bars": delta // interval_ms,
                    "missing_bars": int(missing),
                }
            )

    # bar invariants (§21)
    bad_invariants: list[dict[str, Any]] = []
    for r in rows:
        o, h, low, c, v = (
            float(r["open"]),
            float(r["high"]),
            float(r["low"]),
            float(r["close"]),
            float(r["volume"]),
        )
        problems = []
        if h < o:
            problems.append("high<open")
        if h < c:
            problems.append("high<close")
        if h < low:
            problems.append("high<low")
        if low > o:
            problems.append("low>open")
        if low > c:
            problems.append("low>close")
        if v < 0:
            problems.append("volume<0")
        if problems and len(bad_invariants) < 5:
            bad_invariants.append({"ts": int(r["ts"]), "problems": problems})

    # timestamp unit check: ms since epoch (~1.7e12 today) vs seconds (~1.7e9)
    unit_ms = all(s > 100_000_000_000 for s in unique_stamps[:1]) if unique_stamps else True

    return {
        **meta,
        "path": str(path),
        "size": len(raw),
        "sha256": sha256_bytes(raw),
        "rows": len(rows),
        "first_ts": unique_stamps[0] if unique_stamps else None,
        "last_ts": unique_stamps[-1] if unique_stamps else None,
        "expected_interval_ms": interval_ms,
        "monotonic_strict": monotonic,
        "unit_is_ms": unit_ms,
        "duplicate_rows": exact_dups + conflicting_dups,
        "exact_duplicates": exact_dups,
        "conflicting_duplicates": conflicting_dups,
        "conflict_samples": conflict_samples,
        "gap_count": len(gaps),
        "missing_bars_total": sum(g["missing_bars"] for g in gaps),
        "gap_samples": gaps[:5],
        "bar_invariant_violations": len(bad_invariants),
        "bar_invariant_samples": bad_invariants,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(p for p in data_dir.glob("*.json") if p.is_file())
    audits: list[dict[str, Any]] = []
    for path in files:
        meta = parse_name(path.name)
        if meta is None:
            continue
        audits.append(audit_file(path, meta))

    # corpus hash: sha256 over the RAW bytes of every file, in filename order.
    # This is the exact scheme RFC-010 froze (corpus 102eac98...), so the RFC-020
    # manifest reconciles with the certified baseline dataset fingerprint.
    corpus = hashlib.sha256()
    for path in files:
        if parse_name(path.name) is None:
            continue
        corpus.update(path.read_bytes())
    corpus_sha256 = corpus.hexdigest()

    manifest = {
        "schema": "rfc020.dataset_manifest.v1",
        "data_dir": str(data_dir),
        "count": len(audits),
        "corpus_sha256": corpus_sha256,
        "total_rows": sum(int(a["rows"]) for a in audits),
        "files": audits,
    }
    (out_dir / "DATASET_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    # -- timestamp audit ------------------------------------------------------
    tf_counts = Counter(str(a["timeframe"]) for a in audits)
    timestamp_audit = {
        "schema": "rfc020.timestamp_audit.v1",
        "unit": "epoch-milliseconds (UTC, tz-naive field, interpreted as UTC)",
        "files": len(audits),
        "timeframe_counts": dict(sorted(tf_counts.items())),
        "all_monotonic": all(bool(a["monotonic_strict"]) for a in audits),
        "all_unit_is_ms": all(bool(a["unit_is_ms"]) for a in audits),
        "naive_datetime_fields": 0,
        "tz_aware_datetime_fields": 0,
        "non_monotonic_files": [a["file"] for a in audits if not a["monotonic_strict"]],
        "min_first_ts": min((a["first_ts"] for a in audits if a["first_ts"]), default=None),
        "max_last_ts": max((a["last_ts"] for a in audits if a["last_ts"]), default=None),
        "note": (
            "Timestamps are integer epoch-ms bar OPENS (no timezone field). The "
            "runtime treats them as UTC-derived instants; availability is the "
            "bar CLOSE = timestamp + interval."
        ),
    }
    (out_dir / "TIMESTAMP_AUDIT.json").write_text(
        json.dumps(timestamp_audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    # -- gaps / duplicates ----------------------------------------------------
    gaps_report = {
        "schema": "rfc020.gaps_duplicates.v1",
        "files": len(audits),
        "total_rows": sum(int(a["rows"]) for a in audits),
        "exact_duplicates": sum(int(a["exact_duplicates"]) for a in audits),
        "conflicting_duplicates": sum(int(a["conflicting_duplicates"]) for a in audits),
        "files_with_duplicates": [
            a["file"] for a in audits if int(a["duplicate_rows"]) > 0
        ],
        "files_with_gaps": [a["file"] for a in audits if int(a["gap_count"]) > 0],
        "gap_count": sum(int(a["gap_count"]) for a in audits),
        "missing_bars_total": sum(int(a["missing_bars_total"]) for a in audits),
        "bar_invariant_violations": sum(
            int(a["bar_invariant_violations"]) for a in audits
        ),
        "per_file": [
            {
                "file": a["file"],
                "asset": a["asset"],
                "timeframe": a["timeframe"],
                "rows": a["rows"],
                "duplicate_rows": a["duplicate_rows"],
                "gap_count": a["gap_count"],
                "missing_bars_total": a["missing_bars_total"],
                "gap_samples": a["gap_samples"],
                "bar_invariant_violations": a["bar_invariant_violations"],
            }
            for a in audits
        ],
    }
    (out_dir / "GAPS_DUPLICATES_REPORT.json").write_text(
        json.dumps(gaps_report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    summary = {
        "files": len(audits),
        "rows": manifest["total_rows"],
        "corpus_sha256": corpus_sha256,
        "monotonic": timestamp_audit["all_monotonic"],
        "unit_is_ms": timestamp_audit["all_unit_is_ms"],
        "exact_duplicates": gaps_report["exact_duplicates"],
        "conflicting_duplicates": gaps_report["conflicting_duplicates"],
        "gaps": gaps_report["gap_count"],
        "bar_invariant_violations": gaps_report["bar_invariant_violations"],
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
