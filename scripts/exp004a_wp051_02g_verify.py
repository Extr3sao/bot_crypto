"""WP-051-02G independent verifier: decide from the bytes whether the capture is what it claims.

This program is deliberately a second implementation rather than a call into the first. It does
not import ``trading_bot``, the capture engine or the builder; it parses the declaration, the
shards, the consolidated dataset and the forward store with its own reader, recomputes every
digest and every lag, and derives coverage from the declaration's own denominator. A builder bug
therefore cannot hide behind a shared helper, and a manifest that lies about a shard is caught by
comparison with the store rather than by trust.

Three verdicts, and only three shapes of them:

* ``PASS_COVERAGE_COMPLETE`` — every declared bar is present, admissible and byte-identical to
  the store; the consolidated dataset is the shards' own bytes; nothing in the package claims more
  than it holds. Exit 0. This is the *only* state in which certification is allowed.
* ``PASS_COVERAGE_INCOMPLETE`` — the bytes that exist verify, and the declaration's denominator is
  not met. Exit 3. Never a pass, never a failure of the mechanism: a truthful ``PENDING``.
* ``FAIL`` — a control failed. Exit 2.

Research only: reads local files, writes one JSON verdict, makes no network call, places no order.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

VERIFIER_ID = "verifier-g/EXP-004A/WP-051-02G"
SCHEMA_VERSION = "1.0"
DECLARATION = "config/preregistrations/EXP-004A.datasets.phase3.json"
BUILDER = "scripts/exp004a_wp051_02g_capture.py"

EXIT_PASS = 0
EXIT_FAIL = 2
EXIT_INCOMPLETE = 3
EXIT_ERROR = 4

INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}

COVERAGE_PENDING_WINDOW_OPEN = "PENDING_WINDOW_OPEN"
COVERAGE_PENDING = "PENDING"
COVERAGE_BELOW_DECLARED = "BELOW_DECLARED"
COVERAGE_COMPLETE = "COVERAGE_COMPLETE"

#: Package directories whose bytes this package is forbidden to change. ``wp051_02g`` is absent on
#: purpose: it is the package doing the checking.
FROZEN_PREFIXES = (
    "docs/agentic/exp004a/wp051_02c",
    "docs/agentic/exp004a/wp051_02d",
    "docs/agentic/exp004a/wp051_02e",
    "docs/agentic/exp004a/wp051_02f",
    "data/exp004a/EXP-004A-1H-",
    "config/preregistrations/EXP-004A.datasets",
    "scripts/exp004a_capture.py",
    "scripts/exp004a_provenance_preflight.py",
    "scripts/exp004a_provenance_verify.py",
    "scripts/exp004a_verify.py",
    "scripts/exp004a_foundation.py",
    "scripts/exp004a_wp051_02e_preflight.py",
    "scripts/exp004a_wp051_02e_verify.py",
    "scripts/exp004a_wp051_02f_runner.py",
    "scripts/exp004a_wp051_02f_verify.py",
)


def now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_ms(value: object, field: str) -> int:
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        raise ValueError(f"{field} is naive")
    return int(moment.astimezone(UTC).timestamp() * 1000)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def git(repo: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args], cwd=str(repo), capture_output=True, text=True, timeout=60, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return completed.stdout if completed.returncode == 0 else None


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    ok: bool
    detail: str = ""
    advisory: bool = False

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"name": self.name, "ok": self.ok, "detail": self.detail}
        if self.advisory:
            payload["advisory"] = True
        return payload


# --------------------------------------------------------------------------- #
# the declaration, read again
# --------------------------------------------------------------------------- #


def read_declaration(repo: Path, path: Path) -> dict[str, Any]:
    """Parse the declaration into the shape this verifier needs, or raise."""
    raw = path.read_bytes()
    document = json.loads(raw.decode("utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path} is not an object")
    # Paths inside a declaration are relative to the repository that holds it, not to whichever
    # checkout the verifier happens to be run from.
    declaration_root = path.resolve().parents[2] if len(path.resolve().parents) > 2 else repo
    window = document["capture_window"]
    start = parse_ms(window["start_utc"], "capture_window.start_utc")
    end = parse_ms(window["end_utc"], "capture_window.end_utc")
    effective = parse_ms(document["effective_from_utc"], "effective_from_utc")
    entries = []
    for item in document["entries"]:
        interval = str(item["timeframe"])
        if interval not in INTERVAL_MS:
            raise ValueError(f"{item.get('dataset_id')} has a non-bar timeframe {interval!r}")
        span = INTERVAL_MS[interval]
        entry_start = parse_ms(item.get("period_start_utc") or window["start_utc"], "period_start_utc")
        entry_end = parse_ms(item.get("period_end_utc") or window["end_utc"], "period_end_utc")
        grid = expected_opens(entry_start, entry_end, span)
        declared = int(item.get("row_count") or len(grid))
        parameters = item.get("generator_parameters") or {}
        entries.append(
            {
                "dataset_id": str(item["dataset_id"]),
                "asset": str(item["asset"]),
                "interval": interval,
                "span": span,
                "label": f"{interval}:{item['asset']}",
                "start": entry_start,
                "end": entry_end,
                "grid": grid,
                "declared_rows": declared,
                "lag_bound_ms": int(
                    parameters.get("lag_bound_ms") or item.get("lag_bound_ms") or 0
                ),
                "coverage_required": float(
                    parameters.get("coverage_required") or item.get("coverage_required") or 0.0
                ),
                "source": (declaration_root / str(item["source_path"])).resolve(),
            }
        )
    rehearsal = document.get("rehearsal")
    return {
        "raw": raw,
        "sha256": sha256_bytes(raw),
        "declaration_id": str(document["declaration_id"]),
        "window_start": start,
        "window_end": end,
        "effective_from": effective,
        "entries": entries,
        "rehearsal": rehearsal if isinstance(rehearsal, dict) else None,
        "shard_root": (declaration_root / str(document.get("shard_root") or "")).resolve()
        if document.get("shard_root")
        else None,
        "declaration_root": declaration_root,
        "generator": document.get("generator") if isinstance(document.get("generator"), dict) else {},
    }


def relative(path: Path, repo: Path) -> str:
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def expected_opens(start_ms: int, end_ms: int, span: int) -> tuple[int, ...]:
    first = -(-start_ms // span) * span
    return tuple(range(first, end_ms, span))


def utc_day(open_ms: int) -> str:
    return datetime.fromtimestamp(open_ms / 1000, UTC).strftime("%Y-%m-%d")


def day_open_ms(day: str) -> int:
    return int(datetime.fromisoformat(f"{day}T00:00:00+00:00").timestamp() * 1000)


def day_grid(day: str, span: int) -> tuple[int, ...]:
    start = day_open_ms(day)
    return tuple(range(start, start + 86_400_000, span))


def days_of(entry: dict[str, Any]) -> tuple[str, ...]:
    days: list[str] = []
    for open_ms in entry["grid"]:
        day = utc_day(open_ms)
        if not days or days[-1] != day:
            days.append(day)
    return tuple(days)


# --------------------------------------------------------------------------- #
# the store, read again and independently
# --------------------------------------------------------------------------- #


def read_source(path: Path) -> dict[int, tuple[bytes, dict[str, Any]]]:
    """``open_ms -> (raw line bytes, parsed record)``, parsed without the store module.

    The raw bytes are kept because the central question this verifier asks is not "is the number
    the same" but "is this the same line the observer wrote".
    """
    rows: dict[int, tuple[bytes, dict[str, Any]]] = {}
    for number, line in enumerate(path.read_bytes().splitlines(keepends=True), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        record = json.loads(stripped)
        open_ms = int(record["ts"])
        if open_ms in rows:
            raise ValueError(f"{path}:{number} repeats the open instant {open_ms}")
        rows[open_ms] = (line if line.endswith(b"\n") else line + b"\n", record)
    if not rows:
        raise ValueError(f"{path} holds no bars")
    return rows


# --------------------------------------------------------------------------- #
# controls
# --------------------------------------------------------------------------- #


def check_declaration(
    declaration: dict[str, Any],
    claim: dict[str, Any],
    *,
    prospective: bool,
    repo: Path,
    declaration_rel: str,
) -> list[Check]:
    checks: list[Check] = []
    # A declaration inside the repository is the experiment's; one outside it is a fixture. A
    # control that cannot apply to a fixture is named and marked advisory, never silently green.
    inside = not Path(declaration_rel).is_absolute() and not declaration_rel.startswith("..")
    declared = claim.get("declaration") or {}
    checks.append(
        Check(
            "DECLARATION_SHA256",
            declared.get("sha256") == declaration["sha256"],
            f"claim says {str(declared.get('sha256'))[:16]}, file hashes to {declaration['sha256'][:16]}",
        )
    )
    checks.append(
        Check(
            "DECLARATION_ID",
            declared.get("declaration_id") == declaration["declaration_id"],
            f"claim {declared.get('declaration_id')!r} vs file {declaration['declaration_id']!r}",
        )
    )
    arithmetic: list[str] = []
    for entry in declaration["entries"]:
        if entry["declared_rows"] != len(entry["grid"]):
            arithmetic.append(
                f"{entry['label']}: declared {entry['declared_rows']} rows, grid has {len(entry['grid'])}"
            )
        if entry["lag_bound_ms"] <= 0:
            arithmetic.append(f"{entry['label']}: no positive lag bound")
        if entry["start"] < declaration["window_start"] or entry["end"] > declaration["window_end"]:
            arithmetic.append(f"{entry['label']}: leaves the declared window")
    checks.append(
        Check(
            "DECLARATION_ARITHMETIC",
            not arithmetic,
            "; ".join(arithmetic) or "windows, timeframes and declared row counts agree",
        )
    )
    # The declaration names a commit and three blob ids. Without this control nobody ever checks
    # that the programs which ran are the programs the contract names.
    recorded = declaration.get("generator") or {}
    pairs = (
        ("program", str(recorded.get("program") or ""), str(recorded.get("program_blob") or "")),
        ("verifier", str(recorded.get("verifier") or ""), str(recorded.get("verifier_blob") or "")),
        ("engine", str(recorded.get("engine") or ""), str(recorded.get("engine_block") or "")),
    )
    mismatched: list[str] = []
    for label, relative, expected_blob in pairs:
        if not relative or not expected_blob:
            mismatched.append(f"{label}: the declaration names no blob")
            continue
        actual = (git(repo, "hash-object", relative) or "").strip()
        if actual != expected_blob:
            mismatched.append(f"{relative}: worktree blob is {actual or 'unreadable'}, declaration says {expected_blob}")
    # "The declaration names no programs" and "the programs do not match" are different facts: the
    # first is a fixture, the second is a failure.
    unnamed = not any(relative for _, relative, _ in pairs)
    if unnamed:
        checks.append(
            Check(
                "GENERATOR_BLOB_RECORDED",
                not inside,
                f"{declaration_rel} names no programs; the control does not apply to a fixture"
                if not inside
                else f"{declaration_rel} names no programs, so nothing ties the run to a commit",
                advisory=not inside,
            )
        )
    else:
        checks.append(
            Check(
                "GENERATOR_BLOB_RECORDED",
                not mismatched,
                "; ".join(mismatched[:3])
                or "program, verifier and engine hash to the blob ids the declaration names",
            )
        )
    rehearsal = declaration.get("rehearsal")
    if rehearsal is not None:
        rehearsal_start = parse_ms(rehearsal["start_utc"], "rehearsal.start_utc")
        rehearsal_end = parse_ms(rehearsal["end_utc"], "rehearsal.end_utc")
        overlaps = rehearsal_start < declaration["window_end"] and declaration["window_start"] < rehearsal_end
        checks.append(
            Check(
                "REHEARSAL_DISJOINT_FROM_WINDOW",
                not overlaps and not bool(rehearsal.get("counts_toward_coverage", False)),
                (
                    "the rehearsal window shares an instant with the capture window"
                    if overlaps
                    else "the rehearsal window is disjoint from the capture window and counts for nothing"
                ),
            )
        )
    # A declaration inside the repository is the experiment's; one outside it is a fixture, and a
    # control that cannot apply to a fixture is named and marked advisory rather than passing
    # silently.
    inside = not Path(declaration_rel).is_absolute() and not declaration_rel.startswith("..")
    if prospective:
        # The only thing that makes the window prospective is that the contract existed before it
        # opened. That is a Git fact, not a field, so it is read from Git.
        commit_time = git(repo, "log", "-1", "--format=%cI", "--", declaration_rel) if inside else None
        if commit_time is None and not inside:
            # A declaration outside the repository is a fixture. The control is named and marked
            # advisory rather than passing silently: a real capture cannot be in this position.
            checks.append(
                Check(
                    "DECLARATION_COMMIT_PRECEDES_WINDOW",
                    True,
                    f"{declaration_rel} is not a repository declaration; the control does not apply",
                    advisory=True,
                )
            )
        elif commit_time is None:
            checks.append(
                Check(
                    "DECLARATION_COMMIT_PRECEDES_WINDOW",
                    False,
                    "the declaration has no commit; a window cannot be prospective without one",
                )
            )
        else:
            try:
                committed_ms = parse_ms(commit_time.strip(), "commit time")
            except ValueError:
                committed_ms = -1
            checks.append(
                Check(
                    "DECLARATION_COMMIT_PRECEDES_WINDOW",
                    0 < committed_ms <= declaration["window_start"],
                    f"commit {commit_time.strip()} vs window start {iso(declaration['window_start'])}",
                )
            )
    return checks


def shard_paths(root: Path, entry: dict[str, Any], day: str) -> tuple[Path, Path]:
    base = root / f"{entry['interval']}_{entry['asset']}" / day
    return base.with_suffix(".jsonl"), base.with_suffix(".MANIFEST.json")


def verify_shards(
    root: Path,
    declaration: dict[str, Any],
    entries: list[dict[str, Any]],
    *,
    at_ms: int,
    prospective: bool,
    counts_toward_coverage: bool,
) -> tuple[list[Check], dict[str, dict[str, Any]], list[dict[str, Any]], dict[tuple[str, int], str]]:
    # ``prospective`` is what makes ``effective_from_utc`` binding: a bar stored before the
    # declaration took effect cannot be evidence that the window was watched.
    """Re-derive every shard's claim from the store's bytes.

    Returns the checks, a per-slice summary, and the per-day records the consolidation is rebuilt
    from. Nothing here reads ``state/scheduler.json``: a watermark is not evidence.
    """
    checks: list[Check] = []
    summaries: dict[str, dict[str, Any]] = {}
    days: list[dict[str, Any]] = []
    duplicate_opens: list[str] = []
    seen: set[tuple[str, int]] = set()
    #: Every open instant the store says is inadmissible, with the reason. The dataset must not
    #: contain any of them; a quarantined day is not a failure, a quarantined day that reached the
    #: dataset is.
    inadmissible: dict[tuple[str, int], str] = {}
    undisclosed: list[str] = []
    #: The digest of the program that wrote each shard. Two different builders in one package is
    #: a provenance question the report must answer rather than hide.
    generators: dict[tuple[str, str], str] = {}
    for entry in entries:
        source = read_source(entry["source"])
        summary: dict[str, Any] = {
            "slice": entry["label"],
            "shards": 0,
            "admissible_days": 0,
            "quarantined_days": 0,
            "rows": 0,
            "problems": [],
        }
        for day in days_of(entry):
            data_path, manifest_path = shard_paths(root, entry, day)
            if not manifest_path.is_file():
                if data_path.is_file():
                    summary["problems"].append(f"{day}: payload without manifest")
                continue
            summary["shards"] += 1
            manifest = read_json(manifest_path)
            if not isinstance(manifest, dict):
                summary["problems"].append(f"{day}: manifest unreadable")
                continue
            payload = data_path.read_bytes() if data_path.is_file() else b""
            digest = sha256_bytes(payload)
            if digest != manifest.get("sha256"):
                summary["problems"].append(
                    f"{day}: payload hashes to {digest[:16]}, manifest says "
                    f"{str(manifest.get('sha256'))[:16]}"
                )
                continue
            generator = (manifest.get("capture") or {}).get("generator") or {}
            generators[(entry["label"], day)] = str(generator.get("script_sha256") or "")
            if int(manifest.get("row_count", -1)) != len(
                [line for line in payload.splitlines() if line.strip()]
            ):
                summary["problems"].append(f"{day}: row_count disagrees with the payload")
                continue
            rows: dict[int, bytes] = {}
            for line in payload.splitlines(keepends=True):
                stripped = line.strip()
                if not stripped:
                    continue
                record = json.loads(stripped)
                open_ms = int(record["ts"])
                if open_ms in rows:
                    summary["problems"].append(f"{day}: repeats the open {iso(open_ms)} inside the shard")
                rows[open_ms] = line if line.endswith(b"\n") else line + b"\n"
            expected = tuple(
                open_ms
                for open_ms in day_grid(day, entry["span"])
                if entry["start"] <= open_ms < entry["end"]
            )
            if sorted(rows) != list(expected):
                missing = sorted(set(expected) - set(rows))
                extra = sorted(set(rows) - set(expected))
                summary["problems"].append(
                    f"{day}: {len(missing)} expected bar(s) absent, {len(extra)} unexpected present"
                )
            captured_at = parse_ms(manifest.get("captured_at_utc"), "captured_at_utc")
            defects: list[dict[str, Any]] = []
            for open_ms in sorted(rows):
                key = (entry["label"], open_ms)
                if key in seen:
                    duplicate_opens.append(f"{entry['label']}@{iso(open_ms)}")
                seen.add(key)
                original = source.get(open_ms)
                if original is None:
                    defects.append(
                        {"code": "ROW_NOT_IN_STORE", "open_utc": iso(open_ms), "detail": "no such bar in the store"}
                    )
                    continue
                if original[0] != rows[open_ms]:
                    defects.append(
                        {
                            "code": "SOURCE_BYTES_DIVERGED",
                            "open_utc": iso(open_ms),
                            "detail": "the shard line is not the store's line",
                        }
                    )
                    continue
                record = original[1]
                close_ms = open_ms + entry["span"]
                fetched_at = int(record["fetched_at_ms"])
                lag = fetched_at - close_ms
                if open_ms >= at_ms:
                    defects.append({"code": "FUTURE_BAR", "open_utc": iso(open_ms), "detail": "opens after the verification instant"})
                if not bool(record.get("closed")):
                    defects.append({"code": "BAR_NOT_CLOSED", "open_utc": iso(open_ms), "detail": "the store says it is not closed"})
                if prospective and fetched_at < declaration["effective_from"]:
                    defects.append(
                        {
                            "code": "INGESTED_BEFORE_DECLARATION",
                            "open_utc": iso(open_ms),
                            "detail": "stored before the declaration took effect",
                        }
                    )
                if lag < 0:
                    defects.append({"code": "NEGATIVE_LAG", "open_utc": iso(open_ms), "lag_ms": lag, "detail": "stored before it closed"})
                elif lag > entry["lag_bound_ms"]:
                    defects.append(
                        {
                            "code": "LAG_OVER_BOUND",
                            "open_utc": iso(open_ms),
                            "lag_ms": lag,
                            "bound_ms": entry["lag_bound_ms"],
                            "detail": "backfilled: stored later than the declared bound",
                        }
                    )
                if close_ms > captured_at:
                    defects.append(
                        {
                            "code": "BAR_NOT_CLOSED_AT_CAPTURE",
                            "open_utc": iso(open_ms),
                            "detail": "the bar had not closed when the shard was written",
                        }
                    )
                if fetched_at > captured_at:
                    defects.append(
                        {
                            "code": "INGESTED_AFTER_CAPTURE",
                            "open_utc": iso(open_ms),
                            "detail": "the bar was stored after the shard was written",
                        }
                    )
            recomputed_admissible = not defects
            if bool(manifest.get("admissible")) != recomputed_admissible:
                undisclosed.append(
                    f"{entry['label']}@{day}: manifest says admissible={manifest.get('admissible')}, "
                    f"the bytes and the store say {recomputed_admissible}"
                )
            if not recomputed_admissible:
                for defect in defects:
                    open_text = str(defect.get("open_utc") or "")
                    if open_text:
                        inadmissible[(entry["label"], parse_ms(open_text, "open_utc"))] = str(
                            defect["code"]
                        )
            if bool(manifest.get("counts_toward_coverage")) != counts_toward_coverage:
                defects.append(
                    {
                        "code": "COVERAGE_FLAG_DISAGREES",
                        "detail": (
                            f"shard says counts_toward_coverage="
                            f"{manifest.get('counts_toward_coverage')}; this run is "
                            f"{'a rehearsal' if not counts_toward_coverage else 'the phase'}"
                        ),
                    }
                )
            if prospective and manifest.get("prospective") is not True:
                defects.append(
                    {"code": "NOT_PROSPECTIVE", "detail": "a phase shard is not stamped prospective"}
                )
            if manifest.get("declaration", {}).get("sha256") != declaration["sha256"]:
                defects.append(
                    {"code": "DECLARATION_MISMATCH", "detail": "the shard was written under another declaration"}
                )
            admissible = recomputed_admissible and not defects
            days.append(
                {
                    "slice": entry["label"],
                    "day": day,
                    "admissible": admissible,
                    "rows": len(rows),
                    "defects": defects,
                    "payload": payload,
                }
            )
            if admissible:
                summary["admissible_days"] += 1
                summary["rows"] += len(rows)
            else:
                summary["quarantined_days"] += 1
        summaries[entry["label"]] = summary
    problems = [f"{name}: {item}" for name in summaries for item in summaries[name]["problems"]]
    checks.append(
        Check(
            "SHARD_BYTES_MATCH_MANIFESTS",
            not problems,
            "; ".join(problems[:5])
            or (
                "no shard exists yet, so there is nothing to compare"
                if sum(item["shards"] for item in summaries.values()) == 0
                else (
                    f"{sum(item['shards'] for item in summaries.values())} shard(s) hash to their "
                    "manifests and every row is the store's own line"
                )
            ),
        )
    )
    checks.append(
        Check(
            "NO_DUPLICATE_OPENS",
            not duplicate_opens,
            f"{len(duplicate_opens)} repeated open instant(s): {duplicate_opens[:3]}"
            if duplicate_opens
            else "no open instant appears twice across shards",
        )
    )
    distinct = sorted({digest for digest in generators.values() if digest})
    checks.append(
        Check(
            "GENERATOR_CONSISTENT",
            len(distinct) <= 1 and not any(not digest for digest in generators.values()),
            (
                f"{len(distinct)} distinct generator digest(s): {distinct[:3]}"
                if len(distinct) > 1 or any(not d for d in generators.values())
                else "no shard exists yet, so no generator is named"
                if not distinct
                else f"every shard was written by the program whose digest is {distinct[0][:16]}"
            ),
        )
    )
    checks.append(
        Check(
            "QUARANTINE_IS_DISCLOSED",
            not undisclosed,
            "; ".join(undisclosed[:5])
            or (
                f"{sum(1 for item in days if not item['admissible'])} inadmissible day(s) are named "
                "as such by their own manifests"
            ),
        )
    )
    return checks, summaries, days, inadmissible


def check_dataset_temporal(
    claim: dict[str, Any],
    entries: list[dict[str, Any]],
    inadmissible: dict[tuple[str, int], str],
    repo: Path,
) -> list[Check]:
    """No bar in the consolidated dataset may be one the policy rejects.

    This is the control that gives the quarantine its teeth: a day may be written and quarantined,
    but if any of its rows reach the dataset the run is a failure, whatever the manifest says.
    """
    claimed = {item.get("slice"): item for item in (claim.get("consolidation") or {}).get("slices", [])}
    problems: list[str] = []
    rows = 0
    for entry in entries:
        item = claimed.get(entry["label"])
        if item is None:
            continue
        path = repo / str(item.get("path") or "")
        if not path.is_file():
            continue
        for line in path.read_bytes().splitlines():
            if not line.strip():
                continue
            rows += 1
            open_ms = int(json.loads(line)["ts"])
            reason = inadmissible.get((entry["label"], open_ms))
            if reason is not None:
                problems.append(f"{entry['label']}@{iso(open_ms)}: {reason}")
    return [
        Check(
            "TEMPORAL_POLICY_IN_THE_DATASET",
            not problems,
            "; ".join(problems[:5])
            or f"{rows} row(s) in the consolidated dataset: none is future, late, unclosed or unbounded",
        )
    ]


def check_consolidation(
    claim: dict[str, Any], days: list[dict[str, Any]], entries: list[dict[str, Any]], repo: Path
) -> list[Check]:
    """The consolidated dataset must be the shards' own bytes, in the declared order."""
    checks: list[Check] = []
    claimed = {item.get("slice"): item for item in (claim.get("consolidation") or {}).get("slices", [])}
    problems: list[str] = []
    for entry in entries:
        mine = b"".join(
            item["payload"]
            for item in sorted(
                (day for day in days if day["slice"] == entry["label"] and day["admissible"]),
                key=lambda day: day["day"],
            )
        )
        digest = sha256_bytes(mine)
        item = claimed.get(entry["label"])
        if item is None:
            problems.append(f"{entry['label']}: the claim names no consolidation")
            continue
        path = repo / str(item.get("path") or "")
        if not path.is_file():
            problems.append(f"{entry['label']}: {item.get('path')} does not exist")
            continue
        on_disk = path.read_bytes()
        if sha256_bytes(on_disk) != digest:
            problems.append(
                f"{entry['label']}: consolidated hashes to {sha256_bytes(on_disk)[:16]}, "
                f"the shards rebuild to {digest[:16]}"
            )
        if item.get("sha256") != digest:
            problems.append(f"{entry['label']}: the claim's digest is not the digest of the shards")
        if int(item.get("rows", -1)) != sum(
            1 for line in mine.splitlines() if line.strip()
        ):
            problems.append(f"{entry['label']}: the claim's row count is not the payload's")
    checks.append(
        Check(
            "CONSOLIDATED_IS_THE_SHARDS",
            not problems,
            "; ".join(problems[:5]) or "the consolidated dataset rebuilds from the shards byte for byte",
        )
    )
    return checks


