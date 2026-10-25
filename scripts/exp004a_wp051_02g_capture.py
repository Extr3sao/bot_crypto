"""WP-051-02G: incremental sharded capture of the declared EXP-004A phase-3 window.

The phase-2 extractor is frozen and, by design, writes a dataset once: a capture taken on the
first day of a ninety-day window freezes that day for ever (``DEF-02F-01``). This program is the
second mechanism a new declaration authorises. It captures **one UTC day at a time**, into
**write-once shards**, keeps a **scheduler watermark** so a repeated tick is cheap and an
interrupted one is resumable, and consolidates the shards deterministically into a dataset whose
digest is a function of the shard bytes alone.

What this program is not:

* it is not a certifier. It writes ``CAPTURE_COMPLETE_AWAITING_VERIFICATION`` and nothing
  stronger; ``scripts/exp004a_wp051_02g_verify.py`` is a separate program that decides whether
  the bytes are what the manifest says;
* it is not a daemon. ``--schedule`` loops for a bounded number of ticks inside this process; no
  cron entry, task or service is installed, and ``L-02`` stays open;
* it does not touch phase 2. The phase-2 declaration, extractor, datasets and the sealed
  ``wp051_02b``..``wp051_02f`` packages are read-only to it.

Research only: reads local files, writes local files, makes no network call, places no order.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import platform
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.prospective import incremental as engine  # noqa: E402

CAPTURE_ID = "capture/EXP-004A/WP-051-02G"
SCHEMA_VERSION = "1.0"

DECLARATION = "config/preregistrations/EXP-004A.datasets.phase3.json"
OUT_DIR = "docs/agentic/exp004a/wp051_02g"
VERIFIER = "scripts/exp004a_wp051_02g_verify.py"
GENERATOR = "scripts/exp004a_wp051_02g_capture.py"

RUN_REPORT = "RUN_REPORT.json"
RUN_REPORT_MD = "RUN_REPORT.md"
CLAIM_REPORT = "CLAIM.json"
VERIFICATION_REPORT = "INDEPENDENT_VERIFICATION.json"
EVIDENCE_MANIFEST = "EVIDENCE_MANIFEST.json"
LATEST_RUN = "LATEST_RUN.json"
EVIDENCE_DIR = "evidence"

#: The builder's own states. ``CAPTURE_COMPLETE_AWAITING_VERIFICATION`` is deliberately not
#: ``CAPTURED_VERIFIED``: only the independent verifier may use that word.
STATE_NOT_DUE = "NOT_DUE"
STATE_PENDING_WINDOW_OPEN = "PENDING_WINDOW_OPEN"
STATE_PENDING_DATA = "PENDING_DATA"
STATE_BLOCKED_INTEGRITY = "BLOCKED_INTEGRITY"
STATE_CAPTURE_COMPLETE = "CAPTURE_COMPLETE_AWAITING_VERIFICATION"
STATE_CONSOLIDATED = "CONSOLIDATED_AWAITING_VERIFICATION"
STATE_RESUMED = "RESUMED"
STATE_FAILED = "FAILED"

EXIT_OK = 0
EXIT_BLOCKED = 2
EXIT_PENDING = 3
EXIT_FAILED = 4
EXIT_QUARANTINED = 5
EXIT_ALREADY_RUNNING = 6

LOCK_STALE_SECONDS = 900
_RUN_SEQUENCE = itertools.count(1)

#: The gates this package does not move. Written into every run report so that a reader cannot
#: mistake a capture for a promotion.
GATES_UNCHANGED: dict[str, str] = {
    "economic_executions": "0",
    "orders_placed": "0",
    "paper_orders_placed": "0",
    "live_trading": "DISABLED",
    "risk_limits": "UNCHANGED",
    "promotion": "NO_PROMOTION",
    "certification": "NOT_CLAIMED_BY_BUILDER",
}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def now_ms() -> int:
    return int(time.time() * 1000)


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(repo: Path, *args: str) -> str | None:
    import subprocess

    try:
        completed = subprocess.run(
            ["git", *args], cwd=str(repo), capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def git_blob_sha(repo: Path, path: str) -> str | None:
    return git(repo, "rev-parse", f"HEAD:{path}")


def git_commit_time(repo: Path, path: str) -> str | None:
    return git(repo, "log", "-1", "--format=%cI", "--", path)


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        document = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return document if isinstance(document, dict) else None


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    temporary.write_bytes(json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    os.replace(temporary, path)
    return path


def relative_to_repo(repo: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def new_run_id(at_ms: int) -> str:
    """A run id that cannot collide, even in two attempts inside one clock tick."""
    stamp = datetime.fromtimestamp(at_ms / 1000, UTC).strftime("%Y%m%dT%H%M%SZ")
    nonce = hashlib.sha256(
        f"{at_ms}-{os.getpid()}-{next(_RUN_SEQUENCE)}-{os.urandom(8).hex()}".encode()
    ).hexdigest()[:8]
    return f"{stamp}-{nonce}"


class LockHeld(RuntimeError):
    """Another capture holds the directory. Two publishers would be one shard too many."""


class Lock:
    """An exclusive, age-based lease over the capture root."""

    def __init__(self, path: Path, *, stale_seconds: int = LOCK_STALE_SECONDS) -> None:
        self.path = path
        self.stale_seconds = stale_seconds
        self.taken_over: dict[str, Any] | None = None

    def __enter__(self) -> Lock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"pid": os.getpid(), "capture": CAPTURE_ID, "acquired_at_utc": iso(now_ms())}
        ).encode("utf-8")
        try:
            handle = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            existing = read_json(self.path) or {}
            age = time.time() - self.path.stat().st_mtime
            if age <= self.stale_seconds:
                raise LockHeld(
                    f"{self.path} is held by pid {existing.get('pid')} since "
                    f"{existing.get('acquired_at_utc')} ({int(age)} s old)"
                ) from None
            self.taken_over = {"previous": existing, "age_seconds": int(age)}
            self.path.unlink(missing_ok=True)
            handle = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
        return self

    def __exit__(self, *exc: object) -> None:
        self.path.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# the capture root
# --------------------------------------------------------------------------- #


def capture_root(declaration: engine.Declaration, *, rehearsal: bool) -> Path:
    """Where shards and the scheduler's memory live for this run.

    A rehearsal gets its own root so that historical store bytes can never be mistaken for a
    prospective shard, even by a reader who ignores every flag in the manifests.
    """
    if rehearsal:
        rehearsal_doc = declaration.rehearsal
        assert rehearsal_doc is not None
        return rehearsal_doc.shard_root
    roots = {entry.shard_root for entry in declaration.entries}
    if len(roots) != 1:
        raise engine.CaptureError(f"the declaration names {len(roots)} capture roots: {sorted(map(str, roots))}")
    return roots.pop()


# --------------------------------------------------------------------------- #
# one tick
# --------------------------------------------------------------------------- #


def _plan_view(plan: engine.Plan) -> dict[str, Any]:
    view: dict[str, Any] = {
        "slice": plan.entry.label,
        "day": plan.day,
        "action": plan.action,
        "reason": plan.reason,
        "opens": len(plan.opens),
    }
    if plan.missing:
        view["missing_opens"] = [iso(open_ms) for open_ms in plan.missing[:5]]
        view["missing_count"] = len(plan.missing)
    if plan.unclosed:
        view["unclosed_count"] = len(plan.unclosed)
    if plan.existing_sha256:
        view["existing_sha256"] = plan.existing_sha256
    return view


def _summarise_plan(summary: engine.PlanSummary) -> dict[str, Any]:
    counts = summary.counts()
    return {
        "counts": counts,
        "captured_days": [
            {"slice": plan.entry.label, "day": plan.day} for plan in summary.of(engine.SHARD_CAPTURED)
        ],
        "already_held": [
            {"slice": plan.entry.label, "day": plan.day, "sha256": plan.existing_sha256}
            for plan in summary.of(engine.SHARD_ALREADY_HELD)
        ],
        "conflicts": [_plan_view(plan) for plan in summary.of(engine.SHARD_CONFLICT)],
        "refused": [_plan_view(plan) for plan in summary.of(engine.SHARD_REFUSED)],
        "not_due": [
            _plan_view(plan) for plan in summary.of(engine.SHARD_NOT_DUE) if plan.missing
        ][:10],
        "not_due_count": len(summary.of(engine.SHARD_NOT_DUE)),
        "incomplete_days": len(summary.of(engine.SHARD_INCOMPLETE)),
        "incomplete_first": [_plan_view(plan) for plan in summary.of(engine.SHARD_INCOMPLETE)][:3],
    }


def capture_tick(
    declaration: engine.Declaration,
    *,
    rehearsal: bool,
    at_ms: int,
    run_id: str,
    log_dir: Path | None,
) -> dict[str, Any]:
    """One authorised attempt: recover, plan, capture, consolidate. Never republish."""
    entries, window_start, window_end, counts = engine.resolve_window(
        declaration, rehearsal=rehearsal
    )
    root = capture_root(declaration, rehearsal=rehearsal)
    recovered = engine.recover_partials(root)
    summary = engine.capture_plan(
        entries, at_ms=at_ms, window_start_ms=window_start, window_end_ms=window_end
    )
    written: list[dict[str, Any]] = []
    cache: dict[Path, Any] = {}
    generator = {
        "script": GENERATOR,
        # Two magnitudes, named apart. ``script_sha256`` hashes the bytes of *this checkout* (a
        # CRLF checkout hashes differently from an LF one); ``git_blob_sha`` is the Git object id
        # and is the same in every clone. A reader who wants to know which program ran should
        # compare the blob; one who wants to know what was on disk should compare the digest.
        "script_sha256": sha256_file(Path(__file__).resolve()),
        "git_blob_sha": git_blob_sha(REPO, GENERATOR),
        "argv": [
            sys.executable,
            GENERATOR,
            "--once",
            "--declaration",
            relative_to_repo(REPO, declaration.path),
            *(["--rehearsal"] if rehearsal else []),
        ],
    }
    for plan in summary.of(engine.SHARD_CAPTURED):
        index = cache.get(plan.entry.source)
        if index is None:
            from trading_bot.research.prospective.store import index_series

            index = index_series(plan.entry.source, plan.entry.asset, plan.entry.interval)
            cache[plan.entry.source] = index
        shard = engine.write_shard(
            plan.entry,
            plan,
            index=index,
            declaration=declaration,
            at_ms=at_ms,
            capture_id=CAPTURE_ID,
            prospective=not rehearsal,
            counts_toward_coverage=counts,
            generator=generator,
        )
        entry_view = {
            "slice": plan.entry.label,
            "day": plan.day,
            "rows": shard.manifest["row_count"],
            "bytes": shard.manifest["bytes"],
            "sha256": shard.manifest["sha256"],
            "admissible": shard.manifest["admissible"],
            "defects": shard.manifest["defects"],
            "shard": relative_to_repo(REPO, shard.data_path),
            "manifest": relative_to_repo(REPO, shard.manifest_path),
            "max_lag_ms": shard.manifest["lag"]["max_ms"],
        }
        written.append(entry_view)
        if log_dir is not None:
            log_dir.mkdir(parents=True, exist_ok=True)
            (log_dir / "shards.jsonl").open("a", encoding="utf-8").write(
                json.dumps(entry_view, sort_keys=True) + "\n"
            )
    consolidation = engine.consolidate(
        entries,
        at_ms=at_ms,
        prospective=not rehearsal,
        counts_toward_coverage=counts,
        window_start_ms=window_start,
    )
    consolidated = write_consolidated(
        declaration, consolidation, at_ms=at_ms, run_id=run_id, counts=counts
    )
    state = _state(
        summary=summary,
        written=written,
        consolidation=consolidation,
        at_ms=at_ms,
        window_start_ms=window_start,
        rehearsal=rehearsal,
    )
    return {
        "window": {
            "start_utc": iso(window_start),
            "end_utc": iso(window_end),
            "declared_rows_per_slice": [entry.declared_rows for entry in entries],
            "declared_days": [entry.declared_days for entry in entries],
        },
        "plan": _summarise_plan(summary),
        "recovered_partials": recovered,
        "shards_written": written,
        "consolidation": consolidated,
        "coverage": {
            "declared_rows": consolidation.declared_rows,
            "admissible_rows": consolidation.admissible_rows,
            "fraction": round(consolidation.fraction, 6),
            "required_fraction": consolidation.required_fraction,
            "status": consolidation.status,
            "counts_toward_coverage": counts,
        },
        "state": state,
    }


def _state(
    *,
    summary: engine.PlanSummary,
    written: list[dict[str, Any]],
    consolidation: engine.Consolidation,
    at_ms: int,
    window_start_ms: int,
    rehearsal: bool,
) -> str:
    """The builder's word for what just happened, which is never a verification."""
    conflicts = summary.of(engine.SHARD_CONFLICT)
    if conflicts or any(not item["admissible"] for item in written):
        return STATE_BLOCKED_INTEGRITY
    if consolidation.defects and any(
        defect.get("code")
        in {
            engine.DEFECT_SHARD_DIGEST,
            engine.DEFECT_SHARD_MANIFEST,
            engine.DEFECT_DUPLICATE,
            engine.DEFECT_FUTURE,
            engine.DEFECT_NEGATIVE_LAG,
        }
        for defect in consolidation.defects
    ):
        return STATE_BLOCKED_INTEGRITY
    if written:
        return STATE_CAPTURE_COMPLETE
    if at_ms < window_start_ms and not rehearsal:
        return STATE_PENDING_WINDOW_OPEN
    if summary.of(engine.SHARD_NOT_DUE):
        return STATE_PENDING_DATA
    return STATE_NOT_DUE


