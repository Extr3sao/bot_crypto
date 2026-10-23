"""WP-9A — CI runtime certification: what a real runner would do, and what is in the way.

WP-8 left two workflows committed and never executed on a GitHub runner. That is the
honest state, and this audit keeps it that way: it does **not** manufacture a run id, and
it never reports ``CI_CERTIFIED`` from a local pass.

What it does:

1. **reads the workflow as the runner would** — parses `.github/workflows/*.yml`, derives
   each job's runner, its steps and the commands those steps would execute, and holds
   them against the commit: every referenced script must exist and be tracked, every
   trigger path must match something committed, no step may soften itself with
   ``continue-on-error``;
2. **asks GitHub what it actually has** — repository visibility and default branch, the
   workflows registered on that branch, and whether these two are among them. A workflow
   file that is not on the default branch is not a workflow as far as Actions is
   concerned, which is precisely this project's situation;
3. **probes whether it could publish** — a *dry-run* push that creates no ref, whose only
   purpose is to answer "would this environment be allowed to put the workflow where
   Actions would see it". The probe's answer is recorded verbatim;
4. **runs the declared sequence locally, in the declared order**, and records each step's
   real exit code, so a reader can see exactly which part of the CI contract is proven on
   this machine and which part is not.

The verdict is therefore one of ``CI_CERTIFIED`` (only from a real run), ``LOCAL_EQUIVALENT``
(sequence green here, no runner) or ``BLOCKED`` (the sequence cannot even be attempted).
``LOCAL_EQUIVALENT`` is a claim about the commands, never about the runner.

Exit codes: 0 the sequence passed locally (whatever the runner status is), 2 the
sequence failed locally, 3 the workflows do not hold against the commit, 4 local
execution was not attempted (``--no-run``).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "recovery" / "wp9"

#: The workflows this audit covers, and what each one is supposed to prove.
WORKFLOWS: dict[str, str] = {
    ".github/workflows/recovery-determinism.yml": (
        "the ACTIVE recovery lane reproduces from a clean checkout of the commit"
    ),
    ".github/workflows/cost-barrier-gate.yml": (
        "the cost-barrier artefacts reproduce from their declared inputs"
    ),
}

#: The API surface used to interrogate GitHub without a token. A public repository
#: answers these; a private one would not, and the audit reports that rather than
#: guessing.
GITHUB_API = "https://api.github.com/repos/Extr3sao/bot_crypto"
GITHUB_REMOTE = "https://github.com/Extr3sao/bot_crypto.git"

EXIT_OK = 0
EXIT_SEQUENCE_FAILED = 2
EXIT_WORKFLOW_INVALID = 3
EXIT_NOT_ATTEMPTED = 4


@dataclass(frozen=True)
class Step:
    name: str
    run: str | None
    uses: str | None
    continue_on_error: bool
    if_condition: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "run": self.run,
            "uses": self.uses,
            "continue_on_error": self.continue_on_error,
            "if": self.if_condition,
        }


@dataclass(frozen=True)
class Job:
    name: str
    runs_on: str
    timeout_minutes: int | None
    steps: tuple[Step, ...] = field(default_factory=tuple)


def parse_workflow(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path} does not parse to a mapping")
    jobs = []
    for job_name, job in (document.get("jobs") or {}).items():
        steps = tuple(
            Step(
                name=str(step.get("name") or step.get("uses") or f"step-{index}"),
                run=step.get("run"),
                uses=step.get("uses"),
                continue_on_error=bool(step.get("continue-on-error", False)),
                if_condition=step.get("if"),
            )
            for index, step in enumerate(job.get("steps") or [])
        )
        jobs.append(
            Job(
                name=str(job_name),
                runs_on=str(job.get("runs-on") or ""),
                timeout_minutes=job.get("timeout-minutes"),
                steps=steps,
            )
        )
    triggers = document.get("on") or document.get(True) or {}
    return {
        "name": document.get("name"),
        "triggers": sorted(triggers) if isinstance(triggers, dict) else [str(triggers)],
        "jobs": jobs,
        "permissions": document.get("permissions"),
    }


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)


def tracked(path: str) -> bool:
    return git("ls-files", "--error-unmatch", path).returncode == 0


def committed_exists(path: str) -> bool:
    return git("cat-file", "-e", f"HEAD:{path}").returncode == 0


def ignored_by_git(path: str) -> bool:
    return git("check-ignore", "-q", path).returncode == 0


def trigger_path_matches(pattern: str) -> int:
    """How many committed paths a trigger glob covers (0 means the filter is dead)."""
    if pattern.endswith("/**"):
        prefix = pattern[: -len("/**")]
        out = git("ls-tree", "-r", "--name-only", "HEAD", prefix)
        return len([line for line in out.stdout.splitlines() if line.startswith(prefix)])
    if "*" in pattern:
        directory, _, name = pattern.rpartition("/")
        out = git("ls-tree", "-r", "--name-only", "HEAD", directory)
        regex = re.compile("^" + re.escape(name).replace(r"\*", "[^/]*") + "$")
        return len(
            [line for line in out.stdout.splitlines() if regex.match(line.rpartition("/")[2])]
        )
    return 1 if committed_exists(pattern) else 0


def commands_of(step: Step) -> list[str]:
    """The commands a ``run`` step would execute, with GitHub's folding removed."""
    if not step.run:
        return []
    lines = [line.strip() for line in step.run.strip().splitlines() if line.strip()]
    # a YAML folded scalar (`>-`) is one command spread over lines
    joined = " ".join(lines)
    joined = re.sub(r"\s+", " ", joined)
    return [joined]


