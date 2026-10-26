"""Independent verification of RFC-TAP-CI-003's deliverables.

This tool is deliberately separate from the producers it judges:

* it does not import `cost_barrier_gate`, `cost_barrier_verify` or
  `active_economic_audit`; it runs them as subprocesses and reads their records;
* it re-derives the audit's identity and the certification fingerprint from the
  published bytes instead of asking the tools that wrote them what they mean;
* it fetches the GitHub Actions runs for the tested commit, so "the workflows
  are green" is a statement about the runner and not about a local belief;
* it refuses to call itself PASS when a check is BLOCKED (for example, no
  network), and it exercises four negative controls: a check that cannot fail
  is not a check.

Usage::

    uv run python reports/ai-bots/TAP-CI-REPRO-003/tools/verify_report.py

Exit codes: 0 PASS, 1 FAIL, 3 BLOCKED.
"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

REPORT = Path(__file__).resolve().parents[1]
ROOT = REPORT.parents[2]

MANIFEST = REPORT / "EVIDENCE_MANIFEST.json"
RESULTS = REPORT / "TEST_RESULTS.json"
CERTIFICATION = ROOT / "data/recovery/wp7/COST_BARRIER_CERTIFICATION.json"
AUDIT = ROOT / "data/recovery/ACTIVE_ECONOMIC_AUDIT.json"
AUDIT_MD = ROOT / "data/recovery/ACTIVE_ECONOMIC_AUDIT.md"
EXPLORER = ROOT / "data/recovery/COST_BARRIER_EXPLORER.json"
REHEARSAL = ROOT / "data/recovery/wp8/CLEAN_CHECKOUT_REHEARSAL_REPORT.json"
OUT = REPORT / "INDEPENDENT_VERIFICATION.json"

BASELINE = "a83ac16532f2a8b5ea131b25910d4b57abf9fe0e"
TESTED = "63950a7295d7659fffe894e49d6fa5624d1280a2"

VOLATILE = ("generated_at_utc", "payload_sha256", "head", "branch", "sources",
            "local_observations")
PROVENANCE_ONLY = ("artifact", "work_package", "generated_at_utc", "head", "branch",
                   "mode", "method", "sources", "input_authority", "local_observations",
                   "entrypoints", "scope")

SAFE_SCOPE = (
    "config",
    "src/trading_bot/risk",
    "docs/COST_MODEL_V3.json",
    "src/trading_bot/research/microstructure/cost_model_v3.py",
    ".github/workflows/ci.yml",
    ".github/workflows/integration-gate.yml",
)

EVIDENCE_MUST_FAIL = (
    ("certification fingerprint", "5a79ebe30355e469085081fcdf9ed259481bdbd556cfe0d878c5805dc62b7aa8"),
    ("gate status", "FULL_REPRODUCTION_PASS"),
    ("rehearsal status", "PASS"),
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def git(*args: str) -> str:
    # Decode as UTF-8 explicitly: the default text mode uses the Windows locale, which
    # turns an em dash into mojibake and makes two identical audits look different.
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.decode("utf-8", errors="replace").strip())
    return out.stdout.decode("utf-8").strip()


def record(checks: list[dict[str, Any]], ident: str, name: str, ok: bool,
           detail: str, blocked: bool = False) -> None:
    checks.append({
        "id": ident,
        "check": name,
        "result": "BLOCKED" if blocked else ("PASS" if ok else "FAIL"),
        "detail": detail,
    })


# --------------------------------------------------------------------------- #
# checks
# --------------------------------------------------------------------------- #


def manifest_problems(manifest: dict[str, Any], root: Path) -> list[str]:
    problems: list[str] = []
    rows = [row for group in manifest.get("groups", {}).values() for row in group]
    if not rows:
        return ["the manifest lists no files"]
    for row in rows:
        path = root / row["path"]
        if not path.exists():
            problems.append(f"{row['path']} is absent")
            continue
        data = path.read_bytes()
        if sha256(data) != row["sha256"]:
            problems.append(f"{row['path']} changed (raw digest)")
        if sha256(data.replace(b"\r\n", b"\n")) != row["sha256_lf"]:
            problems.append(f"{row['path']} changed (LF-normalised digest)")
        if len(data) != row["bytes"]:
            problems.append(f"{row['path']} changed length")
    return problems


def certification_problems(record_doc: dict[str, Any], root: Path) -> list[str]:
    problems: list[str] = []
    if record_doc.get("status") != "CERTIFIED":
        problems.append(f"status is {record_doc.get('status')!r}")
    if record_doc.get("candidate", {}).get("dirty_watched_paths"):
        problems.append("the record was produced on a dirty tree")
    fingerprint = sha256(json.dumps(
        {"head": record_doc.get("candidate", {}).get("head"),
         "digests": record_doc.get("evidence_digests")},
        sort_keys=True,
    ).encode("utf-8"))
    if fingerprint != record_doc.get("evidence_fingerprint"):
        problems.append("evidence_fingerprint does not recompute from head+digests")
    for rel, digest in (record_doc.get("evidence_digests") or {}).items():
        path = root / rel
        if not path.exists():
            problems.append(f"{rel} is absent")
            continue
        if sha256(path.read_bytes().replace(b"\r\n", b"\n")) != digest:
            problems.append(f"{rel} no longer matches the certified digest")
    decision = record_doc.get("decision") or {}
    if decision.get("authorizes_promotion") is not False or decision.get("authorizes_live_trading") is not False:
        problems.append("the record authorizes something it must not")
    if (record_doc.get("claims") or {}).get("false_success") != 0:
        problems.append("claims.false_success is not 0")
    if record_doc.get("adversarial_summary", {}).get("attacks_evaded") != 0:
        problems.append("an adversarial attack escaped")
    return problems


def audit_identity(payload: dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k not in VOLATILE}
    return sha256(json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8"))


def audit_problems(payload: dict[str, Any], explorer: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    identity = audit_identity(payload)
    if payload.get("payload_sha256") != identity:
        problems.append("payload_sha256 does not recompute from the published body")
    pinned = next((row.get("state_sha256") for row in explorer.get("sources") or []
                   if row.get("path") == "data/recovery/ACTIVE_ECONOMIC_AUDIT.json"), None)
    if pinned != identity:
        problems.append("the explorer's state pin for the audit is not this identity")
    if (payload.get("checks_failed") or 0) != 0:
        problems.append("the published audit carries failed checks")
    return problems


def findings(payload: dict[str, Any]) -> dict[str, Any]:
    excluded = set(VOLATILE) | set(PROVENANCE_ONLY)
    return {k: v for k, v in payload.items() if k not in excluded}


def scope_problems() -> list[str]:
    changed = git("diff", "--name-only", f"{BASELINE}..{TESTED}", "--", *SAFE_SCOPE)
    return [f"risk/admission scope changed: {changed}"] if changed else []


def economics_problems() -> list[str]:
    baseline = json.loads(git("show", f"{BASELINE}:data/recovery/ACTIVE_ECONOMIC_AUDIT.json"))
    current = read_json(AUDIT)
    problems = []
    if findings(baseline) != findings(current):
        moved = sorted(k for k in set(findings(baseline)) | set(findings(current))
                       if findings(baseline).get(k) != findings(current).get(k))
        problems.append(f"economic findings changed vs the baseline: {moved}")
    if baseline.get("aggregates") != current.get("aggregates"):
        problems.append("aggregates changed vs the baseline")
    return problems


def claims_problems(results: dict[str, Any], gate_report: dict[str, Any],
                    evidence_bundle: dict[str, Any], certification: dict[str, Any],
                    rehearsal: dict[str, Any], audit_check: dict[str, Any]) -> list[str]:
    problems: list[str] = []

    def by_script(name: str) -> dict[str, Any]:
        return next((row for row in results.get("local", [])
                     if f"scripts/{name}.py" in row["command"]), {})

    gate_row = by_script("cost_barrier_gate")
    if gate_row.get("status") != gate_report.get("status"):
        problems.append("TEST_RESULTS gate status contradicts the gate report")
    if gate_row.get("checks_total") != gate_report.get("checks_total"):
        problems.append("TEST_RESULTS gate check count contradicts the gate report")
    evidence_row = by_script("cost_barrier_evidence")
    if evidence_row.get("status") != evidence_bundle.get("status"):
        problems.append("TEST_RESULTS evidence status contradicts the evidence bundle")
    cert_row = by_script("cost_barrier_certify")
    if cert_row.get("evidence_fingerprint") != certification.get("evidence_fingerprint"):
        problems.append("TEST_RESULTS certification fingerprint contradicts the record")
    replay_row = by_script("clean_checkout_rehearsal")
    if replay_row.get("status") != rehearsal.get("status"):
        problems.append("TEST_RESULTS rehearsal status contradicts the report")
    audit_row = by_script("active_economic_audit")
    if audit_row.get("result") != audit_check.get("result"):
        problems.append("TEST_RESULTS audit check contradicts the captured check")
    if results.get("false_success") != 0:
        problems.append("TEST_RESULTS declares false_success != 0")
    if results.get("tested_commit") != TESTED:
        problems.append("TEST_RESULTS names a different tested commit")
    return problems


def ci_problems() -> tuple[list[str], list[dict[str, Any]], bool]:
    url = ("https://api.github.com/repos/Extr3sao/bot_crypto/actions/runs"
           f"?head_sha={TESTED}&per_page=50")
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return [f"GitHub API unavailable: {exc}"], [], True
    runs = payload.get("workflow_runs") or []
    wanted = {"Cost-barrier drift gate": "success", "recovery-determinism": "success"}
    problems: list[str] = []
    found: list[dict[str, Any]] = []
    for name, expected in wanted.items():
        matches = [row for row in runs if row.get("name") == name]
        if not matches:
            problems.append(f"no {name} run on {TESTED}")
            continue
        run = matches[0]
        found.append({"workflow": name, "id": run["id"], "status": run["status"],
                      "conclusion": run["conclusion"], "url": run["html_url"]})
        if run.get("conclusion") != expected:
            problems.append(f"{name} is {run.get('conclusion')!r}, expected {expected!r}")
    return problems, found, False


def audit_check_subprocess() -> tuple[dict[str, Any] | None, str, bool]:
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns)
              for path in (AUDIT, AUDIT_MD)}
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts/active_economic_audit.py"), "--check"],
        cwd=ROOT, capture_output=True, text=True, timeout=300,
    )
    after = {path: (path.read_bytes(), path.stat().st_mtime_ns)
             for path in (AUDIT, AUDIT_MD)}
    if before != after:
        return None, f"--check modified {[str(p) for p in before if before[p] != after[p]]}", False
    try:
        payload = json.loads(out.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        return None, f"--check produced no readable verdict: {exc}", False
    return payload, f"exit {out.returncode}: {payload.get('result')} ({payload.get('classification')})", out.returncode == 0


def gate_rerun() -> tuple[dict[str, Any] | None, str, bool]:
    target = ROOT / "reports/strategy-baseline/COST_BARRIER.json"
    if not target.exists():
        subprocess.run([sys.executable, str(ROOT / "scripts/cost_barrier_evidence.py"), "--materialize"],
                       cwd=ROOT, capture_output=True, timeout=300)
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "gate.json"
        out = subprocess.run(
            [sys.executable, str(ROOT / "scripts/cost_barrier_gate.py"), "--json", "--report", str(report)],
            cwd=ROOT, capture_output=True, text=True, timeout=600,
        )
        if out.returncode != 0 or not report.exists():
            return None, f"gate exited {out.returncode} without a report", False
        payload = read_json(report)
    ok = (payload.get("status") == "FULL_REPRODUCTION_PASS"
          and (payload.get("checks_failed") or 0) == 0)
    return payload, (f"{payload.get('status')} {payload.get('checks_total')} checks, "
                     f"{payload.get('checks_failed')} failed"), ok


# --------------------------------------------------------------------------- #
# negative controls
# --------------------------------------------------------------------------- #


def controls(manifest: dict[str, Any], certification: dict[str, Any],
             audit: dict[str, Any], results: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    missed = 0

    def exercise(name: str, detected: bool, detail: str) -> None:
        nonlocal missed
        missed += 0 if detected else 1
        rows.append({"control": name, "detected": detected, "signal": detail})

    # C1: a digest changed under the manifest must be refused.
    tampered = copy.deepcopy(manifest)
    first = tampered["groups"]["code_and_workflows"][0]
    first["sha256"] = "0" * 64
    problems = manifest_problems(tampered, ROOT)
    exercise("one manifest digest changed", bool(problems), problems[0] if problems else "not detected")

    # C2: a self-consistent but wrong fingerprint must be refused.
    tampered = copy.deepcopy(certification)
    tampered["evidence_fingerprint"] = "0" * 64
    problems = certification_problems(tampered, ROOT)
    exercise("certification fingerprint rewritten", bool(problems),
             problems[0] if problems else "not detected")

    # C3: an economic number edited without rebuilding the identity must be refused.
    tampered = copy.deepcopy(audit)
    strategy = next(iter(tampered["strategies"].values()))
    strategy["economics"]["base_expectancy_bps"] = float(
        strategy["economics"]["base_expectancy_bps"] or 0.0) + 1.0
    detected = audit_identity(tampered) != tampered.get("payload_sha256")
    exercise("one cell's economics raised by 1 bps", detected,
             "the identity no longer matches the stored payload_sha256"
             if detected else "not detected")

    # C4: a report claim that contradicts its evidence must be refused.
    tampered_results = copy.deepcopy(results)
    row = next(item for item in tampered_results["local"]
               if "scripts/cost_barrier_gate.py" in item["command"])
    row["status"] = "FAILED"
    gate_report = read_json(REPORT / "evidence/gate_report.json")
    problems = claims_problems(tampered_results, gate_report,
                               read_json(REPORT / "evidence/evidence_bundle.json"),
                               certification, read_json(REHEARSAL),
                               read_json(REPORT / "evidence/audit_check.json"))
    exercise("the report's gate status flipped to FAILED", bool(problems),
             problems[0] if problems else "not detected")
    return rows, missed


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def main() -> int:
    checks: list[dict[str, Any]] = []
    manifest = read_json(MANIFEST)
    results = read_json(RESULTS)
    certification = read_json(CERTIFICATION)
    audit = read_json(AUDIT)
    explorer = read_json(EXPLORER)
    rehearsal = read_json(REHEARSAL)
    gate_report = read_json(REPORT / "evidence/gate_report.json")
    evidence_bundle = read_json(REPORT / "evidence/evidence_bundle.json")
    audit_check = read_json(REPORT / "evidence/audit_check.json")

    problems = manifest_problems(manifest, ROOT)
    record(checks, "S1", "every artefact the report cites still has the recorded digest",
           not problems, "; ".join(problems[:5]) or f"{manifest.get('files_total')} files verified")

    problems = certification_problems(certification, ROOT)
    record(checks, "S2", "the certification is internally consistent, current and authorizes nothing",
           not problems, "; ".join(problems[:5]) or "CERTIFIED, fingerprint recomputes, evidence digests current")

    problems = audit_problems(audit, explorer)
    record(checks, "S3", "the published audit's identity recomputes and matches its explorer pin",
           not problems, "; ".join(problems[:5]) or audit["payload_sha256"][:16] + "...")

    payload, detail, ok = audit_check_subprocess()
    record(checks, "S4", "`active_economic_audit.py --check` passes without writing",
           ok, detail)

    payload, detail, ok = gate_rerun()
    record(checks, "S5", "a fresh gate run reproduces every published number", ok, detail)

    problems = economics_problems()
    record(checks, "S6", "the fix moved no economic finding or aggregate",
           not problems, "; ".join(problems[:3]) or "findings identical to a83ac165")

    problems = scope_problems()
    record(checks, "S7", "no risk, admission, cost or required-check file changed",
           not problems, "; ".join(problems) or "config/, risk/, cost model and CI gates untouched")

    problems = claims_problems(results, gate_report, evidence_bundle, certification,
                               rehearsal, audit_check)
    record(checks, "S8", "the report's numbers match the evidence it ships",
           not problems, "; ".join(problems[:4]) or "gate, evidence, certification, rehearsal and audit agree")

    ci_problems_found, ci_runs, blocked = ci_problems()
    record(checks, "S9", "both affected workflows are green on the tested commit",
           not ci_problems_found, "; ".join(ci_problems_found[:4])
           or ", ".join(f"{r['workflow']}={r['conclusion']}" for r in ci_runs), blocked)

    control_rows, false_success = controls(manifest, certification, audit, results)

    failed = [row for row in checks if row["result"] == "FAIL"]
    blocked_rows = [row for row in checks if row["result"] == "BLOCKED"]
    status = "FAIL" if failed or false_success else ("BLOCKED" if blocked_rows else "PASS")
    output = {
        "artifact": "RFC_TAP_CI_003_INDEPENDENT_VERIFICATION",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "head": git("rev-parse", "HEAD"),
        "tested_commit": TESTED,
        "baseline_commit": BASELINE,
        "status": status,
        "checks": checks,
        "checks_total": len(checks),
        "checks_failed": len(failed),
        "blocked": len(blocked_rows),
        "controls": control_rows,
        "controls_missed": sum(1 for row in control_rows if not row["detected"]),
        "false_success": false_success,
        "ci_runs": ci_runs,
        "manifest_sha256": sha256(MANIFEST.read_bytes()),
        "report_sha256": {
            name: sha256((REPORT / name).read_bytes())
            for name in ("FINAL_REPORT.json", "FINAL_REPORT.md")
            if (REPORT / name).exists()
        },
        "verifier": "reports/ai-bots/TAP-CI-REPRO-003/tools/verify_report.py",
        "scope": ("checks the delivered report, not the strategy: a PASS says the evidence is "
                  "current, reproducible and honestly described; it authorizes no promotion, no "
                  "PAPER change, no capital and no live order"),
    }
    OUT.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8", newline="\n")
    for row in checks:
        print(f"[{row['result']}] {row['id']} {row['check']} - {row['detail']}")
    print(f"status {status}; controls {len(control_rows)}; false_success {false_success}")
    return 0 if status == "PASS" else (3 if status == "BLOCKED" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