def check_coverage(
    claim: dict[str, Any],
    days: list[dict[str, Any]],
    entries: list[dict[str, Any]],
    *,
    at_ms: int,
    window_start: int,
) -> tuple[list[Check], dict[str, Any]]:
    """Recompute coverage from the declaration's denominator and the admissible rows."""
    declared = sum(entry["declared_rows"] for entry in entries)
    admissible = sum(item["rows"] for item in days if item["admissible"])
    required = max((entry["coverage_required"] for entry in entries), default=0.0)
    quarantined = sum(1 for item in days if not item["admissible"])
    if at_ms < window_start:
        status = COVERAGE_PENDING_WINDOW_OPEN
    elif quarantined:
        status = COVERAGE_BELOW_DECLARED
    elif admissible <= 0:
        status = COVERAGE_PENDING
    elif admissible == declared:
        status = COVERAGE_COMPLETE
    else:
        status = COVERAGE_BELOW_DECLARED
    claimed = (claim.get("coverage") or {}).get("status")
    checks = [
        Check(
            "COVERAGE_RECOMPUTED",
            claimed == status,
            f"the claim says {claimed!r}; the declaration and the bytes say {status!r}",
        ),
        Check(
            "COVERAGE_NOT_OVERSTATED",
            not (claimed == COVERAGE_COMPLETE and status != COVERAGE_COMPLETE),
            "a dataset that is not complete is never called complete",
        ),
        Check(
            "DENOMINATOR_IS_THE_DECLARATION",
            (claim.get("coverage") or {}).get("declared_rows") == declared,
            f"declared {declared} row(s) from the declaration; claim says "
            f"{(claim.get('coverage') or {}).get('declared_rows')}",
        ),
    ]
    return checks, {
        "declared_rows": declared,
        "admissible_rows": admissible,
        "quarantined_days": quarantined,
        "fraction": round(admissible / declared, 6) if declared else 0.0,
        "required_fraction": required,
        "status": status,
        "complete": status == COVERAGE_COMPLETE,
    }


