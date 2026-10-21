"""verify_recovery — the third party in the recovery evidence chain.

This file is deliberately not allowed to import what the builder wrote. It reads the
laboratory's JSON and the books and ledgers on disk, re-derives the economic projection and
the exactly-once invariant with its own code, and refuses the bundle when the two
disagree. Then it mutates its own copy of the bundle ten ways and checks that each mutation
is caught: a verifier that cannot fail proves nothing about the bundle it accepted.

Three separate claims are kept apart, because collapsing them is how a laboratory result
becomes a production claim:

``PROCESS_CRASH_VERIFIED``            a child process really ended inside the write path
``FILESYSTEM_DURABILITY``             what this platform can promise about the rename
``POWER_LOSS_DURABILITY_NOT_VERIFIED`` what no scenario here can claim

Exit code: ``0`` PASS, ``1`` FAIL, ``2`` PARTIAL/BLOCKED (something required was not
verifiable), ``3`` the verifier itself could not run.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

#: The scenarios the RFC preregisters. CR-15 is this file; it is verified by its own
#: negative controls rather than by a lab row.
REQUIRED_SCENARIOS = (
    "CR-00",
    "CR-01",
    "CR-02",
    "CR-03",
    "CR-04",
    "CR-05",
    "CR-06",
    "CR-07",
    "CR-08",
    "CR-09",
    "CR-10",
    "CR-11",
    "CR-12",
    "CR-13",
    "CR-14",
    "CR-16",
)

FAILPOINT_EXIT = 86


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _decimal(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format(Decimal(repr(value)).normalize(), "f")
    return str(value)


#: The economic surface. Re-derived here on purpose: importing the builder's projection
#: would make this file agree with the builder by construction.
def _projection(book: dict[str, Any]) -> dict[str, Any]:
    broker = dict(book.get("broker") or {})
    return {
        "barrier_ms": (book.get("barrier") or {}).get("bar_open_ms"),
        "equity": _decimal(broker.get("equity")),
        "initial_equity": _decimal(broker.get("initial_equity")),
        "cash": _decimal(broker.get("cash")),
        "marked_equity": _decimal(book.get("marked_equity")),
        "risk_equity": _decimal(book.get("risk_equity")),
        "positions": sorted(
            [
                {
                    "position_id": str(row.get("position_id")),
                    "symbol": str(row.get("symbol")),
                    "side": str(row.get("side")),
                    "quantity": _decimal(row.get("quantity")),
                    "entry_price": _decimal(row.get("entry_price")),
                    "stop_loss_price": _decimal(row.get("stop_loss_price")),
                    "take_profit_price": _decimal(row.get("take_profit_price")),
                    "entry_commission": _decimal(row.get("entry_commission")),
                }
                for row in book.get("open_positions") or []
            ],
            key=lambda row: row["position_id"],
        ),
        "closed": sorted(
            [
                {
                    "position_id": str(row.get("position_id")),
                    "trade_id": str(row.get("trade_id")),
                    "symbol": str(row.get("symbol")),
                    "side": str(row.get("side")),
                    "quantity": _decimal(row.get("quantity")),
                    "entry_price": _decimal(row.get("entry_price")),
                    "exit_price": _decimal(row.get("exit_price")),
                    "pnl": _decimal(row.get("pnl")),
                    "gross_pnl": _decimal(row.get("gross_pnl")),
                    "entry_commission": _decimal(row.get("entry_commission")),
                    "exit_commission": _decimal(row.get("exit_commission")),
                    "execution_cost": _decimal(row.get("execution_cost_usdt")),
                    "exit_reason": str(row.get("exit_reason")),
                }
                for row in book.get("closed_trades") or []
            ],
            key=lambda row: row["position_id"],
        ),
        "pending": sorted(str(key) for key in (book.get("pending") or {})),
        "contract": book.get("contract") or {},
    }


def _canonical(book: dict[str, Any]) -> str:
    return _sha(json.dumps(_projection(book), sort_keys=True, separators=(",", ":")).encode())


def _entries(record: dict[str, Any]) -> list[dict[str, Any]]:
    ledger = (record.get("payload") or {}).get("ledger") or {}
    return [
        dict(row.get("entry") or {})
        for row in ledger.get("entries") or []
        if isinstance(row, dict)
    ]


def _closes(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [entry for entry in _entries(record) if entry.get("kind") == "CLOSE"]


def _book(record: dict[str, Any]) -> dict[str, Any]:
    return dict((record.get("payload") or {}).get("book") or {})


def _children(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    return list(scenario.get("children") or [])


def _by_tag(scenario: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(child.get("tag")): child for child in _children(scenario)}


def final_child(scenario: dict[str, Any]) -> dict[str, Any] | None:
    """The child whose book is the scenario's end state.

    Named rather than inferred: a scenario's last child by list order is the second resume,
    which reads the same state but attributes nothing; the state under test is the one the
    first successful resume published.
    """
    tags = _by_tag(scenario)
    for suffix in ("-resume", "-final", "-orphan", "-retry-2", "-retry-1", "-retry-0"):
        candidate = tags.get(f"{scenario.get('id')}{suffix}")
        if candidate is not None and _book(candidate):
            return candidate
    #: Concurrency scenarios have no ``-resume`` child: the survivor is the one that
    #: actually ran. A refused process still reads a book (that is how it reports what it
    #: refused), so "has a book" is not enough to name the writer.
    writers = [
        child
        for child in _children(scenario)
        if _book(child) and child.get("mode") != "inspect"
    ]
    ran = [child for child in writers if int(child.get("returncode", -1)) == 0]
    if ran:
        return ran[-1]
    return writers[-1] if writers else None


Check = tuple[bool, str]


def check_lab_shape(bundle: dict[str, Any], _ctx: dict[str, Any]) -> Check:
    schema = str(bundle.get("schema") or "")
    if schema != "rfc004-recovery-lab/1":
        return False, f"unknown lab schema {schema!r}"
    if bundle.get("wp") != "WP-003-01" or bundle.get("rfc") != "RFC-PAPER-RECOVERY-004":
        return False, "the bundle does not declare WP-003-01 / RFC-PAPER-RECOVERY-004"
    if not bundle.get("source_commit"):
        return False, "no source_commit"
    return True, f"schema {schema}, source_commit {bundle['source_commit'][:12]}"


def check_scenarios_complete(bundle: dict[str, Any], _ctx: dict[str, Any]) -> Check:
    present = {str(item.get("id")) for item in bundle.get("scenarios") or []}
    missing = [case for case in REQUIRED_SCENARIOS if case not in present]
    if missing:
        return False, f"missing scenario(s): {', '.join(missing)}"
    return True, f"{len(present)} scenario(s) present: {', '.join(sorted(present))}"


def check_no_failures(bundle: dict[str, Any], _ctx: dict[str, Any]) -> Check:
    failed = [
        str(item.get("id"))
        for item in bundle.get("scenarios") or []
        if item.get("verdict") != "PASS"
    ]
    if failed:
        return False, f"scenario(s) not passing: {', '.join(failed)}"
    return True, "every scenario reports PASS"


def check_no_unsupported_pass(bundle: dict[str, Any], _ctx: dict[str, Any]) -> Check:
    """A PASS whose own checks contain a failure, or a check the lab never ran."""
    offenders: list[str] = []
    for item in bundle.get("scenarios") or []:
        failed = [row for row in item.get("checks") or [] if row.get("ok") is not True]
        if failed and item.get("verdict") == "PASS":
            offenders.append(f"{item.get('id')}: {', '.join(str(row.get('check')) for row in failed)}")
    if offenders:
        return False, "PASS with a failed check: " + "; ".join(offenders)
    recorded = bundle.get("counts", {}).get("unsupported_pass_count")
    if recorded not in (0, None):
        return False, f"the lab reported unsupported_pass_count={recorded}"
    return True, "no scenario claims PASS while a check failed"


def check_crash_is_real(bundle: dict[str, Any], _ctx: dict[str, Any]) -> Check:
    problems: list[str] = []
    verified = 0
    for item in bundle.get("scenarios") or []:
        failpoint = item.get("failpoint")
        if not failpoint:
            continue
        crashed = [child for child in _children(item) if child.get("failpoint") == failpoint]
        if not crashed:
            problems.append(f"{item.get('id')}: no child was started with {failpoint}")
            continue
        exits = [int(child.get("returncode", -1)) for child in crashed]
        if FAILPOINT_EXIT not in exits:
            problems.append(f"{item.get('id')}: child exit(s) {exits}, expected {FAILPOINT_EXIT}")
            continue
        logs = [
            child.get("stdout")
            for child in crashed
            if child.get("returncode") == FAILPOINT_EXIT
        ]
        if not any(log and (_ctx["bundle_dir"] / log).exists() for log in logs):
            problems.append(f"{item.get('id')}: the killed child left no log")
            continue
        verified += 1
    if problems:
        return False, "; ".join(problems)
    return True, f"{verified} crash(es) end a real process at a real failpoint (exit 86)"


def check_crash_landed_in_the_window(bundle: dict[str, Any], _ctx: dict[str, Any]) -> Check:
    """The post-crash state must be one the write order predicts, not an arbitrary one."""
    problems: list[str] = []
    for item in bundle.get("scenarios") or []:
        observed = item.get("observed") or {}
        if "after_crash_closes" not in observed:
            continue
        closes = int(observed.get("after_crash_closes") or 0)
        failpoint = str(item.get("failpoint") or "")
        if failpoint.startswith(("book.", "ledger.", "bar.")):
            #: Before the replace the book cannot show the new close; after it, it must.
            if failpoint in {"book.after_replace", "book.after_dir_fsync", "bar.after_commit"}:
                if closes != 1:
                    problems.append(f"{item.get('id')}: {failpoint} left closes={closes}, expected 1")
            elif closes not in (0, 1):
                problems.append(f"{item.get('id')}: {failpoint} left closes={closes}")
    if problems:
        return False, "; ".join(problems)
    return True, "each crash left the book on one side of the replace, never in between"


def check_economic_equivalence(bundle: dict[str, Any], _ctx: dict[str, Any]) -> Check:
    """Re-derive the projection; do not accept the lab's digest as given."""
    control_book = _ctx["control_book"]
    if not control_book:
        return False, "the bundle carries no control book"
    control = _canonical(control_book)
    recorded_control = str((bundle.get("control") or {}).get("canonical") or "")
    if recorded_control and recorded_control != control:
        return False, "the recorded control digest is not what the control book hashes to"
    problems: list[str] = []
    checked = 0
    for item in bundle.get("scenarios") or []:
        final = final_child(item)
        if final is None:
            continue
        book = _book(final)
        if not book:
            problems.append(f"{item.get('id')}: the final child published no book")
            continue
        derived = _canonical(book)
        recorded = str((item.get("observed") or {}).get("canonical") or "")
        if recorded and recorded != derived:
            problems.append(f"{item.get('id')}: recorded digest != re-derived digest")
            continue
        if item.get("id") in {"CR-09", "CR-10"}:
            #: Concurrency: whichever process won must still hold the control state, which
            #: is what ``no_double_apply`` in the scenario asserts. CR-11 is refusals only.
            if derived != control:
                problems.append(f"{item.get('id')}: the surviving writer moved the book")
                continue
            checked += 1
            continue
        if item.get("id") == "CR-11":
            checked += 1
            continue
        if derived != control:
            problems.append(f"{item.get('id')}: recovered state differs from the control")
            continue
        checked += 1
    if problems:
        return False, "; ".join(problems)
    return True, f"{checked} recovered state(s) re-derive to the control projection"