def write_consolidated(
    declaration: engine.Declaration,
    consolidation: engine.Consolidation,
    *,
    at_ms: int,
    run_id: str,
    counts: bool,
) -> dict[str, Any]:
    """Write the consolidated dataset once, and describe it.

    The payload is a function of the shard bytes only: days in order, bars in open order, and no
    timestamp of this run inside the file. Two consolidations of the same shards are byte-equal,
    which is what makes the recorded digest worth comparing.
    """
    views: list[dict[str, Any]] = []
    for item in consolidation.slices:
        target = (
            item.entry.shard_root
            / engine.CONSOLIDATED_DIR
            / f"{item.entry.interval}_{item.entry.asset}"
            / f"{run_id}.jsonl"
        )
        manifest_path = target.with_suffix(".MANIFEST.json")
        digest = hashlib.sha256(item.payload).hexdigest()
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + ".part")
            temporary.write_bytes(item.payload)
            os.replace(temporary, target)
        existing = hashlib.sha256(target.read_bytes()).hexdigest()
        manifest: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "consolidation_id": f"{item.entry.label}@{run_id}",
            "slice": item.entry.label,
            "dataset_id": item.entry.dataset_id,
            "declaration": {
                "path": relative_to_repo(REPO, declaration.path),
                "declaration_id": declaration.declaration_id,
                "sha256": declaration.sha256,
            },
            "window": {
                "start_utc": iso(item.entry.period_start_ms),
                "end_utc": iso(item.entry.period_end_ms),
            },
            "prospective": consolidation.prospective,
            "counts_toward_coverage": counts,
            "days": list(item.days),
            "quarantined_days": list(item.quarantined),
            "row_count": item.rows,
            "declared_rows": item.declared_rows,
            "bytes": len(item.payload),
            "sha256": digest,
            "sha256_on_disk": existing,
            "defects": list(item.defects),
            "coverage_status": item.status,
            "consolidated_at_utc": iso(at_ms),
            "run_id": run_id,
            "note": (
                "Deterministic in the shards: the bytes are the shards' own lines, days in order, "
                "bars by open. Nothing about this run is written inside them."
            ),
        }
        write_json(manifest_path, manifest)
        views.append(
            {
                "slice": item.entry.label,
                "dataset_id": item.entry.dataset_id,
                "days": len(item.days),
                "quarantined": len(item.quarantined),
                "rows": item.rows,
                "declared_rows": item.declared_rows,
                "fraction": round(item.fraction, 6),
                "status": item.status,
                "sha256": digest,
                "deterministic_match": digest == existing,
                "path": relative_to_repo(REPO, target),
                "manifest": relative_to_repo(REPO, manifest_path),
                "defects": list(item.defects)[:20],
                "defect_count": len(item.defects),
            }
        )
    return {
        "prospective": consolidation.prospective,
        "counts_toward_coverage": counts,
        "slices": views,
        "status": consolidation.status,
        "defect_count": len(consolidation.defects),
    }


