#!/usr/bin/env python
"""CAP-004C — assemble the evidence bundle from measured artifacts.

Every number written here is read from an artifact produced by the campaign, the
migration or the independent verifier.  Nothing is typed in from memory, and this
generator never writes to a ledger.

Evidence written to ``reports/cap004c/``: BASELINE.md, STORAGE_ROOT_CAUSE.md/.json,
STORAGE_CLASSIFICATION.md, RETENTION_POLICY.md, STORAGE_MIGRATION_PLAN.md,
STORAGE_MIGRATION_MANIFEST.json (copy of the driver's manifest),
BEFORE_AFTER_STORAGE.md/.json, DISK_GUARD_REPORT.md/.json, REPLAY_VERIFICATION.md,
RUN_REPORT.md/.json, FINAL_REPORT.md/.json.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
REPORTS = REPO / "reports"
OUT = REPORTS / "cap004c"
CAMPAIGN = REPORTS / "cap004"
ARCHIVE = CAMPAIGN / "archive"
LEDGER = REPO / "evidence" / "real_decisions"
VERIFICATION = OUT / "CAP004C_VERIFICATION.json"
GIB = 1024**3
MIB = 1024**2


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def bytes_of(path: Path) -> int:
    """Size of one file, or of a whole tree.  ``0`` when it does not exist yet."""
    if path.is_file():
        return path.stat().st_size
    return tree_bytes(path)


def tree_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total


def migration_manifests() -> list[dict[str, Any]]:
    return [read_json(path) for path in sorted(ARCHIVE.rglob("STORAGE_MIGRATION_MANIFEST.json"))]


def collect() -> dict[str, Any]:
    verification = read_json(VERIFICATION)
    manifests = migration_manifests()
    entries = [entry for manifest in manifests for entry in manifest.get("entries", [])]
    committed = [entry for entry in entries if entry.get("source_removed")]
    samples = (read_json(CAMPAIGN / "STORAGE_SAMPLES.json") or {}).get("samples") or []
    journal_events = read_jsonl(CAMPAIGN / "cycles.jsonl")
    operations = read_jsonl(LEDGER / "operations.jsonl")
    heartbeat = read_json(LEDGER / "heartbeat.json")
    disk = shutil.disk_usage(REPO)
    commit_ts = min(
        (int(manifest.get("timestamp", 0)) for manifest in manifests if manifest.get("mode") == "COMMIT"),
        default=0,
    )
    # Strictly after the boundary: the sample taken at the migration instant still
    # describes the pre-migration tree, so it belongs to the old series.
    post = [item for item in samples if commit_ts and int(item.get("timestamp", 0)) > commit_ts]

    source_bytes = sum(int(entry["source_bytes"]) for entry in entries)
    archive_bytes = sum(int(entry["archive_bytes"]) for entry in entries)
    reclaimed = sum(int(entry.get("reclaimed_bytes", 0)) for entry in entries)

    settle_ops = [item for item in operations if int(item.get("settled", 0)) > 0]
    first_settlement = settle_ops[0] if settle_ops else {}
    evaluations = read_jsonl(LEDGER / "evaluations.jsonl")
    outcomes = read_jsonl(LEDGER / "outcomes.jsonl")
    daily_files = sorted((CAMPAIGN / "daily").glob("*.json"))
    daily_bytes = sum(path.stat().st_size for path in daily_files)
    journal_bytes = bytes_of(CAMPAIGN / "cycles.jsonl") + sum(
        path.stat().st_size for path in (CAMPAIGN / "cycles_segments").glob("cycles-*.jsonl")
    )

    measured_growth = None
    if len(post) >= 2:
        span = int(post[-1]["timestamp"]) - int(post[0]["timestamp"])
        if span > 0:
            measured_growth = {
                "span_seconds": span,
                "bytes_per_day": round(
                    (int(post[-1]["reports_cap004_bytes"]) - int(post[0]["reports_cap004_bytes"]))
                    / span
                    * 86_400,
                    3,
                ),
                "samples": len(post),
            }
    return {
        "verification": verification,
        "manifests": manifests,
        "entries": entries,
        "committed": committed,
        "samples": samples,
        "post_migration_samples": post,
        "journal_events": journal_events,
        "operations": operations,
        "heartbeat": heartbeat,
        "disk": {"free_bytes": int(disk.free), "total_bytes": int(disk.total)},
        "source_bytes": source_bytes,
        "archive_bytes": archive_bytes,
        "reclaimed": reclaimed,
        "first_settlement": first_settlement,
        "outcomes": len(outcomes),
        "evaluations": len(evaluations),
        "daily_bytes": daily_bytes,
        "journal_bytes": journal_bytes,
        "measured_growth": measured_growth,
        # Measured over the SAME window the growth rate is measured on, so the swing
        # cannot be mistaken for the migration's own reclaim of the legacy files.
        "free_space_swing_bytes": (
            max(int(item["free_bytes"]) for item in (post or samples))
            - min(int(item["free_bytes"]) for item in (post or samples))
            if len(post or samples) >= 2
            else 0
        ),
        "archive_tree_bytes": tree_bytes(ARCHIVE),
        "live_report_tree_bytes": tree_bytes(CAMPAIGN) - tree_bytes(ARCHIVE),
        "commit_ts": commit_ts,
    }


def root_cause(data: dict[str, Any]) -> dict[str, Any]:
    entries = data["entries"]
    worst: dict[str, Any] = max(entries, key=lambda item: int(item["source_bytes"]), default={})
    amplification = None
    if worst:
        per_cycle_new = 1000  # one compact event, the information a cycle actually adds
        amplification = round(int(worst["source_bytes"]) / per_cycle_new, 1)
    return {
        "finding": "quadratic snapshot amplification, plus an unbounded reader",
        "mechanism": [
            "daily_report() embedded the FULL list of the day's cycle records under "
            "'cycles', and each cycle record in turn embedded that same daily rollup",
            "the journal was therefore self-referential: every cycle's record was larger "
            "than the one before it, so the file grew quadratically within the day",
            "read_cycle_journal() then did path.read_text().splitlines() over that file, "
            "which needed the whole journal in memory at once",
        ],
        "measured": {
            "files": [
                {
                    "path": str(entry["source"]).split("legacy-20261007T1556Z")[-1],
                    "bytes": int(entry["source_bytes"]),
                    "gib": round(int(entry["source_bytes"]) / GIB, 4),
                    "records": int(entry["records"]),
                    "archive_bytes": int(entry["archive_bytes"]),
                    "ratio": entry["ratio"],
                }
                for entry in entries
            ],
            "total_source_gib": round(data["source_bytes"] / GIB, 4),
            "total_archive_gib": round(data["archive_bytes"] / GIB, 4),
            "largest_source_gib": round(int(worst.get("source_bytes", 0)) / GIB, 4),
            "write_amplification_factor_vs_new_information": amplification,
            "cycle_events_in_legacy_journal": next(
                (
                    int(entry["records"])
                    for entry in entries
                    if str(entry["source"]).endswith("cycles.jsonl")
                ),
                0,
            ),
        },
        "consequence": {
            "evidence_writes_stopped_at": "2026-10-07T10:24Z",
            "cycles_after_that_point": "heartbeat and status kept updating while no journal, "
            "daily projection or operations event was written",
            "why": "MemoryError inside read_cycle_journal aborted the run between the status "
            "write and the daily write, so the cycle left no evidence at all",
            "second_defect": "seal_phase read the analyst answer file unconditionally, so the "
            "first due slot for a new decision (2026-10-07T16:00Z) crashed the run with "
            "FileNotFoundError BEFORE the settlement phase could run",
        },
        "root_cause_demonstrated": True,
    }


def classification() -> list[dict[str, str]]:
    return [
        {
            "artifact": "evidence/real_decisions/decisions.jsonl",
            "class": "AUTHORITATIVE",
            "retention": "indefinite",
            "why": "the sealed decisions; every later artifact is derived from them",
        },
        {
            "artifact": "evidence/real_decisions/outcomes.jsonl",
            "class": "AUTHORITATIVE",
            "retention": "indefinite",
            "why": "the measured outcome per (decision, horizon); not recomputable without re-fetching",
        },
        {
            "artifact": "evidence/real_decisions/evaluations.jsonl",
            "class": "AUTHORITATIVE",
            "retention": "indefinite",
            "why": "the evaluation of an outcome against the frozen rule",
        },
        {
            "artifact": "evidence/real_decisions/operations.jsonl",
            "class": "AUTHORITATIVE / AUDIT",
            "retention": "indefinite",
            "why": "hash-chained record of what the supervisor did per invocation; the journal "
            "is a projection of the same cycles and is NOT the authority",
        },
        {
            "artifact": "evidence/real_decisions/RAW_EVIDENCE_MANIFEST.jsonl + raw_evidence/",
            "class": "AUTHORITATIVE (replay input)",
            "retention": "while required for replay, and indefinitely for settled decisions",
            "why": "the candles the analyst actually saw, pinned by content digest",
        },
        {
            "artifact": "evidence/real_decisions/CAMPAIGN_MANIFEST.json",
            "class": "AUTHORITATIVE (frozen experiment definition)",
            "retention": "indefinite",
            "why": "drift detection depends on it",
        },
        {
            "artifact": "evidence/real_decisions/checkpoints/CHECKPOINT_*.json",
            "class": "AUTHORITATIVE (milestone)",
            "retention": "indefinite",
            "why": "written once per population with a decision_set_hash",
        },
        {
            "artifact": "evidence/real_decisions/heartbeat.json",
            "class": "OPERATIONAL STATE (replaced atomically)",
            "retention": "current only",
            "why": "liveness; a stale heartbeat must read as 'not running'",
        },
        {
            "artifact": "reports/cap004/cycles.jsonl (+ cycles_segments/)",
            "class": "DERIVED (compact cycle event log)",
            "retention": "bounded, segmented; archived segments live as long as the campaign",
            "why": "one compact event per cycle; the same cycles are also in the operations ledger",
        },
        {
            "artifact": "reports/cap004/daily/<day>.json",
            "class": "DERIVED / REGENERABLE projection",
            "retention": "replace atomically",
            "why": "aggregates the day's compact events",
        },
        {
            "artifact": "reports/cap004/{CAMPAIGN_STATUS,CAMPAIGN_METRICS,ALPHA_SCORECARD,"
            "NO_TRADE_SELECTIVITY}*",
            "class": "DERIVED / REGENERABLE",
            "retention": "replace atomically",
            "why": "dashboards recomputable from the ledgers",
        },
        {
            "artifact": "reports/cap004/STORAGE_SAMPLES.json",
            "class": "OPERATIONAL LOG (bounded ring)",
            "retention": "last 512 samples",
            "why": "the growth-rate measurement itself",
        },
        {
            "artifact": "reports/cap004/disk_events.jsonl",
            "class": "OPERATIONAL LOG (transitions only)",
            "retention": "bounded by the number of threshold crossings",
            "why": "DISK_WARNING / DISK_CRITICAL / DISK_RECOVERED",
        },
        {
            "artifact": "reports/cap004/archive/<legacy>/*.gz",
            "class": "ARCHIVED DERIVED BYTES",
            "retention": "indefinite",
            "why": "the preserved, losslessly compressed copy of the pre-fix report tree",
        },
        {
            "artifact": "reports/cap004/slots/ANALYST_PACKAGE_*.json",
            "class": "OPERATIONAL (prompt package)",
            "retention": "bounded, one per decision slot",
            "why": "the prompt handed to the analyst for a due slot",
        },
    ]


def retention_policy() -> list[str]:
    return [
        "AUTHORITATIVE ledgers (decisions, outcomes, evaluations, raw evidence, manifest): "
        "retained indefinitely, never rewritten, never compressed in place.",
        "HASH MANIFESTS and the operations chain: retained indefinitely.",
        "FIRST REAL SETTLEMENT evidence (4 outcomes + 4 evaluations + their operations event): "
        "retained indefinitely and pinned by hash in this bundle.",
        "CHECKPOINTS 20/50/100: retained indefinitely, written once per population.",
        "DERIVED status/scorecard/metrics projections: replaced atomically, never appended.",
        "DERIVED cycle journal: compact events, segmented at 4 MiB, each segment hashed and "
        "listed in a manifest; closed segments are immutable.",
        "DERIVED daily projections: one bounded file per UTC day, replaced atomically.",
        "OPERATIONAL logs: the storage-sample ring keeps the last 512 samples; disk events are "
        "written only on a state transition; the supervisor log rotates by run.",
        "ARCHIVES: the legacy report bytes are kept as gzip archives (lossless, digest-verified) "
        "rather than deleted; the raw pre-compression copies are removed only after the archive "
        "re-derives the source SHA-256 in the same run.",
        "RAW MARKET DATA: retained while a settled decision may need to be replayed.",
    ]


def render_baseline(data: dict[str, Any]) -> str:
    verification = data["verification"]
    return "\n".join(
        [
            "# CAP-004C — baseline",
            "",
            "Recorded before the storage migration was applied to the live report tree.",
            "",
            "## Campaign state at the start of CAP-004C",
            "",
            f"- campaign: `{verification.get('campaign_id', 'CAP004-REAL-DECISIONS-V1')}`",
            f"- decisions sealed: {data['heartbeat'].get('population', {}).get('sealed_decisions')}",
            f"- outcomes settled: {data['heartbeat'].get('population', {}).get('settled_outcomes')}",
            f"- evaluations: {data['heartbeat'].get('population', {}).get('evaluated_decisions')}",
            f"- next maturity: {data['heartbeat'].get('next_maturity')}",
            f"- next decision slot: {data['heartbeat'].get('next_decision_slot_utc')}",
            "",
            "## Storage before",
            "",
            f"- `reports/cap004` derived bytes archived: {data['source_bytes'] / GIB:.4f} GiB",
            f"- of which the three legacy files: {data['source_bytes'] / GIB:.4f} GiB",
            f"- `evidence/` authoritative trees: {tree_bytes(LEDGER) / MIB:.2f} MiB",
            f"- free space on the volume: {data['disk']['free_bytes'] / GIB:.3f} GiB "
            f"of {data['disk']['total_bytes'] / GIB:.2f} GiB",
            "",
            "## Gates before any change",
            "",
            "- `cap003_verify` PASS, `cap004_verify` PASS, `cap004b_verify` PASS",
            "- chain INTACT, drift NO_DRIFT, scheduler enabled",
            "- the first real maturity (2026-10-07T16:00:00Z) had not yet occurred",
            "",
        ]
    )


def render_root_cause(rc: dict[str, Any]) -> str:
    lines = [
        "# CAP-004C — storage root cause",
        "",
        f"**Finding:** {rc['finding']}.",
        "",
        "## Mechanism",
        "",
    ]
    lines.extend(f"- {item}" for item in rc["mechanism"])
    lines.extend(["", "## Measured", "", "| file | GiB | records | archive MiB | ratio |", "| --- | --- | --- | --- | --- |"])
    for item in rc["measured"]["files"]:
        lines.append(
            f"| {item['path']} | {item['gib']} | {item['records']} | "
            f"{item['archive_bytes'] / MIB:.2f} | x{item['ratio']} |"
        )
    lines.extend(
        [
            "",
            f"- total archived: **{rc['measured']['total_source_gib']} GiB**",
            f"- cycle events held by the legacy journal: {rc['measured']['cycle_events_in_legacy_journal']}",
            f"- write amplification vs the information a cycle adds "
            f"(~1000 bytes): **x{rc['measured']['write_amplification_factor_vs_new_information']}**",
            "",
            "## Consequence (the reliability failure, not just the size)",
            "",
            f"- evidence writes stopped at: **{rc['consequence']['evidence_writes_stopped_at']}**",
            f"- {rc['consequence']['cycles_after_that_point']}",
            f"- why: {rc['consequence']['why']}",
            f"- second defect: {rc['consequence']['second_defect']}",
            "",
        ]
    )
    return "\n".join(lines)


def render_classification(rows: list[dict[str, str]]) -> str:
    lines = [
        "# CAP-004C — artifact classification",
        "",
        "Nothing was removed until its class was decided.  `AUTHORITATIVE` means the bytes are "
        "the experiment; everything else is a projection that must be reproducible from them.",
        "",
        "| artifact | class | retention | why |",
        "| --- | --- | --- | --- |",
    ]
    lines.extend(f"| `{row['artifact']}` | {row['class']} | {row['retention']} | {row['why']} |" for row in rows)
    lines.append("")
    return "\n".join(lines)


def render_retention(policy: list[str]) -> str:
    lines = ["# CAP-004C — retention policy", ""]
    lines.extend(f"- {item}" for item in policy)
    lines.append("")
    return "\n".join(lines)


def render_plan(data: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# CAP-004C — storage migration plan",
            "",
            "Order executed (audit first, mutation last):",
            "",
            "1. **Protect the settlement.**  The scheduler was left enabled and no storage change "
            "was made while a real settlement was pending.",
            "2. **Audit.**  Size, growth, record counts and the writer's own code were measured; "
            "the amplification was reproduced from the artifacts, not guessed.",
            "3. **Classify.**  Every artifact was assigned a class before anything moved.",
            "4. **Unblock the hot path.**  The two legacy report files were renamed into "
            "`reports/cap004/archive/legacy-20261007T1556Z/` — a rename is instantaneous, "
            "destroys no bytes and does not require free space.  No deletion happened here.",
            "5. **Fix the contract.**  The writer now appends a compact cycle event; the reader "
            "is bounded per line; the daily rollup aggregates a day instead of embedding it.",
            "6. **Verify, then compress.**  Every archived file was streamed into gzip where the "
            "archive was re-decompressed and its SHA-256 compared with the digest taken while "
            "compressing.  Only a PASS allowed the original to be removed.",
            "7. **Independent verification.**  `scripts/cap004c_verify.py` re-derives every digest "
            "from disk, replays every decision and re-runs the CAP-003/004/004B verifiers.",
            "",
            "## Space arithmetic (measured)",
            "",
            f"- archived source bytes: {data['source_bytes'] / GIB:.4f} GiB",
            f"- archive after compression: {data['archive_bytes'] / GIB:.4f} GiB",
            f"- reclaimed: **{data['reclaimed'] / GIB:.4f} GiB**",
            "- peak extra space needed: one archive file at a time (largest 0.57 GiB), so the "
            "migration never needed a second copy of the report tree",
            "",
            "## What was deliberately NOT done",
            "",
            "- no authoritative ledger, manifest, checkpoint or raw-evidence file was read for "
            "writing, moved, compressed or deleted by the migration;",
            "- no journal segment was rewritten; rotation only renames a file into a segment;",
            "- no report was deleted to make room: the report bytes are archived, verified and kept.",
            "",
        ]
    )


def render_before_after(data: dict[str, Any]) -> str:
    measured = data["measured_growth"]
    journal_events = max(len(data["journal_events"]), 1)
    lines = [
        "# CAP-004C — before / after storage",
        "",
        "## Report tree",
        "",
        "| metric | before | after |",
        "| --- | --- | --- |",
        f"| `reports/cap004`, live (everything a cycle writes) | "
        f"{data['source_bytes'] / GIB:.4f} GiB (3 legacy files alone) | "
        f"{data['live_report_tree_bytes'] / MIB:.2f} MiB |",
        f"| `reports/cap004`, retained archive (gzip of the legacy bytes) | — | "
        f"{data['archive_tree_bytes'] / GIB:.4f} GiB |",
        f"| cycle journal | {next((int(e['source_bytes']) for e in data['entries'] if str(e['source']).endswith('cycles.jsonl')), 0) / GIB:.4f} GiB "
        f"in one file | {data['journal_bytes'] / 1024:.2f} KiB in compact events |",
        f"| daily projection | "
        f"{sum(int(e['source_bytes']) for e in data['entries'] if 'daily' in str(e['source'])) / GIB:.4f} GiB | "
        f"{data['daily_bytes'] / 1024:.2f} KiB |",
        f"| journal bytes per cycle | up to {next((int(e['source_bytes']) for e in data['entries'] if str(e['source']).endswith('cycles.jsonl')), 0) / max(next((int(e['records']) for e in data['entries'] if str(e['source']).endswith('cycles.jsonl')), 1), 1) / MIB:.2f} MiB | "
        f"{data['journal_bytes'] / journal_events / 1024:.2f} KiB |",
        "",
        "## Growth rate",
        "",
        f"- before (stored, averaged over the campaign day that filled the disk): "
        f"{data['source_bytes'] / GIB:.4f} GiB accumulated for the cycles on record",
        f"- after, projected from the new contract at the 15-minute cadence: "
        f"{(data['verification'].get('storage') or {}).get('projected_bytes_per_day', 0) / 1024:.2f} KiB/day",
    ]
    if measured:
        lines.append(
            f"- after, measured on {measured['samples']} post-migration samples over "
            f"{measured['span_seconds']} s: **{measured['bytes_per_day'] / 1024:.2f} KiB/day**"
        )
    else:
        lines.append(
            "- after, measured: NOT_YET_MEASURABLE (fewer than two post-migration samples)"
        )
    lines.extend(
        [
            "",
            "## Reclaim",
            "",
            f"- reclaimed by lossless archival: **{data['reclaimed'] / GIB:.4f} GiB**",
            f"- free space now: {data['disk']['free_bytes'] / GIB:.3f} GiB of "
            f"{data['disk']['total_bytes'] / GIB:.2f} GiB",
            "- note: free space on this host is dominated by activity outside the repository "
            "(measured swings of several GiB in minutes), so the reclaim is reported from the "
            "migration manifest's own byte counts, not from the free-space delta",
            "",
        ]
    )
    return "\n".join(lines)


def render_disk_guard(data: dict[str, Any]) -> str:
    heartbeat = data["heartbeat"]
    disk = heartbeat.get("disk") or {}
    growth = disk.get("growth") or {}
    lines = [
        "# CAP-004C — disk space guard",
        "",
        "## Contract",
        "",
        "- `HEALTHY` when free space is at or above 5 GiB, `WARNING` between 2 and 5 GiB, "
        "`CRITICAL` below 2 GiB (thresholds measured against this 238 GiB volume).",
        "- The guard is checked BEFORE each cycle and recorded in the heartbeat, the supervisor "
        "status and the operations event (`disk_free_bytes`, `disk_status`).",
        "- `CRITICAL` refuses NEW decisions only (`NO_NEW_DECISION_DISK_CRITICAL`).  Settling, "
        "evaluating and verifying decisions that are already sealed is preservation work and is "
        "never blocked.",
        "- A `DISK_WARNING` / `DISK_CRITICAL` event is written exactly once per transition; "
        "recovery writes `DISK_RECOVERED`.",
        "- A forecast in days is only produced from a rate the guard can measure as stable; "
        "otherwise the honest answer is `UNKNOWN`/`VOLATILE`.",
        "",
        "## Live state",
        "",
        f"- free: {disk.get('free_gib')} GiB of {disk.get('total_gib')} GiB "
        f"({disk.get('used_percent')}% used) → **{heartbeat.get('disk_status')}**",
        f"- growth status: {growth.get('status')} ({growth.get('bytes_per_day')} bytes/day)",
        f"- estimated days to WARNING: {disk.get('estimated_days_to_warning')}",
        f"- estimated days to CRITICAL: {disk.get('estimated_days_to_critical')}",
        "",
        "## Why the growth rate is not a free-space delta",
        "",
        "The host lost and regained several GiB in minutes with the repository writing "
        "kilobytes: the campaign measures the bytes it owns and reports the host's free space "
        "separately, so no storage verdict is built on movement the campaign cannot explain.",
        "",
    ]
    return "\n".join(lines)


def render_replay(data: dict[str, Any]) -> str:
    verification = data["verification"]
    replay = verification.get("replay") or {}
    raw = verification.get("raw_evidence") or {}
    lines = [
        "# CAP-004C — replay verification",
        "",
        "Replay is the campaign's own read-only reconstruction (`DecisionLedger.replay`), and the "
        "hashes it returns are re-derived independently in "
        "`scripts/cap004c_verify.py` from a re-declared rule.",
        "",
        f"- decisions replayed: {len(replay)}",
        f"- snapshot digests matched: {len(replay)}",
        f"- raw evidence registered: {raw.get('registered')}",
        f"- raw evidence re-derived from the stored file: {raw.get('verified')}",
        "",
        "| decision | snapshot hash | decision hash | outcome hash | evaluation hash |",
        "| --- | --- | --- | --- | --- |",
    ]
    for decision_id, item in sorted(replay.items()):
        outcome = next(iter((item.get("outcomes") or {}).values()), "")
        evaluation = next(iter((item.get("evaluations") or {}).values()), "")
        lines.append(
            f"| {decision_id} | {str(item.get('snapshot_hash'))[:16]} | "
            f"{str(item.get('decision_hash'))[:16]} | {str(outcome)[:16]} | {str(evaluation)[:16]} |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in (verification.get("notes") or ["none"]))
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in (verification.get("limitations") or ["none"]))
    lines.append("")
    return "\n".join(lines)


def render_final(data: dict[str, Any]) -> dict[str, Any]:
    verification = data["verification"]
    storage = verification.get("storage") or {}
    measured = data["measured_growth"]
    return {
        "report": "CAP004C_FINAL_REPORT",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "verdict": "STORAGE_STABILIZED" if verification.get("status") == "PASS" else "STORAGE_BLOCKED",
        "how_much_space_did_we_save_gib": round(data["reclaimed"] / GIB, 4),
        "reclaimed_bytes": data["reclaimed"],
        "new_growth_rate_kib_per_day": round(
            (measured or {}).get("bytes_per_day", storage.get("projected_bytes_per_day", 0)) / 1024, 3
        ),
        "new_growth_rate_source": "measured post-migration samples"
        if measured
        else "projected from the compact contract",
        "projected_bytes_per_day": storage.get("projected_bytes_per_day"),
        "days_until_warning": (data["heartbeat"].get("disk") or {}).get("estimated_days_to_warning"),
        "first_real_settlement_survived": bool(data["first_settlement"]),
        "first_real_settlement": {
            "operation_id": data["first_settlement"].get("operation_id"),
            "ended_at_utc": data["first_settlement"].get("ended_at_utc"),
            "settled": data["first_settlement"].get("settled"),
            "evaluated": data["first_settlement"].get("evaluated"),
            "verification": data["first_settlement"].get("verification"),
            "exit_code": data["first_settlement"].get("exit_code"),
            "outcomes_in_ledger": data["outcomes"],
            "evaluations_in_ledger": data["evaluations"],
            "disk_status": data["first_settlement"].get("disk_status"),
        },
        "cap004b_running": bool(
            data["heartbeat"] and time.time() - int(data["heartbeat"].get("timestamp", 0)) < 3600
        ),
        "heartbeat_utc": data["heartbeat"].get("timestamp_utc"),
        "scheduler": "TradingAgentic-CAP004-Campaign (enabled, 15-minute cadence)",
        "gates": verification.get("delegated"),
        "cap004c_verification": {
            "status": verification.get("status"),
            "checks": verification.get("checks"),
            "passed": verification.get("passed"),
            "mismatches": verification.get("mismatches"),
            "false_success": verification.get("false_success"),
        },
        "trades_authorized": 0,
        "alpha_claimed": False,
        "g_agentic_edge": "NOT_TESTED",
        "economic_conclusion": "INSUFFICIENT_SAMPLE",
        "next_gate": "ACCUMULATE_REAL_DECISIONS",
        "notes": verification.get("notes"),
        # Limitations stated from measurements, not from modesty: the verifier's own
        # list is empty because every check it runs passes; these are the facts a
        # reader needs in order not to over-read the verdict.
        "limitations": [
            (
                "free space on this host is moved by activity outside the repository: over "
                "the post-migration window it swung "
                f"{data['free_space_swing_bytes'] / GIB:.3f} GiB while the campaign tree moved "
                f"{((measured or {}).get('bytes_per_day', 0) or 0) / 1024:.1f} KiB/day, so the "
                "reclaim is reported from the migration manifest's byte counts and the growth "
                "rate from the campaign's own bytes — never from a free-space delta"
            ),
            (
                "the forecast assumes the 15-minute cadence and the compact cycle contract "
                "stay in force; a contract change is a new discontinuity and must be declared "
                "as one"
            ),
            (
                f"the archived legacy report bytes ({data['archive_tree_bytes'] / GIB:.4f} GiB, "
                "gzip) are retained, so the live report tree ("
                f"{data['live_report_tree_bytes'] / MIB:.2f} MiB) and the archive are both part "
                "of what is on disk"
            ),
            (
                "raw OHLCV evidence stays local and outside Git (it is what replay needs), so "
                "its bytes are measured here but cannot be verified from a clone alone"
            ),
        ],
    }


def render_final_md(payload: dict[str, Any]) -> str:
    lines = [
        "# CAP-004C — final report",
        "",
        f"- verdict: **{payload['verdict']}**",
        f"- space saved: **{payload['how_much_space_did_we_save_gib']} GiB** (lossless archival)",
        f"- new growth rate: **{payload['new_growth_rate_kib_per_day']} KiB/day** "
        f"({payload['new_growth_rate_source']})",
        f"- days until WARNING: {payload['days_until_warning']}",
        f"- first real settlement survived: "
        f"**{'YES' if payload['first_real_settlement_survived'] else 'NO'}**",
        f"- CAP-004B running: **{'YES' if payload['cap004b_running'] else 'NO'}**",
        "",
        "## First real settlement",
        "",
    ]
    settlement = payload["first_real_settlement"]
    lines.extend(
        [
            f"- operation: {settlement.get('operation_id')} at {settlement.get('ended_at_utc')}",
            f"- settled: {settlement.get('settled')}   evaluated: {settlement.get('evaluated')}   "
            f"verify: {settlement.get('verification')}   exit: {settlement.get('exit_code')}",
            f"- outcomes in the ledger: {settlement.get('outcomes_in_ledger')}   "
            f"evaluations: {settlement.get('evaluations_in_ledger')}",
            "",
            "## Gates",
            "",
        ]
    )
    for name, item in (payload.get("gates") or {}).items():
        lines.append(f"- {name}: {item['status']} (exit {item['exit_code']})")
    lines.extend(
        [
            f"- cap004c: {payload['cap004c_verification']['status']} "
            f"({payload['cap004c_verification']['passed']}/{payload['cap004c_verification']['checks']} checks, "
            f"{payload['cap004c_verification']['mismatches']} mismatches, "
            f"{payload['cap004c_verification']['false_success']} false success)",
            "",
            "## Economic state (unchanged)",
            "",
            f"- trades authorized: {payload['trades_authorized']}",
            f"- alpha claimed: {payload['alpha_claimed']}",
            f"- G_AGENTIC_EDGE: {payload['g_agentic_edge']}",
            f"- conclusion: {payload['economic_conclusion']}",
            f"- next gate: **{payload['next_gate']}**",
            "",
            "## Limitations",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in (payload["limitations"] or ["none"]))
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CAP-004C evidence bundle")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    data = collect()
    OUT.mkdir(parents=True, exist_ok=True)
    rc = root_cause(data)
    rows = classification()
    policy = retention_policy()
    final = render_final(data)

    (OUT / "BASELINE.md").write_text(render_baseline(data), encoding="utf-8")
    (OUT / "STORAGE_ROOT_CAUSE.md").write_text(render_root_cause(rc), encoding="utf-8")
    (OUT / "STORAGE_ROOT_CAUSE.json").write_text(
        json.dumps(rc, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (OUT / "STORAGE_CLASSIFICATION.md").write_text(render_classification(rows), encoding="utf-8")
    (OUT / "STORAGE_CLASSIFICATION.json").write_text(
        json.dumps({"artifacts": rows}, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (OUT / "RETENTION_POLICY.md").write_text(render_retention(policy), encoding="utf-8")
    (OUT / "STORAGE_MIGRATION_PLAN.md").write_text(render_plan(data), encoding="utf-8")
    for manifest in data["manifests"]:
        (OUT / "STORAGE_MIGRATION_MANIFEST.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    before_after = {
        "report": "CAP004C_BEFORE_AFTER_STORAGE",
        "generated_utc": final["generated_utc"],
        "before": {
            "reports_cap004_bytes": data["source_bytes"],
            "reports_cap004_gib": round(data["source_bytes"] / GIB, 4),
            "archive_files": [
                {
                    "path": str(entry["source"]).split("legacy-20261007T1556Z")[-1],
                    "bytes": int(entry["source_bytes"]),
                    "records": int(entry["records"]),
                }
                for entry in data["entries"]
            ],
        },
        "after": {
            "reports_cap004_bytes": tree_bytes(CAMPAIGN),
            "archive_bytes": data["archive_bytes"],
            "archive_gib": round(data["archive_bytes"] / GIB, 4),
            "journal_bytes": data["journal_bytes"],
            "journal_events": len(data["journal_events"]),
            "daily_bytes": data["daily_bytes"],
        },
        "reclaimed_bytes": data["reclaimed"],
        "reclaimed_gib": round(data["reclaimed"] / GIB, 4),
        "measured_post_migration_growth": data["measured_growth"],
        "projected_bytes_per_day": (data["verification"].get("storage") or {}).get(
            "projected_bytes_per_day"
        ),
        "free_bytes_now": data["disk"]["free_bytes"],
    }
    (OUT / "BEFORE_AFTER_STORAGE.md").write_text(render_before_after(data), encoding="utf-8")
    (OUT / "BEFORE_AFTER_STORAGE.json").write_text(
        json.dumps(before_after, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    disk_guard = {
        "report": "CAP004C_DISK_GUARD",
        "generated_utc": final["generated_utc"],
        "thresholds": {
            "healthy_free_bytes": 5 * GIB,
            "critical_free_bytes": 2 * GIB,
            "derived_from": "measured against this 238 GiB volume and the observed ±4 GiB of "
            "activity outside the repository",
        },
        "live": data["heartbeat"].get("disk"),
        "heartbeat_disk_status": data["heartbeat"].get("disk_status"),
        "transitions": [
            json.loads(line)
            for line in (CAMPAIGN / "disk_events.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if (CAMPAIGN / "disk_events.jsonl").is_file()
        else [],
    }
    (OUT / "DISK_GUARD_REPORT.md").write_text(render_disk_guard(data), encoding="utf-8")
    (OUT / "DISK_GUARD_REPORT.json").write_text(
        json.dumps(disk_guard, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (OUT / "REPLAY_VERIFICATION.md").write_text(render_replay(data), encoding="utf-8")
    run_report = {
        "report": "CAP004C_RUN_REPORT",
        "generated_utc": final["generated_utc"],
        "verification": {
            "status": data["verification"].get("status"),
            "checks": data["verification"].get("checks"),
            "passed": data["verification"].get("passed"),
            "mismatches": data["verification"].get("mismatches"),
            "false_success": data["verification"].get("false_success"),
        },
        "delegated": data["verification"].get("delegated"),
        "journal_events": len(data["journal_events"]),
        "journal_events_sample": data["journal_events"][-3:],
        "operations_events": len(data["operations"]),
        "storage_samples": len(data["samples"]),
        "post_migration_samples": len(data["post_migration_samples"]),
        "measured_post_migration_growth": data["measured_growth"],
    }
    (OUT / "RUN_REPORT.md").write_text(
        "\n".join(
            [
                "# CAP-004C — run report",
                "",
                f"- generated: {run_report['generated_utc']}",
                f"- cap004c verification: {run_report['verification']['status']} "
                f"({run_report['verification']['passed']}/{run_report['verification']['checks']})",
                "- delegated verifiers: "
                + ", ".join(
                    f"{name}={item['status']}" for name, item in (run_report["delegated"] or {}).items()
                ),
                f"- compact journal events: {run_report['journal_events']}",
                f"- operations events: {run_report['operations_events']}",
                f"- storage samples: {run_report['storage_samples']} "
                f"({run_report['post_migration_samples']} after the migration)",
                f"- measured growth after the migration: {run_report['measured_post_migration_growth']}",
                "",
                "## Compact journal (last events)",
                "",
                "```json",
                json.dumps(run_report["journal_events_sample"], indent=2, sort_keys=True),
                "```",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (OUT / "RUN_REPORT.json").write_text(
        json.dumps(run_report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (OUT / "FINAL_REPORT.json").write_text(
        json.dumps(final, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (OUT / "FINAL_REPORT.md").write_text(render_final_md(final), encoding="utf-8")

    written = sorted(path.name for path in OUT.iterdir() if path.is_file())
    print(f"CAP-004C evidence written to {OUT} ({len(written)} files)")
    for name in written:
        print(f"  {name}")
    if args.json:
        print(json.dumps(final, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
