"""verify_isolation — accept the isolation evidence only if it can be re-derived.

This file deliberately does not import ``trading_bot``. It reads the laboratory's JSON, the
child logs and the git blobs of the source commit, re-derives what "isolated" means from
those bytes, and then mutates its own copy of the bundle eight ways to check that it can
fail. A verifier that cannot reject a falsified bundle proves nothing about the bundle it
accepted.

    python scripts/verify_isolation.py --lab .../ISOLATION_LAB.json --bundle .../rfc005 \\
        --inventory .../ISOLATION_INVENTORY.json --repo . --evidence-sha <sha> \\
        --negative-controls --json /tmp/verdict.json

Exit codes: 0 PASS, 1 FAIL, 2 the verifier could not run.
"""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

Check = tuple[bool, str]

ORDER_CODE = "ISO_ORDER_ROUTE"


def _utc_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def _blob(repo: Path, commit: str, path: str) -> bytes | None:
    proc = subprocess.run(
        ["git", "show", f"{commit}:{path}"], cwd=str(repo), capture_output=True
    )
    return proc.stdout if proc.returncode == 0 else None


def _scenario(lab: dict[str, Any], scenario_id: str) -> dict[str, Any]:
    return next(
        (row for row in lab.get("scenarios") or [] if row.get("id") == scenario_id), {}
    )


def _observed(lab: dict[str, Any], scenario_id: str) -> dict[str, Any]:
    return dict(_scenario(lab, scenario_id).get("observed") or {})


def check_lab_shape(lab: dict[str, Any], _ctx: dict[str, Any]) -> Check:
    problems = []
    if lab.get("schema") != "rfc005-isolation-lab/1":
        problems.append(f"schema={lab.get('schema')!r}")
    ids = [row.get("id") for row in lab.get("scenarios") or []]
    expected = [f"ISO-{index:02d}" for index in range(10)]
    if ids != expected:
        problems.append(f"scenarios {ids} != {expected}")
    if lab.get("os_sandbox") != "NOT_AVAILABLE":
        problems.append(f"os_sandbox={lab.get('os_sandbox')!r}")
    counts = lab.get("counts") or {}
    if counts.get("total") != len(ids):
        problems.append("counts.total does not match the scenario list")
    if counts.get("passed", 0) + counts.get("limitations", 0) + counts.get("failed", 0) != len(ids):
        problems.append("counts do not add up to the scenario list")
    if problems:
        return False, "; ".join(problems)
    return True, f"{len(ids)} scenario(s), counts consistent, os_sandbox declared"


def check_scenarios_complete(lab: dict[str, Any], _ctx: dict[str, Any]) -> Check:
    missing = [
        row.get("id")
        for row in lab.get("scenarios") or []
        if row.get("child_status") != "RAN"
    ]
    if missing:
        return False, f"scenario(s) did not run: {missing}"
    return True, "every scenario was executed by a child process"


def check_inventory_gated(lab: dict[str, Any], ctx: dict[str, Any]) -> Check:
    """Every runtime order route is gated, or delegates to one that is.

    Re-derived from the commit, not from a list in the report: the inventory names the
    file, the class and the method, and the gate must be visible in that method's own body.
    """
    inventory: dict[str, Any] = ctx.get("inventory") or {}
    repo: Path | None = ctx.get("repo")
    commit = str(lab.get("source_commit") or "")
    if repo is None or not commit:
        return False, "no repository or source commit: the gate was not re-read"
    routes = [row for row in inventory.get("order_routes") or [] if row.get("authority") == "RUNTIME_REACHABLE"]
    if not routes:
        return False, "the inventory lists no runtime order route"
    problems = []
    gated = 0
    delegated = 0
    for row in routes:
        blob = _blob(repo, commit, str(row["file"]))
        if blob is None:
            problems.append(f"{row['file']}: not in {commit[:12]}")
            continue
        text = blob.decode("utf-8", errors="replace").replace("\r\n", "\n")
        tree = ast.parse(text)
        segment = None
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == row["class"]:
                for item in node.body:
                    if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) and item.name == row["method"]:
                        segment = ast.get_source_segment(text, item)
        if segment is None:
            problems.append(f"{row['route']}: not found in {row['file']}")
            continue
        if "assert_order_allowed" in segment:
            gated += 1
        elif any(token in segment for token in ("self._inner.", "self._client.", "_call(")):
            #: The wrapper forwards to the connector that is itself gated; the delegation
            #: token is checked so a wrapper body that does nothing is not accepted.
            delegated += 1
        else:
            problems.append(f"{row['route']}: no gate and no delegation in its body")
    if problems:
        return False, "; ".join(problems[:6])
    return True, f"{gated} runtime route(s) gated in place, {delegated} delegating route(s)"