# --------------------------------------------------------------------------- #
# read-only and resume
# --------------------------------------------------------------------------- #


def check(declaration: engine.Declaration, *, at_ms: int) -> dict[str, Any]:
    """Read the world; write nothing. No lock, no state, no shard."""
    report: dict[str, Any] = {"at_utc": iso(at_ms), "declaration": relative_to_repo(REPO, declaration.path)}
    for rehearsal in (False, True):
        if rehearsal and declaration.rehearsal is None:
            continue
        entries, window_start, window_end, counts = engine.resolve_window(
            declaration, rehearsal=rehearsal
        )
        summary = engine.capture_plan(
            entries, at_ms=at_ms, window_start_ms=window_start, window_end_ms=window_end
        )
        consolidation = engine.consolidate(
            entries,
            at_ms=at_ms,
            prospective=not rehearsal,
            counts_toward_coverage=counts,
            window_start_ms=window_start,
        )
        block = {
            "window": {"start_utc": iso(window_start), "end_utc": iso(window_end)},
            "counts_toward_coverage": counts,
            "plan": _summarise_plan(summary),
            "coverage": {
                "declared_rows": consolidation.declared_rows,
                "admissible_rows": consolidation.admissible_rows,
                "fraction": round(consolidation.fraction, 6),
                "status": consolidation.status,
            },
        }
        report["rehearsal" if rehearsal else "phase"] = block
    root = capture_root(declaration, rehearsal=False)
    if root.is_dir():
        report["partials"] = [
            relative_to_repo(REPO, path) for path in sorted(root.rglob("*.part"))
        ]
    report["state_file"] = relative_to_repo(REPO, engine.state_path(root))
    report["state_present"] = engine.state_path(root).is_file()
    return report


