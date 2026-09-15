#!/usr/bin/env python
"""ARC-03 data authority builder (deterministic, performance-blind).

Pipeline::

    RAW PROVIDER BYTES (official Binance USD-M monthly archive)
      -> normalized partitions (data/processed/arc03_klines_5m/{SYMBOL}.jsonl)
      -> partition SHA256
      -> deterministic manifest
      -> DATASET SHA256

Also performs, in the same run:

* provider ``.CHECKSUM`` verification of every raw archive;
* data-quality ledger (per month, per symbol) with fail-closed classification;
* **A/B independent normalization** (a second, independently written re-parser must
  reproduce the partition bytes exactly);
* **mutation sensitivity** (mutating one raw value must change the dataset digest while
  the canonical authority stays byte-identical);
* the frozen **PIT adversarial battery**;
* the exact **common causal window** across BTCUSDT/ETHUSDT/SOLUSDT.

No economic quantity is computed anywhere in this file: no returns, no PnL, no
signals, no thresholds. Only provenance, coverage, quality and causal semantics.

Usage::

    python scripts/build_arc03_data_authority.py
    python scripts/build_arc03_data_authority.py --data-root /abs/path
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import shutil
import sys
import tempfile
import zipfile
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trading_bot.research.arc03.arc03_authority import (  # noqa: E402
    ASSETS,
    BAR_MS,
    common_causal_window,
    load_partition,
    resolve_partition_dir,
)
from trading_bot.research.arc03.arc03_normalize import (  # noqa: E402
    ADMITTED_CLASSIFICATIONS,
    DAILY_RAW_RELPATH,
    EXPECTED_HEADER,
    INTERVAL,
    NORMALIZER_VERSION,
    SCHEMA_VERSION,
    build_manifest,
    canonical_json,
    expected_rows,
    month_first_open_ms,
    normalize_symbol,
    sha256_bytes,
    sha256_file,
    write_json_bytes,
    write_jsonl_bytes,
)
from trading_bot.research.arc03 import arc03_pit  # noqa: E402

RAW_RELPATH = pathlib.Path("data") / "raw" / "binance_um" / "arc03"
PROC_RELPATH = pathlib.Path("data") / "processed" / "arc03_klines_5m"
DOCS_RELPATH = pathlib.Path("docs") / "arc03-data-authority-01"

CHECKPOINT = "ARC03-DATA-001"


# --------------------------------------------------------------------------- util
def _independent_reparse(
    symbol: str,
    raw_dir: pathlib.Path,
    *,
    admitted_months: list[str],
    daily_root: pathlib.Path,
) -> bytes:
    """A/B independent normalization (second, separately written implementation).

    Different control flow from ``arc03_normalize.parse_month``: manual field indexing,
    different validation order, provider strings kept verbatim, and — for coverage
    gaps — the missing slots are located by *expected-slot arithmetic* and pulled from
    the official daily archives rather than by reusing the authority's own gap logic.

    Scope of the A/B claim: two independent implementations of the ROW-EXTRACTION
    contract must produce byte-identical partitions. The admitted-month list is a
    shared input; admission POLICY is verified separately (quality ledger + PIT battery).

    Raises ``AssertionError`` when the two implementations disagree, so a mismatch is
    impossible to miss.
    """
    out = bytearray()
    monthly: dict[str, dict[int, dict[str, Any]]] = {}
    for month in admitted_months:
        zp = raw_dir / month / f"{symbol}-{INTERVAL}-{month}.zip"
        with zipfile.ZipFile(zp) as zf:
            text = zf.read(zf.namelist()[0]).decode("utf-8")
        recs: dict[int, dict[str, Any]] = {}
        for raw_line in text.splitlines():
            if not raw_line.strip():
                continue
            if raw_line.startswith("open_time,"):
                assert raw_line.strip() == EXPECTED_HEADER, "unexpected header"
                continue
            f = raw_line.split(",")
            assert len(f) == 12, f"field count drift in {symbol} {month}"
            t = int(f[0])
            recs.setdefault(
                t,
                {
                    "t": t,
                    "ct": int(f[6]),
                    "o": f[1],
                    "h": f[2],
                    "l": f[3],
                    "c": f[4],
                    "v": f[5],
                    "qv": f[7],
                    "n": int(f[8]),
                    "tb": f[9],
                    "tq": f[10],
                    "sym": symbol,
                    "ms": month,
                },
            )
        monthly[month] = recs

    daily_cache: dict[str, dict[int, dict[str, Any]]] = {}

    def _daily(date: str) -> dict[int, dict[str, Any]]:
        if date not in daily_cache:
            zp = daily_root / symbol / date / f"{symbol}-{INTERVAL}-{date}.zip"
            recs: dict[int, dict[str, Any]] = {}
            if zp.exists():
                with zipfile.ZipFile(zp) as zf:
                    text = zf.read(zf.namelist()[0]).decode("utf-8")
                for raw_line in text.splitlines():
                    if not raw_line.strip() or raw_line.startswith("open_time,"):
                        continue
                    f = raw_line.split(",")
                    t = int(f[0])
                    recs[t] = {
                        "t": t,
                        "ct": int(f[6]),
                        "o": f[1],
                        "h": f[2],
                        "l": f[3],
                        "c": f[4],
                        "v": f[5],
                        "qv": f[7],
                        "n": int(f[8]),
                        "tb": f[9],
                        "tq": f[10],
                        "sym": symbol,
                        "ms": date,
                    }
            daily_cache[date] = recs
        return daily_cache[date]

    for index, month in enumerate(admitted_months):
        recs = dict(monthly[month])
        mstart = month_first_open_ms(month)
        mend = mstart + (expected_rows(month) - 1) * BAR_MS
        lo = min(recs) if index == 0 else mstart
        want = list(range(lo, mend + 1, BAR_MS))
        for t in want:
            if t in recs:
                continue
            date = dt.datetime.fromtimestamp(t / 1000, tz=dt.timezone.utc).strftime("%Y-%m-%d")
            got = _daily(date).get(t)
            assert got is not None, f"unresolved slot {t} ({symbol} {month})"
            recs[t] = got
        assert len(recs) == len(want), f"row count mismatch {symbol} {month}"
        for t in want:
            out += (json.dumps(recs[t], sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    return bytes(out)


def _mutate_archive(src: pathlib.Path, dst: pathlib.Path, *, field_index: int, delta: float) -> None:
    """Byte-level mutation of one numeric field of the first archived data row."""
    with zipfile.ZipFile(src) as zf:
        name = zf.namelist()[0]
        text = zf.read(name).decode("utf-8")
    lines = text.split("\n")
    target = None
    for i, ln in enumerate(lines):
        if ln.strip() and not ln.startswith("open_time,"):
            target = i
            break
    assert target is not None, "archive has no data row"
    parts = lines[target].split(",")
    parts[field_index] = repr(float(parts[field_index]) + delta)
    lines[target] = ",".join(parts)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dst, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(name, "\n".join(lines))


def _digest_of(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def _git_head(repo: pathlib.Path) -> str | None:
    """Best-effort HEAD of the worktree (never embedded in identity digests)."""
    import subprocess

    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        return out.stdout.strip()
    except Exception:  # pragma: no cover - git absent
        return None


# --------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", default=None, help="absolute data root (default: in-tree repo root)")
    args = ap.parse_args()

    root = pathlib.Path(args.data_root).resolve() if args.data_root else ROOT
    raw_root = root / RAW_RELPATH
    daily_root = root / DAILY_RAW_RELPATH
    proc_dir = root / PROC_RELPATH
    docs = ROOT / DOCS_RELPATH
    docs.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {"checkpoint": CHECKPOINT, "data_root": str(root)}

    # ------------------------------------------------------- 1. normalization
    print("== normalize ==")
    quality_ledger: list[dict[str, Any]] = []
    parts: list[dict[str, Any]] = []
    for symbol in ASSETS:
        raw_dir = raw_root / symbol
        ledger, rows, sha = normalize_symbol(
            symbol, raw_dir, write=True, out_dir=proc_dir, daily_root=daily_root
        )
        for e in ledger:
            e["checkpoint"] = CHECKPOINT
        quality_ledger.extend(ledger)
        summary = next(e for e in ledger if e.get("kind") == "SYMBOL_SUMMARY")
        print(
            f"  {symbol}: admitted_rows={summary['admitted_rows']} months={summary['admitted_months']}"
            f" withheld={summary['withheld_months']} cadence_breaks={summary['internal_cadence_breaks_admitted']}"
        )
        parts.append({"symbol": symbol, "sha256": sha, **{k: v for k, v in summary.items() if k != "symbol"}})
        report.setdefault("per_symbol", {})[symbol] = summary

    write_jsonl_bytes(docs / "ARC03_DATA_QUALITY_LEDGER.jsonl", quality_ledger)

    # ------------------------------------------------------- 2. manifest + fp
    manifest = build_manifest(parts, quality_ledger)
    base_commit = _git_head(root)
    manifest["authority_commit"] = None  # filled by the commit step (never self-referential)
    manifest["generated_from_commit"] = base_commit
    manifest["report_commit"] = None
    write_json_bytes(docs / "ARC03_DATA_MANIFEST.json", manifest)
    dataset_sha = manifest["dataset_sha256"]
    print(f"  dataset_sha256 = {dataset_sha}")

    fingerprint = {
        "checkpoint": CHECKPOINT,
        "family": "binance_usdm_klines_5m",
        "schema_version": SCHEMA_VERSION,
        "normalizer_version": NORMALIZER_VERSION,
        "interval": INTERVAL,
        "bar_ms": BAR_MS,
        "assets": list(ASSETS),
        "partition_sha256": manifest["partition_sha256"],
        "raw_files_sha256": manifest["raw_files_sha256"],
        "dataset_sha256": dataset_sha,
        "dataset_sha256_method": manifest["dataset_sha256_method"],
        "asset_fingerprint_sha256": {
            s: _digest_of({"symbol": s, "raw_files_sha256": manifest["raw_files_sha256"], "partition_sha256": manifest["partition_sha256"][s]})
            for s in ASSETS
        },
    }
    write_json_bytes(docs / "ARC03_DATASET_FINGERPRINT.json", fingerprint)

    # ------------------------------------------------------- 3. reader load + window
    print("== load partitions + common window ==")
    klines = {s: load_partition(s, partition_dir=proc_dir) for s in ASSETS}
    for s, k in klines.items():
        if k.sha256 != manifest["partition_sha256"][s]:
            raise SystemExit(f"INFRASTRUCTURE_FAIL: partition digest mismatch for {s}")
    window = common_causal_window(klines)
    window.update(
        {
            "checkpoint": CHECKPOINT,
            "start_utc": dt.datetime.fromtimestamp(window["start_ms"] / 1000, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_utc": dt.datetime.fromtimestamp(window["end_ms"] / 1000, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "decision_eligibility_semantics": (
                "a decision requires the signal bar to be complete (bar_close_time_ms <= decision_time_ms) and "
                "30 complete same-slot daily reference bars and 12 forward bars, all inside the admitted partitions"
            ),
        }
    )
    write_json_bytes(docs / "ARC03_COMMON_CAUSAL_WINDOW.json", window)
    print(f"  window = [{window['start_utc']} .. {window['end_utc']}]")

    # ------------------------------------------------------- 4. A/B determinism
    print("== A/B independent normalization ==")
    ab: dict[str, Any] = {"method": "independent re-parser over the same raw provider bytes", "per_symbol": {}}
    ab_ok = True
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = pathlib.Path(tmp)
        for symbol in ASSETS:
            part_path = proc_dir / f"{symbol}.jsonl"
            authority_bytes = part_path.read_bytes()
            admitted_months = [
                e["month"]
                for e in quality_ledger
                if e.get("symbol") == symbol and e.get("classification") in ADMITTED_CLASSIFICATIONS
            ]
            ab_bytes = _independent_reparse(
                symbol,
                raw_root / symbol,
                admitted_months=admitted_months,
                daily_root=daily_root,
            )
            equal = authority_bytes == ab_bytes
            ab_ok &= equal
            ab["per_symbol"][symbol] = {
                "authority_partition_sha256": sha256_bytes(authority_bytes),
                "independent_reparse_sha256": sha256_bytes(ab_bytes),
                "bytes_equal": equal,
            }
            # second, fully independent normalization invocation into a clean directory
            led2, _, sha2 = normalize_symbol(
                symbol, raw_root / symbol, write=True, out_dir=tmpdir, daily_root=daily_root
            )
            ab["per_symbol"][symbol]["second_run_sha256"] = sha2
            ab["per_symbol"][symbol]["second_run_matches"] = sha2 == sha256_bytes(authority_bytes)
            ab_ok &= sha2 == sha256_bytes(authority_bytes)
    ab["A_B_DETERMINISM"] = "PASS" if ab_ok else "FAIL"
    write_json_bytes(docs / "ARC03_DATA_DETERMINISM.json", ab)
    print(f"  A_B_DETERMINISM = {ab['A_B_DETERMINISM']}")

    # ------------------------------------------------------- 5. mutation sensitivity
    print("== mutation sensitivity ==")
    canonical_before = {
        "partition_sha256": {s: sha256_file(proc_dir / f"{s}.jsonl") for s in ASSETS},
        "dataset_sha256": dataset_sha,
    }
    mutation: dict[str, Any] = {"method": "single-value byte mutation of one raw archived row inside a copied single-month raw tree"}
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = pathlib.Path(tmp)
        src_btc = raw_root / "BTCUSDT"
        months = sorted(p.name for p in src_btc.iterdir() if p.is_dir())
        victim = months[len(months) // 2]
        src_zip = src_btc / victim / f"BTCUSDT-{INTERVAL}-{victim}.zip"
        for tree, mutate in (("base", False), ("mut", True)):
            d = tmpdir / tree / "BTCUSDT" / victim
            d.mkdir(parents=True, exist_ok=True)
            dst = d / f"BTCUSDT-{INTERVAL}-{victim}.zip"
            if mutate:
                _mutate_archive(src_zip, dst, field_index=5, delta=0.5)
            else:
                shutil.copy2(src_zip, dst)
        led_b, _, sha_b = normalize_symbol(
            "BTCUSDT", tmpdir / "base" / "BTCUSDT", write=True, out_dir=tmpdir / "pb", daily_root=daily_root
        )
        led_m, _, sha_m = normalize_symbol(
            "BTCUSDT", tmpdir / "mut" / "BTCUSDT", write=True, out_dir=tmpdir / "pm", daily_root=daily_root
        )
        mutation["victim"] = f"BTCUSDT/{victim} (field 5 = volume of the first data row, +0.5)"
        mutation["mutated_partition_sha256"] = sha_m
        mutation["baseline_subset_partition_sha256"] = sha_b
        mutation["MUTATED_SHA_DIFFERS"] = sha_m != sha_b
        mutation["baseline_month_classification"] = led_b[0]["classification"]
        mutation["mutated_month_classification"] = led_m[0]["classification"]
        mutation["mutated_differs_from_baseline_row_count"] = led_m[0]["rows"] != led_b[0]["rows"]
        canonical_after = {
            "partition_sha256": {s: sha256_file(proc_dir / f"{s}.jsonl") for s in ASSETS},
            "dataset_sha256": dataset_sha,
        }
        mutation["CANONICAL_AUTHORITY_UNCHANGED"] = canonical_before == canonical_after
    mutation["MUTATION_SENSITIVITY"] = (
        "PASS" if mutation["MUTATED_SHA_DIFFERS"] and mutation["CANONICAL_AUTHORITY_UNCHANGED"] else "FAIL"
    )
    write_json_bytes(docs / "ARC03_MUTATION_SENSITIVITY.json", mutation)
    print(f"  MUTATION_SENSITIVITY = {mutation['MUTATION_SENSITIVITY']}")

    # ------------------------------------------------------- 6. PIT battery
    print("== PIT adversarial battery ==")
    checks = arc03_pit.run_battery()
    passed = sum(1 for c in checks if c["pass"])
    pit = {
        "battery": "ARC03_PIT_ADVERSARIAL",
        "checks_total": len(checks),
        "checks_passed": passed,
        "result": "PASS" if passed == len(checks) else "FAIL",
        "checks": checks,
    }
    write_json_bytes(docs / "ARC03_PIT_INDEPENDENT_TESTS.json", pit)
    print(f"  PIT_BATTERY = {passed}/{len(checks)}")

    # ------------------------------------------------------- 7. PIT authority
    pit_authority = {
        "checkpoint": CHECKPOINT,
        "contract": {
            "data_time_le_decision_time": "every 5m bar used by a decision satisfies bar_close_time_ms <= decision_time_ms",
            "completed_bars_only": "a bar is readable only once its provider close_time has passed; the forming bar is invisible",
            "decision_instant": "decision_time_ms = close_time of the signal bar (provider field 6, epoch ms)",
            "reference_observations": "the 30 same 5m-slot daily references satisfy data_time <= decision_time trivially (t - 86400000*j)",
            "future_mutation_invariance": "bars with open_time > decision_time cannot change any feature, reason code or emitted direction",
            "past_eligible_mutation_detectable": "mutating a reference bar changes participation_shock/excursion_record",
            "conflicting_duplicates_fail_closed": "a month containing a conflicting duplicate is withheld whole; a partition with a duplicate slot raises",
            "exact_duplicates": "byte-identical duplicate rows collapse deterministically (one kept)",
            "missing_stale_fails_closed": "fewer than 30 complete reference observations -> REFERENCE_HISTORY_INCOMPLETE (NO_SIGNAL)",
            "archive_validity_not_retroactive": "later archive admission cannot alter a decision evaluated at an earlier T",
            "provider_schema_change": "a header row (from 2022-01; SOLUSDT 2022-03 excepted) is detected by exact match and skipped",
        },
        "no_future_field_admitted": [
            "ignore (provider field 12) is never read",
            "close_time is read only as the bar's own completion anchor, never as a forward observation",
        ],
        "evidence": "ARC03_PIT_INDEPENDENT_TESTS.json",
    }
    write_json_bytes(docs / "ARC03_PIT_AUTHORITY.json", pit_authority)

    # ------------------------------------------------------- 8. data authority
    authority = {
        "checkpoint": CHECKPOINT,
        "family": manifest["family"],
        "source": manifest["source"],
        "assets": list(ASSETS),
        "market": "Binance USD-M perpetual futures",
        "interval": INTERVAL,
        "raw_root": str(RAW_RELPATH).replace("\\", "/"),
        "processed_root": str(PROC_RELPATH).replace("\\", "/"),
        "normalized_schema": ["t", "ct", "o", "h", "l", "c", "v", "qv", "n", "tb", "tq", "sym", "ms"],
        "field_admission": {
            "t": "REQUIRED (bar open time, epoch ms UTC)",
            "ct": "REQUIRED (bar close time, epoch ms UTC)",
            "o": "REQUIRED (open)",
            "h": "REQUIRED (high)",
            "l": "REQUIRED (low)",
            "c": "REQUIRED (close)",
            "v": "REQUIRED (base-unit traded volume) — the ARC-03 participation field",
            "qv": "OPTIONAL_RESEARCH_ONLY (quote volume)",
            "n": "OPTIONAL_RESEARCH_ONLY (number of trades)",
            "tb": "OPTIONAL_RESEARCH_ONLY (taker buy base volume) — H5 territory, not used by ARC-03",
            "tq": "OPTIONAL_RESEARCH_ONLY (taker buy quote volume)",
            "sym": "PROVENANCE",
            "ms": "PROVENANCE (source month partition)",
        },
        "data_quality_status": manifest["quality_status"],
        "dataset_sha256": dataset_sha,
        "partition_sha256": manifest["partition_sha256"],
        "common_causal_window": window,
        "pit": "ARC03_PIT_AUTHORITY.json",
        "determinism": ab["A_B_DETERMINISM"],
        "mutation_sensitivity": mutation["MUTATION_SENSITIVITY"],
        "pit_tests": pit["result"],
    }
    write_json_bytes(docs / "ARC03_DATA_AUTHORITY.json", authority)

    summary = {
        "A_B_DETERMINISM": ab["A_B_DETERMINISM"],
        "MUTATION_SENSITIVITY": mutation["MUTATION_SENSITIVITY"],
        "PIT": pit["result"],
        "DATASET_SHA256": dataset_sha,
        "PARTITION_SHA256": manifest["partition_sha256"],
        "COMMON_WINDOW": {"start_ms": window["start_ms"], "end_ms": window["end_ms"]},
        "per_symbol": report["per_symbol"],
    }
    write_json_bytes(docs / "ARC03_BUILD_SUMMARY.json", summary)
    print(json.dumps({k: summary[k] for k in ("A_B_DETERMINISM", "MUTATION_SENSITIVITY", "PIT", "DATASET_SHA256")}, indent=2))
    ok = ab["A_B_DETERMINISM"] == "PASS" and mutation["MUTATION_SENSITIVITY"] == "PASS" and pit["result"] == "PASS"
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
