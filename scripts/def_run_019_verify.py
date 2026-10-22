"""DEF-RUN-019 / WP-04D — does a prospective session's block prove what it claims?

This verifier is the *other* agent. It does not import ``trading_bot``, does not import
the module that produced the block, and does not accept the producer's word for anything:
it re-reads the hash chain, re-hashes the files the run says it executed, asks Git again,
and recomputes every digest from the published fields. Its canonicalisation is written
here, once, as the published contract of ``VISION_SESSION_PROVENANCE_V1``:

* ``pinned_identity = sha256(json({"commit", "runtime": [[path, sha256]...sorted],
  "config_fingerprint"}))``;
* ``run_id = "run-" + pinned_identity[:20]``;
* ``environment_digest = sha256(json({"python_version", "python_implementation",
  "platform", "distributions"}))``;
* ``session_id = "sess-" + sha256(json([pinned_identity, started_at_ms, len(chain)]))[:20]``;
* ``config_fingerprint = sha256(json(payload))`` and ``runtime.digest =
  sha256(json([[path, sha256]...sorted]))``, both with ``sort_keys=True`` and
  ``separators=(",", ":")``.

Three states, never two: ``PASS`` means every claim in the block held against Git on this
machine; ``FAIL`` means the block exists and something in it does not hold; ``NOT_EVIDENCED``
means there was nothing to check (a historical session with no block). A domain that
passes never upgrades another that fails, and a global verdict is never derived from a
subdomain that happened to work.

Usage::

    python scripts/def_run_019_verify.py --session reports/.../session --out VERDICT.json
    python scripts/def_run_019_verify.py --session A --session B --history C
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

SCHEMA = "DEF_RUN_019_VERIFIER_VERDICT_V1"
SESSION_SCHEMA = "VISION_SESSION_PROVENANCE_V1"
POLICY = "CLEAN_RUNTIME_PATHS"
GENESIS = "0" * 64
SHA40 = re.compile(r"^[0-9a-f]{40}$")

#: The floor this verifier demands by its own account. If the producer shortened its list,
#: the block would still agree with itself; these paths make that insufficient.
RUNTIME_FLOOR = (
    "src/trading_bot/market_data/minute_collector.py",
    "src/trading_bot/paper/broker.py",
    "src/trading_bot/research/families/ema_crossover_family.py",
    "src/trading_bot/risk/manager.py",
    "src/trading_bot/vision/lane.py",
    "src/trading_bot/vision/ledger.py",
    "src/trading_bot/vision/prospective.py",
    "src/trading_bot/vision/provenance.py",
    "src/trading_bot/vision/signal_sources.py",
)

PASS, FAIL, NOT_EVIDENCED = "PASS", "FAIL", "NOT_EVIDENCED"


# --------------------------------------------------------------------------- infra


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(payload: Any) -> str:
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def git_read(root: Path, *args: str) -> tuple[bool, bytes]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, check=False, timeout=120
        )
    except (OSError, subprocess.SubprocessError):
        return False, b""
    return completed.returncode == 0, completed.stdout


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            if raw.strip():
                rows.append(json.loads(raw))
    return rows


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


class Checks:
    """Collects checks per domain; a domain's state is the worst of its checks."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def add(self, domain: str, code: str, ok: bool | None, detail: str) -> None:
        state = NOT_EVIDENCED if ok is None else (PASS if ok else FAIL)
        self.rows.append({"domain": domain, "code": code, "state": state, "detail": detail})

    def domain(self, name: str) -> dict[str, Any]:
        rows = [row for row in self.rows if row["domain"] == name]
        failed = [row["code"] for row in rows if row["state"] == FAIL]
        silent = [row["code"] for row in rows if row["state"] == NOT_EVIDENCED]
        state = FAIL if failed else (NOT_EVIDENCED if silent else PASS)
        return {
            "state": state,
            "checks": len(rows),
            "failed": failed,
            "not_evidenced": silent,
        }