def resume(
    declaration: engine.Declaration, *, at_ms: int, run_id: str, rehearsal: bool
) -> dict[str, Any]:
    """Reconcile what a previous attempt left behind, then capture what is still due.

    Reconciliation is deliberately read-only with respect to shards: a shard whose manifest
    matches its bytes is kept and reported; a shard whose bytes do not match is reported as a
    conflict and never rewritten; a temporary file that was never renamed is removed and named.
    """
    entries, _, _, _ = engine.resolve_window(declaration, rehearsal=rehearsal)
    root = capture_root(declaration, rehearsal=rehearsal)
    recovered = engine.recover_partials(root)
    shards: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for entry in entries:
        for day in engine.shard_days(entry.period_start_ms, entry.period_end_ms, entry.interval_ms):
            data_path, manifest_path = engine.shard_paths(entry, day)
            if not manifest_path.is_file() and not data_path.is_file():
                continue
            manifest = read_json(manifest_path)
            if not isinstance(manifest, dict) or not data_path.is_file():
                conflicts.append(
                    {"slice": entry.label, "day": day, "reason": "manifest or payload missing"}
                )
                continue
            digest = sha256_file(data_path)
            healthy = manifest.get("sha256") == digest
            shards.append(
                {
                    "slice": entry.label,
                    "day": day,
                    "sha256": digest,
                    "healthy": healthy,
                    "admissible": manifest.get("admissible"),
                    "rows": manifest.get("row_count"),
                }
            )
            if not healthy:
                conflicts.append({"slice": entry.label, "day": day, "reason": "digest mismatch"})
    tick = capture_tick(
        declaration, rehearsal=rehearsal, at_ms=at_ms, run_id=run_id, log_dir=None
    )
    tick["reconciliation"] = {
        "shards_seen": len(shards),
        "healthy": sum(1 for item in shards if item["healthy"]),
        "unhealthy": [item for item in shards if not item["healthy"]],
        "conflicts": conflicts,
        "recovered_partials": recovered,
        "shards": shards,
    }
    if conflicts:
        tick["state"] = STATE_BLOCKED_INTEGRITY
    elif not tick["shards_written"]:
        tick["state"] = STATE_RESUMED
    return tick


# --------------------------------------------------------------------------- #
# the run report
# --------------------------------------------------------------------------- #