def check_exactly_once(bundle: dict[str, Any], _ctx: dict[str, Any]) -> Check:
    problems: list[str] = []
    control_ids = sorted(
        str(row.get("position_id")) for row in (_ctx["control_book"].get("closed_trades") or [])
    )
    for item in bundle.get("scenarios") or []:
        final = final_child(item)
        if final is None:
            continue
        closes = _closes(final)
        ids = [str(entry.get("operation_id") or "") for entry in closes]
        book = _book(final)
        positions = sorted(str(row.get("position_id")) for row in book.get("closed_trades") or [])
        if item.get("id") in {"CR-11", "CR-09", "CR-10"}:
            #: Refusal and concurrency scenarios have their own witnesses below.
            if item.get("id") == "CR-09" and len(positions) > 1:
                problems.append("CR-09: two concurrent resumes booked two closes")
            continue
        if positions != control_ids:
            problems.append(
                f"{item.get('id')}: book closes {positions} != control {control_ids}"
            )
        if len(closes) != len(control_ids):
            problems.append(
                f"{item.get('id')}: {len(closes)} CLOSE row(s) for {len(control_ids)} effect(s)"
            )
        if len(set(ids)) != len(ids) or any(not value for value in ids):
            problems.append(f"{item.get('id')}: CLOSE rows carry duplicate or empty operation ids")
    if problems:
        return False, "; ".join(problems)
    return True, "one CLOSE row per committed effect, one effect per close, in every scenario"


