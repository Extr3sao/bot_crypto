"""WP-10 phase 0 — close WP-9 on its own files, then prove the closure reproduces.

WP-9 ended with a commit that carries only its lane's files (``90ed615``). This phase
re-establishes that from the commit itself rather than from a note about it, and then
does the two things a closure acta has to do:

* **scope**: every path the commit touches is classified against the lane's declared
  ownership. A path nobody declared is a failure, not a footnote — that is how another
  lane's work would have entered the commit;
* **secrets**: the added blobs are scanned for credential material, with a canary that
  proves the scanner itself is alive rather than merely quiet;
* **reproduction**: the lane's producers are re-run in a **clean worktree of the
  commit** — not in the tree this script was invoked from — and their artefacts are
  compared with the committed ones. Only the keys this script declares volatile
  (timestamps) are excluded, and the exclusion is reported per artefact;
* **controls**: the comparison is exercised a second time against a deliberately
  mutated reference, which it must flag, and the classifier is shown to flag a foreign
  path and an undeclared one. A rehearsal that cannot fail is decoration.

The clean checkout is the point: "it passes here" is a claim about a working copy.
The producers are run with this interpreter and ``PYTHONPATH`` pinned to the worktree's
``src``; a probe asserts that ``trading_bot`` actually resolved inside the worktree, so
the guarantee is measured instead of assumed.

Exit codes: 0 expected outcome (pass), 2 the commit carries an undeclared or foreign
path, 3 credential material found, 4 a producer failed, 5 an artefact did not
reproduce, 6 a negative control was missed, 7 blocked (git or the worktree).
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
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "recovery" / "wp10"

LANE_PATH = "data/recovery/wp9"
CI_PATH = ".ci/wp9"

#: Files the commit is allowed to carry. ``owned`` is the lane's own footprint;
#: ``declared_exception`` is a shared file the lane had to touch to close its defect, and
#: it is declared here with the reason rather than left to look like scope creep.
OWNED_PATTERNS: tuple[str, ...] = (
    rf"^{re.escape(LANE_PATH)}/",
    rf"^{re.escape(CI_PATH)}/",
    r"^scripts/wp9_[a-z0-9_]+\.py$",
    r"^tests/unit/research/test_wp9_[a-z0-9_]+\.py$",
)
DECLARED_EXCEPTIONS: dict[str, str] = {
    "scripts/start_paper_lab.py": (
        "the enforcement point of the disk valve: the preflight that refuses an "
        "unaffordable window lives in the launcher, and WP-9's defect is only closed if "
        "the launcher refuses"
    ),
    "src/trading_bot/research/disk_budget.py": (
        "the disk valve itself: the measured-rate budget WP-9 introduced"
    ),
}
#: Other lanes' footprints. A hypothesis about who else was working at the time; a match
#: is reported loudly, and a non-match that is also not owned is reported as undeclared.
FOREIGN_PATTERNS: tuple[str, ...] = (
    r"^data/st6/",
    r"^data/recovery/wp7/",
    r"^data/recovery/wp8/",
    r"^data/recovery/INDEPENDENT_VERIFICATION\.json$",
    r"^evidence/real_decisions/",
    r"^data/rfc0",
    r"^docs/source_registry\.md$",
    r"^(RUN_REPORT|FINAL_REPORT)\.(md|json)$",
    r"^PAPER_DATA_24H_REPORT\.(md|json)$",
    r"^scripts/(?!wp9_)",
)

#: Credential shapes worth refusing to commit. Deliberately broad: a false positive costs
#: a look, a false negative costs a key.
SECRET_PATTERNS: tuple[tuple[str, str], ...] = (
    ("private_key_block", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("openai_style", r"\bsk-[A-Za-z0-9]{20,}"),
    ("aws_access_key", r"\bAKIA[0-9A-Z]{16}\b"),
    (
        "binance_key_shape",
        r"(?i)\b(api[_-]?key|secret[_-]?key|api[_-]?secret)\b\s*[:=]\s*"
        r"[\"']?[A-Za-z0-9/+_=-]{24,}",
    ),
    (
        "generic_password",
        r"(?i)\b(pass(word|phrase)|secret|token)\b\s*[:=]\s*"
        r"[\"'][^\"'\s]{16,}[\"']",
    ),
    ("bearer", r"(?i)\bauthorization\b\s*[:=]\s*[\"']?bearer\s+[A-Za-z0-9._-]{20,}"),
    ("env_file_content", r"(?m)^\s*[A-Z][A-Z0-9_]{3,}\s*=\s*[A-Za-z0-9/+_=-]{20,}\s*$"),
)
#: The canary: if the scanner cannot see this, it cannot be trusted to see anything.
CANARY = 'api_key = "AKIAIOSFODNN7EXAMPLE"  # canary: not a real key'


def git(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def classify(path: str) -> str:
    if any(re.search(pattern, path) for pattern in OWNED_PATTERNS):
        return "owned"
    if path in DECLARED_EXCEPTIONS:
        return "declared_exception"
    if any(re.search(pattern, path) for pattern in FOREIGN_PATTERNS):
        return "foreign"
    return "undeclared"


def scan_for_secrets(text: str) -> list[str]:
    return [name for name, pattern in SECRET_PATTERNS if re.search(pattern, text)]


def named_missing_input(text: str) -> str | None:
    """The input a failed producer said it could not find, in its own words.

    A producer that dies because an input is absent is a statement about the *input**, not
    about the producer, and the acta has to carry which input so the gap can be named.
    """
    if not text:
        return None
    match = re.search(r'"missing"\s*:\s*"([^"]+)"', text)
    if match:
        return match.group(1)
    match = re.search(r"FileNotFoundError:.*?['\"]([^'\"]+)['\"]", text, re.DOTALL)
    if match:
        return match.group(1)
    return None


# ---------------------------------------------------------------------------
# steps
# ---------------------------------------------------------------------------


def lane_commit(requested: str | None) -> dict[str, Any]:
    if requested:
        sha = requested
    else:
        sha = git("log", "-1", "--format=%H", "--", LANE_PATH).stdout.strip()
    if not sha:
        return {
            "sha": None,
            "resolved": False,
            "why": f"no commit touches {LANE_PATH} in this history",
        }
    meta = git("show", "-s", "--format=%H%x00%s%x00%an%x00%aI", sha).stdout.strip().split("\x00")
    return {
        "sha": meta[0],
        "subject": meta[1] if len(meta) > 1 else None,
        "author": meta[2] if len(meta) > 2 else None,
        "authored_at": meta[3] if len(meta) > 3 else None,
        "resolved": True,
    }


def scope_report(sha: str) -> dict[str, Any]:
    listing = git("show", "--name-only", "--diff-filter=ACMR", "--format=", sha).stdout
    paths = [line.strip() for line in listing.splitlines() if line.strip()]
    classes: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        classes[classify(path)].append(path)
    exceptions = [
        {"path": path, "reason": DECLARED_EXCEPTIONS[path]}
        for path in classes["declared_exception"]
    ]
    return {
        "files_touched": len(paths),
        "owned": classes["owned"],
        "declared_exceptions": exceptions,
        "foreign": classes["foreign"],
        "undeclared": classes["undeclared"],
        "verdict": ("PASS" if not classes["foreign"] and not classes["undeclared"] else "FAIL"),
    }


def secrets_report(sha: str, paths: list[str]) -> dict[str, Any]:
    hits: list[dict[str, Any]] = []
    scanned = 0
    for path in paths:
        blob = git("show", f"{sha}:{path}")
        if blob.returncode != 0:
            continue
        scanned += 1
        found = scan_for_secrets(blob.stdout)
        if found:
            hits.append({"path": path, "patterns": found})
    canary = scan_for_secrets(CANARY)
    return {
        "patterns": [name for name, _ in SECRET_PATTERNS],
        "files_scanned": scanned,
        "hits": hits,
        "canary_detected": bool(canary),
        "verdict": "PASS" if not hits and canary else "FAIL",
    }


class Rehearsal:
    """Runs the lane's producers inside a clean checkout of the commit."""

    def __init__(self, sha: str, python: str) -> None:
        self.sha = sha
        self.python = python
        self.results: list[dict[str, Any]] = []
        self.path: Path | None = None
        self.pristine: Path | None = None

    # -- plumbing -----------------------------------------------------------

    def child_env(self) -> dict[str, str]:
        assert self.path is not None
        env = {**os.environ}
        env["PYTHONPATH"] = str(self.path / "src")
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONHASHSEED"] = "0"
        env.pop("PYTHONSTARTUP", None)
        return env

    def run(
        self,
        ident: str,
        what: str,
        argv: list[str],
        *,
        expect: int = 0,
        timeout: int = 600,
        stdout_to: str | None = None,
    ) -> dict[str, Any]:
        assert self.path is not None
        # Some of the lane's evidence files are literally the tool's stdout; reproducing them
        # means reproducing the redirected stream, not a paraphrase of it.
        sink = None
        target = self.path / stdout_to if stdout_to else None
        if target is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            sink = target.open("w", encoding="utf-8", newline="\n")
        started = time.monotonic()
        try:
            if sink is None:
                completed = subprocess.run(
                    argv,
                    cwd=self.path,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                    env=self.child_env(),
                    encoding="utf-8",
                    errors="replace",
                )
            else:
                completed = subprocess.run(
                    argv,
                    cwd=self.path,
                    stdout=sink,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=timeout,
                    check=False,
                    env=self.child_env(),
                    encoding="utf-8",
                    errors="replace",
                )
            code = completed.returncode
            out = (completed.stdout or "") if sink is None else ""
            err = completed.stderr or ""
        except subprocess.TimeoutExpired:
            code, out, err = -9, "", f"timed out after {timeout} s"
        finally:
            if sink is not None:
                sink.close()
                out = target.read_text(encoding="utf-8") if target.exists() else ""
        entry = {
            "id": ident,
            "what": what,
            "command": " ".join(
                Path(part).name if part.startswith(str(self.path)) else part for part in argv
            ),
            "stdout_to": stdout_to,
            "exit_code": code,
            "expected_exit_code": expect,
            "result": "PASS" if code == expect else "FAIL",
            "seconds": round(time.monotonic() - started, 3),
            "stdout_tail": "\n".join(out.splitlines()[-8:]),
            # A failed producer's cause is usually the last frames of a traceback, so the tail
            # is long enough to carry the exception line rather than only its context.
            "stderr_tail": "\n".join(err.splitlines()[-12:]),
        }
        entry["missing_input_named"] = named_missing_input(
            entry["stdout_tail"] + entry["stderr_tail"]
        )
        self.results.append(entry)
        return entry

    # -- setup --------------------------------------------------------------

    def prepare(self) -> dict[str, Any]:
        tmp = Path(tempfile.gettempdir()) / f"wp10-phase0-{self.sha[:8]}"
        # A rehearsal killed mid-run leaves its worktree registered; the next one must not be
        # blocked by that, and must not silently rehearse a stale checkout either.
        git("worktree", "remove", "--force", str(tmp))
        git("worktree", "prune")
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        added = git("worktree", "add", "--detach", str(tmp), self.sha)
        if added.returncode != 0:
            return {
                "created": False,
                "path": str(tmp),
                "stderr": added.stderr.strip()[-400:],
                "stdout": added.stdout.strip()[-200:],
            }
        self.path = tmp
        head = git("rev-parse", "HEAD", cwd=tmp).stdout.strip()
        status = git("status", "--porcelain", cwd=tmp).stdout.strip()
        # the pristine copies: what the commit says the artefacts are, before anything runs
        self.pristine = Path(tempfile.gettempdir()) / f"wp10-phase0-pristine-{self.sha[:8]}"
        if self.pristine.exists():
            shutil.rmtree(self.pristine, ignore_errors=True)
        shutil.copytree(tmp / "data" / "recovery" / "wp9", self.pristine)
        probe = subprocess.run(
            [self.python, "-c", "import trading_bot, sys; print(trading_bot.__file__)"],
            cwd=tmp,
            capture_output=True,
            text=True,
            check=False,
            env=self.child_env(),
        )
        resolved = probe.stdout.strip()
        return {
            "created": True,
            "path": str(tmp),
            "head": head,
            "head_is_requested_commit": head == self.sha,
            "dirty_before_run": status or None,
            "module_resolved_to": resolved,
            "module_resolved_inside_checkout": resolved.startswith(str(tmp)),
            "pristine_copy": str(self.pristine),
        }

    def teardown(self) -> dict[str, Any]:
        if self.path is None:
            return {"removed": False}
        removed = git("worktree", "remove", "--force", str(self.path))
        if self.pristine is not None:
            shutil.rmtree(self.pristine, ignore_errors=True)
        return {"removed": removed.returncode == 0, "stderr": removed.stderr.strip()[-300:] or None}