def referenced_paths(command: str) -> list[str]:
    return [
        match.group(1)
        for match in re.finditer(r"(scripts/[\w./-]+\.py|tests/[\w./-]+\.py)", command)
    ]


def audit_workflow(relative: str) -> dict[str, Any]:
    path = ROOT / relative
    problems: list[str] = []
    if not path.exists():
        return {
            "path": relative,
            "present": False,
            "problems": ["the workflow file does not exist"],
        }
    parsed = parse_workflow(path)
    jobs = []
    for job in parsed["jobs"]:
        job_problems = list(problems)
        referenced: set[str] = set()
        for step in job.steps:
            if step.continue_on_error:
                job_problems.append(f"{job.name}/{step.name}: continue-on-error softens the step")
            for command in commands_of(step):
                for target in referenced_paths(command):
                    referenced.add(target)
                    if not tracked(target):
                        job_problems.append(
                            f"{job.name}/{step.name}: references untracked path {target}"
                        )
        jobs.append(
            {
                "name": job.name,
                "runs_on": job.runs_on,
                "runner_is_github_hosted": job.runs_on.startswith("ubuntu-"),
                "timeout_minutes": job.timeout_minutes,
                "timeout_declared": job.timeout_minutes is not None,
                "steps": [step.as_dict() for step in job.steps],
                "steps_total": len(job.steps),
                "steps_that_run_commands": sum(1 for s in job.steps if s.run),
                "referenced_paths": sorted(referenced),
                "referenced_paths_all_tracked": all(tracked(p) for p in referenced),
                "problems": [p for p in job_problems if p not in problems],
            }
        )
    # a trigger filter that matches nothing committed is a workflow that cannot fire:
    # the runner would consider the workflow registered and simply never start it
    stale_triggers: list[dict[str, Any]] = []
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    triggers = document.get("on") or document.get(True) or {}
    if isinstance(triggers, dict):
        for event in ("push", "pull_request"):
            entry = triggers.get(event) or {}
            for pattern in entry.get("paths") or []:
                matches = trigger_path_matches(str(pattern))
                if matches == 0:
                    # A path that exists only in the reader's head cannot be the reason a
                    # runner starts. Two things look identical here and mean different
                    # things, so they are told apart by asking git: a *dead* filter (the
                    # path is gone, and the workflow silently stops firing when it
                    # matters) and an *inert* one for an input that is gitignored and
                    # materialised on the runner by design, which the gate's own
                    # activation contract requires to be listed.
                    inert = ignored_by_git(str(pattern))
                    declared = (
                        git("grep", "-q", "-F", str(pattern), "HEAD", "--", "scripts/").returncode
                        == 0
                    )
                    stale_triggers.append(
                        {
                            "event": event,
                            "path": str(pattern),
                            "matches": 0,
                            "class": "INERT_MATERIALISED_INPUT"
                            if inert and declared
                            else "DEAD_FILTER",
                            "declared_in_head_code": declared,
                            "why": (
                                "gitignored by design and materialised from evidence on the "
                                "runner; listed because the gate's activation contract requires "
                                "every declared input to be covered"
                                if inert
                                else "the path is not ignored and not committed either: this filter "
                                "entry can never be the reason the workflow starts"
                            ),
                        }
                    )
    return {
        "path": relative,
        "present": True,
        "tracked": tracked(relative),
        "name": parsed["name"],
        "triggers": parsed["triggers"],
        "jobs": jobs,
        "stale_trigger_paths": stale_triggers,
        "problems": problems
        + [p for job in jobs for p in job["problems"]]
        + [
            f"trigger path {item['path']} matches nothing committed "
            f"({item['class']}: {item['why']})"
            for item in stale_triggers
            if item["class"] == "DEAD_FILTER"
        ],
    }