def check_package(repo: Path, claim: dict[str, Any]) -> list[Check]:
    """Controls that are about the package rather than about the bytes."""
    checks: list[Check] = []
    builder_source = (repo / BUILDER).read_text(encoding="utf-8")
    gates = claim.get("gates") or {}
    forbidden = [
        token
        for token in ("binance_order", "create_order", "api_key", "secret_key")
        if token in builder_source
    ]
    checks.append(
        Check(
            "BUILDER_CANNOT_TRADE",
            not forbidden,
            f"the builder mentions {forbidden}" if forbidden else "the builder names no order or credential entry point",
        )
    )
    checks.append(
        Check(
            "BUILDER_DID_NOT_CERTIFY",
            claim.get("certifiable") is False
            and str(gates.get("certification")) == "NOT_CLAIMED_BY_BUILDER",
            f"certifiable={claim.get('certifiable')}, certification={gates.get('certification')}",
        )
    )
    checks.append(
        Check(
            "GATES_UNCHANGED",
            gates.get("economic_executions") == "0"
            and gates.get("orders_placed") == "0"
            and gates.get("live_trading") == "DISABLED",
            f"gates: {gates}",
        )
    )
    targets: list[str] = []
    for relative in FROZEN_PREFIXES:
        candidate = repo / relative
        if candidate.is_file():
            targets.append(relative)
        elif candidate.is_dir():
            targets.extend(
                path.relative_to(repo).as_posix()
                for path in sorted(candidate.rglob("*"))
                if path.is_file()
            )
    # Two Git calls rather than two per file: ``ls-tree`` gives the committed blob ids and one
    # ``hash-object --stdin-paths`` gives the working-tree ids, with the repository's own filters
    # applied on both sides so that a CRLF checkout is not reported as drift.
    committed: dict[str, str] = {}
    listing = git(repo, "ls-tree", "-r", "HEAD", "--", *FROZEN_PREFIXES)
    for line in (listing or "").splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) == 3 and path:
            committed[path] = parts[2]
    working: list[str] = []
    if targets:
        try:
            completed = subprocess.run(
                ["git", "hash-object", "--stdin-paths"],
                cwd=str(repo),
                input="\n".join(targets),
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            working = completed.stdout.split() if completed.returncode == 0 else []
        except (OSError, subprocess.TimeoutExpired):
            working = []
    drifted: list[str] = []
    if len(working) != len(targets):
        drifted.append("git could not hash the working tree; the control is unproven")
    else:
        for relative, blob in zip(targets, working, strict=True):
            expected = committed.get(relative)
            if expected is None:
                drifted.append(f"{relative} (absent from HEAD)")
            elif expected != blob:
                drifted.append(relative)
    checks.append(
        Check(
            "FROZEN_PACKAGES_INTACT",
            not drifted,
            (
                f"{len(targets)} frozen path(s) compared with HEAD; drifted: {drifted[:5]}"
                if drifted
                else f"{len(targets)} path(s) of WP-051-02B..02F are byte-identical to HEAD"
            ),
        )
    )
    # Read the import graph, not the prose: a docstring that mentions ``trading_bot`` is a
    # sentence about independence, not a dependency.
    imported: set[str] = set()
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    offending = sorted(
        name
        for name in imported
        if name.split(".")[0] == "trading_bot"
        or "incremental" in name
        or "exp004a_wp051_02g_capture" in name
    )
    checks.append(
        Check(
            "VERIFIER_IS_INDEPENDENT",
            not offending,
            "the verifier imports neither the builder, the engine nor trading_bot"
            if not offending
            else f"the verifier imports {offending}",
        )
    )
    return checks


# --------------------------------------------------------------------------- #
# verdict
# --------------------------------------------------------------------------- #


def verify(
    *,
    repo: Path,
    declaration_path: Path,
    claim: dict[str, Any],
    at_ms: int,
    rehearsal: bool,
    shard_root: Path | None = None,
) -> dict[str, Any]:
    declaration = read_declaration(repo, declaration_path)
    prospective = not rehearsal
    checks: list[Check] = []
    if rehearsal:
        if declaration["rehearsal"] is None:
            raise ValueError("the claim is a rehearsal and the declaration defines none")
        start = parse_ms(declaration["rehearsal"]["start_utc"], "rehearsal.start_utc")
        end = parse_ms(declaration["rehearsal"]["end_utc"], "rehearsal.end_utc")
        counts = bool(declaration["rehearsal"].get("counts_toward_coverage", False))
        root = shard_root or (
            declaration["declaration_root"] / str(declaration["rehearsal"]["shard_root"])
        ).resolve()
        # The rehearsal window is taken as given. Clamping it to the phase's period would make a
        # rehearsal that predates the window empty, and a verifier that says "nothing is missing"
        # about an empty grid is the failure mode this package exists to avoid.
        entries = []
        for entry in declaration["entries"]:
            grid = expected_opens(start, end, entry["span"])
            entries.append(
                {
                    **entry,
                    "start": start,
                    "end": end,
                    "grid": grid,
                    "declared_rows": len(grid),
                    "label": f"{entry['interval']}:{entry['asset']}",
                }
            )
        window_start = start
    else:
        counts = True
        root = shard_root or declaration["shard_root"]
        if root is None:
            raise ValueError("the declaration names no shard root")
        entries = declaration["entries"]
        window_start = declaration["window_start"]
    checks.extend(
        check_declaration(
            declaration,
            claim,
            prospective=prospective,
            repo=repo,
            declaration_rel=relative(declaration_path, repo),
        )
    )
    shard_checks, summaries, days, inadmissible = verify_shards(
        root,
        declaration,
        entries,
        at_ms=at_ms,
        prospective=prospective,
        counts_toward_coverage=counts,
    )
    checks.extend(shard_checks)
    checks.extend(check_consolidation(claim, days, entries, repo))
    checks.extend(check_dataset_temporal(claim, entries, inadmissible, repo))
    coverage_checks, coverage = check_coverage(
        claim, days, entries, at_ms=at_ms, window_start=window_start
    )
    checks.extend(coverage_checks)
    checks.extend(check_package(repo, claim))
    failed = [check for check in checks if not check.ok and not check.advisory]
    if failed:
        verdict = "FAIL"
    elif coverage["status"] == COVERAGE_COMPLETE:
        verdict = "PASS_COVERAGE_COMPLETE"
    elif coverage["status"] == COVERAGE_PENDING_WINDOW_OPEN:
        verdict = "PASS_PENDING_WINDOW_OPEN"
    else:
        verdict = "PASS_COVERAGE_INCOMPLETE"
    # A rehearsal can be complete and still certify nothing: its bytes are historical. The word
    # "allowed" is reserved for a prospective window whose every declared bar checks out.
    if failed:
        blocked_by = "FAILED_CHECKS"
    elif rehearsal:
        blocked_by = "REHEARSAL_IS_NOT_EVIDENCE"
    elif coverage["status"] != COVERAGE_COMPLETE:
        blocked_by = f"COVERAGE_{coverage['status']}"
    else:
        blocked_by = None
    return {
        "schema_version": SCHEMA_VERSION,
        "verifier": VERIFIER_ID,
        "package": "WP-051-02G",
        "verdict": verdict,
        "independent_verification": "PASS" if not failed else "FAIL",
        "certification_allowed": not failed
        and coverage["status"] == COVERAGE_COMPLETE
        and not rehearsal,
        "certification_blocked_by": blocked_by,
        "experiment_certified": False,
        "rehearsal": rehearsal,
        "prospective": prospective,
        "at_utc": iso(at_ms),
        "claim_run_id": claim.get("run_id"),
        "declaration": {
            "path": str(declaration_path),
            "code_commit": (declaration.get("generator") or {}).get("code_commit"),
            "declaration_id": declaration["declaration_id"],
            "sha256": declaration["sha256"],
            "window": {"start_utc": iso(declaration["window_start"]), "end_utc": iso(declaration["window_end"])},
        },
        "shard_root": str(root),
        "shards": summaries,
        "coverage": coverage,
        "checks": [check.as_dict() for check in checks],
        "check_count": len(checks),
        "failed_checks": [check.name for check in failed],
        "note": (
            "independent_verification speaks about the bytes and the manifests. It is not a "
            "certification, and certification_allowed is true only when coverage is complete."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--claim", type=Path, required=True, help="the RUN_REPORT.json to verify")
    parser.add_argument("--declaration", type=Path, default=None)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--out", type=Path, default=None, help="write the verdict here")
    parser.add_argument("--rehearsal", action="store_true")
    parser.add_argument("--shard-root", type=Path, default=None)
    parser.add_argument("--as-of", default=None)
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    declaration_path = (args.declaration or repo / DECLARATION).resolve()
    claim = read_json(args.claim)
    if not isinstance(claim, dict):
        print(json.dumps({"ok": False, "error": f"{args.claim} is not a claim"}, sort_keys=True))
        return EXIT_ERROR
    at_ms = parse_ms(args.as_of, "--as-of") if args.as_of else now_ms()
    try:
        verdict = verify(
            repo=repo,
            declaration_path=declaration_path,
            claim=claim,
            at_ms=at_ms,
            rehearsal=args.rehearsal,
            shard_root=args.shard_root.resolve() if args.shard_root else None,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(json.dumps({"ok": False, "error": f"{type(error).__name__}: {error}"}, sort_keys=True))
        return EXIT_ERROR
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        "ok": verdict["independent_verification"] == "PASS",
        "verdict": verdict["verdict"],
        "checks": verdict["check_count"],
        "failed": verdict["failed_checks"],
        "coverage": verdict["coverage"]["status"],
        "certification_allowed": verdict["certification_allowed"],
        "certification_blocked_by": verdict["certification_blocked_by"],
        "out": str(args.out) if args.out else None,
    }
    print(json.dumps(summary, sort_keys=True))
    if verdict["verdict"] == "FAIL":
        return EXIT_FAIL
    # The exit code is about the claim, not about the experiment: a complete rehearsal verifies,
    # and it still certifies nothing (``certification_allowed`` says so in the JSON).
    return EXIT_PASS if verdict["verdict"] == "PASS_COVERAGE_COMPLETE" else EXIT_INCOMPLETE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