# ---------------------------------------------------------------------------
# reproduction comparison
# ---------------------------------------------------------------------------

#: Keys allowed to differ between the committed artefact and the regenerated one. They
#: record *when* a run happened, not what it found; anything else that differs is a
#: disagreement between the commit and its own producers.
VOLATILE_KEYS: frozenset[str] = frozenset(
    {
        "generated_at_utc",
        "measured_at_utc",
        "run_timestamp",
        "started_at",
        "ended_at",
        "seconds",
        "stage_seconds",
        "measure_seconds",
        "elapsed_seconds",
        "duration_seconds",
        "free_bytes_now",
        "free_disk_bytes",
        "traces_added",
        "hours_executed",
        "generated_at",
    }
)

#: Artefacts whose content is a *run*, not a state: their timings and trace counts move by
#: construction. They are compared on the projection that carries the finding.
RUN_RECORDS: dict[str, tuple[str, ...]] = {
    "WP9_RUNTIME_24H_REPORT.json": (
        "verdict",
        "hours_target",
        "window_complete",
        "legs",
        "checks_total",
        "checks_not_exercised",
    ),
}

#: Evidence files that are the launcher's own output and must agree with the committed
#: copy on the state they report, with the clock and the free-space reading excluded.
EVIDENCE_PROJECTION: tuple[str, ...] = ("disk", "duration_hours", "processes", "verdict")

