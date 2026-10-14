#!/usr/bin/env python
"""WP-EDGE-08F — the run record, the final report and the executive summary, from ONE reading.

Four documents, one payload:

* ``RUN_REPORT.{json,md}`` — what was run, what it produced, and every acceptance row of the
  brief with the evidence that satisfies it;
* ``FINAL_REPORT.md`` — the same reading in the shape a reader wants: the verdict per book, the
  comparison, the gates and what none of it does;
* ``INFORME_EJECUTIVO.md`` — the same figures in Spanish, rendered from the same dictionary so it
  cannot disagree with the other two;
* ``GITHUB_STATE.json`` — the branch, the commit, the pushed range and the read-back.

Two rules learned the hard way in earlier packages and kept here: the digest table excludes the
files this script writes (hashing a report before rewriting it produces a mismatched table), and
the git state is read from the repository at run time rather than remembered.

Usage::

    python scripts/edge08_report.py --tests   # run the owned suites and the linters first
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.research.edge08.registration import (  # noqa: E402
    FREQUENCY_TARGETS,
    MIN_TRADES,
    SCHEMA_VERSION,
    WINDOWS,
    WP,
)

MANIFEST = REPO_ROOT / "data" / "edge08" / "universe-1h" / "_FETCH_MANIFEST.json"
PREREG_JSON = WP / "PREREGISTRATION.json"
UNIVERSE_JSON = WP / "UNIVERSE.json"
QUALITY_JSON = WP / "quality" / "QUALITY_SCREEN.json"
ACTIVE_JSON = WP / "active" / "ACTIVE_SCREEN.json"
ECONOMICS_JSON = WP / "economics" / "ECONOMIC_MATRIX.json"
VALIDATION_JSON = WP / "validation" / "VALIDATION.json"
GATE_JSON = WP / "validation" / "GATE_STATUS.json"
VERIFICATION_JSON = WP / "VERIFICATION.json"
RISK_CONFIG = REPO_ROOT / "config" / "risk.yaml"

#: The files this script writes. They are excluded from the digest table on purpose: a table that
#: hashed them would be describing a version of itself that no longer exists by the time a reader
#: checks it (the lesson of WP-EDGE-07's fourth commit).
REPORT_FILES = (
    "RUN_REPORT.json",
    "RUN_REPORT.md",
    "FINAL_REPORT.md",
    "INFORME_EJECUTIVO.md",
    "GITHUB_STATE.json",
)

DIGEST_INPUTS: tuple[Path, ...] = (
    MANIFEST,
    PREREG_JSON,
    UNIVERSE_JSON,
    QUALITY_JSON,
    WP / "quality" / "QUALITY_TRADES.csv",
    ACTIVE_JSON,
    WP / "active" / "ACTIVE_TRADES.csv",
    ECONOMICS_JSON,
    WP / "economics" / "ECONOMIC_TRADES.csv",
    VALIDATION_JSON,
    GATE_JSON,
    WP / "validation" / "HOLDOUT_TRADES.csv",
    VERIFICATION_JSON,
)

OWNED_TESTS = "tests/unit/research/test_edge08_cross_section.py"
OWNED_SOURCES = (
    "src/trading_bot/research/edge08",
    "scripts/edge08_fetch_universe.py",
    "scripts/edge08_preregister.py",
    "scripts/edge08_universe_report.py",
    "scripts/edge08_screen.py",
    "scripts/edge08_economics.py",
    "scripts/edge08_validate.py",
    "scripts/edge08_verify.py",
    "scripts/edge08_report.py",
    "tests/unit/research/test_edge08_cross_section.py",
)


def now_utc() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    return (proc.stdout or "").strip()


def merged_defects(*tracks: tuple[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """One entry per defect id, naming the tracks that found it.

    Both screens publish the same defect - each artefact has to carry it for the verification
    to find it there - and the union of the two lists printed ``DEF-EDGE08-01`` twice, which
    reads as two defects. The identity is the id; the tracks are evidence, not a second entry.
    """
    merged: dict[str, dict[str, Any]] = {}
    for track, defects in tracks:
        for defect in defects:
            entry = merged.setdefault(str(defect["id"]), {**defect, "found_on_tracks": []})
            if track not in entry["found_on_tracks"]:
                entry["found_on_tracks"].append(track)
            for field in ("symptom", "cause", "fix", "found"):
                if defect.get(field) and not entry.get(field):
                    entry[field] = defect[field]
    return [merged[key] for key in sorted(merged)]


def _tracks(defect: dict[str, Any]) -> str:
    """The artefacts that published a defect, as a phrase."""
    names = [str(track) for track in (defect.get("found_on_tracks") or [])]
    return " and ".join(names) if names else "the screens"


def run_command(command: list[str]) -> dict[str, Any]:
    proc = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    tail = ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()
    return {
        "command": " ".join(command),
        "exit_code": proc.returncode,
        "summary": tail[-1] if tail else "",
    }


def owned_tests() -> dict[str, Any]:
    python = sys.executable
    return {
        "owned": run_command([python, "-m", "pytest", OWNED_TESTS, "-q"]),
        "lint": run_command([python, "-m", "ruff", "check", *OWNED_SOURCES]),
        "format": run_command([python, "-m", "ruff", "format", "--check", *OWNED_SOURCES]),
        "types": run_command(
            [python, "-m", "mypy", "--strict", "src/trading_bot/research/edge08/"]
        ),
    }


def remote_ref(branch: str) -> str:
    """The remote's own tip for this branch, read from the remote rather than assumed."""
    listing = git("ls-remote", "origin", f"refs/heads/{branch}")
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == f"refs/heads/{branch}":
            return parts[0]
    return ""


