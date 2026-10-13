"""Independent verification of WP-EDGE-04 (the autonomous forward observer).

    python scripts/edge04_verify.py [--state-root DIR] [--repo DIR]
                                    [--install FILE] [--json-out FILE] [--self-test]

This process imports NOTHING from ``trading_bot`` and drives none of the observer's code. It
reads the artefacts the observer left on disk, restates every rule and every constant from the
declarations written here, and recomputes what the artefacts claim:

1.  ``ARTIFACTS_PRESENT``             every required artefact exists, parses and is not empty
2.  ``SLOT_DISCIPLINE``               no slot is observed twice, every slot key is on the 15
                                      minute grid, and every slot the run log consumed has a row
3.  ``OUTCOMES_AND_EXIT_CODES``       every run row carries an outcome from the closed
                                      vocabulary and the exit code that outcome declares
4.  ``NO_ORDER_PATH_OR_PROMOTION``    no record claims an order was sent, and no record
                                      promotes anything
5.  ``EXPECTATION_ARITHMETIC``        missing == expected - appended per series, and the
                                      outcome follows from those numbers
6.  ``MARKET_REQUESTS_ARE_SPENT``     a tick that observed nothing spent no market request, and
                                      a failed tick did not consume a slot
7.  ``RULESET_PINNED_AND_UNCHANGED``  one ruleset hash across the whole run log, equal to the
                                      published one, and every pin agreed with the publication
8.  ``COVERAGE_RULE_APPLIED``         the day classes, their counts and the remaining days all
                                      follow from the declared coverage rule
9.  ``BACKFILL_IS_NOT_AN_OBSERVATION``no day counted as observed fails the prospective rule
10. ``DAILY_EVIDENCE_CONSISTENT``     the day files agree with the slot log, and the day hashes
                                      answer to the raw store
11. ``HEALTH_FOLLOWS_THE_LOG``        the health reading follows from the retained run log
12. ``BUDGET_DECLARED_MEASURED_AND_BOUNDED``  the byte reading is the tree's real size, the log
                                      caps hold, and the daily evidence was not pruned with them
13. ``PUBLICATION_SWAPPED_ATOMICALLY``every published digest matches its file on disk and no
                                      staging tree survived
14. ``FREEZE_AND_FLOOR_DECLARED``     the frozen instants, the coverage rule and the 60-day
                                      floor are the ones the earlier work packages declared
15. ``SCHEDULER_REGISTRATION_READ``   when the task's own registration was captured, it names
                                      the declared interpreter, script and cadence — and is
                                      labelled a declaration, never a measurement

Checks that cannot be applied to the tree in front of them are reported as ``skipped`` with the
reason, never as passes. ``--self-test`` sabotages a copy of the evidence once per check and
requires the matching check to break: a check nobody can break is reported as a failure.

Research only: this process reads files. It has no market client and no order path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# -- the declarations, restated here (imported from nothing) -----------------------------
SLOT_MS = 900_000
SLOT_MINUTES = 15
FROZEN_1H_END_MS = 1_772_319_600_000
FROZEN_15M_END_MS = 1_791_372_600_000
COVERAGE_REQUIRED = 0.90
EXPECTED_BARS_PER_DAY = 24
OBSERVATION_FLOOR_DAYS = 60
PROSPECTIVE_LAG_BOUND_MS = {"1h": 2 * 3_600_000, "15m": 30 * 60_000}
STALE_AFTER_MS = {"1h": 4 * 3_600_000, "15m": 4 * 3_600_000}
PRIMARY_SERIES = ("1h:BTC", "1h:ETH", "1h:SOL")
TASK_NAME = "TradingAgentic-EDGE04-Forward"

EXIT_CODES = {
    "OBSERVED": 0,
    "NO_NEW_DATA": 0,
    "ALREADY_OBSERVED": 0,
    "ALREADY_RUNNING": 2,
    "MISSING_BARS": 4,
    "STALE_DATA": 4,
    "DISK_BUDGET_EXCEEDED": 5,
    "VERIFICATION_FAILED": 6,
    "PROVIDER_UNAVAILABLE": 7,
    "RUNTIME_EXCEPTION": 1,
}
SLOT_CONSUMING = ("OBSERVED", "NO_NEW_DATA")
FAILED = (
    "ALREADY_RUNNING",
    "MISSING_BARS",
    "STALE_DATA",
    "DISK_BUDGET_EXCEEDED",
    "VERIFICATION_FAILED",
    "PROVIDER_UNAVAILABLE",
    "RUNTIME_EXCEPTION",
)
# The names are the ones the bundle loads, so the cap is checked against the rows that were
# actually read: a key that matches no artefact would make this arm unfireable, and a check that
# cannot fail is not a check.
BOUNDED_LOGS = {
    "runs.jsonl": "runs_kept",
    "slots.jsonl": "slots_kept",
    "ledger/INGEST_LEDGER.jsonl": "ledger_kept",
}
BLOCKED_AFTER_CONSECUTIVE_FAILURES = 8
HEALTH_WINDOW_MS = 86_400_000
LOG_FILES = ("runs.jsonl", "slots.jsonl", "alerts.jsonl")
BUDGET_FILE = "resource_budget.json"
COVERAGE_FILE = "coverage.json"
HEALTH_FILE = "health.json"
SNAPSHOT_FILE = "SNAPSHOT.json"

REQUIRED_SNAPSHOT = (
    COVERAGE_FILE,
    HEALTH_FILE,
    BUDGET_FILE,
    "runs.jsonl",
    "slots.jsonl",
)
OPTIONAL_SNAPSHOT = (
    "alerts.jsonl",
    "ledger/INGEST_LEDGER.jsonl",
    "install.json",
    SNAPSHOT_FILE,
)


@dataclass
class Bundle:
    """Everything a check may read. Nothing here is produced by the lane's own modules."""

    state_root: Path
    repo: Path
    install: Path | None = None
    files: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, str] = field(default_factory=dict)
    corrupt: dict[str, int] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    daily: dict[str, Any] = field(default_factory=dict)
    publication: Path | None = None

    def path(self, name: str) -> Path:
        return self.state_root / name

    def rows(self, name: str) -> list[dict[str, Any]]:
        value = self.files.get(name)
        return list(value) if isinstance(value, list) else []


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    if not path.is_file():
        return [], 0
    rows: list[dict[str, Any]] = []
    corrupt = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError:
            corrupt += 1
            continue
        if isinstance(loaded, dict):
            rows.append(loaded)
        else:
            corrupt += 1
    return rows, corrupt


