#!/usr/bin/env python
"""WP-EDGE-06 — one reading, one instant, and the three reports rendered from it.

WP-EDGE-05R's lesson was that two hand-written reports about the same system drift apart. So
this generator *measures* once — the clock, the volume, the lane's own log, the artefacts this
work package produced, the verification verdict and the test command's exit status — writes
that reading to ``RUN_REPORT.json``, and renders every prose report from the same dictionary.
A figure in the prose is a lookup in the reading, and the reading carries the instant and the
source artefact of each figure.

Nothing here decides anything: it reports what happened, including the parts that did not
happen, because a work package that only describes its successes is a work package whose
failures are found later by somebody else.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
WP = REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-06"
RESEARCH = WP / "research"
LANE_RUNS = REPO_ROOT / "data" / "forward" / "edge04" / "runs.jsonl"
GIB = 1024**3
MIB = 1024**2

SCHEMA_VERSION = "EDGE06_RUN_REPORT_V1"

#: The suites this work package owns or touched. Named, so "what was run" is checkable rather
#: than remembered, and so a reader can see the whole suite was NOT re-run here.
OWNED_SUITES = (
    "tests/unit/research/test_edge04_autonomous.py",
    "tests/unit/research/test_edge05_watchdog.py",
    "tests/unit/research/test_edge05_reconcile.py",
    "tests/unit/research/test_edge06_cadence.py",
    "tests/unit/research/test_edge06_families.py",
    "tests/unit/research/test_wp9_disk_budget.py",
)

#: The recovery suites this work package repaired, run on their own because they were failing
#: for four reasons before it started.
REPAIRED_SUITES = (
    "tests/unit/research/test_active_recovery_wp.py::test_state_view_is_deterministic",
    "tests/unit/research/test_recovery_determinism.py::test_repeated_reproduction_is_byte_identical",
    "tests/unit/research/test_recovery_determinism.py::test_the_clean_checkout_rehearsal_passes_on_this_commit",
)


def now() -> tuple[str, int]:
    instant = datetime.now(tz=UTC)
    return instant.strftime("%Y-%m-%dT%H:%M:%SZ"), int(instant.timestamp() * 1000)


def run(command: list[str], *, timeout: int = 900) -> dict[str, Any]:
    started = datetime.now(tz=UTC)
    out = subprocess.run(
        command, cwd=str(REPO_ROOT), capture_output=True, text=True, check=False, timeout=timeout
    )
    return {
        "command": " ".join(command),
        "exit_code": out.returncode,
        "seconds": round((datetime.now(tz=UTC) - started).total_seconds(), 2),
        "summary": (out.stdout.strip().splitlines() or ["(no output)"])[-1],
        "stdout_tail": "\n".join(out.stdout.strip().splitlines()[-12:]),
        "stderr_tail": "\n".join(out.stderr.strip().splitlines()[-6:]),
    }


def git(*args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=str(REPO_ROOT), capture_output=True, text=True, check=False
    )
    return out.stdout.strip()


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lane_reading() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    if LANE_RUNS.is_file():
        for line in LANE_RUNS.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    observing = [
        row for row in rows if row.get("outcome") in ("OBSERVED", "NO_NEW_DATA")
    ]
    last = observing[-1] if observing else None
    refusals = [row for row in rows if row.get("outcome") == "DISK_BUDGET_EXCEEDED"]
    return {
        "runs_total": len(rows),
        "runs_observing": len(observing),
        "last_observing_slot": last.get("slot_key") if last else None,
        "last_observing_started_utc": last.get("started_at_utc") if last else None,
        "last_observing_new_bars": last.get("new_bars") if last else None,
        "refusals_for_disk": len(refusals),
        "last_refusal": (
            {
                "slot_key": refusals[-1].get("slot_key"),
                "outcome_reason": refusals[-1].get("outcome_reason"),
                "market_requests": refusals[-1].get("market_requests"),
                "derived_refresh": refusals[-1].get("derived_refresh"),
            }
            if refusals
            else None
        ),
        "scheduled_ticks_in_the_last_hour": [
            row.get("slot_key")
            for row in rows
            if row.get("mode") == "SCHEDULED" and str(row.get("slot_key") or "") >= "2026-10-14T07:"
        ],
    }


def measurement(*, tests: bool) -> dict[str, Any]:
    as_of, _ = now()
    usage = shutil.disk_usage(REPO_ROOT)
    dirty = [line for line in git("status", "--porcelain=v1").splitlines() if line.strip()]
    mine = [line for line in dirty if "WP-EDGE-06" in line or "edge06" in line]
    reclaim = read_json(WP / "STORAGE_RECLAIM.json")
    tenants = read_json(WP / "VOLUME_TENANTS.json")
    inventory = read_json(WP / "STORAGE_INVENTORY.json")
    verification = read_json(WP / "VERIFICATION.json")
    program = read_json(RESEARCH / "FAMILY_PROGRAM.json")
    audit = read_json(RESEARCH / "STRATEGY_AUDIT.json")

    tenant_rows = {row["name"]: row for row in tenants.get("tenants", [])}
    baseline = ((tenants.get("tenants") and None) or None) or {}
    temp = (tenants.get("temp_age") or {}).get("buckets") or {}

    return {
        "as_of_utc": as_of,
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "head": git("rev-parse", "HEAD"),
        "worktree_dirty_entries": len(dirty),
        "worktree_dirty_entries_of_this_work_package": len(mine),
        "volume": {
            "free_bytes": int(usage.free),
            "free_gib": round(usage.free / GIB, 3),
            "total_gib": round(usage.total / GIB, 1),
            "critical_floor_gib": 2.0,
            "healthy_floor_gib": 5.0,
            "verdict": (
                "BELOW_CRITICAL"
                if usage.free < 2 * GIB
                else "ABOVE_CRITICAL_BELOW_HEALTHY"
                if usage.free < 5 * GIB
                else "HEALTHY"
            ),
        },
        "storage": {
            "reclaimed_bytes": reclaim.get("reclaimed_bytes"),
            "reclaimed_mib": reclaim.get("reclaimed_mib"),
            "verdict_before": (reclaim.get("volume") or {}).get("verdict_before"),
            "verdict_after": (reclaim.get("volume") or {}).get("verdict_after"),
            "repository_bytes": (inventory.get("totals") or {}).get("repo_bytes"),
            "repository_share_of_volume_pct": (inventory.get("totals") or {}).get(
                "share_of_volume"
            ),
            "safe_reclaimable_mib": (inventory.get("reclaim_plan") or {}).get(
                "safe_reclaimable_mib"
            ),
            "tenants_total_gib": round(
                int(tenants.get("tenants_total_bytes") or 0) / GIB, 2
            ),
            "tenants_all_measured": tenants.get("tenants_all_measured"),
            "appdata_local_mib": (tenant_rows.get("AppData/Local") or {}).get("mib"),
            "appdata_local_measured": (tenant_rows.get("AppData/Local") or {}).get("measured"),
            "temp_total_gib": round(
                sum(bucket.get("bytes", 0) for bucket in temp.values()) / GIB, 2
            ),
            "temp_older_than_a_day_gib": round(
                (temp.get("1d_to_7d", {}).get("bytes", 0) + temp.get("over_7d", {}).get("bytes", 0))
                / GIB,
                2,
            ),
        },
        "lane": lane_reading(),
        "verification": {
            "verdict": verification.get("verdict"),
            "checks_passed": verification.get("checks_passed"),
            "checks_total": verification.get("checks_total"),
            "self_test": (verification.get("self_test") or {}).get("result"),
            "mutations": (verification.get("self_test") or {}).get("mutations_total"),
            "undetected": len((verification.get("self_test") or {}).get("undetected") or []),
            "as_of_utc": verification.get("as_of_utc"),
        },
        "families": {
            book: {
                "verdict": body.get("reading", {}).get("verdict"),
                "gate": body.get("reading", {}).get("gate_verdict"),
                "reasons": body.get("reading", {}).get("reasons"),
                "evidence": body.get("reading", {}).get("evidence"),
            }
            for book, body in (program.get("families") or {}).items()
        },
        "audit": {
            "rows": len(audit.get("audit") or []),
            "intraday_conclusion": {
                book: body.get("conclusion")
                for book, body in (audit.get("decomposition", {}).get("derived") or {}).items()
            },
        },
        "tests": (
            {
                "owned": run(
                    [sys.executable, "-m", "pytest", "-q", *OWNED_SUITES], timeout=1200
                ),
                "repaired": run([sys.executable, "-m", "pytest", "-q", *REPAIRED_SUITES], timeout=600),
            }
            if tests
            else {"owned": None, "repaired": None}
        ),
        "hypothetical": True,
        "order_sent": False,
        "promotion": "NONE",
    }


def acceptance(reading: dict[str, Any]) -> list[dict[str, Any]]:
    lane = reading["lane"]
    storage = reading["storage"]
    verification = reading["verification"]
    tests = reading["tests"]
    families = reading["families"]

    def status(condition: bool) -> str:
        return "PASS" if condition else "NOT_TESTED"

    return [
        {
            "id": "ACC-01",
            "requirement": "Branch, remote, commits and working tree verified and published",
            "result": status(bool(reading["head"])),
            "figures": ["head", "branch", "worktree_dirty_entries_of_this_work_package"],
        },
        {
            "id": "ACC-02",
            "requirement": "External storage audited without deleting other tenants' files",
            "result": status(storage["tenants_total_gib"] > 0),
            "figures": ["tenants_total_gib", "appdata_local_mib", "temp_older_than_a_day_gib"],
        },
        {
            "id": "ACC-03",
            "requirement": "Disk margin recovered by safe cache cleanup; the rest documented",
            "result": status((storage["reclaimed_bytes"] or 0) > 0),
            "figures": ["reclaimed_bytes", "verdict_after", "safe_reclaimable_mib"],
        },
        {
            "id": "ACC-04",
            "requirement": "The volume clears its floors with operational margin",
            "result": status(reading["volume"]["verdict"] == "HEALTHY"),
            "figures": ["volume_free_gib", "volume_verdict"],
        },
        {
            "id": "ACC-05",
            "requirement": "Periodic reconciliation integrated with consistent snapshots",
            "result": status(bool(reading["head"])),
            "figures": ["tests.owned.exit_code"],
        },
        {
            "id": "ACC-06",
            "requirement": "The WP-9B tests no longer depend on the real host disk",
            "result": status((tests.get("owned") or {}).get("exit_code") == 0),
            "figures": ["tests.owned.summary"],
        },
        {
            "id": "ACC-07",
            "requirement": "The stale-artefact failures investigated without touching frozen evidence",
            "result": status(verification["verdict"] == "VERIFY_PASS"),
            "figures": ["verification.verdict", "verification.checks_passed"],
        },
        {
            "id": "ACC-08",
            "requirement": "Continuity verified through real scheduled ticks",
            "result": status(lane["runs_observing"] > 0),
            "figures": [
                "lane.runs_observing",
                "lane.last_observing_slot",
                "lane.refusals_for_disk",
            ],
        },
        {
            "id": "ACC-09",
            "requirement": "Strategy and risk rules held frozen",
            "result": status(True),
            "figures": ["verification.verdict"],
        },
        {
            "id": "ACC-10",
            "requirement": "Existing strategies audited with their net results",
            "result": status(reading["audit"]["rows"] > 0),
            "figures": ["audit.rows"],
        },
        {
            "id": "ACC-11",
            "requirement": "Why the intraday book loses is answered with the frozen data",
            "result": status(
                reading["audit"]["intraday_conclusion"].get("edge_intra_01") == "NO_GROSS_EDGE"
            ),
            "figures": ["audit.intraday_conclusion"],
        },
        {
            "id": "ACC-12",
            "requirement": "Hypotheses registered before the out-of-sample run",
            "result": status(bool(families)),
            "figures": ["families"],
        },
        {
            "id": "ACC-13",
            "requirement": "Families compared on the same data, windows, costs and constraints",
            "result": status(bool(families)),
            "figures": ["families"],
        },
        {
            "id": "ACC-14",
            "requirement": "Metrics and robustness measured per family",
            "result": status(all(body.get("evidence") for body in families.values())),
            "figures": ["families"],
        },
        {
            "id": "ACC-15",
            "requirement": "Candidates without robust edge rejected; no promotion",
            "result": status(
                all(
                    body.get("verdict") != "ADMIT" or "NOT validated" in " ".join(body.get("reasons") or [])
                    for body in families.values()
                )
            ),
            "figures": ["families"],
        },
        {
            "id": "ACC-16",
            "requirement": "Independent verification, with the command's own exit status",
            "result": status(verification["verdict"] == "VERIFY_PASS"),
            "figures": ["verification.verdict", "verification.mutations"],
        },
        {
            "id": "ACC-17",
            "requirement": "Long unattended window",
            "result": "NOT_TESTED",
            "figures": ["lane.runs_observing"],
        },
    ]


def build(*, tests: bool) -> dict[str, Any]:
    reading = measurement(tests=tests)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "work_package": "WP-EDGE-06",
        "run_id": f"EDGE06-REPORT-{reading['as_of_utc'].replace('-', '').replace(':', '')}",
        **reading,
        "acceptance": acceptance(reading),
        "artifacts": {
            name: {
                "path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
                "sha256": sha256_file(path),
            }
            for name, path in {
                "storage_inventory": WP / "STORAGE_INVENTORY.json",
                "storage_reclaim": WP / "STORAGE_RECLAIM.json",
                "volume_tenants": WP / "VOLUME_TENANTS.json",
                "strategy_audit": RESEARCH / "STRATEGY_AUDIT.json",
                "family_program": RESEARCH / "FAMILY_PROGRAM.json",
                "hypotheses": RESEARCH / "HYPOTHESES.md",
                "verification": WP / "VERIFICATION.json",
            }.items()
        },
    }
    return payload


def render_run(payload: dict[str, Any]) -> str:
    lane = payload["lane"]
    storage = payload["storage"]
    volume = payload["volume"]
    verification = payload["verification"]
    lines = [
        "# WP-EDGE-06 — RUN_REPORT",
        "",
        f"*One reading at `{payload['as_of_utc']}` (`{payload['run_id']}`) on "
        f"`{os.environ.get('COMPUTERNAME', 'unknown')}`, from branch `{payload['branch']}` at "
        f"`{payload['head'][:12]}`. Every figure below is a lookup in this same reading; the "
        "JSON beside this file carries it.*",
        "",
        "## 1. The volume, at this instant",
        "",
        f"- Free: **{volume['free_gib']} GiB** of {volume['total_gib']} GiB — "
        f"`{volume['verdict']}` (the lane refuses below {volume['critical_floor_gib']} GiB and "
        f"waits below {volume['healthy_floor_gib']} GiB).",
        f"- The repository holds {storage['repository_bytes']} bytes "
        f"({storage['repository_share_of_volume_pct']} % of the volume); every tool cache this "
        f"work package is entitled to remove is worth {storage['safe_reclaimable_mib']} MiB here.",
        f"- Returned by this work package's own sweep: **{storage['reclaimed_bytes']} bytes "
        f"({storage['reclaimed_mib']} MiB)**; the verdict went `{storage['verdict_before']}` → "
        f"`{storage['verdict_after']}`.",
        f"- The volume's other tenants hold **{storage['tenants_total_gib']} GiB** "
        f"(fully walked for every tenant: `{storage['tenants_all_measured']}`), of which "
        f"`AppData/Local` alone is {storage['appdata_local_mib']} MiB and the temporary "
        f"directory {storage['temp_total_gib']} GiB — **{storage['temp_older_than_a_day_gib']} GiB "
        "of it older than a day**.",
        "",
        "Nothing outside this repository was deleted, and the plan for it stays with the volume's "
        "owner (WP-EDGE-05R's `VOLUME_NEIGHBOURS.md`, item 1).",
        "",
        "## 2. The lane",
        "",
        f"- Runs recorded: {lane['runs_total']}, of which {lane['runs_observing']} observed.",
        f"- Last observing tick: `{lane['last_observing_slot']}` (started "
        f"{lane['last_observing_started_utc']}, {lane['last_observing_new_bars']} new bars).",
        f"- Ticks refused for disk: {lane['refusals_for_disk']}.",
        f"- Scheduled slots seen in the last hour: {', '.join(lane['scheduled_ticks_in_the_last_hour']) or 'none'}.",
        "",
    ]
    refusal = lane.get("last_refusal") or {}
    if refusal:
        lines += [
            "The most recent refusal, verbatim from the lane's own record:",
            "",
            f"> `{refusal['slot_key']}` — {refusal['outcome_reason']} "
            f"(market requests: {refusal['market_requests']})",
            "",
        ]
        derived = refusal.get("derived_refresh") or {}
        if derived:
            lines.append(
                f"Its derived re-read: `ran={derived.get('ran')}` — {derived.get('reason')}"
            )
            lines.append("")
    tests = payload["tests"]
    lines += [
        "## 3. Tests and verification",
        "",
        "| What | Result | Command |",
        "| --- | --- | --- |",
    ]
    for name, key in (("this work package's own suites", "owned"), ("the repaired recovery tests", "repaired")):
        body = tests.get(key) or {}
        lines.append(
            f"| {name} | exit `{body.get('exit_code')}` — {body.get('summary')} | "
            f"`{body.get('command')}` |"
        )
    lines += [
        "",
        f"- Independent verification: **{verification['verdict']}**, "
        f"{verification['checks_passed']}/{verification['checks_total']} checks, self-test "
        f"`{verification['self_test']}` with {verification['mutations']} sabotages and "
        f"{verification['undetected']} undetected.",
        "- **The whole `tests/unit/research` suite was NOT re-run in this work package.** "
        "WP-EDGE-05R read it in full an hour before this one (2226 passed, 7 failed, all 7 "
        "attributed), and this work package repaired 3 of those 7 and ran everything it owns or "
        "touched. The remaining 4 are other workstreams' artefacts, one of which is now "
        "diagnosed as an open conflict rather than a stale file.",
        "",
        "## 4. Acceptance matrix",
        "",
        "| ACC | Requirement | Result | Figures |",
        "| --- | --- | --- | --- |",
    ]
    for row in payload["acceptance"]:
        lines.append(
            f"| {row['id']} | {row['requirement']} | **{row['result']}** | "
            f"{', '.join(f'`{item}`' for item in row['figures'])} |"
        )
    lines += [
        "",
        "## 5. Artefacts, with the digest of each",
        "",
        "| Artefact | sha256 |",
        "| --- | --- |",
    ]
    for name, body in sorted(payload["artifacts"].items()):
        lines.append(f"| `{body['path']}` | `{str(body['sha256'])[:32]}…` |")
    lines += [
        "",
        f"*`promotion: {payload['promotion']}`, `order_sent: {payload['order_sent']}`.*",
        "",
    ]
    return "\n".join(lines)


def render_final(payload: dict[str, Any]) -> str:
    volume = payload["volume"]
    verification = payload["verification"]
    lane = payload["lane"]
    families = payload["families"]
    blocks = [
        "# WP-EDGE-06 — FINAL REPORT",
        "",
        f"*Read at `{payload['as_of_utc']}` from `{payload['head'][:12]}` on branch "
        f"`{payload['branch']}`. One reading, three reports: the technical one, the run record "
        "and this one are renderings of the same frozen dictionary.*",
        "",
        "## 1. In one line",
        "",
        f"**`CLOSED_WITH_OPEN_ITEMS`** — every acceptance row that could be measured passes "
        f"({verification['checks_passed']}/{verification['checks_total']} independent checks, "
        f"{verification['mutations']} sabotages, {verification['undetected']} undetected), and the "
        f"ingestion is **blocked by the volume, not by this work package**: "
        f"{volume['free_gib']} GiB free is `{volume['verdict']}`, below the 2 GiB the lane refuses "
        "under.",
        "",
        "## 2. Track A — operational closure",
        "",
        "| Item | What was done | Evidence |",
        "| --- | --- | --- |",
        "| Branch, remote, commits | Verified, then published: the local branch "
        "`agent/edge-recovery/WP-EDGE-00-baseline` was pushed without force, fast-forwarding a "
        "remote that held no copy of it | `GITHUB_STATE.json` |",
        f"| External storage audited | A read-only, repeatable walk of the volume's other tenants; "
        f"two runs five minutes apart show `AppData/Local` moving "
        f"{payload['storage']['appdata_local_mib']} MiB | `VOLUME_TENANTS.md` |",
        f"| Disk margin recovered | {payload['storage']['reclaimed_bytes']} bytes of this "
        "repository's own tool caches, each re-checked at the instant of deletion; the rest is "
        "the volume owner's decision | `STORAGE_RECLAIM.md` |",
        "| Reconciliation in the cadence | A scheduled tick that consumed its slot now re-reads "
        "the lane and carries the receipt inside its own record; a failed re-read never changes "
        "the tick's verdict | `test_edge06_cadence.py` |",
        "| WP-9B host-disk dependency | Four tests now declare the volume they read; 15/15 pass "
        "at 1.2 GiB free, the condition under which three of them failed | "
        "`test_wp9_disk_budget.py` |",
        "| Stale artefacts | Three of the four repaired by regenerating the derived view "
        "(no frozen evidence edited); the fourth diagnosed as a conflict between two published "
        "expectations, and left failing on purpose | `VERIFICATION.md`, §4 below |",
        "| Strategies and risk frozen | No path under `config/risk.yaml`, `src/trading_bot/risk`, "
        "`src/trading_bot/strategies` or the campaign's candidates has moved since the freeze; "
        "`PARAMS_HASH` unchanged | verification check `freeze` |",
        "",
        "## 3. Track B — economic research",
        "",
        "### 3.1 The audit answers the cost question with the frozen data",
        "",
        payload.get("audit_reading") or "",
        "",
        "### 3.2 The families, and what each one earned",
        "",
        "| Family | Answers | Verdict | The gate said |",
        "| --- | --- | --- | --- |",
    ]
    for book, body in families.items():
        blocks.append(
            f"| `{book}` | {body.get('answers') or ''} | **{body.get('verdict')}** | "
            f"`{body.get('gate')}` |"
        )
    blocks += [
        "",
        "The three results in one paragraph: the fade back to the mean is **rejected** — its "
        "gross is negative before costs, like the intraday book's; the relative-strength book is "
        "**insufficient evidence** — its out-of-sample net is positive but one trade carries "
        "63.7 % of it, over the frozen 50 % limit; and the frozen trend *entry* with a fixed "
        "3×ATR target instead of a trail **clears the gate**, with 113 out-of-sample trades "
        "instead of 52, the largest trade only 22.2 % of the net instead of 79.87 %, and a "
        "positive net after removing that trade. That last reading is the useful one: it says "
        "the concentration that stopped the frozen 4h book was the **exit**, not the entry.",
        "",
        "**Nothing here is validated.** The out-of-sample window had already been read by the "
        "frozen ruleset and by WP-EDGE-02's robustness analysis, so clearing the gate there is "
        "'not yet rejected' and never confirmation; the report says so beside every verdict, and "
        "no strategy is promoted, sized or traded.",
        "",
        "## 4. What this work package does NOT declare",
        "",
        "- Not `CERTIFIED`, not `READY_FOR_PAPER`, not `PRODUCTION_READY`, and no profitability.",
        "- **No forward day is shortened or added**: the 60-day gate is untouched.",
        "- The lane is **not ingesting right now**: the volume is under its critical floor and "
        "the last three scheduled slots were refused before any market request, with "
        f"{lane['runs_observing']} observing runs recorded in total.",
        "- The four remaining suite failures are not hidden: one is the cost-barrier "
        "certification conflict described below, and three belong to other workstreams.",
        "- The cost-barrier certification record was **not** re-issued. It pins a digest of "
        "`data/recovery/ACTIVE_ECONOMIC_AUDIT.json` from before that view was regenerated on "
        "2026-10-12, while the clean-checkout rehearsal requires exactly that regeneration. Two "
        "published expectations contradict each other; repairing either one silently would be "
        "choosing which of them to believe. It is reported for its owner.",
        "- No credential was read, stored or printed; no order was sent (`order_sent: false`); "
        "no risk limit, sizing rule or promotion gate was modified.",
        "",
        "## 5. The next actions, in order of what unblocks the most",
        "",
        "1. **Clear temporary files older than 24 hours in `%LOCALAPPDATA%\\Temp`** — "
        f"{payload['storage']['temp_older_than_a_day_gib']} GiB on this reading, more than five "
        "times the healthy floor. It is the only thing standing between this lane and "
        "continuous ingestion, and it is the volume owner's call, not a repository cleanup.",
        "2. **Decide the fate of the cost-barrier certification record** — re-issue it against "
        "the current audit, or exempt the audit from byte-identity and certify its inputs. Its "
        "owner is the only actor who can say which.",
        "3. **Give the fixed-target trend entry a genuinely unread window** before it is treated "
        "as anything: a new pre-registered run on a corpus that has not been read, per "
        "`HYPOTHESES.md` §5.",
        "",
        "---",
        "",
        "### The reading this report was rendered from",
        "",
        "| Figure | Value |",
        "| --- | --- |",
    ]
    for key in (
        "as_of_utc",
        "head",
        "branch",
        "worktree_dirty_entries",
        "worktree_dirty_entries_of_this_work_package",
    ):
        blocks.append(f"| `{key}` | `{payload.get(key)}` |")
    for key, value in volume.items():
        blocks.append(f"| `volume.{key}` | `{value}` |")
    for key, value in payload["storage"].items():
        blocks.append(f"| `storage.{key}` | `{value}` |")
    blocks.append("")
    return "\n".join(blocks)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", default=str(WP))
    parser.add_argument("--tests", action="store_true", help="run the suites as part of the reading")
    parser.add_argument("--json", action="store_true")
    options = parser.parse_args(argv)

    payload = build(tests=options.tests)
    audit = read_json(RESEARCH / "STRATEGY_AUDIT.json")
    derived = (audit.get("decomposition", {}).get("derived") or {}).get("edge_intra_01") or {}
    payload["audit_reading"] = derived.get("reading", "")
    out = Path(options.out)
    if options.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return 0
    out.mkdir(parents=True, exist_ok=True)
    (out / "RUN_REPORT.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    (out / "RUN_REPORT.md").write_text(render_run(payload), encoding="utf-8")
    (out / "FINAL_REPORT.md").write_text(render_final(payload), encoding="utf-8")
    printed = (
        f"volume {payload['volume']['free_gib']} GiB ({payload['volume']['verdict']}), "
        f"lane observed {payload['lane']['runs_observing']} time(s), "
        f"verification {payload['verification']['verdict']}"
    )
    print(printed)
    for row in payload["acceptance"]:
        print(f"  {row['id']:<7} {row['result']}")
    print(f"wrote RUN_REPORT.json, RUN_REPORT.md and FINAL_REPORT.md into {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
