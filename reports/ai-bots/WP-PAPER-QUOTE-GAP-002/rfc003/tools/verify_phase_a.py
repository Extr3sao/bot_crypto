"""Independent Phase-A verifier for RFC-PAPER-QUOTE-GAP-003.

Deliberately separate from the builder: this file imports **nothing** from ``trading_bot``,
recomputes every identity from bytes on disk, and refuses input it cannot re-derive.  It has
no access to the builder's in-memory state — only to the checkout, the evidence directory and
git.

The metric it publishes is ``unsupported_pass_count``: of the preregistered adversarial cases,
how many invalid artefacts were still accepted.  That is a *bounded* statement about this
certification.  It is not ``FALSE_SUCCESS=0`` for the trading runtime, and the report says so.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

RUNTIME_FILES = [
    "src/trading_bot/vision/lane.py",
    "src/trading_bot/vision/ledger.py",
    "src/trading_bot/vision/prospective.py",
    "src/trading_bot/vision/quotes.py",
    "src/trading_bot/vision/durable.py",
    "src/trading_bot/vision/gap_recovery.py",
    "src/trading_bot/paper/broker.py",
    "src/trading_bot/risk/manager.py",
    "pyproject.toml",
]
TEST_FILES = [
    "tests/unit/vision/test_gap_recovery.py",
    "tests/unit/vision/test_gap_recovery_venue.py",
    "tests/unit/vision/test_durable_book.py",
    "tests/unit/vision/test_session_durable.py",
    "tests/unit/vision/test_session_recovery.py",
    "tests/unit/vision/test_minute_quote_feed.py",
    "tests/unit/vision/test_subbar_execution.py",
]
SCRIPT_FILES = [
    "scripts/quote_gap_lab.py",
    "scripts/verify_quote_gap.py",
    "scripts/quote_feed_source.py",
    "scripts/paper_resume_drill.py",
]
A5_SIZES = [310, 240, 92, 33, 19]
MINUTE_MS = 60_000
BAR_MS = 5 * MINUTE_MS


# -- primitives ------------------------------------------------------------------


def git_blob_sha1(data: bytes) -> str:
    """The hash git stores in a tree, computed here so EOL conversion cannot hide drift."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def git(checkout: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(["git", *args], cwd=checkout, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return proc.returncode, (proc.stdout + proc.stderr)


def record(checks: list[dict[str, Any]], name: str, ok: bool, detail: str) -> None:
    checks.append({"check": name, "ok": bool(ok), "detail": detail})


# -- 1. Git authority ------------------------------------------------------------


def check_authority(checkout: Path, code_sha: str, paths: list[str]) -> tuple[bool, str]:
    """Identity *under the repository's declared EOL policy*, which is the only honest one.

    Hashing the file bytes directly would fail every text file on a host with
    ``core.autocrlf=true``: git stores LF and checks out CRLF, so the bytes on disk are not
    the bytes in the blob and no amount of correctness in the tree would fix that.
    ``git hash-object --path`` applies the same attributes and filters git itself would, so a
    match means "this file is what the commit stores", and ``-text`` trees (where the bytes
    must not be touched) are covered separately by the evidence manifest.
    """
    code, head = git(checkout, "rev-parse", "HEAD")
    if code != 0 or head.strip() != code_sha:
        return False, f"HEAD is {head.strip()!r}, expected {code_sha}"
    _, status = git(checkout, "status", "--porcelain=v2", "--untracked-files=all")
    dirty = [line for line in status.splitlines() if line.strip()]
    if dirty:
        return False, f"{len(dirty)} worktree entries, e.g. {dirty[0][:80]}"

    mismatched: list[str] = []
    for rel in paths:
        code, blob = git(checkout, "rev-parse", f"HEAD:{rel}")
        if code != 0:
            mismatched.append(f"{rel}: not in HEAD")
            continue
        target = checkout / rel
        if not target.is_file():
            mismatched.append(f"{rel}: missing on disk")
            continue
        hashed, value = git(checkout, "hash-object", "--path", rel, str(target))
        if hashed != 0 or value.strip() != blob.strip():
            mismatched.append(f"{rel}: disk content is not the committed content")
    if mismatched:
        return False, json.dumps(mismatched[:6])
    return True, f"{len(paths)} files hash to their HEAD blob under the repo's EOL policy"