def build_report(
    *,
    declaration: engine.Declaration,
    mode: str,
    run_id: str,
    at_ms: int,
    tick: dict[str, Any],
    rehearsal: bool,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "package": "WP-051-02G",
        "rfc": "RFC-EXP004A-051-02G",
        "builder": CAPTURE_ID,
        "run_id": run_id,
        "mode": mode,
        "at_utc": iso(at_ms),
        "head": git(REPO, "rev-parse", "HEAD"),
        "platform": {
            "python": platform.python_version(),
            "system": platform.system(),
            "machine": platform.machine(),
        },
        "declaration": {
            "path": relative_to_repo(REPO, declaration.path),
            "declaration_id": declaration.declaration_id,
            "sha256": declaration.sha256,
            "git_blob_sha": git_blob_sha(REPO, relative_to_repo(REPO, declaration.path)),
            "commit_time": git_commit_time(REPO, relative_to_repo(REPO, declaration.path)),
            "window": {
                "start_utc": iso(declaration.window_start_ms),
                "end_utc": iso(declaration.window_end_ms),
            },
            "effective_from_utc": iso(declaration.effective_from_ms),
            "shard_granularity": declaration.shard_granularity,
            "lag_policy": declaration.lag_policy,
            "rehearsal": None
            if declaration.rehearsal is None
            else {
                "start_utc": iso(declaration.rehearsal.start_ms),
                "end_utc": iso(declaration.rehearsal.end_ms),
                "counts_toward_coverage": declaration.rehearsal.counts_toward_coverage,
                "note": declaration.rehearsal.note,
            },
        },
        "generator": {
            "script": GENERATOR,
            "script_sha256": sha256_file(Path(__file__).resolve()),
            "git_blob_sha": git_blob_sha(REPO, GENERATOR),
            "verifier": VERIFIER,
            "verifier_sha256": sha256_file(REPO / VERIFIER) if (REPO / VERIFIER).is_file() else None,
        },
        "rehearsal": rehearsal,
        "prospective": not rehearsal,
        "state": tick["state"],
        "window": tick["window"],
        "plan": tick["plan"],
        "shards_written": tick["shards_written"],
        "consolidation": tick["consolidation"],
        "coverage": tick["coverage"],
        "recovered_partials": tick["recovered_partials"],
        "gates": dict(GATES_UNCHANGED),
        "certifiable": False,
        "certifiable_reason": (
            "the builder never certifies. Coverage is "
            f"{tick['coverage']['status']}; the independent verifier decides whether the bytes "
            "match their manifests and whether that state may be called complete."
        ),
        "notes": [],
    }
    if extra:
        report.update(extra)
    notes: list[str] = report["notes"]
    if rehearsal:
        notes.append(
            "This run is a rehearsal over the declared rehearsal window. Every shard is stamped "
            "prospective=false and counts_toward_coverage=false; the phase's own coverage is not "
            "moved by it and is reported separately."
        )
    if tick["coverage"]["status"] != engine.COVERAGE_COMPLETE:
        notes.append(
            "Coverage is incomplete. Incomplete coverage stays "
            f"{tick['coverage']['status']} for ever; no run of this program can promote it."
        )
    if report["plan"]["conflicts"]:
        notes.append(
            "A shard exists whose bytes contradict its manifest, or a payload exists without a "
            "manifest. It was neither adopted nor overwritten; the run is BLOCKED_INTEGRITY."
        )
    return report


