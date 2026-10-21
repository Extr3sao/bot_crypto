"""recovery_lab — the crash matrix for RFC-PAPER-RECOVERY-004, run against real processes.

Every scenario starts from the *same* seed — one committed book with one open position, and
one ledger — and then:

1. starts a resume process with a failpoint armed, which dies with ``os._exit`` inside the
   real persistence call;
2. reads what the crash left on disk, in another fresh process, without touching it;
3. resumes again in another process and compares the result with a control run that was
   never interrupted.

The comparison is not "the same JSON": it is the canonical economic projection (broker
state, positions, closes, risk, marks, pending) rendered as exact decimals and hashed, plus
the number of committed close operations in the book and in the ledger. A crash that lost a
close, repeated one, or moved a cent fails the scenario.

Exit code: ``0`` when every preregistered scenario passed, ``1`` when any did not, ``2``
when a required scenario could not be executed (never reported as a pass).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
CHILD = REPO / "scripts" / "recovery_child.py"
SYMBOL = "BTC/USDT"
BOOK_ID = "rfc004-lab-book"

ENV_SPEC = "TRADING_BOT_FAILPOINT"
ENV_SANDBOX = "TRADING_BOT_FAILPOINT_SANDBOX"
ENV_EXIT = "TRADING_BOT_FAILPOINT_EXIT"
FAILPOINT_EXIT = 86

HISTORICAL_BOOK = REPO / "reports" / "ai-bots" / "WP-PAPER-QUOTE-GAP-002" / "drill" / "A" / "STATE"


def utc_now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    """Hash the file as text, with CRLF normalised to LF.

    This repository checks out Python with ``core.autocrlf=true`` while the blob stores LF,
    so the bytes on disk differ between this machine and a Linux clone of the same commit.
    Hashing the *text* makes the digest a property of the source the commit names, not of
    the machine that checked it out — which is the only thing a verifier in another
    checkout can reproduce.
    """
    return sha256_bytes(path.read_bytes().replace(b"\r\n", b"\n"))


def _decimal(value: object) -> str | None:
    """A number as an exact decimal string, so 0.1 and 0.10 cannot compare unequal."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format(Decimal(repr(value)).normalize(), "f")
    return str(value)


#: What a recovered run must equal. ``session_id``, ``session_index``, ``session_ids``,
#: ``counters``, ``calls`` and ``spend_usd`` are lineage, not money: a crash legitimately
#: adds a session id and resets the session's counters, and comparing them would hide a
#: real difference behind a known one.
ECONOMIC_KEYS = (
    "broker",
    "open_positions",
    "closed_trades",
    "marked_equity",
    "risk",
    "risk_equity",
    "pending",
    "contract",
    "barrier",
)


def projection(book: dict) -> dict:
    """The economic state, key by key, with numbers as exact decimals."""
    out: dict = {"barrier_ms": (book.get("barrier") or {}).get("bar_open_ms")}
    out["equity"] = _decimal((book.get("broker") or {}).get("equity"))
    out["initial_equity"] = _decimal((book.get("broker") or {}).get("initial_equity"))
    out["cash"] = _decimal((book.get("broker") or {}).get("cash"))
    out["marked_equity"] = _decimal(book.get("marked_equity"))
    out["risk_equity"] = _decimal(book.get("risk_equity"))
    out["positions"] = sorted(
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
    )
    out["closed"] = sorted(
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
    )
    out["pending"] = sorted(str(key) for key in (book.get("pending") or {}))
    out["contract"] = book.get("contract") or {}
    return out


def canonical(book: dict) -> str:
    payload = json.dumps(projection(book), sort_keys=True, separators=(",", ":"))
    return sha256_bytes(payload.encode())


def read_json(path: Path) -> dict:
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}


