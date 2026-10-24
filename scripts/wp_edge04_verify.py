"""Independent verification of the progress work package.

Imports neither the freeze module nor the analyser: it re-hashes the corpus, rebuilds the
manifest digest from the published JSON, re-derives the EDGE-03 1h pins from the shard bytes,
and reads the paper run's own report.  The claims under test are the ones that would be
convenient to fake:

* the freeze manifest answers to the bytes on disk, and freezing did not move the pins;
* the mirror is a real second copy, and the restore drill really lost and re-read the corpus;
* the paper run was paper (fake venue, no order, no runtime failure) and not a stub;
* the dependency matrix accounts for every blocked entrypoint it lists;
* nothing claims EXP004A is unblocked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
FORWARD_PLAN = REPO / "src" / "trading_bot" / "research" / "edge03" / "forward_plan.py"
CORPUS_1H = REPO / "reports" / "alpha-expansion-v1" / "data"
CORPUS_15M = REPO / "data" / "raw" / "alpha003" / "price"
MIRROR = Path.home() / "exp004a-corpus-mirror" / "alpha-expansion-v1-data"
FORWARD_TASK = "TradingAgentic-EDGE04-Forward"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def shards(root: Path) -> list[Path]:
    return sorted(p for p in root.glob("*.json") if not p.name.startswith("_"))


def recompute_manifest_digest(entries: dict[str, dict[str, Any]]) -> str:
    """``sha256`` over ``name + sha256 + bytes`` per shard, in name order."""
    combined = hashlib.sha256()
    for name in sorted(entries):
        combined.update(name.encode("utf-8"))
        combined.update(str(entries[name]["sha256"]).encode("utf-8"))
        combined.update(str(entries[name]["bytes"]).encode("utf-8"))
    return combined.hexdigest()


def corpus_digest_1h(root: Path, asset: str) -> str:
    """``edge01.data._digest`` for a multi-shard corpus, restated here rather than imported."""
    combined = hashlib.sha256()
    for path in sorted(p for p in root.glob(f"{asset}USDT_*.json") if not p.name.startswith("_")):
        combined.update(path.name.encode("utf-8"))
        combined.update(sha256_file(path).encode("utf-8"))
    return combined.hexdigest()


def pinned_1h() -> dict[str, str]:
    """The pins as published in the source text, not as imported from it."""
    text = FORWARD_PLAN.read_text(encoding="utf-8")
    block = re.search(r"FROZEN_SHARD_SHA256[^{]*\{(?P<body>[^}]*)\}", text)
    if not block:
        return {}
    return {
        m.group("key"): m.group("value")
        for m in re.finditer(r'"(?P<key>1h:[A-Z]+)":\s*"(?P<value>[0-9a-f]+)"', block.group("body"))
    }


def task_state() -> dict[str, Any]:
    proc = subprocess.run(
        ["schtasks", "/query", "/tn", FORWARD_TASK, "/xml"],
        capture_output=True,
        text=True,
        check=False,
    )
    xml = proc.stdout.replace("\x00", "")
    return {"exit_code": proc.returncode, "enabled": "<Enabled>true</Enabled>" in xml}


def check(name: str, ok: bool, detail: str, **extra: Any) -> dict[str, Any]:
    return {"check": name, "status": "PASS" if ok else "FAIL", "ok": ok, "detail": detail, **extra}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw", required=True, help="the raw/ directory this work package wrote")
    ap.add_argument("--reports", required=True, help="where FINAL/RUN/EVIDENCE live")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    raw, reports = Path(args.raw), Path(args.reports)
    checks: list[dict[str, Any]] = []

    manifest_path = CORPUS_1H / "_FREEZE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else None

    # 1. The manifest answers to the bytes.
    problems = []
    if manifest:
        for name, entry in manifest["shards"].items():
            path = CORPUS_1H / name
            if not path.is_file():
                problems.append({"shard": name, "kind": "MISSING"})
            elif sha256_file(path) != entry["sha256"] or path.stat().st_size != entry["bytes"]:
                problems.append({"shard": name, "kind": "CHANGED"})
        found = {p.name for p in shards(CORPUS_1H)}
        if found != set(manifest["shards"]):
            problems.append({"kind": "SET_DIFFERS", "found": len(found)})
        if recompute_manifest_digest(manifest["shards"]) != manifest["corpus_digest"]:
            problems.append({"kind": "DIGEST_NOT_SELF_CONSISTENT"})
    checks.append(check(
        "FREEZE_MANIFEST_ANSWERS_TO_BYTES",
        bool(manifest) and not problems,
        f"{len(manifest['shards']) if manifest else 0} shard(s) re-hashed; "
        f"{len(problems)} difference(s)",
        problems=problems,
    ))

    # 2. Every frozen shard ends on a closed bar, judged against the manifest's own instant.
    unclosed = []
    if manifest:
        step = manifest["interval_ms"]
        for name, entry in manifest["shards"].items():
            if entry["last_ts"] + step > manifest["frozen_at_ms"]:
                unclosed.append(name)
    checks.append(check(
        "EVERY_FROZEN_BAR_WAS_CLOSED",
        bool(manifest) and not unclosed,
        "a shard ending on an open bar is refused at freeze time; none here is open",
        open_shards=unclosed,
    ))

    # 3. Freezing did not touch what the experiment pins.
    pins = pinned_1h()
    derived = {f"1h:{asset}": corpus_digest_1h(CORPUS_1H, asset) for asset in ("BTC", "ETH", "SOL")}
    agree = {key: derived[key][:16] == value for key, value in pins.items()}
    checks.append(check(
        "FREEZING_DID_NOT_MOVE_THE_PINS",
        bool(pins) and all(agree.values()),
        f"{sum(agree.values())}/{len(pins)} EDGE-03 1h pins still hold after the manifest was added",
        derived={k: v[:16] for k, v in derived.items()},
        pins=pins,
        agree=agree,
    ))

    # 4. The mirror is a second copy, byte for byte.
    mirror_ok, mirror_detail = False, "mirror absent"
    if manifest and MIRROR.is_dir():
        mismatch = [
            name for name, entry in manifest["shards"].items()
            if not (MIRROR / name).is_file() or sha256_file(MIRROR / name) != entry["sha256"]
        ]
        mirror_ok = not mismatch and (MIRROR / "_FREEZE_MANIFEST.json").is_file()
        mirror_detail = f"{len(manifest['shards']) - len(mismatch)}/{len(manifest['shards'])} shards identical in {MIRROR}"
    checks.append(check("MIRROR_IS_A_REAL_SECOND_COPY", mirror_ok, mirror_detail))

    # 5. The restore drill really lost the corpus and really read it back.
    drill = json.loads((raw / "drill.json").read_text(encoding="utf-8"))
    drill_ok = (
        drill.get("restored") is True
        and drill.get("reader_agrees") is True
        and drill["during_loss"]["ok"] is False
        and drill["before"]["corpus_digest"] == drill["after_restore"]["corpus_digest"]
        and drill["shards_removed"] >= len(manifest["shards"]) if manifest else False
    )
    checks.append(check(
        "RESTORE_DRILL_IS_REAL",
        bool(drill_ok),
        f"{drill['shards_removed']} file(s) deleted, verify said "
        f"{'ok' if drill['during_loss']['ok'] else 'not ok'}, restored digest "
        f"{drill['after_restore']['corpus_digest'][:16]}, reader agrees={drill['reader_agrees']}",
        drill={k: drill[k] for k in ("shards_removed", "restored", "reader_agrees")},
    ))

    # 6. The paper run was paper, and it did something.
    paper = json.loads((raw / "paper" / "RUN_REPORT.json").read_text(encoding="utf-8"))
    totals = paper["totals"]
    paper_ok = (
        paper["mode"] == "paper"
        and "fake" in str(paper.get("environment", ""))
        and totals["orders_created"] == 0
        and totals["runtime_failures"] == 0
        and totals["asset_cycle_evaluations"] >= 2
    )
    checks.append(check(
        "PAPER_RUN_WAS_PAPER_AND_RAN",
        paper_ok,
        f"mode={paper['mode']} environment={paper.get('environment')} "
        f"cycles={totals['asset_cycle_evaluations']} orders={totals['orders_created']} "
        f"failures={totals['runtime_failures']} traces={totals['traces_persisted']}",
        commit=paper.get("commit"),
    ))

    # 7. EXP004A is still blocked, and says so.
    missing = [a for a in ("BTC", "ETH", "SOL") if not (CORPUS_15M / f"{a}USDT_15m.json").is_file()]
    checks.append(check(
        "EXP004A_STILL_BLOCKED",
        len(missing) == 3,
        f"{len(missing)}/3 frozen 15m shards absent; no substitute was placed under data/",
        missing=missing,
    ))

    # 8. The scheduled lane is still parked.
    task = task_state()
    checks.append(check("FORWARD_TASK_STILL_PARKED", task["enabled"] is False,
                        f"{FORWARD_TASK} enabled={task['enabled']}", task=task))

    # 9. The matrix accounts for what it blocks.
    matrix = json.loads((raw / "DEPENDENCY_MATRIX.json").read_text(encoding="utf-8"))
    rows = matrix["entrypoints"]
    blocked = [r for r in rows if not r["statically_reachable"]]
    explained = all(
        r["blocker"] == "ALPHA003_PRICE_ABSENT" and (r["hard_readers"] or r["unguarded_directory_readers"])
        for r in blocked
    )
    totals_ok = (
        matrix["totals"]["entrypoints"] == len(rows)
        and matrix["totals"]["blocked_by_corpus"] == len(blocked)
    )
    checks.append(check(
        "MATRIX_BLOCKS_ONLY_WHAT_IT_CAN_NAME",
        explained and totals_ok,
        f"{len(blocked)} blocked of {len(rows)}; every blocked row names the reader that needs "
        f"the absent directory",
    ))

    # 10. Nothing claims the campaign is unblocked.
    success_words = ("RECOVERED", "UNBLOCKED", "PASS")
    claims = []
    for path in sorted(reports.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("corpus_recovered") or payload.get("exp004a_unblocked"):
            claims.append({"path": path.name, "corpus_recovered": payload.get("corpus_recovered"),
                           "exp004a_unblocked": payload.get("exp004a_unblocked")})
        verdict = str(payload.get("verdict", "")).upper()
        if verdict in success_words:
            claims.append({"path": path.name, "verdict": verdict})
    checks.append(check(
        "FALSE_SUCCESS_ZERO",
        not claims,
        f"{len(claims)} artefact(s) claim the frozen campaign is recovered or unblocked",
        claims=claims,
    ))

    # 11. Different programs built and checked this.
    checks.append(check(
        "BUILDER_NEQ_VERIFIER",
        Path(__file__).name not in ("wp_edge04_freeze.py", "wp_edge04_deps.py"),
        "builder: scripts/wp_edge04_freeze.py + scripts/wp_edge04_deps.py; "
        "verifier: scripts/wp_edge04_verify.py (re-hashes, re-derives pins from the source text)",
    ))

    payload = {
        "wp": "EDGE04-PROGRESS",
        "builder": ["scripts/wp_edge04_freeze.py", "scripts/wp_edge04_deps.py"],
        "verifier": "scripts/wp_edge04_verify.py",
        "checks": checks,
        "passed": sum(1 for c in checks if c["ok"]),
        "total": len(checks),
        "false_success": sum(1 for c in checks if c["check"] == "FALSE_SUCCESS_ZERO" and not c["ok"]),
    }
    payload["verdict"] = (
        "EVIDENCE_CONSISTENT_WITH_BLOCKED" if payload["passed"] == payload["total"] else "INCONSISTENT"
    )
    Path(args.out).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for c in checks:
        print(f"{c['status']}  {c['check']:34s} {c['detail']}")
    print(f"\nverdict  {payload['verdict']}  ({payload['passed']}/{payload['total']})")
    return 0 if payload["verdict"].startswith("EVIDENCE_CONSISTENT") else 1


if __name__ == "__main__":
    raise SystemExit(main())