def check_runtime_isolated(lab: dict[str, Any], _ctx: dict[str, Any]) -> Check:
    scenario = _scenario(lab, "ISO-00")
    observed = _observed(lab, "ISO-00")
    isolation = observed.get("isolation") or {}
    policy = isolation.get("policy") or {}
    problems = []
    if scenario.get("verdict") != "PASS":
        problems.append(f"verdict={scenario.get('verdict')}")
    if observed.get("exit_code") != 0:
        problems.append(f"runtime exit={observed.get('exit_code')}")
    if observed.get("report_status") != "EXECUTED":
        problems.append(f"report status={observed.get('report_status')!r}")
    if policy.get("mode") != "paper":
        problems.append(f"policy mode={policy.get('mode')!r}")
    if policy.get("order_routes") is not False or policy.get("external_network") is not False:
        problems.append(f"policy is not strict: {policy}")
    if scenario.get("network_log"):
        problems.append(f"{len(scenario['network_log'])} audited attempt(s) during the runtime")
    if problems:
        return False, "; ".join(problems)
    return True, "the paper runtime ran to EXECUTED under a strict policy, with no audited attempt"


def check_order_routes(lab: dict[str, Any], _ctx: dict[str, Any]) -> Check:
    problems = []
    checked = 0

    def refused(scenario_id: str, key: str) -> None:
        nonlocal checked
        row = (_observed(lab, scenario_id).get(key) or {})
        if row.get("outcome") != "REFUSED" or row.get("code") != ORDER_CODE:
            problems.append(f"{scenario_id}.{key}: {row.get('outcome')}/{row.get('code')}")
        checked += 1

    for key in ("create", "cancel"):
        refused("ISO-01", key)
    for key in ("client_place_order", "connector_create_order", "connector_cancel_order"):
        refused("ISO-02", key)
    for key in ("create", "cancel"):
        refused("ISO-03", key)

    if (_observed(lab, "ISO-01").get("venue_calls") or []) != []:
        problems.append("ISO-01: the fake venue was called")
    if (_observed(lab, "ISO-02").get("http_requests") or 0) != 0:
        problems.append("ISO-02: an HTTP request was attempted")
    if (_observed(lab, "ISO-03").get("client_calls") or 0) != 0:
        problems.append("ISO-03: the spot client was called")
    if problems:
        return False, "; ".join(problems)
    return True, f"{checked} order-capable call(s) refused with {ORDER_CODE}; no venue touched"


def check_live_route(lab: dict[str, Any], _ctx: dict[str, Any]) -> Check:
    observed = _observed(lab, "ISO-04")
    scenario = _scenario(lab, "ISO-04")
    problems = []
    if observed.get("exit_without_confirm") != 2:
        problems.append(f"without confirm: {observed.get('exit_without_confirm')}")
    if observed.get("exit_with_confirm_in_paper") != 2:
        problems.append(f"with confirm in paper: {observed.get('exit_with_confirm_in_paper')}")
    gate = observed.get("gate_on_command") or {}
    if gate.get("outcome") != "REFUSED" or gate.get("code") != ORDER_CODE:
        problems.append(f"gate={gate.get('outcome')}/{gate.get('code')}")
    if scenario.get("network_log"):
        problems.append("the CLI route produced an audited network attempt")
    if problems:
        return False, "; ".join(problems)
    return True, "the documented live CLI route exits 2 with and without --confirm-live, before any I/O"