def render_report_md(report: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    add(f"# WP-051-02G run report — `{report['run_id']}`")
    add("")
    add(
        f"**Mode:** `{report['mode']}` · **State:** `{report['state']}` · "
        f"**Rehearsal:** {report['rehearsal']} · **At:** `{report['at_utc']}` · "
        f"**HEAD:** `{report['head']}`"
    )
    add("")
    add("> A capture is not a certification. The builder states what it wrote and what it found;")
    add("> `INDEPENDENT_VERIFICATION.json` is what decides whether the bytes are what they claim.")
    add("")
    add("## The declaration")
    add("")
    declaration = report["declaration"]
    add(f"- `{declaration['declaration_id']}` at `{declaration['path']}`")
    add(f"- sha256 `{declaration['sha256'][:16]}` · git blob `{str(declaration['git_blob_sha'])[:12]}`")
    add(f"- commit time `{declaration['commit_time']}`")
    add(
        f"- window `{declaration['window']['start_utc']}` → `{declaration['window']['end_utc']}` · "
        f"effective from `{declaration['effective_from_utc']}`"
    )
    add("")
    add("## What the plan found")
    add("")
    plan = report["plan"]
    for name, value in sorted(plan["counts"].items()):
        add(f"- `{name}`: {value}")
    add("")
    add("## Shards written in this run")
    add("")
    if report["shards_written"]:
        add("| Slice | Day | Rows | sha256 | Admissible | Max lag (ms) |")
        add("|---|---|---|---|---|---|")
        for item in report["shards_written"]:
            add(
                f"| `{item['slice']}` | {item['day']} | {item['rows']} | "
                f"`{item['sha256'][:16]}` | {item['admissible']} | {item['max_lag_ms']} |"
            )
    else:
        add("No shard was written in this run.")
    add("")
    add("## Consolidation")
    add("")
    if report["consolidation"]["slices"]:
        add("| Slice | Days | Rows | Declared | Fraction | Status | Deterministic |")
        add("|---|---|---|---|---|---|---|")
        for item in report["consolidation"]["slices"]:
            add(
                f"| `{item['slice']}` | {item['days']} | {item['rows']} | {item['declared_rows']} | "
                f"{item['fraction']:.4f} | {item['status']} | {item['deterministic_match']} |"
            )
    else:
        add("No slice could be consolidated.")
    add("")
    coverage = report["coverage"]
    add(
        f"**Coverage:** {coverage['admissible_rows']} / {coverage['declared_rows']} "
        f"({coverage['fraction']:.4f}) · required {coverage['required_fraction']} · "
        f"**{coverage['status']}** · counts toward coverage: {coverage['counts_toward_coverage']}"
    )
    add("")
    if report["recovered_partials"]:
        add("## Interrupted writes recovered")
        add("")
        for path in report["recovered_partials"]:
            add(f"- `{path}` (temporary, never renamed, never evidence)")
        add("")
    add("## The gates this package did not move")
    add("")
    for name, value in report["gates"].items():
        add(f"- `{name}`: {value}")
    add("")
    add("## Notes")
    add("")
    for note in report["notes"]:
        add(f"- {note}")
    add("")
    return "\n".join(lines) + "\n"


def evidence_manifest(repo: Path, out_dir: Path, run_dir: Path, report: dict[str, Any]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for path in sorted(item for item in out_dir.rglob("*") if item.is_file()):
        name = relative_to_repo(repo, path)
        if name.endswith(EVIDENCE_MANIFEST):
            continue
        entry: dict[str, Any] = {
            "path": name,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        blob = git_blob_sha(repo, name)
        if blob:
            entry["git_blob_sha"] = blob
        entries.append(entry)
    return {
        "schema_version": SCHEMA_VERSION,
        "package": "WP-051-02G",
        "sealed_at_utc": iso(now_ms()),
        "head": git(repo, "rev-parse", "HEAD"),
        "run_id": report.get("run_id"),
        "run_dir": relative_to_repo(repo, run_dir),
        "state": report.get("state"),
        "coverage": report.get("coverage"),
        "hash_semantics": (
            "sha256 hashes the bytes in this checkout; git_blob_sha is the Git object id at HEAD. "
            "They are different magnitudes and are never presented as the same value."
        ),
        "entries": entries,
        "entry_count": len(entries),
        "not_a_certification": (
            "a manifest says what is in the package. It does not say the package is right, and it "
            "promotes nothing."
        ),
    }


def summarise_runs(repo: Path, out_dir: Path) -> dict[str, Any]:
    """Index every attempt in the package, and keep the phase and the rehearsal apart.

    A package that captured a rehearsal and nothing else must not read like a package that
    captured the window. The two are listed under different keys, with their own coverage and
    their own verdict file if one exists, so that a reader cannot average them.
    """
    evidence = out_dir / EVIDENCE_DIR
    runs: list[dict[str, Any]] = []
    if evidence.is_dir():
        for run_dir in sorted(item for item in evidence.iterdir() if item.is_dir()):
            report = read_json(run_dir / RUN_REPORT)
            if report is None:
                continue
            verification = read_json(run_dir / VERIFICATION_REPORT) or read_json(
                out_dir / VERIFICATION_REPORT
            )
            runs.append(
                {
                    "run_id": report.get("run_id"),
                    "mode": report.get("mode"),
                    "rehearsal": report.get("rehearsal"),
                    "state": report.get("state"),
                    "at_utc": report.get("at_utc"),
                    "shards_written": len(report.get("shards_written") or []),
                    "coverage": report.get("coverage"),
                    "certifiable": report.get("certifiable"),
                    "verdict": None
                    if verification is None
                    else {
                        "path": relative_to_repo(repo, run_dir / VERIFICATION_REPORT)
                        if (run_dir / VERIFICATION_REPORT).is_file()
                        else relative_to_repo(repo, out_dir / VERIFICATION_REPORT),
                        "verdict": verification.get("verdict"),
                        "certification_allowed": verification.get("certification_allowed"),
                    },
                }
            )
    phase = [item for item in runs if item["rehearsal"] is False]
    rehearsals = [item for item in runs if item["rehearsal"] is True]
    return {
        "schema_version": SCHEMA_VERSION,
        "package": "WP-051-02G",
        "generated_at_utc": iso(now_ms()),
        "head": git(repo, "rev-parse", "HEAD"),
        "runs": runs,
        "run_count": len(runs),
        "phase": phase[-1] if phase else None,
        "rehearsal": rehearsals[-1] if rehearsals else None,
        "note": (
            "the phase and the rehearsal are reported apart on purpose. The rehearsal verifies the "
            "mechanism on historical bytes; it never moves the phase's coverage."
        ),
    }


def latest_run_dir(out_dir: Path) -> Path | None:
    evidence = out_dir / EVIDENCE_DIR
    if not evidence.is_dir():
        return None
    candidates = sorted(item for item in evidence.iterdir() if item.is_dir())
    return candidates[-1] if candidates else None


def seal(repo: Path, out_dir: Path, run_id: str | None) -> tuple[int, dict[str, Any]]:
    run_dir = out_dir / EVIDENCE_DIR / run_id if run_id else latest_run_dir(out_dir)
    if run_dir is None or not run_dir.is_dir():
        return EXIT_FAILED, {"ok": False, "error": "there is no run to seal"}
    report = read_json(run_dir / RUN_REPORT)
    if report is None:
        return EXIT_FAILED, {"ok": False, "error": f"{run_dir.name} has no run report"}
    manifest_path = out_dir / EVIDENCE_MANIFEST
    existing = read_json(manifest_path) or {}
    if existing and existing.get("run_id") != report.get("run_id"):
        return EXIT_BLOCKED, {
            "ok": False,
            "error": (
                f"a seal for run {existing.get('run_id')} already exists; sealing "
                f"{report.get('run_id')} would overwrite it"
            ),
        }
    write_json(out_dir / RUN_REPORT, report)
    (out_dir / RUN_REPORT_MD).write_text(render_report_md(report), encoding="utf-8")
    verification = read_json(run_dir / VERIFICATION_REPORT)
    if verification is not None:
        write_json(out_dir / VERIFICATION_REPORT, verification)
    # ``LATEST_RUN`` is written before the manifest, not after it: a manifest that does not cover
    # every file of the package is a manifest a reader has to audit by hand.
    write_json(out_dir / LATEST_RUN, {"run_id": report.get("run_id"), "at_utc": iso(now_ms())})
    manifest = evidence_manifest(repo, out_dir, run_dir, report)
    write_json(manifest_path, manifest)
    return EXIT_OK, {
        "ok": True,
        "run_id": report.get("run_id"),
        "state": report.get("state"),
        "coverage": report.get("coverage"),
        "entry_count": manifest["entry_count"],
    }


# --------------------------------------------------------------------------- #
# the state watermark
# --------------------------------------------------------------------------- #


def update_state(
    declaration: engine.Declaration,
    *,
    root: Path,
    tick: dict[str, Any],
    run_id: str,
    at_ms: int,
    rehearsal: bool,
) -> dict[str, Any]:
    state = engine.read_state(root)
    previous_slices = state.get("slices")
    slices: dict[str, Any] = dict(previous_slices) if isinstance(previous_slices, dict) else {}
    for item in tick["shards_written"]:
        key = str(item["slice"])
        previous = slices.get(key)
        record: dict[str, Any] = previous if isinstance(previous, dict) else {}
        held = record.get("days")
        days = sorted({*(held if isinstance(held, list) else []), item["day"]})
        slices[key] = {
            **record,
            "days": days,
            "last_run_id": run_id,
            "last_at_utc": iso(at_ms),
            "last_state": tick["state"],
            "rows": int(record.get("rows", 0)) + int(item["rows"]),
        }
    previous_runs = state.get("runs")
    runs: list[Any] = previous_runs if isinstance(previous_runs, list) else []
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "declaration": {
            "path": relative_to_repo(REPO, declaration.path),
            "declaration_id": declaration.declaration_id,
            "sha256": declaration.sha256,
        },
        "rehearsal": rehearsal,
        "updated_at_utc": iso(at_ms),
        "runs": [
            *runs[-49:],
            {"run_id": run_id, "at_utc": iso(at_ms), "state": tick["state"]},
        ],
        "slices": slices,
        "coverage_status": tick["coverage"]["status"],
        "note": "a watermark, not evidence: the verifier never reads this file",
    }
    engine.write_state(root, payload)
    return payload


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def run_attempt(
    declaration: engine.Declaration,
    *,
    repo: Path,
    out_dir: Path,
    mode: str,
    rehearsal: bool,
    resume_mode: bool,
    at_ms: int,
) -> tuple[int, dict[str, Any]]:
    """One attempt at the declared clock instant.

    ``at_ms`` is a parameter and not ``now_ms()`` because a rehearsal has to be able to ask the
    question "what would a tick at this instant have captured?". The instant is written into every
    manifest as ``captured_at_utc``, so a rehearsal run is auditable as one.
    """
    run_id = new_run_id(at_ms)
    root = capture_root(declaration, rehearsal=rehearsal)
    run_dir = out_dir / EVIDENCE_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    try:
        with Lock(engine.lock_path(root)) as lock:
            tick = (
                resume(declaration, at_ms=at_ms, run_id=run_id, rehearsal=rehearsal)
                if resume_mode
                else capture_tick(
                    declaration, rehearsal=rehearsal, at_ms=at_ms, run_id=run_id, log_dir=run_dir
                )
            )
            extra: dict[str, Any] = {}
            if lock.taken_over:
                extra["lock_taken_over"] = lock.taken_over
            if resume_mode:
                extra["reconciliation"] = tick.get("reconciliation")
            state = update_state(
                declaration, root=root, tick=tick, run_id=run_id, at_ms=at_ms, rehearsal=rehearsal
            )
            extra["scheduler_state"] = {
                "path": relative_to_repo(repo, engine.state_path(root)),
                "slices": sorted(state["slices"]),
                "runs_recorded": len(state["runs"]),
            }
            report = build_report(
                declaration=declaration,
                mode=mode,
                run_id=run_id,
                at_ms=at_ms,
                tick=tick,
                rehearsal=rehearsal,
                extra=extra,
            )
    except LockHeld as error:
        report = {
            "schema_version": SCHEMA_VERSION,
            "package": "WP-051-02G",
            "run_id": run_id,
            "mode": mode,
            "state": STATE_FAILED,
            "error": str(error),
            "gates": dict(GATES_UNCHANGED),
            "certifiable": False,
        }
        write_json(run_dir / RUN_REPORT, report)
        return EXIT_ALREADY_RUNNING, report
    write_json(run_dir / CLAIM_REPORT, report)
    write_json(run_dir / RUN_REPORT, report)
    (run_dir / RUN_REPORT_MD).write_text(render_report_md(report), encoding="utf-8")
    return exit_for(report), report


def exit_for(report: dict[str, Any]) -> int:
    state = report.get("state")
    if state == STATE_BLOCKED_INTEGRITY:
        return EXIT_BLOCKED
    if state in (STATE_PENDING_WINDOW_OPEN, STATE_PENDING_DATA, STATE_NOT_DUE, STATE_RESUMED):
        return EXIT_PENDING
    if state == STATE_FAILED:
        return EXIT_FAILED
    return EXIT_OK


def run_consolidate(
    declaration: engine.Declaration, *, out_dir: Path, rehearsal: bool, at_ms: int
) -> tuple[int, dict[str, Any]]:
    run_id = new_run_id(at_ms)
    entries, window_start, window_end, counts = engine.resolve_window(
        declaration, rehearsal=rehearsal
    )
    consolidation = engine.consolidate(
        entries,
        at_ms=at_ms,
        prospective=not rehearsal,
        counts_toward_coverage=counts,
        window_start_ms=window_start,
    )
    consolidated = write_consolidated(
        declaration, consolidation, at_ms=at_ms, run_id=run_id, counts=counts
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "package": "WP-051-02G",
        "run_id": run_id,
        "mode": "consolidate",
        "at_utc": iso(at_ms),
        "head": git(REPO, "rev-parse", "HEAD"),
        "rehearsal": rehearsal,
        "prospective": not rehearsal,
        "state": STATE_CONSOLIDATED,
        "declaration": {
            "path": relative_to_repo(REPO, declaration.path),
            "declaration_id": declaration.declaration_id,
            "sha256": declaration.sha256,
        },
        "window": {"start_utc": iso(window_start), "end_utc": iso(window_end)},
        "consolidation": consolidated,
        "coverage": {
            "declared_rows": consolidation.declared_rows,
            "admissible_rows": consolidation.admissible_rows,
            "fraction": round(consolidation.fraction, 6),
            "required_fraction": consolidation.required_fraction,
            "status": consolidation.status,
            "counts_toward_coverage": counts,
        },
        "gates": dict(GATES_UNCHANGED),
        "certifiable": False,
        "notes": [
            "Consolidation reconstructs the dataset from the shards and names every defect it "
            "finds. It does not repair anything, and it does not certify.",
        ],
    }
    run_dir = out_dir / EVIDENCE_DIR / run_id
    write_json(run_dir / RUN_REPORT, report)
    readable: dict[str, Any] = {
        **report,
        "plan": {"counts": {}},
        "shards_written": [],
        "recovered_partials": [],
    }
    (run_dir / RUN_REPORT_MD).write_text(render_report_md(readable), encoding="utf-8")
    return EXIT_OK, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="read the world; write nothing")
    mode.add_argument("--once", action="store_true", help="one authorised capture tick")
    mode.add_argument("--resume", action="store_true", help="reconcile a previous attempt, then tick")
    mode.add_argument("--consolidate", action="store_true", help="rebuild from the shards only")
    mode.add_argument("--schedule", action="store_true", help="bounded periodic ticks in-process")
    mode.add_argument("--seal", action="store_true", help="promote one run to the package's seal")
    mode.add_argument("--summary", action="store_true", help="index every attempt; write nothing else")
    parser.add_argument("--declaration", type=Path, default=REPO / DECLARATION)
    parser.add_argument("--out", type=Path, default=REPO / OUT_DIR)
    parser.add_argument("--rehearsal", action="store_true", help="use the declared rehearsal window")
    parser.add_argument("--run-id", default=None, help="seal this run instead of the latest")
    parser.add_argument("--interval-seconds", type=int, default=3600, help="schedule tick period")
    parser.add_argument("--max-ticks", type=int, default=1, help="schedule tick budget")
    parser.add_argument(
        "--as-of",
        default=None,
        help=(
            "evaluate (and capture) as if the clock said this (ISO-8601). A capture that uses it "
            "writes that instant into every manifest, so it is auditable as a rehearsal."
        ),
    )
    args = parser.parse_args(argv)

    try:
        if args.as_of:
            from trading_bot.research.prospective.incremental import parse_ms

            clock = parse_ms(args.as_of, "--as-of")
        else:
            clock = now_ms()
        declaration = engine.load_declaration(Path(args.declaration))
    except (engine.DeclarationError, engine.CaptureError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, sort_keys=True), file=sys.stderr)
        return EXIT_FAILED

    if args.seal:
        code, result = seal(REPO, Path(args.out), args.run_id)
        print(json.dumps(result, sort_keys=True))
        return code
    if args.summary:
        summary = summarise_runs(REPO, Path(args.out))
        write_json(Path(args.out) / "PACKAGE_SUMMARY.json", summary)
        print(
            json.dumps(
                {
                    "ok": True,
                    "runs": summary["run_count"],
                    "phase": None if summary["phase"] is None else summary["phase"]["state"],
                    "rehearsal": None
                    if summary["rehearsal"] is None
                    else summary["rehearsal"]["state"],
                },
                sort_keys=True,
            )
        )
        return EXIT_OK
    if args.check:
        report = check(declaration, at_ms=clock)
        print(json.dumps({"ok": True, **report}, indent=2, sort_keys=True))
        return EXIT_OK
    if args.consolidate:
        try:
            code, report = run_consolidate(
                declaration, out_dir=Path(args.out), rehearsal=args.rehearsal, at_ms=clock
            )
        except (engine.CaptureError, OSError) as error:
            print(json.dumps({"ok": False, "error": str(error)}, sort_keys=True), file=sys.stderr)
            return EXIT_FAILED
        print(json.dumps({"ok": True, "run_id": report["run_id"], "state": report["state"], "coverage": report["coverage"]}, sort_keys=True))
        return code
    if args.schedule:
        # A bounded loop, not a daemon: the process owns its lifetime and a `--max-ticks` budget.
        ticks = max(1, min(args.max_ticks, 48))
        codes: list[int] = []
        last: dict[str, Any] = {}
        for index in range(ticks):
            code, report = run_attempt(
                declaration,
                repo=REPO,
                out_dir=Path(args.out),
                mode="schedule",
                rehearsal=args.rehearsal,
                resume_mode=False,
                at_ms=now_ms(),
            )
            codes.append(code)
            last = report
            if index + 1 < ticks:
                time.sleep(max(0, args.interval_seconds))
        summary = {
            "ticks": len(codes),
            "exit_codes": codes,
            "last_run_id": last.get("run_id"),
            "last_state": last.get("state"),
            "coverage": last.get("coverage"),
        }
        print(json.dumps(summary, sort_keys=True))
        return exit_for(last) if last else EXIT_OK

    code, report = run_attempt(
        declaration,
        repo=REPO,
        out_dir=Path(args.out),
        mode="resume" if args.resume else "once",
        rehearsal=args.rehearsal,
        resume_mode=args.resume,
        at_ms=clock,
    )
    print(
        json.dumps(
            {
                "ok": code in (EXIT_OK, EXIT_PENDING),
                "run_id": report.get("run_id"),
                "state": report.get("state"),
                "rehearsal": args.rehearsal,
                "shards_written": len(report.get("shards_written") or []),
                "coverage": report.get("coverage"),
            },
            sort_keys=True,
        )
    )
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
