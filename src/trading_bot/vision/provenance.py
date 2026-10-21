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
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

SCHEMA = "VISION_RUN_CODE_PROVENANCE_V1"
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