# --------------------------------------------------------------------------- chain


def chain_state(path: Path) -> dict[str, Any]:
    """Recompute the append-only hash chain the session published."""

    if not path.is_file():
        return {"ok": None, "reason": "MISSING", "lines": 0}
    previous = GENESIS
    count = 0
    kinds: dict[str, int] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        count += 1
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            return {"ok": False, "reason": f"BAD_JSON_AT_{count}: {exc}", "lines": count}
        entry = row.get("entry")
        if not isinstance(entry, dict):
            return {"ok": False, "reason": f"MISSING_ENTRY_AT_{count}", "lines": count}
        expected = hashlib.sha256(
            canonical(
                {"seq": int(row.get("seq", 0)), "prev_sha256": previous, "entry": entry}
            ).encode("utf-8")
        ).hexdigest()
        if int(row.get("seq", 0)) != count:
            return {"ok": False, "reason": f"SEQ_GAP_AT_{count}", "lines": count}
        if str(row.get("prev_sha256")) != previous:
            return {"ok": False, "reason": f"BROKEN_LINK_AT_{count}", "lines": count}
        if str(row.get("sha256")) != expected:
            return {"ok": False, "reason": f"TAMPERED_LINE_{count}", "lines": count}
        previous = expected
        kind = str(entry.get("kind", "?"))
        kinds[kind] = kinds.get(kind, 0) + 1
    return {"ok": True, "reason": "INTACT", "lines": count, "kinds": kinds}


# --------------------------------------------------------------------------- code


def code_domain(checks: Checks, block: dict[str, Any], root: Path, cache: dict[str, Any]) -> None:
    code = block.get("code") if isinstance(block.get("code"), dict) else {}
    checks.add(
        "code",
        "CODE_BLOCK_PRESENT",
        bool(code),
        f"code keys={sorted(code)[:6]}" if code else "sin bloque de código",
    )
    commit = str(code.get("commit") or "")
    checks.add(
        "code",
        "COMMIT_FORMAT",
        bool(SHA40.match(commit)) and commit != "0" * 40,
        f"commit={commit!r}",
    )
    if commit not in cache:
        ok, output = git_read(root, "rev-parse", "--verify", f"{commit}^{{commit}}")
        cache[commit] = output.decode("ascii", "replace").strip() if ok else None
    resolved = cache[commit]
    checks.add(
        "code",
        "COMMIT_RESOLVES",
        bool(SHA40.match(commit)) and resolved == commit,
        f"git rev-parse {commit[:12]}… -> {str(resolved)[:12]}…",
    )

    files = code.get("files") if isinstance(code.get("files"), dict) else {}
    declared = sorted(str(name) for name in (code.get("runtime_paths") or []))
    checks.add(
        "code",
        "FILES_COVER_DECLARED",
        bool(files) and sorted(files) == declared,
        f"{len(files)} ficheros hasheados, {len(declared)} declarados",
    )
    recorded_runtime = block.get("runtime") if isinstance(block.get("runtime"), dict) else {}
    session_paths = sorted(str(name) for name in (recorded_runtime.get("paths") or []))
    missing = sorted(str(name) for name in (code.get("missing_runtime_paths") or []))
    uncovered = [path for path in RUNTIME_FLOOR if path not in files or path not in session_paths]
    checks.add(
        "code",
        "RUNTIME_PATHS_COVERED",
        not missing and not uncovered,
        f"missing={missing[:4]} no_cubiertos={uncovered[:4]}",
    )

    bound: list[str] = []
    unbound: list[str] = []
    bytes_ok: list[str] = []
    bytes_bad: list[str] = []
    if resolved == commit and files:
        for path, info in sorted(files.items()):
            key = ("blob", commit, str(path))
            if key not in cache:
                ok, output = git_read(root, "rev-parse", f"{commit}:{path}")
                cache[key] = output.decode("ascii", "replace").strip() if ok else None
            recorded_blob = info.get("blob") if isinstance(info, dict) else None
            (bound if cache[key] and cache[key] == recorded_blob else unbound).append(str(path))
            key = ("bytes", commit, str(path))
            if key not in cache:
                #: ``cat-file --filters`` applies the same end-of-line policy as a
                #: checkout, so a CRLF worktree is not mistaken for an edit.
                ok, output = git_read(root, "cat-file", "--filters", f"{commit}:{path}")
                cache[key] = output if ok else None
            recorded = info.get("sha256") if isinstance(info, dict) else None
            payload = cache[key]
            if payload is not None and recorded and hashlib.sha256(payload).hexdigest() == recorded:
                bytes_ok.append(str(path))
            else:
                bytes_bad.append(str(path))
    checks.add(
        "code",
        "BLOBS_AT_COMMIT",
        bool(bound) and not unbound,
        f"{len(bound)} blobs coinciden; discrepan={unbound[:4]}",
    )
    checks.add(
        "code",
        "BYTES_AT_COMMIT",
        bool(bytes_ok) and not bytes_bad,
        f"{len(bytes_ok)} ficheros coinciden byte a byte; discrepan={bytes_bad[:4]}",
    )
    worktree = code.get("worktree") if isinstance(code.get("worktree"), dict) else {}
    dirty = sorted(str(name) for name in (worktree.get("runtime_dirty") or []))
    checks.add(
        "code",
        "WORKTREE_RUNTIME_CLEAN",
        not dirty,
        f"runtime_dirty={dirty[:4]} fuera_del_runtime={worktree.get('dirty_outside_runtime_total')}",
    )
    checks.add(
        "code",
        "POLICY_DECLARED",
        code.get("policy") == POLICY,
        f"policy={code.get('policy')!r}",
    )


