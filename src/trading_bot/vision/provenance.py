"""Which code opened this ledger — recorded *before* the first decision, not after.

RFC-DEF-018 reproduced the sealed runs of DEF-RUN-017 exactly and still had to write
``original_commit = null``: the ``RUN`` header carried the dataset, the lane, the provider
and the risk policy, but not the commit that produced them. Provenance that is
reconstructed afterwards is not provenance — the only honest way to close that gap is to
write the commit down **before** the run reads a single bar.

This module captures facts and nothing else:

* the full commits of ``HEAD`` at capture time (a prefix is not an identifier);
* for every runtime file the lane imports, the SHA-256 of the bytes that will execute and
  the Git blob id those bytes hash to. ``hash-object`` applies the same end-of-line policy
  ``git add`` would, so a CRLF checkout of an LF blob is not mistaken for a modification;
* whether the worktree differed from ``HEAD`` at that instant, split into the paths that
  decide the run (``runtime_dirty``) and the rest of the tree, disclosed by name and count.

It deliberately does **not** publish a verdict. ``complete`` computed by the module that
wrote the block would let the producer certify itself; the verifier re-derives the answer
from the block and from Git. What the producer can do is refuse to look like provenance
when it is not: if Git is absent, the root is not a repository, or a runtime file is
missing, ``unavailable_reason`` says so instead of the block quietly coming out empty.

The policy is stated rather than implied. ``CLEAN_RUNTIME_PATHS`` admits a run whose
*runtime* bytes are exactly the commit's bytes while unrelated files (reports, other
agents' work) are dirty — they cannot change a decision — and discloses the rest of the
tree so a reader is not told the checkout was clean when it was not. A run whose runtime
paths are dirty gets no provenance at all: those bytes are not in the commit.

Read-only with respect to the repository: only ``git`` plumbing that prints. It never
stages, commits, stashes or checks anything out.

RFC-DEF-RUN-019 / WP-04 extends the same mechanism — it does **not** add a second one —
to a *prospective* session. A replay can be described after the fact; a live session
starts, and only then decides. ``capture_session`` wraps the block above with the facts a
session needs to be re-identifiable before its first decision: ``run_id`` (the code and
configuration pin), ``session_id`` (one contiguous execution of that pin), the config
fingerprint, the runtime digest, the interpreter/dependency versions it ran under, the
provider that produced the signals, and the parent session when it resumes a previous
one. ``pinned_identity`` is the digest a resumed session must reproduce; ``drifted`` says
which files moved if it does not.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

SCHEMA = "VISION_RUN_CODE_PROVENANCE_V1"
SESSION_SCHEMA = "VISION_SESSION_PROVENANCE_V1"
POLICY = "CLEAN_RUNTIME_PATHS"
ZERO_SHA = "0" * 40

#: The files whose bytes decide a lane run: what the lane executes, the accounting it
#: executes with, and the strategy/indicator code the signal source asks. A commit that
#: does not contain these exact bytes is not the code that ran.
PROVENANCE_PATHS: tuple[str, ...] = (
    "src/trading_bot/config/settings.py",
    "src/trading_bot/indicators/builtin.py",
    "src/trading_bot/paper/broker.py",
    "src/trading_bot/research/economic_recovery/alpha15.py",
    "src/trading_bot/research/economic_recovery/experiments.py",
    "src/trading_bot/research/families/ema_crossover_family.py",
    "src/trading_bot/risk/manager.py",
    "src/trading_bot/vision/chart.py",
    "src/trading_bot/vision/clock.py",
    "src/trading_bot/vision/contract.py",
    "src/trading_bot/vision/execution.py",
    "src/trading_bot/vision/guards.py",
    "src/trading_bot/vision/lane.py",
    "src/trading_bot/vision/ledger.py",
    "src/trading_bot/vision/provenance.py",
    "src/trading_bot/vision/provider.py",
    "src/trading_bot/vision/quotes.py",
    "src/trading_bot/vision/settings.py",
    "src/trading_bot/vision/signal_sources.py",
)

#: How many dirty paths outside the runtime are named before the block falls back to the
#: count alone. The ledger is an evidence file, not a place to paste a whole ``git status``.
NAMED_DIRTY_PATHS = 20

#: Files a prospective session executes that a lane replay does not: the collector that
#: turns polls into bars, the session wrapper that decides *when* a decision is allowed,
#: and the signal adapter the session may ask. Added to the lane set rather than replacing
#: it, so the session block is a superset a reader can compare with the ``RUN`` block.
SESSION_EXTRA_PATHS: tuple[str, ...] = (
    "src/trading_bot/market_data/minute_collector.py",
    "src/trading_bot/vision/prospective.py",
    "src/trading_bot/vision/signal_sources.py",
)

SESSION_PATHS: tuple[str, ...] = tuple(sorted(set(PROVENANCE_PATHS) | set(SESSION_EXTRA_PATHS)))

#: Distributions whose version can change a decision or an accounting figure. Recorded by
#: name and version; absent ones are reported as ``None`` instead of being omitted, so a
#: reader can tell "not installed" from "not asked".
ENVIRONMENT_DISTRIBUTIONS: tuple[str, ...] = (
    "PyYAML",
    "numpy",
    "pandas",
    "pydantic",
    "pydantic-settings",
    "matplotlib",
    "structlog",
    "tenacity",
)


class RuntimeNotProvable(RuntimeError):
    """FAIL_CLOSED: the bytes about to decide cannot be named, so they must not decide."""

    def __init__(self, reasons: list[str], block: Mapping[str, Any] | None = None) -> None:
        self.reasons = list(reasons)
        self.block = dict(block or {})
        super().__init__(
            "the runtime cannot be identified, so an auditable session is refused: "
            + ", ".join(self.reasons)
        )


class SessionIdentityMismatch(RuntimeError):
    """A resumed session would silently continue on different bytes than it pinned."""

    def __init__(self, reasons: list[str], detail: Mapping[str, Any] | None = None) -> None:
        self.reasons = list(reasons)
        self.detail = dict(detail or {})
        super().__init__(
            "resume refused: the identity pinned at the start of the session no longer "
            "matches: " + ", ".join(self.reasons)
        )


def _git(root: Path, *args: str) -> tuple[bool, bytes]:
    """One read-only plumbing call. ``False`` on any non-zero exit, never an exception."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return False, b""
    if completed.returncode != 0:
        return False, completed.stderr or b""
    return True, completed.stdout