def check_second_resume(bundle: dict[str, Any], _ctx: dict[str, Any]) -> Check:
    problems: list[str] = []
    checked = 0
    for item in bundle.get("scenarios") or []:
        tags = _by_tag(item)
        second = tags.get(f"{item.get('id')}-resume2")
        first = tags.get(f"{item.get('id')}-resume")
        if second is None or first is None:
            continue
        before = len(_closes(first))
        after = len(_closes(second))
        if after != before:
            problems.append(f"{item.get('id')}: {after} CLOSE row(s) after {before}")
            continue
        if _canonical(_book(first)) != _canonical(_book(second)):
            problems.append(f"{item.get('id')}: the second resume moved the book")
            continue
        checked += 1
    if problems:
        return False, "; ".join(problems)
    return True, f"{checked} second resume(s) booked nothing and moved nothing"


def check_refusals(bundle: dict[str, Any], _ctx: dict[str, Any]) -> Check:
    """Corruption and contention must be refused, with the runtime's own words."""
    wanted = {
        "CR-09": ("SessionBusy",),
        "CR-10": ("SessionBusy",),
        "CR-11": ("CorruptBook", "OperationConflict"),
    }
    problems: list[str] = []
    for case, expected in wanted.items():
        item = next((row for row in bundle.get("scenarios") or [] if row.get("id") == case), None)
        if item is None:
            problems.append(f"{case}: missing")
            continue
        seen = [
            str((child.get("payload") or {}).get("refusal"))
            for child in _children(item)
            if int(child.get("returncode", 0)) == 2
        ]
        if not any(value in expected for value in seen):
            problems.append(f"{case}: refusals {seen} do not include {expected}")
    if problems:
        return False, "; ".join(problems)
    return True, "contention and corruption were refused by the runtime, not repaired"