# --------------------------------------------------------------------------- identity


def identity_domain(checks: Checks, block: dict[str, Any]) -> None:
    code = block.get("code") if isinstance(block.get("code"), dict) else {}
    runtime = block.get("runtime") if isinstance(block.get("runtime"), dict) else {}
    config = block.get("config") if isinstance(block.get("config"), dict) else {}
    payload = config.get("payload") if isinstance(config.get("payload"), dict) else {}

    checks.add(
        "identity",
        "SCHEMA",
        block.get("schema") == SESSION_SCHEMA,
        f"schema={block.get('schema')!r}",
    )
    runtime_hashes = {
        str(name): str(value) for name, value in (runtime.get("sha256") or {}).items()
    }
    roles = runtime.get("paths") or []
    checks.add(
        "identity",
        "RUNTIME_SET_MATCHES_FILES",
        sorted(runtime_hashes) == sorted(code.get("files") or {})
        and sorted(runtime_hashes) == sorted(str(name) for name in roles),
        f"{len(runtime_hashes)} hashes, {len(roles)} rutas declaradas",
    )

    fingerprint = digest(payload) if payload else ""
    checks.add(
        "identity",
        "CONFIG_FINGERPRINT_RECOMPUTED",
        bool(payload) and fingerprint == config.get("fingerprint"),
        f"publicado={str(config.get('fingerprint'))[:12]}… recalculado={fingerprint[:12]}…",
    )
    checks.add(
        "identity",
        "CONFIG_PRESENT",
        {"timeframe", "symbols", "signal_source", "window_bars", "equity"} <= set(payload),
        f"campos={len(payload)}",
    )
    runtime_digest = digest([[name, runtime_hashes[name]] for name in sorted(runtime_hashes)])
    checks.add(
        "identity",
        "RUNTIME_DIGEST_RECOMPUTED",
        bool(runtime_hashes) and runtime_digest == runtime.get("digest"),
        f"publicado={str(runtime.get('digest'))[:12]}… recalculado={runtime_digest[:12]}…",
    )

    pinned = digest(
        {
            "commit": code.get("commit"),
            "runtime": [[name, runtime_hashes[name]] for name in sorted(runtime_hashes)],
            "config_fingerprint": fingerprint,
        }
    )
    checks.add(
        "identity",
        "PINNED_IDENTITY_RECOMPUTED",
        pinned == block.get("pinned_identity"),
        f"publicado={str(block.get('pinned_identity'))[:12]}… recalculado={pinned[:12]}…",
    )
    checks.add(
        "identity",
        "RUN_ID_DERIVED",
        block.get("run_id") == "run-" + pinned[:20],
        f"run_id={block.get('run_id')!r}",
    )

    resume = block.get("resume") if isinstance(block.get("resume"), dict) else {}
    chain = resume.get("chain") if isinstance(resume.get("chain"), list) else []
    expected_session = "sess-" + digest(
        [pinned, int(block.get("started_at_ms") or 0), len(chain)]
    )[:20]
    checks.add(
        "identity",
        "SESSION_ID_DERIVED",
        block.get("session_id") == expected_session,
        f"publicado={block.get('session_id')!r} recalculado={expected_session!r}",
    )

    environment = block.get("environment") if isinstance(block.get("environment"), dict) else {}
    expected_environment = digest(
        {
            "python_version": environment.get("python_version"),
            "python_implementation": environment.get("python_implementation"),
            "platform": environment.get("platform"),
            "distributions": environment.get("distributions") or {},
        }
    )
    checks.add(
        "identity",
        "ENVIRONMENT_DIGEST_RECOMPUTED",
        expected_environment == block.get("environment_digest"),
        f"publicado={str(block.get('environment_digest'))[:12]}… "
        f"recalculado={expected_environment[:12]}…",
    )
    distributions = environment.get("distributions") or {}
    checks.add(
        "identity",
        "ENVIRONMENT_PRESENT",
        bool(environment.get("python_version")) and len(distributions) >= 5,
        f"python={environment.get('python_version')!r} "
        f"distribuciones={sorted(distributions)[:4]}…",
    )

    provider = block.get("provider") if isinstance(block.get("provider"), dict) else {}
    signal = provider.get("signal") if isinstance(provider.get("signal"), dict) else {}
    data = provider.get("data") if isinstance(provider.get("data"), dict) else {}
    checks.add(
        "identity",
        "PROVIDER_PRESENT",
        bool(signal.get("provider")) and bool(data.get("name")),
        f"signal={signal.get('provider')!r} data={data.get('name')!r}",
    )
    checks.add(
        "identity",
        "MODE_IS_PAPER",
        str(block.get("mode")) == "PAPER" and block.get("live_enabled") is False,
        f"mode={block.get('mode')!r} live_enabled={block.get('live_enabled')!r}",
    )
    checks.add(
        "identity",
        "PRODUCER_CLAIMS_NOTHING",
        not {
            "complete",
            "verdict",
            "certified",
        }
        & set(block),
        f"claves={sorted(set(block) & {'complete', 'verdict', 'certified'})}",
    )