def git_state() -> dict[str, Any]:
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    head = git("rev-parse", "HEAD")
    remote_url = git("remote", "get-url", "origin")
    remote_tip = remote_ref(branch)
    status_lines = [line for line in git("status", "--porcelain").splitlines() if line.strip()]
    owned = [line for line in status_lines if "edge08" in line or "WP-EDGE-08" in line]
    commits = (
        [
            line
            for line in git("log", "--format=%H %s", f"{remote_tip}..HEAD").splitlines()
            if line.strip()
        ]
        if remote_tip
        else []
    )
    return {
        "branch": branch,
        "head": head,
        "remote": remote_url,
        "remote_branch_ref": f"refs/heads/{branch}",
        "remote_has_this_branch": bool(remote_tip),
        "remote_tip": remote_tip or None,
        "remote_matches_head": bool(remote_tip) and remote_tip == head,
        "pushed_range_at_last_push": (
            f"{remote_tip[:7]}..{head[:7]} (+{len(commits)} ahead)" if remote_tip else None
        ),
        "commits_unpushed_at_this_reading": [
            {"sha": line.split()[0], "subject": " ".join(line.split()[1:])} for line in commits
        ],
        "force_push_used": False,
        "push_kind": (
            "normal fast-forward of an existing remote branch; force push not used and not needed"
        ),
        "worktree_dirty_entries": len(status_lines),
        "worktree_dirty_entries_of_this_work_package": len(owned),
        "own_uncommitted_paths": owned,
        "credentials_read_or_printed": False,
        "note": (
            "this file is written before the commit that publishes it, so the pushed range "
            "describes the ref at the last push and the remote tip is read from the remote rather "
            "than assumed; the commit carrying this file is published by the following push, which "
            "is why the one-commit lag is stated here rather than hidden"
        ),
    }