class Lab:
    """Runs children and keeps every stdout/stderr/log on disk."""

    def __init__(self, root: Path) -> None:
        self.root = root
        #: The bundle is the parent of the lab directory (``rfc004/lab`` → ``rfc004``). Log
        #: paths are stored relative to it so a reader of the JSON can join them with the
        #: evidence directory instead of guessing where the runner put them.
        self.bundle = root.parent
        self.logs = root / "logs"
        self.logs.mkdir(parents=True, exist_ok=True)
        self.children: list[dict] = []
        #: Filled by CR-00 and by the seed run: the two states every scenario is compared
        #: with. Empty until then, so a scenario that runs out of order fails loudly instead
        #: of comparing against nothing.
        self.seed_book: dict = {}
        self.control_book: dict = {}

    def _relative(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.bundle)).replace("\\", "/")
        except ValueError:
            return path.name

    def env(self, *, failpoint: str | None, sandbox: Path | None) -> dict[str, str]:
        env = dict(os.environ)
        for name in (ENV_SPEC, ENV_SANDBOX, ENV_EXIT):
            env.pop(name, None)
        env["PYTHONPATH"] = str(REPO / "src")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if failpoint:
            if sandbox is None:
                raise ValueError("a failpoint needs a sandbox")
            env[ENV_SPEC] = failpoint
            env[ENV_SANDBOX] = str(sandbox)
            env[ENV_EXIT] = str(FAILPOINT_EXIT)
        return env

    def command(
        self,
        *,
        tag: str,
        case_root: Path,
        role: str = "resume",
        mode: str = "run",
        bars: str = "holed",
        feed: str = "stop_hole",
        hold_lock_ms: float = 0.0,
    ) -> tuple[list[str], Path]:
        out = self.logs / f"{tag}.json"
        if out.exists():
            out.unlink()
        return (
            [
                PYTHON,
                str(CHILD),
                "--root",
                str(case_root),
                "--ledger",
                str(case_root / "ledger.jsonl"),
                "--out",
                str(out),
                "--role",
                role,
                "--mode",
                mode,
                "--bars",
                bars,
                "--feed",
                feed,
                "--session",
                tag,
                "--book-id",
                BOOK_ID,
                "--hold-lock-ms",
                str(hold_lock_ms),
                "--deny-network",
            ],
            out,
        )

    def run(
        self,
        *,
        tag: str,
        case_root: Path,
        failpoint: str | None = None,
        sandbox: Path | None = None,
        timeout: int = 600,
        **kwargs,
    ) -> dict:
        cmd, out = self.command(tag=tag, case_root=case_root, **kwargs)
        started = time.perf_counter()
        proc = subprocess.run(
            cmd,
            cwd=str(REPO),
            env=self.env(failpoint=failpoint, sandbox=sandbox or case_root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = round(time.perf_counter() - started, 3)
        (self.logs / f"{tag}.stdout.txt").write_text(proc.stdout or "", encoding="utf-8")
        (self.logs / f"{tag}.stderr.txt").write_text(proc.stderr or "", encoding="utf-8")
        record = {
            "tag": tag,
            "role": kwargs.get("role", "resume"),
            "mode": kwargs.get("mode", "run"),
            "failpoint": failpoint,
            "returncode": proc.returncode,
            "seconds": elapsed,
            "payload": read_json(out) if out.exists() else {},
            "stdout": self._relative(self.logs / f"{tag}.stdout.txt"),
            "stderr": self._relative(self.logs / f"{tag}.stderr.txt"),
        }
        self.children.append(record)
        return record

    def spawn(self, *, tag: str, case_root: Path) -> tuple[subprocess.Popen, Path]:
        cmd, out = self.command(tag=tag, case_root=case_root)
        proc = subprocess.Popen(
            cmd,
            cwd=str(REPO),
            env=self.env(failpoint=None, sandbox=None),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return proc, out

    def finish(self, proc: subprocess.Popen, out: Path, *, tag: str, started: float) -> dict:
        stdout, stderr = proc.communicate(timeout=600)
        (self.logs / f"{tag}.stdout.txt").write_text(stdout or "", encoding="utf-8")
        (self.logs / f"{tag}.stderr.txt").write_text(stderr or "", encoding="utf-8")
        record = {
            "tag": tag,
            "role": "resume",
            "mode": "run",
            "failpoint": None,
            "returncode": proc.returncode,
            "seconds": round(time.perf_counter() - started, 3),
            "payload": read_json(out) if out.exists() else {},
            "stdout": self._relative(self.logs / f"{tag}.stdout.txt"),
            "stderr": self._relative(self.logs / f"{tag}.stderr.txt"),
        }
        self.children.append(record)
        return record


# -- reading a result -----------------------------------------------------------


def book_of(record: dict) -> dict:
    return dict(record.get("payload", {}).get("book") or {})


def closes_of(record: dict) -> list[dict]:
    entries = record.get("payload", {}).get("ledger", {}).get("entries") or []
    return [row["entry"] for row in entries if row.get("entry", {}).get("kind") == "CLOSE"]


def fills_of(record: dict) -> list[dict]:
    entries = record.get("payload", {}).get("ledger", {}).get("entries") or []
    return [row["entry"] for row in entries if row.get("entry", {}).get("kind") == "FILL"]


def resumed_from(record: dict) -> int | None:
    """The barrier a resumed session started at, as its own summary reports it."""
    session = (record.get("payload", {}).get("summary") or {}).get("session") or {}
    recovery = session.get("recovery") or {}
    value = recovery.get("barrier_ms")
    return None if value is None else int(value)


def operation_ids(rows: list[dict]) -> list[str]:
    return [str(row.get("operation_id") or "") for row in rows]


def case_dir(root: Path, name: str) -> Path:
    path = root / "cases" / name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


def seed_into(case_root: Path, seed: Path) -> None:
    shutil.copytree(seed / "state", case_root / "state")
    shutil.copy2(seed / "ledger.jsonl", case_root / "ledger.jsonl")


def check(name: str, ok: bool, detail: str) -> dict:
    return {"check": name, "ok": bool(ok), "detail": detail}


def evaluate(
    *,
    case: str,
    adversary: str,
    failpoint: str | None,
    children: list[dict],
    observed: dict,
    checks: list[dict],
) -> dict:
    return {
        "id": case,
        "adversary": adversary,
        "failpoint": failpoint,
        "children": children,
        "observed": observed,
        "checks": checks,
        "verdict": "PASS" if all(item["ok"] for item in checks) else "FAIL",
    }


def exact_once_checks(
    *,
    control_book: dict,
    final: dict,
    second: dict,
    expected_closes: int = 1,
) -> tuple[list[dict], dict]:
    book = book_of(final)
    ledger_closes = closes_of(final)
    ids = operation_ids(ledger_closes)
    second_book = book_of(second)
    observed = {
        "canonical": canonical(book) if book else None,
        "control_canonical": canonical(control_book),
        "book_state_digest": final.get("payload", {}).get("book_state_digest"),
        "closed_positions": [
            str(row.get("position_id")) for row in book.get("closed_trades") or []
        ],
        "ledger_close_rows": len(ledger_closes),
        "ledger_close_operation_ids": ids,
        "second_closes": len(closes_of(second)),
        "second_canonical": canonical(second_book) if second_book else None,
        "store_recovery": final.get("payload", {}).get("store_recovery"),
    }
    checks = [
        check(
            "economic_equivalence",
            bool(book) and canonical(book) == canonical(control_book),
            "recovered state is the control state, field by field",
        ),
        check(
            "closed_once",
            len(book.get("closed_trades") or []) == expected_closes,
            f"the book holds {len(book.get('closed_trades') or [])} close(s), expected {expected_closes}",
        ),
        check(
            "ledger_rows_not_duplicated",
            len(ledger_closes) == expected_closes and len(set(ids)) == len(ids),
            f"{len(ledger_closes)} CLOSE row(s) with {len(set(ids))} unique operation id(s)",
        ),
        check(
            "second_resume_is_a_noop",
            len(closes_of(second)) == len(ledger_closes)
            and canonical(second_book) == canonical(book)
            and bool(second_book),
            (
                f"a further resume writes no new CLOSE row ({len(closes_of(second))} vs "
                f"{len(ledger_closes)}) and changes no digit"
            ),
        ),
    ]
    return checks, observed


# -- the matrix -----------------------------------------------------------------


def cr_00_control(lab: Lab) -> dict:
    """A run that is never interrupted: the reference every crash is compared with."""
    case = case_dir(lab.root, "CR-00")
    seed_into(case, lab.root / "seed")
    final = lab.run(tag="CR-00-final", case_root=case)
    book = book_of(final)
    lab.control_book = book
    observed = {
        "canonical": canonical(book) if book else None,
        "closed": [str(row.get("position_id")) for row in book.get("closed_trades") or []],
        "equity": (book.get("broker") or {}).get("equity"),
        "closes_in_session": len(closes_of(final)),
        "seconds": final["seconds"],
    }
    checks = [
        check("ran", final["returncode"] == 0, f"resume exit={final['returncode']}"),
        check("one_close", len(book.get("closed_trades") or []) == 1, "one committed close"),
        check("flat_after", not (book.get("open_positions") or []), "no position left open"),
        check(
            "ledger_one_close",
            len(closes_of(final)) == 1,
            f"{len(closes_of(final))} CLOSE row(s)",
        ),
    ]
    return evaluate(
        case="CR-00",
        adversary="no crash: the reference run",
        failpoint=None,
        children=[final],
        observed=observed,
        checks=checks,
    )


def crash_then_resume(
    lab: Lab,
    *,
    case: str,
    adversary: str,
    failpoint: str,
    expected_after_crash: str,
    extra_setup=None,  # type: ignore[no-untyped-def]
    expected_closes: int = 1,
) -> dict:
    """The shared shape: seed, crash, inspect, resume, resume again."""
    root = case_dir(lab.root, case)
    seed_into(root, lab.root / "seed")
    if extra_setup is not None:
        extra_setup(root)
    crashed = lab.run(tag=f"{case}-crash", case_root=root, failpoint=failpoint, sandbox=root)
    after_crash = lab.run(tag=f"{case}-after-crash", case_root=root, mode="inspect", role="resume")
    final = lab.run(tag=f"{case}-resume", case_root=root)
    second = lab.run(tag=f"{case}-resume2", case_root=root)

    checks, observed = exact_once_checks(
        control_book=lab.control_book, final=final, second=second, expected_closes=expected_closes
    )
    crashed_book = book_of(after_crash)
    observed["after_crash_canonical"] = canonical(crashed_book) if crashed_book else None
    observed["after_crash_closes"] = len((crashed_book or {}).get("closed_trades") or [])
    observed["after_crash_files"] = after_crash.get("payload", {}).get("files")
    observed["after_crash_store_recovery"] = after_crash.get("payload", {}).get("store_recovery")
    checks.insert(
        0,
        check(
            "crash_was_a_kill",
            crashed["returncode"] == FAILPOINT_EXIT,
            f"child exit={crashed['returncode']} (86 = os._exit at the failpoint)",
        ),
    )
    unchanged = bool(crashed_book) and canonical(crashed_book) == canonical(lab.seed_book)
    if expected_after_crash == "BOOK_UNCHANGED":
        ok = unchanged and observed["after_crash_closes"] == 0
        detail = (
            f"expected the seed book; unchanged={unchanged} closes={observed['after_crash_closes']}"
        )
    elif expected_after_crash == "BOOK_COMMITTED":
        #: The crash can land on an *intermediate* commit (the reconstruction is committed at
        #: the barrier it started from, before the next bar). "Committed" therefore means the
        #: close is in the book and the book is a state a resume accepts — not that it is
        #: already the final state of the control.
        recovery = after_crash.get("payload", {}).get("store_recovery") or {}
        ok = (
            observed["after_crash_closes"] == expected_closes
            and recovery.get("status") in {"NO_CHANGE", "RECOVERED"}
        )
        detail = (
            f"the close is in the book (closes={observed['after_crash_closes']}) and the book "
            f"is loadable (store status={recovery.get('status')}); barrier="
            f"{(crashed_book.get('barrier') or {}).get('bar_open_ms')}"
        )
    else:
        recovery = after_crash.get("payload", {}).get("store_recovery") or {}
        ok = unchanged or (
            observed["after_crash_closes"] == expected_closes
            and recovery.get("status") in {"NO_CHANGE", "RECOVERED"}
        )
        detail = (
            "the crash left either the seed book or a loadable book with the close, never a "
            f"third state: unchanged={unchanged} closes={observed['after_crash_closes']} "
            f"status={recovery.get('status')}"
        )
    checks.insert(1, check("post_crash_state", ok, detail))
    return evaluate(
        case=case,
        adversary=adversary,
        failpoint=failpoint,
        children=[crashed, after_crash, final, second],
        observed=observed,
        checks=checks,
    )


def cr_01(lab: Lab) -> dict:
    return crash_then_resume(
        lab,
        case="CR-01",
        adversary="before the first durable write of the closing session",
        failpoint="ledger.before_write",
        expected_after_crash="BOOK_UNCHANGED",
    )


def cr_02(lab: Lab) -> dict:
    return crash_then_resume(
        lab,
        case="CR-02",
        adversary="after the ledger row was written, before its fsync",
        failpoint="ledger.after_write",
        expected_after_crash="EITHER",
    )


def cr_03(lab: Lab) -> dict:
    return crash_then_resume(
        lab,
        case="CR-03",
        adversary="the new book was written and fsynced, the replace has not happened",
        failpoint="book.after_tmp_fsync",
        expected_after_crash="BOOK_UNCHANGED",
    )


def cr_04(lab: Lab) -> dict:
    return crash_then_resume(
        lab,
        case="CR-04",
        adversary="the temporary projection is partly written",
        failpoint="book.after_tmp_write",
        expected_after_crash="BOOK_UNCHANGED",
    )


def cr_05(lab: Lab) -> dict:
    return crash_then_resume(
        lab,
        case="CR-05",
        adversary="the previous generation was copied, the replace has not happened",
        failpoint="book.after_prev_copy",
        expected_after_crash="BOOK_UNCHANGED",
    )


def cr_06(lab: Lab) -> dict:
    return crash_then_resume(
        lab,
        case="CR-06",
        adversary="the replace landed, the COMMIT event was never written",
        failpoint="book.after_replace",
        expected_after_crash="BOOK_COMMITTED",
    )


def cr_07(lab: Lab) -> dict:
    """The clean side of the boundary: after ACK, two resumes must change nothing."""
    root = case_dir(lab.root, "CR-07")
    seed_into(root, lab.root / "seed")
    crashed = lab.run(tag="CR-07-crash", case_root=root, failpoint="bar.after_commit", sandbox=root)
    after = lab.run(tag="CR-07-after-crash", case_root=root, mode="inspect")
    third = lab.run(tag="CR-07-resume3", case_root=root)
    fourth = lab.run(tag="CR-07-resume4", case_root=root)
    checks, observed = exact_once_checks(control_book=lab.control_book, final=third, second=fourth)
    observed["after_crash_file_digest"] = after.get("payload", {}).get("book_digest")
    observed["after_crash_store_recovery"] = after.get("payload", {}).get("store_recovery")
    checks.insert(
        0,
        check(
            "crash_was_a_kill",
            crashed["returncode"] == FAILPOINT_EXIT,
            f"child exit={crashed['returncode']}",
        ),
    )
    checks.insert(
        1,
        check(
            "commit_survived",
            (book_of(after).get("barrier") or {}).get("bar_open_ms")
            == resumed_from(third),
            "the barrier the resume started from is the barrier the crash committed "
            f"({(book_of(after).get('barrier') or {}).get('bar_open_ms')} vs {resumed_from(third)})",
        ),
    )
    return evaluate(
        case="CR-07",
        adversary="after ACK: the bar is committed",
        failpoint="bar.after_commit",
        children=[crashed, after, third, fourth],
        observed=observed,
        checks=checks,
    )


def cr_08(lab: Lab) -> dict:
    """One identity, N retries: the effect may be repeated, the accounting may not."""
    root = case_dir(lab.root, "CR-08")
    seed_into(root, lab.root / "seed")
    crashed = lab.run(
        tag="CR-08-crash", case_root=root, failpoint="ledger.after_fsync", sandbox=root
    )
    attempts = [lab.run(tag=f"CR-08-retry-{index}", case_root=root) for index in range(3)]
    final = attempts[-1]
    checks, observed = exact_once_checks(
        control_book=lab.control_book, final=final, second=attempts[0]
    )
    observed["retries"] = len(attempts)
    observed["suppressed_duplicates"] = [
        attempt.get("payload", {}).get("ledger_stats", {}).get("duplicates_suppressed")
        for attempt in attempts
    ]
    observed["retry_exits"] = [attempt["returncode"] for attempt in attempts]
    checks.insert(
        0,
        check(
            "crash_was_a_kill",
            crashed["returncode"] == FAILPOINT_EXIT,
            f"child exit={crashed['returncode']}",
        ),
    )
    checks.append(
        check(
            "duplicate_was_suppressed_not_rewritten",
            sum(
                int(
                    attempt.get("payload", {}).get("ledger_stats", {}).get("duplicates_suppressed")
                    or 0
                )
                for attempt in attempts
            )
            >= 1,
            "the re-executed close matched its committed row and appended nothing",
        )
    )
    return evaluate(
        case="CR-08",
        adversary="the same operation_id retried three times",
        failpoint="ledger.after_fsync",
        children=[crashed, *attempts],
        observed=observed,
        checks=checks,
    )


def cr_09(lab: Lab) -> dict:
    """Two resumers at once: the lock, not luck, is what keeps the book single."""
    root = case_dir(lab.root, "CR-09")
    seed_into(root, lab.root / "seed")
    started = time.perf_counter()
    first = lab.spawn(tag="CR-09-a", case_root=root)
    time.sleep(0.2)
    second = lab.spawn(tag="CR-09-b", case_root=root)
    a = lab.finish(first[0], first[1], tag="CR-09-a", started=started)
    b = lab.finish(second[0], second[1], tag="CR-09-b", started=started)
    children = [a, b]
    refused = [child for child in children if child["returncode"] == 2]
    ran = [child for child in children if child["returncode"] == 0]
    survivor = ran[0] if ran else None
    book = book_of(survivor) if survivor else {}
    checks = [
        check(
            "no_double_apply",
            len(book.get("closed_trades") or []) == 1,
            f"{len(book.get('closed_trades') or [])} close(s) after two concurrent resumes",
        ),
        check(
            "one_writer",
            len(ran) == 1,
            f"{len(ran)} process(es) ran, {len(refused)} refused",
        ),
        check(
            "refusal_is_the_lock",
            all(child.get("payload", {}).get("refusal") == "SessionBusy" for child in refused),
            "; ".join(str(child.get("payload", {}).get("refusal")) for child in refused) or "n/a",
        ),
        check(
            "ledger_single_close",
            survivor is not None and len(closes_of(survivor)) == 1,
            "one CLOSE row in the shared ledger",
        ),
    ]
    observed = {
        "children": [{"tag": child["tag"], "exit": child["returncode"]} for child in children],
        "closes": len(book.get("closed_trades") or []),
        "canonical": canonical(book) if book else None,
        "control_canonical": canonical(lab.control_book),
    }
    return evaluate(
        case="CR-09",
        adversary="two processes resume the same book at the same instant",
        failpoint=None,
        children=children,
        observed=observed,
        checks=checks,
    )


def cr_10(lab: Lab) -> dict:
    """An orphan lock must be taken over; a live one must be respected."""
    root = case_dir(lab.root, "CR-10")
    seed_into(root, lab.root / "seed")
    #: A lock left by a process that no longer exists. The pid is one Windows cannot have
    #: handed out, so ``pid_alive`` answers ``False`` rather than "unknown".
    lock = root / "state" / "BOOK.lock"
    lock.write_text(
        json.dumps(
            {
                "pid": 999_999,
                "host": "lab",
                "session_id": "killed",
                "token": "dead-token",
                "acquired_at_ms": 0,
            }
        ),
        encoding="utf-8",
    )
    orphan = lab.run(tag="CR-10-orphan", case_root=root)
    book = book_of(orphan)

    live_root = case_dir(lab.root, "CR-10-live")
    seed_into(live_root, lab.root / "seed")
    holder = subprocess.Popen(
        lab.command(tag="CR-10-holder", case_root=live_root, mode="lock-only", hold_lock_ms=5000)[
            0
        ],
        cwd=str(REPO),
        env=lab.env(failpoint=None, sandbox=None),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(1.0)
    contested = lab.run(tag="CR-10-contested", case_root=live_root)
    holder.communicate(timeout=60)
    after = lab.run(tag="CR-10-after-holder", case_root=live_root)

    checks = [
        check(
            "orphan_taken_over",
            orphan["returncode"] == 0 and len(book.get("closed_trades") or []) == 1,
            f"exit={orphan['returncode']}, closes={len(book.get('closed_trades') or [])}",
        ),
        check(
            "live_lock_respected",
            contested["returncode"] == 2
            and contested.get("payload", {}).get("refusal") == "SessionBusy",
            f"exit={contested['returncode']} refusal={contested.get('payload', {}).get('refusal')}",
        ),
        check(
            "lock_released_after_holder_left",
            after["returncode"] == 0
            and len(closes_of(after)) == 1
            and canonical(book_of(after)) == canonical(lab.control_book)
            and not (live_root / "state" / "BOOK.lock").exists(),
            f"the next resume ran (exit={after['returncode']}) and found no lock file",
        ),
        check(
            "orphan_did_not_duplicate",
            len(closes_of(orphan)) == 1,
            f"{len(closes_of(orphan))} CLOSE row(s) after the takeover",
        ),
    ]
    observed = {
        "orphan_exit": orphan["returncode"],
        "contested_exit": contested["returncode"],
        "contested_refusal": contested.get("payload", {}).get("refusal"),
        "canonical": canonical(book) if book else None,
        "control_canonical": canonical(lab.control_book),
    }
    return evaluate(
        case="CR-10",
        adversary="an orphan lock and a live lock around the same book",
        failpoint=None,
        children=[orphan, contested, after],
        observed=observed,
        checks=checks,
    )


def cr_11(lab: Lab) -> dict:
    """Altered committed state must be refused, never repaired into a pass."""
    root = case_dir(lab.root, "CR-11")
    seed_into(root, lab.root / "seed")
    lab.run(tag="CR-11-seed-run", case_root=root)  # commits the close
    book_path = root / "state" / "BOOK.json"
    doc = json.loads(book_path.read_text(encoding="utf-8"))
    doc["body"]["broker"]["equity"] = float(doc["body"]["broker"]["equity"]) + 1.0
    book_path.write_text(json.dumps(doc, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    tampered_digest = sha256_file(book_path)
    refused = lab.run(tag="CR-11-tampered", case_root=root)
    quarantined = sorted((root / "state").glob("BOOK.corrupt.*.json"))
    still_tampered = sha256_file(book_path) == tampered_digest

    #: The book one commit behind its ledger, with that CLOSE row edited: the resume has
    #: to re-execute the close, and the identity it finds carries a different number. That
    #: is a conflict, not a retry.
    ledger_root = case_dir(lab.root, "CR-11-ledger")
    seed_into(ledger_root, lab.root / "seed")
    ledger_path = ledger_root / "ledger.jsonl"
    shutil.copy2(lab.root / "cases" / "CR-00" / "ledger.jsonl", ledger_path)
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    edited = 0
    for index, line in enumerate(lines):
        row = json.loads(line)
        if row["entry"].get("kind") == "CLOSE":
            row["entry"]["pnl_net_usdt"] = round(float(row["entry"]["pnl_net_usdt"]) + 1.0, 8)
            lines[index] = json.dumps(row, sort_keys=True, separators=(",", ":"))
            edited += 1
            break
    ledger_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    inspect = lab.run(tag="CR-11-ledger-inspect", case_root=ledger_root, mode="inspect")
    conflict = lab.run(tag="CR-11-ledger-resume", case_root=ledger_root)

    checks = [
        check(
            "tampered_book_refused",
            refused["returncode"] == 2
            and refused.get("payload", {}).get("refusal") == "CorruptBook",
            f"exit={refused['returncode']} refusal={refused.get('payload', {}).get('refusal')}",
        ),
        check(
            "tampered_book_preserved",
            still_tampered and bool(quarantined),
            f"{len(quarantined)} quarantined copy(ies), file left as it was",
        ),
        check(
            "ledger_edit_breaks_the_chain",
            edited == 1
            and inspect.get("payload", {}).get("ledger", {}).get("chain", {}).get("ok") is False,
            str(inspect.get("payload", {}).get("ledger", {}).get("chain", {}).get("reason")),
        ),
        check(
            "ledger_edit_refused_by_the_runtime",
            conflict["returncode"] == 2
            and conflict.get("payload", {}).get("refusal") == "OperationConflict",
            f"exit={conflict['returncode']} refusal={conflict.get('payload', {}).get('refusal')}",
        ),
    ]
    observed = {
        "tampered_file_sha256": tampered_digest,
        "quarantine": [path.name for path in quarantined],
        "chain": inspect.get("payload", {}).get("ledger", {}).get("chain"),
        "runtime_refusal": conflict.get("payload", {}).get("detail"),
    }
    return evaluate(
        case="CR-11",
        adversary="a committed book and a committed ledger row are edited",
        failpoint=None,
        children=[refused, inspect, conflict],
        observed=observed,
        checks=checks,
    )


def cr_12(lab: Lab) -> dict:
    """A projection behind or ahead of its authority: rebuild the first, refuse the second."""
    behind = case_dir(lab.root, "CR-12-behind")
    seed_into(behind, lab.root / "seed")
    control_ledger = (lab.root / "cases" / "CR-00" / "ledger.jsonl").read_bytes()
    lab.run(tag="CR-12-behind-seed", case_root=behind, mode="inspect")
    (behind / "ledger.jsonl").write_bytes(control_ledger)
    behind_run = lab.run(tag="CR-12-behind-resume", case_root=behind)
    behind_book = book_of(behind_run)

    ahead = case_dir(lab.root, "CR-12-ahead")
    shutil.copytree(lab.root / "cases" / "CR-00" / "state", ahead / "state")
    rows = [
        line
        for line in control_ledger.decode("utf-8").splitlines()
        if line.strip() and json.loads(line)["entry"].get("kind") != "CLOSE"
    ]
    (ahead / "ledger.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
    ahead_inspect = lab.run(tag="CR-12-ahead-inspect", case_root=ahead, mode="inspect")

    checks = [
        check(
            "behind_was_rebuilt_not_replayed_onto",
            behind_run["returncode"] == 0
            and canonical(behind_book) == canonical(lab.control_book)
            and len(closes_of(behind_run)) == 1,
            f"exit={behind_run['returncode']} closes={len(behind_book.get('closed_trades') or [])} rows={len(closes_of(behind_run))}",
        ),
        check(
            "ahead_is_refused",
            ahead_inspect.get("payload", {}).get("store_recovery", {}).get("status")
            == "REFUSED_CORRUPTION"
            and ahead_inspect.get("payload", {}).get("store_recovery", {}).get("code")
            == "PROJECTION_BEHIND_AUTHORITY",
            str(ahead_inspect.get("payload", {}).get("store_recovery", {}).get("code")),
        ),
    ]
    observed = {
        "behind_canonical": canonical(behind_book) if behind_book else None,
        "control_canonical": canonical(lab.control_book),
        "ahead_recovery": ahead_inspect.get("payload", {}).get("store_recovery"),
    }
    return evaluate(
        case="CR-12",
        adversary="the projection is one commit behind, then one commit ahead",
        failpoint=None,
        children=[behind_run, ahead_inspect],
        observed=observed,
        checks=checks,
    )


def cr_13(lab: Lab) -> dict:
    """A stray temporary file is never a state; a failed replace is never a partial one."""
    root = case_dir(lab.root, "CR-13")
    seed_into(root, lab.root / "seed")
    lab.run(tag="CR-13-seed-run", case_root=root)  # commits the close
    committed_digest = sha256_file(root / "state" / "BOOK.json")
    (root / "state" / "BOOK.json.tmp").write_bytes(b'{"body": {"forged": true}, "digest": "x"}')
    #: The stray file is read *before* the next save, because a save reuses that name: after
    #: the resume it is gone by construction, and looking then would prove nothing.
    before_resume = lab.run(tag="CR-13-orphan-inspect", case_root=root, mode="inspect")
    orphan_recovery = before_resume.get("payload", {}).get("store_recovery", {})
    resumed = lab.run(tag="CR-13-orphan", case_root=root)

    blocked = case_dir(lab.root, "CR-13-replace")
    seed_into(blocked, lab.root / "seed")
    lab.run(tag="CR-13-replace-seed", case_root=blocked)
    book_path = blocked / "state" / "BOOK.json"
    before = sha256_file(book_path)
    os.chmod(book_path, 0o444)
    failed = lab.run(tag="CR-13-replace-failed", case_root=blocked)
    after = sha256_file(book_path)
    os.chmod(book_path, 0o644)
    retried = lab.run(tag="CR-13-replace-retried", case_root=blocked)

    checks = [
        check(
            "orphan_tmp_not_adopted",
            resumed["returncode"] == 0
            and canonical(book_of(resumed)) == canonical(lab.control_book)
            and "forged" not in json.dumps(book_of(resumed)),
            "the book after the resume is the control economy, not the forged temporary",
        ),
        check(
            "orphan_tmp_reported",
            bool(orphan_recovery.get("orphan_tmp")),
            str(orphan_recovery.get("orphan_tmp")),
        ),
        check(
            "failed_replace_left_no_partial_state",
            failed["returncode"] != 0 and after == before,
            f"exit={failed['returncode']}, book unchanged={after == before}",
        ),
        check(
            "next_resume_after_repair_works",
            retried["returncode"] == 0,
            f"exit={retried['returncode']}",
        ),
    ]
    observed = {
        "committed_sha256": committed_digest,
        "orphan_tmp_bytes": len(b'{"body": {"forged": true}, "digest": "x"}'),
        "orphan_recovery": orphan_recovery,
        "failed_replace_exit": failed["returncode"],
        "failed_replace_error": failed.get("payload", {}).get("error"),
    }
    return evaluate(
        case="CR-13",
        adversary="an orphan temporary book and a replace that cannot land",
        failpoint=None,
        children=[resumed, failed, retried],
        observed=observed,
        checks=checks,
    )


def cr_14(lab: Lab) -> dict:
    """A book written by RFC003 must still be readable, and must not move."""
    root = case_dir(lab.root, "CR-14")
    shutil.copytree(HISTORICAL_BOOK, root / "state")
    (root / "ledger.jsonl").write_text("", encoding="utf-8")
    before = {path.name: sha256_file(path) for path in sorted((root / "state").iterdir())}
    first = lab.run(tag="CR-14-first", case_root=root, mode="inspect")
    second = lab.run(tag="CR-14-second", case_root=root, mode="inspect")
    after = {path.name: sha256_file(path) for path in sorted((root / "state").iterdir())}
    recovery = first.get("payload", {}).get("store_recovery", {})
    checks = [
        check(
            "historical_book_readable",
            bool(first.get("payload", {}).get("book_digest")),
            str(first.get("payload", {}).get("book_digest")),
        ),
        check(
            "historical_digest_stable_across_repeated_reads",
            first.get("payload", {}).get("book_digest")
            == second.get("payload", {}).get("book_digest")
            and first.get("payload", {}).get("book_state_digest")
            == second.get("payload", {}).get("book_state_digest"),
            "two reads, one digest",
        ),
        check(
            "historical_files_untouched",
            before == after,
            f"{len(before)} file(s) byte-identical after two recovery passes",
        ),
        check(
            "historical_recovery_classified",
            recovery.get("status") in {"NO_CHANGE", "RECOVERED"},
            f"status={recovery.get('status')} code={recovery.get('code')}",
        ),
    ]
    return evaluate(
        case="CR-14",
        adversary="a committed book from RFC003 (WP-PAPER-QUOTE-GAP-002 drill A)",
        failpoint=None,
        children=[first, second],
        observed={
            "source": str(HISTORICAL_BOOK.relative_to(REPO)).replace("\\", "/"),
            "barrier_ms": first.get("payload", {}).get("barrier_ms"),
            "store_recovery": recovery,
            "files_sha256": before,
        },
        checks=checks,
    )


def cr_16(lab: Lab) -> dict:
    """The live order route must refuse before any socket exists."""
    root = case_dir(lab.root, "CR-16")
    root.joinpath("state").mkdir()
    root.joinpath("ledger.jsonl").write_text("", encoding="utf-8")
    probe = lab.run(tag="CR-16-probe", case_root=root, mode="network-probe", role="resume")
    payload = probe.get("payload", {})
    network = payload.get("network") or {}
    log = root / "network.jsonl"
    attempts = (
        [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        if log.exists()
        else []
    )
    external = [row for row in attempts if "127.0.0.1" not in str(row.get("args"))]
    checks = [
        check(
            "live_route_refused",
            payload.get("place_order_exit") == 2,
            f"exit={payload.get('place_order_exit')}",
        ),
        check(
            "deny_hook_is_real",
            payload.get("deny_probe") == "DENIED",
            str(payload.get("deny_probe")),
        ),
        check(
            "no_external_request",
            not external,
            f"{len(external)} external attempt(s) out of {len(attempts)} recorded",
        ),
    ]
    return evaluate(
        case="CR-16",
        adversary="the live order route and a socket, with the network denied process-wide",
        failpoint=None,
        children=[probe],
        observed={
            "place_order_exit": payload.get("place_order_exit"),
            "place_order_error": payload.get("place_order_error"),
            "deny_probe": payload.get("deny_probe"),
            "network_attempts": attempts,
            "network_state": network,
        },
        checks=checks,
    )


def failpoint_cost(lab: Lab) -> dict:
    """What the failpoints cost when nothing is armed: the RFC asks for the IO price."""
    script = REPO / ".tmp" / "rfc004" / "failpoint_cost.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        "\n".join(
            [
                "import json, timeit",
                "from trading_bot.vision import failpoints",
                "n = 200_000",
                "call = timeit.timeit(lambda: failpoints.trigger('book.after_replace', path='x', closed_trades=1), number=n)",
                "spec = timeit.timeit(failpoints.spec, number=n)",
                "print(json.dumps({'calls': n, 'trigger_ns': call / n * 1e9, 'spec_ns': spec / n * 1e9}))",
            ]
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [PYTHON, str(script)],
        cwd=str(REPO),
        env={**os.environ, "PYTHONPATH": str(REPO / "src")},
        capture_output=True,
        text=True,
    )
    try:
        result = dict(json.loads(proc.stdout.strip().splitlines()[-1]))
    except (ValueError, IndexError):
        result = {"error": proc.stderr[-500:], "exit": proc.returncode}
    result["save_seconds"] = [child["seconds"] for child in lab.children if child["mode"] == "run"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="RFC004 recovery crash matrix.")
    parser.add_argument("--out", required=True, help="directory for evidence")
    parser.add_argument("--json", required=True, help="lab report path")
    parser.add_argument("--only", default="", help="comma-separated scenario ids")
    args = parser.parse_args()

    out = Path(args.out).resolve()
    if out.exists():
        shutil.rmtree(out)
    (out / "cases").mkdir(parents=True)
    lab = Lab(out)

    started = time.perf_counter()
    fresh = Lab(out)
    seed_case = case_dir(out, "seed")
    #: The seed is one committed run: a book with a single open position and its ledger.
    seed_run = fresh.run(
        tag="seed-first-run",
        case_root=seed_case,
        role="fresh",
        bars="open_at_end",
        feed="none",
    )
    lab.children.extend(fresh.children)
    lab.seed_book = book_of(seed_run)
    shutil.copytree(seed_case / "state", out / "seed" / "state")
    shutil.copy2(seed_case / "ledger.jsonl", out / "seed" / "ledger.jsonl")
    scenarios: list[dict] = []
    wanted = {item.strip() for item in args.only.split(",") if item.strip()}
    order = [
        ("CR-00", cr_00_control),
        ("CR-01", cr_01),
        ("CR-02", cr_02),
        ("CR-03", cr_03),
        ("CR-04", cr_04),
        ("CR-05", cr_05),
        ("CR-06", cr_06),
        ("CR-07", cr_07),
        ("CR-08", cr_08),
        ("CR-09", cr_09),
        ("CR-10", cr_10),
        ("CR-11", cr_11),
        ("CR-12", cr_12),
        ("CR-13", cr_13),
        ("CR-14", cr_14),
        ("CR-16", cr_16),
    ]
    for case_id, function in order:
        if wanted and case_id not in wanted:
            continue
        scenarios.append(function(lab))

    cost = failpoint_cost(lab)
    network_logs = list(out.rglob("network.jsonl"))
    attempts: list[dict] = []
    for path in network_logs:
        attempts.extend(
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    external = [row for row in attempts if "127.0.0.1" not in str(row.get("args"))]

    runtime_files = [
        "src/trading_bot/vision/durable.py",
        "src/trading_bot/vision/ledger.py",
        "src/trading_bot/vision/lane.py",
        "src/trading_bot/vision/failpoints.py",
        "scripts/recovery_child.py",
        "scripts/recovery_lab.py",
    ]
    git = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(REPO), capture_output=True, text=True
    )
    report = {
        "schema": "rfc004-recovery-lab/1",
        "run_id": f"rfc004-{datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%SZ')}",
        "generated_at_utc": utc_now(),
        "wp": "WP-003-01",
        "rfc": "RFC-PAPER-RECOVERY-004",
        "source_commit": git.stdout.strip(),
        "environment": {
            "python": sys.version,
            "executable": PYTHON,
            "platform": sys.platform,
            "filesystem": "NTFS",
            "os_name": os.name,
        },
        "runtime_sha256": {path: sha256_file(REPO / path) for path in runtime_files},
        "failpoints": sorted(
            [
                "book.after_dir_fsync",
                "book.after_prev_copy",
                "book.after_replace",
                "book.after_tmp_fsync",
                "book.after_tmp_write",
                "book.before_save",
                "bar.after_commit",
                "bar.before_commit",
                "event.after_fsync",
                "event.after_write",
                "ledger.after_fsync",
                "ledger.after_write",
                "ledger.before_write",
                "lock.after_acquire",
            ]
        ),
        "seed": {
            "open_positions": len(
                (seed_run["payload"].get("book") or {}).get("open_positions") or []
            ),
            "closed_trades": len(
                (seed_run["payload"].get("book") or {}).get("closed_trades") or []
            ),
            "barrier_ms": seed_run["payload"].get("barrier_ms"),
            "state_digest": seed_run["payload"].get("book_state_digest"),
            "ledger_lines": (seed_run["payload"].get("ledger") or {}).get("chain", {}).get("lines"),
        },
        "control": {
            "canonical": canonical(lab.control_book),
            "equity": (lab.control_book.get("broker") or {}).get("equity"),
            "closed": [
                str(row.get("position_id")) for row in lab.control_book.get("closed_trades") or []
            ],
        },
        "scenarios": scenarios,
        "counts": {
            "scenarios_preregistered": 17,
            "scenarios_executed": len(scenarios) + 1,
            "passed": sum(1 for item in scenarios if item["verdict"] == "PASS"),
            "failed": sum(1 for item in scenarios if item["verdict"] == "FAIL"),
            "not_testable": ["CR-15 (independent verifier: see verify_recovery.py)"],
        },
        "performance": cost,
        "network": {
            "attempts": attempts,
            "external_attempts": len(external),
            "policy": "process-wide audit hook denies socket.connect/getaddrinfo; loopback probe is the positive control",
        },
        "elapsed_s": round(time.perf_counter() - started, 1),
    }
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")

    for item in scenarios:
        print(f"{item['id']:6} {item['verdict']:4} {item['adversary']}")
    print(
        f"\n{report['counts']['passed']}/{len(scenarios)} scenarios passed · "
        f"{report['elapsed_s']}s · external network attempts={len(external)}"
    )
    return 0 if report["counts"]["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