# --------------------------------------------------------------------------- evidence


def evidence_domain(
    checks: Checks, session: Path, entries: list[dict[str, Any]], block: dict[str, Any]
) -> None:
    kinds = [str(entry.get("kind")) for entry in entries]
    provenance_positions = [index for index, kind in enumerate(kinds) if kind == "SESSION_PROVENANCE"]
    checks.add(
        "evidence",
        "PROVENANCE_ROW_ONCE",
        len(provenance_positions) == 1,
        f"{len(provenance_positions)} fila(s) SESSION_PROVENANCE",
    )
    checks.add(
        "evidence",
        "SESSION_START_PRESENT",
        "SESSION_START" in kinds,
        f"kinds={sorted(set(kinds))}",
    )
    cycle_positions = [index for index, kind in enumerate(kinds) if kind == "CYCLE"]
    first_cycle = cycle_positions[0] if cycle_positions else None
    provenance_at = provenance_positions[0] if provenance_positions else None
    checks.add(
        "evidence",
        "PROVENANCE_BEFORE_FIRST_CYCLE",
        None
        if provenance_at is None or first_cycle is None
        else provenance_at < first_cycle,
        f"provenance en {provenance_at}, primera decisión en {first_cycle}",
    )

    pinned = block.get("pinned_identity")
    runtime_digest = (block.get("runtime") or {}).get("digest")
    mismatched = [
        int(entry.get("cycle", 0))
        for entry in entries
        if entry.get("kind") == "CYCLE"
        and (
            (entry.get("provenance") or {}).get("pinned_identity") != pinned
            or (entry.get("provenance") or {}).get("runtime_digest") != runtime_digest
        )
    ]
    cycles = [entry for entry in entries if entry.get("kind") == "CYCLE"]
    checks.add(
        "evidence",
        "EVERY_CYCLE_CARRIES_THE_PIN",
        bool(cycles) and not mismatched,
        f"{len(cycles)} ciclos, discrepan={mismatched[:4]}",
    )
    ending = [entry for entry in entries if entry.get("kind") == "SESSION_END"]
    checks.add(
        "evidence",
        "SUMMARY_CARRIES_THE_PIN",
        bool(ending)
        and (ending[-1].get("provenance") or {}).get("pinned_identity") == pinned,
        f"{len(ending)} fila(s) SESSION_END",
    )

    missing_ledgers: list[str] = []
    broken: list[str] = []
    for entry in cycles:
        ledger = entry.get("ledger") or {}
        relative = str(ledger.get("path") or "")
        target = session / relative if relative else None
        if target is None or not target.is_file():
            missing_ledgers.append(relative or "?")
            continue
        if sha256_file(target) != str(ledger.get("sha256")):
            broken.append(relative)
    checks.add(
        "evidence",
        "CYCLE_LEDGERS_PRESENT",
        bool(cycles) and not missing_ledgers,
        f"faltan={missing_ledgers[:3]}",
    )
    checks.add(
        "evidence",
        "CYCLE_LEDGERS_MATCH_HASH",
        bool(cycles) and not broken,
        f"no coinciden={broken[:3]}",
    )