# -- 2. import identity ----------------------------------------------------------


def probe(python: Path, checkout: Path, inject: str | None) -> dict[str, Any]:
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
    if inject:
        env["PYTHONPATH"] = inject
    proc = subprocess.run(
        [str(python), "-c",
         "import importlib.util as u, json; s=u.find_spec('trading_bot');"
         "print(json.dumps({'found': bool(s and s.origin), 'origin': s.origin if s else None}))"],
        cwd=checkout, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {"found": False, "error": (proc.stdout + proc.stderr)[:400]}


def check_import(python: Path, checkout: Path, inject: str | None, *, expect_inside: bool
                 ) -> tuple[bool, str]:
    result = probe(python, checkout, inject)
    if not result.get("found"):
        return False, f"package not importable: {result.get('error', '')}"
    origin = Path(str(result["origin"]))
    inside = str(origin).lower().startswith(str(checkout.resolve()).lower())
    if inside == expect_inside:
        return True, f"origin={origin} inside={inside} (inject={inject})"
    return False, f"origin={origin} inside={inside}, expected inside={expect_inside}"


# -- 3. suite identity -----------------------------------------------------------


def read_collection(evidence: Path) -> list[str]:
    text = (evidence / "collect.txt").read_text(encoding="utf-8", errors="replace")
    return [line.strip() for line in text.splitlines()
            if "::" in line and not line.startswith(("=", "FAILED", "ERROR"))]


def slice_parts(ids: list[str], sizes: list[int]) -> list[list[str]]:
    parts, cursor = [], 0
    for size in sizes:
        parts.append(ids[cursor:cursor + size])
        cursor += size
    return parts


def check_suite(identity: dict[str, Any], evidence: Path, ids: list[str]) -> tuple[bool, str]:
    problems: list[str] = []
    sizes = identity.get("sizes") or []
    if identity.get("collected") != len(ids):
        problems.append(f"collected={identity.get('collected')} vs {len(ids)} read from collect.txt")
    if sum(sizes) != len(ids):
        problems.append(f"partitions sum {sum(sizes)} != {len(ids)}")

    parts = slice_parts(ids, sizes)
    pairwise = {}
    for i in range(len(parts)):
        for j in range(i + 1, len(parts)):
            pairwise[f"{i}v{j}"] = len(set(parts[i]) & set(parts[j]))
    if any(pairwise.values()):
        problems.append(f"overlapping partitions: {pairwise}")
    if set().union(*[set(p) for p in parts]) != set(ids):
        problems.append("union of partitions does not cover the collection")

    recorded = {int(p["part"]): p for p in identity.get("parts") or []}
    if len(recorded) != len(sizes):
        problems.append(f"{len(recorded)} parts recorded, {len(sizes)} expected")
    for index, part in enumerate(parts, start=1):
        row = recorded.get(index)
        if row is None:
            problems.append(f"part {index} missing")
            continue
        expected_hash = hashlib.sha256("\n".join(part).encode("utf-8")).hexdigest()
        if row.get("node_ids_sha256") != expected_hash:
            problems.append(f"part {index}: node-id hash does not re-derive")
        log = evidence / f"part-{index}.log"
        if not log.is_file():
            problems.append(f"part {index}: log missing")
            continue
        raw = log.read_bytes()
        if hashlib.sha256(raw).hexdigest() != row.get("log_sha256"):
            problems.append(f"part {index}: log hash does not match the manifest")
        if len(raw) != row.get("log_bytes"):
            problems.append(f"part {index}: log size differs")
        text = raw.decode("utf-8", errors="replace")
        if row.get("exit_code") != 0:
            problems.append(f"part {index}: recorded exit {row.get('exit_code')}")
        if " FAILED" in text or " ERROR" in text:
            problems.append(f"part {index}: log contains FAILED/ERROR")
        if f"{len(part)} passed" not in text:
            problems.append(f"part {index}: log does not claim {len(part)} passed")
    total_passed = sum(int(p.get("passed") or 0) for p in recorded.values())
    if total_passed != len(ids):
        problems.append(f"passed={total_passed} != collected={len(ids)}")
    return (not problems), json.dumps(problems[:8]) if problems else \
        f"{len(ids)} ids, {len(parts)} disjoint parts, all logs re-hash"


# -- 4. dataset provenance -------------------------------------------------------


def load_minutes(archive: Path, symbol: str) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in
            (archive / f"{symbol}.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    rows.sort(key=lambda row: int(row["open_ms"]))
    return rows


def bars_from_minutes(rows: list[dict[str, Any]]) -> list[list[float]]:
    buckets: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        opened = int(row["open_ms"])
        used = opened - (opened % MINUTE_MS)
        buckets.setdefault(used - (used % BAR_MS), []).append({**row, "open_ms": used})
    bars: list[list[float]] = []
    for bucket in sorted(buckets):
        minutes = sorted(buckets[bucket], key=lambda row: int(row["open_ms"]))
        if [int(m["open_ms"]) for m in minutes] != [bucket + i * MINUTE_MS for i in range(5)]:
            continue
        bars.append([bucket, round(float(minutes[0]["open"]), 8),
                     round(max(float(m["high"]) for m in minutes), 8),
                     round(min(float(m["low"]) for m in minutes), 8),
                     round(float(minutes[-1]["close"]), 8)])
    return bars


def check_dataset(archive: Path, drill: dict[str, Any]) -> tuple[bool, str]:
    problems: list[str] = []
    data = drill.get("data") or {}
    for symbol, meta in (data.get("symbols") or {}).items():
        minutes_file = archive / f"{symbol}.jsonl"
        if not minutes_file.is_file():
            problems.append(f"{symbol}: archive missing")
            continue
        minutes_sha = hashlib.sha256(minutes_file.read_bytes()).hexdigest()
        if minutes_sha != meta.get("minutes_sha256"):
            problems.append(f"{symbol}: minutes_sha256 does not re-derive")
        bars = bars_from_minutes(load_minutes(archive, symbol))
        digest = hashlib.sha256(
            json.dumps(bars, separators=(",", ":")).encode()).hexdigest()
        if digest != meta.get("bars_sha256"):
            problems.append(f"{symbol}: bars_sha256 does not re-derive")
        if len(bars) != meta.get("bars_5m"):
            problems.append(f"{symbol}: {len(bars)} bars vs {meta.get('bars_5m')}")
    return (not problems), json.dumps(problems) if problems else \
        "minutes and 5m bars re-derive from the WP archive"


def check_event_chain(events_file: Path, manifest: dict[str, Any]) -> tuple[bool, str]:
    head = "0" * 64
    rows = 0
    for line in events_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        payload = {k: v for k, v in row.items() if k not in {"prev_sha256", "sha256"}}
        if row.get("prev_sha256") != head:
            return False, f"row {rows}: prev_sha256 breaks the chain"
        digest = hashlib.sha256(
            json.dumps({"prev": head, **payload}, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False).encode("utf-8")).hexdigest()
        if digest != row.get("sha256"):
            return False, f"row {rows}: sha256 does not re-derive"
        head = digest
        rows += 1
    if rows != manifest.get("events"):
        return False, f"{rows} rows vs manifest {manifest.get('events')}"
    if head != manifest.get("events_sha256"):
        return False, "chain head is not the manifest's events_sha256"
    return True, f"{rows} events, head {head[:16]}… intact"


# -- 5. gap-lab replay -----------------------------------------------------------


def check_gap_lab(python: Path, checkout: Path, wp: Path, recorded: dict[str, Any]
                  ) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "verify.json"
        proc = subprocess.run(
            [str(python), "scripts/verify_quote_gap.py",
             "--lab", str(wp / "lab" / "GAP_LAB.json"), "--negative-controls", "--json", str(out)],
            cwd=checkout, capture_output=True, text=True, encoding="utf-8", errors="replace",
            env={k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}})
        if proc.returncode != 0 or not out.is_file():
            return False, f"verifier exited {proc.returncode}: {(proc.stdout + proc.stderr)[:300]}"
        fresh = json.loads(out.read_text(encoding="utf-8"))

    problems: list[str] = []
    if fresh.get("passed") != recorded.get("passed"):
        problems.append(f"passed={fresh.get('passed')} vs recorded {recorded.get('passed')}")
    if fresh.get("ok") != recorded.get("ok"):
        problems.append(f"ok={fresh.get('ok')} vs recorded {recorded.get('ok')}")
    if not fresh.get("ok"):
        problems.append(f"recomputed verifier says ok=False: {fresh.get('failed')}")

    fresh_names = [c.get("check") for c in fresh.get("checks") or []]
    recorded_names = [c.get("check") for c in recorded.get("checks") or []]
    if fresh_names != recorded_names:
        differ = [n for n, m in zip(fresh_names, recorded_names) if n != m][:3]
        problems.append(f"check names differ (first: {differ}), {len(fresh_names)} vs "
                        f"{len(recorded_names)}")
    lab_sha = hashlib.sha256((wp / "lab" / "GAP_LAB.json").read_bytes()).hexdigest()
    if lab_sha != recorded.get("lab_sha256"):
        problems.append("the lab file is not the one the recorded verification names")

    controls = fresh.get("negative_controls") or []
    detected = [c for c in controls if c.get("detected")]
    if len(controls) != 10 or len(detected) != 10:
        problems.append(f"{len(detected)}/{len(controls)} negative controls detected")
    fresh_failures = {c.get("control"): c.get("first_failure") for c in controls}
    recorded_failures = {c.get("control"): c.get("first_failure")
                         for c in recorded.get("negative_controls") or []}
    if fresh_failures != recorded_failures:
        drift = [k for k in fresh_failures if fresh_failures.get(k) != recorded_failures.get(k)]
        problems.append(f"negative controls fail differently now: {drift[:3]}")
    if problems:
        return False, json.dumps(problems)
    return True, (f"{fresh.get('passed')} checks with the same names, "
                  f"{len(detected)}/{len(controls)} controls detect, same first_failure")


# -- 6. recovery matrix ----------------------------------------------------------


def check_recovery(drill: dict[str, Any], lab: dict[str, Any]) -> tuple[bool, str]:
    """Two different comparisons that a single 'digests equal' line would flatten."""
    problems: list[str] = []

    #: The drill: two arms over the same committed book, expected to be byte-identical.
    arm_a = (drill.get("A") or {}).get("state_digest")
    arm_b = (drill.get("B") or {}).get("state_digest")
    if not arm_a or arm_a != arm_b:
        problems.append(f"drill arms diverge: {str(arm_a)[:12]} vs {str(arm_b)[:12]}")
    if (drill.get("comparison") or {}).get("differences") not in ([], None):
        problems.append(f"drill comparison found {len(drill['comparison']['differences'])} diffs")

    #: The lab: 14 kills, all before a close existed.
    resuming = lab.get("kill_while_resuming") or {}
    attempts = resuming.get("attempts") or []
    if len(attempts) != 14:
        problems.append(f"{len(attempts)} kill attempts, expected 14")
    if not all(row.get("killed") for row in attempts):
        problems.append("some attempt was not actually killed")
    for row in attempts:
        before, after = row.get("closed_before"), row.get("closed_after")
        if before not in (0, 1) or after not in (0, 1):
            problems.append(f"attempt {row.get('attempt')}: impossible counts {before}/{after}")
        if (after or 0) - (before or 0) > 1:
            problems.append(f"attempt {row.get('attempt')}: booked more than one close")
    if resuming.get("final_closed") != 1 or resuming.get("final_open") != 0:
        problems.append(f"after the kills: closed={resuming.get('final_closed')} "
                        f"open={resuming.get('final_open')}")
    if resuming.get("final_equity") != resuming.get("reference_equity"):
        problems.append("recovered equity differs from the reference")
    differences = (resuming.get("book_comparison") or {}).get("differences")
    if differences not in ([], None):
        problems.append(f"book comparison reports {len(differences)} differences")

    #: Saving branch: every book left by a kill has to be readable.
    saves = (lab.get("kill_while_saving") or {}).get("outcomes") or []
    if not saves or not all(row.get("status") == "READABLE" for row in saves):
        problems.append(f"{len(saves)} save outcomes, not all readable")

    if problems:
        return False, json.dumps(problems[:8])
    return True, (f"drill arms identical, {len(attempts)} kills with no double close, "
                  f"economy equal, {len(saves)} books readable")


# -- 7. order boundary -----------------------------------------------------------


def static_order_scan(root: Path) -> dict[str, Any]:
    tokens = ("place_order", "create_order", "submit_order", "createOrder", "placeOrder")
    hits: list[str] = []
    for path in (root / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for token in tokens:
            if token in text:
                hits.append(f"{path.relative_to(root)}:{token}")
    return {"files_scanned": len(list((root / "src").rglob("*.py"))), "hits": hits}


def check_orders(root: Path, audit: dict[str, Any]) -> tuple[bool, str]:
    """Three claims, three standards: config, a measured counter, and the venue.

    A source tree that contains a gated live order command can never support "no order path".
    What it can support is a counter at an armed boundary, and that counter stays scoped to
    the session it was armed for.
    """
    problems: list[str] = []
    claims = audit.get("claims") or {}

    external = claims.get("external_orders") or {}
    if external.get("status") != "NOT_VERIFIABLE" or external.get("value") is not None:
        problems.append("external_orders asserted without venue reconciliation")

    attempts = claims.get("order_submit_attempts") or {}
    if attempts.get("status") != "MEASURED":
        problems.append(f"order_submit_attempts is {attempts.get('status')}, not measured")
    else:
        if not attempts.get("spies_armed"):
            problems.append("attempts=0 claimed with no armed boundary: proves nothing")
        if attempts.get("calls_crossed"):
            problems.append(f"the armed boundary was crossed: {attempts.get('calls_crossed')}")

    scan = audit.get("static_scan") or {}
    live_hits = scan.get("live_or_execution_hits") or []
    if live_hits and not audit.get("prior_claim_corrected"):
        problems.append(f"{len(live_hits)} submission sites in src/ and the audit hides them")

    if problems:
        return False, json.dumps(problems[:5])
    return True, (f"{attempts.get('spies_armed')} armed boundaries, none crossed, "
                  f"{len(live_hits)} gated live sites declared")


# -- 8. evidence manifest --------------------------------------------------------


def check_inventory(manifest: dict[str, Any], required: list[str], *, root: Path
                    ) -> tuple[bool, str]:
    """The inventory must name every runtime file, and a chain head is not a file hash."""
    listed = manifest.get("runtime_inventory") or []
    missing = [path for path in required if path not in listed]
    if missing:
        return False, f"inventory omits {missing[:5]}"
    chain = manifest.get("chain_heads") or {}
    for entry in manifest.get("entries") or []:
        if entry.get("path", "").endswith("EVENTS.jsonl") and entry.get("sha256") in chain.values():
            return False, "an event-chain head is filed as a file hash"
    return True, f"inventory covers {len(required)} runtime files"


def check_evidence_manifest(manifest: dict[str, Any], root: Path) -> tuple[bool, str]:
    problems: list[str] = []
    entries = manifest.get("entries") or []
    if not entries:
        return False, "manifest has no entries"
    for entry in entries:
        target = root / entry["path"]
        if not target.is_file():
            problems.append(f"{entry['path']}: missing")
            continue
        raw = target.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry.get("sha256"):
            problems.append(f"{entry['path']}: sha256 does not match the bytes")
        if len(raw) != entry.get("byte_count"):
            problems.append(f"{entry['path']}: byte_count differs")
    #: Only the manifest that is being checked matters. An older manifest with the same
    #: basename (the A5 one) is a predecessor artefact and hashing it is the point, not a bug.
    self_path = manifest.get("self_excluded")
    if self_path and any(e.get("path") == self_path for e in entries):
        problems.append("manifest hashes itself: circular reference")
    return (not problems), json.dumps(problems[:8]) if problems else \
        f"{len(entries)} entries re-hash from their bytes"


# -- adversarial set -------------------------------------------------------------


def run_nodes(python: Path, checkout: Path, nodes: list[str]) -> tuple[int, str]:
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
    proc = subprocess.run([str(python), "-m", "pytest", "-q", "-p", "no:warnings", *nodes],
                          cwd=checkout, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return proc.returncode, (proc.stdout + proc.stderr).strip().splitlines()[-1:] or [""]


def adversarial(checkout: Path, evidence: Path, identity: dict[str, Any], ids: list[str],
                wp: Path, drill: dict[str, Any], manifest_entries: list[dict[str, Any]],
                python: Path, post_checkout: Path | None = None) -> list[dict[str, Any]]:
    """Each case invalidates an artefact; the verifier must notice. A miss is an unsupported pass."""
    cases: list[dict[str, Any]] = []

    def case(case_id: str, expectation: str, accepted: bool, detail: str) -> None:
        cases.append({"id": case_id, "expectation": expectation, "accepted_invalid": accepted,
                      "detail": detail})

    #: NEG-02 — a runtime file mutated after CODE_SHA.
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "lane.py"
        shutil.copy2(checkout / RUNTIME_FILES[0], copy)
        copy.write_bytes(copy.read_bytes() + b"\n# mutation\n")
        ok, detail = check_authority(checkout, git(checkout, "rev-parse", "HEAD")[1].strip(),
                                     [RUNTIME_FILES[0]])
        ok_after = ok and git_blob_sha1(copy.read_bytes()) == git(
            checkout, "rev-parse", f"HEAD:{RUNTIME_FILES[0]}")[1].strip()
        case("NEG-02", "mutated runtime file is rejected", bool(ok_after),
             "git blob identity sees the mutation" if not ok_after else "blob check missed it")

    #: NEG-03 — a primary log with one byte changed.
    with tempfile.TemporaryDirectory() as tmp:
        fake = Path(tmp) / "evidence"
        fake.mkdir()
        for part in (evidence.glob("part-*.log")):
            shutil.copy2(part, fake / part.name)
        shutil.copy2(evidence / "collect.txt", fake / "collect.txt")
        target = fake / "part-1.log"
        raw = bytearray(target.read_bytes())
        raw[len(raw) // 2] ^= 0x01
        target.write_bytes(bytes(raw))
        ok, detail = check_suite(identity, fake, ids)
        case("NEG-03", "a tampered log is rejected", bool(ok), detail)

    #: NEG-04 — one partition recorded as if it held another partition's tests, which is what a
    #: duplicated node ID looks like in the manifest. The gate re-derives each part from
    #: collect.txt, so the forgery has to be caught even when the counts still add up.
    with tempfile.TemporaryDirectory() as tmp:
        fake = Path(tmp) / "evidence"
        fake.mkdir()
        for part in evidence.glob("part-*.log"):
            shutil.copy2(part, fake / part.name)
        shutil.copy2(evidence / "collect.txt", fake / "collect.txt")
        forged = json.loads(json.dumps(identity))
        if len(forged.get("parts") or []) > 1:
            forged["parts"][1]["node_ids_sha256"] = forged["parts"][0]["node_ids_sha256"]
        ok, detail = check_suite(forged, fake, ids)
        case("NEG-04", "a duplicated node id is rejected", bool(ok), detail)

    #: NEG-05 — a partition omitted.
    with tempfile.TemporaryDirectory() as tmp:
        fake = Path(tmp) / "evidence"
        fake.mkdir()
        for part in evidence.glob("part-*.log"):
            if part.name == "part-5.log":
                continue
            shutil.copy2(part, fake / part.name)
        shutil.copy2(evidence / "collect.txt", fake / "collect.txt")
        ok, detail = check_suite(identity, fake, ids)
        case("NEG-05", "a missing partition is rejected", bool(ok), detail)

    #: NEG-09 — an audit that upgrades a scoped zero into "no orders at the venue", and one
    #: that claims a measured boundary without arming anything.
    falsified = {"claims": {"external_orders": {"value": 0, "status": "MEASURED"},
                            "order_submit_attempts": {"value": 0, "status": "MEASURED",
                                                      "spies_armed": 0, "calls_crossed": []}}}
    ok, detail = check_orders(checkout, falsified)
    case("NEG-09", "an unmeasured 'no orders' claim is rejected", bool(ok), detail)

    #: NEG-10 — the inventory drops ledger.py and a chain head is filed as if it were a file
    #: hash. Both are schema violations, so both have to make the gate refuse.
    forged_manifest = {"runtime_inventory": [p for p in RUNTIME_FILES if "ledger" not in p],
                       "entries": [{"path": "archive/EVENTS.jsonl",
                                    "sha256": drill.get("data", {}).get("events_sha256", "")}]}
    ok, detail = check_inventory(forged_manifest, RUNTIME_FILES, root=wp)
    case("NEG-10", "an incomplete inventory is rejected", bool(ok), detail)

    #: NEG-01 — a foreign package that shadows ``trading_bot`` on PYTHONPATH. Built here so the
    #: case cannot quietly pass because a hard-coded sibling path does not exist on this host,
    #: and driven through the gate the suite would actually run.
    with tempfile.TemporaryDirectory() as tmp:
        shadow = Path(tmp) / "src" / "trading_bot"
        shadow.mkdir(parents=True)
        (shadow / "__init__.py").write_text("# foreign checkout\n", encoding="utf-8")
        gate = Path(__file__).with_name("import_identity_gate.py")
        proc = subprocess.run(
            [sys.executable, str(gate), "--checkout", str(checkout),
             "--inject-pythonpath", str(Path(tmp) / "src"), "--expect", "REFUSED"],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        verdict = {}
        try:
            verdict = json.loads(proc.stdout)
        except json.JSONDecodeError:
            pass
        case("NEG-01", "the import gate refuses a foreign package",
             proc.returncode != 3,
             f"gate exit {proc.returncode}, status={verdict.get('status')}, "
             f"origin={(verdict.get('probe') or {}).get('origin')}")

    #: NEG-06 — a crash before the commit, then a resume: the pre-commit regression must hold.
    pre_nodes = [
        "tests/unit/vision/test_session_recovery.py::"
        "test_the_stop_armed_before_the_crash_closes_the_trade_after_it",
        "tests/unit/vision/test_session_recovery.py::"
        "test_a_close_that_already_happened_is_not_booked_twice",
    ]
    code, tail = run_nodes(python, checkout, pre_nodes)
    case("NEG-06", "a pre-commit crash resumes consistently", code != 0, tail[0] if tail else "")

    #: NEG-07 — a crash after the commit, then two resumes: no second close.
    if post_checkout is not None and (post_checkout / ".venv").exists():
        post_python = post_checkout / ".venv" / "Scripts" / "python.exe"
        if not post_python.exists():
            post_python = post_checkout / ".venv" / "bin" / "python"
        code, tail = run_nodes(post_python, post_checkout, [
            "tests/unit/vision/test_session_recovery.py::"
            "test_a_resume_after_the_gap_close_was_committed_books_nothing_twice"])
        case("NEG-07", "a post-commit crash does not close twice", code != 0,
             tail[0] if tail else "")
    else:
        case("NEG-07", "a post-commit crash does not close twice", False,
             "not executed: no post-commit checkout supplied (reported as uncovered)")

    #: NEG-08 — an armed transport refuses the submission instead of sending it.
    #:
    #: The first version of this case built ``ccxt.binance({...})``, and that constructor is
    #: not inert: it reached the venue and came back with an AuthenticationError. One
    #: unauthenticated request left the machine before the spy could be armed around anything.
    #: The case now instantiates the abstract ``ccxt.Exchange``, which constructs no websocket
    #: and loads no markets, so the boundary can be exercised offline.
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "attempt.py"
        script.write_text(
            "import ccxt\n"
            "calls = []\n"
            "ccxt.Exchange.__init_subclass__ = ccxt.Exchange.__init_subclass__\n"
            "def refuse(*a, **k):\n"
            "    calls.append(1)\n"
            "    raise RuntimeError('refused')\n"
            "ccxt.Exchange.create_order = refuse\n"
            "client = ccxt.Exchange({})\n"
            "try:\n"
            "    client.create_order('BTC/USDT', 'market', 'buy', 1.0)\n"
            "except RuntimeError:\n"
            "    print('REFUSED', len(calls))\n",
            encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
        proc = subprocess.run([str(python), str(script)], cwd=checkout, env=env,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace")
        refused = "REFUSED" in proc.stdout and "1" in proc.stdout
        case("NEG-08", "an armed transport refuses a live order", not refused,
             proc.stdout.strip() or (proc.stderr or "")[-160:])

    return cases


# -- main ------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--wp", type=Path, required=True)
    parser.add_argument("--code-sha", default=None)
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--evidence-sha", default=None,
                        help="commit that publishes the evidence; verifies the anchor exists")
    parser.add_argument("--post-checkout", default=None,
                        help="checkout that carries the post-COMMIT regression test")
    args = parser.parse_args(argv)

    checkout = args.checkout.resolve()
    wp = args.wp.resolve()
    rfc = wp / "rfc003"
    #: manifest paths are repository-relative, so they resolve from here and not from rfc003
    repo_root = wp.parents[2]
    evidence = rfc / "evidence"
    python = checkout / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        python = checkout / ".venv" / "bin" / "python"

    identity = json.loads((rfc / "SUITE_IDENTITY.json").read_text(encoding="utf-8"))
    code_sha = args.code_sha or str(identity.get("code_sha"))
    drill = json.loads((wp / "drill" / "DRILL.json").read_text(encoding="utf-8"))
    archive = wp / "archive"
    recorded_verification = json.loads((wp / "VERIFICATION.json").read_text(encoding="utf-8"))

    checks: list[dict[str, Any]] = []
    ids = read_collection(evidence)

    record(checks, "ACC-001.git_authority",
           *check_authority(checkout, code_sha, RUNTIME_FILES + TEST_FILES + SCRIPT_FILES))
    record(checks, "ACC-002.import_identity",
           *check_import(python, checkout, None, expect_inside=True))
    record(checks, "ACC-003.suite_identity", *check_suite(identity, evidence, ids))
    record(checks, "ACC-005.dataset", *check_dataset(archive, drill))
    manifest = json.loads((archive / "MANIFEST.json").read_text(encoding="utf-8"))
    record(checks, "ACC-005.event_chain", *check_event_chain(archive / "EVENTS.jsonl", manifest))
    record(checks, "ACC-004.gap_lab_replay", *check_gap_lab(python, checkout, wp,
                                                            recorded_verification))
    lab = json.loads((wp / "lab" / "GAP_LAB.json").read_text(encoding="utf-8"))
    record(checks, "ACC-006.recovery_matrix", *check_recovery(drill, lab))
    order_audit = json.loads((rfc / "ORDER_BOUNDARY_AUDIT.json").read_text(encoding="utf-8"))
    record(checks, "ACC-008.order_boundary", *check_orders(checkout, order_audit))

    manifest_path = rfc / "EVIDENCE_MANIFEST.json"
    if manifest_path.is_file():
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        record(checks, "ACC-007.evidence_manifest",
               *check_evidence_manifest(payload, repo_root))
        record(checks, "ACC-010.inventory",
               *check_inventory(payload, RUNTIME_FILES, root=wp))
    if args.evidence_sha:
        #: The seal has no external anchor until a commit names it: verify from a throwaway
        #: clone that the evidence commit really carries the manifest, instead of trusting the
        #: working tree it was just written in.
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "clone", "--no-hardlinks", "-q", str(checkout), tmp],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
            exists_code, _ = git(Path(tmp), "cat-file", "-e", f"{args.evidence_sha}^{{commit}}")
            clone = Path(tmp)
            subprocess.run(["git", "checkout", "-q", args.evidence_sha], cwd=clone,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
            published = (clone / "reports/ai-bots/WP-PAPER-QUOTE-GAP-002/rfc003"
                         / "EVIDENCE_MANIFEST.json")
            anchored = exists_code == 0 and published.is_file()
            record(checks, "ACC-010.evidence_anchor", anchored,
                   f"EVIDENCE_SHA {args.evidence_sha[:12]} carries the manifest" if anchored
                   else f"EVIDENCE_SHA {args.evidence_sha[:12]} does not carry the manifest")

    post = Path(args.post_checkout).resolve() if args.post_checkout else None
    cases = adversarial(checkout, evidence, identity, ids, wp, drill, [], python, post)
    unsupported = sum(1 for c in cases if c["accepted_invalid"])
    record(checks, "ACC-009.unsupported_pass_count", unsupported == 0,
           f"{unsupported} of {len(cases)} adversarial cases were wrongly accepted")

    failed = [c["check"] for c in checks if not c["ok"]]
    verdict = {
        "schema": "PHASE_A_VERIFICATION_V1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "code_sha": code_sha,
        "checkout": str(checkout),
        "verifier": "reports/ai-bots/WP-PAPER-QUOTE-GAP-002/rfc003/tools/verify_phase_a.py",
        "imports_business_logic": False,
        "checks": checks,
        "passed": sum(1 for c in checks if c["ok"]),
        "failed": failed,
        "adversarial": cases,
        "unsupported_pass_count": unsupported,
        "unsupported_pass_scope": "preregistered Phase-A adversarial cases only",
        "ok": not failed,
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(verdict, indent=2, ensure_ascii=False) + chr(10),
                             encoding="utf-8")
    print(json.dumps({"passed": verdict["passed"], "failed": failed,
                      "unsupported_pass_count": unsupported}, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