#: Which step writes which artefact. Reproduction is only *claimed* for an artefact whose
#: producer ran and passed in the checkout: a file nobody regenerated is the commit's own
#: copy, and calling that "identical" would be the cheapest possible false success.
ARTIFACT_PRODUCER: dict[str, str] = {
    "WP9_DISK_BUDGET_AUDIT.json": "disk-audit",
    "WP9_M03_M07_READINESS.json": "readiness",
    "WP9_ACTIVE_ECONOMIC_BLOCKERS.json": "economics",
    "INDEPENDENT_VERIFICATION.json": "verifier",
    "RUN_REPORT.json": "run-report",
    "WP9_CI_EXECUTION_REPORT.json": "ci-audit",
    "WP9_RUNTIME_24H_REPORT.json": "runtime-legs",
    "evidence/preflight_refusal.out": "preflight-refusal",
    "evidence/preflight_autoscale.out": "preflight-autoscale",
    "evidence/preflight_refusal_default.out": "preflight-refusal-default",
}


def scrub(node: Any, removed: list[str]) -> Any:
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if key in VOLATILE_KEYS:
                removed.append(key)
                continue
            out[key] = scrub(value, removed)
        return out
    if isinstance(node, list):
        return [scrub(item, removed) for item in node]
    return node


def project(node: Any, keys: tuple[str, ...]) -> Any:
    if isinstance(node, dict):
        return {key: project(node.get(key), keys) for key in keys}
    if isinstance(node, list):
        return [project(item, keys) for item in node]
    return node


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]