def stability_domain(
    checks: Checks, entries: list[dict[str, Any]], block: dict[str, Any]
) -> None:
    kinds = [str(entry.get("kind")) for entry in entries]
    drift_positions = [
        index
        for index, entry in enumerate(entries)
        if entry.get("kind") == "BLOCKED" and entry.get("reason") == "RUNTIME_DRIFT"
    ]
    cycle_positions = [index for index, kind in enumerate(kinds) if kind == "CYCLE"]

    if not drift_positions:
        checks.add(
            "stability",
            "NO_DRIFT_OBSERVED",
            True,
            "ninguna fila RUNTIME_DRIFT: el runtime no se movió durante la sesión",
        )
        return
    checks.add("stability", "NO_DRIFT_OBSERVED", False, f"deriva en {drift_positions}")
    after = [position for position in cycle_positions if position > drift_positions[0]]
    checks.add(
        "stability",
        "DRIFT_CONTAINED",
        not after,
        f"ciclos posteriores a la deriva={len(after)}",
    )
    ending = [entry for entry in entries if entry.get("kind") == "SESSION_END"]
    checks.add(
        "stability",
        "DRIFT_DISCLOSED",
        bool(ending) and ending[-1].get("runtime_stable") is False,
        f"summary runtime_stable={(ending[-1] or {}).get('runtime_stable') if ending else None}",
    )