def check_network_denied(lab: dict[str, Any], _ctx: dict[str, Any]) -> Check:
    network = _observed(lab, "ISO-05")
    http = _observed(lab, "ISO-06")
    problems = []
    for key in ("external_connect", "loopback_connect", "external_dns", "loopback_dns"):
        row = network.get(key) or {}
        if row.get("outcome") != "DENIED":
            problems.append(f"ISO-05.{key}={row.get('outcome')}")
    for key in ("urllib", "http_client"):
        row = http.get(key) or {}
        if row.get("outcome") != "DENIED":
            problems.append(f"ISO-06.{key}={row.get('outcome')}")
    hosts = {str(row.get("host")) for row in _scenario(lab, "ISO-05").get("network_log") or []}
    if "api.binance.com" not in hosts:
        problems.append(f"ISO-05: the denied host was not recorded (saw {sorted(host for host in hosts if host)})")
    if problems:
        return False, "; ".join(problems)
    return True, "connect, DNS, urllib and http.client were denied and the venue host was recorded"


def check_disarm(lab: dict[str, Any], _ctx: dict[str, Any]) -> Check:
    observed = _observed(lab, "ISO-08")
    problems = []
    for key in ("before", "after_env_flip"):
        row = observed.get(key) or {}
        if row.get("outcome") != "DENIED":
            problems.append(f"{key}={row.get('outcome')}")
    for key in ("reinstall_live", "mutated_policy"):
        row = observed.get(key) or {}
        if row.get("outcome") != "REFUSED":
            problems.append(f"{key}={row.get('outcome')}")
    if problems:
        return False, "; ".join(problems)
    return True, "environment flips did not weaken the guard and re-installation was refused"


def check_ccxt_construction(lab: dict[str, Any], _ctx: dict[str, Any]) -> Check:
    constructor = (_observed(lab, "ISO-07").get("constructor") or {})
    outcome = constructor.get("outcome")
    if outcome == "DENIED":
        return True, "the ccxt constructor was itself denied"
    if outcome == "CONSTRUCTED":
        fetch = (constructor.get("fetch_after_construction") or {}).get("outcome")
        if fetch == "DENIED":
            return True, "construction performed no I/O in this ccxt version; the first call was denied"
        return False, f"constructed and the next call ended {fetch!r}"
    return False, f"constructor outcome {outcome!r} is not classifiable"


def check_subprocess_limitation(lab: dict[str, Any], _ctx: dict[str, Any]) -> Check:
    scenario = _scenario(lab, "ISO-09")
    observed = _observed(lab, "ISO-09")
    problems = []
    if lab.get("os_sandbox") != "NOT_AVAILABLE":
        problems.append(f"os_sandbox={lab.get('os_sandbox')!r}: an OS barrier was claimed")
    if scenario.get("verdict") != "LIMITATION":
        problems.append(f"verdict={scenario.get('verdict')}: a known gap was folded into a PASS")
    if (observed.get("parent_attempt") or {}).get("outcome") != "DENIED":
        problems.append("the parent attempt was not denied")
    if "ATTEMPTED" not in str(observed.get("child_output")):
        problems.append(f"the child never reached the socket: {observed.get('child_output')!r}")
    if problems:
        return False, "; ".join(problems)
    return True, "the per-process boundary is measured and declared, never claimed as containment"


def check_no_orders(lab: dict[str, Any], _ctx: dict[str, Any]) -> Check:
    sent = 0
    for row in lab.get("scenarios") or []:
        observed = row.get("observed") or {}
        sent += len(observed.get("venue_calls") or [])
        sent += int(observed.get("http_requests") or 0)
        sent += int(observed.get("client_calls") or 0)
        if (observed.get("exit_with_confirm_in_paper") not in (None, 2)):
            sent += 1
    if sent:
        return False, f"{sent} order-capable side effect(s) were observed"
    return True, "venue calls, HTTP requests and spot-client calls sum to zero across the battery"