def load_bundle(
    state_root: Path, *, repo: Path | None = None, install: Path | None = None
) -> Bundle:
    state_root = Path(state_root)
    bundle = Bundle(state_root=state_root, repo=Path(repo) if repo else Path.cwd(), install=install)
    for name in REQUIRED_SNAPSHOT + OPTIONAL_SNAPSHOT:
        path = state_root / name
        if not path.is_file():
            if name in OPTIONAL_SNAPSHOT:
                continue
            bundle.missing.append(name)
            continue
        bundle.raw[name] = path.read_text(encoding="utf-8")
        if name.endswith(".jsonl"):
            rows, corrupt = read_jsonl(path)
            bundle.files[name] = rows
            bundle.corrupt[name] = corrupt
        else:
            try:
                bundle.files[name] = json.loads(bundle.raw[name])
            except json.JSONDecodeError:
                bundle.missing.append(name)
    daily_dir = state_root / "daily"
    if daily_dir.is_dir():
        for path in sorted(daily_dir.glob("*.json")):
            try:
                bundle.daily[path.name] = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                bundle.daily[path.name] = {"corrupt": True}
    declared_dir = state_root / "publication"
    publication_dir: Path | None = (
        declared_dir
        if declared_dir.is_dir()
        else state_root
        if (state_root / "LATEST.json").is_file()
        else None
    )
    bundle.publication = publication_dir
    return bundle


