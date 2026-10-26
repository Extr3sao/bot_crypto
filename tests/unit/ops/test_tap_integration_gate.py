"""The gate's judgements must fail on weak evidence, not only on a failing campaign.

These tests never run a campaign: they exercise the decision layer the campaigns feed, plus
the one rule that needs a real repository -- evidence may be delivered in a later commit only
while that commit adds nothing but evidence.  The campaigns themselves are exercised by
``tap_integration_gate.py run``; a unit test that faked them would prove nothing about them.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

REPO = Path(__file__).resolve().parents[3]


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


GATE = _load("tap_integration_gate")
AUDIT = _load("tap_gate_campaign_audit")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=True
    ).stdout.strip()


def _repo(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "gate@example.invalid")
    _git(path, "config", "user.name", "gate")
    (path / "a.txt").write_text("1\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-q", "-m", "start")
    return path


def _verifier_report(kind: str = "supervisor") -> dict[str, Any]:
    checks = GATE.MIN_SUPERVISOR_CHECKS if kind == "supervisor" else GATE.MIN_LOCK_CHECKS
    mutants = 14 if kind == "supervisor" else 9
    return {
        "verdict": "PASS",
        "judgement": {"verdict": "PASS", "checks": {f"check-{i}": True for i in range(checks)}},
        "adversarial": [
            {"mutation": f"mutation-{i}", "detected": True, "applicable": True}
            for i in range(mutants)
        ],
        "false_success": 0,
        "invalid_mutations": [],
        "undetected_mutations": [],
    }


def _audit_report(status: str = "PASS") -> dict[str, Any]:
    claims = {
        identifier: {"status": status, "problems": []}
        for identifier in ("C1", "L1", "S1", "S2", "V1")
    }
    return {
        "verdict": status,
        "false_success": 0,
        "claims": claims,
        "summary": {"claims": 5, "pass": 5 if status == "PASS" else 0},
    }


# --------------------------------------------------------------------------- verdicts


def test_a_single_failure_or_block_cannot_be_certified() -> None:
    assert GATE.verdict_of(["PASS", "PASS"]) == "PASS"
    assert GATE.verdict_of(["PASS", "NOT_TESTED"]) == "NOT_TESTED"
    assert GATE.verdict_of(["PASS", "FAIL", "NOT_TESTED"]) == "FAIL"
    assert GATE.verdict_of(["PASS", "BLOCKED", "FAIL"]) == "BLOCKED"


def test_the_report_says_which_steps_did_not_run() -> None:
    steps = {
        "C1": GATE.Step("C1", "campaign", status="FAIL", detail="exit 1"),
        "V1": GATE.Step("V1", "verifier", status="NOT_TESTED", detail="not run"),
    }
    report = {"verdict": "FAIL"}
    conclusion = GATE.conclusion_for(report, steps)
    assert "FAIL" in conclusion
    assert "C1" in conclusion and "V1" in conclusion


# --------------------------------------------------------------------------- verifier


def test_an_honest_verifier_report_passes_its_contract() -> None:
    for kind in ("supervisor", "lock"):
        status, _, problems = GATE.judge_verifier(kind, _verifier_report(kind))
        assert status == "PASS", (kind, problems)


def test_a_weakened_verifier_report_is_refused() -> None:
    good = _verifier_report("lock")

    failing = dict(good, verdict="FAIL")
    assert GATE.judge_verifier("lock", failing)[0] == "FAIL"

    one_false = json.loads(json.dumps(good))
    one_false["judgement"]["checks"]["stream_chain_intact"] = False
    assert GATE.judge_verifier("lock", one_false)[0] == "FAIL"

    fewer_checks = json.loads(json.dumps(good))
    fewer_checks["judgement"]["checks"] = dict(
        list(fewer_checks["judgement"]["checks"].items())[:5]
    )
    assert GATE.judge_verifier("lock", fewer_checks)[0] == "FAIL"

    fewer_mutations = json.loads(json.dumps(good))
    fewer_mutations["adversarial"] = fewer_mutations["adversarial"][:2]
    assert GATE.judge_verifier("lock", fewer_mutations)[0] == "FAIL"

    undetected = json.loads(json.dumps(good))
    undetected["adversarial"][0]["detected"] = False
    assert GATE.judge_verifier("lock", undetected)[0] == "FAIL"

    not_applicable = dict(good, not_applicable_checks=["budget_was_exhausted_not_exceeded"])
    assert GATE.judge_verifier("supervisor", not_applicable)[0] == "FAIL"


# --------------------------------------------------------------------------- audit


def test_the_audit_needs_every_claim_to_pass() -> None:
    assert GATE.judge_audit(_audit_report())[0] == "PASS"
    assert GATE.judge_audit(_audit_report("FAIL"))[0] == "FAIL"

    blind = _audit_report()
    blind["claims"]["S2"]["status"] = "FAIL"
    assert GATE.judge_audit(blind)[0] == "FAIL"


# --------------------------------------------------------------------------- binding


def test_a_campaign_from_another_commit_breaks_the_binding(tmp_path: Path) -> None:
    supervisor = tmp_path / "supervisor"
    lock = tmp_path / "lock"
    for root in (supervisor, lock):
        root.mkdir()
        (root / "CAMPAIGN.json").write_text(json.dumps({"commit": "a" * 40}), encoding="utf-8")
    reports = {"verifier_commit": "a" * 40}
    status, _, problems = GATE.judge_binding("a" * 40, supervisor, lock, reports, reports)
    assert status == "PASS", problems
    status, _, problems = GATE.judge_binding("b" * 40, supervisor, lock, reports, reports)
    assert status == "FAIL"
    assert any("ran at" in problem for problem in problems)


def test_evidence_may_travel_in_a_later_commit_only_if_it_adds_evidence(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    run_commit = _git(repo, "rev-parse", "HEAD")
    assert GATE.commit_binding(repo, run_commit, run_commit)[0] is True

    delivered = repo / "reports" / "ai-bots" / "TAP-INTEGRATION-GATE-001" / "RUN_REPORT.md"
    delivered.parent.mkdir(parents=True)
    delivered.write_text("# report\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "deliver the evidence")
    evidence_commit = _git(repo, "rev-parse", "HEAD")
    ok, detail = GATE.commit_binding(repo, run_commit, evidence_commit)
    assert ok is True, detail
    assert "only evidence" in detail

    (repo / "src").mkdir()
    (repo / "src" / "code.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "change the code")
    head = _git(repo, "rev-parse", "HEAD")
    ok, detail = GATE.commit_binding(repo, run_commit, head)
    assert ok is False
    assert "changed" in detail

    ok, detail = GATE.commit_binding(repo, "0" * 40, head)
    assert ok is False
    assert "not an ancestor" in detail


# --------------------------------------------------------------------------- shape


def _campaign_pair(tmp_path: Path, iterations: int = 6, races: int = 2) -> tuple[Path, Path]:
    supervisor = tmp_path / "supervisor"
    lock = tmp_path / "lock"
    (supervisor / "scenarios").mkdir(parents=True)
    (supervisor / "scenarios" / "SCENARIOS.json").write_text(
        json.dumps({"scenarios": {"corrupt": {}, "budget": {}}}), encoding="utf-8"
    )
    (supervisor / "CAMPAIGN.json").write_text(
        json.dumps(
            {
                "episodes": [{"episode": 1}],
                "live_orders": 0,
                "final": {"cycles": [1, 2], "state": "RECOVERED"},
            }
        ),
        encoding="utf-8",
    )
    lock.mkdir()
    rows = []
    for index in range(iterations):
        rows.append(
            {
                "iteration": index + 1,
                "crash_site": "AFTER_CYCLE" if index else "BEFORE_CYCLE",
                "concurrency": {"reclaimers": 1} if index < races else None,
            }
        )
    (lock / "CAMPAIGN.json").write_text(
        json.dumps({"iterations": rows, "mode": "PAPER", "live_orders": 0, "final_locks": []}),
        encoding="utf-8",
    )
    return supervisor, lock


def test_the_campaign_shape_is_part_of_the_contract(tmp_path: Path) -> None:
    supervisor, lock = _campaign_pair(tmp_path)
    passing = {"verdict": "PASS"}
    status, _, problems = GATE.judge_shape(supervisor, lock, passing)
    assert status == "PASS", problems

    short = tmp_path / "short"
    supervisor_short, lock_short = _campaign_pair(short, iterations=5)
    status, _, problems = GATE.judge_shape(supervisor_short, lock_short, passing)
    assert status == "FAIL"
    assert any("iterations" in problem for problem in problems)

    no_race = tmp_path / "no_race"
    supervisor_race, lock_race = _campaign_pair(no_race, races=1)
    status, _, problems = GATE.judge_shape(supervisor_race, lock_race, passing)
    assert status == "FAIL"
    assert any("races" in problem for problem in problems)


def test_a_moved_head_is_a_failure_not_a_footnote() -> None:
    recorded = {
        "commit": "a" * 40,
        "head_before": "a" * 40,
        "head_after": "a" * 40,
        "tree_clean_before": True,
        "tree_clean_after": True,
        "observed_commits": ["a" * 40],
    }
    assert GATE.judge_stability(recorded)[0] == "PASS"

    moved = dict(recorded, head_after="b" * 40, observed_commits=["b" * 40])
    status, _, problems = GATE.judge_stability(moved)
    assert status == "FAIL"
    assert any("HEAD moved" in problem for problem in problems)

    dirty = dict(recorded, tree_clean_before=False)
    assert GATE.judge_stability(dirty)[0] == "FAIL"


# --------------------------------------------------------------------------- verify


def test_verify_refuses_a_report_whose_campaigns_are_absent(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    head = GATE.git(REPO, "rev-parse", "HEAD")
    report = GATE.base_report(
        type("Args", (), {"label": "unit"})(),
        head,
        {"head": head, "branch": "test", "porcelain": [], "clean": True},
        {"head": head, "porcelain": [], "clean": True},
        GATE.contract_hashes(REPO),
        {"J1_SUPERVISOR_CONTRACT": GATE.Step("J1_SUPERVISOR_CONTRACT", "x", status="PASS")},
        [],
    )
    report["verdict"] = "PASS"
    report["certifies"] = True
    GATE.write_json(evidence / "GATE_REPORT.json", report)
    GATE.write_manifest(evidence, head)

    assert GATE.verify_evidence(evidence, REPO) == 1


# --------------------------------------------------------------------------- auditor chain


def test_the_auditor_recomputes_a_hand_built_chain(tmp_path: Path) -> None:
    stream = tmp_path / "STREAM.jsonl"
    previous = "0" * 64
    rows = []
    for seq in (1, 2):
        entry = {"kind": "CYCLE", "cycle": seq, "live_orders": 0}
        digest = AUDIT.sha256_bytes(
            AUDIT.canonical({"seq": seq, "prev_sha256": previous, "entry": entry}).encode()
        )
        rows.append(
            json.dumps({"seq": seq, "prev_sha256": previous, "entry": entry, "sha256": digest})
        )
        previous = digest
    stream.write_text("\n".join(rows) + "\n", encoding="utf-8")
    chain = AUDIT.chain_of(stream)
    assert chain["ok"] is True, chain["reason"]
    assert chain["lines"] == 2

    rows[1] = rows[1].replace('"cycle": 2', '"cycle": 3')
    stream.write_text("\n".join(rows) + "\n", encoding="utf-8")
    broken = AUDIT.chain_of(stream)
    assert broken["ok"] is False
    assert broken["reason"].startswith("SHA_AT_")


def test_a_campaign_without_a_stream_is_not_a_campaign(tmp_path: Path) -> None:
    claim = AUDIT.supervisor_claim(tmp_path)
    assert claim["status"] == "UNKNOWN"
    assert "CAMPAIGN.json missing" in claim["detail"]