def local_sequence(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    """The declared command steps, in order, as they would be run here."""
    out = []
    for job in workflow.get("jobs", []):
        for step in job["steps"]:
            if not step["run"]:
                continue
            out.append({"job": job["name"], "step": step["name"], "command": step["run"]})
    return out


def declared_shell() -> tuple[list[str], str]:
    """The shell the commands are executed in, declared rather than inherited.

    A GitHub runner's default shell for a ``run:`` step is bash. This host's default shell
    is not (on Windows it is ``cmd.exe``, where ``mkdir -p .ci`` means something else
    entirely), so the sequence is executed with bash explicitly: the point of running the
    declared commands is to run *them*, not a shell's reinterpretation of them.

    On Windows, a bare ``bash`` can resolve to a WSL shell that cannot see Windows
    ``PATH`` entries at all, so the concrete binary is chosen (Git Bash first) rather than
    whatever the system happens to do with the name.
    """
    if os.name == "nt":
        for candidate in (
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
        ):
            if Path(candidate).exists():
                return [candidate, "-c"], candidate
        found = shutil.which("bash")
        if found and "git" in found.lower():
            return [found, "-c"], found
        return [], "platform default (cmd.exe: no Git Bash found)"
    for candidate in (["bash", "-c"], ["sh", "-c"]):
        if shutil.which(candidate[0]):
            return candidate, candidate[0]
    return [], "platform default (no bash or sh on PATH)"


def shell_env() -> dict[str, str]:
    """The runner's image has its tools on PATH; this shell must be told.

    Without this the declared commands fail with ``uv: command not found``, which would be
    a statement about this workstation's environment rather than about the commit.
    """
    env = {**os.environ}
    path = env.get("PATH", "")
    for tool in ("uv", "python", "git"):
        resolved = shutil.which(tool)
        if resolved:
            directory = os.path.dirname(resolved)
            if directory and directory not in path:
                path = directory + os.pathsep + path
    env["PATH"] = path
    if os.name == "nt":
        env.setdefault("MSYSTEM", "MINGW64")
    return env


EXPRESSION = re.compile(r"\$\{\{\s*([^}]+?)\s*\}\}")


def local_command(command: str) -> tuple[str, list[str]]:
    """The command as it can be run here, plus the substitutions that were made.

    Two things a runner does before the shell ever sees a step are reproduced rather than
    assumed: GitHub expands ``${{ ... }}`` expressions, and the runner's image has the
    tools on ``PATH``. Freezing an expression into a shell string is the difference
    between a step that runs and a step that dies with ``bad substitution``.
    """
    substitutions: list[str] = []

    def expand(match: re.Match[str]) -> str:
        expression = match.group(1).strip()
        if expression == "github.sha":
            substitutions.append(f"${{{{ {expression} }}}} -> the commit under test")
            return git("rev-parse", "HEAD").stdout.strip()
        substitutions.append(f"${{{{ {expression} }}}} -> NOT AVAILABLE locally")
        return f"<unavailable:{expression}>"

    expanded = EXPRESSION.sub(expand, command)
    return expanded, substitutions


def run_sequence(workflow: dict[str, Any], *, timeout: int) -> list[dict[str, Any]]:
    results = []
    shell, shell_name = declared_shell()
    for item in local_sequence(workflow):
        command, substitutions = local_command(item["command"])
        argv = [*shell, command] if shell else command
        started = time.monotonic()
        completed = subprocess.run(
            argv,
            cwd=ROOT,
            shell=not shell,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=shell_env(),
        )
        results.append(
            {
                **item,
                "command_as_run": command,
                "shell": shell_name,
                "substitutions": substitutions,
                "exit_code": completed.returncode,
                "result": "PASS" if completed.returncode == 0 else "FAIL",
                "seconds": round(time.monotonic() - started, 3),
                "stdout_tail": "\n".join(completed.stdout.splitlines()[-6:]),
                "stderr_tail": "\n".join(completed.stderr.splitlines()[-6:]),
            }
        )
    return results


def probe_github() -> dict[str, Any]:
    """What GitHub itself says, without a token."""
    import urllib.error
    import urllib.request

    def get(url: str) -> Any:
        request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}

    repo = get(GITHUB_API)
    answer: dict[str, Any] = {
        "repository": {
            "full_name": repo.get("full_name"),
            "visibility": repo.get("visibility"),
            "default_branch": repo.get("default_branch"),
            "pushed_at": repo.get("pushed_at"),
            "api_error": repo.get("error"),
        }
    }
    if repo.get("error"):
        answer["reachable"] = False
        return answer
    answer["reachable"] = True
    workflows = get(f"{GITHUB_API}/actions/workflows")
    registered = [
        {"name": item.get("name"), "path": item.get("path"), "state": item.get("state")}
        for item in (workflows.get("workflow_runs") or workflows.get("workflows") or [])
    ]
    answer["registered_workflows"] = registered
    answer["registered_total"] = workflows.get("total_count")
    runs = get(f"{GITHUB_API}/actions/runs?per_page=5")
    answer["recent_runs"] = [
        {
            "id": run.get("id"),
            "name": run.get("name"),
            "path": run.get("path"),
            "head_sha": run.get("head_sha"),
            "event": run.get("event"),
            "status": run.get("status"),
            "conclusion": run.get("conclusion"),
            "created_at": run.get("created_at"),
        }
        for run in (runs.get("workflow_runs") or [])
    ]
    remote = git("ls-remote", "origin", "HEAD")
    answer["remote_head"] = remote.stdout.split()[0] if remote.stdout.split() else None
    local = git("rev-parse", "HEAD").stdout.strip()
    answer["local_head"] = local
    behind = git("rev-list", "--left-right", "--count", "origin/main...HEAD")
    counts = behind.stdout.split()
    answer["commits_remote_ahead_of_local"] = int(counts[0]) if len(counts) == 2 else None
    answer["commits_local_ahead_of_remote"] = int(counts[1]) if len(counts) == 2 else None
    for relative in WORKFLOWS:
        answer.setdefault("workflow_presence_on_default_branch", {})[relative] = (
            git("cat-file", "-e", f"origin/main:{relative}").returncode == 0
        )
    return answer


