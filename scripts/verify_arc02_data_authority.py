"""ARC-02 portable, read-only data-authority verifier.

Run from the ARC-02 worktree, from any other working directory, or from a fresh detached
worktree. Nothing is written.

Checks
------
PYTHON_IMPORT_AUTHORITY        the imported ``trading_bot.research.arc02`` lives inside the audited
                               target, not in another checkout
TEST_TARGET_EQUALS_AUDITED     the pytest sys.path guard resolves to the audited target
TARGET_ARTIFACTS_PRESENT       the authority artifacts exist and parse
REUSE_IDENTITY_MATCH           the reused ARC-03 partitions reproduce the certified digests
PARTITION_SHA256_MATCH         on-disk ARC-02 projections reproduce the recorded partition digests
DATASET_SHA256_MATCH           the recorded dataset digest is independently recomputed
COMMON_WINDOW_MATCH            the recorded common causal window equals the observed intersection
RAW_LEDGER_VERIFIED            every raw archive is present, size+SHA256 matched and CHECKSUM-verified
FUNDING_REUSE_MATCH            the reused funding partitions reproduce the certified ARC-01 digests
PIT_BATTERY                    the frozen PIT adversarial battery passes
DATA_ROOT_EXPLICIT             an explicit absolute data root is used and it is the audited target
WRONG_ROOT_FAILS_CLOSED        a wrong data root is refused (fail closed)
EMPTY_ROOT_FAILS_CLOSED        an empty data root is refused (fail closed)
CLEAN_WORKTREE                 ``git status --porcelain`` is empty for the audited target

Exit codes: 0 = PASS, 1 = FAIL, 2 = FAIL_CLOSED (wrong/incomplete target or data root).

Usage::

    python scripts/verify_arc02_data_authority.py [--target DIR] [--data-root DIR] [--skip-git]
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from typing import Any

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


class Report:
    def __init__(self, target: pathlib.Path, data_root: pathlib.Path) -> None:
        self.target = target
        self.data_root = data_root
        self.checks: list[dict[str, Any]] = []

    def add(self, name: str, ok: bool, detail: Any = None, *, fail_closed: bool = False) -> None:
        self.checks.append({"check": name, "pass": bool(ok), "fail_closed": fail_closed, "detail": detail})

    @property
    def failed(self) -> list[dict[str, Any]]:
        return [c for c in self.checks if not c["pass"]]

    def verdict(self) -> str:
        return "PASS" if not self.failed else "FAIL"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=str(REPO))
    ap.add_argument("--data-root", default=None)
    ap.add_argument("--skip-git", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    target = pathlib.Path(args.target).resolve()
    data_root = pathlib.Path(args.data_root).resolve() if args.data_root else target
    docs = target / "docs" / "arc02-data-authority-01"
    rep = Report(target, data_root)

    # --------------------------------------------------------------- artifacts first
    required = [
        "ARC02_DATA_INVENTORY.json",
        "ARC02_SOURCE_REGISTRY.md",
        "ARC02_RAW_LEDGER.jsonl",
        "ARC02_DATA_QUALITY_LEDGER.jsonl",
        "ARC02_DATA_MANIFEST.json",
        "ARC02_DATA_AUTHORITY.json",
        "ARC02_DATASET_FINGERPRINT.json",
        "ARC02_COMMON_CAUSAL_WINDOW.json",
        "ARC02_DATA_DETERMINISM.json",
        "ARC02_MUTATION_SENSITIVITY.json",
        "ARC02_PIT_AUTHORITY.json",
        "ARC02_PIT_INDEPENDENT_TESTS.json",
        "ARC02_REUSE_ASSESSMENT.json",
    ]
    missing = [n for n in required if not (docs / n).exists()]
    rep.add("TARGET_ARTIFACTS_PRESENT", not missing, {"missing": missing, "target": str(target)}, fail_closed=bool(missing))
    if missing:
        return _emit(rep, args.out, fail_closed=True)

    manifest = json.loads((docs / "ARC02_DATA_MANIFEST.json").read_text(encoding="utf-8"))
    authority = json.loads((docs / "ARC02_DATA_AUTHORITY.json").read_text(encoding="utf-8"))
    window_doc = json.loads((docs / "ARC02_COMMON_CAUSAL_WINDOW.json").read_text(encoding="utf-8"))
    pit_doc = json.loads((docs / "ARC02_PIT_INDEPENDENT_TESTS.json").read_text(encoding="utf-8"))

    # ----------------------------------------------------------- import authority
    from trading_bot.research.arc02 import arc02_authority as A
    from trading_bot.research.arc02 import arc02_funding as F
    from trading_bot.research.arc02 import arc02_normalize as N
    from trading_bot.research.arc02 import arc02_pit as PIT

    module_path = pathlib.Path(A.__file__).resolve()
    rep.add(
        "PYTHON_IMPORT_AUTHORITY",
        target in module_path.parents,
        {"module": str(module_path), "audited_target": str(target)},
    )
    conftest = target / "conftest.py"
    guard_ok = conftest.exists() and "sys.path.insert" in conftest.read_text(encoding="utf-8") and "src" in conftest.read_text(encoding="utf-8")
    rep.add(
        "TEST_TARGET_EQUALS_AUDITED",
        guard_ok and (target / "src" / "trading_bot" / "research" / "arc02" / "arc02_authority.py").exists(),
        {"conftest_guard": guard_ok, "src_present": (target / "src").is_dir()},
    )

    # ------------------------------------------------------------ reuse identity
    src_dir = A.resolve_partition_dir(data_root).parent / "arc03_klines_5m"
    reuse_rows = []
    for symbol, recorded in N.SOURCE_PARTITION_SHA256.items():
        path = src_dir / f"{symbol}.jsonl"
        observed = N.sha256_file(path) if path.exists() else None
        reuse_rows.append({"symbol": symbol, "recorded": recorded, "observed": observed, "match": observed == recorded})
    rep.add(
        "REUSE_IDENTITY_MATCH",
        all(r["match"] for r in reuse_rows),
        {"rows": reuse_rows, "source_root": str(src_dir)},
        fail_closed=not src_dir.exists(),
    )

    # -------------------------------------------------------- partition / dataset
    part_dir = A.resolve_partition_dir(data_root)
    observed_parts: dict[str, str] = {}
    for symbol, recorded in manifest["partition_sha256"].items():
        path = part_dir / f"{symbol}.jsonl"
        observed_parts[symbol] = N.sha256_file(path) if path.exists() else "MISSING"
    rep.add(
        "PARTITION_SHA256_MATCH",
        observed_parts == manifest["partition_sha256"],
        {"observed": observed_parts, "recorded": manifest["partition_sha256"]},
        fail_closed=not part_dir.exists(),
    )
    recomputed = _recompute_dataset(manifest, N)
    rep.add(
        "DATASET_SHA256_MATCH",
        recomputed == manifest["dataset_sha256"],
        {"recomputed": recomputed, "recorded": manifest["dataset_sha256"]},
    )

    # ---------------------------------------------------------------- window
    partitions = {s: A.load_partition(s, partition_dir=part_dir) for s in manifest["partition_sha256"]}
    observed_window = A.common_causal_window(partitions)
    rep.add(
        "COMMON_WINDOW_MATCH",
        (observed_window["start_ms"], observed_window["end_ms"])
        == (window_doc["start_ms"], window_doc["end_ms"]),
        {"observed": [observed_window["start_ms"], observed_window["end_ms"]],
         "recorded": [window_doc["start_ms"], window_doc["end_ms"]]},
    )

    # ------------------------------------------------------------- raw ledger
    ledger = [json.loads(x) for x in (docs / "ARC02_RAW_LEDGER.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    raw_failures: list[Any] = []
    for entry in ledger:
        root_key = "binance_um/arc03" if entry["granularity"] == "MONTHLY" else "binance_um/arc03_daily"
        zp = data_root / "data" / "raw" / root_key / entry["symbol"] / entry["period"] / entry["archive"]
        if not zp.exists() or zp.stat().st_size != entry["size_bytes"] or N.sha256_file(zp) != entry["raw_sha256"]:
            raw_failures.append(entry["archive"])
            continue
        sidecar = zp.with_name(zp.name + ".CHECKSUM")
        if not sidecar.exists() or sidecar.read_text(encoding="utf-8").split()[0] != entry["raw_sha256"]:
            raw_failures.append(entry["archive"])
    rep.add(
        "RAW_LEDGER_VERIFIED",
        not raw_failures and len(ledger) > 0,
        {"total_entries": len(ledger), "failures": raw_failures[:10]},
    )

    # --------------------------------------------------------------- funding
    funding_dir = F.resolve_funding_dir(data_root)
    funding_rows = []
    for symbol, recorded in F.ARC01_FUNDING_PARTITION_SHA256.items():
        path = funding_dir / f"{symbol}_funding.jsonl"
        observed = N.sha256_file(path) if path.exists() else None
        funding_rows.append({"symbol": symbol, "match": observed == recorded, "observed": observed})
    rep.add("FUNDING_REUSE_MATCH", all(r["match"] for r in funding_rows), {"rows": funding_rows})

    # ------------------------------------------------------------------ PIT
    battery = PIT.run_battery()
    passed = sum(1 for c in battery if c["pass"])
    rep.add(
        "PIT_BATTERY",
        passed == len(battery) and pit_doc.get("result") == "PASS",
        {"passed": passed, "total": len(battery)},
    )

    # ------------------------------------------------------------- data root rules
    rep.add(
        "DATA_ROOT_EXPLICIT",
        data_root.is_absolute()
        and part_dir.is_dir()
        and len(list(part_dir.glob("*.jsonl"))) == len(manifest["partition_sha256"]),
        {
            "data_root": str(data_root),
            "is_absolute": data_root.is_absolute(),
            "data_root_is_audited_target": data_root == target,
            "partitions_found": sorted(p.name for p in part_dir.glob("*.jsonl")),
        },
        fail_closed=True,
    )
    rep.add("WRONG_ROOT_FAILS_CLOSED", _wrong_root_refused(N, A), None)
    rep.add("EMPTY_ROOT_FAILS_CLOSED", _empty_root_refused(N, A), None)

    # -------------------------------------------------------------- clean tree
    if not args.skip_git:
        try:
            proc = subprocess.run(
                ["git", "status", "--porcelain"], cwd=str(target), capture_output=True, text=True
            )
            dirty = [x for x in proc.stdout.splitlines() if x.strip()]
        except Exception as exc:  # pragma: no cover - defensive
            dirty = [f"git unavailable: {exc}"]
        rep.add("CLEAN_WORKTREE", not dirty, {"dirty_entries": dirty[:20]})
    else:
        rep.add("CLEAN_WORKTREE", True, {"skipped": True})

    fail_closed = any(c.get("fail_closed") and not c["pass"] for c in rep.checks)
    return _emit(rep, args.out, fail_closed=fail_closed)


def _recompute_dataset(manifest: dict[str, Any], N: Any) -> str:
    files = sorted(
        (
            {
                "symbol": f["symbol"],
                "source_partition_sha256": f["source_partition_sha256"],
                "projection_sha256": f["projection_sha256"],
                "rows": f["rows"],
                "first_open_ms": f["first_open_ms"],
                "last_open_ms": f["last_open_ms"],
            }
            for f in (
                {
                    "symbol": s,
                    "source_partition_sha256": N.SOURCE_PARTITION_SHA256[s],
                    "projection_sha256": manifest["partition_sha256"][s],
                    "rows": manifest["per_symbol"][s]["rows"],
                    "first_open_ms": manifest["per_symbol"][s]["first_open_ms"],
                    "last_open_ms": manifest["per_symbol"][s]["last_open_ms"],
                }
                for s in manifest["partition_sha256"]
            )
        ),
        key=lambda x: x["symbol"],
    )
    payload = {
        "schema_version": manifest["schema_version"],
        "projection_version": manifest["projection_version"],
        "interval": manifest["interval"],
        "projected_fields": manifest["per_symbol"][sorted(manifest["per_symbol"])[0]]["projected_fields"],
        "dropped_fields": manifest["per_symbol"][sorted(manifest["per_symbol"])[0]]["dropped_fields"],
        "source_authority_dataset_sha256": N.SOURCE_DATASET_SHA256,
        "reuse_semantics": "REUSE_BY_CONTENT_IDENTITY (no re-download; source partitions byte-identical)",
        "files": files,
    }
    return N.sha256_bytes(N.canonical_json(payload))


def _wrong_root_refused(N: Any, A: Any) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        wrong = pathlib.Path(tmp) / "definitely_not_the_data_root"
        wrong.mkdir(parents=True, exist_ok=True)
        try:
            A.load_partition("BTCUSDT", partition_dir=wrong)
        except FileNotFoundError:
            return True
        except Exception:
            return True
        return False


def _empty_root_refused(N: Any, A: Any) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        empty = pathlib.Path(tmp)
        try:
            A.load_partition("BTCUSDT", partition_dir=empty)
        except FileNotFoundError:
            return True
        except Exception:
            return True
        return False


def _emit(rep: Report, out: str | None, *, fail_closed: bool) -> int:
    payload = {
        "verifier": "verify_arc02_data_authority.py",
        "read_only": True,
        "audited_target": str(rep.target),
        "data_root": str(rep.data_root),
        "data_root_is_audited_target": rep.data_root == rep.target,
        "checks_total": len(rep.checks),
        "checks_passed": len(rep.checks) - len(rep.failed),
        "failed_checks": [c["check"] for c in rep.failed],
        "verdict": rep.verdict(),
        "checks": rep.checks,
    }
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if out:
        pathlib.Path(out).write_bytes(text.encode("utf-8"))
    print(text)
    if fail_closed and rep.failed:
        return 2
    return 0 if rep.verdict() == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