def check_post_crash_book_loadable(bundle: dict[str, Any], _ctx: dict[str, Any]) -> Check:
    """Whatever the crash left must be classifiable, and never a ref[/]used generation."""
    problems: list[str] = []
    for item in bundle.get("scenarios") or []:
        observed = item.get("observed") or {}
        recovery = observed.get("after_crash_store_recovery")
        if not isinstance(recovery, dict):
            continue
        status = str(recovery.get("status"))
        if status not in {"NO_CHANGE", "RECOVERED"}:
            problems.append(f"{item.get('id')}: post-crash status {status}")
    if problems:
        return False, "; ".join(problems)
    return True, "the state a crash leaves is always nameable (NO_CHANGE or RECOVERED)"


def check_network(bundle: dict[str, Any], _ctx: dict[str, Any]) -> Check:
    network = bundle.get("network") or {}
    attempts = network.get("attempts") or []
    external = [row for row in attempts if "127.0.0.1" not in str(row.get("args"))]
    if external:
        return False, f"{len(external)} external network attempt(s) recorded"
    if int(network.get("external_attempts", -1)) != 0:
        return False, "the lab's own external_attempts counter is not zero"
    item = next((row for row in bundle.get("scenarios") or [] if row.get("id") == "CR-16"), None)
    if item is None:
        return False, "CR-16 is missing"
    probe = (item.get("observed") or {})
    if probe.get("place_order_exit") != 2:
        return False, f"CR-16 live route exit={probe.get('place_order_exit')}, expected 2"
    if probe.get("deny_probe") != "DENIED":
        return False, f"CR-16 deny hook answered {probe.get('deny_probe')!r}"
    return True, (
        f"{len(attempts)} audited socket call(s), all loopback control; the live route "
        "refused before any I/O"
    )