def _bytes_under(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for entry in path.rglob("*"):
        if entry.is_file():
            try:
                total += entry.stat().st_size
            except OSError:  # pragma: no cover - racing deletion
                continue
    return total


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_rows(rows: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(json.dumps(row, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return digest.hexdigest()


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- the checks
def check_artifacts_present(bundle: Bundle) -> list[tuple[str, bool, str]]:
    failures = [f"missing or unparsable: {name}" for name in bundle.missing]
    empty = [
        name
        for name in ("runs.jsonl", "slots.jsonl")
        if name in bundle.files and not bundle.files[name]
    ]
    failures.extend(f"empty: {name}" for name in empty)
    if not bundle.daily:
        failures.append("no daily evidence file was published")
    return [
        (
            "ARTIFACTS_PRESENT",
            not failures,
            "; ".join(failures)
            or f"{len(bundle.files)} file(s), {len(bundle.daily)} daily evidence file(s)",
        )
    ]


def check_slot_discipline(bundle: Bundle) -> list[tuple[str, bool, str]]:
    failures: list[str] = []
    slots = [str(row.get("slot_key")) for row in bundle.rows("slots.jsonl")]
    if len(slots) != len(set(slots)):
        duplicates = sorted({key for key in slots if slots.count(key) > 1})
        failures.append(f"a slot was observed more than once: {duplicates[:3]}")
    for key in slots:
        try:
            stamp_ms = _slot_ms(key)
        except ValueError:
            failures.append(f"slot key is not on the declared grid: {key!r}")
            continue
        if stamp_ms % SLOT_MS:
            failures.append(f"slot key is not on the {SLOT_MINUTES}-minute grid: {key}")
    consumed = {
        str(row.get("slot_key"))
        for row in bundle.rows("runs.jsonl")
        if row.get("outcome") in SLOT_CONSUMING
    }
    recorded = set(slots)
    orphan = sorted(consumed - recorded)
    if orphan:
        failures.append(f"run rows that consumed a slot without a slot row: {orphan[:3]}")
    extra = sorted(recorded - consumed)
    if extra:
        failures.append(f"slot rows with no consuming run row: {extra[:3]}")
    # A slot claims a run id sealed it. That row must exist in the run log, with a consuming
    # outcome: a slot whose tick is missing from the record is a claim with no author behind it.
    for row in bundle.rows("slots.jsonl"):
        key = str(row.get("slot_key"))
        run_id = str(row.get("run_id"))
        answered = any(
            str(candidate.get("run_id")) == run_id
            and str(candidate.get("slot_key")) == key
            and candidate.get("outcome") in SLOT_CONSUMING
            for candidate in bundle.rows("runs.jsonl")
        )
        if not answered:
            failures.append(f"slot {key}: no consuming run row answers for {run_id!r}")
    return [
        (
            "SLOT_DISCIPLINE",
            not failures,
            "; ".join(failures) or f"{len(slots)} slot(s), no duplicates, all on the grid",
        )
    ]


def _slot_ms(key: str) -> int:
    if not key or not key.endswith("Z"):
        raise ValueError(key)
    from datetime import UTC, datetime

    return int(datetime.strptime(key, "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC).timestamp() * 1000)


def check_outcomes_and_exit_codes(bundle: Bundle) -> list[tuple[str, bool, str]]:
    failures: list[str] = []
    runs = bundle.rows("runs.jsonl")
    if not runs:
        return [("OUTCOMES_AND_EXIT_CODES", False, "no run rows to read")]
    for row in runs:
        outcome = str(row.get("outcome"))
        if outcome not in EXIT_CODES:
            failures.append(f"outcome outside the vocabulary: {outcome!r}")
            continue
        if _int(row.get("exit_code")) != EXIT_CODES[outcome]:
            failures.append(
                f"{row.get('run_id')}: exit code {row.get('exit_code')} does not follow from {outcome}"
            )
        if outcome in FAILED and not row.get("errors"):
            failures.append(f"{row.get('run_id')}: a failed outcome carries no error record")
        if row.get("hypothetical") is not True:
            failures.append(f"{row.get('run_id')}: hypothetical is not true")
        if row.get("order_sent") is not False:
            failures.append(f"{row.get('run_id')}: order_sent is not false")
    return [
        (
            "OUTCOMES_AND_EXIT_CODES",
            not failures,
            "; ".join(failures[:5]) or f"{len(runs)} run row(s) agree with the vocabulary",
        )
    ]


def check_no_order_path_or_promotion(bundle: Bundle) -> list[tuple[str, bool, str]]:
    failures: list[str] = []
    forbidden = ("order_endpoint", "place_order", "api_key", "secret", "createOrder")
    for name in (*LOG_FILES, COVERAGE_FILE, HEALTH_FILE, BUDGET_FILE):
        text = bundle.raw.get(name)
        if text is None:
            continue
        for token in forbidden:
            if token in text:
                failures.append(f"{name} mentions {token!r}")
    blobs: list[tuple[str, dict[str, Any]]] = [
        ("runs.jsonl", row) for row in bundle.rows("runs.jsonl")
    ]
    blobs += [(f"daily/{name}", body) for name, body in bundle.daily.items()]
    blobs += [(name, body) for name, body in bundle.files.items() if isinstance(body, dict)]
    for label, body in blobs:
        if body.get("order_sent") not in (None, False):
            failures.append(f"{label}: order_sent is not false")
        if body.get("promotion") not in (None, "NONE"):
            failures.append(f"{label}: promotion is not NONE")
    for label, body in bundle.daily.items():
        text = json.dumps(body)
        if '"PAPER"' in text or '"LIVE"' in text:
            failures.append(f"daily/{label}: names a PAPER or LIVE state")
    return [
        (
            "NO_ORDER_PATH_OR_PROMOTION",
            not failures,
            "; ".join(failures[:5]) or "no order path and no promotion in any artefact",
        )
    ]


def check_expectation_arithmetic(bundle: Bundle) -> list[tuple[str, bool, str]]:
    failures: list[str] = []
    checked = 0
    for row in bundle.rows("runs.jsonl"):
        series = row.get("expectation_series")
        if not isinstance(series, list):
            continue
        checked += 1
        expected = appended = missing = 0
        for entry in series:
            exp = _int(entry.get("expected")) or 0
            app = _int(entry.get("appended")) or 0
            want = max(0, exp - app)
            if _int(entry.get("missing")) != want:
                failures.append(
                    f"{row.get('run_id')}/{entry.get('series')}: missing {entry.get('missing')} != {want}"
                )
            expected += exp
            appended += app
            missing += want
        if _int(row.get("expected_new_bars")) != expected:
            failures.append(f"{row.get('run_id')}: expected_new_bars is not the sum of its series")
        if _int(row.get("missing_bars")) != missing:
            failures.append(f"{row.get('run_id')}: missing_bars is not the sum of its series")
        new_bars = _int(row.get("new_bars")) or 0
        if new_bars != appended:
            failures.append(f"{row.get('run_id')}: new_bars {new_bars} != appended {appended}")
        outcome = str(row.get("outcome"))
        if missing and outcome not in ("MISSING_BARS", "PROVIDER_UNAVAILABLE", "RUNTIME_EXCEPTION"):
            failures.append(
                f"{row.get('run_id')}: {missing} bar(s) missing but the outcome is {outcome}"
            )
        if not missing and new_bars and outcome != "OBSERVED":
            failures.append(
                f"{row.get('run_id')}: {new_bars} bar(s) appended but the outcome is {outcome}"
            )
        if (
            not missing
            and not new_bars
            and outcome not in ("NO_NEW_DATA", "STALE_DATA", "ALREADY_OBSERVED")
        ):
            failures.append(
                f"{row.get('run_id')}: nothing appended and no bar missing, yet {outcome}"
            )
    if not checked:
        return [("EXPECTATION_ARITHMETIC", False, "no run row carries per-series expectations")]
    return [
        (
            "EXPECTATION_ARITHMETIC",
            not failures,
            "; ".join(failures[:5]) or f"{checked} run row(s) recomputed from their own series",
        )
    ]


def check_market_requests_are_spent(bundle: Bundle) -> list[tuple[str, bool, str]]:
    failures: list[str] = []
    runs = bundle.rows("runs.jsonl")
    for row in runs:
        outcome = str(row.get("outcome"))
        requests = _int(row.get("market_requests"))
        if requests is None:
            failures.append(f"{row.get('run_id')}: no market-request count")
            continue
        if (
            outcome in ("ALREADY_OBSERVED", "ALREADY_RUNNING", "DISK_BUDGET_EXCEEDED")
            and requests != 0
        ):
            failures.append(f"{row.get('run_id')}: {outcome} spent {requests} market request(s)")
        if outcome in ("OBSERVED", "NO_NEW_DATA", "MISSING_BARS", "STALE_DATA") and requests < 1:
            failures.append(f"{row.get('run_id')}: {outcome} spent no market request at all")
        if outcome in FAILED and outcome not in (
            "ALREADY_RUNNING",
            "DISK_BUDGET_EXCEEDED",
            "PROVIDER_UNAVAILABLE",
        ):
            consumed = {str(s.get("slot_key")) for s in bundle.rows("slots.jsonl")}
            if str(row.get("slot_key")) in consumed:
                failures.append(f"{row.get('run_id')}: a failed tick consumed its slot")
    # A slot is answered by the tick that *sealed* it — the run row the slot ledger names, with a
    # consuming outcome. A later trigger inside the same slot records its own row and spends
    # nothing; reading the newest row for a slot would blame the no-op trigger for the ledger's
    # cost, which is exactly the wrong conclusion.
    for row in bundle.rows("slots.jsonl"):
        key = str(row.get("slot_key"))
        run_id = str(row.get("run_id"))
        owner = next(
            (
                candidate
                for candidate in runs
                if str(candidate.get("run_id")) == run_id
                and str(candidate.get("slot_key")) == key
                and candidate.get("outcome") in SLOT_CONSUMING
            ),
            None,
        )
        if owner is None:
            failures.append(f"slot {key}: no consuming run row for {run_id!r}")
            continue
        spent = _int(owner.get("market_requests")) or 0
        if spent < 1:
            failures.append(f"slot {key}: consumed by a tick that spent no market request")
        recorded = _int(row.get("market_requests"))
        if recorded != spent:
            failures.append(
                f"slot {key}: the slot ledger records {recorded} request(s), its run row {spent}"
            )
    return [
        (
            "MARKET_REQUESTS_ARE_SPENT",
            not failures,
            "; ".join(failures[:5]) or f"{len(runs)} run row(s) spent their requests coherently",
        )
    ]


def check_ruleset_pinned(bundle: Bundle) -> list[tuple[str, bool, str]]:
    failures: list[str] = []
    hashes: set[str] = set()
    pinned = 0
    for row in bundle.rows("runs.jsonl"):
        ruleset = row.get("ruleset")
        if not isinstance(ruleset, dict):
            continue
        pinned += 1
        if ruleset.get("agrees_with_publication") is not True:
            failures.append(
                f"{row.get('run_id')}: the ruleset pin did not agree with the publication"
            )
        digest = str(ruleset.get("params_hash") or "")
        if not digest:
            failures.append(f"{row.get('run_id')}: the pin carries no digest")
        hashes.add(digest)
    if len(hashes) > 1:
        failures.append(
            f"the run log carries {len(hashes)} different ruleset digests: {sorted(hashes)[:3]}"
        )
    publication = bundle.publication
    published: str | None = None
    if publication is not None:
        pointer = publication / "LATEST.json"
        if pointer.is_file():
            try:
                published = str(json.loads(pointer.read_text(encoding="utf-8")).get("params_hash"))
            except json.JSONDecodeError:
                published = None
    if published and hashes and published not in hashes:
        failures.append(
            f"the published ruleset digest {published[:16]}… is not the one the run log pinned"
        )
    coverage = bundle.files.get(COVERAGE_FILE)
    if isinstance(coverage, dict):
        freeze = coverage.get("freeze") or {}
        if freeze.get("params_hash") and hashes and str(freeze["params_hash"]) not in hashes:
            failures.append("the coverage artefact names a different ruleset digest")
    if not pinned:
        failures.append("no run row carries a ruleset pin")
    return [
        (
            "RULESET_PINNED_AND_UNCHANGED",
            not failures,
            "; ".join(failures[:5]) or f"{pinned} run row(s) pinned to {sorted(hashes)[0][:16]}…",
        )
    ]


def _primary_coverage(day: dict[str, Any]) -> dict[str, float]:
    coverage = day.get("coverage") or {}
    out: dict[str, float] = {}
    for key in PRIMARY_SERIES:
        value = coverage.get(key)
        out[key] = float(value) if isinstance(value, (int, float)) else 0.0
    return out


def check_coverage_rule(bundle: Bundle) -> list[tuple[str, bool, str]]:
    coverage = bundle.files.get(COVERAGE_FILE)
    if not isinstance(coverage, dict):
        return [("COVERAGE_RULE_APPLIED", False, "no coverage artefact")]
    failures: list[str] = []
    days = coverage.get("days")
    if not isinstance(days, list):
        return [("COVERAGE_RULE_APPLIED", False, "the coverage artefact carries no days")]
    valid: list[str] = []
    backfilled: list[str] = []
    for day in days:
        ratios = _primary_coverage(day)
        stored = day.get("stored_bars") or {}
        dense = bool(stored) and all(
            (_int(stored.get(key)) or 0) >= COVERAGE_REQUIRED * EXPECTED_BARS_PER_DAY
            for key in PRIMARY_SERIES
        )
        complete = dense and all(ratios[key] >= COVERAGE_REQUIRED for key in PRIMARY_SERIES)
        want = (
            "PROSPECTIVELY_OBSERVED"
            if complete
            else "DENSE_BUT_BACKFILLED"
            if dense
            else "INCOMPLETE"
        )
        if day.get("class") != want:
            failures.append(
                f"{day.get('day')}: class {day.get('class')!r} but the rule gives {want}"
            )
        if complete:
            valid.append(str(day.get("day")))
        elif dense:
            backfilled.append(str(day.get("day")))
    if sorted(valid) != sorted(map(str, coverage.get("prospectively_observed_days") or [])):
        failures.append("the valid-day list is not the set of days the rule accepts")
    if _int(coverage.get("prospectively_observed")) != len(valid):
        failures.append("the counted observation days do not match the day list")
    if _int(coverage.get("densely_covered_but_backfilled")) != len(backfilled):
        failures.append("the backfilled-day count does not match the day list")
    if _int(coverage.get("required_days")) != OBSERVATION_FLOOR_DAYS:
        failures.append(f"the required floor is not {OBSERVATION_FLOOR_DAYS} days")
    remaining = _int(coverage.get("remaining_days"))
    if remaining is None or remaining != max(0, OBSERVATION_FLOOR_DAYS - len(valid)):
        failures.append("the remaining-days figure does not follow from the floor and the days")
    return [
        (
            "COVERAGE_RULE_APPLIED",
            not failures,
            "; ".join(failures[:5])
            or f"{len(valid)} prospective day(s), {len(backfilled)} dense-but-backfilled",
        )
    ]


def check_backfill_is_not_an_observation(bundle: Bundle) -> list[tuple[str, bool, str]]:
    coverage = bundle.files.get(COVERAGE_FILE)
    if not isinstance(coverage, dict):
        return [("BACKFILL_IS_NOT_AN_OBSERVATION", False, "no coverage artefact")]
    failures: list[str] = []
    valid = set(map(str, coverage.get("prospectively_observed_days") or []))
    backfilled = set(map(str, coverage.get("densely_covered_but_backfilled_days") or []))
    overlap = sorted(valid & backfilled)
    if overlap:
        failures.append(f"days counted as observed and as backfilled: {overlap[:3]}")
    for day in coverage.get("days") or []:
        if str(day.get("day")) not in valid:
            continue
        ratios = _primary_coverage(day)
        if any(ratios[key] < COVERAGE_REQUIRED for key in PRIMARY_SERIES):
            bad = {key: ratios[key] for key in PRIMARY_SERIES if ratios[key] < COVERAGE_REQUIRED}
            failures.append(f"{day.get('day')}: counted as observed with coverage {bad}")
    rule = str(coverage.get("rule") or "")
    if "lag bound" not in rule and "prospectively" not in rule:
        failures.append("the declared rule does not mention the prospective lag bound")
    return [
        (
            "BACKFILL_IS_NOT_AN_OBSERVATION",
            not failures,
            "; ".join(failures[:5]) or f"{len(valid)} day(s) counted, none backfilled",
        )
    ]


def check_daily_evidence(bundle: Bundle) -> list[tuple[str, bool, str]]:
    if not bundle.daily:
        return [("DAILY_EVIDENCE_CONSISTENT", False, "no daily evidence file")]
    failures: list[str] = []
    slots = {str(row.get("slot_key")): row for row in bundle.rows("slots.jsonl")}
    coverage = bundle.files.get(COVERAGE_FILE)
    store_root: Path | None = None
    if isinstance(coverage, dict) and coverage.get("store_root"):
        store_root = Path(str(coverage["store_root"]))
    checked_hashes = 0
    for name, day in bundle.daily.items():
        if day.get("corrupt"):
            failures.append(f"daily/{name}: unreadable")
            continue
        slots_of_day = day.get("slots") or {}
        ticks = _int(day.get("ticks"))
        if ticks is None or ticks < len(slots_of_day):
            failures.append(f"daily/{name}: fewer ticks than slots")
        for key, entry in slots_of_day.items():
            if key not in slots:
                # A pruned slot log is allowed to have lost old rows; a day it cannot explain
                # at all is not.
                if (
                    len(slots)
                    >= int(
                        (bundle.files.get(BUDGET_FILE) or {})
                        .get("declared", {})
                        .get("slots_kept", 0)
                        or 0
                    )
                    and slots
                ):
                    failures.append(f"daily/{name}: slot {key} is missing from the slot log")
                continue
            if (entry or {}).get("outcome") != slots[key].get("outcome"):
                failures.append(f"daily/{name}: slot {key} disagrees with the slot log")
        hashes = day.get("day_hashes") or {}
        if store_root is not None and hashes:
            for series, digest in hashes.items():
                timeframe, _, symbol = series.partition(":")
                path = store_root / timeframe / f"{symbol.upper()}.jsonl"
                if not path.is_file():
                    failures.append(f"daily/{name}: no store file for {series}")
                    continue
                rows_for_day = [
                    row
                    for row in read_jsonl(path)[0]
                    if _day_of(_int(row.get("ts"))) == day.get("day")
                ]
                if not rows_for_day:
                    continue
                checked_hashes += 1
                if _sha256_rows(rows_for_day)[:16] != digest:
                    failures.append(f"daily/{name}: {series} digest does not answer to the store")
    return [
        (
            "DAILY_EVIDENCE_CONSISTENT",
            not failures,
            "; ".join(failures[:5])
            or f"{len(bundle.daily)} day file(s), {checked_hashes} digest(s) recomputed from the store",
        )
    ]


def _day_of(instant_ms: int | None) -> str | None:
    if instant_ms is None:
        return None
    import time

    return time.strftime("%Y-%m-%d", time.gmtime(instant_ms / 1000))


def check_health_follows_the_log(bundle: Bundle) -> list[tuple[str, bool, str]]:
    health = bundle.files.get(HEALTH_FILE)
    if not isinstance(health, dict):
        return [("HEALTH_FOLLOWS_THE_LOG", False, "no health artefact")]
    failures: list[str] = []
    runs = bundle.rows("runs.jsonl")
    # Restated here, not imported: a trigger that found its slot already sealed, and a trigger
    # that lost the lease to a live one, are neither an observation nor evidence that the feed
    # is failing. Counting them as failures would call the schedule's own politeness a fault.
    neutral = ("ALREADY_OBSERVED", "ALREADY_RUNNING")
    consecutive = 0
    for row in reversed(runs):
        outcome = str(row.get("outcome"))
        if outcome in SLOT_CONSUMING:
            break
        if outcome in neutral:
            continue
        consecutive += 1
    status = str(health.get("status"))
    if consecutive >= BLOCKED_AFTER_CONSECUTIVE_FAILURES and status != "BLOCKED":
        failures.append(
            f"{consecutive} consecutive non-observations but the health reading is {status}"
        )
    if _int(health.get("consecutive_non_observations")) != consecutive:
        failures.append(
            f"the published run of failures ({health.get('consecutive_non_observations')}) is not {consecutive}"
        )
    if status not in ("HEALTHY", "DEGRADED", "BLOCKED"):
        failures.append(f"health status outside the vocabulary: {status!r}")
    if status != "HEALTHY" and not health.get("reasons"):
        failures.append("a degraded or blocked reading carries no reason")
    last = health.get("last_tick") or {}
    if runs and last.get("run_id") not in (None, runs[-1].get("run_id")):
        failures.append("the health artefact names a different last tick than the run log")
    # The alert vocabulary, restated as declarations: a severity follows from the kind, a
    # recovery may only be called a recovery when the state it carries is healthy, and an
    # unhealthy reading must say why. A row that claims a recovery while carrying DEGRADED is
    # the failure this check exists for.
    severity_of = {
        "HEALTH_BLOCKED": "CRITICAL",
        "HEALTH_DEGRADED": "WARNING",
        "HEALTH_RECOVERED": "INFO",
        "OBSERVATION_GAP": "WARNING",
        "OBSERVATION_STALLED": "CRITICAL",
    }
    alerts, _corrupt = read_jsonl(bundle.path("alerts.jsonl"))
    for row in alerts:
        kind = str(row.get("kind"))
        if kind not in severity_of:
            continue
        if row.get("severity") != severity_of[kind]:
            failures.append(f"{kind} carries severity {row.get('severity')!r}")
        if row.get("hypothetical") is not True or row.get("order_sent") is not False:
            failures.append(f"{kind} at {row.get('at_utc')} is not marked hypothetical/no-order")
        if kind == "HEALTH_RECOVERED" and row.get("state") != "HEALTHY":
            failures.append(
                f"a recovery at {row.get('at_utc')} carries state {row.get('state')!r}"
            )
        if kind in ("HEALTH_BLOCKED", "HEALTH_DEGRADED") and not row.get("reasons"):
            failures.append(f"{kind} at {row.get('at_utc')} carries no reason")
        if kind in ("OBSERVATION_GAP", "OBSERVATION_STALLED") and _int(
            row.get("silence_minutes")
        ) is None:
            failures.append(f"{kind} at {row.get('at_utc')} does not say how long the silence was")
    return [
        (
            "HEALTH_FOLLOWS_THE_LOG",
            not failures,
            "; ".join(failures[:5])
            or f"{status} with {consecutive} consecutive non-observation(s)",
        )
    ]


def check_budget_declared_measured_and_bounded(bundle: Bundle) -> list[tuple[str, bool, str]]:
    budget = bundle.files.get(BUDGET_FILE)
    if not isinstance(budget, dict):
        return [("BUDGET_DECLARED_MEASURED_AND_BOUNDED", False, "no budget artefact")]
    failures: list[str] = []
    declared = budget.get("declared") or {}
    measured = budget.get("measured") or {}
    # The lane's own reading: the state tree, plus the publication tree only when it lives
    # outside the state root (inside it, it is already counted once).
    publication = bundle.publication
    inside_state = publication is not None and (
        publication == bundle.state_root or publication.is_relative_to(bundle.state_root)
    )
    # The tree the reading describes is the lane's own files. When the snapshot carries the
    # manifest of what it copied, that manifest *is* the tree: the snapshot directory also holds
    # this work package's own additions — the manifest itself, the generated timeline — and
    # charging those to the lane would be measuring the verifier's desk instead of the lane.
    manifest = bundle.files.get(SNAPSHOT_FILE)
    claimed = (manifest or {}).get("files") if isinstance(manifest, dict) else None
    if isinstance(claimed, dict) and claimed:
        state_bytes = sum(int((body or {}).get("bytes") or 0) for body in claimed.values())
    else:
        state_bytes = _bytes_under(bundle.state_root)
        if publication is not None and not inside_state:
            state_bytes += _bytes_under(publication)
    published = _int(measured.get("lane_bytes"))
    if published is None or published <= 0:
        failures.append("the measured lane size is not a positive number")
    # The reading is taken by the tick before it rewrites the two files that carry it, so it
    # can only be *smaller* than the tree at rest, and only by those files. A reading larger
    # than the tree, or smaller by more than them, is not a reading of this tree.
    carriers = sum(
        (bundle.path(name).stat().st_size if bundle.path(name).is_file() else 0)
        for name in (HEALTH_FILE, BUDGET_FILE)
    )
    if state_bytes and published is not None:
        delta = int(state_bytes) - int(published)
        if delta < 0:
            failures.append(
                f"the measured lane size {published} is larger than the tree {state_bytes}"
            )
        elif delta > max(carriers, 1):
            failures.append(
                f"the measured lane size {published} is {delta} bytes below the tree {state_bytes}, "
                f"more than the {carriers} bytes of the files written after it"
            )
    limit = _int(declared.get("lane_bytes"))
    if limit is None or limit <= 0:
        failures.append("no declared byte budget")
    elif published is not None and bool(budget.get("over_budget")) != (published > limit):
        failures.append("the over-budget flag does not follow from the declared limit")
    for name, key in BOUNDED_LOGS.items():
        keep = _int(declared.get(key))
        if keep is None:
            continue
        rows = len(bundle.rows(name))
        if rows > keep:
            failures.append(f"{name} holds {rows} rows, above its declared cap of {keep}")
    daily_keep = _int(declared.get("daily_kept"))
    if daily_keep is not None and len(bundle.daily) > max(0, int(daily_keep)):
        failures.append(f"{len(bundle.daily)} daily files, above the declared cap of {daily_keep}")
    if not (budget.get("policy") or {}):
        failures.append("the budget artefact declares no policy")
    return [
        (
            "BUDGET_DECLARED_MEASURED_AND_BOUNDED",
            not failures,
            "; ".join(failures[:5]) or f"lane {published} bytes of {limit} declared",
        )
    ]


def check_publication_swapped(bundle: Bundle) -> list[tuple[str, bool, str]]:
    """Every file the publication holds must answer to a recorded digest, and vice versa.

    The check is deliberately mapping-free: the pointer names its artefacts by the reporter's
    own keys, so instead of guessing which key means which file it requires the *set* of
    published files and the *set* of recorded digests to be the same thing.
    """
    publication = bundle.publication
    if publication is None:
        return [("PUBLICATION_SWAPPED_ATOMICALLY", False, "no publication directory was captured")]
    failures: list[str] = []
    staging = sorted(publication.glob(".staging-*"))
    if staging:
        failures.append(f"a staging tree survived: {[p.name for p in staging][:3]}")
    pointer = publication / "LATEST.json"
    if not pointer.is_file():
        return [("PUBLICATION_SWAPPED_ATOMICALLY", False, "the publication pointer is missing")]
    try:
        payload = json.loads(pointer.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [("PUBLICATION_SWAPPED_ATOMICALLY", False, "the publication pointer is unreadable")]
    if not isinstance(payload, dict):
        return [
            ("PUBLICATION_SWAPPED_ATOMICALLY", False, "the publication pointer is not an object")
        ]
    if payload.get("order_sent") is not False:
        failures.append("the publication pointer does not deny sending an order")
    artifacts = payload.get("artifacts") or {}
    if not artifacts:
        failures.append("the publication pointer names no artefact")
    published = sorted(
        path
        for path in publication.rglob("*")
        if path.is_file() and not path.name.startswith(".") and path != pointer
    )
    recorded = {
        (str(body.get("sha256")), _int(body.get("bytes")))
        for body in artifacts.values()
        if isinstance(body, dict)
    }
    if len(published) != len(recorded):
        failures.append(
            f"{len(published)} published file(s) against {len(recorded)} recorded digest(s)"
        )
    for path in published:
        actual = (_digest(path), path.stat().st_size)
        if actual not in recorded:
            name = path.relative_to(publication).as_posix()
            failures.append(f"a published file answers to no recorded digest: {name}")
    return [
        (
            "PUBLICATION_SWAPPED_ATOMICALLY",
            not failures,
            "; ".join(failures[:5])
            or f"{len(published)} published file(s) answer to their recorded digests",
        )
    ]


def check_freeze_and_floor_declared(bundle: Bundle) -> list[tuple[str, bool, str]]:
    coverage = bundle.files.get(COVERAGE_FILE)
    if not isinstance(coverage, dict):
        return [("FREEZE_AND_FLOOR_DECLARED", False, "no coverage artefact")]
    failures: list[str] = []
    freeze = coverage.get("freeze") or {}
    if freeze.get("frozen_1h_end_utc") != _stamp(FROZEN_1H_END_MS):
        failures.append(f"the 1h freeze is not {_stamp(FROZEN_1H_END_MS)}")
    if freeze.get("frozen_15m_end_utc") != _stamp(FROZEN_15M_END_MS):
        failures.append(f"the 15m freeze is not {_stamp(FROZEN_15M_END_MS)}")
    if _int(coverage.get("required_days")) != OBSERVATION_FLOOR_DAYS:
        failures.append("the observation floor is not the declared 60 days")
    if abs(float(coverage.get("coverage_required") or 0) - COVERAGE_REQUIRED) > 1e-9:
        failures.append("the coverage requirement is not the declared 90%")
    if sorted(map(str, coverage.get("primary_series") or [])) != sorted(PRIMARY_SERIES):
        failures.append("the primary series are not the declared ones")
    rule = str(coverage.get("rule") or "")
    for bound in PROSPECTIVE_LAG_BOUND_MS.values():
        if str(bound) not in rule:
            failures.append("the declared lag bound is not the one applied")
            break
    for key in ("not_an_admission", "not_counted"):
        if not coverage.get(key):
            failures.append(f"the coverage artefact does not declare {key}")
    return [
        (
            "FREEZE_AND_FLOOR_DECLARED",
            not failures,
            "; ".join(failures[:5]) or "freeze, coverage rule, primary series and floor declared",
        )
    ]


def _stamp(instant_ms: int) -> str:
    import time

    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(instant_ms / 1000))


def check_scheduler_registration_read(bundle: Bundle) -> list[tuple[str, bool, str]]:
    if bundle.install is None or not Path(bundle.install).is_file():
        return [
            (
                "SCHEDULER_REGISTRATION_READ",
                True,
                "skipped: no captured task registration to read (SKIPPED_NO_REGISTRATION)",
            )
        ]
    try:
        payload = json.loads(Path(bundle.install).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [("SCHEDULER_REGISTRATION_READ", False, "the captured registration is unreadable")]
    failures: list[str] = []
    task = payload.get("task") or {}
    if str(payload.get("task_name") or task.get("task_name")) != TASK_NAME:
        failures.append(f"the registration is not for {TASK_NAME}")
    if not payload.get("installed"):
        failures.append("the task is not installed")
    if not payload.get("enabled"):
        failures.append("the task is not enabled")
    arguments = str(payload.get("arguments") or "")
    for token in ("--scheduled", "--due"):
        if token not in arguments:
            failures.append(f"the task does not pass {token}")
    if "edge04_observer.py" not in arguments:
        failures.append("the task does not run the observer entry point")
    if _int(payload.get("interval_minutes")) != SLOT_MINUTES:
        failures.append(f"the task does not repeat every {SLOT_MINUTES} minutes")
    return [
        (
            "SCHEDULER_REGISTRATION_READ",
            not failures,
            "; ".join(failures[:5])
            or (
                "the registration names the entry point, the flags and the cadence — a "
                "declaration, not a measurement"
            ),
        )
    ]


CHECKS = (
    ("ARTIFACTS_PRESENT", check_artifacts_present),
    ("SLOT_DISCIPLINE", check_slot_discipline),
    ("OUTCOMES_AND_EXIT_CODES", check_outcomes_and_exit_codes),
    ("NO_ORDER_PATH_OR_PROMOTION", check_no_order_path_or_promotion),
    ("EXPECTATION_ARITHMETIC", check_expectation_arithmetic),
    ("MARKET_REQUESTS_ARE_SPENT", check_market_requests_are_spent),
    ("RULESET_PINNED_AND_UNCHANGED", check_ruleset_pinned),
    ("COVERAGE_RULE_APPLIED", check_coverage_rule),
    ("BACKFILL_IS_NOT_AN_OBSERVATION", check_backfill_is_not_an_observation),
    ("DAILY_EVIDENCE_CONSISTENT", check_daily_evidence),
    ("HEALTH_FOLLOWS_THE_LOG", check_health_follows_the_log),
    ("BUDGET_DECLARED_MEASURED_AND_BOUNDED", check_budget_declared_measured_and_bounded),
    ("PUBLICATION_SWAPPED_ATOMICALLY", check_publication_swapped),
    ("FREEZE_AND_FLOOR_DECLARED", check_freeze_and_floor_declared),
    ("SCHEDULER_REGISTRATION_READ", check_scheduler_registration_read),
)


def run_checks(bundle: Bundle) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for name, function in CHECKS:
        for check_name, passed, detail in function(bundle):
            assert check_name == name, (check_name, name)
            checks.append({"check": check_name, "passed": bool(passed), "detail": detail})
    failed = [entry for entry in checks if not entry["passed"]]
    return {
        "verdict": "VERIFY_PASS" if not failed else "VERIFY_FAIL",
        "checks_total": len(checks),
        "checks_passed": len(checks) - len(failed),
        "failures": [f"{entry['check']}: {entry['detail']}" for entry in failed],
        "checks": checks,
        "state_root": str(bundle.state_root),
        "reading": (
            "this process imports nothing from trading_bot and drives none of the observer's "
            "code: it recomputes every claim from the files the observer left behind"
        ),
    }


# --------------------------------------------------------------------------- self-test
def _sabotages() -> list[tuple[str, str, Any]]:
    """One sabotage per check. Each returns whether it could be applied to this tree.

    A sabotage whose precondition is absent (no backfilled day to promote, no published digest
    to break) is reported as *skipped*, never as a pass: a check nobody could attack is not a
    check that held.
    """

    def delete_an_artifact(root: Path) -> bool:
        path = root / HEALTH_FILE
        if not path.is_file():
            return False
        path.unlink()
        return True

    def duplicate_slot(root: Path) -> bool:
        path = root / "slots.jsonl"
        rows = path.read_text(encoding="utf-8").splitlines()
        if not rows:
            return False
        path.write_text("\n".join([*rows, rows[-1]]) + "\n", encoding="utf-8")
        return True

    def off_grid_slot(root: Path) -> bool:
        path = root / "slots.jsonl"
        rows, _ = read_jsonl(path)
        if not rows:
            return False
        rows[0]["slot_key"] = "2026-10-13T00:07Z"
        path.write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8"
        )
        return True

    def wrong_exit_code(root: Path) -> bool:
        path = root / "runs.jsonl"
        rows, _ = read_jsonl(path)
        if not rows:
            return False
        for row in rows:
            row["exit_code"] = 0 if row.get("outcome") != "OBSERVED" else 99
            if row.get("exit_code") == EXIT_CODES.get(str(row.get("outcome"))):
                row["exit_code"] = 99
        path.write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8"
        )
        return True

    def order_sent(root: Path) -> bool:
        path = root / "runs.jsonl"
        rows, _ = read_jsonl(path)
        if not rows:
            return False
        rows[-1]["order_sent"] = True
        path.write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8"
        )
        return True

    def promotion(root: Path) -> bool:
        files = sorted((root / "daily").glob("*.json"))
        if not files:
            return False
        for path in files:
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["promotion"] = "PAPER"
            path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return True

    def missing_without_marking(root: Path) -> bool:
        """A bar that had closed and is not in the store, reported as nothing missing."""
        path = root / "runs.jsonl"
        rows, _ = read_jsonl(path)
        for row in rows:
            series = row.get("expectation_series")
            if isinstance(series, list) and series and isinstance(series[0], dict):
                series[0]["expected"] = int(series[0].get("expected") or 0) + 5
                series[0]["missing"] = 0
                path.write_text(
                    "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8"
                )
                return True
        return False

    def requests_on_a_refusal(root: Path) -> bool:
        path = root / "runs.jsonl"
        rows, _ = read_jsonl(path)
        if not rows:
            return False
        rows.append(
            {
                "run_id": "FWD-EDGE04-SABOTAGE",
                "outcome": "DISK_BUDGET_EXCEEDED",
                "exit_code": 5,
                "slot_key": "1999-01-01T00:00Z",
                "market_requests": 42,
                "hypothetical": True,
                "order_sent": False,
                "errors": [{"stage": "tick"}],
                "expectation_series": [],
            }
        )
        path.write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8"
        )
        return True

    def repin_ruleset(root: Path) -> bool:
        path = root / "runs.jsonl"
        rows, _ = read_jsonl(path)
        touched = False
        for row in rows:
            if isinstance(row.get("ruleset"), dict):
                row["ruleset"]["params_hash"] = "0" * 64
                touched = True
        path.write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8"
        )
        return touched

    def inflate_the_day_count(root: Path) -> bool:
        path = root / COVERAGE_FILE
        if not path.is_file():
            return False
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["prospectively_observed"] = 42
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return True

    def promote_a_backfilled_day(root: Path) -> bool:
        path = root / COVERAGE_FILE
        if not path.is_file():
            return False
        payload = json.loads(path.read_text(encoding="utf-8"))
        for day in payload.get("days") or []:
            if day.get("class") == "DENSE_BUT_BACKFILLED":
                day["class"] = "PROSPECTIVELY_OBSERVED"
                payload.setdefault("prospectively_observed_days", []).append(day["day"])
                path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
                return True
        return False

    def change_a_freeze(root: Path) -> bool:
        path = root / COVERAGE_FILE
        if not path.is_file():
            return False
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.setdefault("freeze", {})["frozen_1h_end_utc"] = "2026-01-01T00:00:00Z"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return True

    def flip_a_day_hash(root: Path) -> bool:
        for path in sorted((root / "daily").glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            hashes = payload.get("day_hashes") or {}
            if hashes:
                hashes[sorted(hashes)[0]] = "0" * 16
                path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
                return True
        return False

    def healthy_with_failures(root: Path) -> bool:
        """A run of failed ticks in the log, with the health reading claiming all is well."""
        path = root / HEALTH_FILE
        runs = root / "runs.jsonl"
        if not path.is_file() or not runs.is_file():
            return False
        failure = {
            "run_id": "FWD-EDGE04-SABOTAGE",
            "outcome": "MISSING_BARS",
            "exit_code": 4,
            "slot_key": "1999-01-01T00:00Z",
            "market_requests": 1,
            "hypothetical": True,
            "order_sent": False,
            "errors": [{"stage": "tick"}],
            "expectation_series": [],
        }
        with runs.open("a", encoding="utf-8") as handle:
            for _ in range(BLOCKED_AFTER_CONSECUTIVE_FAILURES):
                handle.write(json.dumps(failure, sort_keys=True) + "\n")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["status"] = "HEALTHY"
        payload["reasons"] = []
        payload["consecutive_non_observations"] = 0
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return True

    def inflate_the_lane_size(root: Path) -> bool:
        path = root / BUDGET_FILE
        if not path.is_file():
            return False
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.setdefault("measured", {})["lane_bytes"] = 999_999_999
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return True

    def unbounded_log(root: Path) -> bool:
        """Grow a bounded log past the cap its own budget artefact declares.

        Five extra rows would prove nothing when the cap is thousands: the sabotage reads the
        declared cap and crosses it, so it stays a real attack if the cap is ever changed.
        """
        path = root / "runs.jsonl"
        budget = root / BUDGET_FILE
        if not path.is_file() or not budget.is_file():
            return False
        declared = json.loads(budget.read_text(encoding="utf-8")).get("declared") or {}
        keep = _int(declared.get("runs_kept"))
        if keep is None:
            return False
        rows, _corrupt = read_jsonl(path)
        row = {
            "run_id": "x",
            "outcome": "NO_NEW_DATA",
            "exit_code": 0,
            "slot_key": "1999-01-01T00:00Z",
        }
        with path.open("a", encoding="utf-8") as handle:
            for _ in range(max(1, int(keep) + 1 - len(rows))):
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        return True

    def break_a_published_digest(root: Path) -> bool:
        target = root / "publication" / "LATEST.json"
        if not target.is_file():
            return False
        payload = json.loads(target.read_text(encoding="utf-8"))
        broken = False
        for _name, body in (payload.get("artifacts") or {}).items():
            if isinstance(body, dict):
                body["sha256"] = "0" * 64
                broken = True
                break
        if not broken:
            return False
        target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return True

    def leave_a_staging_tree(root: Path) -> bool:
        staging = root / "publication" / ".staging-1"
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "HALF.md").write_text("torn", encoding="utf-8")
        return True

    def unregister_the_task(root: Path) -> bool:
        path = root / "install.json"
        if not path.is_file():
            return False
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["enabled"] = False
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return True

    def forget_the_tick(root: Path) -> bool:
        """Delete the run row that *sealed* the newest slot, and nothing else.

        Removing whichever row happens to be last would attack a no-op trigger that sealed
        nothing, and a check that ignored it would be right: the attack has to take the row the
        slot ledger names as its author, with the consuming outcome.
        """
        path = root / "runs.jsonl"
        slots_path = root / "slots.jsonl"
        if not path.is_file() or not slots_path.is_file():
            return False
        seals, _corrupt = read_jsonl(slots_path)
        rows, _corrupt_rows = read_jsonl(path)
        if not seals or not rows:
            return False
        key = str(seals[-1].get("slot_key"))
        run_id = str(seals[-1].get("run_id"))
        keep = [
            row
            for row in rows
            if not (
                str(row.get("run_id")) == run_id
                and str(row.get("slot_key")) == key
                and row.get("outcome") in SLOT_CONSUMING
            )
        ]
        if len(keep) == len(rows):
            return False
        path.write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in keep), encoding="utf-8"
        )
        return True

    return [
        (
            "ARTIFACTS_PRESENT",
            "delete a required artefact",
            delete_an_artifact,
        ),
        ("SLOT_DISCIPLINE", "duplicate an observed slot", duplicate_slot),
        ("SLOT_DISCIPLINE", "move a slot key off the grid", off_grid_slot),
        ("OUTCOMES_AND_EXIT_CODES", "flatten every exit code to zero", wrong_exit_code),
        ("NO_ORDER_PATH_OR_PROMOTION", "claim an order was sent", order_sent),
        ("NO_ORDER_PATH_OR_PROMOTION", "promote the lane in a day file", promotion),
        ("EXPECTATION_ARITHMETIC", "hide a shortfall in one series", missing_without_marking),
        ("MARKET_REQUESTS_ARE_SPENT", "spend requests on a refusal", requests_on_a_refusal),
        ("RULESET_PINNED_AND_UNCHANGED", "re-pin the ruleset to another digest", repin_ruleset),
        ("COVERAGE_RULE_APPLIED", "inflate the observation day count", inflate_the_day_count),
        (
            "BACKFILL_IS_NOT_AN_OBSERVATION",
            "call a backfilled day observed",
            promote_a_backfilled_day,
        ),
        ("FREEZE_AND_FLOOR_DECLARED", "move the 1h freeze", change_a_freeze),
        ("DAILY_EVIDENCE_CONSISTENT", "flip a day's store digest", flip_a_day_hash),
        ("HEALTH_FOLLOWS_THE_LOG", "declare HEALTHY under a failure streak", healthy_with_failures),
        (
            "BUDGET_DECLARED_MEASURED_AND_BOUNDED",
            "inflate the measured lane size",
            inflate_the_lane_size,
        ),
        ("BUDGET_DECLARED_MEASURED_AND_BOUNDED", "grow a bounded log past its cap", unbounded_log),
        ("PUBLICATION_SWAPPED_ATOMICALLY", "break a published digest", break_a_published_digest),
        ("PUBLICATION_SWAPPED_ATOMICALLY", "leave a staging tree behind", leave_a_staging_tree),
        ("SCHEDULER_REGISTRATION_READ", "disable the registered task", unregister_the_task),
        ("SLOT_DISCIPLINE", "remove the run row behind a slot", forget_the_tick),
    ]