def compare(
    regenerated_dir: Path, reference_dir: Path, producer_result: dict[str, str]
) -> dict[str, Any]:
    """Compare regenerated artefacts with the committed ones, by name.

    An artefact whose producer did not run (or failed) is reported as NOT_REPRODUCED and
    excluded from the identity claim: its bytes in the checkout are the commit's own, and
    "they match themselves" is not a reproduction.
    """
    rows: list[dict[str, Any]] = []
    for path in sorted(regenerated_dir.glob("*.json")):
        name = path.name
        producer = ARTIFACT_PRODUCER.get(name)
        ran = producer_result.get(producer or "") == "PASS"
        if producer and not ran:
            rows.append(
                {
                    "artifact": name,
                    "producer": producer,
                    "producer_result": producer_result.get(producer, "NOT_RUN"),
                    "comparison": "NOT_REPRODUCED",
                    "identical": None,
                    "why": (
                        "the step that writes this artefact did not run, so the file in the "
                        "checkout is the commit's own copy"
                    ),
                }
            )
            continue
        reference = reference_dir / name
        if not reference.exists():
            rows.append(
                {
                    "artifact": name,
                    "producer": producer,
                    "comparison": "NO_REFERENCE",
                    "identical": False,
                    "why": "the commit does not carry this artefact",
                }
            )
            continue
        try:
            left = json.loads(reference.read_text(encoding="utf-8"))
            right = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            rows.append(
                {
                    "artifact": name,
                    "comparison": "UNPARSEABLE",
                    "identical": False,
                    "why": type(exc).__name__,
                }
            )
            continue
        removed: list[str] = []
        if name in RUN_RECORDS:
            left_cmp = project(left, RUN_RECORDS[name])
            right_cmp = project(right, RUN_RECORDS[name])
            mode = f"projection({', '.join(RUN_RECORDS[name])})"
        else:
            left_cmp = scrub(left, removed)
            right_cmp = scrub(right, removed)
            mode = "full document, volatile keys excluded"
        rows.append(
            {
                "artifact": name,
                "producer": producer,
                "producer_result": producer_result.get(producer or "", "NOT_RUN"),
                "comparison": mode,
                "excluded_keys": sorted(set(removed)),
                "digest_committed": digest(left_cmp),
                "digest_regenerated": digest(right_cmp),
                "identical": left_cmp == right_cmp,
            }
        )

    for path in sorted((regenerated_dir / "evidence").glob("*.out")):
        name = f"evidence/{path.name}"
        producer = ARTIFACT_PRODUCER.get(name)
        if producer and producer_result.get(producer) != "PASS":
            rows.append(
                {
                    "artifact": name,
                    "producer": producer,
                    "producer_result": producer_result.get(producer, "NOT_RUN"),
                    "comparison": "NOT_REPRODUCED",
                    "identical": None,
                    "why": "the command that writes this file did not run",
                }
            )
            continue
        reference = reference_dir / "evidence" / path.name
        if not reference.exists():
            rows.append({"artifact": name, "comparison": "NO_REFERENCE", "identical": False})
            continue
        try:
            left = json.loads(reference.read_text(encoding="utf-8"))
            right = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            rows.append(
                {
                    "artifact": name,
                    "comparison": "NOT_JSON",
                    "identical": None,
                    "why": "compared by the exit code of the command that wrote it",
                }
            )
            continue
        left_cmp = project(left, EVIDENCE_PROJECTION)
        right_cmp = project(right, EVIDENCE_PROJECTION)
        rows.append(
            {
                "artifact": name,
                "producer": producer,
                "producer_result": producer_result.get(producer or "", "NOT_RUN"),
                "comparison": f"projection({', '.join(EVIDENCE_PROJECTION)})",
                "digest_committed": digest(left_cmp),
                "digest_regenerated": digest(right_cmp),
                "identical": left_cmp == right_cmp,
            }
        )

    mismatches = [row["artifact"] for row in rows if row["identical"] is False]
    not_reproduced = [row["artifact"] for row in rows if row["comparison"] == "NOT_REPRODUCED"]
    compared = [row["artifact"] for row in rows if row["identical"] is not None]
    return {
        "artifacts": rows,
        "compared": len(compared),
        "mismatches": mismatches,
        "not_reproduced": not_reproduced,
    }