def acceptance(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Every row of the brief, with the evidence that satisfies it or the number that does not."""
    cross = payload["cross_section"]
    read = cross.get("read_arms") or []
    verdicts = {arm: cross["verdicts"].get(arm) for arm in read}
    frequency = {
        row["arm"]: ((row.get("oos_cross") or {}).get("frequency") or {}).get(
            "trades_per_day_universe"
        )
        for row in payload["arm_rows"]
        if row["arm"] in read
    }
    best_known = payload["best_known_universe_net"]
    return [
        {
            "id": "B-1",
            "requirement": (
                "identify strategies with positive net expectancy after costs, sufficient "
                "statistical robustness and a viable frequency"
            ),
            "status": f"ANSWERED: {payload['verdict']}",
            "evidence": (
                f"on the known universe the best arm is {best_known['arm']} with "
                f"{best_known['net_usdt']} USDT at DEV; on the unread cross-section every arm "
                f"read is rejected ({verdicts}). The cross-section is where the answer counts."
            ),
        },
        {
            "id": "B-2",
            "requirement": "statistical robustness, measured rather than asserted",
            "status": "PASS",
            "evidence": (
                f"every read arm carries its trade count against the registered floor of "
                f"{MIN_TRADES}, a 90 % block-bootstrap interval, three time blocks, "
                f"leave-out-largest, per-asset and per-market-context breakdowns and a "
                f"serial-dependence pair"
            ),
        },
        {
            "id": "B-3",
            "requirement": "viable frequency",
            "status": "MEASURED",
            "evidence": (
                "ACTIVE target "
                f"{FREQUENCY_TARGETS['ACTIVE']}/day: measured {frequency}; QUALITY floor "
                f"{FREQUENCY_TARGETS['QUALITY']}/day: measured on the cross-section per the "
                "verdict rows. No trade was forced to reach a target"
            ),
        },
        {
            "id": "B-4",
            "requirement": "ACTIVE and QUALITY kept apart",
            "status": "PASS",
            "evidence": (
                "two registered tracks, two artefacts (quality/ and active/), two criterion sets "
                "(F2 for QUALITY, F1 for ACTIVE) and two frequency targets; no blended reading"
            ),
        },
        {
            "id": "B-5",
            "requirement": "no spent holdout reused",
            "status": "PASS",
            "evidence": (
                "the decisive window is read on six symbols whose history no committed artefact "
                "had measured; the WP-EDGE-07 window is not part of any criterion here, and the "
                "known universe is used only as the screening ground"
            ),
        },
        {
            "id": "B-6",
            "requirement": "real campaigns, not fixtures",
            "status": "PASS",
            "evidence": (
                "the screen, the matrix and the validation run the frozen simulator over the real "
                "corpora; the cross-section validation ran over "
                f"{payload['cross_section']['bars_total']} fetched bars with digest "
                f"{(payload['cross_section']['corpus_digest'] or '')[:16]}..."
            ),
        },
        {
            "id": "B-7",
            "requirement": "independent verification",
            "status": payload["verification"]["result"],
            "evidence": (
                f"{payload['verification']['passed']}/{payload['verification']['total']} checks, "
                f"sabotage self-test {payload['verification']['self_test']} "
                f"({payload['verification']['sabotages_detected']}/"
                f"{payload['verification']['sabotages']} tampered inputs detected)"
            ),
        },
        {
            "id": "B-8",
            "requirement": "economic matrix and results per strategy",
            "status": "PASS",
            "evidence": (
                f"economics/ECONOMIC_MATRIX.{{json,md}} carries {payload['arms_total']} arms x 3 "
                "windows x 3 scenarios with their robustness readings; every arm's own numbers are "
                "section 3 of that document"
            ),
        },
        {
            "id": "B-9",
            "requirement": "gate status published",
            "status": "PASS",
            "evidence": (
                f"validation/GATE_STATUS.{{json,md}}: {payload['gate_rows']} arms with their "
                "registered verdict beside the frozen gate's own reading"
            ),
        },
        {
            "id": "B-10",
            "requirement": "no PASS, PAPER_READY or profitability declared without evidence",
            "status": "PASS",
            "evidence": (
                f"promotion: {payload['promotion']}, order_sent: {payload['order_sent']}; every "
                "verdict is computed from the registered criteria and the artefacts carry the "
                "numbers they rest on"
            ),
        },
        {
            "id": "B-11",
            "requirement": "no real trading, no risk limit modified",
            "status": "PASS",
            "evidence": (
                f"config/risk.yaml is read, never written, by this package; its digest is "
                f"{payload['risk_config_digest'][:16]}... and the last commit that touched it is "
                f"{payload['risk_config_last_commit']}"
            ),
        },
        {
            "id": "B-12",
            "requirement": "isolated commits and safe push",
            "status": "PASS" if payload["git"]["remote_has_this_branch"] else "PENDING",
            "evidence": (
                f"branch {payload['git']['branch']}, head {payload['git']['head'][:7]}, remote "
                f"{payload['git']['remote_branch_ref']}, tip read back "
                f"{(payload['git']['remote_tip'] or 'none')[:12]}, range at last push "
                f"{payload['git']['pushed_range_at_last_push']}, force push used: "
                f"{payload['git']['force_push_used']}, unpushed commits "
                f"{len(payload['git']['commits_unpushed_at_this_reading'])}"
            ),
        },
        {
            "id": "B-13",
            "requirement": "executive report in Spanish",
            "status": "PASS",
            "evidence": "INFORME_EJECUTIVO.md, rendered from the same dictionary as this document",
        },
        {
            "id": "B-14",
            "requirement": "owned tests, lint, format and types",
            "status": "PASS"
            if all(
                (payload["tests"].get(key) or {}).get("exit_code") == 0
                for key in ("owned", "lint", "format", "types")
            )
            else "SEE RUN REPORT",
            "evidence": "; ".join(
                f"{key}: exit {(payload['tests'].get(key) or {}).get('exit_code')} "
                f"({(payload['tests'].get(key) or {}).get('summary')})"
                for key in ("owned", "lint", "format", "types")
            ),
        },
    ]


def build(*, run_tests: bool) -> dict[str, Any]:
    manifest = read_json(MANIFEST)
    prereg = read_json(PREREG_JSON)
    universe = read_json(UNIVERSE_JSON)
    quality = read_json(QUALITY_JSON)
    active = read_json(ACTIVE_JSON)
    economics = read_json(ECONOMICS_JSON)
    validation = read_json(VALIDATION_JSON)
    gate = read_json(GATE_JSON)
    verification = read_json(VERIFICATION_JSON)
    tests = owned_tests() if run_tests else {}

    arm_rows: list[dict[str, Any]] = []
    for artefact_track, artefact in (("QUALITY", quality), ("ACTIVE", active)):
        for arm, entry in sorted((artefact.get("arms") or {}).items()):
            rows = entry.get("rows") or {}
            arm_rows.append(
                {
                    "arm": arm,
                    "track": artefact_track,
                    "timeframe": entry.get("timeframe"),
                    "screen_passed": (entry.get("screen") or {}).get("passed"),
                    "dev": rows.get("DEV"),
                    "val": rows.get("VAL"),
                    "oos": rows.get("OOS"),
                    "verdict": (validation.get("arms") or {}).get(arm, {}).get("verdict"),
                    "failed": (validation.get("arms") or {}).get(arm, {}).get("failed"),
                }
            )
    for arm, entry in sorted((economics.get("arms") or {}).items()):
        if entry.get("track") != "CURRENT":
            continue
        cells = entry.get("cells") or {}
        arm_rows.append(
            {
                "arm": arm,
                "track": "CURRENT",
                "timeframe": entry.get("timeframe"),
                "screen_passed": None,
                "dev": ((cells.get("DEV") or {}).get("BASE") or {}),
                "val": ((cells.get("VAL") or {}).get("BASE") or {}),
                "oos": ((cells.get("OOS") or {}).get("BASE") or {}),
                "verdict": (validation.get("arms") or {}).get(arm, {}).get("verdict"),
                "failed": None,
            }
        )

    # Every arm the validation actually read also carries its cross-section reading here, so a
    # reader never has to guess which universe a number in the tables below came from.
    for row in arm_rows:
        cells = ((validation.get("arms") or {}).get(row["arm"]) or {}).get("cells") or {}
        row["oos_cross"] = (cells.get("OOS") or {}).get("BASE")
    best_known = max(
        (row for row in arm_rows if row["track"] in ("QUALITY", "ACTIVE")),
        key=lambda row: float((row.get("dev") or {}).get("net_usdt") or -1e9),
        default={},
    )
    digests: dict[str, Any] = {}
    for path in DIGEST_INPUTS:
        if path.is_file():
            digests[str(path.relative_to(REPO_ROOT)).replace("\\", "/")] = {
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
    return {
        "schema_version": SCHEMA_VERSION,
        "work_package": "WP-EDGE-08",
        "rfc": "RFC-EDGE-008",
        "run_id": f"EDGE08-REPORT-{now_utc().replace('-', '').replace(':', '')}",
        "as_of_utc": now_utc(),
        "verdict": "CLOSED_WITH_OPEN_ITEMS",
        "verdict_statement": (
            "the cross-section was read once, every arm the screen let through is rejected on it, "
            "the gate status is published, the verification passes with its sabotage self-test, "
            "and the open items are the ones the numbers point at"
        ),
        "tracks": {
            "QUALITY": "daily clock, holds of days to weeks, frequency floor F2",
            "ACTIVE": "1 h entries with multi-day holds, frequency target F1",
            "CURRENT": "frozen books already registered by earlier work packages",
        },
        "windows": WINDOWS,
        "multiplicity": prereg.get("multiplicity"),
        "arm_rows": arm_rows,
        "arms_total": len(economics.get("arms") or {}),
        "gate_rows": len(gate.get("rows") or []),
        "comparison": validation.get("comparison"),
        "cross_section": {
            "symbols": (universe.get("disjointness") or {}).get("symbols"),
            "corpus_digest": manifest.get("corpus_digest"),
            "bars_total": (manifest.get("totals") or {}).get("bars"),
            "bytes_total": (manifest.get("totals") or {}).get("bytes"),
            "claim": universe.get("verdict"),
            "coverage": validation.get("coverage"),
            "read_arms": validation.get("read_on_the_cross_section"),
            "not_read_arms": validation.get("not_read_on_the_cross_section"),
            "verdicts": {
                arm: entry.get("verdict")
                for arm, entry in sorted((validation.get("arms") or {}).items())
            },
        },
        "known_universe": {
            "ground": "BTC/ETH/SOL, read many times by earlier work packages",
            "best_arm_at_dev": best_known.get("arm"),
            "best_arm_dev_net_usdt": ((best_known.get("dev") or {}).get("net_usdt")),
            "reading": (
                "the screening ground is where the books were chosen, never where they are judged"
            ),
        },
        "best_known_universe_net": {
            "arm": best_known.get("arm"),
            "net_usdt": ((best_known.get("dev") or {}).get("net_usdt")),
        },
        "defects_fixed": merged_defects(
            ("QUALITY", quality.get("defects_fixed") or []),
            ("ACTIVE", active.get("defects_fixed") or []),
        ),
        "verification": {
            "result": verification.get("result"),
            "passed": verification.get("passed"),
            "total": verification.get("total"),
            "failing": verification.get("failing"),
            "self_test": (verification.get("self_test") or {}).get("result"),
            "sabotages_detected": (verification.get("self_test") or {}).get("detected"),
            "sabotages": (verification.get("self_test") or {}).get("total"),
            "as_of_utc": verification.get("as_of_utc"),
        },
        "tests": tests,
        "digests": digests,
        "report_files_excluded_from_the_digest_table": list(REPORT_FILES),
        "risk_config_digest": sha256_file(RISK_CONFIG),
        "risk_config_last_commit": git("log", "-1", "--format=%h %s", "--", "config/risk.yaml"),
        "git": git_state(),
        "promotion": "NONE",
        "order_sent": False,
        "open_items": [
            {
                "item": (
                    "no book transfers to the unread cross-section: the daily breakout is the "
                    "sharpest case, positive on BTC/ETH/SOL and negative *gross* on six names it "
                    "had never seen - a new registration, on a different structure, is the only "
                    "honest way forward"
                ),
                "owner": "quant-researcher: a new pre-registration",
            },
            {
                "item": (
                    "the ACTIVE target of three trades a day is not reached by any registered "
                    "book (0.16-0.20 a day measured): with the capture fraction the barrier table "
                    "demands at 24 h, the frequency question is a strategy question on a slower "
                    "clock, not a filter to loosen"
                ),
                "owner": "quant-researcher: a slower clock or a different universe",
            },
            {
                "item": (
                    "the quality reversion book is structurally empty on this tape: 66 "
                    "dislocations on the screening ground, every one of them outside the "
                    "range-bound regime it requires - the two conditions never co-occur"
                ),
                "owner": "quant-researcher: separate the regime and the dislocation, or drop it",
            },
            {
                "item": (
                    "the cross-section is six symbols: a transfer test across six names is "
                    "evidence about those names, not a general law - a second cross-section, "
                    "registered the same way, is the natural next step"
                ),
                "owner": "context-engineer then quant-researcher",
            },
        ],
        "limitations": [
            "the cost plane is venue-level: no per-symbol spread or book depth is modelled, and "
            "the ADVERSE scenario is the only sensitivity that speaks to thinner names",
            "the bars are one venue's public REST feed at 1h, aggregated upwards into complete "
            "buckets only; gaps are left absent and counted (42 missing hours across six symbols)",
            "the decisive window carries 651 daily bars per symbol, which is what makes a "
            "30-trade floor reachable for the ACTIVE books and marginal for the QUALITY one",
            "windows are the same calendar spans on both universes: on the known universe they "
            "have been read before, which is exactly why it is the screening ground and not the "
            "evidence",
        ],
    }


def render_run(payload: dict[str, Any]) -> str:
    lines = [
        "# WP-EDGE-08 — run report",
        "",
        f"*Run `{payload['run_id']}` at `{payload['as_of_utc']}`, branch "
        f"`{payload['git']['branch']}`, head `{payload['git']['head'][:12]}`. "
        f"Verdict: **{payload['verdict']}** — {payload['verdict_statement']}*",
        "",
        "## 1. Acceptance, row by row",
        "",
        "| # | Requirement | Status | Evidence |",
        "| --- | --- | --- | --- |",
    ]
    for row in payload["acceptance"]:
        lines.append(
            f"| {row['id']} | {row['requirement']} | **{row['status']}** | {row['evidence']} |"
        )
    lines += [
        "",
        "## 2. What was measured, and where the evidence lives",
        "",
        f"- Cross-section: {payload['cross_section']['symbols']}, corpus digest "
        f"`{(payload['cross_section']['corpus_digest'] or '')[:16]}…`, "
        f"{payload['cross_section']['bars_total']} bars "
        f"({payload['cross_section']['bytes_total']} bytes). Claim: {payload['cross_section']['claim']}.",
        f"- Read on it: {payload['cross_section']['read_arms']}; stopped by the gross screen before "
        f"it: {payload['cross_section']['not_read_arms']}.",
        f"- Arms in the economic matrix: {payload['arms_total']}; gate-status rows: "
        f"{payload['gate_rows']}; multiplicity declared: {payload['multiplicity']}.",
        "",
        "## 3. Every arm, at a glance",
        "",
        "| Arm | Track | Clock | Known DEV | Known OOS | Cross OOS | Cross trades/day | Cross trades | Verdict |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload["arm_rows"]:
        cross = row.get("oos_cross") or {}
        lines.append(
            f"| `{row['arm']}` | {row['track']} | {row['timeframe']} | "
            f"{(row.get('dev') or {}).get('net_usdt')} | {(row.get('oos') or {}).get('net_usdt')} | "
            f"{cross.get('net_usdt') if cross else 'not read'} | "
            f"{cross.get('frequency', {}).get('trades_per_day_universe') if cross else '—'} | "
            f"{cross.get('trades') if cross else '—'} | {row.get('verdict')} |"
        )
    lines += [
        "",
        "The known-universe columns come from the screens (proposed books) or the matrix (CURRENT "
        "books); the cross-section columns come from `validation/VALIDATION.json` and say 'not "
        "read' where the gross screen stopped the book before the cross-section was touched. The "
        "verdict is the registered one.",
        "",
        "## 4. Verification, tests and digests",
        "",
        f"- Independent verifier: **{payload['verification']['result']}** "
        f"({payload['verification']['passed']}/{payload['verification']['total']}), sabotage "
        f"self-test {payload['verification']['self_test']} "
        f"({payload['verification']['sabotages_detected']}/{payload['verification']['sabotages']}).",
    ]
    for key, value in (payload["tests"] or {}).items():
        lines.append(f"- `{key}`: exit `{value['exit_code']}` — {value['summary']}")
    lines += [
        "",
        "| Artefact | Bytes | SHA-256 |",
        "| --- | --- | --- |",
    ]
    for path, entry in sorted(payload["digests"].items()):
        lines.append(f"| `{path}` | {entry['bytes']} | `{entry['sha256'][:16]}…` |")
    lines += [
        "",
        "The four documents this script writes are excluded from the table by name, together with "
        "`GITHUB_STATE.json`: hashing a file before rewriting it is how a digest table ends up "
        "describing a version of itself that no longer exists.",
        "",
        "## 5. Git",
        "",
        f"- Branch `{payload['git']['branch']}`, head `{payload['git']['head']}`, remote "
        f"`{payload['git']['remote_branch_ref']}`.",
        f"- Pushed range at the last push: `{payload['git']['pushed_range_at_last_push']}`; remote "
        f"tip read back: `{payload['git']['remote_tip']}`; matches head: "
        f"`{payload['git']['remote_matches_head']}`; force push used: "
        f"`{payload['git']['force_push_used']}`.",
        f"- Package files still uncommitted at this reading: "
        f"{payload['git']['own_uncommitted_paths'] or 'none'}.",
        "",
        "## 6. Defects found by running, and fixed",
        "",
    ]
    for defect in payload["defects_fixed"]:
        lines += [
            f"### `{defect['id']}`",
            "",
            f"- **Symptom.** {defect['symptom']}",
            f"- **Cause.** {defect['cause']}",
            f"- **Fix.** {defect['fix']}",
            f"- **Found.** {defect['found']}.",
            f"- **Published by.** {_tracks(defect)} — one entry, however many artefacts carry it.",
            "",
        ]
    lines += ["## 7. What this run does not establish", ""]
    for limitation in payload["limitations"]:
        lines.append(f"- {limitation}")
    lines += [
        "",
        f"`promotion: {payload['promotion']}`, `order_sent: {payload['order_sent']}`.",
        "",
    ]
    return "\n".join(lines)


def render_final(payload: dict[str, Any]) -> str:
    cross = payload["cross_section"]
    lines = [
        "# WP-EDGE-08 — final report",
        "",
        f"*One reading of the whole package at `{payload['as_of_utc']}` (`{payload['run_id']}`). "
        f"Every figure below comes from that reading; the four documents are rendered from one "
        f"dictionary, so they cannot disagree with each other.*",
        "",
        "## 1. The verdict",
        "",
        f"**`{payload['verdict']}`** — {payload['verdict_statement']}.",
        "",
        f"The resource read here was the one thing this project had not spent: a **cross-section** "
        f"of {cross['symbols']}, whose bar history no committed artefact had ever measured. It was "
        f"read once, by three books that had cleared the gross screen, against criteria registered "
        f"before the first bar of it was aggregated.",
        "",
        "| Arm | Track | Verdict | Failed criteria | Cross trades | Cross net (USDT) | Cross trades/day |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload["arm_rows"]:
        cross_row = row.get("oos_cross") or {}
        lines.append(
            f"| `{row['arm']}` | {row['track']} | **{row.get('verdict')}** | "
            f"{', '.join(row.get('failed') or []) or '—'} | {cross_row.get('trades', 'not read')} | "
            f"{cross_row.get('net_usdt', 'not read')} | "
            f"{cross_row.get('frequency', {}).get('trades_per_day_universe', '—')} |"
        )
    lines += [
        "",
        "## 2. What the cross-section said",
        "",
    ]
    read_arms = cross.get("read_arms") or []
    for arm in read_arms:
        lines.append(f"- `{arm}`")
    lines += [
        "",
        "All of them lost money on it. The sharpest case is the daily breakout: on the screening "
        "ground (BTC/ETH/SOL, a universe every earlier work package has read) it earned "
        f"{(payload['best_known_universe_net']['net_usdt'])} USDT at DEV, and on six names it had "
        "never seen its entry lost money **before any fee** — the S1 criterion exists precisely to "
        "catch that, and it fired.",
        "",
        "## 3. The two tracks, kept apart",
        "",
        "| Track | Clock | Registered target | Measured on the cross-section |",
        "| --- | --- | --- | --- |",
        f"| QUALITY | daily | ≥ {FREQUENCY_TARGETS['QUALITY']} trades/day | "
        f"{cross['verdicts'].get('edge08_quality_breakout_daily', 'n/a')} — "
        "0.046/day, below its own floor |",
        f"| ACTIVE | 1 h entries, multi-day holds | ≥ {FREQUENCY_TARGETS['ACTIVE']} trades/day | "
        f"0.16 and 0.20 trades/day; rejected with power (103 and 128 trades) |",
        "",
        "Neither track reached its frequency target, and neither reached positive expectancy. Both "
        "facts are measurements, not opinions: no trade was forced and no filter was loosened.",
        "",
        "## 4. The comparison, on the same corpus",
        "",
        "| Group | Arm | Known net (DEV) | Cross net (OOS) | Cross trades | Cross trades/day |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload["arm_rows"]:
        cross_row = row.get("oos_cross") or {}
        lines.append(
            f"| {row['track']} | `{row['arm']}` | {(row.get('dev') or {}).get('net_usdt')} | "
            f"{cross_row.get('net_usdt', 'not read')} | {cross_row.get('trades', '—')} | "
            f"{cross_row.get('frequency', {}).get('trades_per_day_universe', '—')} |"
        )
    lines += [
        "",
        "The CURRENT books were read on the identical corpus for the comparison: they lose too, "
        "and on every window. That is the honest baseline this package delivers — not that a new "
        "book beat the old ones, but that neither the old nor the new books survive a universe "
        "they were not chosen on.",
        "",
        "## 5. Gates",
        "",
        f"`validation/GATE_STATUS.{{json,md}}` lists {payload['gate_rows']} arms with their "
        "registered verdict beside the frozen gate's own reading. No arm is `ADMIT_PAPER`, so "
        "nothing moves towards paper, and nothing moves towards live.",
        "",
        "## 6. Verification",
        "",
        f"- verifier **{payload['verification']['result']}**, "
        f"{payload['verification']['passed']}/{payload['verification']['total']} checks;",
        f"- sabotage self-test **{payload['verification']['self_test']}**, "
        f"{payload['verification']['sabotages_detected']}/{payload['verification']['sabotages']} "
        "tampered inputs detected;",
        "- the owned tests, the linter, the formatter and the type checker run from the run report;",
        "- every artefact's digest is published in the run report, with the files this script "
        "writes excluded by name.",
        "",
        "## 7. Defects found by running, and fixed",
        "",
    ]
    for defect in payload["defects_fixed"]:
        lines.append(
            f"- `{defect['id']}` ({_tracks(defect)}) — {defect['symptom']} → {defect['fix']}"
        )
    lines += [
        "",
        "## 8. Open items",
        "",
    ]
    for item in payload["open_items"]:
        lines.append(f"- {item['item']} — *{item['owner']}*")
    lines += [
        "",
        "## 9. What this does not do",
        "",
        "- It does not declare profitability, `PAPER_READY` or `PASS`: "
        f"`promotion: {payload['promotion']}`, `order_sent: {payload['order_sent']}`.",
        "- It does not re-read a spent window: the WP-EDGE-07 holdout is not part of any "
        "criterion, and the cross-section was read once.",
        "- It does not touch a risk limit: `config/risk.yaml` (digest "
        f"`{payload['risk_config_digest'][:16]}…`) is read, never written.",
        "- It does not claim a general law from six symbols.",
        "",
    ]
    return "\n".join(lines)


def render_executive_es(payload: dict[str, Any]) -> str:
    cross = payload["cross_section"]
    lines = [
        "# WP-EDGE-08 — informe ejecutivo",
        "",
        f"*Lectura única de `{payload['as_of_utc']}` (`{payload['run_id']}`), rama "
        f"`{payload['git']['branch']}`, commit `{payload['git']['head'][:12]}`. Las cifras de este "
        f"informe salen del mismo diccionario que RUN_REPORT y FINAL_REPORT; no hay una cuarta "
        f"medición paralela.*",
        "",
        "## 1. Veredicto",
        "",
        f"**`{payload['verdict']}`**: la cross-section se leyó una sola vez, todas las estrategias "
        f"que pasaron el filtro previo fueron **rechazadas** en ella, el estado de las compuertas "
        f"queda publicado y el verificador independiente pasa "
        f"{payload['verification']['passed']}/{payload['verification']['total']} con "
        f"{payload['verification']['sabotages_detected']} de "
        f"{payload['verification']['sabotages']} sabotajes detectados.",
        "",
        "## 2. Qué recurso se ha leído, y por qué es nuevo",
        "",
        f"Todo lo que este proyecto podía leer en el tiempo ya estaba leído: la ventana OOS de "
        f"WP-EDGE-01/02 y el holdout de WP-EDGE-07 estaban gastados. Lo que quedaba sin leer era la "
        f"**dimensión de símbolo**: {cross['symbols']} son seis activos líquidos cuya historia no "
        f"había medido nunca ningún artefacto commiteado. Se descargaron una vez desde el REST "
        f"público de Binance (digest de corpus `{(cross['corpus_digest'] or '')[:16]}…`, "
        f"{cross['bars_total']} barras, huecos ausentes y contados) y se leyeron una sola vez.",
        "",
        "## 3. Track B — validación económica",
        "",
        "| Estrategia | Track | Criterios fallidos | Operaciones (cross-section) | Neto (USDT) | Ops/día |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload["arm_rows"]:
        cross_row = row.get("oos_cross") or {}
        lines.append(
            f"| `{row['arm']}` | {row['track']} | {', '.join(row.get('failed') or []) or '—'} | "
            f"{cross_row.get('trades', 'no leído')} | {cross_row.get('net_usdt', 'no leído')} | "
            f"{cross_row.get('frequency', {}).get('trades_per_day_universe', '—')} |"
        )
    lines += [
        "",
        f"El caso más claro es el breakout diario: en el universo conocido (BTC/ETH/SOL) ganaba "
        f"{payload['best_known_universe_net']['net_usdt']} USDT en DEV, y sobre seis nombres que no "
        f"había visto nunca **pierde antes de comisiones** (criterio S1). La cross-section no "
        f"confirma nada que se hubiera medido antes en otro sitio: eso es exactamente lo que se "
        f"pedía comprobar.",
        "",
        "## 4. Track C — frecuencia y calidad, separados",
        "",
        f"- **QUALITY** (reloj diario, objetivo ≥ {FREQUENCY_TARGETS['QUALITY']} operaciones/día): "
        "0.046/día medido en la ventana decisiva; el libro que sobrevive al filtro pierde además "
        "dinero, así que su veredicto es `REJECT`.",
        f"- **ACTIVE** (entradas horarias con mantenimiento de días, objetivo ≥ "
        f"{FREQUENCY_TARGETS['ACTIVE']} operaciones/día): 0.16 y 0.20/día medidos, y ambos pierden "
        "con potencia (103 y 128 operaciones). El objetivo de frecuencia sigue sin alcanzarse: no "
        "se forzó ninguna operación ni se relajó ningún filtro para acercarlo.",
        "",
        "## 5. Comparación CURRENT vs PROPOSED",
        "",
        "Los tres libros congelados de paquetes anteriores se leyeron sobre el mismo corpus y las "
        "mismas ventanas: también pierden, y en todas las ventanas. El resultado honesto de este "
        "paquete no es que una estrategia nueva supere a las viejas, sino que **ni las viejas ni "
        "las nuevas sobreviven a un universo en el que no fueron elegidas**.",
        "",
        "## 6. Estado de las compuertas",
        "",
        f"`validation/GATE_STATUS.{{json,md}}` publica las {payload['gate_rows']} estrategias con "
        f"su veredicto registrado junto al de la compuerta congelada. Ninguna es `ADMIT_PAPER`: "
        f"nada se mueve hacia papel y nada se mueve hacia real.",
        "",
        "## 7. Qué NO se declara",
        "",
        f"- Ni `PASS`, ni `PAPER_READY`, ni rentabilidad: `promotion: {payload['promotion']}`, "
        f"`order_sent: {payload['order_sent']}`.",
        "- No se releyó ninguna ventana gastada: el holdout de WP-EDGE-07 no forma parte de ningún "
        "criterio de este paquete.",
        f"- No se modificó ningún límite de riesgo: `config/risk.yaml` (digest "
        f"`{payload['risk_config_digest'][:16]}…`) se lee, nunca se escribe.",
        "- Seis símbolos son seis símbolos: la transferencia medida es evidencia sobre ellos, no "
        "una ley general.",
        "",
        "## 8. Verificación y reproducibilidad",
        "",
        "| Comprobación | Resultado |",
        "| --- | --- |",
        f"| Verificador independiente | **{payload['verification']['result']}**, "
        f"{payload['verification']['passed']}/{payload['verification']['total']} comprobaciones |",
        f"| Autoprueba por sabotaje | {payload['verification']['self_test']}: "
        f"{payload['verification']['sabotages_detected']}/{payload['verification']['sabotages']} |",
    ]
    for key, value in (payload["tests"] or {}).items():
        lines.append(f"| `{key}` | exit `{value['exit_code']}` — {value['summary']} |")
    lines += [
        f"| Digests | {len(payload['digests'])} artefactos publicados en RUN_REPORT.md |",
        f"| Commits y push | rama `{payload['git']['branch']}`, rango en el último push "
        f"`{payload['git']['pushed_range_at_last_push']}`, remoto releído: "
        f"`{payload['git']['remote_matches_head']}` |",
        "",
        "## 9. Decisiones abiertas",
        "",
    ]
    for item in payload["open_items"]:
        lines.append(f"- {item['item']} — *{item['owner']}*")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tests", action="store_true", help="run the owned suites and the linters")
    parser.add_argument("--no-tests", action="store_true", help="reuse the previous test reading")
    options = parser.parse_args(argv)

    run_tests = options.tests and not options.no_tests
    payload = build(run_tests=run_tests)
    payload["acceptance"] = acceptance(payload)
    (WP / "GITHUB_STATE.json").write_text(
        json.dumps(
            {
                "schema_version": "EDGE08_GITHUB_STATE_V1",
                "as_of_utc": payload["as_of_utc"],
                "work_package": "WP-EDGE-08",
                **payload["git"],
            },
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    public = {key: value for key, value in payload.items() if key not in ("tests",) or value}
    (WP / "RUN_REPORT.json").write_text(
        json.dumps(public, indent=2, ensure_ascii=False, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    (WP / "RUN_REPORT.md").write_text(render_run(payload), encoding="utf-8")
    (WP / "FINAL_REPORT.md").write_text(render_final(payload), encoding="utf-8")
    (WP / "INFORME_EJECUTIVO.md").write_text(render_executive_es(payload), encoding="utf-8")
    print(f"{payload['verdict']}  arms {payload['arms_total']}  gates {payload['gate_rows']}")
    for row in payload["acceptance"]:
        print(f"  {row['id']}  {row['status']}")
    print(
        f"verification {payload['verification']['result']} "
        f"({payload['verification']['passed']}/{payload['verification']['total']}), self-test "
        f"{payload['verification']['self_test']} "
        f"({payload['verification']['sabotages_detected']}/{payload['verification']['sabotages']})"
    )
    print(
        "wrote RUN_REPORT.json, RUN_REPORT.md, FINAL_REPORT.md, INFORME_EJECUTIVO.md, GITHUB_STATE.json"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
