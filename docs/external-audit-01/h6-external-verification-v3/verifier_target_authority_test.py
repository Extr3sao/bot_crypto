"""INDEPENDENT VERIFIER — TEST TARGET AUTHORITY assertions.

Run under pytest from the verifier worktree:

    PYTHONPATH=<verifier>/src python -m pytest <this file> -q

Proves that under pytest the project modules resolve INSIDE the verifier worktree
and that their on-disk bytes equal the audited commit's blobs.

Verifier-owned. Touches no builder code.
"""
from __future__ import annotations

import hashlib
import pathlib
import subprocess

AUDITED_COMMIT = "a5487164803fb601f87f2cd4c865929c30da274e"

VERIFIER_ROOT = pathlib.Path(
    subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                   check=True).stdout.decode().strip()).resolve()

MODULES = [
    "trading_bot",
    "trading_bot.research.h6.whitelist",
    "trading_bot.research.h6.conf_lock",
    "trading_bot.research.h6.confirmation_state",
    "trading_bot.research.h6.execution_ledger",
    "trading_bot.research.h6.execution_harness",
    "trading_bot.research.h6.eligibility",
    "trading_bot.research.h6.feature_engine",
    "trading_bot.research.h6.drift_guard",
    "trading_bot.research.h6.hash_validator",
    "trading_bot.shadow.resolver",
    "trading_bot.execution.service",
]


def _resolve(name):
    import importlib
    mod = importlib.import_module(name)
    return pathlib.Path(mod.__file__).resolve()


def test_verifier_root_is_not_main_checkout():
    assert ".worktrees" in VERIFIER_ROOT.parts, VERIFIER_ROOT


def test_trading_bot_resolves_inside_verifier_worktree():
    p = _resolve("trading_bot")
    assert str(p).startswith(str(VERIFIER_ROOT)), (
        "TEST_TARGET_AUTHORITY violated: trading_bot resolved to %s, which is outside %s"
        % (p, VERIFIER_ROOT))


def test_critical_modules_resolve_inside_verifier_worktree():
    bad = {}
    for m in MODULES:
        p = _resolve(m)
        if not str(p).startswith(str(VERIFIER_ROOT)):
            bad[m] = str(p)
    assert not bad, bad


def test_resolved_module_bytes_match_audited_commit():
    mismatches = {}
    for m in MODULES:
        p = _resolve(m)
        rel = p.relative_to(VERIFIER_ROOT).as_posix()
        blob = subprocess.run(["git", "cat-file", "blob", "%s:%s" % (AUDITED_COMMIT, rel)],
                              cwd=str(VERIFIER_ROOT), capture_output=True, check=True).stdout
        disk = p.read_bytes()
        if hashlib.sha256(disk).hexdigest() != hashlib.sha256(blob).hexdigest():
            mismatches[rel] = {
                "on_disk": hashlib.sha256(disk).hexdigest(),
                "audited": hashlib.sha256(blob).hexdigest(),
            }
    assert not mismatches, mismatches


def test_worktree_head_is_audited_commit():
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(VERIFIER_ROOT),
                          capture_output=True, check=True).stdout.decode().strip()
    assert head == AUDITED_COMMIT, "verifier worktree HEAD is %s" % head