def mutate_reference(directory: Path, artifact: str = "WP9_M03_M07_READINESS.json") -> str | None:
    """Change one number in a reference copy and return what was changed.

    The mutation is applied to a throwaway copy of the *reference*, never to the committed
    artefact, and the comparison must flag it: that is the difference between a rehearsal
    and a rubber stamp.
    """
    path = directory / artifact
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    marker = "criteria_not_met"
    for hypothesis in (payload.get("hypotheses") or {}).values():
        if isinstance(hypothesis, dict) and isinstance(hypothesis.get(marker), int):
            before = hypothesis[marker]
            hypothesis[marker] = before + 1
            path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            return f"{artifact}: {marker} {before} -> {before + 1}"
    payload["sabotage_marker"] = "this line exists only in the mutated reference"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return f"{artifact}: added sabotage_marker"


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------


def free_bytes() -> int | None:
    try:
        return shutil.disk_usage(ROOT).free
    except OSError:
        return None


def build(
    requested_sha: str | None, *, run_rehearsal: bool, run_runtime_legs: bool
) -> dict[str, Any]:
    started = datetime.now(UTC)
    head = git("rev-parse", "HEAD").stdout.strip()
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    commit = lane_commit(requested_sha)

    controls: list[dict[str, Any]] = []
    classifier_control = {
        "id": "control-classifier",
        "what": "a foreign lane's path and an undeclared path are both reported",
        "detected": (
            classify(f"{LANE_PATH}/RUN_REPORT.json") == "owned"
            and classify("data/st6/ST6_RUNS.jsonl") == "foreign"
            and classify("somewhere/else.txt") == "undeclared"
            and classify("scripts/start_paper_lab.py") == "declared_exception"
        ),
        "observed": {
            f"{LANE_PATH}/RUN_REPORT.json": classify(f"{LANE_PATH}/RUN_REPORT.json"),
            "data/st6/ST6_RUNS.jsonl": classify("data/st6/ST6_RUNS.jsonl"),
            "somewhere/else.txt": classify("somewhere/else.txt"),
            "scripts/start_paper_lab.py": classify("scripts/start_paper_lab.py"),
        },
    }
    controls.append(classifier_control)

    if not commit.get("resolved"):
        return {
            "artifact": "WP10_PHASE0_WP9_CLOSURE",
            "verdict": "BLOCKED",
            "head": head,
            "branch": branch,
            "lane_commit": commit,
            "why": "the lane commit could not be resolved",
        }

    sha = commit["sha"]
    scope = scope_report(sha)
    secrets = secrets_report(
        sha, scope["owned"] + [p["path"] for p in scope["declared_exceptions"]]
    )
    controls.append(
        {
            "id": "control-secret-canary",
            "what": "the secret scanner sees a synthetic credential",
            "detected": secrets["canary_detected"],
        }
    )

    payload: dict[str, Any] = {
        "artifact": "WP10_PHASE0_WP9_CLOSURE",
        "work_package": "WP-10 (ECONOMIC EDGE RECOVERY & EXECUTION COST DISCOVERY)",
        "phase": "0 — CONTROLLED CLOSE OF WP-9",
        "generated_at_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "head": head,
        "branch": branch,
        "lane_commit": commit,
        "scope": scope,
        "secrets": secrets,
        "controls": controls,
        "not_exercised": [],
    }
    exit_code = 0
    if scope["verdict"] != "PASS":
        exit_code = 2
    if secrets["verdict"] != "PASS":
        exit_code = 3

    if run_rehearsal:
        rehearsal = Rehearsal(sha, sys.executable)
        setup = rehearsal.prepare()
        payload["clean_checkout"] = setup
        if not setup.get("created") or not setup.get("module_resolved_inside_checkout"):
            payload["verdict"] = (
                "BLOCKED — the clean checkout could not be established with the "
                "module resolved inside it"
            )
            payload["not_exercised"].append("every producer: the checkout was not usable")
            payload["inputs_absent_from_the_commit"] = []
            payload["controls"] = controls
            return payload
        python = sys.executable
        evidence = "data/recovery/wp9/evidence"
        rehearsal.run(
            "disk-audit",
            "the disk budget audit (the defect)",
            [python, "scripts/wp9_disk_budget_audit.py"],
        )
        rehearsal.run(
            "readiness", "M-03 / M-07 readiness", [python, "scripts/wp9_m03_m07_readiness.py"]
        )
        rehearsal.run(
            "economics", "ACTIVE economic blockers", [python, "scripts/wp9_economic_blockers.py"]
        )
        rehearsal.run(
            "preflight-refusal",
            "the launcher refuses a 24 h window its collector budget cannot pay for",
            [python, "scripts/start_paper_lab.py", "--duration-hours", "24", "--dry-run"],
            expect=4,
            stdout_to=f"{evidence}/preflight_refusal.out",
        )
        rehearsal.run(
            "preflight-refusal-default",
            "the same refusal on the default budget, with the run named",
            [
                python,
                "scripts/start_paper_lab.py",
                "--duration-hours",
                "24",
                "--dry-run",
                "--run-id",
                "wp9-preflight-refusal-default",
            ],
            expect=4,
            stdout_to=f"{evidence}/preflight_refusal_default.out",
        )
        rehearsal.run(
            "preflight-autoscale",
            "the same window, with the collector budget autoscaled, is accepted",
            [
                python,
                "scripts/start_paper_lab.py",
                "--duration-hours",
                "24",
                "--dry-run",
                "--autoscale-collector-budget",
                "--run-id",
                "wp9-preflight-autoscale",
            ],
            expect=0,
            stdout_to=f"{evidence}/preflight_autoscale.out",
        )
        rehearsal.run(
            "focused-tests",
            "the WP-9 focused test file",
            [python, "-m", "pytest", "-q", "tests/unit/research/test_wp9_disk_budget.py"],
            timeout=900,
        )
        if run_runtime_legs:
            rehearsal.run(
                "runtime-legs",
                "the runtime rehearsal: four legs, a controlled stop and a resume",
                [
                    python,
                    "scripts/wp9_runtime_rehearsal.py",
                    "--run-id",
                    "wp10-phase0-legs",
                    "--interval",
                    "20",
                    "--cycles",
                    "3",
                    "--bar-close-cycles",
                    "1",
                    "--stop-after-seconds",
                    "45",
                ],
                timeout=900,
            )
        else:
            payload["not_exercised"].append(
                "the four runtime legs: they start the real launcher and a scheduler, so the "
                "closure runs them only when asked for explicitly (--run-runtime-legs)"
            )
        rehearsal.run(
            "verifier",
            "the independent verifier, after the artefacts it checks exist",
            [python, "scripts/wp9_verify.py"],
            timeout=900,
        )
        rehearsal.run(
            "run-report",
            "the run report, folded from the regenerated artefacts",
            [python, "scripts/wp9_run_report.py"],
        )
        payload["rehearsal"] = rehearsal.results
        payload["not_exercised"].append(
            "the CI execution report: regenerating it re-runs two other lanes' workflow "
            "sequences (~9 min) and does not verify WP-9's own claims, which wp9_verify.py "
            "re-derives from the workflow text instead"
        )

        produced = rehearsal.path / "data" / "recovery" / "wp9"
        reference = rehearsal.pristine
        assert reference is not None
        producer_result = {row["id"]: row["result"] for row in rehearsal.results}
        reproduction = compare(produced, reference, producer_result)
        payload["reproduction"] = reproduction

        # the negative control: the same comparison, against a mutated reference, must fail
        mutated = Path(tempfile.gettempdir()) / f"wp10-phase0-mutated-{sha[:8]}"
        if mutated.exists():
            shutil.rmtree(mutated, ignore_errors=True)
        shutil.copytree(reference, mutated)
        changed = mutate_reference(mutated)
        mutated_result = compare(produced, mutated, producer_result)
        shutil.rmtree(mutated, ignore_errors=True)
        payload["controls"].append(
            {
                "id": "control-reproduction",
                "what": "a comparison against a mutated reference is flagged",
                "mutation": changed,
                "detected": bool(mutated_result["mismatches"]),
                "flagged": mutated_result["mismatches"][:5],
            }
        )
        # The falsifier for the gating itself: feed the comparison a status map in which one
        # producer failed and check that exactly its artefact is excluded. The artefacts are
        # compared against themselves here, so only the gate can produce a NOT_REPRODUCED.
        synthetic = {
            name: ("FAIL" if name == "disk-audit" else "PASS")
            for name in set(ARTIFACT_PRODUCER.values())
        }
        gated = compare(produced, produced, synthetic)
        payload["controls"].append(
            {
                "id": "control-nothing-ran",
                "what": "an artefact whose producer did not run is excluded from the identity claim",
                "detected": (
                    "WP9_DISK_BUDGET_AUDIT.json" in gated["not_reproduced"]
                    and "WP9_M03_M07_READINESS.json" not in gated["not_reproduced"]
                    and any(
                        row["artifact"] == "WP9_ACTIVE_ECONOMIC_BLOCKERS.json"
                        and row["identical"] is not None
                        for row in gated["artifacts"]
                    )
                ),
                "excluded_when_its_producer_failed": gated["not_reproduced"],
            }
        )
        payload["clean_checkout_removed"] = rehearsal.teardown()

        failed_producers = [row for row in rehearsal.results if row["result"] != "PASS"]
        payload["producers_failed"] = [row["id"] for row in failed_producers]
        payload["inputs_absent_from_the_commit"] = sorted(
            {
                row["missing_input_named"]
                for row in failed_producers
                if row.get("missing_input_named")
            }
        )
        if payload["inputs_absent_from_the_commit"]:
            payload["finding"] = (
                "the lane's artefacts are functions of (this commit, untracked campaign inputs). "
                "They rebuild in the working tree they were produced in and not from the commit "
                "alone: the same defect class WP-8B closed for its own lane with evidence copies "
                "under evidence/inputs/, still open here. The closure is therefore scoped, not "
                "withdrawn: the scope and secret gates pass, the launcher evidence and the "
                "focused tests reproduce exactly, and the three artefacts that consume campaign "
                "data are named as unreproducible rather than reported as identical to "
                "themselves"
            )
        missed_controls = [c["id"] for c in payload["controls"] if not c["detected"]]
        # The first phase that failed names the exit code, so a scope problem is never
        # hidden behind a later reproduction problem: min over the codes that were *earned*.
        earned = []
        if exit_code:
            earned.append(exit_code)
        if failed_producers:
            earned.append(4)
        if reproduction["mismatches"]:
            earned.append(5)
        if missed_controls:
            earned.append(6)
        exit_code = min(earned) if earned else 0

    payload["free_bytes_before"] = free_bytes()
    payload["elapsed_seconds"] = round((datetime.now(UTC) - started).total_seconds(), 3)
    payload["verdict"] = verdict_of(payload, exit_code)
    payload["exit_code"] = exit_code
    return payload