def check_runtime_identity(lab: dict[str, Any], ctx: dict[str, Any]) -> Check:
    repo: Path | None = ctx.get("repo")
    commit = str(lab.get("source_commit") or "")
    recorded = lab.get("filesystem_hashes") or {}
    if repo is None or not commit:
        return False, "no repository or source commit"
    if not recorded:
        return False, "the lab recorded no runtime hashes"
    problems = []
    for path, expected in sorted(recorded.items()):
        blob = _blob(repo, commit, path)
        if blob is None:
            problems.append(f"{path}: not in {commit[:12]}")
            continue
        if _sha(blob) != str(expected):
            problems.append(f"{path}: {_sha(blob)[:12]} != {str(expected)[:12]}")
    if problems:
        return False, "; ".join(problems[:5])
    return True, f"{len(recorded)} runtime file(s) hash to their blobs at {commit[:12]}"


def check_suite(lab: dict[str, Any], ctx: dict[str, Any]) -> Check:
    suite = ctx.get("suite") or {}
    if not suite:
        return False, "SUITE_IDENTITY.json is missing"
    repo_wide = suite.get("repo_wide") or {}
    problems = []
    if suite.get("exit_code") != 0:
        problems.append(f"acceptance exit={suite.get('exit_code')}")
    if (suite.get("failed") or 0) != 0:
        problems.append(f"acceptance failed={suite.get('failed')}")
    if repo_wide.get("non_baseline_failures"):
        problems.append(f"{repo_wide.get('non_baseline_failures')} new repo-wide failure(s)")
    if problems:
        return False, "; ".join(problems)
    return True, (
        f"acceptance {suite.get('passed')} passed, exit 0; "
        f"{repo_wide.get('failed', '—')} repo-wide failure(s), none new"
    )


def check_evidence_in_commit(_lab: dict[str, Any], ctx: dict[str, Any]) -> Check:
    repo: Path | None = ctx.get("repo")
    evidence_sha = ctx.get("evidence_sha")
    bundle: Path | None = ctx.get("bundle_dir")
    if repo is None or not evidence_sha or bundle is None:
        return False, "no evidence commit given: ACC evidence-in-commit was not verified"
    proc = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", evidence_sha],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return False, f"commit {evidence_sha[:12]} does not exist"
    committed = set(proc.stdout.split("\n"))
    try:
        prefix = str(bundle.resolve().relative_to(repo.resolve())).replace("\\", "/") + "/"
    except ValueError:
        return False, "the bundle is outside the repository"
    in_commit = {path[len(prefix) :] for path in committed if path.startswith(prefix) and path.strip()}
    on_disk = {
        str(path.relative_to(bundle)).replace("\\", "/")
        for path in bundle.rglob("*")
        if path.is_file() and path.name != "VERIFIER_REPLAY.json"
    }
    missing = sorted(on_disk - in_commit)
    if missing:
        return False, f"{len(missing)} file(s) on disk are not in the commit: {', '.join(missing[:5])}"
    return True, f"{len(in_commit)} evidence file(s) are inside commit {evidence_sha[:12]}"


def check_manifest(_lab: dict[str, Any], ctx: dict[str, Any]) -> Check:
    bundle: Path | None = ctx.get("bundle_dir")
    if bundle is None:
        return False, "no bundle directory"
    path = bundle / "EVIDENCE_MANIFEST.json"
    if not path.exists():
        return False, "EVIDENCE_MANIFEST.json is missing"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    files = manifest.get("files") or []
    problems = []
    listed = {str(row.get("path")) for row in files}
    for row in files:
        target = bundle / str(row.get("path"))
        if not target.exists():
            problems.append(f"{row.get('path')}: listed but absent")
            continue
        if _sha(target.read_bytes()) != str(row.get("sha256")):
            problems.append(f"{row.get('path')}: sha256 differs")
    on_disk = {
        str(p.relative_to(bundle)).replace("\\", "/")
        for p in bundle.rglob("*")
        if p.is_file()
        and p.name not in {"EVIDENCE_MANIFEST.json", "VERIFIER_REPLAY.json", "VERIFICATION.json"}
    }
    unlisted = sorted(on_disk - listed)
    if unlisted:
        problems.append(f"not in the manifest: {', '.join(unlisted[:5])}")
    if problems:
        return False, "; ".join(problems)
    return True, f"{len(files)} file(s) hashed and covered by the manifest"


