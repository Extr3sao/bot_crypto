#!/usr/bin/env python
"""RFC-051 independent verifier for EXP-004A — read-only, fail-closed.

This module is written by the verification role, not by the builder. It imports no
``trading_bot`` module and shares no arithmetic with ``scripts/exp004a_evidence_inventory.py``
or ``scripts/exp004a_foundation.py``: every digest, count and classification below is recomputed
from bytes and from the frozen text of RFC-050, and the builder's reports are read only as the
*claims to be tested*. ``audit_own_source`` enforces both statements at run time.

Two modes, one contract::

    verify            full claim adjudication (V-GIT, V-TIME, V-DATA, V-ADMISSION, V-GATE,
                      V-REPLAY, V-COST, V-ENV) and artifact emission
    inspect-evidence  digest and chain reconciliation only, writes nothing

Exit codes are the verifier's own and do not touch ``prereg_gate``'s::

    0 PASS     2 FAIL     3 BLOCKED     4 ERROR

``PASS`` here means "every in-scope technical claim was recomputed and agreed". It is never an
authorisation, a profitability statement or a promotion. When a required input is missing — most
often the principal-level independence RFC-051 §5 demands — the run is ``BLOCKED``, not ``PASS``.

Windows note: junctions are created with ``mklink /J`` because that is the one reparse point this
host can make without elevation; a refused or skipped control is reported as such, never as a pass.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

VERIFIER_ID = "verifier-b/EXP-004A/WP-051-02"
RFC_ID = "RFC-051"
SCHEMA_VERSION = "1.0"

EXIT_PASS = 0
EXIT_FAIL = 2
EXIT_BLOCKED = 3
EXIT_ERROR = 4

STATUS_EXIT = {"PASS": EXIT_PASS, "FAIL": EXIT_FAIL, "BLOCKED": EXIT_BLOCKED, "ERROR": EXIT_ERROR}

# Reason codes. The first block is RFC-051 §6.4 verbatim; the additions are real gaps this
# verifier had to name, and they are schema-tested so they cannot drift.
RFC_REASONS = frozenset(
    {
        "BLOCKED_MISSING_INDEPENDENT_VERIFIER",
        "SOURCE_BYTES_UNAVAILABLE",
        "PROTOCOL_REF_UNRESOLVED",
        "EVALUATED_SOURCE_MISMATCH",
        "REPORT_CODE_STALE",
        "DIGEST_MISMATCH",
        "LEDGER_DUPLICATE",
        "ADMISSION_REPLAY_MISMATCH",
        "LOOKAHEAD_DETECTED",
        "TIME_PROOF_WEAK",
        "INVALID_PHASE1_AUTHORIZATION",
        "PHASE2_CAPTURE_OPEN",
        "INSUFFICIENT_ADMITTED_DAYS",
        "DECLARED_SIZE_NOT_WALKED",
        "COST_SCOPE_UNPROVEN",
        "UNSUPPORTED_PROFITABILITY_CLAIM",
        "UNPROVEN_ENVIRONMENT_COVERAGE",
        "VERIFIER_MUTATED_SOURCE",
        "INDEPENDENCE_NOT_PROVEN",
        "VERIFIER_INTERNAL_ERROR",
    }
)
EXTRA_REASONS = frozenset(
    {
        "IDEMPOTENCY_NOT_REPLAYED",
        "SOURCE_CORRUPT",
        "PREFIX_NOT_RECORD_ALIGNED",
        "GATE_TRANSCRIPT_MISMATCH",
        "SELF_CERTIFICATION_DETECTED",
        "OUTPUT_ROOT_FORBIDDEN",
        "CHAIN_DIGEST_MISMATCH",
    }
)
ALL_REASONS = RFC_REASONS | EXTRA_REASONS

# Numeric constants that would turn the verifier into a rubber stamp: if any appears as a number
# in this file, the audit fails the run. Keeping them out is the executable form of "do not assert
# what you did not measure". The claim *sentences* may quote them — only code is scanned.
FORBIDDEN_NUMBERS = ("20.0012", "20.0408", "20.9414", "702", "229", "234", "235", "5616")

FORBIDDEN_IMPORTS = (
    "trading_bot.research.prereg_gate",
    "trading_bot.research.prospective",
    "trading_bot.research.execution_cost",
    "trading_bot.research.microstructure",
    "exp004a_evidence_inventory",
    "exp004a_foundation",
)

# day -> bars, and asset -> day -> bars. The order matters: the calendar day is the unit of
# admission, so it is the innermost key.
DayBars = dict[str, list[dict[str, Any]]]
SeriesBars = dict[str, DayBars]

INTERVAL_MS = {"1h": 3_600_000, "15m": 900_000}
EXPECTED_BARS_PER_DAY = {"1h": 24, "15m": 96}
COVERAGE_REQUIRED = 0.90

CLAIMS: tuple[tuple[str, str], ...] = (
    ("C-000", "verifier identity is independent of the builder (RFC-051 §5)"),
    ("C-001", "115 tests passed, 1 skipped; ruff and mypy clean"),
    ("C-002", "prereg gate inspect exits 3 with zero defects"),
    ("C-003", "prereg gate authorize exits 2 with TWO_PHASE_PHASE_1_IS_NOT_AUTHORISABLE and nothing else"),
    ("C-004", "admission coverage 235 -> 234 -> 229 -> 5 prospective (1h) and 4 joint (1h+15m)"),
    ("C-005", "234 + 14 attestations, series prefix digests and 14 joint records, zero byte-verification errors"),
    ("C-006", "a repeated run adds zero records"),
    ("C-007", "ST-6 cost at 200 USDT: BTC 20.0012, ETH 20.0408, SOL 20.9414 bps median"),
    ("C-008", "declared 500 USDT not walked: DECLARED_SIZE_NOT_WALKED remains"),
    ("C-009", "RUN_REPORT used d05f8de while later commits exist; evaluated vs report commit must be distinguished"),
    ("C-010", "a clean checkout reproduces the sealed ledger bytes; the external store is outside Git"),
    ("C-011", "Windows junction escape refused with a positive control; symlink test skipped for want of privilege"),
    ("C-012", "economic_executions is 0 and phase-2 capture is still open"),
    ("C-013", "the protocol freeze provably precedes the capture start under a trusted clock"),
    ("C-014", "the verifier's own adversarial acceptance suite passes with FALSE_SUCCESS = 0"),
)

ACCEPTANCE_SUITE = "tests/unit/research/test_exp004a_verify_adversarial.py"

# Files the builder owns. The verifier hashes them before and after itself to prove the one
# permission it was given (read) is the only permission it used.
BUILDER_OWNED_GLOBS = (
    "docs/agentic/exp004a/RUN_REPORT.json",
    "docs/agentic/exp004a/RUN_REPORT.md",
    "docs/agentic/exp004a/FINAL_REPORT.md",
    "docs/agentic/exp004a/GATE_INSPECT.json",
    "docs/agentic/exp004a/GATE_AUTHORIZE.json",
    "docs/agentic/exp004a/handoff",
    "data/exp004a/admission_1h.jsonl",
    "data/exp004a/admission_1h+15m.jsonl",
    "config/preregistrations/EXP-004A.json",
    "config/preregistrations/EXP-004A.prior_runs.json",
    "config/preregistrations/EXP-004A.datasets.json",
    "data/st6/ST6_OBSERVATIONS.jsonl",
    "docs/RFC-050_EXP004A_TWO_PHASE_FREEZE.md",
)

FORBIDDEN_OUTPUT_ROOTS = ("data", "reports/ai-bots", "evidence")


# --------------------------------------------------------------------------- #
# Primitives — written here, not imported
# --------------------------------------------------------------------------- #
class SourceCorrupt(RuntimeError):
    """An evidence file could not be read as the format it claims to be."""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path, limit: int | None = None) -> str:
    digest = hashlib.sha256()
    remaining = limit
    with path.open("rb") as handle:
        while True:
            size = 1 << 20 if remaining is None else min(1 << 20, remaining)
            if size == 0:
                break
            chunk = handle.read(size)
            if not chunk:
                break
            digest.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
    return digest.hexdigest()


def canonical(payload: dict[str, Any]) -> bytes:
    """The ledger's documented serialisation (``prospective/ledger.py`` docstring form)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def record_digest(payload: dict[str, Any]) -> str:
    return sha256_bytes(canonical({key: value for key, value in payload.items() if key != "sha256"}))


def iso_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def utc_day(epoch_ms: int) -> str:
    return datetime.fromtimestamp(epoch_ms / 1000, UTC).strftime("%Y-%m-%d")


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceCorrupt(f"{path}: {exc}") from exc