def _text(output: bytes) -> str:
    return output.decode("utf-8", "replace").strip()


def _utc(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_head(root: Path) -> str | None:
    ok, output = _git(root, "rev-parse", "--verify", "HEAD^{commit}")
    head = _text(output) if ok else ""
    return head if len(head) == 40 else None


def worktree_blob(root: Path, relative: str) -> str | None:
    """The object id Git would store for the file on disk, filters applied."""
    ok, output = _git(root, "hash-object", "--", relative)
    blob = _text(output) if ok else ""
    return blob if len(blob) == 40 else None


def dirty_paths(root: Path) -> list[str]:
    """Every path ``git status`` reports as changed, tracked or untracked."""
    ok, output = _git(root, "status", "--porcelain", "--untracked-files=normal")
    if not ok:
        return []
    paths: list[str] = []
    for line in output.decode("utf-8", "replace").splitlines():
        if len(line) < 4:
            continue
        name = line[3:]
        #: A rename is reported as ``old -> new``; the new name is the one on disk.
        if " -> " in name:
            name = name.split(" -> ", 1)[1]
        paths.append(name.strip().strip('"').replace("\\", "/"))
    return sorted(set(paths))


def capture(
    root: Path | str,
    *,
    paths: tuple[str, ...] = PROVENANCE_PATHS,
) -> dict[str, Any]:
    """The block written into the ``RUN`` header before the first bar is processed.

    Facts only. Whether they add up to demonstrated provenance is the verifier's call.
    """
    repo = Path(root)
    head = resolve_head(repo)
    reasons: list[str] = []
    if not (repo / ".git").exists() and not (repo / "HEAD").exists() and head is None:
        #: ``.git`` is a file in a worktree of a worktree (``git worktree add``), so the
        #: directory test alone would refuse a valid checkout; ``HEAD`` covers the rest.
        reasons.append("NOT_A_REPOSITORY")
    elif head is None:
        reasons.append("HEAD_UNRESOLVED")
    elif head == ZERO_SHA:
        reasons.append("HEAD_IS_ZERO")

    files: dict[str, dict[str, str | None]] = {}
    missing: list[str] = []
    for relative in sorted(paths):
        target = repo / relative
        if not target.is_file():
            missing.append(relative)
            continue
        files[relative] = {
            "sha256": sha256_file(target),
            "blob": worktree_blob(repo, relative),
        }

    observed = dirty_paths(repo) if head is not None else []
    declared = set(paths)
    runtime_dirty = [name for name in observed if name in declared]
    outside = [name for name in observed if name not in declared]

    block: dict[str, Any] = {
        "schema": SCHEMA,
        "policy": POLICY,
        #: Sin reloj propio: el instante del bloque es el ``recorded_at_utc`` de la misma
        #: fila ``RUN``, y un segundo campo de hora solo haría que dos corridas idénticas
        #: escribiesen ledgers distintos.
        "commit": head,
        "head_at_capture": head,
        "files": files,
        "runtime_paths": sorted(declared),
        "missing_runtime_paths": missing,
        "worktree": {
            "runtime_dirty": runtime_dirty,
            "dirty_outside_runtime": outside[:NAMED_DIRTY_PATHS],
            "dirty_outside_runtime_total": len(outside),
            "fully_clean": not observed,
        },
    }
    if runtime_dirty:
        reasons.append("RUNTIME_PATHS_DIRTY")
    if missing:
        reasons.append("RUNTIME_PATH_MISSING")
    if not files:
        reasons.append("NO_RUNTIME_BYTES")
    #: An empty list means the capture is usable as evidence; it is *not* a verdict on the
    #: run, which is exactly why the verifier recomputes it.
    block["unavailable_reasons"] = sorted(set(reasons))
    return block


# --------------------------------------------------------------------- sesión viva
#
# The functions below do not decide anything either. They capture, digest and compare;
# the session applies the policy (refuse / stop) and the verifier re-derives the verdict.


def file_hashes(root: Path | str, paths: tuple[str, ...] = SESSION_PATHS) -> dict[str, str]:
    """SHA-256 of the bytes on disk, without asking Git.

    Used per cycle, so it must be cheap: no subprocess, and ``MISSING`` instead of an
    exception when a pinned file disappears mid-session (that is drift, not a crash).
    """
    repo = Path(root)
    out: dict[str, str] = {}
    for relative in sorted(paths):
        target = repo / relative
        out[relative] = sha256_file(target) if target.is_file() else "MISSING"
    return out


def runtime_digest(hashes: Mapping[str, str]) -> str:
    """One digest over ``{path: sha256}`` so a cycle can name the runtime in a few bytes."""
    payload = [[name, str(hashes[name])] for name in sorted(hashes)]
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def config_fingerprint(payload: Mapping[str, Any]) -> str:
    """Digest of the declared configuration, canonicalised so key order cannot change it."""
    return hashlib.sha256(_canonical(dict(payload)).encode("utf-8")).hexdigest()


def environment() -> dict[str, Any]:
    """The interpreter, the platform and the versions of the relevant distributions."""
    versions: dict[str, str | None] = {}
    for name in ENVIRONMENT_DISTRIBUTIONS:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": sys.platform,
        "machine": platform.machine(),
        "executable": sys.executable,
        "distributions": versions,
    }