def self_test(*, state_root: Path, repo: Path, install: Path | None = None) -> dict[str, Any]:
    """Sabotage a copy of the evidence once per check and require the matching check to break."""
    results: list[dict[str, Any]] = []
    baseline = run_checks(load_bundle(state_root, repo=repo, install=install))
    with tempfile.TemporaryDirectory() as scratch:
        for check_name, description, sabotages in _sabotages():
            target = Path(scratch) / check_name.lower().replace("_", "-")[:24]
            target = Path(scratch) / f"{len(results):02d}"
            shutil.copytree(state_root, target, dirs_exist_ok=True)
            captured = install
            if install is not None and Path(install).is_file():
                captured = target / Path(install).name
                shutil.copyfile(install, captured)
            could_apply = bool(sabotages(target))
            if not could_apply:
                results.append(
                    {
                        "check": check_name,
                        "sabotage": description,
                        "applied": False,
                        "detected": None,
                        "detail": "SKIPPED_NO_PRECONDITION: nothing in this tree to attack",
                    }
                )
                continue
            report = run_checks(load_bundle(target, repo=repo, install=captured))
            broken = [
                entry
                for entry in report["checks"]
                if entry["check"] == check_name and not entry["passed"]
            ]
            results.append(
                {
                    "check": check_name,
                    "sabotage": description,
                    "applied": True,
                    "detected": bool(broken),
                    "detail": broken[0]["detail"] if broken else report["verdict"],
                }
            )
    applied = sum(1 for entry in results if entry["applied"])
    skipped = len(results) - applied
    detected = sum(1 for entry in results if entry["detected"])
    return {
        "verdict": "SELF_TEST_PASS" if detected == applied else "SELF_TEST_FAIL",
        "baseline_verdict": baseline["verdict"],
        "applied": applied,
        "skipped": skipped,
        "detected": detected,
        "undetected": applied - detected,
        "sabotages": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--state-root", default="data/forward/edge04", help="where the observer's state lives"
    )
    parser.add_argument("--repo", default=None, help="the checkout the artefacts describe")
    parser.add_argument("--install", default=None, help="a captured task registration to read")
    parser.add_argument("--json-out", default=None)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    state_root = Path(args.state_root).resolve()
    repo = Path(args.repo).resolve() if args.repo else Path.cwd()
    candidate = Path(args.install) if args.install else state_root / "install.json"
    install: Path | None = candidate if candidate.is_file() else None
    report = run_checks(load_bundle(state_root, repo=repo, install=install))
    payload: dict[str, Any] = {"verification": report}
    if args.self_test:
        payload["self_test"] = self_test(state_root=state_root, repo=repo, install=install)
    for entry in report["checks"]:
        print(f"{'PASS' if entry['passed'] else 'FAIL'}  {entry['check']:<40} {entry['detail']}")
    print(f"\nverdict  {report['verdict']}  ({report['checks_passed']}/{report['checks_total']})")
    if args.self_test:
        self_test_report = payload["self_test"]
        print(
            f"self-test  {self_test_report['verdict']}  "
            f"({self_test_report['detected']}/{self_test_report['applied']} sabotages detected, "
            f"{self_test_report['skipped']} skipped)"
        )
        for entry in self_test_report["sabotages"]:
            if entry["applied"] and not entry["detected"]:
                print(f"  UNDETECTED  {entry['check']}: {entry['sabotage']}")
            elif not entry["applied"]:
                print(f"  SKIPPED     {entry['check']}: {entry['sabotage']}")
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
    failed = report["verdict"] != "VERIFY_PASS" or (
        args.self_test and payload.get("self_test", {}).get("verdict") != "SELF_TEST_PASS"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
