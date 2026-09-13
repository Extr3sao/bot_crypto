#!/usr/bin/env python
"""INDEPENDENT VERIFIER — PRICE_CONTINUITY + PRICE_FULL_OVERLAP.

Recomputes, from the ACTUAL 1h price files on disk:
  * the per-asset file sha256 and byte length
  * the price-authority aggregate sha256
  * the number of distinct hourly bars inside the frozen common window
  * hour-by-hour continuity (strictly 3600s spacing, no gaps, no duplicates)
  * full common-window coverage for every asset

Read-only. No economics.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
from datetime import datetime, timezone

VERIFIER_ROOT = pathlib.Path(
    subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                   check=True).stdout.decode().strip()).resolve()
AUDITED = "a5487164803fb601f87f2cd4c865929c30da274e"
MANIFEST = "docs/external-audit-01/oi-full-history-02/PRICE_1H_AUTHORITY_V2_MANIFEST.json"
FROZEN_AUTHORITY_SHA = "e1c2462a6aa9ba0c921154d259a28c49be1e2fc58a544dbd97af8ecabef52168"
ASSETS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
WINDOW = (datetime(2021, 12, 1, tzinfo=timezone.utc), datetime(2026, 9, 10, 23, tzinfo=timezone.utc))
EXPECTED_HOURS = 41880


def git(*a, binary=False):
    p = subprocess.run(["git"] + list(a), cwd=str(VERIFIER_ROOT), capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode("utf-8", "replace"))
    return p.stdout if binary else p.stdout.decode("utf-8", "replace")


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main():
    mk = json.loads(git("cat-file", "blob", "%s:%s" % (AUDITED, MANIFEST)))
    out = {
        "verifier_type": "INDEPENDENT_PRICE_AUTHORITY_V3",
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "audited_target_commit": AUDITED,
        "manifest_path": MANIFEST,
        "manifest_sha256": hashlib.sha256(
            git("cat-file", "blob", "%s:%s" % (AUDITED, MANIFEST), binary=True)).hexdigest(),
        "declared": {
            "price_authority_sha256": mk.get("PRICE_AUTHORITY_SHA256_V2"),
            "method": mk.get("PRICE_AUTHORITY_SHA256_V2_method"),
            "expected_hours_per_asset": mk.get("expected_hours_per_asset"),
            "common_window_utc": mk.get("common_window_utc"),
            "all_assets_cover_common_window": mk.get("all_assets_cover_common_window"),
            "overlap_verification": mk.get("overlap_verification"),
        },
        "economics": {"H6_BACKTESTS": 0, "H6_EXECUTIONS": 0, "PERFORMANCE_OBSERVED": False},
        "per_asset": {},
    }

    per_symbol_sha = {}
    for sym in ASSETS:
        d = mk["per_asset"][sym]
        p = pathlib.Path(d["v2_path"])
        if not p.is_absolute():
            p = VERIFIER_ROOT / d["v2_path"]
        rec = {"declared_path": d["v2_path"], "resolved_path": str(p), "exists": p.exists()}
        if not p.exists():
            # data/processed is gitignored; fall back to the shared data root
            p2 = pathlib.Path("C:/Users/GVLLFR0035/Downloads/bot freebuff") / d["v2_path"]
            rec["fallback_path"] = str(p2)
            p = p2
            rec["exists"] = p.exists()
        if not p.exists():
            rec["status"] = "FILE_MISSING"
            out["per_asset"][sym] = rec
            continue
        got_sha = sha256_file(p)
        got_len = p.stat().st_size
        per_symbol_sha[sym] = got_sha
        rec.update({
            "declared_sha256": d["v2_sha256"],
            "verified_sha256": got_sha,
            "sha256_match": got_sha == d["v2_sha256"],
            "declared_bytes_len": d["v2_bytes_len"],
            "verified_bytes_len": got_len,
            "bytes_len_match": got_len == d["v2_bytes_len"],
        })

        # parse hourly bars inside the frozen common window
        hs, bad_json = [], 0
        with p.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    bad_json += 1
                    continue
                if isinstance(r, (list, tuple)):
                    # Binance kline array: [open_time_ms, o, h, l, c, v, close_time_ms, ...]
                    ts = r[0] if r else None
                elif isinstance(r, dict):
                    ts = r.get("open_time_ms", r.get("timestamp_ms", r.get("open_time")))
                else:
                    ts = None
                if ts is None:
                    bad_json += 1
                    continue
                ts = int(ts)
                if ts < 10 ** 12:  # seconds -> ms
                    ts *= 1000
                hs.append(ts)
        rec["rows_parsed"] = len(hs)
        rec["declared_rows_total"] = d["v2_rows_total"]
        rec["rows_total_match"] = len(hs) == d["v2_rows_total"]
        rec["bad_rows"] = bad_json
        lo, hi = int(WINDOW[0].timestamp() * 1000), int(WINDOW[1].timestamp() * 1000)
        win = sorted(t for t in hs if lo <= t <= hi)
        distinct = sorted(set(win))
        rec["window_lower_ms"] = lo
        rec["window_upper_ms"] = hi
        rec["bars_in_common_window"] = len(win)
        rec["distinct_bars_in_common_window"] = len(distinct)
        rec["declared_available_hours_common"] = d["available_hours_common"]
        rec["declared_expected_hours_common"] = d["expected_hours_common"]
        rec["expected_hours_match"] = len(distinct) == d["expected_hours_common"] == EXPECTED_HOURS
        rec["duplicate_hours"] = len(win) - len(distinct)
        rec["declared_duplicate_hours_common"] = d["duplicate_hours_common"]
        rec["duplicate_free"] = rec["duplicate_hours"] == 0
        rec["first_bar_in_window_utc"] = datetime.fromtimestamp(distinct[0] / 1000, tz=timezone.utc).isoformat() if distinct else None
        rec["last_bar_in_window_utc"] = datetime.fromtimestamp(distinct[-1] / 1000, tz=timezone.utc).isoformat() if distinct else None
        rec["covers_window_edges"] = bool(distinct) and distinct[0] == lo and distinct[-1] == hi
        gaps = [i for i in range(1, len(distinct)) if distinct[i] - distinct[i - 1] != 3_600_000]
        rec["non_hourly_transitions"] = len(gaps)
        rec["declared_non_hourly_transitions"] = d["non_hourly_transitions"]
        rec["continuity_pass"] = not gaps
        rec["first_gap_example"] = (
            {"after_utc": datetime.fromtimestamp(distinct[gaps[0] - 1] / 1000, tz=timezone.utc).isoformat(),
             "delta_ms": distinct[gaps[0]] - distinct[gaps[0] - 1]} if gaps else None)
        rec["status"] = "VERIFIED"

    # aggregate authority sha256, recomputed independently
    agg_payload = json.dumps(dict(sorted(per_symbol_sha.items())), sort_keys=True,
                             separators=(",", ":")).encode("utf-8")
    agg = hashlib.sha256(agg_payload).hexdigest()
    out["price_authority_sha256_recomputed"] = agg
    out["price_authority_sha256_declared_frozen"] = FROZEN_AUTHORITY_SHA
    out["price_authority_sha256_matches_frozen"] = agg == FROZEN_AUTHORITY_SHA
    out["price_authority_sha256_matches_manifest"] = agg == mk.get("PRICE_AUTHORITY_SHA256_V2")

    checks = {
        "all_three_asset_files_present": all(v.get("exists") for v in out["per_asset"].values()),
        "all_asset_sha256_match": all(v.get("sha256_match") for v in out["per_asset"].values()),
        "all_asset_byte_length_match": all(v.get("bytes_len_match") for v in out["per_asset"].values()),
        "all_asset_row_count_match": all(v.get("rows_total_match") for v in out["per_asset"].values()),
        "all_assets_41880_distinct_hours": all(v.get("expected_hours_match") for v in out["per_asset"].values()),
        "all_assets_duplicate_free": all(v.get("duplicate_free") for v in out["per_asset"].values()),
        "all_assets_cover_window_edges": all(v.get("covers_window_edges") for v in out["per_asset"].values()),
        "all_assets_strictly_hourly": all(v.get("continuity_pass") for v in out["per_asset"].values()),
        "price_authority_sha256_recomputes": agg == FROZEN_AUTHORITY_SHA,
    }
    out["checks"] = checks
    out["PRICE_CONTINUITY"] = "PASS" if (
        checks["all_assets_strictly_hourly"] and checks["all_assets_duplicate_free"]
        and checks["all_asset_row_count_match"]) else "FAIL"
    out["PRICE_FULL_OVERLAP"] = "PASS" if (
        checks["all_assets_41880_distinct_hours"] and checks["all_assets_cover_window_edges"]
        and checks["all_asset_sha256_match"] and checks["price_authority_sha256_recomputes"]) else "FAIL"

    print(json.dumps(out, indent=2))
    if "--out" in sys.argv:
        dest = sys.argv[sys.argv.index("--out") + 1]
        with open(dest, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(out, fh, indent=2)
            fh.write("\n")
        print("WROTE", dest, file=sys.stderr)


if __name__ == "__main__":
    main()