def resume_domain(checks: Checks, session: Path, block: dict[str, Any]) -> None:
    resume = block.get("resume") if isinstance(block.get("resume"), dict) else {}
    chain = resume.get("chain") if isinstance(resume.get("chain"), list) else []
    known = sorted((session / "provenance").glob("session-*.json")) if (
        session / "provenance"
    ).is_dir() else []

    if not resume.get("resumed") and len(known) <= 1:
        checks.add(
            "resume",
            "NO_RESUME_TO_JUDGE",
            None,
            "la sesión no declara reanudación y no hay una anterior que enlazar",
        )
        return
    checks.add(
        "resume",
        "PARENT_DECLARED",
        bool(resume.get("resumed")) and bool(resume.get("parent_session_id")),
        f"resumed={resume.get('resumed')} parent={resume.get('parent_session_id')!r}",
    )
    checks.add(
        "resume",
        "CHAIN_ORDERED",
        bool(chain) and chain[-1].get("session_id") == resume.get("parent_session_id"),
        f"cadena={[item.get('session_id') for item in chain][:4]}",
    )
    pinned = block.get("pinned_identity")
    checks.add(
        "resume",
        "CHAIN_PINNED_IDENTITIES_EQUAL",
        bool(chain) and all(item.get("pinned_identity") == pinned for item in chain),
        "todas las sesiones anteriores comparten pin"
        if chain
        else "sin cadena que comparar",
    )
    linked = {
        item.get("session_id"): item.get("pinned_identity") for item in chain if isinstance(item, dict)
    }
    found: dict[str, Any] = {}
    for path in known:
        payload = read_json(path)
        if payload:
            found[str(payload.get("session_id"))] = payload.get("pinned_identity")
    absent = [name for name in linked if name not in found]
    disagreement = [
        name for name in linked if name in found and found[name] != linked[name]
    ]
    checks.add(
        "resume",
        "PARENT_BLOCKS_ON_DISK",
        bool(linked) and not absent,
        f"sin bloque en disco={absent[:3]}",
    )
    checks.add(
        "resume",
        "PARENT_PINS_AGREE",
        bool(linked) and not disagreement and all(value == pinned for value in found.values()),
        f"discrepan={disagreement[:3]} bloques={len(found)}",
    )


# --------------------------------------------------------------------------- session


def judge_session(session: Path, repo: Path) -> dict[str, Any]:
    checks = Checks()
    stream = session / "STREAM.jsonl"
    chain = chain_state(stream)
    checks.add("chain", "STREAM_PRESENT", stream.is_file(), f"{stream.name}")
    checks.add(
        "chain",
        "CHAIN_INTACT",
        chain.get("ok"),
        f"{chain.get('reason')} líneas={chain.get('lines')}",
    )

    entries = [row["entry"] for row in read_jsonl(stream)]
    rows = [entry for entry in entries if entry.get("kind") == "SESSION_PROVENANCE"]
    #: The chain adds ``kind`` and ``recorded_at_utc`` to every row; the block itself is
    #: the payload beside them, and comparing the file against the whole row would always
    #: look like a disagreement.
    block = (
        {key: value for key, value in rows[0].items() if key not in ("kind", "recorded_at_utc")}
        if rows
        else {}
    )
    file_block = read_json(session / "SESSION_PROVENANCE.json")

    if not block:
        checks.add(
            "identity",
            "PROVENANCE_ROW_PRESENT",
            None,
            "la sesión no publicó bloque de procedencia: nada que verificar, nada que aprobar",
        )
        checks.add("code", "CODE_BLOCK_PRESENT", None, "sin bloque")
        checks.add("evidence", "PROVENANCE_ROW_ONCE", None, "sin fila")
        checks.add("stability", "NO_DRIFT_OBSERVED", None, "sin bloque que fijar")
    else:
        checks.add("identity", "PROVENANCE_ROW_PRESENT", True, f"session_id={block.get('session_id')!r}")
        if file_block is not None:
            checks.add(
                "evidence",
                "PROVENANCE_FILE_MATCHES_ROW",
                canonical(file_block) == canonical(block),
                "SESSION_PROVENANCE.json y la fila de la cadena coinciden"
                if canonical(file_block) == canonical(block)
                else "el fichero y la cadena no coinciden",
            )
        cache: dict[str, Any] = {}
        code_domain(checks, block, repo, cache)
        identity_domain(checks, block)
        evidence_domain(checks, session, entries, block)
        stability_domain(checks, entries, block)
        resume_domain(checks, session, block)

    domains = {
        name: checks.domain(name)
        for name in ("chain", "code", "identity", "evidence", "stability", "resume")
    }
    #: The domains that must hold for *any* session decide its verdict. ``resume`` is
    #: published beside them and only gates when the session claims to be a continuation:
    #: a clean single session must not read as NOT_EVIDENCED because nothing resumed.
    gating = ("chain", "code", "identity", "evidence", "stability")
    if any(domains[name]["state"] == FAIL for name in gating):
        overall = FAIL
    elif any(domains[name]["state"] == NOT_EVIDENCED for name in gating):
        overall = NOT_EVIDENCED
    else:
        overall = PASS
    if overall != FAIL and domains["resume"]["state"] == FAIL:
        overall = FAIL

    reasons = [
        f"{row['domain']}:{row['code']}"
        for row in checks.rows
        if row["state"] in (FAIL, NOT_EVIDENCED)
    ]
    return {
        "session": str(session),
        "session_id": block.get("session_id"),
        "run_id": block.get("run_id"),
        "commit": (block.get("code") or {}).get("commit"),
        "overall": overall,
        "domains": domains,
        "reasons": reasons,
        "checks": checks.rows,
    }