def check_historical(bundle: dict[str, Any], _ctx: dict[str, Any]) -> Check:
    item = next((row for row in bundle.get("scenarios") or [] if row.get("id") == "CR-14"), None)
    if item is None:
        return False, "CR-14 is missing"
    observed = item.get("observed") or {}
    if not observed.get("barrier_ms"):
        return False, "the historical book has no barrier"
    if not observed.get("files_sha256"):
        return False, "the historical files were not hashed before and after"
    return True, (
        f"RFC003 book at barrier {observed.get('barrier_ms')} read twice; "
        f"{len(observed.get('files_sha256') or {})} file(s) byte-identical"
    )


def check_platform_scope(bundle: dict[str, Any], _ctx: dict[str, Any]) -> Check:
    environment = bundle.get("environment") or {}
    recovery = None
    for item in bundle.get("scenarios") or []:
        for child in _children(item):
            candidate = (child.get("payload") or {}).get("store_recovery") or {}
            if candidate.get("platform"):
                recovery = candidate["platform"]
                break
        if recovery:
            break
    if recovery is None:
        return False, "no child published a platform durability classification"
    if recovery.get("power_loss_scope") != "POWER_LOSS_DURABILITY_NOT_VERIFIED":
        return False, (
            f"power-loss scope claimed as {recovery.get('power_loss_scope')!r}; no scenario "
            "cut the power"
        )
    if environment.get("os_name") == "nt" and recovery.get("directory_fsync") != "unsupported":
        return False, "Windows has no directory fsync and the bundle does not say so"
    return True, (
        f"os={environment.get('os_name')} filesystem={environment.get('filesystem')} "
        f"directory_fsync={recovery.get('directory_fsync')} power_loss=NOT_VERIFIED"
    )


def check_runtime_identity(bundle: dict[str, Any], _ctx: dict[str, Any]) -> Check:
    repo: Path | None = _ctx.get("repo")
    if repo is None:
        return False, "no repository given: the runtime hashes were not re-derived"
    commit = str(bundle.get("source_commit") or "")
    recorded = bundle.get("runtime_sha256") or {}
    problems: list[str] = []
    for path, expected in sorted(recorded.items()):
        proc = subprocess.run(
            ["git", "show", f"{commit}:{path}"],
            cwd=str(repo),
            capture_output=True,
        )
        if proc.returncode != 0:
            problems.append(f"{path}: not in commit {commit[:12]}")
            continue
        #: El blob guarda LF y este checkout (autocrlf=true) escribe CRLF: se compara el
        #: texto, que es lo que el commit nombra y lo que otro checkout puede reproducir.
        actual = _sha(proc.stdout.replace(b"\r\n", b"\n"))
        if actual != expected:
            problems.append(f"{path}: {actual[:12]} != recorded {str(expected)[:12]}")
    if problems:
        return False, "; ".join(problems)
    return True, f"{len(recorded)} runtime file(s) hash to their blobs at {commit[:12]}"