def check_reports(lab: dict[str, Any], ctx: dict[str, Any]) -> Check:
    bundle: Path | None = ctx.get("bundle_dir")
    if bundle is None:
        return False, "no bundle directory"
    problems = []
    for name in ("RUN_REPORT.json", "FINAL_REPORT.json"):
        path = bundle / name
        if not path.exists():
            problems.append(f"{name} is missing")
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("code_sha") != lab.get("source_commit"):
            problems.append(f"{name}: code_sha != source_commit")
        if int(report.get("unsupported_pass_count", -1)) != 0:
            problems.append(f"{name}: unsupported_pass_count != 0")
        if report.get("paper_validation") != "NOT_PERFORMED":
            problems.append(f"{name}: paper_validation must remain NOT_PERFORMED")
    if problems:
        return False, "; ".join(problems)
    return True, "both reports point at the same commit and claim no paper validation"


CHECKS: tuple[tuple[str, Callable[[dict[str, Any], dict[str, Any]], Check]], ...] = (
    ("lab_shape", check_lab_shape),
    ("scenarios_complete", check_scenarios_complete),
    ("inventory_gated", check_inventory_gated),
    ("runtime_isolated", check_runtime_isolated),
    ("order_routes_refused", check_order_routes),
    ("live_route_refused", check_live_route),
    ("network_denied", check_network_denied),
    ("disarm_refused", check_disarm),
    ("ccxt_construction", check_ccxt_construction),
    ("subprocess_limitation", check_subprocess_limitation),
    ("no_orders", check_no_orders),
    ("runtime_identity", check_runtime_identity),
    ("suite_identity", check_suite),
    ("evidence_in_commit", check_evidence_in_commit),
    ("manifest_covers", check_manifest),
    ("reports_consistent", check_reports),
)


def verify(
    lab: dict[str, Any],
    *,
    bundle_dir: Path | None,
    repo: Path | None,
    evidence_sha: str | None,
    inventory: dict[str, Any],
    suite: dict[str, Any],
) -> dict[str, Any]:
    context = {
        "bundle_dir": bundle_dir,
        "repo": repo,
        "evidence_sha": evidence_sha,
        "inventory": inventory,
        "suite": suite,
    }
    results: list[dict[str, Any]] = []
    for name, function in CHECKS:
        try:
            ok, detail = function(lab, context)
        except Exception as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        results.append({"check": name, "ok": bool(ok), "detail": str(detail)})
    failed = [row["check"] for row in results if not row["ok"]]
    return {
        "schema": "rfc005-verification/1",
        "generated_at_utc": _utc_now(),
        "verdict": "PASS" if not failed else "FAIL",
        "checks": results,
        "failed": failed,
        "unsupported_pass_count": 0 if not failed else len(failed),
    }


def _mutations() -> dict[str, Callable[[dict[str, Any]], None]]:
    def drop_scenario(lab: dict[str, Any]) -> None:
        lab["scenarios"] = [row for row in lab["scenarios"] if row.get("id") != "ISO-05"]
        lab["counts"]["total"] = len(lab["scenarios"])

    def allow_an_order(lab: dict[str, Any]) -> None:
        row = _scenario(lab, "ISO-01")
        row["observed"]["create"] = {"outcome": "ALLOWED"}

    def venue_was_called(lab: dict[str, Any]) -> None:
        _scenario(lab, "ISO-01")["observed"]["venue_calls"] = ["create_order"]

    def claim_os_sandbox(lab: dict[str, Any]) -> None:
        lab["os_sandbox"] = "VERIFIED"
        _scenario(lab, "ISO-09")["verdict"] = "PASS"

    def hide_the_host(lab: dict[str, Any]) -> None:
        row = _scenario(lab, "ISO-05")
        row["network_log"] = [
            attempt for attempt in row.get("network_log") or [] if attempt.get("host") != "api.binance.com"
        ]

    def falsify_source(lab: dict[str, Any]) -> None:
        lab["source_commit"] = "0" * 40

    def falsify_runtime_hash(lab: dict[str, Any]) -> None:
        key = sorted(lab["filesystem_hashes"])[0]
        lab["filesystem_hashes"][key] = "0" * 64

    def runtime_attempted_network(lab: dict[str, Any]) -> None:
        row = _scenario(lab, "ISO-00")
        row["network_log"] = [
            {"event": "socket.getaddrinfo", "host": "api.binance.com", "decision": "DENY"}
        ]

    return {
        "NEG-01-scenario-dropped": drop_scenario,
        "NEG-02-order-allowed": allow_an_order,
        "NEG-03-venue-called": venue_was_called,
        "NEG-04-os-sandbox-claimed": claim_os_sandbox,
        "NEG-05-denied-host-hidden": hide_the_host,
        "NEG-06-source-commit-falsified": falsify_source,
        "NEG-07-runtime-hash-falsified": falsify_runtime_hash,
        "NEG-08-runtime-attempt-hidden": runtime_attempted_network,
    }


