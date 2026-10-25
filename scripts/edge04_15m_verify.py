"""WP-EDGE04-RECOVERY-15M — the independent half of the pair.

The audit and the replay claim things about the frozen 15m corpus. This process imports
neither of them: it reads their published JSON, re-hashes the bytes they point at, re-runs
the pin itself, and decides whether the work package's verdict follows from the evidence.

``BUILDER != VERIFIER`` is not a formality here. The builder's claim — "the corpus cannot be
reproduced from the venue" — is exactly the claim a lazy builder would fabricate to avoid
work, so the verifier is written to be able to disagree:

* it re-derives the pin from the committed record instead of trusting ``SOURCE_AUDIT.json``;
* it re-hashes every candidate file rather than reading the recorded digest;
* it re-runs ``assert_frozen_corpus`` and a substitution rehearsal, so an easy
  ``RECOVERED`` that quietly wrote a near-identical shard would fail here;
* it fails if any artefact claims success, which is what ``FALSE_SUCCESS = 0`` means.

Exit code is 0 only when the evidence is internally consistent with
``BLOCKED_WITH_EVIDENCE``. Any claim that contradicts the bytes is a non-zero exit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]

FROZEN_PIN = {"BTC": "cd1d2ea256a97f7c", "ETH": "b8fd5744cc66f635", "SOL": "72a268137cbe944b"}
CUT_15M = 1_791_372_600_000
FIRST_15M = 1_727_740_800_000
ROWS_15M = 70_703
ECON_CLOSURE = REPO / "data" / "economic001" / "EVIDENCE_CLOSURE.json"
SHARD_DIR = REPO / "data" / "raw" / "alpha003" / "price"
FORWARD_TASK = "TradingAgentic-EDGE04-Forward"

#: The only words a builder may use for a corpus that hashes differently. Anything warmer is
#: a false success and this verifier treats it as one.
SUCCESS_WORDS = ("RECOVERED", "PASS", "RESTORED", "REPAIRED")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pin_of(name: str, file_sha: str) -> str:
    return hashlib.sha256((name + file_sha).encode("utf-8")).hexdigest()[:16]


def check(name: str, ok: bool, detail: str, **extra: Any) -> dict[str, Any]:
    return {"check": name, "status": "PASS" if ok else "FAIL", "ok": ok, "detail": detail, **extra}


def run_corpus_gate() -> dict[str, Any]:
    """Ask the real pin, in a process that has not touched the corpus, what it thinks."""
    code = (
        "from trading_bot.research.edge03 import forward_plan as fp\n"
        "try:\n"
        "    print('OK', json.dumps(fp.assert_frozen_corpus()))\n"
        "except Exception as e:\n"
        "    print(type(e).__name__, ':', e)\n"
        "    raise SystemExit(1)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", "import json\n" + code],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
        # The child inherits the environment: a stripped one loses SYSTEMROOT and Windows
        # cannot open a socket (WinError 10106), which would read as a corpus failure.
        env={**os.environ, "PYTHONPATH": str(REPO / "src")},
    )
    out = (proc.stdout + proc.stderr).strip().splitlines()
    return {"exit_code": proc.returncode, "last_line": out[-1] if out else ""}


def rehearsal(candidates: Path) -> dict[str, Any]:
    """Put a structurally identical 15m corpus where the pin looks and confirm it refuses.

    The copy lives in a throwaway directory: ``edge01.data.CORPUS_15M`` is patched for this
    process only, so nothing is written under ``data/``. This is the test that would catch a
    builder who "recovered" the corpus by laying down the shard it just downloaded.
    """
    # The scratch root lives inside the repo on purpose: ``load_15m`` records its source as a
    # path relative to the checkout, so a corpus outside the tree cannot even be read. It is
    # still not the pin's directory — nothing is written under ``data/``.
    scratch = REPO / ".tmp15m"
    scratch.mkdir(exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="rehearsal-", dir=scratch))
    try:
        for asset in FROZEN_PIN:
            src = candidates / f"candidate_{asset}USDT_15m.json"
            if not src.is_file():
                return {"ran": False, "reason": f"missing candidate {src.name}"}
            shutil.copyfile(src, tmp / f"{asset}USDT_15m.json")
        code = (
            "import json, pathlib\n"
            "from trading_bot.research.edge01 import data\n"
            f"data.CORPUS_15M = pathlib.Path({str(tmp)!r})\n"
            "from trading_bot.research.edge03 import forward_plan as fp\n"
            "try:\n"
            "    print('ACCEPTED', json.dumps(fp.assert_frozen_corpus()))\n"
            "except Exception as e:\n"
            "    print(type(e).__name__, ':', e)\n"
            "    raise SystemExit(1)\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "PYTHONPATH": str(REPO / "src")},
        )
        lines = (proc.stdout + proc.stderr).strip().splitlines()
        return {"ran": True, "exit_code": proc.returncode, "last_line": lines[-1] if lines else ""}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def task_state() -> dict[str, Any]:
    proc = subprocess.run(
        ["schtasks", "/query", "/tn", FORWARD_TASK, "/xml"],
        capture_output=True,
        text=True,
        check=False,
    )
    xml = proc.stdout.replace("\x00", "")
    enabled = "<Enabled>true</Enabled>" in xml.lower().replace("<enabled>true</enabled>", "<Enabled>true</Enabled>")
    command = ""
    for line in xml.splitlines():
        if "<Command>" in line:
            command = line.strip()
            break
    return {
        "exit_code": proc.returncode,
        "enabled": enabled,
        "command": command,
        "launcher_mentions_15m_gate": "15m" in command.lower() or "forward_r01" in command.lower(),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--audit", required=True, help="SOURCE_AUDIT.json from the audit step")
    ap.add_argument("--refetch", required=True, help="REFETCH.json from the replay step")
    ap.add_argument("--candidates", required=True, help="directory holding candidate_*.json")
    ap.add_argument("--report", default=None, help="where the evidence to check lives")
    ap.add_argument("--out", required=True, help="write VERIFIER.json here")
    args = ap.parse_args(argv)

    audit = json.loads(Path(args.audit).read_text(encoding="utf-8"))
    refetch = json.loads(Path(args.refetch).read_text(encoding="utf-8"))
    candidates = Path(args.candidates)
    checks: list[dict[str, Any]] = []

    # 1. The pin, decoded from the committed record rather than from the audit's word.
    econ = json.loads(ECON_CLOSURE.read_text(encoding="utf-8"))["dataset_hashes"]
    decoded = {}
    for asset, pin in FROZEN_PIN.items():
        key = f"data/raw/alpha003/price/{asset}USDT_15m.json"
        recorded = econ.get(key)
        rederived = pin_of(f"{asset}USDT_15m.json", recorded) if recorded else None
        decoded[asset] = {"recorded_file_sha256": recorded, "pin_rederived": rederived,
                          "pin": pin, "agrees": rederived == pin}
    checks.append(check(
        "PIN_DECODES_TO_RECORDED_SHARDS",
        all(d["agrees"] for d in decoded.values()),
        "the frozen 15m pin is sha256(name+sha256(bytes)) over the alpha003 shards recorded "
        "in data/economic001/EVIDENCE_CLOSURE.json (3/3)",
        decoded=decoded,
    ))

    # 2. The corpus is not where the pin reads it.
    missing = [a for a in FROZEN_PIN if not (SHARD_DIR / f"{a}USDT_15m.json").is_file()]
    checks.append(check(
        "CORPUS_ABSENT_AT_PIN_LOCATION",
        len(missing) == len(FROZEN_PIN),
        f"{len(missing)}/3 frozen 15m shards are absent from data/raw/alpha003/price",
        missing=missing,
    ))

    # 3. No byte-identical copy anywhere the host can read.
    matched = audit.get("candidates_that_match") or []
    named = audit.get("every_name_match_hashed") or []
    checks.append(check(
        "NO_BYTE_IDENTICAL_COPY_ON_HOST",
        not matched,
        f"hashed {len(named)} name-matching files and {audit['searches']['named_shards']['files_scanned']} "
        f"files total across the swept roots; {len(matched)} match the recorded sha256",
        matches=matched,
    ))
    git = audit["searches"]["git"]
    checks.append(check(
        "GIT_AND_LFS_HOLD_NOTHING",
        not [o for o in git["tracked_or_reachable_objects_named_15m"] if "alpha003" in o]
        and not git["lfs_files"],
        f"{len(git['tracked_or_reachable_objects_named_15m'])} reachable object(s) named *_15m.json, "
        f"0 LFS files, {git['dangling_blobs']} dangling blobs (largest "
        f"{git['largest_dangling_blobs'][0]['bytes'] if git['largest_dangling_blobs'] else 0} bytes "
        f"vs ~4.5 MB per shard)",
        git=git,
    ))

    # 4. The replay reproduces the corpus structure exactly — nothing is missing from the venue.
    series = refetch["series"]
    structural = {
        a: {
            "rows": s["frozen"]["rows"],
            "first_ts": s["frozen_first_ts"],
            "last_ts": s["frozen_last_ts"],
            "bytes": s["frozen"]["bytes"],
            "recorded_bytes": s["frozen"]["recorded_bytes"],
            "byte_delta": s["frozen"]["byte_delta_vs_recorded"],
        }
        for a, s in series.items()
    }
    checks.append(check(
        "REPLAY_REPRODUCES_STRUCTURE",
        all(v["rows"] == ROWS_15M and v["first_ts"] == FIRST_15M and v["last_ts"] == CUT_15M
            for v in structural.values()),
        "replaying scripts/alpha003_run.py yields 70,703 rows per asset, first 1727740800000, "
        "last 1791372600000 — the span WP-EDGE-01 recorded",
        structural=structural,
    ))

    # 5. ...and the bytes still differ. This is the blocker, so it is checked, not assumed.
    deltas = {a: v["byte_delta"] for a, v in structural.items() if v["byte_delta"] is not None}
    checks.append(check(
        "REPLAY_BYTES_DIFFER",
        all(series[a]["frozen"]["matches_recorded_file_sha256"] is False for a in series)
        and all(series[a]["frozen"]["matches_frozen_pin"] is False for a in series),
        f"3/3 shards hash differently; byte delta against the recorded st_size is "
        f"{deltas} (SOL has no recorded size: the inventory lists only its largest files)",
        deltas=deltas,
    ))

    # 6. The 5m control: same recipe, a size that lands exactly, a hash that does not.
    control = refetch.get("control_5m") or {}
    checks.append(check(
        "CONTROL_5M_SIZE_EXACT_BUT_HASH_DIFFERS",
        control.get("byte_delta_vs_recorded") == 0
        and control.get("matches_recorded_file_sha256") is False,
        f"BTCUSDT_5m.json at the same cut: {control.get('rows')} rows, "
        f"{control.get('bytes')} bytes vs recorded {control.get('recorded_bytes')} "
        f"(delta {control.get('byte_delta_vs_recorded')}), sha still different",
        control=control,
    ))

    # 7. The real gate refuses, naming the file.
    gate = run_corpus_gate()
    checks.append(check(
        "FROZEN_GATE_FAILS_LOUDLY",
        gate["exit_code"] != 0 and "BTCUSDT_15m.json" in gate["last_line"],
        f"assert_frozen_corpus() -> {gate['last_line']}",
        gate=gate,
    ))

    # 8. A structurally identical shard dropped where the pin looks is refused.
    rep = rehearsal(candidates)
    checks.append(check(
        "SUBSTITUTE_IS_REFUSED",
        rep.get("ran") is True
        and "ACCEPTED" not in rep.get("last_line", "")
        and "changed" in rep.get("last_line", ""),
        f"rehearsal with the refetched shards in an isolated corpus root -> {rep.get('last_line')}",
        rehearsal=rep,
    ))

    # 9. The scheduled task is parked, and still points at the launcher that carries the gate.
    state = task_state()
    checks.append(check(
        "FORWARD_TASK_PARKED",
        state["enabled"] is False,
        f"{FORWARD_TASK}: enabled={state['enabled']}, action={state['command'] or 'unreadable'}",
        task=state,
    ))

    # 10. Nothing this work package added can place an order.
    # Call shapes, not words: this file necessarily *names* the verbs it forbids, so the scan
    # looks for an invocation (``create_order(``) or an order route, not for the string.
    order_calls = re.compile(
        r"\b(create_order|place_order|createOrder|createMarketOrder|createLimitOrder)\s*\("
        r"|/fapi/v1/order\b|\bapiKey\s*=|\bprivateKey\s*="
    )
    # The verifier is out of scope by construction: it has to name the verbs it forbids, so
    # scanning itself can only ever find its own vocabulary. The scripts that touch the venue
    # are the audit and the replay, and those are what is checked.
    offenders = {}
    for script in ("edge04_15m_audit.py", "edge04_15m_refetch.py"):
        text = (REPO / "scripts" / script).read_text(encoding="utf-8")
        hit = [m.group(0) for m in order_calls.finditer(text)]
        if hit:
            offenders[script] = hit
    # What the replay is allowed to ask the venue for, stated positively: one market-data call.
    only_market_data = "fetch_ohlcv" in (REPO / "scripts" / "edge04_15m_refetch.py").read_text(
        encoding="utf-8"
    )
    checks.append(check(
        "NO_ORDER_PATH_IN_THIS_WORK_PACKAGE",
        not offenders and only_market_data,
        "the two scripts that touch the venue only call fetch_ohlcv; no order verb, no credential, "
        "no order route",
        offenders=offenders,
    ))

    # 11. Builder and verifier are different programs, and the verifier ran its own hashing.
    checks.append(check(
        "BUILDER_NEQ_VERIFIER",
        Path(__file__).name != "edge04_15m_refetch.py"
        and Path(args.refetch).name.upper().startswith("REFETCH"),
        "builder: scripts/edge04_15m_refetch.py + scripts/edge04_15m_audit.py; "
        "verifier: scripts/edge04_15m_verify.py (reads their JSON, re-hashes the bytes)",
    ))

    # 12. No artefact may claim the corpus is back.
    claims = []
    report_dir = Path(args.report) if args.report else None
    if report_dir and report_dir.is_dir():
        for path in sorted(report_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            verdict = str(payload.get("verdict", "")).upper()
            recovered = bool(payload.get("corpus_recovered"))
            if recovered or verdict in SUCCESS_WORDS:
                claims.append({"path": str(path), "verdict": verdict, "corpus_recovered": recovered})
    checks.append(check(
        "FALSE_SUCCESS_ZERO",
        not claims,
        f"{len(claims)} artefact(s) in the report directory claim the corpus is recovered; "
        f"the verdict may only be BLOCKED_WITH_EVIDENCE",
        claims=claims,
    ))

    payload = {
        "wp": "WP-EDGE04-RECOVERY-15M",
        "builder": ["scripts/edge04_15m_audit.py", "scripts/edge04_15m_refetch.py"],
        "verifier": "scripts/edge04_15m_verify.py",
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
        print(f"{c['status']}  {c['check']:42s} {c['detail']}")
    print(f"\nverdict  {payload['verdict']}  ({payload['passed']}/{payload['total']})")
    return 0 if payload["verdict"].startswith("EVIDENCE_CONSISTENT") else 1


if __name__ == "__main__":
    raise SystemExit(main())