def check_evidence_in_commit(bundle: dict[str, Any], _ctx: dict[str, Any]) -> Check:
    repo: Path | None = _ctx.get("repo")
    evidence_sha: str | None = _ctx.get("evidence_sha")
    bundle_dir: Path | None = _ctx.get("bundle_dir")
    if repo is None or evidence_sha is None or bundle_dir is None:
        return False, "no evidence commit given: ACC-011 was not verified"
    proc = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", evidence_sha],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return False, f"commit {evidence_sha[:12]} does not exist"
    committed = set(proc.stdout.split("\n"))
    try:
        relative = bundle_dir.resolve().relative_to(repo.resolve())
    except ValueError:
        return False, "the bundle is outside the repository"
    prefix = str(relative).replace("\\", "/") + "/"
    in_commit = {
        path[len(prefix) :] for path in committed if path.startswith(prefix) and path.strip()
    }
    on_disk = {
        str(path.relative_to(bundle_dir)).replace("\\", "/")
        for path in bundle_dir.rglob("*")
        if path.is_file() and path.name != "VERIFIER_REPLAY.json"
    }
    missing = sorted(on_disk - in_commit)
    if missing:
        return False, f"{len(missing)} file(s) on disk are not in the commit: {', '.join(missing[:5])}"
    return True, f"{len(in_commit)} evidence file(s) are inside commit {evidence_sha[:12]}"


def check_manifest(bundle: dict[str, Any], _ctx: dict[str, Any]) -> Check:
    bundle_dir: Path | None = _ctx.get("bundle_dir")
    if bundle_dir is None:
        return False, "no bundle directory: the manifest was not checked"
    manifest_path = bundle_dir / "EVIDENCE_MANIFEST.json"
    if not manifest_path.exists():
        return False, "EVIDENCE_MANIFEST.json is missing"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files") or []
    listed = {str(row.get("path")) for row in files}
    problems: list[str] = []
    for row in files:
        path = bundle_dir / str(row.get("path"))
        if not path.exists():
            problems.append(f"{row.get('path')}: listed but absent")
            continue
        if _sha(path.read_bytes().replace(b"\r\n", b"\n")) != str(row.get("sha256")):
            problems.append(f"{row.get('path')}: sha256 differs")
    on_disk = {
        str(path.relative_to(bundle_dir)).replace("\\", "/")
        for path in bundle_dir.rglob("*")
        if path.is_file()
        and path.name
        not in {"EVIDENCE_MANIFEST.json", "VERIFIER_REPLAY.json", "VERIFICATION.json"}
    }
    unlisted = sorted(on_disk - listed)
    if unlisted:
        problems.append(f"not in the manifest: {', '.join(unlisted[:5])}")
    if problems:
        return False, "; ".join(problems)
    return True, f"{len(files)} file(s) hashed and covered by the manifest"


def check_reports(bundle: dict[str, Any], _ctx: dict[str, Any]) -> Check:
    bundle_dir: Path | None = _ctx.get("bundle_dir")
    if bundle_dir is None:
        return False, "no bundle directory: the reports were not cross-checked"
    problems: list[str] = []
    for name in ("RUN_REPORT.json", "FINAL_REPORT.json"):
        path = bundle_dir / name
        if not path.exists():
            problems.append(f"{name} is missing")
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("code_sha") != bundle.get("source_commit"):
            problems.append(f"{name}: code_sha != the lab's source_commit")
        if int(report.get("unsupported_pass_count", -1)) != 0:
            problems.append(f"{name}: unsupported_pass_count != 0")
        if report.get("paper_validation") != "NOT_PERFORMED":
            problems.append(f"{name}: paper_validation must remain NOT_PERFORMED")
    if problems:
        return False, "; ".join(problems)
    return True, "both reports point at the same commit and claim no paper validation"


CHECKS: tuple[tuple[str, Callable[[dict[str, Any], dict[str, Any]], Check]], ...] = (
    ("lab_shape", check_lab_shape),
    ("scenarios_complete", check_scenarios_complete),
    ("no_failures", check_no_failures),
    ("no_unsupported_pass", check_no_unsupported_pass),
    ("crash_is_real", check_crash_is_real),
    ("crash_window", check_crash_landed_in_the_window),
    ("post_crash_loadable", check_post_crash_book_loadable),
    ("economic_equivalence", check_economic_equivalence),
    ("exactly_once", check_exactly_once),
    ("second_resume", check_second_resume),
    ("refusals", check_refusals),
    ("network_isolation", check_network),
    ("historical_compat", check_historical),
    ("platform_scope", check_platform_scope),
    ("runtime_identity", check_runtime_identity),
    ("evidence_in_commit", check_evidence_in_commit),
    ("manifest_covers", check_manifest),
    ("reports_consistent", check_reports),
)