def negative_controls(
    lab: dict[str, Any],
    *,
    bundle_dir: Path | None,
    repo: Path | None,
    evidence_sha: str | None,
    inventory: dict[str, Any],
    suite: dict[str, Any],
) -> list[dict[str, Any]]:
    results = []
    for name, mutate in _mutations().items():
        mutated = copy.deepcopy(lab)
        mutate(mutated)
        outcome = verify(
            mutated,
            bundle_dir=bundle_dir,
            repo=repo,
            evidence_sha=evidence_sha,
            inventory=inventory,
            suite=suite,
        )
        results.append(
            {
                "id": name.split("-")[0],
                "mutation": name,
                "rejected": outcome["verdict"] != "PASS",
                "rejected_by": outcome["failed"],
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Independent verifier for RFC005 isolation.")
    parser.add_argument("--lab", required=True)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--suite", default="")
    parser.add_argument("--repo", default="")
    parser.add_argument("--evidence-sha", default="")
    parser.add_argument("--negative-controls", action="store_true")
    parser.add_argument("--json", required=True)
    args = parser.parse_args()

    lab_path = Path(args.lab)
    if not lab_path.exists():
        print(f"missing lab report: {lab_path}")
        return 2
    lab = json.loads(lab_path.read_text(encoding="utf-8"))
    inventory_path = Path(args.inventory)
    inventory = (
        json.loads(inventory_path.read_text(encoding="utf-8")) if inventory_path.exists() else {}
    )
    suite_path = Path(args.suite) if args.suite else Path(args.bundle) / "SUITE_IDENTITY.json"
    suite = json.loads(suite_path.read_text(encoding="utf-8")) if suite_path.exists() else {}

    outcome = verify(
        lab,
        bundle_dir=Path(args.bundle).resolve(),
        repo=Path(args.repo).resolve() if args.repo else None,
        evidence_sha=args.evidence_sha or None,
        inventory=inventory,
        suite=suite,
    )
    if args.negative_controls:
        controls = negative_controls(
            lab,
            bundle_dir=Path(args.bundle).resolve(),
            repo=Path(args.repo).resolve() if args.repo else None,
            evidence_sha=args.evidence_sha or None,
            inventory=inventory,
            suite=suite,
        )
        outcome["negative_controls"] = controls
        outcome["negative_controls_total"] = len(controls)
        outcome["negative_controls_rejected"] = sum(1 for row in controls if row["rejected"])
        if outcome["negative_controls_rejected"] != len(controls):
            outcome["verdict"] = "FAIL"
            outcome["failed"].append("negative_controls")
    target = Path(args.json)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(outcome, indent=1, sort_keys=True), encoding="utf-8")
    for row in outcome["checks"]:
        print(f"{'ok  ' if row['ok'] else 'FAIL'} {row['check']:24} {row['detail'][:110]}")
    for row in outcome.get("negative_controls") or []:
        print(f"{'ok  ' if row['rejected'] else 'FAIL'} {row['mutation']:34} {row['rejected_by']}")
    print(f"\nverdict: {outcome['verdict']}")
    return 0 if outcome["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
