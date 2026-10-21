"""Publish a read-only inventory of the EXP-004A evidence so somebody else can verify it.

This script is a **publisher, not a verifier**. It opens evidence files for reading, computes
sha256 / size / mtime / last-commit for each declared reference, and writes one JSON document.
It makes no ``PASS``/``FAIL`` decision, grants no authorisation and evaluates no claim: the
certifying act is the independent verifier recomputing these numbers from the same bytes.

What it therefore refuses to do:

* follow a symlink or junction out of the repository (declared paths are allowlisted, and the
  resolved path is compared against the repository root afterwards);
* write anywhere near the evidence: the store, the ledgers, ``reports/ai-bots`` (a run
  directory there would spend the ``EXP-004A`` identifier the gate guards) and ``data/`` are
  all refused as ``--out`` targets;
* touch the network, the exchange, or any process that could place an order.

Two properties of the store decide the shape of the output. The capture is live, so a
whole-file digest of a series file is only true for the instant it is computed; and the sealed
attestations already pin an exact byte prefix, so a prefix digest is the stable unit. The
document therefore carries both, and labels which one it is.

Research only. ``economic_executions: 0``.
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

REPO = Path(__file__).resolve().parents[1]

#: Roots the inventory is allowed to read. Anything else is a bug in the caller, not a file.
ALLOWLISTED_ROOTS = (
    "config",
    "data/exp004a",
    "data/forward/edge03",
    "data/st6",
    "docs",
    "scripts",
    "src",
    "tests",
)

#: Roots an output file may never be written into: writing there would alter evidence or
#: occupy the experiment identifier.
FORBIDDEN_OUTPUT_ROOTS = ("data", "reports/ai-bots", "evidence")

#: Declared references, grouped by what they are. Every path is relative to the repository.
TRACKED_REFERENCES: dict[str, tuple[str, ...]] = {
    "protocol": ("docs/RFC-050_EXP004A_TWO_PHASE_FREEZE.md",),
    "preregistration": (
        "config/preregistrations/EXP-004A.json",
        "config/preregistrations/EXP-004A.datasets.json",
        "config/preregistrations/EXP-004A.prior_runs.json",
        "config/preregistrations/EXP-004A.baseline.json",
    ),
    "builder_reports": (
        "docs/agentic/exp004a/RUN_REPORT.json",
        "docs/agentic/exp004a/RUN_REPORT.md",
        "docs/agentic/exp004a/FINAL_REPORT.md",
    ),
    "builder_gate_evidence": (
        "docs/agentic/exp004a/GATE_INSPECT.json",
        "docs/agentic/exp004a/GATE_INSPECT.log",
        "docs/agentic/exp004a/GATE_AUTHORIZE.json",
        "docs/agentic/exp004a/GATE_AUTHORIZE.log",
    ),
    "admission_ledgers": (
        "data/exp004a/admission_1h.jsonl",
        "data/exp004a/admission_1h+15m.jsonl",
    ),
    "implementation": (
        "src/trading_bot/research/prereg_gate.py",
        "src/trading_bot/research/prospective/__init__.py",
        "src/trading_bot/research/prospective/admission.py",
        "src/trading_bot/research/prospective/independence.py",
        "src/trading_bot/research/prospective/ledger.py",
        "src/trading_bot/research/prospective/store.py",
        "src/trading_bot/research/execution_cost/__init__.py",
        "src/trading_bot/research/execution_cost/measured.py",
        "scripts/exp004a_foundation.py",
    ),
    "tests": (
        "tests/unit/research/test_prereg_gate.py",
        "tests/unit/research/test_prereg_gate_two_phase.py",
        "tests/unit/research/test_prereg_gate_escape.py",
        "tests/unit/research/test_prospective_admission.py",
        "tests/unit/research/test_execution_cost_measured.py",
    ),
}

#: The live capture store. Series files are appended by the observer, so their whole-file
#: digest is transient; ``sealed_prefix`` digests are the stable references.
STORE_ROOT = "data/forward/edge03"
STORE_SERIES = tuple(
    f"{STORE_ROOT}/{interval}/{asset}.jsonl"
    for interval in ("1h", "15m")
    for asset in ("BTC", "ETH", "SOL")
)

#: The frozen cost tape the measured component was computed from.
ST6_TAPE = "data/st6/ST6_OBSERVATIONS.jsonl"

DISCLAIMER = (
    "BUILDER_PUBLISHED_INVENTORY_NOT_VERIFICATION: these digests were computed by the "
    "EXP-004A builder. An independent verifier must recompute them from the same bytes and "
    "must not treat this document as evidence of its own correctness."
)


class InventoryError(RuntimeError):
    """An inventory input cannot be published as declared."""


def _utc(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prefix_sha256(path: Path, byte_length: int) -> str:
    with path.open("rb") as handle:
        payload = handle.read(byte_length)
    if len(payload) != byte_length:
        raise InventoryError(f"{path} holds {len(payload)} bytes, {byte_length} were attested")
    return hashlib.sha256(payload).hexdigest()


def _git(*args: str, repo: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _blob(repo: Path, commit: str, relative: str) -> tuple[str, int] | None:
    """sha256 and length of the *committed* bytes, which do not depend on the checkout.

    A tracked file's working-tree digest is not a stable reference on a host with
    ``core.autocrlf=true``: the file on disk can be CRLF while the blob in Git is LF, so a
    verifier comparing its own checkout against a published working-tree hash would report a
    mismatch that is really a line-ending policy. The blob digest is what both sides can agree
    on, and it is the one a clean checkout reproduces.
    """

    completed = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "blob", f"{commit}:{relative}"],
        capture_output=True,
        check=False,
        timeout=120,
    )
    if completed.returncode != 0:
        return None
    payload = completed.stdout
    return hashlib.sha256(payload).hexdigest(), len(payload)


def _under(relative: str, roots: tuple[str, ...]) -> bool:
    return any(relative == root or relative.startswith(root + "/") for root in roots)


def resolve_declared(repo: Path, relative: str) -> Path:
    """Resolve a declared reference, refusing an allowlist breach or a symlink escape.

    The allowlist is checked on the *declared* path and the containment check on the
    *resolved* path. Checking only one of the two would let ``data/exp004a/x`` be a junction to
    ``C:/Users/.../something-else`` and pass, so both are required.
    """

    normalised = relative.replace("\\", "/").strip("/")
    if not normalised:
        raise InventoryError("refusing an empty declared reference")
    # Every declared reference is published verbatim, so it must already be canonical: a
    # ``..`` segment would make the published path describe a different file than the one
    # hashed, which is exactly the confusion an inventory exists to prevent.
    if any(part in ("..", ".") for part in normalised.split("/")):
        raise InventoryError(f"refusing a non-canonical declared reference: {relative!r}")
    if not _under(normalised, ALLOWLISTED_ROOTS):
        raise InventoryError(f"{relative!r} is not under an allowlisted root")
    root = repo.resolve()
    resolved = (root / normalised).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise InventoryError(f"{relative!r} resolves outside {root}: {resolved}") from exc
    return resolved


def check_output_target(repo: Path, target: Path) -> Path:
    """Refuse to write the inventory into anything that is or feeds the evidence."""

    root = repo.resolve()
    resolved = target.resolve()
    for name in FORBIDDEN_OUTPUT_ROOTS:
        forbidden = (root / name).resolve()
        try:
            resolved.relative_to(forbidden)
        except ValueError:
            continue
        raise InventoryError(f"refusing to write inventory output under {name}/: {resolved}")
    return resolved


def describe(repo: Path, relative: str) -> dict[str, Any]:
    path = resolve_declared(repo, relative)
    if not path.is_file():
        raise InventoryError(f"declared reference is missing: {relative}")
    stat = path.stat()
    last_commit = _git("log", "-1", "--format=%H", "--", relative, repo=repo) or None
    tracked = bool(_git("ls-files", "--error-unmatch", "--", relative, repo=repo))
    committed = _blob(repo, last_commit, relative) if last_commit else None
    return {
        "path": relative.replace("\\", "/"),
        "sha256": _sha256(path),
        "size_bytes": stat.st_size,
        "mtime_utc": _utc(stat.st_mtime),
        "last_commit": last_commit,
        "tracked": tracked,
        "blob_sha256": committed[0] if committed else None,
        "blob_size_bytes": committed[1] if committed else None,
        "note": "compare blob_sha256 for a checkout-independent reference; sha256 is this worktree",
    }


def _ledger_records(repo: Path, relative: str) -> list[dict[str, Any]]:
    path = resolve_declared(repo, relative)
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise InventoryError(f"{relative}:{number} is not JSON: {exc}") from exc
            if not isinstance(payload, dict):
                raise InventoryError(f"{relative}:{number} is not an object")
            records.append(payload)
    return records


def _manifest(repo: Path) -> dict[str, Any]:
    path = resolve_declared(repo, "config/preregistrations/EXP-004A.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise InventoryError("the phase-1 manifest is not an object")
    return payload


def _admission(manifest: dict[str, Any], ledgers: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Record what the ledgers say, and where those days sit relative to the frozen window.

    The distinction matters and is not a quibble: the days that are admissible today were
    observed *before* ``capture.start_utc``, so they demonstrate that the mechanism classifies
    a genuinely prospective day and they are not progress against the 90-day window.
    """

    two_phase = manifest.get("two_phase")
    capture = two_phase.get("capture") if isinstance(two_phase, dict) else None
    if not isinstance(capture, dict):
        raise InventoryError("the manifest declares no two_phase.capture block")
    start = str(capture.get("start_utc") or "")
    end = str(capture.get("end_utc") or "")
    if not start or not end:
        raise InventoryError("the capture window has no start/end")

    lanes: dict[str, Any] = {}
    for name, records in ledgers.items():
        admissible = sorted(
            str(record.get("day")) for record in records if record.get("admissible") is True
        )
        inside = [day for day in admissible if start[:10] <= day <= end[:10]]
        lanes[name] = {
            "records": len(records),
            "admissible": len(admissible),
            "admissible_days": admissible,
            "admissible_days_inside_capture_window": inside,
            "admissible_days_outside_capture_window": [
                day for day in admissible if day not in inside
            ],
            "first_day": records[0].get("day") if records else None,
            "last_day": records[-1].get("day") if records else None,
            "chain_tip_sha256": records[-1].get("sha256") if records else None,
        }
    return {
        "capture": {
            "start_utc": start,
            "end_utc": end,
            "target_days": capture.get("target_days"),
            "closed": capture.get("closed"),
            "window_has_opened": start[:10] <= datetime.now(tz=UTC).strftime("%Y-%m-%d"),
        },
        "lanes": lanes,
        "declared_notional_usdt": (manifest.get("economics") or {}).get("declared_notional_usdt"),
        "acceptance_min_oos_trading_days": (manifest.get("acceptance") or {}).get(
            "min_oos_trading_days"
        ),
    }