def verify(
    bundle: dict[str, Any],
    *,
    bundle_dir: Path | None,
    repo: Path | None,
    evidence_sha: str | None,
) -> dict[str, Any]:
    scenario_00 = next(
        (row for row in bundle.get("scenarios") or [] if row.get("id") == "CR-00"), None
    )
    control_book: dict[str, Any] = {}
    if scenario_00:
        for child in _children(scenario_00):
            control_book = _book(child) or control_book
    context = {
        "bundle_dir": bundle_dir,
        "repo": repo,
        "evidence_sha": evidence_sha,
        "control_book": control_book,
    }
    results: list[dict[str, Any]] = []
    for name, function in CHECKS:
        try:
            ok, detail = function(bundle, context)
        except Exception as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        results.append({"check": name, "ok": bool(ok), "detail": str(detail)})
    failed = [row for row in results if not row["ok"]]
    blocked = [row for row in failed if "no repository" in row["detail"] or "no evidence commit" in row["detail"]]
    verdict = "PASS" if not failed else ("PARTIAL" if blocked else "FAIL")
    return {
        "schema": "rfc004-verifier/1",
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": verdict,
        "checks": results,
        "failed": [row["check"] for row in failed],
        "unsupported_pass_count": 0 if verdict == "PASS" else len(failed),
        "claims": {
            "PROCESS_CRASH_VERIFIED": all(
                row["ok"] for row in results if row["check"] == "crash_is_real"
            ),
            "FILESYSTEM_DURABILITY": "PROCESS_CRASH_VERIFIED_ONLY",
            "POWER_LOSS_DURABILITY_NOT_VERIFIED": any(
                row["check"] == "platform_scope" and row["ok"] for row in results
            ),
        },
    }


# -- negative controls -----------------------------------------------------------


def _mutations() -> dict[str, Callable[[dict[str, Any]], None]]:
    def drop_scenario(bundle: dict[str, Any]) -> None:
        bundle["scenarios"] = [
            row for row in bundle["scenarios"] if row.get("id") != "CR-06"
        ]

    def flip_verdict(bundle: dict[str, Any]) -> None:
        for row in bundle["scenarios"]:
            if row.get("id") == "CR-03":
                row["verdict"] = "FAIL"

    def pass_with_failed_check(bundle: dict[str, Any]) -> None:
        for row in bundle["scenarios"]:
            if row.get("id") == "CR-05":
                row["checks"] = [
                    {"check": "fabricated", "ok": False, "detail": "injected"},
                    *list(row.get("checks") or []),
                ]

    def duplicate_operation(bundle: dict[str, Any]) -> None:
        for row in bundle["scenarios"]:
            if row.get("id") != "CR-06":
                continue
            for child in row["children"]:
                ledger = (child.get("payload") or {}).get("ledger") or {}
                entries = ledger.get("entries") or []
                for entry in entries:
                    if (entry.get("entry") or {}).get("kind") == "CLOSE":
                        entries.append(copy.deepcopy(entry))
                        return

    def move_a_cent(bundle: dict[str, Any]) -> None:
        for row in bundle["scenarios"]:
            if row.get("id") != "CR-01":
                continue
            for child in row["children"]:
                book = (child.get("payload") or {}).get("book")
                if book:
                    book["broker"]["equity"] = float(book["broker"]["equity"]) + 0.01
                    return

    def falsify_source(bundle: dict[str, Any]) -> None:
        bundle["source_commit"] = "0" * 40

    def falsify_runtime_hash(bundle: dict[str, Any]) -> None:
        path = sorted(bundle["runtime_sha256"])[0]
        bundle["runtime_sha256"][path] = "0" * 64

    def hide_the_crash(bundle: dict[str, Any]) -> None:
        for row in bundle["scenarios"]:
            for child in row["children"]:
                if child.get("failpoint"):
                    child["returncode"] = 0

    def sneak_a_request(bundle: dict[str, Any]) -> None:
        bundle["network"]["attempts"] = [
            *list(bundle["network"].get("attempts") or []),
            {"event": "socket.connect", "pid": 1, "args": "('api.binance.com', 443)"},
        ]

    def claim_power_loss(bundle: dict[str, Any]) -> None:
        for row in bundle["scenarios"]:
            for child in row["children"]:
                recovery = (child.get("payload") or {}).get("store_recovery") or {}
                if recovery.get("platform"):
                    recovery["platform"]["power_loss_scope"] = "POWER_LOSS_DURABILITY_VERIFIED"
                    return

    return {
        "NEG-01-scenario-dropped": drop_scenario,
        "NEG-02-scenario-failed": flip_verdict,
        "NEG-03-pass-with-failed-check": pass_with_failed_check,
        "NEG-04-duplicate-operation-id": duplicate_operation,
        "NEG-05-equity-moved-one-cent": move_a_cent,
        "NEG-06-falsified-source-commit": falsify_source,
        "NEG-07-falsified-runtime-hash": falsify_runtime_hash,
        "NEG-08-crash-returncode-zeroed": hide_the_crash,
        "NEG-09-external-request-added": sneak_a_request,
        "NEG-10-power-loss-claimed": claim_power_loss,
    }