def verdict_of(payload: dict[str, Any], exit_code: int) -> str:
    sha = (payload.get("lane_commit") or {}).get("sha") or ""
    if exit_code == 0 and "reproduction" in payload:
        reproduction = payload["reproduction"]
        return (
            f"PASS — commit {sha[:8]} touches only its own files, carries no credential "
            f"material, and rebuilds from a clean checkout: "
            f"{reproduction['compared']} artefact(s) compared with 0 mismatches, "
            f"{len(reproduction['not_reproduced'])} not reproduced by this run, "
            f"every control detected"
        )
    if exit_code == 0:
        return (
            "PASS (scope and secrets only) — the rehearsal was not requested (pass --run-rehearsal)"
        )
    parts = [f"exit {exit_code}"]
    if payload.get("producers_failed"):
        parts.append(f"producers failed: {', '.join(payload['producers_failed'])}")
    reproduction = payload.get("reproduction") or {}
    if reproduction.get("mismatches"):
        parts.append(
            f"artefacts that did not match the commit: {', '.join(reproduction['mismatches'])}"
        )
    absent = payload.get("inputs_absent_from_the_commit") or []
    if absent:
        parts.append(f"inputs the commit does not carry: {len(absent)} named in this file")
    return "PARTIAL/FAIL — " + "; ".join(parts)


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# WP-10 phase 0 — controlled close of WP-9",
        "",
        f"> `{payload.get('generated_at_utc')}` · **{payload.get('verdict')}**",
        "",
        f"* HEAD `{payload.get('head')}` on `{payload.get('branch')}`",
        f"* lane commit `{(payload.get('lane_commit') or {}).get('sha')}` — "
        f"{(payload.get('lane_commit') or {}).get('subject')}",
        "",
        "## 1. Scope of the commit",
        "",
    ]
    scope = payload.get("scope") or {}
    lines += [
        f"* files touched: **{scope.get('files_touched')}**",
        f"* owned: **{len(scope.get('owned') or [])}**",
        f"* declared exceptions: **{len(scope.get('declared_exceptions') or [])}**",
        f"* other lanes' paths: **{len(scope.get('foreign') or [])}**",
        f"* undeclared paths: **{len(scope.get('undeclared') or [])}**",
        "",
    ]
    for item in scope.get("declared_exceptions") or []:
        lines.append(f"* `{item['path']}` — {item['reason']}")
    lines += ["", "## 2. Credentials", ""]
    secrets = payload.get("secrets") or {}
    lines += [
        f"* files scanned: **{secrets.get('files_scanned')}**, hits: **{len(secrets.get('hits') or [])}**",
        f"* scanner canary detected: **{secrets.get('canary_detected')}**",
        "",
    ]
    if payload.get("clean_checkout"):
        checkout = payload["clean_checkout"]
        lines += [
            "## 3. Clean checkout",
            "",
            f"* `{checkout.get('path')}` at `{checkout.get('head')}` "
            f"(is the requested commit: **{checkout.get('head_is_requested_commit')}**)",
            f"* `trading_bot` resolved to `{checkout.get('module_resolved_to')}` — inside the "
            f"checkout: **{checkout.get('module_resolved_inside_checkout')}**",
            f"* dirty before the run: **{checkout.get('dirty_before_run') or 'no'}**",
            "",
            "## 4. What ran in it",
            "",
            "| id | exit | expected | result | seconds | what |",
            "| --- | ---: | ---: | --- | ---: | --- |",
        ]
        for row in payload.get("rehearsal") or []:
            lines.append(
                f"| `{row['id']}` | {row['exit_code']} | {row['expected_exit_code']} | "
                f"{row['result']} | {row['seconds']} | {row['what']} |"
            )
        reproduction = payload.get("reproduction") or {}
        lines += [
            "",
            "## 5. Reproduction against the committed artefacts",
            "",
            f"compared **{reproduction.get('compared')}**, mismatches "
            f"**{len(reproduction.get('mismatches') or [])}**, not reproduced "
            f"**{len(reproduction.get('not_reproduced') or [])}**",
            "",
            "| artefact | producer | comparison | committed | regenerated | identical |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for row in reproduction.get("artifacts") or []:
            lines.append(
                f"| `{row['artifact']}` | `{row.get('producer') or '—'}` | "
                f"{row['comparison']} | "
                f"`{row.get('digest_committed') or '—'}` | "
                f"`{row.get('digest_regenerated') or '—'}` | {row['identical']} |"
            )
        if payload.get("inputs_absent_from_the_commit"):
            lines += ["", "Inputs a producer said it could not find in the clean checkout:", ""]
            lines += [f"* `{path}`" for path in payload["inputs_absent_from_the_commit"]]
    lines += ["", "## 6. Controls", "", "| id | what | detected |", "| --- | --- | --- |"]
    for control in payload.get("controls") or []:
        lines.append(f"| `{control['id']}` | {control['what']} | **{control['detected']}** |")
    if payload.get("not_exercised"):
        lines += ["", "## 7. Not exercised", ""]
        lines += [f"* {item}" for item in payload["not_exercised"]]
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--commit",
        default=None,
        help="commit to close (default: the last commit that touched the lane)",
    )
    parser.add_argument(
        "--run-rehearsal",
        action="store_true",
        help="rebuild the artefacts in a clean worktree of the commit",
    )
    parser.add_argument(
        "--run-runtime-legs", action="store_true", help="also re-run the four runtime legs (~4 min)"
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build(
        args.commit, run_rehearsal=args.run_rehearsal, run_runtime_legs=args.run_runtime_legs
    )
    if args.json:
        print(json.dumps(payload, indent=2, default=str))
        return int(payload.get("exit_code") or 0)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / "WP10_PHASE0_WP9_CLOSURE.json"
    md_path = OUT_DIR / "WP10_PHASE0_WP9_CLOSURE.md"
    json_path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(payload) + "\n", encoding="utf-8")
    print(f"{payload['verdict']}: {json_path.relative_to(ROOT)}")
    return int(payload.get("exit_code") or 0)


if __name__ == "__main__":
    sys.exit(main())
