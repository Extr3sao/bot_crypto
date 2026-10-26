"""ST-6 — what Windows itself says about the scheduled runs, read without changing the host.

RFC-047 separates three planes of evidence.  The market data and the run log are produced by the
program under test; this module reads the third plane, which is *not*: the event records the Task
Scheduler provider writes to the Windows Event Log.  Its only job is to bring those records into the
repository durably, so that a claim of "the schedule ran" can rest on something other than the
program's own account of itself.

What this module refuses to do, on purpose:

* it never writes to the Event Log — the single configuration change RFC-047 contemplates
  (``wevtutil sl ... /e:true``) is not issued from here, it is a host gate with its own approval and
  its own recorded preflight and postflight;
* it never treats the candidate event identifiers as if their meaning were known.  ``100``, ``102``,
  ``107``, ``110``, ``200`` and ``201`` are the identifiers the request names as *candidates*; on
  this host no record carrying any of them exists in a channel this session can read, so their
  semantics are recorded as unverified rather than assumed, and classification is driven by the
  fields of a record, never by its number alone;
* it never drops a record it could not read without saying so: an unparseable fragment, a refused
  query and a rotated range all leave a trace in the live state beside the immutable store;
* it never advances the watermark before the records behind it are on disk.

The store is bounded and append-only: one normalised record per (channel, EventRecordID), deduplicated
on write.  The watermark, the attempt log, the refusals and the measured growth are live state and
live in a separate document, so that immutable evidence and mutable state are never mixed.

Run:  python scripts/st6_windows_events.py --audit     (host audit: channel, permissions, gate)
      python scripts/st6_windows_events.py --ingest    (read past the watermark, persist, advance)
      python scripts/st6_windows_events.py --status    (the evidence document over the store)
      python scripts/st6_windows_events.py --all
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ElementTree
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from st6_scheduler_evidence import read_json, read_jsonl  # noqa: E402  the shared readers

DATA = REPO / "data" / "st6"
RFC047_DIR = DATA / "rfc047"
EVENT_STORE = RFC047_DIR / "WINDOWS_EVENTS.jsonl"
LIVE_STATE = RFC047_DIR / "WINDOWS_EVENT_LIVE_STATE.json"
EVIDENCE_JSON = DATA / "RFC047_WINDOWS_EVENT_EVIDENCE.json"
HOST_AUDIT_JSON = DATA / "RFC047_HOST_AUDIT.json"
SEMANTICS_JSON = RFC047_DIR / "EVENT_SEMANTICS.json"
PERIOD_PATH = DATA / "ST6_PERIOD.json"
TASK_NAME = "TradingAgentic-ST6-Forward"

STORE_VERSION = "RFC047_WIN_EVENT_STORE_V1"
AUDIT_VERSION = "RFC047_HOST_AUDIT_V1"
EVIDENCE_VERSION = "RFC047_WINDOWS_EVENT_EVIDENCE_V1"

CHANNEL_OPERATIONAL = "Microsoft-Windows-TaskScheduler/Operational"
CHANNEL_MAINTENANCE = "Microsoft-Windows-TaskScheduler/Maintenance"
CHANNELS = (CHANNEL_OPERATIONAL, CHANNEL_MAINTENANCE)
#: The identifiers the request names as candidates.  They are read as *candidates*: nothing here
#: assigns them a meaning, because none of them could be checked against a real record of this host.
CANDIDATE_EVENT_IDS = (100, 102, 107, 110, 200, 201)

#: The channel states, and the states of the proof that this session may offer.
CHANNEL_AVAILABLE = "CHANNEL_AVAILABLE"
CHANNEL_DISABLED = "CHANNEL_DISABLED"
CHANNEL_UNREADABLE = "CHANNEL_UNREADABLE"
CHANNEL_MISSING = "CHANNEL_MISSING"
CHANNEL_ENABLED_AWAITING_REAL_EVENT = "CHANNEL_ENABLED_AWAITING_REAL_EVENT"
HOST_AUDIT_CHANGE_APPROVAL_REQUIRED = "HOST_AUDIT_CHANGE_APPROVAL_REQUIRED"
CHANNEL_DISABLED_NO_RECORDS = "CHANNEL_DISABLED_NO_RECORDS"
NO_RECORDS_MATCHING_THE_TASK = "NO_RECORDS_MATCHING_THE_TASK"
RECORDS_INGESTED = "RECORDS_INGESTED"
ROTATION_DETECTED = "ROTATION_DETECTED"
RECORD_ID_RESET_DETECTED = "RECORD_ID_RESET_DETECTED"
QUERY_REFUSED = "QUERY_REFUSED"
QUERY_TIMED_OUT = "QUERY_TIMED_OUT"
WEVTUTIL_NOT_AVAILABLE = "WEVTUTIL_NOT_AVAILABLE"
UNPARSEABLE_RECORD = "UNPARSEABLE_RECORD"

#: How long a query may take before it is abandoned.  A tick of the forward monitor runs every
#: fifteen minutes and must not be blocked by this reading failing.
DEFAULT_QUERY_TIMEOUT_S = 20
#: How many records a single read pulls.  The bound is deliberate: the store must not be fed by an
#: export of the whole log, and a run that needs more than this continues on the next read.
MAX_RECORDS_PER_READ = 400
#: A completion event may be written after the process it describes has exited.
COMPLETION_GRACE_S = 2 * 15 * 60
#: The original fragment is kept beside the record up to this size, so that the hash of the evidence
#: can be recomputed by a program that did not write it.  A larger fragment is counted and its
#: absence is recorded rather than the store growing without a bound.
MAX_STORED_XML_BYTES = 8192


def _utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(stamp: str) -> datetime:
    text = str(stamp)
    if "." in text:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


#: A Windows instant carries as many fractional digits as it likes — the provider writes seven
#: hundred-nanosecond ticks, so the fraction cannot be handed to a parser that accepts six.
_INSTANT = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.(\d+))?Z?$")


def parse_window_instant(text: str) -> tuple[datetime, bool]:
    """Parse an event instant, and say whether it came with a zone at all.

    The fraction is truncated to microseconds rather than rejected: a value the provider wrote with
    seven digits is a valid instant, and refusing it would lose the only field that correlates a
    record with a run.
    """
    match = _INSTANT.match(str(text).strip())
    if not match:
        raise ValueError(f"{text!r} is not an instant")
    day, clock, fraction = match.groups()
    micro = int((fraction or "0")[:6].ljust(6, "0"))
    moment = datetime.strptime(f"{day}T{clock}", "%Y-%m-%dT%H:%M:%S").replace(
        microsecond=micro, tzinfo=UTC
    )
    return moment, bool(str(text).strip().endswith("Z"))


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def host_offset_minutes(now: datetime | None = None) -> int:
    """The host's offset from UTC, taken from the clock rather than assumed."""
    moment = now or datetime.now(UTC)
    return int((moment.astimezone().utcoffset() or timedelta()).total_seconds() // 60)


def write_json_atomic(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


# ---------------------------------------------------------------------------------------------
# the host: what wevtutil answers, captured verbatim and parsed as text
# ---------------------------------------------------------------------------------------------


def run_wevtutil(arguments: list[str], timeout_s: int = DEFAULT_QUERY_TIMEOUT_S) -> dict[str, Any]:
    """Run one read-only wevtutil command and keep its answer verbatim.

    ``stdout`` and ``stderr`` are returned as well as the exit status, because the difference between
    "the channel holds no such record" and "the channel refused to answer" is exactly the difference
    between an absence that may be claimed and one that may not.
    """
    command = ["wevtutil", *arguments]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout_s, check=False
        )
    except FileNotFoundError:
        return {
            "command": command,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "status": WEVTUTIL_NOT_AVAILABLE,
        }
    except subprocess.TimeoutExpired:
        return {
            "command": command,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "status": QUERY_TIMED_OUT,
            "timeout_s": timeout_s,
        }
    return {
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "status": "OK" if completed.returncode == 0 else QUERY_REFUSED,
    }


def parse_channel_config(text: str) -> dict[str, Any]:
    """Parse ``wevtutil gl`` output: the channel's own declaration of itself."""
    flat: dict[str, Any] = {}
    for line in str(text).splitlines():
        stripped = line.strip()
        if not stripped or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        flat[key.strip()] = value.strip()
    if not flat:
        return {"parsed": False}
    config: dict[str, Any] = {
        "parsed": True,
        "name": flat.get("name"),
        "enabled": flat.get("enabled") == "true",
        "enabled_raw": flat.get("enabled"),
        "type": flat.get("type"),
        "owning_publisher": flat.get("owningPublisher"),
        "isolation": flat.get("isolation"),
        "channel_access_sddl": flat.get("channelAccess"),
        "log_file_name": flat.get("logFileName"),
        # `retention: false` is the circular policy: the oldest record is overwritten rather than
        # the log being backed up, which is why the system's own history cannot be the durable record
        "retention": flat.get("retention"),
        "auto_backup": flat.get("autoBackup"),
    }
    for key, field in (("maxSize", "max_size_bytes"),):
        try:
            config[field] = int(flat.get(key, ""))
        except ValueError:
            config[field] = None
    return config


def parse_log_info(text: str) -> dict[str, Any]:
    """Parse ``wevtutil gli`` output: how much of the log is still there."""
    flat: dict[str, str] = {}
    for line in str(text).splitlines():
        stripped = line.strip()
        if not stripped or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        flat[key.strip()] = value.strip()
    info: dict[str, Any] = {
        "parsed": bool(flat),
        "file_size_bytes": _maybe_int(flat.get("fileSize")),
        "records_present": _maybe_int(flat.get("numberOfLogRecords")),
        "oldest_record_number": _maybe_int(flat.get("oldestRecordNumber")),
        "creation_time_utc": flat.get("creationTime"),
        "last_write_time_utc": flat.get("lastWriteTime"),
    }
    return info


def _maybe_int(value: str | None) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _sddl_allows_read(channel_access: str | None, group_sids: dict[str, bool]) -> dict[str, Any]:
    """What the channel's own access control list grants this session.

    The list is read, not modified, and only the read bit is interpreted.  A grant to *Interactive
    Users* is what makes a read possible without an administrator; changing the channel's
    configuration is a different right, and on this host it is not granted.
    """
    text = str(channel_access or "")
    return {
        "readable_by_this_session": bool(group_sids.get("interactive") or group_sids.get("admin")),
        "read_grant_present": "0x3;;;IU" in text or "0x1;;;IU" in text,
        "write_grant_to_this_session": bool(group_sids.get("admin")),
        "administrators_grant_present": "0x7;;;BA" in text,
        "source": "the channel's channelAccess attribute, read from wevtutil gl",
    }


def effective_user(now: datetime | None = None) -> dict[str, Any]:
    """Who this session is, and whether that identity is in the administrator group."""
    name = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    domain = os.environ.get("USERDOMAIN") or ""
    probe = run_wevtutil(["gli", CHANNEL_MAINTENANCE], timeout_s=10)
    is_admin: bool | None = None
    if sys.platform == "win32":
        try:
            import ctypes

            is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:  # pragma: no cover - the host's own answer, not reproducible off it
            is_admin = None
    return {
        "user": f"{domain}\\{name}" if domain else name or None,
        "is_administrator_token": is_admin,
        "read_probe_status": probe["status"],
        "read_probe_exit_code": probe["exit_code"],
        "as_of_utc": _utc() if now is None else now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def group_sids() -> dict[str, bool]:
    """The two groups that matter for this decision, as the host reports them."""
    if sys.platform != "win32":
        return {"interactive": False, "admin": False}
    try:
        import ctypes

        admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # pragma: no cover - the host's own answer
        admin = False
    return {"interactive": True, "admin": admin}


def disk_capacity(path: Path) -> dict[str, Any]:
    """Free space on the volume the log lives on, so a bounded store can be shown to fit."""
    try:
        import shutil

        probe = path if path.exists() else path.parent
        usage = shutil.disk_usage(str(probe))
    except OSError:
        return {"measured": False}
    return {
        "measured": True,
        "total_bytes": usage.total,
        "free_bytes": usage.free,
        "used_percent": round(100 * usage.used / usage.total, 1) if usage.total else None,
    }


# ---------------------------------------------------------------------------------------------
# the records: XML in, normalised evidence out
# ---------------------------------------------------------------------------------------------


def split_events(text: str) -> list[str]:
    """The ``<Event>`` elements of a ``wevtutil qe /f:xml`` answer.

    The answer is a concatenation of sibling elements with no wrapping document, so it cannot be
    handed to a parser as it stands.  Event elements do not nest, which is what makes slicing them
    out by their own tags safe here; anything that is not a complete element is returned as a
    fragment too, so that a truncated answer is *visible* instead of silently shortening the record.
    """
    body = str(text)
    complete = [match.group(0) for match in re.finditer(r"<Event\b.*?</Event>", body, re.DOTALL)]
    if complete:
        return complete
    return [body.strip()] if body.strip() else []


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(element: ElementTree.Element, *path: str) -> ElementTree.Element | None:
    """Find by local name, whatever namespace the record happens to declare."""
    node: ElementTree.Element | None = element
    for step in path:
        if node is None:
            return None
        node = next(
            (child for child in node if _strip_ns(child.tag) == step),
            None,
        )
    return node


def _text(element: ElementTree.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def _event_data(element: ElementTree.Element) -> dict[str, str]:
    data: dict[str, str] = {}
    container = _find(element, "EventData") or _find(element, "UserData")
    if container is None:
        return data
    for child in container.iter():
        if _strip_ns(child.tag) == "Data" and child.attrib.get("Name"):
            data[child.attrib["Name"]] = (child.text or "").strip()
    return data


def _attribute(element: ElementTree.Element | None, name: str) -> str | None:
    if element is None:
        return None
    return element.attrib.get(name)


def _normalise_instant(raw: str | None, host_offset_minutes_: int | None) -> tuple[str | None, str]:
    """A record's instant in UTC, with the basis it was read on.

    ``System/TimeCreated/@SystemTime`` is documented as UTC and this host's own newest record was
    checked against the wall clock before it was trusted; a value that carries no zone is read as
    this host's local time and converted, never labelled UTC on the strength of its spelling.
    """
    text = (raw or "").strip()
    if not text:
        return None, "ABSENT"
    try:
        moment, had_zone = parse_window_instant(text)
    except ValueError:
        pass
    else:
        if had_zone:
            return moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "SYSTEM_TIME_UTC"
        offset = host_offset_minutes_ or 0
        return (
            (moment.replace(tzinfo=None) - timedelta(minutes=offset)).strftime(
                "%Y-%m-%dT%H:%M:%S.%fZ"
            ),
            "RELABELLED_FROM_LOCAL",
        )
    return text, "UNPARSED"


def normalise_event(
    fragment: str,
    channel: str,
    collected_at_utc: str,
    host_offset_minutes_: int | None,
    task_name: str = TASK_NAME,
) -> dict[str, Any]:
    """One raw ``<Event>`` fragment as a normalised record, or a refusal that names the reason.

    The record is kept whatever its identifier is: the identifier alone is not allowed to decide
    whether the record matters, because on this host the identifiers that were named as candidates
    could not be checked against a single real record.
    """
    try:
        element = ElementTree.fromstring(fragment)
    except ElementTree.ParseError as failure:
        return {
            "status": UNPARSEABLE_RECORD,
            "reason": str(failure),
            "event_xml_sha256": _sha256_text(fragment),
            "channel": channel,
            "collected_at_utc": collected_at_utc,
            "excerpt": fragment[:200],
        }
    system = _find(element, "System")
    provider = _find(system, "Provider") if system is not None else None
    time_created = _find(system, "TimeCreated") if system is not None else None
    correlation = _find(system, "Correlation") if system is not None else None
    execution = _find(system, "Execution") if system is not None else None
    data = _event_data(element)
    instant, basis = _normalise_instant(
        _attribute(time_created, "SystemTime"), host_offset_minutes_
    )
    record_id = _maybe_int(_text(_find(system, "EventRecordID"))) if system is not None else None
    event_id = _maybe_int(_text(_find(system, "EventID"))) if system is not None else None
    raw_task = data.get("TaskName") or data.get("Path") or _text(_find(element, "TaskName")) or None
    return {
        "status": "OK",
        "store_version": STORE_VERSION,
        "provider_name": _attribute(provider, "Name"),
        "provider_guid": _attribute(provider, "Guid"),
        "channel": _text(_find(system, "Channel")) if system is not None else channel,
        "queried_channel": channel,
        "event_id": event_id,
        "event_record_id": record_id,
        "event_timestamp_utc": instant,
        "event_timestamp_basis": basis,
        "event_timestamp_raw": _attribute(time_created, "SystemTime"),
        "computer": _text(_find(system, "Computer")) if system is not None else None,
        "task_full_path": raw_task,
        "task_name": raw_task.rsplit("\\", 1)[-1] if raw_task else None,
        "belongs_to_the_monitored_task": bool(
            raw_task and str(raw_task).rsplit("\\", 1)[-1] == task_name
        ),
        "instance_id": _attribute(correlation, "ActivityID") or data.get("InstanceId"),
        "activity_id": _attribute(correlation, "ActivityID"),
        "action_path": data.get("ActionName") or data.get("Path"),
        "process_id": _maybe_int(_attribute(execution, "ProcessID")),
        "thread_id": _maybe_int(_attribute(execution, "ThreadID")),
        "result_code": data.get("ResultCode") or data.get("resultCode"),
        "level": _maybe_int(_text(_find(system, "Level"))) if system is not None else None,
        "event_data_keys": sorted(data),
        "event_xml_sha256": _sha256_text(fragment),
        "event_xml_bytes": len(fragment.encode("utf-8")),
        # the evidence itself, so the hash above is checkable by a reader rather than only assertable
        "event_xml": fragment if len(fragment.encode("utf-8")) <= MAX_STORED_XML_BYTES else None,
        "event_xml_kept": len(fragment.encode("utf-8")) <= MAX_STORED_XML_BYTES,
        "collected_at_utc": collected_at_utc,
        "identifier_is_a_named_candidate": bool(event_id in CANDIDATE_EVENT_IDS),
        "identifier_semantics": (
            "unverified on this host: no record carrying this identifier exists in any channel this "
            "session can read, so the record is classified by its fields alone"
        ),
    }


def event_key(record: dict[str, Any]) -> str:
    """The identity a duplicate would collide on."""
    return f"{record.get('channel')}#{record.get('event_record_id')}"


def semantics_status(
    store_rows: list[dict[str, Any]] | None = None, path: Path | None = None
) -> dict[str, Any]:
    """Whether the meaning of the event identifiers has been established on *this* host.

    The request names six identifiers as candidates and requires their real meaning to be verified
    against the Windows actually installed before they are turned into classification rules.  No
    program here may declare that meaning by itself, so a declaration only counts when it quotes a
    record that is really in the store: a hand-written file cannot promote an absence into an
    observation, and the classification that depends on it stays partial until a real record exists.
    """
    rows = store_rows if store_rows is not None else load_store()
    declaration = read_json(path or SEMANTICS_JSON)
    if not declaration:
        return {
            "state": "NOT_VERIFIED_ON_THIS_HOST",
            "declaration": None,
            "rules": None,
            "reason": (
                "no declaration of the identifiers' meaning exists for this host, and none may be "
                "invented here: the identifiers are read as candidates and a record is classified "
                "by its fields"
            ),
            "declaration_path": str(SEMANTICS_JSON.relative_to(REPO)).replace("\\", "/"),
        }
    quoted = declaration.get("verified_against") or {}
    channel = quoted.get("channel")
    record_id = quoted.get("event_record_id")
    witness = [
        row
        for row in rows
        if row.get("channel") == channel and row.get("event_record_id") == record_id
    ]
    if not witness:
        return {
            "state": "NOT_VERIFIED_ON_THIS_HOST",
            "declaration": declaration,
            "rules": None,
            "reason": (
                "the declaration quotes a record that is not in the store, so it is not evidence of "
                "anything: a meaning is only accepted once it can be checked against a record that "
                "really exists"
            ),
            "declaration_path": str(SEMANTICS_JSON.relative_to(REPO)).replace("\\", "/"),
        }
    return {
        "state": "VERIFIED_ON_THIS_HOST",
        "declaration": declaration,
        "rules": declaration.get("rules") or {},
        "verified_against_event_record_id": record_id,
        "verified_against_channel": channel,
        "reason": (
            "the meaning of the identifiers was declared after reading a real record of this host, "
            "and that record is in the store"
        ),
        "declaration_path": str(SEMANTICS_JSON.relative_to(REPO)).replace("\\", "/"),
    }


def read_channel_records(
    channel: str,
    since_record_id: int | None,
    collected_at_utc: str,
    host_offset_minutes_: int | None,
    limit: int = MAX_RECORDS_PER_READ,
    newest_first: bool = False,
) -> dict[str, Any]:
    """Read the channel past a watermark, oldest first, and normalise what comes back.

    The filter is by ``EventRecordID`` rather than by identifier, so the read does not depend on the
    candidate identifiers being the right ones.  Records that belong to another task are counted and
    not persisted: the store holds what ST-6 needs, never an export of the log.
    """
    # ``/rd:false`` walks forward from the oldest record, which is what makes an incremental read by
    # EventRecordID complete; the audit asks the opposite question — what is the newest record — and
    # reads its answer off the same code path rather than a second one
    arguments = [
        "qe",
        channel,
        "/f:xml",
        f"/c:{int(limit)}",
        f"/rd:{'true' if newest_first else 'false'}",
    ]
    if since_record_id is not None:
        arguments.append(f"/q:*[System[(EventRecordID > {int(since_record_id)})]]")
    answer = run_wevtutil(arguments)
    records: list[dict[str, Any]] = []
    refusals: list[dict[str, Any]] = []
    if answer["status"] != "OK":
        return {
            "channel": channel,
            "status": answer["status"],
            "exit_code": answer["exit_code"],
            "stderr": (answer["stderr"] or "").strip()[:400],
            "records": [],
            "refusals": [],
            "bytes_read": len(answer["stdout"]),
        }
    for fragment in split_events(answer["stdout"]):
        record = normalise_event(fragment, channel, collected_at_utc, host_offset_minutes_)
        if record["status"] == "OK":
            records.append(record)
        else:
            refusals.append(record)
    return {
        "channel": channel,
        "status": "OK" if records or not refusals else UNPARSEABLE_RECORD,
        "exit_code": answer["exit_code"],
        "stderr": (answer["stderr"] or "").strip()[:400],
        "records": records,
        "refusals": refusals,
        "bytes_read": len(answer["stdout"]),
    }


def time_basis_check(
    newest_event_utc: str | None, now: datetime, host_offset_minutes_: int | None
) -> dict[str, Any]:
    """Is the channel's clock the same clock as the wall clock?

    A log cannot contain a record written in the future.  If its newest record sits ahead of the
    wall clock by about the host's offset, the value was rendered in local time and mislabelled UTC,
    and correlation against it would move every match by hours — so the check is recorded, and a
    suspect basis travels with the arithmetic that uses the instants.
    """
    offset = host_offset_minutes_ or 0
    if not newest_event_utc:
        return {"status": "NO_RECORD_TO_CHECK", "host_offset_minutes": offset}
    try:
        moment, had_zone = parse_window_instant(newest_event_utc)
    except ValueError:
        return {"status": "UNPARSEABLE", "host_offset_minutes": offset}
    if not had_zone:
        return {
            "status": "SUSPECT_LOCAL_LABELLED_UTC",
            "newest_event_utc": newest_event_utc,
            "host_offset_minutes": offset,
            "reading": (
                "the record carries no zone of its own, so its instant is read as this host's "
                "local time and converted rather than trusted as UTC"
            ),
        }
    delta = (moment - now).total_seconds()
    if delta > 60:
        status = "SUSPECT_LOCAL_LABELLED_UTC"
    elif delta > -max(3600, abs(offset) * 60 * 2):
        status = "CONSISTENT_WITH_UTC"
    else:
        status = "STALE_LOG"
    return {
        "status": status,
        "newest_event_utc": newest_event_utc,
        "seconds_ahead_of_the_wall_clock": round(delta, 1),
        "host_offset_minutes": offset,
        "reading": (
            "the newest record is not in the future, so the instants of this channel are UTC as "
            "they claim to be"
            if status == "CONSISTENT_WITH_UTC"
            else (
                "the newest record lies ahead of the wall clock, which is impossible for a record "
                "already written: the instants are read as this host's local time and converted"
                if status == "SUSPECT_LOCAL_LABELLED_UTC"
                else "the channel's newest record is old, so its instants say nothing about now"
            )
        ),
    }


# ---------------------------------------------------------------------------------------------
# the store: bounded, deduplicated, append-only, and advanced only after a durable write
# ---------------------------------------------------------------------------------------------


def load_store(path: Path | None = None) -> list[dict[str, Any]]:
    return read_jsonl(path or EVENT_STORE)


def store_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = event_key(row)
        index[key] = row
    return index


def load_live_state(path: Path | None = None) -> dict[str, Any]:
    return read_json(path or LIVE_STATE) or {}


def append_records(new_records: list[dict[str, Any]], path: Path | None = None) -> dict[str, Any]:
    """Add records to the store atomically: the whole file is rewritten through a temporary.

    An append that is interrupted mid-line would leave a store whose last line is unreadable, and a
    reader that skipped it would silently lose the record.  Rewriting through a temporary in the same
    directory means a reader sees either the previous store or the new one.
    """
    target = path or EVENT_STORE
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = load_store(target)
    index = store_index(existing)
    added: list[str] = []
    for record in new_records:
        key = event_key(record)
        if key in index:
            continue
        index[key] = record
        added.append(key)
    merged = sorted(
        index.values(),
        key=lambda row: (
            str(row.get("channel") or ""),
            int(row.get("event_record_id") or 0),
        ),
    )
    payload = "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in merged)
    temporary = target.with_suffix(target.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)
    return {
        "records_total": len(merged),
        "records_added": len(added),
        "added_keys": added,
        "store_bytes": len(payload.encode("utf-8")),
    }


def ingest(
    now: datetime | None = None,
    store_path: Path | None = None,
    live_path: Path | None = None,
    channels: tuple[str, ...] = CHANNELS,
    limit: int = MAX_RECORDS_PER_READ,
) -> dict[str, Any]:
    """One read past the watermark, per channel, with the failure modes recorded as they happen."""
    moment = now or datetime.now(UTC)
    collected_at = moment.strftime("%Y-%m-%dT%H:%M:%SZ")
    offset = host_offset_minutes(moment)
    live = load_live_state(live_path)
    store = load_store(store_path)
    index = store_index(store)
    attempt: dict[str, Any] = {
        "attempted_at_utc": collected_at,
        "host_offset_minutes": offset,
        "channels": {},
        "records_added": 0,
        "status": RECORDS_INGESTED,
    }
    pending: list[dict[str, Any]] = []
    for channel in channels:
        config = parse_channel_config(run_wevtutil(["gl", channel])["stdout"])
        info = parse_log_info(run_wevtutil(["gli", channel])["stdout"])
        watermark = (live.get("watermarks") or {}).get(channel)
        report: dict[str, Any] = {
            "channel": channel,
            "enabled": config.get("enabled"),
            "config_parsed": config.get("parsed") is True,
            "records_present": info.get("records_present"),
            "oldest_record_number": info.get("oldest_record_number"),
            "watermark_before": watermark,
            "status": None,
            "records_added": 0,
            "records_seen": 0,
            "records_not_belonging_to_the_task": 0,
            "refusals": [],
        }
        read = read_channel_records(channel, watermark, collected_at, offset, limit=limit)
        report["exit_code"] = read.get("exit_code")
        report["stderr"] = read.get("stderr")
        report["bytes_read"] = read.get("bytes_read")
        report["refusals"] = read["refusals"]
        if read["status"] != "OK":
            report["status"] = read["status"]
            attempt["channels"][channel] = report
            continue
        records = read["records"]
        report["records_seen"] = len(records)
        ours = [row for row in records if row.get("belongs_to_the_monitored_task")]
        report["records_not_belonging_to_the_task"] = len(records) - len(ours)
        report["time_basis"] = time_basis_check(
            records[-1]["event_timestamp_utc"] if records else None, moment, offset
        )
        duplicates = [event_key(row) for row in ours if event_key(row) in index]
        report["duplicates_already_stored"] = len(duplicates)
        fresh = [row for row in ours if event_key(row) not in index]
        for row in fresh:
            index[event_key(row)] = row
        pending.extend(fresh)
        # rotation and reset: the log's own numbers say whether a range was overwritten before it
        # could be read.  Neither is an absence of the schedule; both are absences of the record.
        oldest = info.get("oldest_record_number")
        if watermark is not None and oldest is not None and oldest > watermark + 1:
            report["gap"] = {
                "status": ROTATION_DETECTED,
                "first_record_never_read": watermark + 1,
                "oldest_still_present": oldest,
                "records_lost_to_rotation": oldest - (watermark + 1),
            }
        highest = max((int(row.get("event_record_id") or 0) for row in records), default=0)
        if watermark is not None and highest and highest < watermark:
            report["gap"] = {
                "status": RECORD_ID_RESET_DETECTED,
                "watermark_before": watermark,
                "highest_record_seen": highest,
                "reading": (
                    "the channel's identifiers restarted below the watermark, so the log was "
                    "cleared; the watermark is kept as the highest identifier ever durably stored, "
                    "and the discontinuity is recorded instead of being smoothed away"
                ),
            }
        if not records and not report["refusals"]:
            report["status"] = (
                CHANNEL_DISABLED_NO_RECORDS
                if config.get("enabled") is False
                else NO_RECORDS_MATCHING_THE_TASK
            )
        else:
            report["status"] = RECORDS_INGESTED if fresh else NO_RECORDS_MATCHING_THE_TASK
        oldest_present = info.get("oldest_record_number")
        present = info.get("records_present")
        report["oldest_record_number"] = oldest_present
        report["pending_records_estimate"] = (
            max(0, oldest_present + present - 1 - watermark)
            if (watermark is not None and oldest_present is not None and present is not None)
            else None
        )
        # An unreadable fragment is *not* an examined record.  Advancing the watermark over it would
        # step past a record of this task's that was never read, and the step would be invisible
        # afterwards; holding the watermark back re-reads the same range on the next attempt and the
        # deduplication on write makes that free.
        if report["refusals"]:
            report["watermark_held_back"] = {
                "reason": f"{len(report['refusals'])} fragment(s) of this read could not be parsed",
                "previous_watermark": watermark,
                "policy": (
                    "the watermark is never advanced past a record that could not be read, so the "
                    "unread range is re-read rather than skipped"
                ),
            }
            report["watermark_candidate"] = None
        else:
            report["watermark_candidate"] = (
                max([int(row.get("event_record_id") or 0) for row in records] + [watermark or 0])
                or None
            )
        attempt["channels"][channel] = report

    written = append_records(pending, store_path)
    attempt["records_added"] = written["records_added"]
    attempt["records_total"] = written["records_total"]
    attempt["store_bytes"] = written["store_bytes"]
    if written["records_added"] == 0 and all(
        report["status"] in (CHANNEL_DISABLED_NO_RECORDS, NO_RECORDS_MATCHING_THE_TASK)
        for report in attempt["channels"].values()
    ):
        attempt["status"] = (
            CHANNEL_DISABLED_NO_RECORDS
            if attempt["channels"].get(CHANNEL_OPERATIONAL, {}).get("enabled") is False
            else NO_RECORDS_MATCHING_THE_TASK
        )
    # the watermark moves only now: the records behind it are on disk, replacing the store
    # atomically, and an interrupted write can only leave the watermark behind rather than ahead
    watermarks = dict(live.get("watermarks") or {})
    for channel, report in attempt["channels"].items():
        candidate = report.get("watermark_candidate")
        if candidate is not None and (
            watermarks.get(channel) is None or candidate > watermarks[channel]
        ):
            watermarks[channel] = candidate
    attempts = [*((live.get("attempts") or [])[-19:]), attempt]
    document = {
        "artifact": "RFC047_WINDOWS_EVENT_LIVE_STATE",
        "version": STORE_VERSION,
        "purpose": (
            "the mutable side of the evidence: how far the read has advanced, what each attempt "
            "saw, and what it could not read — kept apart from the immutable store of records"
        ),
        "watermarks": watermarks,
        "watermark_semantics": (
            "the highest EventRecordID examined per channel: every record at or below it was either "
            "stored in the immutable store or counted as not belonging to the monitored task.  It is "
            "advanced only after the store has been replaced and never past a fragment that could "
            "not be read, so a crash or a bad read can leave it behind but never ahead"
        ),
        "attempts": attempts,
        "last_attempt_status": attempt["status"],
        "last_attempt_at_utc": collected_at,
        "records_stored": written["records_total"],
        "store_bytes": written["store_bytes"],
        "growth": {
            "records": written["records_total"],
            "bytes": written["store_bytes"],
            "bytes_per_record": round(written["store_bytes"] / written["records_total"], 1)
            if written["records_total"]
            else None,
            "bound": (
                "one record per (channel, EventRecordID), deduplicated on write; the store is never "
                "an export of the whole log and never grows by a re-read"
            ),
        },
    }
    write_json_atomic(live_path or LIVE_STATE, document)
    return attempt


# ---------------------------------------------------------------------------------------------
# the host audit: the before-state, the gate, and the after-state
# ---------------------------------------------------------------------------------------------


def probe_activation_change(channel: str = CHANNEL_OPERATIONAL) -> dict[str, Any]:
    """Attempt the one configuration change RFC-047 contemplates, and record the host's answer.

    This is not an attempt to evade a permission: it is the measurement of it.  The command is
    issued exactly as an operator would issue it, without elevation, and its refusal is the evidence
    that the gate exists.  Nothing else about the host is touched.
    """
    answer = run_wevtutil(["sl", channel, "/e:true"], timeout_s=15)
    return {
        "command": "wevtutil " + " ".join(answer["command"][1:]),
        "exit_code": answer["exit_code"],
        "stderr": (answer["stderr"] or "").strip()[:400],
        "stdout": (answer["stdout"] or "").strip()[:400],
        "applied": answer["exit_code"] == 0,
        "reading": (
            "the host accepted the change"
            if answer["exit_code"] == 0
            else (
                "the host refused the change without an elevated token, which is the gate RFC-047 "
                "describes: it is recorded and not worked around"
            )
        ),
    }


def host_audit(
    now: datetime | None = None,
    probe_write: bool = True,
    audit_path: Path | None = None,
    activation_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read the host's audit surface, before anything is changed, and record the gate."""
    moment = now or datetime.now(UTC)
    taken_at = moment.strftime("%Y-%m-%dT%H:%M:%SZ")
    offset = host_offset_minutes(moment)
    groups = group_sids()
    channels: dict[str, Any] = {}
    for channel in CHANNELS:
        config = parse_channel_config(run_wevtutil(["gl", channel])["stdout"])
        info = parse_log_info(run_wevtutil(["gli", channel])["stdout"])
        read = read_channel_records(channel, None, taken_at, offset, limit=1, newest_first=True)
        newest = read["records"][0]["event_timestamp_utc"] if read["records"] else None
        channels[channel] = {
            "config": config,
            "log_info": info,
            "readable": read["status"] == "OK",
            "read_status": read["status"],
            "read_exit_code": read.get("exit_code"),
            "newest_record_utc": newest,
            "time_basis": time_basis_check(newest, moment, offset),
            "permissions": _sddl_allows_read(config.get("channel_access_sddl"), groups),
            "state": (
                CHANNEL_MISSING
                if not config.get("parsed")
                else (CHANNEL_AVAILABLE if config.get("enabled") else CHANNEL_DISABLED)
                if read["status"] == "OK"
                else CHANNEL_UNREADABLE
            ),
        }
    probe = probe_activation_change() if probe_write else {"applied": None, "skipped": True}
    if probe["applied"] is True:
        recheck = parse_channel_config(run_wevtutil(["gl", CHANNEL_OPERATIONAL])["stdout"])
        gate_status = CHANNEL_ENABLED_AWAITING_REAL_EVENT
        coverage_from = taken_at
        post_state = bool(recheck.get("enabled"))
    else:
        gate_status = HOST_AUDIT_CHANGE_APPROVAL_REQUIRED
        coverage_from = None
        post_state = bool(channels[CHANNEL_OPERATIONAL]["config"].get("enabled"))
    document: dict[str, Any] = {
        "artifact": "RFC047_HOST_AUDIT",
        "audit_version": AUDIT_VERSION,
        "purpose": (
            "the before-state of the audit channels, the permissions the effective user holds over "
            "them, the gate that stands between this session and the one configuration change RFC-047 "
            "contemplates, and how that change would be reversed"
        ),
        "read_only_until_now": True,
        "taken_at_utc": taken_at,
        "host_offset_minutes": offset,
        "task": {
            "name": TASK_NAME,
            "full_path": "\\" + TASK_NAME,
            "declared_by": "data/st6/ST6_SCHEDULER_EVIDENCE.json, the task's own registration",
        },
        "session": effective_user(moment),
        "channels": channels,
        "candidate_event_identifiers": {
            "declared": list(CANDIDATE_EVENT_IDS),
            "declared_where": (
                "the request names them as candidates; the earlier audit of this host read them from "
                "the provider's own documentation and recorded their downstream meaning, but no "
                "record of this host was ever seen for any of them"
            ),
            "semantics_verified_on_this_host": False,
            "why_not": (
                "no record carrying any of these identifiers exists in a channel this session can "
                "read, so their meaning could not be verified against a real record and this RFC "
                "does not assign them one"
            ),
            "what_would_verify_them": (
                "one real record per identifier, read from a channel this host enables, quoted in "
                "data/st6/rfc047/EVENT_SEMANTICS.json together with its channel and its record id"
            ),
        },
        "gate": {
            "change_contemplated": (
                f"enable the {CHANNEL_OPERATIONAL} channel (wevtutil sl ... /e:true): the only "
                "configuration change RFC-047 contemplates"
            ),
            "state_before": channels[CHANNEL_OPERATIONAL]["config"].get("enabled"),
            "state_after": post_state,
            "status": gate_status,
            "probe": probe,
            "activation_request": activation_request
            or {
                "raised": True,
                "command": f"wevtutil sl {CHANNEL_OPERATIONAL} /e:true",
                "outcome": "NOT_GRANTED_IN_THIS_SESSION",
                "note": (
                    "the change was requested with the exact command and the request for an "
                    "elevated token was not approved in this session, so the change was not "
                    "applied; the refusal of the unelevated attempt above is the measurement of the "
                    "gate and is recorded rather than worked around"
                ),
            },
            "rollback": {
                "command": f"wevtutil sl {CHANNEL_OPERATIONAL} /e:false",
                "restores": "the channel's enabled flag to the value recorded above as state_before",
                "does_not": (
                    "delete the evidence already collected, touch the Security channel, change any "
                    "ACL, GPO, size limit, retention policy or any other administrator's "
                    "configuration"
                ),
                "owner_check_required_before_running": True,
            },
        },
        "coverage_from_utc": coverage_from,
        "coverage_reading": (
            "the instant from which a per-run record could exist; no coverage is inferred for any "
            "instant before it"
            if coverage_from
            else (
                "no instant exists from which a per-run record could exist: the operational channel "
                "is disabled and has never recorded on this host, so every slot of the period is "
                "outside the reach of external evidence, and a later rebuild may not promote one"
            )
        ),
        "retention": {
            "operational": channels[CHANNEL_OPERATIONAL]["config"].get("retention"),
            "circular_policy_means": (
                "the channel overwrites its oldest record rather than backing it up, so the system's "
                "own history cannot be the durable record; that is why this RFC persists what it "
                "reads"
            ),
            "maintenance_records_present": channels[CHANNEL_MAINTENANCE]["log_info"].get(
                "records_present"
            ),
            "maintenance_oldest_record_number": channels[CHANNEL_MAINTENANCE]["log_info"].get(
                "oldest_record_number"
            ),
            "maintenance_max_size_bytes": channels[CHANNEL_MAINTENANCE]["config"].get(
                "max_size_bytes"
            ),
            "maintenance_file_size_bytes": channels[CHANNEL_MAINTENANCE]["log_info"].get(
                "file_size_bytes"
            ),
        },
        "disk": disk_capacity(Path(os.environ.get("SYSTEMROOT") or "C:/") / "System32" / "Winevt"),
        "no_change_applied": not bool(probe.get("applied")),
        "commands_run": [
            "wevtutil gl <channel>            (read a channel's own configuration)",
            "wevtutil gli <channel>           (read how much of a log is still present)",
            "wevtutil qe <channel> /f:xml ...  (read records; no filter writes anything)",
            "wevtutil sl <channel> /e:true    (the gate; refused here without elevation)",
        ],
    }
    write_json_atomic(audit_path or HOST_AUDIT_JSON, document)
    return document


# ---------------------------------------------------------------------------------------------
# the evidence document: what the store holds, and what it cannot
# ---------------------------------------------------------------------------------------------


def evidence_document(
    audit: dict[str, Any] | None = None,
    now: datetime | None = None,
    evidence_path: Path | None = None,
) -> dict[str, Any]:
    moment = now or datetime.now(UTC)
    rows = load_store()
    live = load_live_state()
    audit = audit or read_json(HOST_AUDIT_JSON) or {}
    channels = audit.get("channels") or {}
    per_channel: dict[str, Any] = {}
    for channel in CHANNELS:
        records = [row for row in rows if row.get("channel") == channel]
        per_channel[channel] = {
            "enabled": (channels.get(channel) or {}).get("config", {}).get("enabled"),
            "state": (channels.get(channel) or {}).get("state"),
            "readable": (channels.get(channel) or {}).get("readable"),
            "records_stored": len(records),
            "event_record_ids": sorted(int(row.get("event_record_id") or 0) for row in records),
            "event_ids_seen": sorted({int(row.get("event_id") or 0) for row in records}),
            "watermark": (live.get("watermarks") or {}).get(channel),
            "attempt_status": (live.get("attempts") or [{}])[-1]
            .get("channels", {})
            .get(channel, {})
            .get("status"),
        }
    available = sum(
        len([row for row in rows if row.get("channel") == channel]) for channel in CHANNELS
    )
    document: dict[str, Any] = {
        "artifact": "RFC047_WINDOWS_EVENT_EVIDENCE",
        "evidence_version": EVIDENCE_VERSION,
        "store_version": STORE_VERSION,
        "generated_at_utc": moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_by": "scripts/st6_windows_events.py",
        "purpose": (
            "the durable, deduplicated record of the Task Scheduler events this host produced, and "
            "an honest account of the events it could not produce or could not be read"
        ),
        "store": {
            "path": str(EVENT_STORE.relative_to(REPO)).replace("\\", "/"),
            "records_total": len(rows),
            "bytes": sum(int(row.get("event_xml_bytes") or 0) for row in rows),
            "deduplicated_on": "(channel, event_record_id)",
        },
        "live_state": {
            "path": str(LIVE_STATE.relative_to(REPO)).replace("\\", "/"),
            "watermarks": live.get("watermarks"),
            "attempts_recorded": len(live.get("attempts") or []),
            "last_attempt_status": live.get("last_attempt_status"),
            "last_attempt_at_utc": live.get("last_attempt_at_utc"),
            "growth": live.get("growth"),
        },
        "channels": per_channel,
        "event_identifier_candidates": {
            "declared": list(CANDIDATE_EVENT_IDS),
            "semantics": semantics_status(rows),
            "classification_rule": (
                "a record is classified by its channel, its task path, its instance identifiers and "
                "its instants; the identifier alone never establishes that a run was scheduled"
            ),
        },
        "events_available": available,
        "events_missing_or_unobtainable": {
            "operational_channel_enabled": (channels.get(CHANNEL_OPERATIONAL) or {})
            .get("config", {})
            .get("enabled"),
            "gate_status": (audit.get("gate") or {}).get("status"),
            "records_lost_to_rotation_in_the_maintenance_channel": (
                channels.get(CHANNEL_MAINTENANCE) or {}
            )
            .get("log_info", {})
            .get("oldest_record_number"),
            "why": (
                "the operational channel is disabled on this host and the change that would enable "
                "it was refused without an elevated token; the maintenance channel carries only "
                "identifiers 800 and 808, none of which describes a task's execution"
                if not (channels.get(CHANNEL_OPERATIONAL) or {}).get("config", {}).get("enabled")
                else "recorded per channel above"
            ),
        },
        "retention": {
            "bounded": True,
            "watermark_advanced_only_after_a_durable_write": True,
            "deduplicated": True,
            "rotation_and_reset_recorded": True,
            "refusals_recorded": True,
            "storage_bytes_measured": live.get("store_bytes"),
            "policy": (
                "the store holds only records of the monitored task, one per EventRecordID, and is "
                "preserved until the period closes; the log itself is never exported wholesale"
            ),
        },
        "collection_never_blocks_the_monitor": (
            "the scheduled tick runs this program as a subprocess and records its exit status; a "
            "refused read cannot stop a sample from being taken"
        ),
    }
    write_json_atomic(evidence_path or EVIDENCE_JSON, document)
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="read the Windows event evidence of ST-6")
    parser.add_argument("--audit", action="store_true", help="read the host audit surface")
    parser.add_argument("--ingest", action="store_true", help="read past the watermark")
    parser.add_argument("--status", action="store_true", help="write the evidence document")
    parser.add_argument("--all", action="store_true", help="audit, ingest and status")
    parser.add_argument(
        "--no-probe-write",
        action="store_true",
        help="skip the gate probe (the change is never applied here; the probe only measures it)",
    )
    parser.add_argument(
        "--json", action="store_true", help="print the document instead of a summary"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=MAX_RECORDS_PER_READ,
        help="how many records one read may pull (the store is never filled by an export)",
    )
    args = parser.parse_args(argv)
    if not (args.audit or args.ingest or args.status or args.all):
        args.status = True
    if args.all:
        args.audit = args.ingest = args.status = True
    outputs: dict[str, Any] = {}
    if args.audit:
        outputs["audit"] = host_audit(probe_write=not args.no_probe_write)
    if args.ingest:
        outputs["ingest"] = ingest(limit=args.limit)
    if args.status:
        outputs["evidence"] = evidence_document(
            audit=outputs.get("audit") or read_json(HOST_AUDIT_JSON)
        )
    if args.json:
        print(json.dumps(outputs, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    if "audit" in outputs:
        audit = outputs["audit"]
        print(
            f"host audit: operational enabled={audit['gate']['state_before']} "
            f"gate={audit['gate']['status']} coverage_from={audit['coverage_from_utc']}"
        )
    if "ingest" in outputs:
        attempt = outputs["ingest"]
        for channel, report in attempt["channels"].items():
            print(
                f"ingest {channel}: {report['status']} enabled={report.get('enabled')} "
                f"seen={report.get('records_seen')} added={report.get('records_added')} "
                f"watermark={report.get('watermark_candidate')}"
            )
    if "evidence" in outputs:
        evidence = outputs["evidence"]
        print(
            f"windows evidence: {evidence['events_available']} record(s) stored; "
            f"missing={evidence['events_missing_or_unobtainable']['gate_status']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