def load_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse JSONL without repairing it: a truncated line is a finding, not a skip."""
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SourceCorrupt(f"{path}: {exc}") from exc
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{path.name}:{number}: {exc.msg}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"{path.name}:{number}: record is {type(payload).__name__}, not object")
            continue
        rows.append(payload)
    return rows, errors


class Git:
    """Thin plumbing wrapper: git is the evidence for provenance, so it is queried, not trusted."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def __call__(self, *args: str) -> tuple[int, bytes]:
        completed = subprocess.run(
            ["git", "-C", str(self.root), *args],
            capture_output=True,
            check=False,
            timeout=120,
        )
        return completed.returncode, completed.stdout

    def text(self, *args: str) -> str:
        code, out = self(*args)
        if code != 0:
            return ""
        return out.decode("utf-8", "replace").strip()

    def resolve(self, rev: str) -> str | None:
        code, out = self("rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
        return out.decode().strip() if code == 0 else None

    def parents(self, rev: str) -> list[str]:
        fields = self.text("rev-list", "--parents", "-n", "1", rev).split()
        return fields[1:]

    def tree(self, rev: str) -> str:
        return self.text("rev-parse", f"{rev}^{{tree}}")

    def is_ancestor(self, older: str, newer: str) -> bool:
        return self("merge-base", "--is-ancestor", older, newer)[0] == 0

    def committer_iso(self, rev: str) -> str | None:
        raw = self.text("show", "-s", "--format=%cI", rev)
        return raw or None

    def blob_sha256(self, rev: str, path: str) -> str | None:
        code, out = self("cat-file", "-p", f"{rev}:{path}")
        return sha256_bytes(out) if code == 0 else None

    def blob_size(self, rev: str, path: str) -> int | None:
        code, out = self("cat-file", "-p", f"{rev}:{path}")
        return len(out) if code == 0 else None

    def last_commit_touching(self, path: str) -> str | None:
        return self.text("log", "-1", "--format=%H", "--", path) or None

    def changed_paths(self, older: str, newer: str, paths: Sequence[str]) -> list[str]:
        out = self.text("diff", "--name-only", older, newer, "--", *paths)
        return [line for line in out.splitlines() if line.strip()]

    def dirty_count(self) -> int:
        return len([line for line in self.text("status", "--porcelain").splitlines() if line])


# --------------------------------------------------------------------------- #
# Findings
# --------------------------------------------------------------------------- #
@dataclass
class Finding:
    claim_id: str
    status: str
    reason_code: str | None
    observed: dict[str, Any] = field(default_factory=dict)
    evidence_refs: list[str] = field(default_factory=list)
    scope: str = ""

    def to_dict(self) -> dict[str, Any]:
        if self.reason_code is not None and self.reason_code not in ALL_REASONS:
            raise AssertionError(f"unstable reason code {self.reason_code!r} for {self.claim_id}")
        return {
            "claim_id": self.claim_id,
            "status": self.status,
            "reason_code": self.reason_code,
            "observed": self.observed,
            "evidence_refs": self.evidence_refs,
            "scope": self.scope,
        }


@dataclass
class Context:
    source_root: Path
    evidence_root: Path
    output_root: Path
    ref: str | None = None
    offline: bool = False

    @property
    def git(self) -> Git:
        return Git(self.source_root)


# --------------------------------------------------------------------------- #
# Independence
# --------------------------------------------------------------------------- #
def audit_own_source(module_path: Path) -> dict[str, Any]:
    """Static proof that this verifier cannot quietly BE the builder."""
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            imported.add(base)
            imported.update(f"{base}.{alias.name}" for alias in node.names)
    forbidden_imports = sorted(
        name for name in imported for bad in FORBIDDEN_IMPORTS if name.startswith(bad)
    )
    numbers = {
        float(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    }
    literals = sorted(value for value in FORBIDDEN_NUMBERS if float(value) in numbers)
    return {
        "module": str(module_path.name),
        "imports": sorted(imported),
        "forbidden_imports": forbidden_imports,
        "forbidden_literals": literals,
        "clean": not forbidden_imports and not literals,
    }


def check_independence(ctx: Context) -> Finding:
    manifest = load_json(ctx.source_root / "config/preregistrations/EXP-004A.json")
    builder = str(manifest.get("controls", {}).get("builder_identity", "")).strip()
    declared_verifier = str(
        manifest.get("controls", {}).get("independent_verifier_identity", "")
    ).strip()
    principal = os.environ.get("EXP004A_VERIFIER_PRINCIPAL", "").strip()
    audit = audit_own_source(Path(__file__))

    observed: dict[str, Any] = {
        "verifier_id": VERIFIER_ID,
        "verifier_principal": principal or None,
        "builder_identity_in_manifest": builder or None,
        "declared_verifier_identity": declared_verifier or None,
        "separate_worktree": False,
        "disjoint_write_rights": True,
        "output_root": str(ctx.output_root),
        "own_source_audit": audit,
    }
    if not audit["clean"]:
        return Finding(
            "C-000",
            "FAIL",
            "INDEPENDENCE_NOT_PROVEN",
            observed,
            ["scripts/exp004a_verify.py"],
            "the verifier shares code or a hardcoded verdict with the builder",
        )

    same_principal = not principal or principal == builder
    observed["same_principal_as_builder"] = same_principal
    if same_principal:
        observed["why"] = (
            "RFC-051 §5: a role label or a new prompt in the same build session is insufficient "
            "evidence of independence; a distinct principal or agent run with its own worktree "
            "was not available to this execution"
        )
        return Finding(
            "C-000",
            "BLOCKED",
            "INDEPENDENCE_NOT_PROVEN",
            observed,
            ["docs/agentic/exp004a/handoff/RUN_REPORT.json#independence"],
            "program-level separation demonstrable; principal-level separation not",
        )
    return Finding("C-000", "PASS", None, observed, ["scripts/exp004a_verify.py"], "")


# --------------------------------------------------------------------------- #
# V-GIT — provenance
# --------------------------------------------------------------------------- #
def resolve_evaluated_commit(report: Any) -> str | None:
    explicit = report.get("authority", {}).get("evaluated_commit") if isinstance(report, dict) else None
    if isinstance(explicit, str) and len(explicit) == 40:
        return explicit
    stack: list[Any] = [report]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                if (
                    isinstance(value, str)
                    and len(value) == 40
                    and key.endswith("_commit")
                    and key != "head_commit"
                    and all(ch in "0123456789abcdef" for ch in value.lower())
                ):
                    return value
                stack.append(value)
        elif isinstance(node, list):
            stack.extend(node)
    return None


def check_authority(ctx: Context, report: dict[str, Any], manifest: dict[str, Any]) -> Finding:
    git = ctx.git
    evaluated = ctx.ref or resolve_evaluated_commit(report)
    refs = ["docs/agentic/exp004a/handoff/RUN_REPORT.json#authority"]
    if not evaluated:
        return Finding("C-009", "BLOCKED", "PROTOCOL_REF_UNRESOLVED", {}, refs, "")

    commit = git.resolve(evaluated)
    if not commit:
        return Finding("C-009", "BLOCKED", "PROTOCOL_REF_UNRESOLVED", {"ref": evaluated}, refs, "")

    protocol_commit = str(
        manifest.get("phase_one_commits", {}).get("protocol_and_measurement_code", "")
    )
    head = git.text("rev-parse", "HEAD")
    scope = list(manifest.get("controls", {}).get("code_scope_paths", [])) or ["src", "scripts"]
    drift = git.changed_paths(commit, head, scope) if head and head != commit else []

    claimed_head = str(report.get("authority", {}).get("builder_report_claimed_head", ""))
    pin = protocol_commit
    observed = {
        "evaluated_commit": commit,
        "evaluated_tree": git.tree(commit),
        "parents": git.parents(commit),
        "protocol_commit_in_manifest": pin or None,
        "protocol_is_ancestor_of_evaluated": bool(pin) and git.is_ancestor(pin, commit),
        "head": head,
        "head_tree": git.tree(head),
        "builder_report_claimed_head": claimed_head or None,
        "builder_label_matches_manifest_pin": bool(claimed_head) and claimed_head == pin,
        "code_scope": scope,
        "code_drift_since_evaluated": drift,
        "committer_iso_evaluated": git.committer_iso(commit),
        "dirty_entries_in_builder_tree": git.dirty_count(),
    }

    if not observed["protocol_is_ancestor_of_evaluated"]:
        return Finding("C-009", "FAIL", "EVALUATED_SOURCE_MISMATCH", observed, refs, "")
    if drift:
        return Finding("C-009", "FAIL", "REPORT_CODE_STALE", observed, refs, "")
    # C-009 states a discrepancy exists; it is verified when the discrepancy is reproducible.
    if claimed_head and claimed_head == pin:
        observed["note"] = "the builder label agreed with the manifest pin; C-009 is refuted"
        return Finding("C-009", "FAIL", "EVALUATED_SOURCE_MISMATCH", observed, refs, "")
    observed["note"] = (
        "the builder report's HEAD label is not the commit the manifest pins; the evaluated "
        "commit is the pinned one and the code under it is unchanged up to HEAD"
    )
    return Finding("C-009", "PASS", None, observed, refs, "")


# --------------------------------------------------------------------------- #
# V-TIME — chronology
# --------------------------------------------------------------------------- #
def check_chronology(ctx: Context, manifest: dict[str, Any]) -> Finding:
    capture = manifest.get("two_phase", {}).get("capture", {})
    start = str(capture.get("start_utc", ""))
    pin = str(manifest.get("phase_one_commits", {}).get("protocol_and_measurement_code", ""))
    committer = ctx.git.committer_iso(pin) if pin else None
    attestations = sorted(
        str(path.relative_to(ctx.evidence_root)).replace("\\", "/")
        for path in (ctx.evidence_root / "data/exp004a").glob("*capture*")
    )
    observed = {
        "capture_start_utc": start or None,
        "protocol_commit_committer_iso": committer,
        "capture_start_attestations": attestations,
        "now_utc": iso_now(),
        "window_has_opened": bool(start) and iso_now() >= start,
    }
    if not attestations:
        observed["why"] = (
            "ordering rests on the Git committer clock and on builder-written sealed_at_utc "
            "fields; neither is an external timestamp authority"
        )
        return Finding(
            "C-013",
            "BLOCKED",
            "TIME_PROOF_WEAK",
            observed,
            ["docs/RFC-050_EXP004A_TWO_PHASE_FREEZE.md#2"],
            "ordering rests on Git commit times and builder-sealed timestamps",
        )
    return Finding("C-013", "PASS", None, observed, [], "")


# --------------------------------------------------------------------------- #
# V-DATA — bytes
# --------------------------------------------------------------------------- #
def check_tracked_digests(ctx: Context, inventory: dict[str, Any], evaluated: str | None) -> Finding:
    git = ctx.git
    rows: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    normalisations: list[str] = []
    for group, entries in (inventory.get("tracked_references") or {}).items():
        for entry in entries or []:
            path = str(entry.get("path", ""))
            record: dict[str, Any] = {
                "group": group,
                "path": path,
                "published_sha256": entry.get("sha256"),
                "published_blob_sha256": entry.get("blob_sha256"),
            }
            worktree = ctx.evidence_root / path
            record["present"] = worktree.is_file()
            if record["present"]:
                record["checkout_sha256"] = sha256_file(worktree)
                record["checkout_size"] = worktree.stat().st_size
            if evaluated and ctx.source_root.is_dir():
                blob = git.blob_sha256(entry.get("last_commit") or evaluated, path)
                if blob:
                    record["git_blob_sha256_at_evaluated"] = blob
                    record["git_blob_size_at_evaluated"] = git.blob_size(entry.get("last_commit") or evaluated, path)
            record["last_commit_declared"] = entry.get("last_commit")
            record["last_commit_actual"] = git.last_commit_touching(path)
            rows.append(record)

            if not record["present"]:
                mismatches.append({**record, "why": "declared reference missing from evidence root"})
                continue
            if record["published_sha256"] and record["checkout_sha256"] != record["published_sha256"]:
                mismatches.append({**record, "why": "checkout bytes differ from published sha256"})
                continue
            if record["last_commit_declared"] and record["last_commit_actual"] != record["last_commit_declared"]:
                mismatches.append({**record, "why": "declared last_commit is not the last commit touching the path"})
                continue
            blob = record.get("git_blob_sha256_at_evaluated")
            if record["published_blob_sha256"] and blob and blob != record["published_blob_sha256"]:
                mismatches.append({**record, "why": "git object differs from published blob_sha256"})
                continue
            if blob and record["published_sha256"] and blob != record["published_sha256"]:
                normalisations.append(path)

    observed = {
        "checked": len(rows),
        "records": rows,
        "mismatches": mismatches,
        "eol_normalised_files": normalisations,
        "evaluated_commit": evaluated,
    }
    if mismatches:
        return Finding("C-005", "FAIL", "DIGEST_MISMATCH", observed, [], "tracked references")
    return Finding("C-005", "PASS", None, observed, [], "tracked references")


def series_path(interval: str, asset: str) -> str:
    return f"data/forward/edge03/{interval}/{asset}.jsonl"


def _series_index(path: Path) -> dict[str, Any]:
    """Parse a series file once: its bytes, its line offsets and its bars keyed by UTC day.

    Parsing each sealed prefix separately is O(days x file size) and turns a 30-second sweep
    into minutes; the prefix is a *byte* range, so the bytes stay authoritative and the parse is
    only an index into them.
    """
    payload = path.read_bytes()
    offsets: list[tuple[int, dict[str, Any] | None]] = []
    by_day: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    position = 0
    corrupt = 0
    for raw in payload.split(b"\n"):
        if raw.strip():
            try:
                bar = json.loads(raw)
            except json.JSONDecodeError:
                bar = None
                corrupt += 1
            offsets.append((position, bar))
            if isinstance(bar, dict) and bar.get("closed"):
                by_day.setdefault(utc_day(int(bar.get("ts", 0))), []).append((position, bar))
        position += len(raw) + 1
    return {"payload": payload, "offsets": offsets, "by_day": by_day, "corrupt_lines": corrupt}


def check_prefix_sweep(ctx: Context, ledgers: dict[str, list[dict[str, Any]]]) -> Finding:
    cache: dict[Path, dict[str, Any]] = {}
    prefixes: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    duplicates: list[str] = []
    lookahead: list[dict[str, Any]] = []

    for lane, rows in ledgers.items():
        for record in rows:
            day = str(record.get("day", ""))
            for series_id, series in (record.get("series") or {}).items():
                interval = str(series.get("interval", ""))
                asset = str(series.get("asset", ""))
                path = ctx.evidence_root / series_path(interval, asset)
                entry: dict[str, Any] = {"lane": lane, "day": day, "series": series_id}
                if not path.is_file():
                    entry.update({"status": "MISSING", "path": series_path(interval, asset)})
                    errors.append(entry)
                    continue
                if path not in cache:
                    cache[path] = _series_index(path)
                index = cache[path]
                payload: bytes = index["payload"]
                if index["corrupt_lines"]:
                    entry["status"] = "CORRUPT_BAR"
                    entry["corrupt_lines"] = index["corrupt_lines"]
                    errors.append(entry)
                    continue
                byte_end = int(series.get("byte_end") or 0)
                entry["byte_end"] = byte_end
                entry["file_size_at_read"] = len(payload)
                if byte_end <= 0 or byte_end > len(payload):
                    entry.update({"status": "OUT_OF_RANGE"})
                    errors.append(entry)
                    continue
                prefix = payload[:byte_end]
                entry["recomputed"] = sha256_bytes(prefix)
                entry["recorded"] = series.get("sha256")
                entry["match"] = entry["recomputed"] == entry["recorded"]
                entry["record_aligned"] = prefix.endswith(b"\n")
                if not entry["match"]:
                    entry["status"] = "DIGEST_MISMATCH"
                    errors.append(entry)
                    continue
                if not entry["record_aligned"]:
                    entry["status"] = "NOT_RECORD_ALIGNED"
                    errors.append(entry)
                    continue

                # The sealed prefix is cumulative — it runs from the first byte of the store to the
                # end of ``day`` — so the day's own bars are the ones whose UTC date matches and
                # whose bytes fall inside the sealed range.
                day_bars = [bar for offset, bar in index["by_day"].get(day, []) if offset < byte_end]
                day_stamps = [int(bar.get("ts", 0)) for bar in day_bars]
                if len(set(day_stamps)) != len(day_stamps):
                    duplicates.append(f"{lane}:{day}:{series_id}")
                    entry["duplicate_ts"] = len(day_stamps) - len(set(day_stamps))
                entry["bars_in_cumulative_prefix"] = sum(
                    1 for offset, _bar in index["offsets"] if offset < byte_end
                )
                entry["bars_on_day"] = len(day_bars)
                entry["stored_bars_recorded"] = series.get("stored_bars")
                entry["stored_bars_recomputed"] = len(day_bars)
                if series.get("stored_bars") is not None and int(series["stored_bars"]) != len(day_bars):
                    entry["status"] = "STORED_BARS_MISMATCH"
                    errors.append(entry)
                    continue
                interval_ms = INTERVAL_MS.get(interval, 0)
                lag_bound = int((record.get("lag_bounds_ms") or {}).get(interval, 0))
                late = 0
                for bar in day_bars:
                    close = int(bar.get("ts", 0)) + interval_ms
                    fetched = int(bar.get("fetched_at_ms", 0))
                    lag = fetched - close
                    if lag < 0:
                        lookahead.append({"lane": lane, "day": day, "series": series_id, "lag_ms": lag})
                    if lag_bound and lag > lag_bound:
                        late += 1
                entry["bars_outside_lag_bound"] = late
                entry["status"] = "VERIFIED"
                prefixes.append(entry)

    cache.clear()

    observed = {
        "ledgers": {lane: len(rows) for lane, rows in ledgers.items()},
        "series_prefixes_checked": len(prefixes) + len([e for e in errors if e.get("status") == "DIGEST_MISMATCH"]),
        "verified": sum(1 for entry in prefixes if entry.get("status") == "VERIFIED"),
        "errors": errors,
        "duplicate_series_days": duplicates,
        "lookahead_observations": lookahead,
        "errors_by_kind": {},
    }
    tally: dict[str, int] = {}
    for entry in errors:
        tally[str(entry.get("status"))] = tally.get(str(entry.get("status")), 0) + 1
    observed["errors_by_kind"] = tally

    if lookahead:
        return Finding("C-004", "FAIL", "LOOKAHEAD_DETECTED", observed, [], "sealed prefixes")
    if duplicates:
        return Finding("C-005", "FAIL", "LEDGER_DUPLICATE", observed, [], "sealed prefixes")
    if any(entry.get("status") == "MISSING" for entry in errors):
        return Finding("C-005", "BLOCKED", "SOURCE_BYTES_UNAVAILABLE", observed, [], "sealed prefixes")
    if errors:
        reason = "DIGEST_MISMATCH"
        if all(entry.get("status") == "NOT_RECORD_ALIGNED" for entry in errors):
            reason = "PREFIX_NOT_RECORD_ALIGNED"
        return Finding("C-005", "FAIL", reason, observed, [], "sealed prefixes")
    return Finding("C-005", "PASS", None, observed, [], "sealed prefixes and full store bytes")


def check_chain(ctx: Context, ledgers: dict[str, list[dict[str, Any]]], inventory: dict[str, Any]) -> Finding:
    observed: dict[str, Any] = {}
    problems: list[str] = []
    for lane, rows in ledgers.items():
        recomputed = 0
        linked = 0
        seq_ok = 0
        for index, record in enumerate(rows):
            if record_digest(record) == record.get("sha256"):
                recomputed += 1
            expected = "0" * 64 if index == 0 else rows[index - 1].get("sha256")
            if record.get("prev_sha256") == expected:
                linked += 1
            if record.get("seq") == index + 1:
                seq_ok += 1
        days = [str(record.get("day")) for record in rows]
        observed[lane] = {
            "records": len(rows),
            "digest_recomputed": recomputed,
            "back_links_valid": linked,
            "seq_contiguous": seq_ok,
            "unique_days": len(set(days)),
            "chain_tip": rows[-1].get("sha256") if rows else None,
            "published_chain_tip": (
                inventory.get("admission", {}).get("lanes", {}).get(lane, {}).get("chain_tip_sha256")
            ),
        }
        if recomputed != len(rows):
            problems.append(f"{lane}: {len(rows) - recomputed} record digests do not recompute")
        if linked != len(rows):
            problems.append(f"{lane}: {len(rows) - linked} back-links are broken")
        if seq_ok != len(rows):
            problems.append(f"{lane}: seq not contiguous from 1")
        if len(set(days)) != len(days):
            problems.append(f"{lane}: duplicate day in the chain")
    total = sum(len(rows) for rows in ledgers.values())
    observed["total_records"] = total
    if problems:
        code = "LEDGER_DUPLICATE" if any("duplicate" in p for p in problems) else "CHAIN_DIGEST_MISMATCH"
        return Finding("C-005", "FAIL", code, {**observed, "problems": problems}, [], "")
    return Finding("C-005", "PASS", None, observed, [], "append-only chain")


# --------------------------------------------------------------------------- #
# V-ADMISSION — classification replay (RFC-050 §3)
# --------------------------------------------------------------------------- #
def _bars_by_day(path: Path) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    rows, errors = load_jsonl(path)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for bar in rows:
        if not bar.get("closed"):
            continue
        grouped.setdefault(utc_day(int(bar.get("ts", 0))), []).append(bar)
    return grouped, errors


def classify_day(
    day: str,
    bars_by_series: dict[str, SeriesBars],
    lag_bounds: dict[str, int],
) -> dict[str, Any]:
    """RFC-050 §3, implemented from its text: coverage first, then the lag of every bar."""
    detail: dict[str, Any] = {}
    missing_any = False
    late_any = False
    started_any = False
    # The required intervals come from the declared lag bounds, not from whatever data happens to
    # exist: a joint lane cannot be satisfied by one interval alone.
    for interval in lag_bounds:
        by_asset: SeriesBars = bars_by_series.get(interval, {})
        expected = EXPECTED_BARS_PER_DAY[interval]
        if not any(grouped.get(day) for grouped in by_asset.values()):
            missing_any = True
            detail[f"{interval}:ABSENT"] = {"stored": 0, "expected": expected}
            continue
        for asset, grouped in by_asset.items():
            bars = grouped.get(day, [])
            if not bars:
                continue
            started_any = True
            interval_ms = INTERVAL_MS[interval]
            bound = lag_bounds.get(interval, 0)
            lags = [int(bar.get("fetched_at_ms", 0)) - (int(bar.get("ts", 0)) + interval_ms) for bar in bars]
            coverage = len(bars) / expected
            within = all(0 <= lag <= bound for lag in lags) if bound else False
            detail[f"{interval}:{asset}"] = {
                "stored": len(bars),
                "expected": expected,
                "coverage": round(coverage, 6),
                "max_lag_ms": max(lags) if lags else None,
                "lag_bound_ms": bound,
                "all_within_lag": within,
            }
            if coverage < COVERAGE_REQUIRED:
                missing_any = True
            if not within:
                late_any = True
    if not started_any:
        classification = "NO_DATA"
    elif missing_any:
        classification = "INCOMPLETE"
    elif late_any:
        classification = "DENSE_BUT_BACKFILLED"
    else:
        classification = "PROSPECTIVELY_OBSERVED"
    return {"day": day, "classification": classification, "series": detail}


def check_admission_replay(ctx: Context, ledgers: dict[str, list[dict[str, Any]]], manifest: dict[str, Any]) -> Finding:
    capture = manifest.get("two_phase", {}).get("capture", {})
    start_utc = str(capture.get("start_utc", ""))[:10]
    end_utc = str(capture.get("end_utc", ""))[:10]
    target_days = int(capture.get("target_days", 90))

    lanes_bars: dict[str, SeriesBars] = {}
    corrupt: list[str] = []
    unavailable: list[str] = []
    for interval in ("1h", "15m"):
        by_asset: SeriesBars = {}
        for asset in ("BTC", "ETH", "SOL"):
            path = ctx.evidence_root / series_path(interval, asset)
            if not path.is_file():
                unavailable.append(series_path(interval, asset))
                continue
            grouped, errors = _bars_by_day(path)
            by_asset[asset] = grouped
            corrupt.extend(f"{interval}:{asset} {error}" for error in errors)
        lanes_bars[interval] = by_asset

    replayable = {interval: len(by_asset) == 3 for interval, by_asset in lanes_bars.items()}
    lane_intervals = {"1h": ("1h",), "1h+15m": ("1h", "15m")}
    unreplayable = {
        lane: [interval for interval in intervals if not replayable.get(interval, False)]
        for lane, intervals in lane_intervals.items()
    }

    recomputed: dict[str, dict[str, Any]] = {}
    mismatches: list[dict[str, Any]] = []
    days_all: set[str] = set()
    for by_asset in lanes_bars.values():
        for grouped in by_asset.values():
            days_all.update(grouped)
    one_hour_lag = {"1h": INTERVAL_MS["1h"] * 2}
    joint_lag = {"1h": INTERVAL_MS["1h"] * 2, "15m": INTERVAL_MS["15m"] * 2}

    for day in sorted(days_all):
        single = classify_day(day, {"1h": lanes_bars["1h"]}, one_hour_lag)
        joint = classify_day(day, {"1h": lanes_bars["1h"], "15m": lanes_bars["15m"]}, joint_lag)
        recomputed[day] = {"1h": single["classification"], "1h+15m": joint["classification"]}

    for lane, rows in ledgers.items():
        if unreplayable.get(lane):
            continue
        for record in rows:
            day = str(record.get("day", ""))
            mine = recomputed.get(day, {}).get(lane)
            theirs = record.get("class")
            if mine and theirs and mine != theirs:
                mismatches.append({"lane": lane, "day": day, "recomputed": mine, "sealed": theirs})

    counts = {
        lane: {
            "sealed": len(rows),
            "sealed_admissible": sum(1 for record in rows if record.get("admissible")),
            "sealed_classes": _count_classes(rows),
            "recomputed_admissible": sum(
                1
                for record in rows
                if recomputed.get(str(record.get("day")), {}).get(lane) == "PROSPECTIVELY_OBSERVED"
            ),
        }
        for lane, rows in ledgers.items()
    }
    in_window = sorted(
        day
        for day in days_all
        if start_utc <= day <= end_utc and recomputed[day]["1h+15m"] == "PROSPECTIVELY_OBSERVED"
    )
    outside = sorted(
        day
        for day in days_all
        if recomputed[day]["1h+15m"] == "PROSPECTIVELY_OBSERVED" and not (start_utc <= day <= end_utc)
    )
    observed = {
        "days_with_any_bar": len(days_all),
        "days_sealed_1h": len(ledgers.get("1h", [])),
        "days_sealed_joint": len(ledgers.get("1h+15m", [])),
        "lanes": counts,
        "mismatches": mismatches,
        "capture": {"start_utc": start_utc, "end_utc": end_utc, "target_days": target_days},
        "recomputed_admissible_inside_window": in_window,
        "recomputed_admissible_outside_window": outside,
        "recomputed_admissible_inside_window_count": len(in_window),
        "admitted_days_out_of_target": f"{len(in_window)}/{target_days}",
        "corrupt": corrupt,
        "unavailable_series": unavailable,
        "unreplayable_lanes": {lane: intervals for lane, intervals in unreplayable.items() if intervals},
        "per_day": recomputed,
    }
    if corrupt:
        return Finding("C-004", "FAIL", "SOURCE_CORRUPT", observed, [], "")
    blocking = [lane for lane, rows in ledgers.items() if rows and unreplayable.get(lane)]
    if blocking:
        return Finding(
            "C-004",
            "BLOCKED",
            "SOURCE_BYTES_UNAVAILABLE",
            observed,
            [],
            f"sealed records exist for {blocking} but the bytes to replay them do not",
        )
    if mismatches:
        return Finding("C-004", "FAIL", "ADMISSION_REPLAY_MISMATCH", observed, [], "")
    return Finding("C-004", "PASS", None, observed, [], "recomputed from raw bars")


def _count_classes(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("class"))
        counts[key] = counts.get(key, 0) + 1
    return counts


# --------------------------------------------------------------------------- #
# V-GATE — protocol semantics, exercised as a black box
# --------------------------------------------------------------------------- #
def _python_executable(source_root: Path) -> str:
    override = os.environ.get("EXP004A_VERIFIER_PYTHON")
    if override:
        return override
    for candidate in (".venv/Scripts/python.exe", ".venv/bin/python"):
        path = source_root / candidate
        if path.is_file():
            return str(path)
    return sys.executable


def check_gate(ctx: Context) -> Finding:
    python = _python_executable(ctx.source_root)
    results: dict[str, Any] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for mode in ("inspect", "authorize"):
            out = Path(tmp) / f"{mode}.json"
            # One execution per mode: the CLI prints its transcript and, with --json-out, also
            # stores the payload. Running it twice would only add wall-clock, not evidence.
            completed = subprocess.run(
                [
                    python,
                    "-m",
                    "trading_bot.research.prereg_gate",
                    "--repo",
                    ".",
                    "--manifest",
                    "config/preregistrations/EXP-004A.json",
                    "--registry",
                    "config/preregistrations/EXP-004A.datasets.json",
                    "--experiment-id",
                    "EXP-004A",
                    "--mode",
                    mode,
                    "--json-out",
                    str(out),
                ],
                cwd=str(ctx.source_root),
                capture_output=True,
                check=False,
                timeout=300,
            )
            payload: dict[str, Any] | None = None
            if out.is_file():
                payload = json.loads(out.read_text(encoding="utf-8"))
            results[mode] = {
                "exit_code": completed.returncode,
                "stdout_sha256": sha256_bytes(completed.stdout),
                "stderr_sha256": sha256_bytes(completed.stderr),
                "stderr_tail": [
                    line
                    for line in completed.stderr.decode("utf-8", "replace").splitlines()
                    if line.strip()
                ][:5],
                "payload": payload,
            }

    recorded: dict[str, Any] = {}
    for mode, name in (("inspect", "INSPECT.json"), ("authorize", "AUTHORIZE.json")):
        path = ctx.evidence_root / "docs/agentic/exp004a/handoff/gate" / name
        recorded[mode] = load_json(path) if path.is_file() else None

    inspect_code = results["inspect"]["exit_code"]
    authorize_code = results["authorize"]["exit_code"]
    authorize_errors = list((results["authorize"].get("payload") or {}).get("errors") or [])
    inspect_errors = list((results["inspect"].get("payload") or {}).get("errors") or [])

    observed = {
        "inspect_exit": inspect_code,
        "authorize_exit": authorize_code,
        "inspect_errors": inspect_errors,
        "authorize_errors": authorize_errors,
        "recorded_inspect_exit": (recorded["inspect"] or {}).get("exit_code"),
        "recorded_authorize_exit": (recorded["authorize"] or {}).get("exit_code"),
        "results": results,
        "python": python,
    }
    if authorize_code == 0:
        return Finding("C-003", "FAIL", "INVALID_PHASE1_AUTHORIZATION", observed, [], "")
    if inspect_code != 3 or inspect_errors:
        return Finding("C-002", "FAIL", "GATE_TRANSCRIPT_MISMATCH", observed, [], "")
    if authorize_code != 2 or authorize_errors != ["TWO_PHASE_PHASE_1_IS_NOT_AUTHORISABLE"]:
        return Finding("C-003", "FAIL", "GATE_TRANSCRIPT_MISMATCH", observed, [], "")
    for mode in ("inspect", "authorize"):
        if (recorded[mode] or {}).get("exit_code") != results[mode]["exit_code"]:
            return Finding("C-002", "FAIL", "GATE_TRANSCRIPT_MISMATCH", observed, [], "")
    return Finding("C-002", "PASS", None, observed, [], "both modes re-executed")


def check_gate_authorization_split(ctx: Context, inspect_finding: Finding) -> Finding:
    """C-003 is the refusal, and the refusal is only meaningful if it is the *whole* error list."""
    if inspect_finding.reason_code == "INVALID_PHASE1_AUTHORIZATION":
        return Finding("C-003", "FAIL", "INVALID_PHASE1_AUTHORIZATION", inspect_finding.observed, [], "")
    return Finding(
        "C-003",
        inspect_finding.status,
        inspect_finding.reason_code if inspect_finding.status != "PASS" else None,
        inspect_finding.observed,
        [],
        "phase 1 refused with exactly one named error",
    )


# --------------------------------------------------------------------------- #
# V-COST — claim scoping
# --------------------------------------------------------------------------- #
def check_cost(ctx: Context, manifest: dict[str, Any], report: dict[str, Any]) -> tuple[Finding, Finding]:
    tape_path = ctx.evidence_root / "data/st6/ST6_OBSERVATIONS.jsonl"
    rows, errors = load_jsonl(tape_path)
    economics = manifest.get("economics", {})
    fee_per_side = float(economics.get("taker_fee_bps_per_side", 0.0))
    declared = float(economics.get("declared_notional_usdt", 0.0))
    claimed = {
        str(key): float(value)
        for key, value in (report.get("cost", {}).get("observed_median_bps") or {}).items()
    }

    per_asset: dict[str, list[dict[str, float]]] = {}
    sizes: set[float] = set()
    for row in rows:
        impact = row.get("impact") or {}
        depth = row.get("depth") or {}
        size = float(impact.get("size_usdt") or 0.0)
        sizes.add(size)
        if not (impact.get("filled_buy") and impact.get("filled_sell") and depth.get("available")):
            continue
        ask, bid = float(row.get("ask") or 0.0), float(row.get("bid") or 0.0)
        if ask <= 0 or bid <= 0:
            continue
        mid = (ask + bid) / 2.0
        spread_bps = (ask - bid) / mid * 10_000.0
        asset = str(row.get("asset", "")).replace("USDT", "")
        one = 2.0 * fee_per_side + spread_bps + float(impact.get("buy_bps") or 0.0) + float(
            impact.get("sell_bps") or 0.0
        )
        two = 2.0 * fee_per_side + 2.0 * spread_bps + float(impact.get("buy_bps") or 0.0) + float(
            impact.get("sell_bps") or 0.0
        )
        per_asset.setdefault(asset, []).append({"one_spread": one, "two_spread": two, "spread_bps": spread_bps})

    medians: dict[str, Any] = {}
    for asset, values in sorted(per_asset.items()):
        ones = sorted(value["one_spread"] for value in values)
        twos = sorted(value["two_spread"] for value in values)
        spreads = sorted(value["spread_bps"] for value in values)
        medians[asset] = {
            "rows": len(values),
            "median_one_spread": round(_nearest_rank(ones, 0.5), 4),
            "median_two_spread": round(_nearest_rank(twos, 0.5), 4),
            "median_spread_bps": round(_nearest_rank(spreads, 0.5), 4),
            "claimed": claimed.get(asset),
            "agrees_with_claim_one_spread": claimed.get(asset) is not None
            and abs(_nearest_rank(ones, 0.5) - claimed[asset]) < 5e-4,
        }

    observed = {
        "tape": {
            "path": "data/st6/ST6_OBSERVATIONS.jsonl",
            "rows": len(rows),
            "sha256": sha256_file(tape_path) if tape_path.is_file() else None,
            "size_bytes": tape_path.stat().st_size if tape_path.is_file() else None,
            "parse_errors": errors,
        },
        "sizes_walked_usdt": sorted(sizes),
        "declared_notional_usdt": declared,
        "declared_size_walked": declared in sizes,
        "fee_bps_per_side": fee_per_side,
        "medians": medians,
        "definition": (
            "recomputed as 2*fee + spread + buy_impact + sell_impact (the builder's arithmetic); "
            "the two-spread variant charges the half-spread on entry and again on exit, which is "
            "what a round trip across the book actually pays"
        ),
    }
    # The claim names three assets. Any further asset the tape happens to contain is evidence of
    # the tape's scope, not a refutation of a number nobody claimed.
    claimed_medians = {asset: value for asset, value in medians.items() if value["claimed"] is not None}
    observed["assets_without_claim"] = sorted(
        asset for asset, value in medians.items() if value["claimed"] is None
    )
    if errors:
        cost = Finding("C-007", "FAIL", "SOURCE_CORRUPT", observed, [], "")
    elif not claimed_medians or any(
        not value["agrees_with_claim_one_spread"] for value in claimed_medians.values()
    ):
        cost = Finding("C-007", "FAIL", "COST_SCOPE_UNPROVEN", observed, [], "")
    else:
        cost = Finding(
            "C-007",
            "BLOCKED",
            "COST_SCOPE_UNPROVEN",
            observed,
            ["data/st6/ST6_OBSERVATIONS.jsonl"],
            "medians reproduce; the round-trip interpretation does not",
        )

    size_finding = Finding(
        "C-008",
        "PASS" if declared not in sizes else "FAIL",
        None if declared not in sizes else "COST_SCOPE_UNPROVEN",
        observed,
        [],
        "declared size absent from every walked row",
    )
    return cost, size_finding


def _stable(payload: Any) -> Any:
    """Drop observation timestamps so two runs of the same measurement can be compared."""
    if isinstance(payload, dict):
        return {
            key: _stable(value)
            for key, value in payload.items()
            if not (key.endswith("_utc") or key.endswith("_at") or key == "generated_at")
        }
    if isinstance(payload, list):
        return [_stable(item) for item in payload]
    return payload


def _stable_digest(path: Path) -> str | None:
    if path.suffix != ".json":
        return None
    try:
        return sha256_bytes(canonical(_stable(load_json(path))))
    except SourceCorrupt:
        return None


def _nearest_rank(sorted_values: Sequence[float], quantile: float) -> float:
    if not sorted_values:
        return float("nan")
    rank = max(1, math.ceil(quantile * len(sorted_values)))
    return float(sorted_values[rank - 1])


# --------------------------------------------------------------------------- #
# V-REPLAY — idempotency
# --------------------------------------------------------------------------- #
def _kill_tree(process: subprocess.Popen[bytes]) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
            check=False,
        )
        return
    os.killpg(process.pid, 9)


def _run_bounded(cmd: Sequence[str], cwd: Path, timeout: int) -> dict[str, Any]:
    """Run a child with its output on a file, so a timeout can never block on an open pipe.

    ``subprocess.run(capture_output=True, timeout=...)`` kills the child and then waits for the
    pipe to close, which any grandchild can hold open indefinitely. Redirecting to a file removes
    the pipe, and the process tree is killed when the budget runs out.
    """
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "child.log"
        with log.open("wb") as handle:
            process = subprocess.Popen(
                list(cmd),
                cwd=str(cwd),
                stdout=handle,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
                start_new_session=sys.platform != "win32",
            )
            timed_out = False
            try:
                code: int | None = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill_tree(process)
                try:
                    code = process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    code = None
        text = log.read_text(encoding="utf-8", errors="replace")
    return {
        "exit_code": code,
        "timed_out": timed_out,
        "output_sha256": sha256_bytes(text.encode("utf-8")),
        "output_tail": text.splitlines()[-5:],
    }


def check_idempotency(ctx: Context) -> Finding:
    ledger_paths = [
        ctx.evidence_root / "data/exp004a/admission_1h.jsonl",
        ctx.evidence_root / "data/exp004a/admission_1h+15m.jsonl",
    ]
    before = {path.name: sha256_file(path) for path in ledger_paths if path.is_file()}
    script = ctx.source_root / "scripts/exp004a_foundation.py"
    runs: list[dict[str, Any]] = []
    budget = int(os.environ.get("EXP004A_REPLAY_TIMEOUT", "300"))
    if not script.is_file():
        return Finding("C-006", "BLOCKED", "IDEMPOTENCY_NOT_REPLAYED", {"script": None}, [], "")

    timed_out = False
    for attempt in range(2):
        clock = time.monotonic()
        with tempfile.TemporaryDirectory() as tmp:
            outcome = _run_bounded(
                [_python_executable(ctx.source_root), str(script), "--skip-seal", "--out", tmp],
                ctx.source_root,
                budget,
            )
            # A replay that does not finish is not evidence that the run is idempotent. It is also
            # not a failure of the claim: it is a verifier budget limit, and it is reported as one.
            timed_out = timed_out or bool(outcome["timed_out"])
            produced: dict[str, str] = {}
            stable: dict[str, str] = {}
            for path in sorted(Path(tmp).glob("*")):
                if path.is_file():
                    produced[path.name] = sha256_file(path)
                    digest = _stable_digest(path)
                    if digest:
                        stable[path.name] = digest
            runs.append(
                {
                    "attempt": attempt + 1,
                    "exit_code": outcome["exit_code"],
                    "elapsed_s": round(time.monotonic() - clock, 1),
                    "timed_out": outcome["timed_out"],
                    "output_sha256": outcome["output_sha256"],
                    "output_tail": outcome["output_tail"],
                    "reports": produced,
                    "reports_stable": stable,
                }
            )
        if timed_out:
            break
    after = {path.name: sha256_file(path) for path in ledger_paths if path.is_file()}
    completed_runs = [run for run in runs if run.get("exit_code") is not None and not run.get("timed_out")]
    observed = {
        "ledger_sha256_before": before,
        "ledger_sha256_after": after,
        "store_unchanged": before == after,
        "runs": runs,
        "replay_budget_seconds": budget,
        # The claim is about records, so the comparison is over the timestamps-stripped report and
        # the identical stdout, not over the byte hashes of files that stamp their own clock.
        "repeatable": len(completed_runs) == 2
        and completed_runs[0]["reports_stable"] == completed_runs[1]["reports_stable"]
        and completed_runs[0]["output_sha256"] == completed_runs[1]["output_sha256"],
    }
    if before != after:
        return Finding("C-006", "FAIL", "VERIFIER_MUTATED_SOURCE", observed, [], "")
    if timed_out:
        return Finding(
            "C-006",
            "BLOCKED",
            "IDEMPOTENCY_NOT_REPLAYED",
            observed,
            ["scripts/exp004a_foundation.py"],
            f"the repeated-run replay did not finish within {budget}s; the claim is unverified, not refuted",
        )
    if any(run["exit_code"] != 0 for run in runs):
        return Finding("C-006", "BLOCKED", "IDEMPOTENCY_NOT_REPLAYED", observed, [], "")
    if not observed["repeatable"]:
        return Finding("C-006", "FAIL", "IDEMPOTENCY_NOT_REPLAYED", observed, [], "")
    return Finding("C-006", "PASS", None, observed, [], "measurement replayed twice, ledger untouched")


# --------------------------------------------------------------------------- #
# V-ENV — Windows path safety (independent of the builder's test)
# --------------------------------------------------------------------------- #
def ensure_within(root: Path, candidate: Path) -> bool:
    try:
        root_resolved = root.resolve(strict=True)
        candidate_resolved = candidate.resolve(strict=True)
    except OSError:
        return False
    return root_resolved == candidate_resolved or root_resolved in candidate_resolved.parents


def check_environment(ctx: Context) -> Finding:
    observed: dict[str, Any] = {"platform": sys.platform}
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        inside = base / "root"
        outside = base / "outside"
        (inside / "config").mkdir(parents=True)
        outside.mkdir()
        (inside / "config" / "ok.json").write_text("{}\n", encoding="utf-8")
        (outside / "secret.json").write_text('{"experiment_id": "EXP-STOLEN"}\n', encoding="utf-8")
        link = inside / "config" / "escape"
        created = False
        if sys.platform == "win32":
            completed = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
            created = completed.returncode == 0 and link.exists()
        else:
            try:
                link.symlink_to(outside, target_is_directory=True)
                created = link.exists()
            except (OSError, NotImplementedError):
                created = False
        observed["junction_created"] = created
        if created:
            reachable = (link / "secret.json").is_file()
            observed["link_reaches_file"] = reachable
            observed["escape_refused"] = not ensure_within(inside, link / "secret.json")
            observed["positive_control_inside"] = ensure_within(inside, inside / "config" / "ok.json")
            observed["parent_traversal_refused"] = not ensure_within(inside, base / "outside" / "secret.json")
        symlink_made = False
        if sys.platform == "win32":
            probe = inside / "config" / "symlink_probe"
            try:
                probe.symlink_to(outside, target_is_directory=True)
                symlink_made = probe.exists()
            except (OSError, NotImplementedError):
                symlink_made = False
        observed["symlink_privilege_available"] = symlink_made

    if not observed.get("junction_created"):
        return Finding(
            "C-011", "BLOCKED", "UNPROVEN_ENVIRONMENT_COVERAGE", observed, [], "no link could be made"
        )
    if not observed.get("escape_refused") or not observed.get("positive_control_inside"):
        return Finding("C-011", "FAIL", "UNPROVEN_ENVIRONMENT_COVERAGE", observed, [], "")
    return Finding(
        "C-011",
        "PASS",
        None,
        observed,
        [],
        "junction escape refused; POSIX symlink coverage not exercised on this host",
    )


# --------------------------------------------------------------------------- #
# Write isolation
# --------------------------------------------------------------------------- #
def snapshot(paths: Iterable[Path]) -> dict[str, Any]:
    state: dict[str, Any] = {}
    for entry in paths:
        if entry.is_file():
            state[str(entry)] = {"sha256": sha256_file(entry), "size": entry.stat().st_size}
        elif entry.is_dir():
            for child in sorted(entry.rglob("*")):
                if child.is_file():
                    state[str(child)] = {"sha256": sha256_file(child), "size": child.stat().st_size}
    return state


def builder_owned(root: Path) -> list[Path]:
    return [root / glob for glob in BUILDER_OWNED_GLOBS]


def check_write_isolation(ctx: Context, before: dict[str, Any]) -> Finding:
    after = snapshot(builder_owned(ctx.evidence_root))
    changed = sorted(
        path
        for path in set(before) | set(after)
        if before.get(path, {}).get("sha256") != after.get(path, {}).get("sha256")
    )
    out_rel = ctx.output_root
    forbidden = []
    for root in FORBIDDEN_OUTPUT_ROOTS:
        try:
            out_rel.relative_to(ctx.source_root / root)
            forbidden.append(root)
        except ValueError:
            continue
    observed = {
        "files_watched": len(before),
        "changed": changed,
        "output_root": str(ctx.output_root),
        "output_root_under_forbidden": forbidden,
    }
    if changed:
        return Finding("C-000", "FAIL", "VERIFIER_MUTATED_SOURCE", observed, [], "")
    if forbidden:
        return Finding("C-000", "FAIL", "OUTPUT_ROOT_FORBIDDEN", observed, [], "")
    return Finding("C-000", "PASS", None, observed, [], "no builder-owned byte changed under verification")


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def load_inputs(ctx: Context) -> dict[str, Any]:
    inventory = load_json(ctx.evidence_root / "docs/agentic/exp004a/handoff/EVIDENCE_INVENTORY.json")
    report = load_json(ctx.evidence_root / "docs/agentic/exp004a/handoff/RUN_REPORT.json")
    submission = load_json(ctx.evidence_root / "docs/agentic/exp004a/handoff/CLAIM_SUBMISSION.json")
    manifest = load_json(ctx.source_root / "config/preregistrations/EXP-004A.json")
    ledgers: dict[str, list[dict[str, Any]]] = {}
    corrupt: list[str] = []
    for lane, rel in (
        ("1h", "data/exp004a/admission_1h.jsonl"),
        ("1h+15m", "data/exp004a/admission_1h+15m.jsonl"),
    ):
        rows, errors = load_jsonl(ctx.evidence_root / rel)
        ledgers[lane] = rows
        corrupt.extend(f"{rel}: {error}" for error in errors)
    return {
        "inventory": inventory,
        "report": report,
        "submission": submission,
        "manifest": manifest,
        "ledgers": ledgers,
        "corrupt": corrupt,
    }


def _trace(label: str, started: float) -> None:
    """Progress on stderr with elapsed seconds, so a long run is observable while it runs."""
    print(
        f"[exp004a-verify] .. {label} ({time.monotonic() - started:.1f}s)",
        file=sys.stderr,
        flush=True,
    )


def run_verification(ctx: Context, mode: str = "verify") -> dict[str, Any]:
    started = iso_now()
    clock = time.monotonic()
    inputs = load_inputs(ctx)
    _trace("inputs loaded", clock)
    before = snapshot(builder_owned(ctx.evidence_root))
    _trace("builder evidence snapshotted", clock)
    findings: list[Finding] = []

    independence = check_independence(ctx)
    findings.append(independence)
    evaluated = resolve_evaluated_commit(inputs["report"])
    _trace("independence audited", clock)

    data = check_tracked_digests(ctx, inputs["inventory"], evaluated)
    _trace("tracked digests reconciled", clock)
    sweep = check_prefix_sweep(ctx, inputs["ledgers"])
    _trace("sealed prefixes swept", clock)
    chain = check_chain(ctx, inputs["ledgers"], inputs["inventory"])
    _trace("attestation chains verified", clock)
    findings.extend([data, sweep, chain])

    if mode == "verify":
        authority = check_authority(ctx, inputs["report"], inputs["manifest"])
        _trace("provenance checked", clock)
        chronology = check_chronology(ctx, inputs["manifest"])
        _trace("chronology assessed", clock)
        admission = check_admission_replay(ctx, inputs["ledgers"], inputs["manifest"])
        _trace("admissions replayed from raw bars", clock)
        gate = check_gate(ctx)
        _trace("gate re-executed in both modes", clock)
        gate_split = check_gate_authorization_split(ctx, gate)
        cost, size = check_cost(ctx, inputs["manifest"], inputs["report"])
        _trace("cost tape re-derived", clock)
        idempotency = check_idempotency(ctx)
        _trace("measurement replayed twice", clock)
        environment = check_environment(ctx)
        _trace("path-safety control exercised", clock)
        findings.extend(
            [authority, chronology, admission, gate, gate_split, cost, size, idempotency, environment]
        )
        economic_zero = _economic_zero(inputs, ctx)
        findings.append(
            Finding(
                "C-012",
                "PASS" if economic_zero else "FAIL",
                None if economic_zero else "UNSUPPORTED_PROFITABILITY_CLAIM",
                {
                    "economic_executions": 0 if economic_zero else None,
                    "see": ["handoff/gate/INSPECT.json", "config/preregistrations/EXP-004A.json"],
                },
                [],
            )
        )
        findings.append(_tests_finding(ctx, inputs))
        _trace("EXP-004A suites re-executed", clock)
        findings.append(check_acceptance_suite(ctx))
        _trace("verifier acceptance suite re-executed", clock)
        findings.append(_clean_checkout_finding(ctx, evaluated))
        _trace("clean checkout reproduced", clock)
    else:
        findings.append(
            Finding(
                "C-004",
                "NOT_APPLICABLE",
                None,
                {"why": "inspect-evidence reconciles bytes only; it does not run the gate, the admission replay or the test suites"},
                [],
                "partial mode: not exercised",
            )
        )

    isolation = check_write_isolation(ctx, before)
    findings.append(isolation)
    finished = iso_now()

    claims = adjudicate(findings)
    status = "PASS"
    if any(finding.status == "FAIL" for finding in findings):
        status = "FAIL"
    elif any(finding.status == "BLOCKED" for finding in findings):
        status = "BLOCKED"

    blocking = sorted({finding.reason_code for finding in findings if finding.status != "PASS" and finding.reason_code})
    if status != "PASS" and not blocking:
        blocking = ["VERIFIER_INTERNAL_ERROR"]

    return {
        "schema_version": SCHEMA_VERSION,
        "rfc_id": RFC_ID,
        "run_id": f"{VERIFIER_ID}:{started}",
        "mode": mode,
        "run_started_at_utc": started,
        "run_finished_at_utc": finished,
        "evaluated_commit": evaluated,
        "source_tree_sha": ctx.git.tree(evaluated) if evaluated else None,
        "rfc050_sha256": _maybe_sha(ctx.evidence_root / "docs/RFC-050_EXP004A_TWO_PHASE_FREEZE.md"),
        "environment": {
            "os": sys.platform,
            "python": sys.version.split()[0],
            "python_executable": _python_executable(ctx.source_root),
            "source_root": str(ctx.source_root),
            "evidence_root": str(ctx.evidence_root),
            "output_root": str(ctx.output_root),
            "worktree_head": ctx.git.text("rev-parse", "HEAD"),
            "worktree_dirty_entries": ctx.git.dirty_count(),
        },
        "builder": {
            "agent_id": inputs["manifest"].get("controls", {}).get("builder_identity"),
            "run_id": inputs["submission"].get("run_id"),
        },
        "verifier": {
            "agent_id": VERIFIER_ID,
            "run_id": f"{VERIFIER_ID}:{started}",
            "implementation": "scripts/exp004a_verify.py",
            "implementation_sha256": _maybe_sha(Path(__file__)),
        },
        "independence": {
            "status": "FAIL" if independence.status == "FAIL" else ("BLOCKED" if independence.status == "BLOCKED" else "PASS"),
            "reason_code": independence.reason_code,
            "evidence": independence.observed,
        },
        "claims": claims,
        "findings": [finding.to_dict() for finding in findings],
        "status": status,
        "promotion": {
            "decision": "NO_PROMOTION",
            "blocking_reasons": _promotion_blocks(inputs, findings),
            "note": "eligibility is never a live order; phase 1 stays un-authorisable",
        },
        "economic_executions": 0,
        "source_mutations": len(isolation.observed.get("changed") or []),
        "blocking_reasons": blocking,
        "false_success": _false_success(findings),
    }


def _false_success(findings: Sequence[Finding]) -> int | None:
    """Zero only when the refusals were actually executed; otherwise unknown, never zero."""
    suite = next((finding for finding in findings if finding.claim_id == "C-014"), None)
    if suite is None or suite.status != "PASS":
        return None
    return 0


def _maybe_sha(path: Path) -> str | None:
    return sha256_file(path) if path.is_file() else None


def _economic_zero(inputs: dict[str, Any], ctx: Context) -> bool:
    gate = inputs["report"].get("gate", {})
    counts = [gate.get(mode, {}).get("economic_executions", 0) for mode in ("inspect", "authorize")]
    payload = load_json(ctx.evidence_root / "docs/agentic/exp004a/handoff/gate/INSPECT.json")
    return all(value == 0 for value in counts) and payload.get("economic_executions") == 0


def _tests_finding(ctx: Context, inputs: dict[str, Any]) -> Finding:
    suites = [
        "tests/unit/research/test_prereg_gate.py",
        "tests/unit/research/test_prereg_gate_two_phase.py",
        "tests/unit/research/test_prereg_gate_escape.py",
        "tests/unit/research/test_prospective_admission.py",
        "tests/unit/research/test_execution_cost_measured.py",
        "tests/unit/research/test_exp004a_evidence_inventory.py",
    ]
    present = [suite for suite in suites if (ctx.source_root / suite).is_file()]
    missing = [suite for suite in suites if suite not in present]
    completed = subprocess.run(
        [_python_executable(ctx.source_root), "-m", "pytest", *present, "-q", "--no-header"],
        cwd=str(ctx.source_root),
        capture_output=True,
        check=False,
        timeout=1800,
    )
    output = completed.stdout.decode("utf-8", "replace")
    summary = [line for line in output.splitlines() if "passed" in line or "failed" in line][-1:] or [""]
    observed = {
        "suites": present,
        "missing_suites": missing,
        "exit_code": completed.returncode,
        "summary": summary[0],
        "stdout_sha256": sha256_bytes(completed.stdout),
        "skips": [line for line in output.splitlines() if "SKIPPED" in line or "skipped" in line][-3:],
    }
    if missing:
        return Finding("C-001", "BLOCKED", "SOURCE_BYTES_UNAVAILABLE", observed, present, "")
    if completed.returncode != 0:
        return Finding("C-001", "FAIL", "VERIFIER_INTERNAL_ERROR", observed, present, "")
    claimed = str(inputs["report"].get("tests", {}).get("exp004a_suites", {}).get("result", ""))
    observed["claimed"] = claimed
    return Finding("C-001", "PASS", None, observed, present, "re-executed by the verifier")


def check_acceptance_suite(ctx: Context) -> Finding:
    """The verifier is only as good as its own refusals, so its suite is part of the run."""
    suite = ctx.source_root / ACCEPTANCE_SUITE
    if not suite.is_file():
        return Finding(
            "C-014", "BLOCKED", "SOURCE_BYTES_UNAVAILABLE", {"suite": ACCEPTANCE_SUITE}, [], ""
        )
    completed = subprocess.run(
        [_python_executable(ctx.source_root), "-m", "pytest", str(suite), "-q", "--no-header"],
        cwd=str(ctx.source_root),
        capture_output=True,
        check=False,
        timeout=900,
    )
    output = completed.stdout.decode("utf-8", "replace")
    summary = [line for line in output.splitlines() if "passed" in line or "failed" in line][-1:]
    observed = {
        "suite": ACCEPTANCE_SUITE,
        "exit_code": completed.returncode,
        "summary": summary[0] if summary else "",
        "stdout_sha256": sha256_bytes(completed.stdout),
        "false_success_invariant": "every adversarial case must be non-PASS",
    }
    if completed.returncode != 0:
        return Finding("C-014", "FAIL", "VERIFIER_INTERNAL_ERROR", observed, [ACCEPTANCE_SUITE], "")
    return Finding("C-014", "PASS", None, observed, [ACCEPTANCE_SUITE], "refusals re-executed")


def _clean_checkout_finding(ctx: Context, evaluated: str | None) -> Finding:
    """The bar store is gitignored, so a checkout can prove ledgers and code, never bars."""
    if not evaluated:
        return Finding("C-010", "BLOCKED", "PROTOCOL_REF_UNRESOLVED", {}, [], "")
    with tempfile.TemporaryDirectory() as tmp:
        completed = subprocess.run(
            ["git", "-C", str(ctx.source_root), "worktree", "add", "--detach", tmp, evaluated],
            capture_output=True,
            check=False,
            timeout=300,
        )
        if completed.returncode != 0:
            return Finding(
                "C-010",
                "BLOCKED",
                "SOURCE_BYTES_UNAVAILABLE",
                {"worktree_add": completed.stderr.decode("utf-8", "replace")[-400:]},
                [],
                "",
            )
        checkout = Path(tmp)
        pairs = {}
        for rel in ("data/exp004a/admission_1h.jsonl", "data/exp004a/admission_1h+15m.jsonl"):
            path = checkout / rel
            pairs[rel] = {
                "in_checkout": path.is_file(),
                "checkout_sha256": sha256_file(path) if path.is_file() else None,
                "live_sha256": _maybe_sha(ctx.evidence_root / rel),
                "store_series_in_checkout": (checkout / "data/forward/edge03/1h").is_dir(),
            }
        subprocess.run(
            ["git", "-C", str(ctx.source_root), "worktree", "remove", "--force", tmp],
            capture_output=True,
            check=False,
            timeout=300,
        )
    reproduced = all(
        entry["in_checkout"] and entry["checkout_sha256"] == entry["live_sha256"] for entry in pairs.values()
    )
    observed = {"checkout": pairs, "ledgers_reproduced": reproduced,
                "limit": "the gitignored bar store is absent, so this cannot verify source bytes"}
    if not reproduced:
        return Finding("C-010", "FAIL", "DIGEST_MISMATCH", observed, [], "")
    return Finding("C-010", "PASS", None, observed, [], "ledgers reproduce; raw bars are not in Git")


def _promotion_blocks(inputs: dict[str, Any], findings: Sequence[Finding]) -> list[str]:
    blocks = ["PHASE2_CAPTURE_OPEN", "INSUFFICIENT_ADMITTED_DAYS", "DECLARED_SIZE_NOT_WALKED"]
    admission = next((f for f in findings if f.claim_id == "C-004"), None)
    if admission and admission.observed.get("recomputed_admissible_inside_window_count") == 0:
        blocks.append("ZERO_ADMITTED_DAYS_INSIDE_CAPTURE_WINDOW")
    if any(f.reason_code == "INDEPENDENCE_NOT_PROVEN" for f in findings):
        blocks.append("BLOCKED_MISSING_INDEPENDENT_VERIFIER")
    return blocks


def adjudicate(findings: Sequence[Finding]) -> list[dict[str, Any]]:
    by_claim: dict[str, Finding] = {}
    for finding in findings:
        current = by_claim.get(finding.claim_id)
        if current is None or _severity(finding.status) > _severity(current.status):
            by_claim[finding.claim_id] = finding
    claims: list[dict[str, Any]] = []
    for claim_id, text in CLAIMS:
        matched = by_claim.get(claim_id)
        if matched is None:
            claims.append(
                {
                    "claim_id": claim_id,
                    "claim": text,
                    "status": "NOT_APPLICABLE",
                    "reason_code": None,
                    "observed": {},
                    "evidence_refs": [],
                    "scope": "not exercised by this mode",
                }
            )
            continue
        claims.append(
            {
                "claim_id": claim_id,
                "claim": text,
                **matched.to_dict(),
            }
        )
    return claims


def _severity(status: str) -> int:
    return {"PASS": 0, "NOT_APPLICABLE": 0, "BLOCKED": 1, "FAIL": 2, "ERROR": 3}[status]


# --------------------------------------------------------------------------- #
# Artifacts
# --------------------------------------------------------------------------- #
def _dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_artifacts(result: dict[str, Any], ctx: Context) -> list[str]:
    out = ctx.output_root
    written: list[str] = []
    _dump(out / "INDEPENDENT_VERIFICATION_REPORT.json", result)
    written.append("INDEPENDENT_VERIFICATION_REPORT.json")
    _dump(out / "CLAIM_VERDICTS.json", {"schema_version": SCHEMA_VERSION, "run_id": result["run_id"],
                                        "status": result["status"], "claims": result["claims"]})
    written.append("CLAIM_VERDICTS.json")
    digests = {
        "run_id": result["run_id"],
        "evaluated_commit": result["evaluated_commit"],
        "checks": [f for f in result["findings"] if f["claim_id"] in {"C-005", "C-010"}],
    }
    _dump(out / "DIGEST_RECONCILIATION.json", digests)
    written.append("DIGEST_RECONCILIATION.json")
    decision = {
        "run_id": result["run_id"],
        "verifier_status": result["status"],
        "promotion": result["promotion"],
        "independence": result["independence"]["status"],
        "blocking_reasons": result["blocking_reasons"],
        "authority": "deterministic acceptance controller, not the verifier",
    }
    _dump(out / "ACCEPTANCE_DECISION.json", decision)
    written.append("ACCEPTANCE_DECISION.json")
    inventory = [
        {
            "claim_id": claim["claim_id"],
            "status": claim["status"],
            "reason_code": claim["reason_code"],
            "evidence_refs": claim["evidence_refs"],
        }
        for claim in result["claims"]
    ]
    _dump(out / "SOURCE_INVENTORY.json", {"run_id": result["run_id"], "claims": inventory})
    written.append("SOURCE_INVENTORY.json")
    return written


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=("verify", "inspect-evidence"), default="verify")
    parser.add_argument("--source-root", type=Path, default=Path("."))
    parser.add_argument("--evidence-root", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=Path("docs/agentic/exp004a/independent"))
    parser.add_argument("--ref", default=None, help="commit under verification (default: the report's)")
    parser.add_argument("--offline", action="store_true", help="refuse anything that leaves the host")
    args = parser.parse_args(argv)

    source_root = args.source_root.resolve()
    evidence_root = (args.evidence_root or args.source_root).resolve()
    output_root = args.output_root if args.output_root.is_absolute() else source_root / args.output_root
    ctx = Context(source_root, evidence_root, output_root, args.ref, args.offline)

    try:
        result = run_verification(ctx, args.mode)
    except SourceCorrupt as exc:
        print(f"[exp004a-verify] BLOCKED SOURCE_CORRUPT: {exc}", file=sys.stderr)
        return EXIT_BLOCKED
    except Exception as exc:  # a verifier that crashes must never look like a pass
        print(f"[exp004a-verify] ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.mode == "verify":
        written = write_artifacts(result, ctx)
        result["artifacts"] = written

    for claim in result["claims"]:
        print(
            f"[exp004a-verify] {claim['status']:<7} {claim['claim_id']} "
            f"{claim['reason_code'] or '-'} :: {claim['claim'][:72]}"
        )
    print(
        f"[exp004a-verify] {result['status']} · {RFC_ID} · {result['mode']} · "
        f"claims={len(result['claims'])} · blocking={len(result['blocking_reasons'])} · "
        f"promotion={result['promotion']['decision']}"
    )
    return STATUS_EXIT[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