def environment_digest(block: Mapping[str, Any]) -> str:
    """What a resumed session must reproduce about the interpreter.

    ``executable`` and ``machine`` are disclosed but excluded from the digest: the same
    interpreter reached through a different path is not a different runtime, and claiming
    otherwise would make a resume on the same host look like drift.
    """
    return hashlib.sha256(
        _canonical(
            {
                "python_version": block.get("python_version"),
                "python_implementation": block.get("python_implementation"),
                "platform": block.get("platform"),
                "distributions": block.get("distributions") or {},
            }
        ).encode("utf-8")
    ).hexdigest()


def identity_digest(
    *, commit: str | None, runtime: Mapping[str, str], config_fingerprint_value: str
) -> str:
    """The pin: which commit, which bytes, which configuration. Nothing else.

    Deliberately excludes the worktree disclosure and the environment: the first is a
    property of the checkout, the second is digest-checked separately so a mismatch can be
    named (``ENVIRONMENT_DRIFT``) instead of being folded into one opaque number.
    """
    return hashlib.sha256(
        _canonical(
            {
                "commit": commit,
                "runtime": [[name, str(runtime[name])] for name in sorted(runtime)],
                "config_fingerprint": config_fingerprint_value,
            }
        ).encode("utf-8")
    ).hexdigest()


def drifted(current: Mapping[str, str], pinned: Mapping[str, str]) -> list[str]:
    """Every pinned path whose bytes are no longer the ones that were pinned."""
    changed = [name for name in sorted(pinned) if str(current.get(name)) != str(pinned[name])]
    return changed