def _sealed_prefixes(
    repo: Path, ledgers: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    """Recompute each ledger's pinned prefix digest, per ledger, at its latest byte offset.

    This is the only cross-check the publisher performs, and it is reported as a builder
    observation rather than as a verdict: the verifier recomputes it independently.
    """

    report: dict[str, Any] = {}
    for name, records in ledgers.items():
        latest: dict[str, dict[str, Any]] = {}
        for record in records:
            series = record.get("series")
            if not isinstance(series, dict):
                continue
            for key, entry in series.items():
                if not isinstance(entry, dict):
                    continue
                byte_end = entry.get("byte_end")
                if not isinstance(byte_end, int):
                    continue
                previous = latest.get(key)
                if previous is None or byte_end > previous["byte_end"]:
                    latest[key] = {"byte_end": byte_end, "sha256": entry.get("sha256")}
        checks: list[dict[str, Any]] = []
        for key in sorted(latest):
            interval, _, asset = key.partition(":")
            relative = f"{STORE_ROOT}/{interval}/{asset}.jsonl"
            path = resolve_declared(repo, relative)
            entry = latest[key]
            if not path.is_file():
                checks.append({"series": key, "status": "SOURCE_BYTES_UNAVAILABLE"})
                continue
            recomputed = _prefix_sha256(path, int(entry["byte_end"]))
            checks.append(
                {
                    "series": key,
                    "path": relative,
                    "byte_end": entry["byte_end"],
                    "prefix_sha256_recorded": entry["sha256"],
                    "prefix_sha256_recomputed": recomputed,
                    "prefix_digest_equal": recomputed == entry["sha256"],
                    "file_size_bytes": path.stat().st_size,
                }
            )
        report[name] = checks
    return report


def build(repo: Path) -> dict[str, Any]:
    """Assemble the inventory document. Reads only; the caller decides where it goes."""

    repo = repo.resolve()
    head = _git("rev-parse", "HEAD", repo=repo)
    if not head:
        raise InventoryError(f"{repo} is not a git repository")

    tracked: dict[str, list[dict[str, Any]]] = {}
    for group, references in TRACKED_REFERENCES.items():
        tracked[group] = [describe(repo, relative) for relative in references]

    store: list[dict[str, Any]] = []
    for relative in STORE_SERIES:
        path = resolve_declared(repo, relative)
        if not path.is_file():
            store.append({"path": relative, "status": "SOURCE_BYTES_UNAVAILABLE"})
            continue
        stat = path.stat()
        store.append(
            {
                "path": relative,
                "status": "PRESENT",
                "size_bytes": stat.st_size,
                "mtime_utc": _utc(stat.st_mtime),
                "whole_file_sha256_transient": _sha256(path),
                "gitignored": _is_ignored(repo, relative),
            }
        )

    ledgers = {
        name: _ledger_records(repo, relative)
        for name, relative in (
            ("1h", "data/exp004a/admission_1h.jsonl"),
            ("1h+15m", "data/exp004a/admission_1h+15m.jsonl"),
        )
    }
    manifest = _manifest(repo)

    tape = resolve_declared(repo, ST6_TAPE)
    tape_entry: dict[str, Any] = {"path": ST6_TAPE}
    if tape.is_file():
        tape_entry.update(
            {
                "sha256": _sha256(tape),
                "size_bytes": tape.stat().st_size,
                "mtime_utc": _utc(tape.stat().st_mtime),
                "rows": sum(1 for line in tape.open("rb") if line.strip()),
            }
        )
    else:
        tape_entry["status"] = "SOURCE_BYTES_UNAVAILABLE"

    return {
        "schema_version": "1.0",
        "artifact": "EXP004A_EVIDENCE_INVENTORY",
        "role": "BUILDER_PUBLISHED_READ_ONLY_INVENTORY_NOT_VERIFICATION",
        "disclaimer": DISCLAIMER,
        "digest_policy": (
            "Both digests are published because they answer different questions. If you hash "
            "a checkout on disk, compare against sha256. If you hash the git object at "
            "last_commit, compare against blob_sha256. The two differ wherever end-of-line "
            "normalisation applies and coincide for a tree pinned -text. For the live store, "
            "compare only attested byte prefixes."
        ),
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repository": {
            "root": str(repo),
            "head_commit": head,
            "head_tree": _git("rev-parse", "HEAD^{tree}", repo=repo),
            "branch": _git("rev-parse", "--abbrev-ref", "HEAD", repo=repo),
        },
        "allowlisted_roots": list(ALLOWLISTED_ROOTS),
        "forbidden_output_roots": list(FORBIDDEN_OUTPUT_ROOTS),
        "tracked_references": tracked,
        "live_store": {
            "root": STORE_ROOT,
            "note": (
                "appended by the forward observer, therefore outside git and still growing; "
                "whole-file digests are transient, sealed prefix digests are stable"
            ),
            "series": store,
        },
        "cost_tape": tape_entry,
        "admission": _admission(manifest, ledgers),
        "builder_observations": {
            "label": "BUILDER_OBSERVATION_UNVERIFIED_NOT_CERTIFICATION",
            "sealed_prefixes": _sealed_prefixes(repo, ledgers),
        },
        "economic_executions": 0,
    }


def _is_ignored(repo: Path, relative: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(repo), "check-ignore", "-q", relative],
        capture_output=True,
        check=False,
        timeout=120,
    )
    return completed.returncode == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO / "docs" / "agentic" / "exp004a" / "handoff" / "EVIDENCE_INVENTORY.json",
    )
    args = parser.parse_args(argv)

    try:
        document = build(args.repo)
        target = check_output_target(args.repo, args.out)
    except InventoryError as error:
        print(f"[inventory] REFUSED {error}", file=sys.stderr)
        return 2

    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    target.write_text(payload, encoding="utf-8", newline="\n")
    print(
        f"[inventory] wrote {target} · head={document['repository']['head_commit'][:7]} · "
        f"references={sum(len(v) for v in document['tracked_references'].values())} · "
        f"economic_executions=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