def negative_controls(
    bundle: dict[str, Any], *, bundle_dir: Path | None, repo: Path | None, evidence_sha: str | None
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for name, mutate in _mutations().items():
        mutated = copy.deepcopy(bundle)
        mutate(mutated)
        outcome = verify(mutated, bundle_dir=bundle_dir, repo=repo, evidence_sha=evidence_sha)
        caught = outcome["verdict"] != "PASS"
        results.append(
            {
                "id": name.split("-")[0],
                "mutation": name,
                "rejected": caught,
                "rejected_by": outcome["failed"],
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Independent verifier for RFC004 evidence.")
    parser.add_argument("--lab", required=True, help="RECOVERY_LAB.json")
    parser.add_argument("--bundle", required=True, help="evidence directory")
    parser.add_argument("--repo", default="", help="git repository to check the commit against")
    parser.add_argument("--evidence-sha", default="", help="evidence commit")
    parser.add_argument("--negative-controls", action="store_true")
    parser.add_argument("--json", required=True, help="where to write the verdict")
    args = parser.parse_args()

    bundle_dir = Path(args.bundle).resolve()
    lab_path = Path(args.lab).resolve()
    if not lab_path.exists():
        print(f"missing lab report: {lab_path}")
        return 3
    bundle = json.loads(lab_path.read_text(encoding="utf-8"))
    repo = Path(args.repo).resolve() if args.repo else None
    evidence_sha = args.evidence_sha or None

    outcome = verify(bundle, bundle_dir=bundle_dir, repo=repo, evidence_sha=evidence_sha)
    if args.negative_controls:
        controls = negative_controls(
            bundle, bundle_dir=bundle_dir, repo=repo, evidence_sha=evidence_sha
        )
        outcome["negative_controls"] = controls
        outcome["negative_controls_rejected"] = sum(1 for row in controls if row["rejected"])
        outcome["negative_controls_total"] = len(controls)
        if outcome["negative_controls_rejected"] != len(controls):
            outcome["verdict"] = "FAIL"
            outcome["unsupported_pass_count"] += sum(
                1 for row in controls if not row["rejected"]
            )
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(outcome, indent=1, sort_keys=True), encoding="utf-8")

    for row in outcome["checks"]:
        print(f"{'ok  ' if row['ok'] else 'FAIL'} {row['check']:24} {row['detail'][:110]}")
    for row in outcome.get("negative_controls") or []:
        print(f"{'ok  ' if row['rejected'] else 'FAIL'} {row['mutation']:34} {row['rejected_by']}")
    print(f"\nverdict: {outcome['verdict']}")
    if outcome["verdict"] == "PASS":
        return 0
    return 1 if outcome["verdict"] == "FAIL" else 2


if __name__ == "__main__":
    sys.exit(main())