def capture_session(
    root: Path | str,
    *,
    config: Mapping[str, Any],
    provider: Mapping[str, Any],
    started_at_ms: int,
    mode: str,
    resume_parent: Mapping[str, Any] | None = None,
    paths: tuple[str, ...] = SESSION_PATHS,
    environment_block: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The block a session writes before its first decision.

    ``run_id`` names the pin (commit + runtime bytes + configuration) and is therefore
    shared by every session that resumes it; ``session_id`` names one contiguous process
    execution of that pin. Both are derived, never random, so the same facts produce the
    same identifiers and a reader can recompute them.
    """
    code = capture(root, paths=paths)
    fingerprint = config_fingerprint(config)
    runtime = {
        name: str((code.get("files", {}).get(name) or {}).get("sha256") or "MISSING")
        for name in sorted(paths)
    }
    digest = runtime_digest(runtime)
    pinned = identity_digest(
        commit=code.get("commit"), runtime=runtime, config_fingerprint_value=fingerprint
    )
    env = dict(environment_block or environment())
    run_id = "run-" + pinned[:20]

    chain: list[dict[str, Any]] = []
    parent_id: str | None = None
    if resume_parent:
        parent_id = str(resume_parent.get("session_id") or "") or None
        chain = [dict(item) for item in (resume_parent.get("chain") or [])]
        chain.append(
            {
                "session_id": parent_id,
                "started_at_ms": resume_parent.get("started_at_ms"),
                "pinned_identity": resume_parent.get("pinned_identity"),
                "runtime_digest": resume_parent.get("runtime_digest"),
            }
        )
    session_id = "sess-" + hashlib.sha256(
        _canonical([pinned, int(started_at_ms), len(chain)]).encode("utf-8")
    ).hexdigest()[:20]

    reasons = sorted(set(str(item) for item in (code.get("unavailable_reasons") or [])))
    if not fingerprint:
        reasons.append("CONFIG_FINGERPRINT_MISSING")
    if not commit_is_valid(code.get("commit")):
        reasons.append("COMMIT_FORMAT")

    block: dict[str, Any] = {
        "schema": SESSION_SCHEMA,
        "run_id": run_id,
        "session_id": session_id,
        "mode": str(mode),
        "live_enabled": False,
        "started_at_ms": int(started_at_ms),
        "started_at_utc": _utc(started_at_ms),
        "code": code,
        "config": {"payload": dict(config), "fingerprint": fingerprint},
        "runtime": {"paths": sorted(paths), "sha256": runtime, "digest": digest},
        "provider": dict(provider),
        "environment": env,
        "environment_digest": environment_digest(env),
        "resume": {
            "resumed": bool(resume_parent),
            "parent_session_id": parent_id,
            "chain": chain,
        },
        "pinned_identity": pinned,
        "unavailable_reasons": sorted(set(reasons)),
    }
    return block


def commit_is_valid(commit: Any) -> bool:
    text = str(commit or "")
    if len(text) != 40 or text == ZERO_SHA:
        return False
    return all(character in "0123456789abcdef" for character in text)


#: Reasons that make a session unprovable and therefore refused. The rest of the block's
#: reasons are disclosures (noise outside the runtime) that do not stop a run.
BLOCKING_REASONS: tuple[str, ...] = (
    "NOT_A_REPOSITORY",
    "HEAD_UNRESOLVED",
    "HEAD_IS_ZERO",
    "RUNTIME_PATHS_DIRTY",
    "RUNTIME_PATH_MISSING",
    "NO_RUNTIME_BYTES",
    "COMMIT_FORMAT",
    "CONFIG_FINGERPRINT_MISSING",
)


def blocking_reasons(block: Mapping[str, Any]) -> list[str]:
    """Why this block cannot identify the bytes that are about to decide."""
    declared = {str(item) for item in (block.get("unavailable_reasons") or [])}
    return [name for name in BLOCKING_REASONS if name in declared]


def assert_provable(block: Mapping[str, Any]) -> dict[str, Any]:
    """FAIL_CLOSED gate. Returns the block when usable, raises when it is not."""
    reasons = blocking_reasons(block)
    if reasons:
        raise RuntimeNotProvable(reasons, block)
    return dict(block)


def resume_reasons(
    previous: Mapping[str, Any], current: Mapping[str, Any]
) -> list[str]:
    """What changed between the pinned session and the run asking to continue it."""
    reasons: list[str] = []
    old_code = previous.get("code") or {}
    new_code = current.get("code") or {}
    if str(old_code.get("commit")) != str(new_code.get("commit")):
        reasons.append("COMMIT_CHANGED")
    old_runtime = {str(k): str(v) for k, v in (previous.get("runtime", {}).get("sha256") or {}).items()}
    new_runtime = {str(k): str(v) for k, v in (current.get("runtime", {}).get("sha256") or {}).items()}
    if drifted(new_runtime, old_runtime):
        reasons.append("RUNTIME_DRIFT")
    if sorted(old_runtime) != sorted(new_runtime):
        reasons.append("RUNTIME_SET_CHANGED")
    old_config = (previous.get("config") or {}).get("fingerprint")
    new_config = (current.get("config") or {}).get("fingerprint")
    if old_config != new_config:
        reasons.append("CONFIG_CHANGED")
    if previous.get("environment_digest") != current.get("environment_digest"):
        reasons.append("ENVIRONMENT_DRIFT")
    if not reasons and previous.get("pinned_identity") != current.get("pinned_identity"):
        #: The pin covers the same facts the checks above name; if it differs and none of
        #: them does, the block itself is inconsistent and cannot be trusted.
        reasons.append("PINNED_IDENTITY_MISMATCH")
    return reasons