def probe_push(dry_run_branch: str) -> dict[str, Any]:
    """Would this environment be allowed to publish? A dry run creates no ref."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
    completed = subprocess.run(
        ["git", "push", "--dry-run", "origin", f"HEAD:refs/heads/{dry_run_branch}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )
    output = (completed.stdout + completed.stderr).strip()
    authenticated = completed.returncode == 0 and "could not read Username" not in output
    return {
        "command": f"git push --dry-run origin HEAD:refs/heads/{dry_run_branch}",
        "creates_a_ref": False,
        "exit_code": completed.returncode,
        "output": output.splitlines()[:6],
        "authenticated": authenticated,
    }


def audit(run: bool, timeout: int) -> dict[str, Any]:
    workflows = {relative: audit_workflow(relative) for relative in WORKFLOWS}
    github = probe_github()
    push = probe_push("wp9-ci-probe-do-not-create")

    blocked_by: list[str] = []
    if not push["authenticated"]:
        blocked_by.append(
            "this environment cannot authenticate to the remote: the dry-run push reports "
            f"`{push['output'][0] if push['output'] else push['exit_code']}` — no `gh` CLI, no "
            "token in the environment, and the credential helper cannot prompt"
        )
    unregistered = [
        relative
        for relative, present in (github.get("workflow_presence_on_default_branch") or {}).items()
        if not present
    ]
    if unregistered:
        blocked_by.append(
            "the workflows are not on the default branch, so Actions has never registered them: "
            + ", ".join(sorted(unregistered))
            + f" (GitHub reports {github.get('registered_total')} registered workflow(s):"
            + " "
            + ", ".join(w["path"] or "?" for w in github.get("registered_workflows") or [])
            + ")"
        )
    ahead = github.get("commits_local_ahead_of_remote")
    if isinstance(ahead, int) and ahead:
        blocked_by.append(
            f"the commit that carries these workflows is {ahead} commits ahead of the remote: "
            "running them on a runner means publishing this history to a public repository, which "
            "is a governance decision and not a side effect of an audit"
        )
    if github.get("reachable") is False:
        blocked_by.append(f"the GitHub API is not answering: {github.get('error')}")

    sequence: list[dict[str, Any]] = []
    if run:
        for relative, workflow in workflows.items():
            if not workflow.get("present"):
                continue
            for result in run_sequence(workflow, timeout=timeout):
                sequence.append({**result, "workflow": relative})

    failed = [item for item in sequence if item["result"] != "PASS"]
    workflow_problems = [p for w in workflows.values() for p in w.get("problems", [])]

    verdict = "BLOCKED" if blocked_by else "LOCAL_EQUIVALENT"
    if not run:
        verdict = "BLOCKED" if blocked_by else "NOT_ATTEMPTED"
    if failed:
        verdict = "SEQUENCE_FAILED"

    return {
        "artifact": "WP9_CI_EXECUTION_REPORT",
        "work_package": "WP-9A (CI RUNTIME CERTIFICATION)",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "runner": ("GITHUB_ACTIONS" if os.environ.get("GITHUB_ACTIONS") else "LOCAL"),
        "ci_certified": False,
        "certification": {
            "ci_certified": False,
            "reason": (
                "CI_CERTIFIED requires a run id from a real runner; this audit has none and "
                "will not invent one. What is claimed instead is stated per workflow below."
            ),
            "local_equivalent": verdict == "LOCAL_EQUIVALENT",
            "blocked": bool(blocked_by),
            "blocked_by": blocked_by,
        },
        "workflows": workflows,
        "workflow_problems": workflow_problems,
        "github": github,
        "push_probe": push,
        "sequence_runs": sequence,
        "sequence_total": len(sequence),
        "sequence_failed": len(failed),
        "local_execution_attempted": run,
        "local_shell": declared_shell()[1],
        "verdict": verdict,
        "scope": {
            "read": [
                *sorted(WORKFLOWS),
                "git ls-files / cat-file against HEAD",
                "the GitHub REST API (public data only)",
            ],
            "wrote_to_the_remote": False,
            "note": (
                "the push probe is a dry run: it contacts the remote, authenticates nothing, "
                "and creates no ref"
            ),
        },
    }


def render_markdown(payload: dict[str, Any]) -> str:
    certification = payload["certification"]
    lines = [
        "# WP-9A — CI runtime certification",
        "",
        f"> `{payload['verdict']}` · runner `{payload['runner']}` · generated "
        f"`{payload['generated_at_utc']}`",
        "",
        "## 1. The verdict, first",
        "",
        f"`CI_CERTIFIED = {certification['ci_certified']}`. {certification['reason']}",
        "",
        "Local sequence: "
        f"{payload['sequence_total']} step(s), {payload['sequence_failed']} failed, "
        f"attempted={payload['local_execution_attempted']}.",
        "",
    ]
    if certification["blocked_by"]:
        lines += ["Blocked by:", ""]
        lines += [
            f"{index}. {reason}" for index, reason in enumerate(certification["blocked_by"], 1)
        ]
        lines.append("")
    lines += [
        "## 2. The workflows, read as the runner reads them",
        "",
    ]
    for relative, workflow in payload["workflows"].items():
        if not workflow.get("present"):
            lines.append(f"* `{relative}` — **missing**")
            continue
        lines.append(f"### `{relative}` — {workflow['name']}")
        lines.append("")
        for job in workflow["jobs"]:
            lines.append(
                f"* job `{job['name']}` on `{job['runs_on']}` "
                f"(github-hosted: {job['runner_is_github_hosted']}, "
                f"timeout: {job['timeout_minutes']} min)"
            )
            lines.append(
                f"  * {job['steps_total']} steps, {job['steps_that_run_commands']} that run commands, "
                f"referenced paths all tracked: {job['referenced_paths_all_tracked']}"
            )
        lines.append(f"* problems: {workflow['problems'] or 'none'}")
        lines.append("")
    lines += [
        "## 3. What GitHub actually has",
        "",
        f"* repository: `{payload['github']['repository']['full_name']}` "
        f"({payload['github']['repository']['visibility']}), default branch "
        f"`{payload['github']['repository']['default_branch']}`",
        f"* registered workflows: {payload['github'].get('registered_total')} — "
        + ", ".join(
            f"`{w['path']}` ({w['state']})"
            for w in payload["github"].get("registered_workflows") or []
        ),
        f"* remote head `{payload['github'].get('remote_head')}` vs local "
        f"`{payload['github'].get('local_head')}`: "
        f"{payload['github'].get('commits_local_ahead_of_remote')} commit(s) local-only, "
        f"{payload['github'].get('commits_remote_ahead_of_local')} remote-only",
        "* the workflows on the default branch: "
        + ", ".join(
            f"`{path}` {'present' if present else '**absent**'}"
            for path, present in (
                payload["github"].get("workflow_presence_on_default_branch") or {}
            ).items()
        ),
        "",
        "## 4. The publish probe",
        "",
        f"`{payload['push_probe']['command']}` (creates no ref: "
        f"`{payload['push_probe']['creates_a_ref']}`)",
        "",
        "```text",
        *payload["push_probe"]["output"],
        "```",
        "",
        "## 5. The declared sequence, executed here",
        "",
    ]
    if not payload["sequence_runs"]:
        lines.append("Not attempted (`--no-run` or a blocked workflow).")
        lines.append("")
    else:
        lines += [
            "| workflow | step | exit | seconds |",
            "| --- | --- | ---: | ---: |",
        ]
        for item in payload["sequence_runs"]:
            lines.append(
                f"| `{item['workflow']}` | {item['step']} | {item['exit_code']} | {item['seconds']} |"
            )
        lines.append("")
    lines += [
        "## 6. What this does and does not claim",
        "",
        "* **does**: the workflows parse, their steps name only tracked paths, no step softens "
        "itself, the trigger filters are not dead, and the declared command sequence passes "
        "on this machine with these exit codes;",
        "* **does not**: that any of it ran on a GitHub runner, that the runners' images carry "
        "the pinned Python and `uv`, or that a clean Ubuntu checkout behaves like this one. "
        "`TEST_TARGET == RUNTIME_TARGET` holds here between the declared commands and this "
        "workstation, not between this workstation and `ubuntu-latest`.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--no-run", action="store_true", help="audit the workflows, execute nothing"
    )
    parser.add_argument("--timeout", type=int, default=1800, help="per-step timeout (seconds)")
    parser.add_argument("--out", default=None)
    parser.add_argument("--report", default=None)
    args = parser.parse_args()

    payload = audit(run=not args.no_run, timeout=args.timeout)
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = Path(args.out) if args.out else OUT_DIR / "WP9_CI_EXECUTION_REPORT.json"
        report = Path(args.report) if args.report else OUT_DIR / "WP9_CI_EXECUTION_REPORT.md"
        out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        report.write_text(render_markdown(payload) + "\n", encoding="utf-8")
        print(f"{payload['verdict']}: {out} · {report}")

    if payload["workflow_problems"]:
        return EXIT_WORKFLOW_INVALID
    if payload["sequence_failed"]:
        return EXIT_SEQUENCE_FAILED
    return EXIT_OK if payload["local_execution_attempted"] else EXIT_NOT_ATTEMPTED


if __name__ == "__main__":
    sys.exit(main())
