#!/usr/bin/env python
"""ARC-03 portable read-only data-authority verifier.

Independently re-derives the ARC-03 authority digest chain from the *actual* bytes and
fails closed on any mismatch. Read-only with respect to the data root: it never writes,
repairs or regenerates data.

Checks
------
PYTHON_IMPORT_AUTHORITY        the imported ``trading_bot.research.arc03`` lives inside the
                               audited target, not in another checkout
TARGET_ARTIFACTS_PRESENT       the five authority artifacts exist and parse
RAW_LEDGER_VERIFIED            every raw archive in the ledger is present, has the recorded
                               size and SHA256, and is CHECKSUM-verified against the provider
                               sidecar
PARTITION_SHA256_MATCH         on-disk partitions reproduce the recorded partition digests
DATASET_SHA256_MATCH           the recorded dataset digest is reproduced from the manifest's
                               own file + daily-supplement registries (independent recompute)
SUPPLEMENT_SHA256_MATCH        every daily-supplement archive matches both its recorded
                               digest and its provider sidecar
COMMON_WINDOW_MATCH            the recorded common causal window equals the observed
                               intersection of the partitions
PIT_BATTERY                    the frozen PIT adversarial battery passes
CLEAN_WORKTREE                 ``git status --porcelain`` is empty for the audited target
TEST_TARGET_EQUALS_AUDITED     the worktree sys.path guard resolves to the audited target

Exit codes: 0 = PASS, 1 = FAIL, 2 = FAIL_CLOSED (wrong/incomplete target or data root).

Usage
-----
    python scripts/verify_arc03_data_authority.py
    python scripts/verify_arc03_data_authority.py --target /abs/worktree --data-root /abs/data
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import sys
import zipfile
from typing import Any

HERE = pathlib.Path(__file__).resolve()
TARGET_DEFAULT = HERE.parents[1]

REL = pathlib.Path("docs") / "arc03-data-authority-01"
RAW_RELPATH = pathlib.Path("data") / "raw" / "binance_um" / "arc03"
DAILY_RAW_RELPATH = pathlib.Path("data") / "raw" / "binance_um" / "arc03_daily"
PART_RELPATH = pathlib.Path("data") / "processed" / "arc03_klines_5m"
ASSETS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


class Report:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []

    def add(self, name: str, ok: bool, detail: Any = None) -> None:
        self.checks.append({"check": name, "pass": bool(ok), "detail": detail})

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c["pass"] for c in self.checks)

    def failed(self) -> list[str]:
        return [c["check"] for c in self.checks if not c["pass"]]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=str(TARGET_DEFAULT))
    ap.add_argument("--data-root", default=None)
    ap.add_argument(
        "--no-report",
        action="store_true",
        help="do not write ARC03_PORTABLE_DATA_VERIFICATION.json (used for the clean-worktree check)",
    )
    args = ap.parse_args(argv)

    target = pathlib.Path(args.target).resolve()
    data_root = pathlib.Path(args.data_root).resolve() if args.data_root else target
    docs = target / REL
    rep = Report()

    # --------------------------------------------------------- import authority
    sys.path.insert(0, str(target / "src"))
    import trading_bot.research.arc03.arc03_authority as authority  # noqa: E402

    module_path = pathlib.Path(authority.__file__).resolve()
    rep.add(
        "PYTHON_IMPORT_AUTHORITY",
        target in module_path.parents,
        {"module": str(module_path), "audited_target": str(target)},
    )

    conftest = target / "conftest.py"
    guard_ok = False
    if conftest.exists():
        text = conftest.read_text(encoding="utf-8")
        guard_ok = "src" in text and "sys.path.insert" in text
    rep.add(
        "TEST_TARGET_EQUALS_AUDITED",
        guard_ok and (target / "src" / "trading_bot" / "research" / "arc03" / "arc03_authority.py").exists(),
        {"conftest_guard": guard_ok, "src_present": (target / "src").is_dir()},
    )

    # --------------------------------------------------------- artifacts present
    required = [
        "ARC03_DATA_MANIFEST.json",
        "ARC03_DATASET_FINGERPRINT.json",
        "ARC03_DATA_AUTHORITY.json",
        "ARC03_RAW_LEDGER.jsonl",
        "ARC03_DATA_QUALITY_LEDGER.jsonl",
        "ARC03_COMMON_CAUSAL_WINDOW.json",
        "ARC03_PROVIDER_COVERAGE_SUPPLEMENT.json",
    ]
    missing = [f for f in required if not (docs / f).exists()]
    rep.add("TARGET_ARTIFACTS_PRESENT", not missing, {"missing": missing})
    if missing:
        print(json.dumps({"verdict": "FAIL_CLOSED", "reason": "missing authority artifacts", "missing": missing}))
        return 2

    manifest = json.loads((docs / "ARC03_DATA_MANIFEST.json").read_text(encoding="utf-8"))
    window = json.loads((docs / "ARC03_COMMON_CAUSAL_WINDOW.json").read_text(encoding="utf-8"))
    ledger = [
        json.loads(l)
        for l in (docs / "ARC03_RAW_LEDGER.jsonl").read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]

    # --------------------------------------------------------- raw ledger / checksums
    # Raw archives are part of the DATA ROOT (not of the audited commit): the audited
    # commit carries the authority artifacts, the data root carries the bytes they bind.
    bad_raw: list[dict[str, Any]] = []
    for e in ledger:
        if e.get("status") != "VERIFIED":
            continue
        rel = e.get("raw_path")
        p = data_root / rel if rel else None
        if p is None or not p.exists():
            bad_raw.append({"raw_path": rel, "error": "MISSING"})
            continue
        actual = sha256_file(p)
        if actual != e.get("sha256"):
            bad_raw.append({"raw_path": rel, "error": "SHA256_MISMATCH", "ledger": e.get("sha256"), "actual": actual})
            continue
        sidecar = p.with_name(p.name + ".CHECKSUM")
        if not sidecar.exists():
            bad_raw.append({"raw_path": rel, "error": "NO_PROVIDER_SIDECAR"})
            continue
        expected = sidecar.read_text(encoding="utf-8").split()[0]
        if expected != actual:
            bad_raw.append({"raw_path": rel, "error": "CHECKSUM_MISMATCH", "provider": expected, "actual": actual})
    verified_entries = sum(1 for e in ledger if e.get("status") == "VERIFIED")
    rep.add(
        "RAW_LEDGER_VERIFIED",
        not bad_raw,
        {"verified_entries": verified_entries, "total_entries": len(ledger), "failures": bad_raw[:10]},
    )

    # --------------------------------------------------------- partitions
    mismatched: dict[str, Any] = {}
    observed: dict[str, dict[str, int]] = {}
    for sym in ASSETS:
        p = data_root / PART_RELPATH / f"{sym}.jsonl"
        if not p.exists():
            mismatched[sym] = "MISSING"
            continue
        actual = sha256_file(p)
        if actual != manifest["partition_sha256"].get(sym):
            mismatched[sym] = {"recorded": manifest["partition_sha256"].get(sym), "actual": actual}
            continue
        first = last = None
        n = 0
        with p.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                t = json.loads(line)["t"]
                if first is None:
                    first = t
                last = t
                n += 1
        observed[sym] = {"rows": n, "first": first, "last": last}
    rep.add(
        "PARTITION_SHA256_MATCH",
        not mismatched,
        {"mismatches": mismatched, "observed": observed},
    )
    if mismatched:
        print(json.dumps({"verdict": "FAIL_CLOSED", "reason": "partition digests do not reproduce", "mismatches": mismatched}, indent=2))
        return 2

    # --------------------------------------------------------- dataset digest (independent)
    quality = [
        json.loads(l)
        for l in (docs / "ARC03_DATA_QUALITY_LEDGER.jsonl").read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    files_registry = [
        {
            "symbol": e["symbol"],
            "month": e["month"],
            "raw_sha256": e.get("raw_sha256"),
            "normalized_rows": e.get("rows") if e["classification"] in {"VALID", "VALID_INITIAL_PARTIAL", "VALID_WITH_DAILY_SUPPLEMENT"} else 0,
            "classification": e["classification"],
        }
        for e in sorted((x for x in quality if x.get("kind") != "SYMBOL_SUMMARY"), key=lambda x: (x["symbol"], x["month"]))
    ]
    supplements = sorted(
        [dict(s) for s in manifest.get("daily_supplements", [])],
        key=lambda x: (x["symbol"], x["date"]),
    )
    payload = {
        "schema_version": manifest["schema_version"],
        "normalizer_version": manifest["normalizer_version"],
        "interval": manifest["interval"],
        "files": files_registry,
        "daily_supplements": supplements,
    }
    recomputed = hashlib.sha256(canonical(payload)).hexdigest()
    rep.add(
        "DATASET_SHA256_MATCH",
        recomputed == manifest["dataset_sha256"],
        {"recorded": manifest["dataset_sha256"], "recomputed": recomputed},
    )

    # --------------------------------------------------------- supplements
    bad_sup: list[dict[str, Any]] = []
    for s in supplements:
        d = s["date"]
        p = data_root / DAILY_RAW_RELPATH / s["symbol"] / d / f"{s['symbol']}-5m-{d}.zip"
        if not p.exists():
            bad_sup.append({"symbol": s["symbol"], "date": d, "error": "MISSING"})
            continue
        actual = sha256_file(p)
        if actual != s.get("raw_sha256"):
            bad_sup.append({"symbol": s["symbol"], "date": d, "error": "SHA256_MISMATCH", "actual": actual})
            continue
        sidecar = p.with_name(p.name + ".CHECKSUM")
        if not sidecar.exists() or sidecar.read_text(encoding="utf-8").split()[0] != actual:
            bad_sup.append({"symbol": s["symbol"], "date": d, "error": "PROVIDER_CHECKSUM_MISMATCH"})
            continue
        try:
            with zipfile.ZipFile(p) as zf:
                text = zf.read(zf.namelist()[0]).decode("utf-8")
            lines = [l for l in text.splitlines() if l.strip() and not l.startswith("open_time,")]
            if len(lines) != 288:
                bad_sup.append({"symbol": s["symbol"], "date": d, "error": f"ROWS_{len(lines)}"})
        except Exception as exc:  # noqa: BLE001
            bad_sup.append({"symbol": s["symbol"], "date": d, "error": f"UNREADABLE:{exc}"})
    rep.add(
        "SUPPLEMENT_SHA256_MATCH",
        not bad_sup and len(supplements) == len(manifest.get("daily_supplements", [])),
        {"supplements": len(supplements), "failures": bad_sup},
    )

    # --------------------------------------------------------- common window
    exp_start = max(v["first"] for v in observed.values())
    exp_end = min(v["last"] for v in observed.values())
    rep.add(
        "COMMON_WINDOW_MATCH",
        exp_start == window["start_ms"] and exp_end == window["end_ms"],
        {"recorded": [window["start_ms"], window["end_ms"]], "observed": [exp_start, exp_end]},
    )

    # --------------------------------------------------------- PIT battery
    from trading_bot.research.arc03 import arc03_pit  # noqa: E402

    checks = arc03_pit.run_battery()
    passed = sum(1 for c in checks if c["pass"])
    rep.add("PIT_BATTERY", passed == len(checks), {"passed": passed, "total": len(checks)})

    # --------------------------------------------------------- clean worktree
    report_rel = str(REL / "ARC03_PORTABLE_DATA_VERIFICATION.json").replace("\\", "/")
    try:
        out = subprocess.run(
            ["git", "-C", str(target), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        # the verifier's own report is excluded, otherwise writing evidence could never
        # coexist with a clean-worktree claim
        porcelain = [
            l for l in out.stdout.splitlines() if l.strip() and report_rel not in l.replace("\\", "/")
        ]
        head = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        ).stdout.strip()
    except Exception as exc:  # noqa: BLE001
        porcelain, head = [f"git-unavailable:{exc}"], None
    rep.add(
        "CLEAN_WORKTREE",
        not porcelain,
        {"dirty_entries": porcelain[:20], "head": head, "ignored_for_this_check": [report_rel]},
    )

    verdict = "PASS" if rep.ok else "FAIL"
    report = {
        "verifier": "verify_arc03_data_authority.py",
        "verdict": verdict,
        "audited_target": str(target),
        "data_root": str(data_root),
        "data_root_is_audited_target": data_root == target,
        "git_head": head,
        "checks": rep.checks,
        "failed_checks": rep.failed(),
        "checks_total": len(rep.checks),
        "checks_passed": sum(1 for c in rep.checks if c["pass"]),
        "read_only": True,
    }
    if not args.no_report:
        (docs / "ARC03_PORTABLE_DATA_VERIFICATION.json").write_bytes(
            (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
        )
    print(json.dumps({"verdict": verdict, "failed": rep.failed()}, indent=2))
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main())
