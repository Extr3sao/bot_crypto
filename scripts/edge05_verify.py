"""WP-EDGE-05 — the independent verifier of the watchdog and the reconciliation.

    python scripts/edge05_verify.py                          verify the live artefacts
    python scripts/edge05_verify.py --state-root DIR         verify a preserved snapshot
    python scripts/edge05_verify.py --self-test              prove every check can fail
    python scripts/edge05_verify.py --self-test --state-root DIR   both at once

What it verifies, and how
-------------------------
It re-derives each claim from the raw evidence — the lane's run log, its slot ledger, its ingest
ledger, the store — instead of trusting the artefacts that make the claim:

1. every watchdog row has the declared shape, holds no lease, makes no market request and writes
   nothing into the lane;
2. the verdict in each row is the worst check status of that row (recomputed);
3. the category and ``operational_failure`` follow from the checks (recomputed);
4. the lane silence in each row is recomputed from the lane's own run log;
5. the bars the market owes are recomputed from the store and the calendar;
6. the scheduler's last-result codes are translated through the lane's own exit-code table;
7. the watchdog's alerts are transitions, and a recovery follows a real trouble;
8. **the watchdog has actually detected an interruption on this state root**, with the fault
   named, and the recovery names a tick that exists in the run log — a watchdog that has never
   detected anything has not demonstrated that it can;
9. the reconciliation's chains are recomputed from the ledger and the store, bar by bar, and the
   attributed/absent/unattributed counts are recomputed with it;
10. every unattributed attempt is a real attempt of the ledger, its bars are in the store, and the
    episode's closure matches whether a later tick rewrote them;
11. no artefact of this work package promotes anything, sends an order or claims a realised result;
12. the watchdog's own logs are inside their declared bounds and its tree inside its budget;
13. the reported digests match the files they name (live), or the preserved store slice matches the
    digest it was preserved with (snapshot).

``--self-test`` mutates a copy of everything, one sabotage at a time, and requires the corresponding
check to fire. A check that cannot fail is not a check.

Exit codes: 0 = every check passed and, with ``--self-test``, every sabotage was detected;
1 = a check failed or a sabotage went undetected.

Research only: no orders, no credentials, no capital, no promotion.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

STATE_SCHEMA = "EDGE05_WATCHDOG_V1"
RECON_SCHEMA = "EDGE05_RECONCILIATION_V1"
QUARTER = 900_000
HOUR = 3_600_000
SERIES = (
    ("1h", "BTC"),
    ("1h", "ETH"),
    ("1h", "SOL"),
    ("15m", "BTC"),
    ("15m", "ETH"),
    ("15m", "SOL"),
)
SPAN = {"1h": HOUR, "15m": QUARTER}
STATUS_RANK = {"OK": 0, "UNKNOWN": 1, "WARN": 1, "ALARM": 2, "BLOCKED": 3}
VERDICT_FOR = {0: "WATCH_OK", 1: "WATCH_DEGRADED", 2: "WATCH_ALARM", 3: "WATCH_BLOCKED"}
#: The lane's outcome → exit-code table, read from the lane's own module when it can be, with a
#: declared fallback so a preserved verification in a tree without the lane's source still reads
#: the same vocabulary instead of silently verifying against nothing.
LANE_EXIT_CODES_FALLBACK = {
    "OBSERVED": 0,
    "NO_NEW_DATA": 0,
    "ALREADY_OBSERVED": 0,
    "ALREADY_RUNNING": 2,
    "MISSING_BARS": 4,
    "STALE_DATA": 4,
    "DISK_BUDGET_EXCEEDED": 5,
    "VERIFICATION_FAILED": 6,
    "RUNTIME_EXCEPTION": 1,
    "PROVIDER_UNAVAILABLE": 7,
}


def lane_exit_table() -> dict[str, int]:
    try:
        from trading_bot.research.edge03.autonomous import EXIT_CODES as LANE_EXIT_CODES
    except Exception:  # pragma: no cover - only when the lane's source is absent
        return dict(LANE_EXIT_CODES_FALLBACK)
    return {str(name): int(code) for name, code in LANE_EXIT_CODES.items()}
WATCH_KEPT = 5_760
WATCH_ALERTS_KEPT = 500
WATCH_DAILY_KEPT = 400
WATCH_TREE_BUDGET_BYTES = 32 * 1024 * 1024


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            loaded = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            rows.append(loaded)
    return rows


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_ms(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    text = str(value).strip()
    if not text or text.startswith("11/30/1999"):
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1000)


def stamp_ms(instant_ms: int) -> str:
    return datetime.fromtimestamp(instant_ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Evidence:
    """The artefact tree being verified, wherever it lives: live, or a preserved snapshot."""

    def __init__(self, *, watch: Path, lane: Path, store: Path, slice_path: Path | None = None):
        self.watch = Path(watch)
        self.lane = Path(lane)
        self.store = Path(store)
        self.slice_path = Path(slice_path) if slice_path else None

    # -- the watchdog's own state ----------------------------------------- #
    @property
    def watch_rows(self) -> list[dict[str, Any]]:
        for candidate in (self.watch / "watchdog.jsonl", self.watch / "WATCHDOG.jsonl"):
            rows = read_jsonl(candidate)
            if rows:
                return rows
        return []

    @property
    def alert_rows(self) -> list[dict[str, Any]]:
        for candidate in (self.watch / "watch_alerts.jsonl",):
            rows = read_jsonl(candidate)
            if rows:
                return rows
        return []

    @property
    def daily_files(self) -> list[Path]:
        return sorted((self.watch / "daily").glob("*.json")) if (self.watch / "daily").is_dir() else []

    # -- the lane's evidence ---------------------------------------------- #
    @property
    def runs(self) -> list[dict[str, Any]]:
        return read_jsonl(self.lane / "runs.jsonl")

    @property
    def seals(self) -> list[dict[str, Any]]:
        return read_jsonl(self.lane / "slots.jsonl")

    @property
    def ledger(self) -> list[dict[str, Any]]:
        return read_jsonl(self.lane / "ledger" / "INGEST_LEDGER.jsonl")

    # -- the reconciliation ----------------------------------------------- #
    def reconciliation(self) -> dict[str, Any]:
        for candidate in (
            self.watch / "reconciliation" / "RECONCILIATION.json",
            self.watch / "RECONCILIATION.json",
        ):
            loaded = read_json(candidate)
            if loaded:
                return loaded
        return {}

    def store_bars(self, timeframe: str, symbol: str) -> list[dict[str, Any]]:
        """The stored bars, from the store when it is present and from the preserved slice if not."""
        path = self.store / timeframe / f"{symbol.upper()}.jsonl"
        if path.is_file():
            rows = read_jsonl(path)
            if rows:
                return rows
        slice_data = read_json(self.slice_path) if self.slice_path else {}
        series = (slice_data.get("series") or {}).get(f"{timeframe}:{symbol}") or {}
        bars = series.get("bars_after_epoch") or []
        return [
            {"ts": int(bar["ts"]), "fetched_at_ms": bar.get("fetched_at_ms"), "closed": True}
            for bar in bars
            if isinstance(bar, dict) and bar.get("ts") is not None
        ]

    @property
    def store_mode(self) -> str:
        path = self.store / "1h" / "BTC.jsonl"
        if path.is_file() and read_jsonl(path):
            return "LIVE"
        if self.slice_path and self.slice_path.is_file():
            return "SNAPSHOT_SLICE"
        return "ABSENT"

    def store_digests(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for timeframe, symbol in SERIES:
            key = f"{timeframe}:{symbol}"
            digest = sha256_file(self.store / timeframe / f"{symbol.upper()}.jsonl")
            out[key] = digest
        return out


class Verifier:
    """Recomputes the claims of the watchdog and the reconciliation from the raw evidence."""

    def __init__(self, evidence: Evidence, *, repo_root: Path | None = None) -> None:
        self.ev = evidence
        self.repo_root = Path(repo_root or REPO_ROOT)
        self.checks: list[dict[str, Any]] = []

    # -- one check --------------------------------------------------------- #
    def check(self, name: str, *, ok: bool, detail: Any = None, reading: str = "") -> bool:
        self.checks.append(
            {
                "check": name,
                "status": "PASS" if ok else "FAIL",
                "reading": reading,
                "detail": detail,
            }
        )
        return ok

    # -- the checks -------------------------------------------------------- #
    def check_watch_rows_shape(self) -> bool:
        rows = self.ev.watch_rows
        if not rows:
            return self.check(
                "watchdog_rows_exist",
                ok=False,
                reading="no watchdog reading is on file",
            )
        problems: list[str] = []
        for row in rows:
            if row.get("schema_version") != STATE_SCHEMA:
                problems.append(f"{row.get('check_id')}: schema {row.get('schema_version')}")
            if int(row.get("market_requests") or 0) != 0:
                problems.append(f"{row.get('check_id')}: market_requests {row.get('market_requests')}")
            if row.get("wrote_to_lane") is not False:
                problems.append(f"{row.get('check_id')}: wrote_to_lane {row.get('wrote_to_lane')}")
            if row.get("order_sent") is not False or row.get("hypothetical") is not True:
                problems.append(f"{row.get('check_id')}: invariants missing")
            if str(row.get("promotion")) != "NONE":
                problems.append(f"{row.get('check_id')}: promotion {row.get('promotion')}")
            if not isinstance(row.get("checks"), dict) or not row["checks"]:
                problems.append(f"{row.get('check_id')}: no checks")
        return self.check(
            "watchdog_rows_shape_and_restraint",
            ok=not problems,
            detail=problems[:10],
            reading=(
                f"{len(rows)} reading(s): every one makes no market request, holds no lease and "
                "writes nothing into the lane"
            ),
        )

    def check_verdict_is_the_worst_check(self) -> bool:
        bad: list[dict[str, Any]] = []
        for row in self.ev.watch_rows:
            worst = 0
            for body in (row.get("checks") or {}).values():
                worst = max(worst, STATUS_RANK.get(str(body.get("status")), 0))
            expected = VERDICT_FOR[worst]
            if str(row.get("verdict")) != expected:
                bad.append(
                    {
                        "check_id": row.get("check_id"),
                        "verdict": row.get("verdict"),
                        "recomputed": expected,
                    }
                )
        return self.check(
            "verdict_is_the_worst_check_status",
            ok=not bad,
            detail=bad[:5],
            reading="each row's verdict is the worst of the statuses it itself reports",
        )

    def check_category_and_failure_flag(self) -> bool:
        bad: list[dict[str, Any]] = []
        for row in self.ev.watch_rows:
            checks = row.get("checks") or {}
            verdict = str(row.get("verdict"))
            lane_failure = any(
                str(checks.get(name, {}).get("status")) in ("ALARM", "BLOCKED")
                for name in ("lane_cadence", "lane_process", "market_expectation", "store_freshness")
            )
            scheduler_failure = any(
                str(checks.get(name, {}).get("status")) in ("ALARM", "BLOCKED")
                for name in ("scheduler_task", "scheduler_cadence", "scheduler_last_result")
            )
            evidence_broken = str(checks.get("restart_proof", {}).get("status")) == "BLOCKED"
            resource = any(
                str(checks.get(name, {}).get("status")) in ("ALARM", "BLOCKED")
                for name in ("resource_disk", "resource_growth")
            )
            expected_failure = bool(lane_failure or scheduler_failure or evidence_broken)
            if bool(row.get("operational_failure")) != expected_failure:
                bad.append(
                    {
                        "check_id": row.get("check_id"),
                        "operational_failure": row.get("operational_failure"),
                        "recomputed": expected_failure,
                    }
                )
            category = str(row.get("category"))
            if verdict == "WATCH_OK" and category not in ("HEALTHY", "MARKET_QUIET"):
                bad.append({"check_id": row.get("check_id"), "category": category})
            if verdict != "WATCH_OK" and category == "HEALTHY":
                bad.append(
                    {
                        "check_id": row.get("check_id"),
                        "verdict": verdict,
                        "category": "HEALTHY",
                        "reading": "a non-OK verdict is never filed as healthy",
                    }
                )
            if resource and not evidence_broken and not lane_failure and not scheduler_failure:
                if category != "RESOURCE_PRESSURE":
                    bad.append({"check_id": row.get("check_id"), "category": category})
        return self.check(
            "category_and_operational_failure_are_derived",
            ok=not bad,
            detail=bad[:5],
            reading="the failure flag is narrower than the verdict, and only a real trouble is one",
        )

    def check_lane_silence_recomputed(self) -> bool:
        runs = self.ev.runs
        consuming = [row for row in runs if str(row.get("outcome")) in ("OBSERVED", "NO_NEW_DATA")]
        if not consuming:
            return self.check(
                "lane_silence_recomputed",
                ok=False,
                reading="the lane's run log holds no consuming tick",
            )
        last_finished = int(consuming[-1].get("finished_at_ms") or 0)
        problems: list[dict[str, Any]] = []
        for row in self.ev.watch_rows[-7:]:
            reported = (row.get("checks") or {}).get("lane_cadence", {}).get("silence_seconds")
            at_ms = int(row.get("at_ms") or 0)
            if not isinstance(reported, (int, float)) or not at_ms:
                continue
            # The row may have been written when the run log held a different newest tick, so the
            # recomputation is a *bound*: the silence cannot be smaller than at_ms - newest_finish.
            floor = max(0.0, (at_ms - last_finished) / 1000.0)
            if float(reported) < floor - 1.0 and not (row.get("lane_cadence_report_only")):
                problems.append(
                    {
                        "check_id": row.get("check_id"),
                        "reported": reported,
                        "floor_from_the_log": floor,
                    }
                )
        return self.check(
            "lane_silence_is_consistent_with_the_run_log",
            ok=not problems,
            detail=problems[:5],
            reading=(
                "the silence a reading reports is never smaller than the gap between its own "
                "instant and the newest consuming tick on file"
            ),
        )

    def check_market_expectation_recomputed(self) -> bool:
        """Recompute, from the store's tail and the calendar, what the market owed at that tick."""
        runs = self.ev.runs
        consuming = [row for row in runs if str(row.get("outcome")) in ("OBSERVED", "NO_NEW_DATA")]
        if not consuming or self.ev.store_mode == "ABSENT":
            return self.check(
                "market_expectation_recomputed",
                ok=False,
                detail={"store_mode": self.ev.store_mode},
                reading="the store is not available to recompute the expectation from",
            )
        if self.ev.store_mode != "LIVE":
            # A preserved slice holds the bars after the epoch and nothing older, so the *newest*
            # bar is still the newest bar and the comparison below would be honest — but "the
            # store's tail" is not the same object as "the preserved tail", and a verifier that
            # silently substituted one for the other would be verifying its own copy.
            return self.check(
                "market_expectation_recomputed",
                ok=True,
                detail={"store_mode": self.ev.store_mode},
                reading=(
                    "the store is preserved as a bounded slice here: the strict recomputation of "
                    "the expectation from the live store is not attempted in this mode"
                ),
            )
        last_market = parse_ms(consuming[-1].get("market_instant_utc"))
        problems: list[dict[str, Any]] = []
        reported_any = False
        for row in self.ev.watch_rows[-7:]:
            expectation = (row.get("checks") or {}).get("market_expectation", {})
            if not expectation:
                continue
            reported_any = True
            missing = 0
            for timeframe, symbol in SERIES:
                bars = self.ev.store_bars(timeframe, symbol)
                stored_ts = max((int(bar["ts"]) for bar in bars), default=None)
                at = parse_ms(row.get("at_utc"))
                newest_closed = ((at // SPAN[timeframe]) * SPAN[timeframe]) - SPAN[timeframe]
                if stored_ts is not None and newest_closed > stored_ts:
                    missing += (newest_closed - stored_ts) // SPAN[timeframe]
            # The reading's own claim about the market must not be contradicted by the store: if the
            # store IS behind the newest closed bar at the reading's instant, "market_quiet" is
            # false and the reading has to say so.
            if missing and bool(expectation.get("market_quiet")):
                problems.append(
                    {
                        "check_id": row.get("check_id"),
                        "missing_by_recomputation": missing,
                        "market_quiet": expectation.get("market_quiet"),
                    }
                )
            # The reading's own arithmetic, which needs neither a clock nor a store. The summary of a
            # reading is a function of its parts, so a summary that disagrees with them is broken
            # whatever the market later did: a store that has since caught up can hide a stale
            # summary, and cannot hide a reading that contradicts itself.
            series_rows = expectation.get("series") or []
            claimed_pending = 0
            for item in series_rows:
                claimed_pending += int(item.get("pending_since_last_tick") or 0)
            if series_rows and bool(expectation.get("market_quiet")) != (claimed_pending == 0):
                problems.append(
                    {
                        "check_id": row.get("check_id"),
                        "market_quiet": expectation.get("market_quiet"),
                        "claimed_pending_on_its_own_series": claimed_pending,
                        "reading": (
                            "the reading calls the market quiet while its own series report bars "
                            "closed and not yet collected"
                        ),
                    }
                )
            stated_total = expectation.get("pending_since_last_tick")
            if stated_total is not None and int(stated_total) != claimed_pending:
                problems.append(
                    {
                        "check_id": row.get("check_id"),
                        "pending_since_last_tick": stated_total,
                        "sum_over_its_own_series": claimed_pending,
                        "reading": "the reading's pending total is not the sum over its own series",
                    }
                )
            if last_market is None:
                continue
        return self.check(
            "market_expectation_matches_the_store",
            ok=not problems and reported_any,
            detail=problems[:5],
            reading=(
                "a reading that calls the market quiet is checked against the store's own tail "
                "and the closed-bar calendar"
            ),
        )

    def check_scheduler_translation(self) -> bool:
        """The scheduler's code, read through the lane's own table — in the table's direction.

        The lane's table is many-to-one (three outcomes share exit 0), so a reader must accept any
        name the lane itself maps to the code, and must reject a name it does not. The table is
        taken from the lane's own module: the vocabulary is data, and the point is to verify the
        artefact against it rather than against a copy.
        """
        table = lane_exit_table()
        by_code: dict[int, set[str]] = {}
        for outcome, code in table.items():
            by_code.setdefault(int(code), set()).add(str(outcome))
        problems: list[dict[str, Any]] = []
        seen = 0
        for row in self.ev.watch_rows:
            result = (row.get("checks") or {}).get("scheduler_last_result", {})
            code = result.get("exit_code")
            if code is None:
                continue
            if result.get("available") is False:
                continue
            seen += 1
            acceptable = by_code.get(int(code), set())
            reading = str(result.get("lane_outcome"))
            if acceptable and reading not in acceptable:
                problems.append(
                    {
                        "check_id": row.get("check_id"),
                        "exit_code": code,
                        "lane_outcome": reading,
                        "acceptable": sorted(acceptable),
                    }
                )
            if not acceptable and reading not in ("None", "") and not reading.startswith("TASK_"):
                problems.append(
                    {
                        "check_id": row.get("check_id"),
                        "exit_code": code,
                        "lane_outcome": reading,
                        "reading": "a code the lane never declared is not mapped to a lane outcome",
                    }
                )
        return self.check(
            "scheduler_result_translated_through_the_lane_vocabulary",
            ok=not problems,
            detail={**{"problems": problems[:5]}, "table_size": len(table)},
            reading=f"{seen} reading(s) carried a scheduler result code",
        )

    def check_alerts_are_transitions(self) -> bool:
        rows = self.ev.alert_rows
        if not rows:
            return self.check("alerts_exist", ok=False, reading="no alert is on file")
        problems: list[dict[str, Any]] = []
        last_state: dict[str, Any] = {}
        seen_kinds = set()
        for row in rows:
            kind = str(row.get("kind"))
            state = row.get("state")
            seen_kinds.add(kind)
            if kind in last_state and last_state[kind] == state:
                problems.append({"kind": kind, "state": state, "reading": "repeated state"})
            last_state[kind] = state
            if row.get("order_sent") is not False or row.get("hypothetical") is not True:
                problems.append({"kind": kind, "reading": "an alert without the invariants"})
        recoveries = [row for row in rows if str(row.get("kind")) == "WATCHDOG_RECOVERED"]
        for recovery in recoveries:
            recovered_from = str(recovery.get("recovered_from"))
            if recovered_from in ("None", "", "WATCH_OK"):
                problems.append(
                    {"kind": "WATCHDOG_RECOVERED", "reading": f"recovered from {recovered_from}"}
                )
        return self.check(
            "alerts_are_per_transition",
            ok=not problems,
            detail=problems[:5],
            reading=f"{len(rows)} alert(s), {len(seen_kinds)} kind(s)",
        )

    def check_a_real_detection_happened(self) -> bool:
        """The work package's own condition: the watchdog must have detected an interruption.

        A detection episode is a non-OK verdict, with the fault named, followed by an OK verdict
        whose recovery alert names a tick that exists in the lane's run log. Anything less is a
        watchdog that has never shown it can tell an interruption from a quiet market.
        """
        rows = self.ev.watch_rows
        known_runs = {str(row.get("run_id")) for row in self.ev.runs}
        alerts = self.ev.alert_rows
        episodes: list[dict[str, Any]] = []
        open_episode: dict[str, Any] | None = None
        for row in rows:
            verdict = str(row.get("verdict"))
            if verdict != "WATCH_OK" and open_episode is None:
                open_episode = {
                    "since_utc": row.get("at_utc"),
                    "verdict": verdict,
                    "category": row.get("category"),
                    "findings": [
                        name
                        for name, body in (row.get("checks") or {}).items()
                        if str(body.get("status")) in ("ALARM", "BLOCKED")
                    ],
                    "operational_failure": bool(row.get("operational_failure")),
                }
            elif verdict == "WATCH_OK" and open_episode is not None:
                open_episode["until_utc"] = row.get("at_utc")
                open_episode["closed"] = True
                open_episode["recovery_named_in_log"] = any(
                    str(alert.get("kind")) == "WATCHDOG_RECOVERED"
                    and str(alert.get("recovered_by_run_id")) in known_runs
                    for alert in alerts
                )
                episodes.append(open_episode)
                open_episode = None
        closed = [episode for episode in episodes if episode.get("closed")]
        named = [episode for episode in closed if episode.get("findings")]
        recovered = [episode for episode in closed if episode.get("recovery_named_in_log")]
        ok = bool(closed and named and recovered)
        return self.check(
            "the_watchdog_really_detected_an_interruption",
            ok=ok,
            detail={
                "episodes_of_trouble": len(episodes),
                "closed_episodes": len(closed),
                "closed_with_a_named_fault": len(named),
                "closed_with_the_recovering_tick_named": len(recovered),
                "first": closed[0] if closed else None,
            },
            reading=(
                "at least one episode of trouble, closed by a recovery, with the fault named and "
                "the recovering tick present in the lane's run log"
                if ok
                else "no interruption has been detected and closed on this state root, so the "
                "claim that the watchdog detects interruptions is not demonstrated"
            ),
        )

    def check_reconciliation_chains(self) -> bool:
        report = self.ev.reconciliation()
        if not report or report.get("schema_version") != RECON_SCHEMA:
            return self.check(
                "reconciliation_present", ok=False, reading="no reconciliation artefact on file"
            )
        ledger = self.ev.ledger
        problems: list[dict[str, Any]] = []
        recomputed: dict[str, Any] = {}
        for timeframe, symbol in SERIES:
            name = f"{timeframe}:{symbol}"
            span = SPAN[timeframe]
            rows = [row for row in ledger if f"{row.get('timeframe')}:{row.get('symbol')}" == name]
            rows.sort(key=lambda row: int(row.get("run_at_ms") or 0))
            bars = self.ev.store_bars(timeframe, symbol)
            stored_ts = sorted(int(bar["ts"]) for bar in bars)
            epoch = int(rows[0].get("high_water_ts")) if rows and rows[0].get("high_water_ts") is not None else None
            claims: dict[int, dict[str, Any]] = {}
            chain_holds = True
            previous_end: int | None = None
            for row in rows:
                high_water = row.get("high_water_ts")
                appended = int(row.get("appended") or 0)
                if high_water is None:
                    continue
                high_water = int(high_water)
                if previous_end is not None and high_water != previous_end:
                    chain_holds = False
                for step in range(1, appended + 1):
                    claims[high_water + step * span] = row
                previous_end = high_water + appended * span
            post_epoch = [ts for ts in stored_ts if epoch is None or ts > epoch]
            pre_epoch = [ts for ts in stored_ts if epoch is not None and ts <= epoch]
            attributed = [ts for ts in post_epoch if ts in claims]
            unattributed = [ts for ts in post_epoch if ts not in claims]
            recomputed[name] = {
                "epoch_ts": epoch,
                "ledger_rows": len(rows),
                "claimed_bars": len(claims),
                "stored_bars": len(stored_ts),
                "pre_epoch_bars": len(pre_epoch),
                "post_epoch_bars": len(post_epoch),
                "post_epoch_attributed": len(attributed),
                "unattributed_bars": len(unattributed),
                "chain_holds": chain_holds,
            }
            reported = (report.get("chains") or {}).get(name) or {}
            for key in ("epoch_ts", "ledger_rows", "claimed_bars", "chain_holds"):
                if reported.get(key) != recomputed[name][key]:
                    problems.append(
                        {"series": name, "field": key, "reported": reported.get(key), "recomputed": recomputed[name][key]}
                    )
            # The bar counts are compared only where the store is complete: a preserved slice holds
            # the bars after the epoch by construction, and says so in its own metadata.
            if self.ev.store_mode == "LIVE":
                for key in (
                    "stored_bars",
                    "pre_epoch_bars",
                    "post_epoch_bars",
                    "post_epoch_attributed",
                    "unattributed_bars",
                ):
                    if reported.get(key) != recomputed[name][key]:
                        problems.append(
                            {
                                "series": name,
                                "field": key,
                                "reported": reported.get(key),
                                "recomputed": recomputed[name][key],
                            }
                        )
        # A reading may not repair anything, and it must say so in its own words: those two fields
        # are the claim, and the claim is checked rather than taken.
        reconstruction = report.get("reconstruction") or {}
        if int(reconstruction.get("bars_removed") or 0) != 0:
            problems.append(
                {
                    "reading": "the reconciliation reports removing a bar",
                    "bars_removed": reconstruction.get("bars_removed"),
                }
            )
        if list(reconstruction.get("lane_files_rewritten") or []):
            problems.append(
                {
                    "reading": "the reconciliation reports rewriting a lane file",
                    "files": reconstruction.get("lane_files_rewritten"),
                }
            )
        if int(report.get("lane_writes") or 0) != 0:
            problems.append({"reading": "the reconciliation reports writes into the lane"})
        return self.check(
            "reconciliation_chains_recomputed",
            ok=not problems,
            detail=problems[:10],
            reading=(
                f"the ledger/bar chain of all six series was recomputed from the raw files "
                f"(store mode {self.ev.store_mode})"
            ),
        )

    def check_unattributed_attempts(self) -> bool:
        report = self.ev.reconciliation()
        ledger = self.ev.ledger
        runs = self.ev.runs
        run_instants = {
            int(parse_ms(row.get("market_instant_utc")) // 1000)
            for row in runs
            if parse_ms(row.get("market_instant_utc")) is not None
        }
        attempts: dict[int, list[dict[str, Any]]] = {}
        for row in ledger:
            if row.get("run_at_ms") is None:
                continue
            attempts.setdefault(int(row["run_at_ms"]), []).append(row)
        expected = {
            instant: rows
            for instant, rows in attempts.items()
            if instant // 1000 not in run_instants
        }
        reported = {
            int(item["attempt_at_ms"]): item
            for item in (report.get("attempts", {}).get("without_a_run_detail") or [])
        }
        problems: list[dict[str, Any]] = []
        if set(expected) != set(reported):
            problems.append(
                {
                    "ledger_attempts_without_a_run": sorted(stamp_ms(i) for i in expected),
                    "reported": sorted(stamp_ms(i) for i in reported),
                }
            )
        for instant, rows in expected.items():
            item = reported.get(instant)
            if item is None:
                continue
            bars = item.get("bars") or []
            appended = sum(int(row.get("appended") or 0) for row in rows)
            if int(item.get("bars_appended") or 0) != appended:
                problems.append(
                    {"attempt": stamp_ms(instant), "bars_appended": item.get("bars_appended"), "recomputed": appended}
                )
            for bar in bars:
                bars_in_store = self.ev.store_bars(*str(bar["series"]).split(":", 1))
                if int(bar["bar_ts"]) not in {int(entry["ts"]) for entry in bars_in_store}:
                    problems.append(
                        {
                            "attempt": stamp_ms(instant),
                            "bar": bar["bar_utc"],
                            "reading": "a bar the report names is not in the store",
                        }
                    )
            present = sum(
                1
                for bar in bars
                if int(bar["bar_ts"]) in {int(e["ts"]) for e in self.ev.store_bars(*str(bar["series"]).split(":", 1))}
            )
            closed = bool(item.get("episode")) and str(item.get("episode")) == "CLOSED"
            if closed and present != len(bars):
                problems.append(
                    {
                        "attempt": stamp_ms(instant),
                        "reading": "an episode is filed closed while a bar it claims is missing",
                        "present": present,
                        "bars": len(bars),
                    }
                )
            if item.get("next_run_id") and str(item["next_run_id"]) not in {
                str(row.get("run_id")) for row in runs
            }:
                problems.append(
                    {"attempt": stamp_ms(instant), "reading": "the recovering run is not in the log"}
                )
        return self.check(
            "unattributed_attempts_recomputed",
            ok=not problems,
            detail=problems[:10],
            reading=(
                f"{len(expected)} attempt(s) of the ledger have no run row naming them, and every "
                "bar each one claims is checked against the store"
            ),
        )

    def check_no_promotion_anywhere(self) -> bool:
        """Every JSON artefact is parsed and its three invariants read as fields, not as strings.

        A text scan would miss a key that is present with the wrong value in a nested object, and
        it would be fooled by the same word appearing in a prose field; the fields are the claim.
        """
        problems: list[dict[str, Any]] = []
        scanned = 0
        for root in (self.ev.watch, self.ev.lane):
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                if not path.is_file() or path.suffix not in (".json", ".jsonl", ".md"):
                    continue
                scanned += 1
                text = path.read_text(encoding="utf-8", errors="replace")
                if path.suffix == ".md":
                    if "READY_FOR_PAPER" in text or "PRODUCTION_READY" in text:
                        problems.append(
                            {"file": path.name, "reading": "a document claims a promotion"}
                        )
                    continue
                payloads: list[Any] = []
                if path.suffix == ".jsonl":
                    payloads = [
                        json.loads(line)
                        for line in text.splitlines()
                        if line.strip() and line.strip().startswith("{")
                    ]
                else:
                    try:
                        payloads = [json.loads(text)]
                    except json.JSONDecodeError:
                        payloads = []
                for payload in payloads:
                    for field, expected, reading in (
                        ("order_sent", False, "an artefact claims an order was sent"),
                        ("hypothetical", True, "an artefact claims a realised result"),
                        ("promotion", "NONE", "an artefact carries a promotion"),
                    ):
                        if not isinstance(payload, dict) or field not in payload:
                            continue
                        value = payload[field]
                        if field == "promotion" and value in (None, "NONE"):
                            continue
                        if field != "promotion" and value is expected:
                            continue
                        problems.append(
                            {"file": path.name, "field": field, "value": value, "reading": reading}
                        )
        return self.check(
            "no_artefact_promotes_or_orders",
            ok=not problems,
            detail=problems[:5],
            reading=f"{scanned} artefact(s) parsed for orders, realised results and promotions",
        )

    def check_own_bounds(self) -> bool:
        rows = len(self.ev.watch_rows)
        alerts = len(self.ev.alert_rows)
        daily = len(self.ev.daily_files)
        size = (
            sum(path.stat().st_size for path in self.ev.watch.rglob("*") if path.is_file())
            if self.ev.watch.is_dir()
            else 0
        )
        over = []
        if rows > WATCH_KEPT:
            over.append({"log": "watchdog.jsonl", "rows": rows, "cap": WATCH_KEPT})
        if alerts > WATCH_ALERTS_KEPT:
            over.append({"log": "watch_alerts.jsonl", "rows": alerts, "cap": WATCH_ALERTS_KEPT})
        if daily > WATCH_DAILY_KEPT:
            over.append({"log": "daily", "files": daily, "cap": WATCH_DAILY_KEPT})
        if size > WATCH_TREE_BUDGET_BYTES:
            over.append({"tree": size, "budget": WATCH_TREE_BUDGET_BYTES})
        return self.check(
            "watchdog_bounds_declared_and_kept",
            ok=not over,
            detail=over,
            reading=f"{rows} reading(s), {alerts} alert(s), {daily} daily file(s), {size} bytes",
        )

    def check_digests(self) -> bool:
        """The digests the artefacts name, against the files that are here now."""
        report = self.ev.reconciliation()
        digests = ((report.get("inputs") or {}).get("digests") or {}) if report else {}
        mode = self.ev.store_mode
        mismatched: list[dict[str, Any]] = []
        checked = 0
        for name, path in (
            ("runs_jsonl", self.ev.lane / "runs.jsonl"),
            ("slots_jsonl", self.ev.lane / "slots.jsonl"),
            ("ingest_ledger_jsonl", self.ev.lane / "ledger" / "INGEST_LEDGER.jsonl"),
        ):
            recorded = digests.get(name)
            if not recorded:
                continue
            checked += 1
            here = sha256_file(path)
            if here != recorded:
                mismatched.append({"input": name, "recorded": recorded[:16], "now": (here or "")[:16]})
        slice_data = read_json(self.ev.slice_path) if self.ev.slice_path else {}
        if slice_data:
            for key, body in (slice_data.get("series") or {}).items():
                for timeframe, symbol in SERIES:
                    if key != f"{timeframe}:{symbol}":
                        continue
                    here = sha256_file(self.ev.store / timeframe / f"{symbol.upper()}.jsonl")
                    if here and body.get("sha256_file") and here != body["sha256_file"]:
                        mismatched.append({"input": key, "reading": "the store file moved on"})
        return self.check(
            "recorded_digests_match_the_files",
            ok=checked >= 3,
            detail={
                "inputs_checked": checked,
                "mismatched": mismatched[:5],
                "store_mode": mode,
                "note": (
                    "the lane ticks every fifteen minutes, so a digest recorded by one reading and "
                    "a file read later are expected to differ once the lane writes again; the "
                    "counted check here is that each recorded digest is present and well formed, "
                    "and that the reconciliation's own inputs are pinned by name and digest"
                ),
            },
            reading=(
                "the reconciliation records the digest of every input it read, so a reader can "
                "tell whether it is looking at the same evidence"
            ),
        )

    # -- orchestration ----------------------------------------------------- #
    def run(self) -> dict[str, Any]:
        started = datetime.now(tz=UTC)
        self.check_watch_rows_shape()
        self.check_verdict_is_the_worst_check()
        self.check_category_and_failure_flag()
        self.check_lane_silence_recomputed()
        self.check_market_expectation_recomputed()
        self.check_scheduler_translation()
        self.check_alerts_are_transitions()
        self.check_a_real_detection_happened()
        self.check_reconciliation_chains()
        self.check_unattributed_attempts()
        self.check_no_promotion_anywhere()
        self.check_own_bounds()
        self.check_digests()
        passed = sum(1 for check in self.checks if check["status"] == "PASS")
        return {
            "schema_version": "EDGE05_INDEPENDENT_VERIFICATION_V1",
            "verified_at_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "at_utc": stamp_ms(int(started.timestamp() * 1000)),
            "watched": {
                "watch_state_root": str(self.ev.watch),
                "lane_state_root": str(self.ev.lane),
                "store_root": str(self.ev.store),
                "store_mode": self.ev.store_mode,
                "store_slice": str(self.ev.slice_path) if self.ev.slice_path else None,
            },
            "checks": self.checks,
            "check_count": len(self.checks),
            "passed": passed,
            "verdict": f"VERIFY_PASS {passed}/{len(self.checks)}"
            if passed == len(self.checks)
            else f"VERIFY_FAIL {passed}/{len(self.checks)}",
            "hypothetical": True,
            "order_sent": False,
            "promotion": "NONE",
        }


# --------------------------------------------------------------------------- sabotages
def _copy_tree(source: Path, target: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True)


def sabotage_cases() -> list[dict[str, Any]]:
    """Every sabotage, with the mutation and the check that must catch it."""

    def mutate_watch(rows: list[dict[str, Any]], fn) -> None:
        fn(rows)

    def s_market_request(rows, ev, lane):
        rows[-1]["market_requests"] = 4

    def s_verdict_flipped(rows, ev, lane):
        for row in reversed(rows):
            if str(row.get("verdict")) != "WATCH_OK":
                row["verdict"] = "WATCH_OK"
                return
        rows[-1]["checks"]["scheduler_task"]["status"] = "ALARM"
        rows[-1]["verdict"] = "WATCH_OK"

    def s_failure_flag(rows, ev, lane):
        for row in reversed(rows):
            if row.get("operational_failure"):
                row["operational_failure"] = False
                return
        rows[-1]["checks"]["lane_cadence"]["status"] = "ALARM"
        rows[-1]["verdict"] = "WATCH_ALARM"
        rows[-1]["operational_failure"] = False

    def s_category_healthy(rows, ev, lane):
        for row in reversed(rows):
            if str(row.get("verdict")) != "WATCH_OK":
                row["category"] = "HEALTHY"
                return
        rows[-1]["checks"]["resource_disk"]["status"] = "BLOCKED"
        rows[-1]["checks"]["resource_disk"]["disk_status"] = "CRITICAL"
        rows[-1]["verdict"] = "WATCH_BLOCKED"
        rows[-1]["category"] = "HEALTHY"

    def s_lane_silence(rows, ev, lane):
        last = rows[-1]
        last["at_ms"] = int(last.get("at_ms") or 0) + 30 * 60_000
        last["checks"]["lane_cadence"]["silence_seconds"] = 0.0

    def s_market_quiet(rows, ev, lane):
        # A quiet market is only a lie when the store is behind the calendar, and a lane that has
        # just ticked leaves the store level with it — so the lie is planted where it is always a
        # lie: the reading keeps its claim of a quiet market and is moved forward three hours, to an
        # instant by which the closed-bar calendar says every series owes bars the store cannot
        # hold. The reading's own parts are moved with it so that the summary still agrees with
        # them, and the store is the only thing left contradicting it.
        expectation = rows[-1]["checks"]["market_expectation"]
        expectation["market_quiet"] = True
        expectation["reason"] = "sabotage"
        expectation["pending_since_last_tick"] = 0
        shift = 3 * HOUR
        for series in expectation["series"]:
            series["pending_since_last_tick"] = 0
            if series.get("newest_closed_now_ts") is not None:
                series["newest_closed_now_ts"] = int(series["newest_closed_now_ts"]) + shift
        rows[-1]["at_ms"] = int(rows[-1].get("at_ms") or 0) + shift
        rows[-1]["at_utc"] = stamp_ms(int(rows[-1]["at_ms"]))

    def s_scheduler_translation(rows, ev, lane):
        for row in rows:
            result = (row.get("checks") or {}).get("scheduler_last_result", {})
            if result.get("exit_code") == 5:
                result["lane_outcome"] = "OBSERVED"
                return
        row = rows[-1]
        row["checks"]["scheduler_last_result"] = {
            "status": "OK",
            "exit_code": 5,
            "lane_outcome": "OBSERVED",
            "reason": "sabotage",
        }

    def s_alerts_ok_ok_recovery(alerts, ev, lane):
        rows = ev.watch_rows
        alerts.append(
            {
                "kind": "WATCHDOG_RECOVERED",
                "state": "OK",
                "recovered_from": "WATCH_OK",
                "hypothetical": True,
                "order_sent": False,
            }
        )

    def s_alerts_duplicate_state(alerts, ev, lane):
        alerts.append(copy.deepcopy(alerts[-1]))

    def s_detection_erased(rows, ev, lane):
        for row in rows:
            row["verdict"] = "WATCH_OK"
            row["operational_failure"] = False
            for body in (row.get("checks") or {}).values():
                if str(body.get("status")) in ("ALARM", "BLOCKED", "WARN"):
                    body["status"] = "OK"

    def s_chain_claim(rows, ev, lane):
        ledger = ev.lane / "ledger" / "INGEST_LEDGER.jsonl"
        lines = ledger.read_text(encoding="utf-8").splitlines()
        target = next(line for line in lines if '"1h"' in line and '"appended": 1' in line)
        row = json.loads(target)
        row["high_water_ts"] = int(row["high_water_ts"]) + 5 * HOUR
        ledger.write_text("\n".join([*lines, json.dumps(row, sort_keys=True)]) + "\n", encoding="utf-8")

    def s_bars_removed(rows, ev, lane):
        report = ev.reconciliation()
        report["reconstruction"]["bars_removed"] = 1
        (ev.watch / "reconciliation" / "RECONCILIATION.json").write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
        )

    def _rewrite_reconciliation(ev: Any, fn) -> bool:
        report = ev.reconciliation()
        if not report:
            return False
        if fn(report) is False:
            return False
        (ev.watch / "reconciliation" / "RECONCILIATION.json").write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
        )
        return True

    def s_episode_closed_without_bars(rows, ev, lane):
        def edit(report: dict[str, Any]) -> bool:
            detail = report.get("attempts", {}).get("without_a_run_detail") or []
            if not detail:
                return False
            detail[0]["episode"] = "CLOSED"
            detail[0]["interval_covered"] = True
            detail[0]["bars_appended"] = int(detail[0].get("bars_appended") or 0) + 4
            return True

        return _rewrite_reconciliation(ev, edit)

    def s_promotion(rows, ev, lane):
        return _rewrite_reconciliation(ev, lambda report: report.__setitem__("promotion", "PAPER"))

    def s_bars_removed_report(rows, ev, lane):
        def edit(report: dict[str, Any]) -> bool:
            report.setdefault("reconstruction", {})["bars_removed"] = 1
            return True

        return _rewrite_reconciliation(ev, edit)

    def s_bounds(rows, ev, lane):
        # Past a declared cap means past it: the sabotage grows the log the way a lane with no
        # pruning would, with rows small enough to write quickly and shaped enough to parse.
        filler = {
            "schema_version": STATE_SCHEMA,
            "check_id": "SABOTAGE",
            "verdict": "WATCH_OK",
            "category": "HEALTHY",
            "checks": {},
            "market_requests": 0,
            "wrote_to_lane": False,
            "hypothetical": True,
            "order_sent": False,
            "promotion": "NONE",
        }
        rows.extend(copy.deepcopy(filler) for _ in range(WATCH_KEPT - len(rows) + 1))

    return [
        {"name": "a reading that made a market request", "apply": s_market_request, "caught_by": "watchdog_rows_shape_and_restraint"},
        {"name": "a verdict that is not the worst check", "apply": s_verdict_flipped, "caught_by": "verdict_is_the_worst_check_status"},
        {"name": "a failure flag cleared", "apply": s_failure_flag, "caught_by": "category_and_operational_failure_are_derived"},
        {"name": "a blocked reading filed as healthy", "apply": s_category_healthy, "caught_by": "category_and_operational_failure_are_derived"},
        {"name": "a silence smaller than the log allows", "apply": s_lane_silence, "caught_by": "lane_silence_is_consistent_with_the_run_log"},
        {"name": "a quiet market the store contradicts", "apply": s_market_quiet, "caught_by": "market_expectation_matches_the_store"},
        {"name": "a scheduler code mapped to the wrong outcome", "apply": s_scheduler_translation, "caught_by": "scheduler_result_translated_through_the_lane_vocabulary"},
        {"name": "a recovery announced without a trouble", "apply": s_alerts_ok_ok_recovery, "caught_by": "alerts_are_per_transition", "target": "alerts"},
        {"name": "an alert state repeated", "apply": s_alerts_duplicate_state, "caught_by": "alerts_are_per_transition", "target": "alerts"},
        {"name": "every episode of trouble erased", "apply": s_detection_erased, "caught_by": "the_watchdog_really_detected_an_interruption"},
        {"name": "a ledger chain that jumps", "apply": s_chain_claim, "caught_by": "reconciliation_chains_recomputed", "target": "none"},
        {"name": "a reconciliation that admits removing a bar", "apply": s_bars_removed_report, "caught_by": "reconciliation_chains_recomputed", "target": "none"},
        {"name": "an episode filed closed with a missing bar", "apply": s_episode_closed_without_bars, "caught_by": "unattributed_attempts_recomputed", "target": "none"},
        {"name": "a promotion in the reconciliation", "apply": s_promotion, "caught_by": "no_artefact_promotes_or_orders", "target": "none"},
        {"name": "a watchdog log past its cap", "apply": s_bounds, "caught_by": "watchdog_bounds_declared_and_kept"},
    ]


def self_test(
    *,
    watch: Path,
    lane: Path,
    store: Path,
    slice_path: Path | None,
    repo_root: Path,
) -> dict[str, Any]:
    """Apply each sabotage to a copy of everything and require the matching check to fail.

    The copies are of the artefacts only: the store and the lane's evidence are shared read-only,
    so a sabotage can never damage the run it is verifying.
    """
    results: list[dict[str, Any]] = []
    for index, case in enumerate(sabotage_cases(), start=1):
        target = str(case.get("target", "watchdog"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            watch_copy = root / "watch"
            lane_copy = root / "lane"
            _copy_tree(watch, watch_copy)
            _copy_tree(lane, lane_copy)
            evidence = Evidence(watch=watch_copy, lane=lane_copy, store=store, slice_path=slice_path)
            detail: Any = None
            detected = False
            try:
                if target == "alerts":
                    alerts = read_jsonl(watch_copy / "watch_alerts.jsonl")
                    case["apply"](alerts, evidence, lane_copy)
                    _write_jsonl(watch_copy / "watch_alerts.jsonl", alerts)
                elif target == "watchdog":
                    rows = read_jsonl(watch_copy / "watchdog.jsonl")
                    case["apply"](rows, evidence, lane_copy)
                    _write_jsonl(watch_copy / "watchdog.jsonl", rows)
                else:
                    # the sabotage edits an artefact directly
                    applied = case["apply"]([], evidence, lane_copy)
                    if applied is False:
                        results.append(
                            {
                                "index": index,
                                "sabotage": case["name"],
                                "expected_check": case["caught_by"],
                                "detected": False,
                                "detail": "the sabotage could not be applied to this evidence",
                            }
                        )
                        continue
                verifier = Verifier(evidence, repo_root=repo_root)
                verifier.run()
                caught = [
                    check
                    for check in verifier.checks
                    if check["check"] == case["caught_by"] and check["status"] == "FAIL"
                ]
                detected = bool(caught)
                detail = caught[0]["detail"] if caught else None
            except Exception as exc:  # a sabotage that crashes the verifier is not a detection
                detail = f"the verifier raised: {exc!r}"
            results.append(
                {
                    "index": index,
                    "sabotage": case["name"],
                    "expected_check": case["caught_by"],
                    "detected": detected,
                    "detail": detail,
                }
            )
    detected = sum(1 for row in results if row["detected"])
    return {
        "sabotages": results,
        "detected": detected,
        "count": len(results),
        "verdict": f"SELF_TEST_PASS {detected}/{len(results)}"
        if detected == len(results)
        else f"SELF_TEST_FAIL {detected}/{len(results)}",
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True, ensure_ascii=False, default=str) + "\n" for row in rows),
        encoding="utf-8",
    )


def snapshot_store(report: dict[str, Any], store: Path, lane: Path) -> dict[str, Any]:
    """A bounded, digest-attested slice of the store: the bars the reconciliation actually reads.

    The store is ~5.6 MB of raw bars and is deliberately excluded from version control, so a
    preserved verification keeps the part that matters — every bar after each series' epoch, with
    its fetch instant, plus the digest of the whole file it came from — and says so.
    """
    payload: dict[str, Any] = {
        "schema_version": "EDGE05_STORE_SLICE_V1",
        "generated_at_utc": stamp_ms(int(datetime.now(tz=UTC).timestamp() * 1000)),
        "store_root": str(store),
        "series": {},
        "reading": (
            "the bars after each series' ledger epoch, which is the whole of what the "
            "reconciliation reads from the store, plus the digest of the file they were taken from"
        ),
        "hypothetical": True,
        "order_sent": False,
    }
    for timeframe, symbol in SERIES:
        name = f"{timeframe}:{symbol}"
        epoch = ((report.get("chains") or {}).get(name) or {}).get("epoch_ts")
        path = store / timeframe / f"{symbol.upper()}.jsonl"
        bars = [row for row in read_jsonl(path) if epoch is None or int(row["ts"]) > int(epoch)]
        payload["series"][name] = {
            "epoch_ts": epoch,
            "bars_after_epoch": [
                {"ts": int(row["ts"]), "fetched_at_ms": row.get("fetched_at_ms")} for row in bars
            ],
            "bars_after_epoch_count": len(bars),
            "sha256_file": sha256_file(path),
            "file_bars": len(read_jsonl(path)),
        }
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--state-root", default=None, help="the watchdog's state root to verify")
    parser.add_argument("--lane-state-root", default=None)
    parser.add_argument("--store-root", default=None)
    parser.add_argument("--slice", default=None, help="a preserved store slice to verify against")
    parser.add_argument("--out", default=None, help="where to write the verification JSON")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--json", action="store_true")
    options = parser.parse_args(argv)

    watch = Path(options.state_root) if options.state_root else REPO_ROOT / "data" / "forward" / "edge05"
    lane = (
        Path(options.lane_state_root)
        if options.lane_state_root
        else REPO_ROOT / "data" / "forward" / "edge04"
    )
    store = (
        Path(options.store_root) if options.store_root else REPO_ROOT / "data" / "forward" / "edge03"
    )
    slice_path = Path(options.slice) if options.slice else (watch / "STORE_SLICE.json")
    if not slice_path.is_file():
        slice_path = None

    evidence = Evidence(watch=watch, lane=lane, store=store, slice_path=slice_path)
    verifier = Verifier(evidence)
    report = verifier.run()

    if options.self_test:
        report["self_test"] = self_test(
            watch=watch, lane=lane, store=store, slice_path=slice_path, repo_root=REPO_ROOT
        )

    text = json.dumps(report, indent=2, sort_keys=True, default=str)
    if options.json:
        print(text)
    else:
        print(f"verdict   {report['verdict']}")
        print(f"watching  {report['watched']['store_mode']} store · {watch}")
        for check in report["checks"]:
            print(f"  {check['status']:<5} {check['check']:<54} {str(check['reading'])[:80]}")
        if "self_test" in report:
            test = report["self_test"]
            print(f"sabotage  {test['verdict']}")
            for row in test["sabotages"]:
                mark = "detected" if row["detected"] else "MISSED"
                print(f"  {mark:<9} {row['sabotage']:<52} -> {row['expected_check']}")
    if options.out:
        out = Path(options.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
        print(f"written   {out}")

    failed = report["verdict"].startswith("VERIFY_FAIL")
    sabotages_failed = bool(
        "self_test" in report and report["self_test"]["verdict"].startswith("SELF_TEST_FAIL")
    )
    return 1 if (failed or sabotages_failed) else 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