def judge_history(directory: Path) -> dict[str, Any]:
    """A session recorded before the block existed: not a failure, not a pass."""

    block = read_json(directory / "SESSION_PROVENANCE.json")
    entries = [row["entry"] for row in read_jsonl(directory / "STREAM.jsonl")]
    has_row = any(entry.get("kind") == "SESSION_PROVENANCE" for entry in entries)
    has_provenance = block is not None or has_row
    return {
        "session": str(directory),
        #: A pre-control session is not a failure of this work package and not a pass of
        #: it either: the file predates the block, so there is nothing to judge.
        "overall": NOT_EVIDENCED,
        "reason": "THIS_SESSION_HAS_A_BLOCK_USE_SESSION"
        if has_provenance
        else "PRE_CONTROL_SESSION",
        "rows": len(entries),
        "has_provenance": has_provenance,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify prospective-session provenance")
    parser.add_argument("--session", action="append", default=[], help="session directories")
    parser.add_argument("--history", action="append", default=[], help="pre-WP sessions")
    parser.add_argument("--repo", default=None, help="repo root the commits resolve in")
    parser.add_argument("--out", default=None, help="VERDICT.json path")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve() if args.repo else Path(__file__).resolve().parents[1]
    sessions = [judge_session(Path(item).resolve(), repo) for item in args.session]
    history = [judge_history(Path(item).resolve()) for item in args.history]

    states = {row["overall"] for row in sessions}
    if FAIL in states:
        overall = FAIL
    elif NOT_EVIDENCED in states or not sessions:
        overall = NOT_EVIDENCED
    else:
        overall = PASS

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_by": "scripts/def_run_019_verify.py",
        "independent": True,
        "imports_producer": False,
        "repo": str(repo),
        "overall": overall,
        "sessions": sessions,
        "history": history,
        #: A PASS is only counted when the session it describes failed nothing: the number
        #: here is the count of passes that would be lying, and it must be zero.
        "false_success": sum(
            1
            for row in sessions
            if row["overall"] == PASS
            and any(
                row["domains"][name]["state"] != PASS
                for name in ("chain", "code", "identity", "evidence", "stability")
            )
        ),
    }
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
    print(
        json.dumps(
            {
                "overall": overall,
                "sessions": [
                    {
                        "session": Path(row["session"]).name,
                        "overall": row["overall"],
                        "domains": {name: row["domains"][name]["state"] for name in row["domains"]},
                    }
                    for row in sessions
                ],
                "history": [{"session": Path(row["session"]).name, "overall": row["overall"]} for row in history],
            },
            indent=2,
        )
    )
    return 0 if overall == PASS else 1


if __name__ == "__main__":
    sys.exit(main())
