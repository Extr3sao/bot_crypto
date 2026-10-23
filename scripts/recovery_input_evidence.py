"""Input authority for the POST RFC-049 / ACTIVE RECOVERY lane (WP-8B).

The two derived artefacts of this lane (``CAMPAIGN_STATE_VIEW.json`` and
``ACTIVE_ECONOMIC_AUDIT.json``) and their independent verifier were reconstructing
themselves from whatever happened to be on the machine that ran them:

* ``PAPER_DATA_24H_REPORT.json`` and ``data/st6/ST6_HEALTH_STATUS.json`` were read
  from the working tree while untracked, so a clean checkout lost the paper lane's
  verdict and the forward lane's governance mirror;
* ``reports/strategy-baseline/*.json`` and ``reports/alpha-recovery-v1/*.md`` are
  gitignored by design, so the audit's per-timeframe gross edges, its sample
  counts and its cost barrier came from files that are not in the repository;
* raw dataset digests were graded as "missing" when the gitignored dataset was not
  on the machine, which turned a normal clean checkout into a contradiction;
* every digest was taken over raw bytes, so ``core.autocrlf`` alone changed the
  recorded identity of a text file between two checkouts of the same commit.

This module answers one question for all of them: *what are this input's bytes, and
what authority do they answer to?* It classifies every declared input, resolves it
the same way in every checkout, and carries the evidence a clean checkout needs.

Classes
-------
``COMMITTED``
    Tracked at HEAD. The certified bytes are the commit's bytes, read through
    ``git show HEAD:<path>``, so an uncommitted edit cannot enter a certified
    artefact and cannot change its identity.
``EXTERNAL_GENERATED``
    Gitignored by design (a local research output). The repository carries a
    byte-identical evidence copy under ``evidence/inputs/``; that copy is what the
    consumers read, so the published findings reconstruct anywhere. The copy is
    admissible only while it reproduces the digest the published artefact itself
    recorded for the input. When the local original is present, its digest is an
    observation, never a silent substitute.
``EXTERNAL_LIVE``
    Another lane's live state file, rewritten on its own schedule - it *cannot*
    answer to a digest published once, because by design it moves. The repository
    carries a dated snapshot whose attested governance fields are the certified
    facts; the live file is an observation, and a change to an attested field
    blocks a re-capture for review instead of sliding into the certified state.
``EXTERNAL_DATASET``
    Gitignored raw input pinned by a frozen manifest. Not needed to reproduce any
    published number, so its absence is a materialization note rather than a
    contradiction; when present it is graded against the frozen digest.

Byte conventions
----------------
Digests are content digests: ``sha256_lf`` and ``sha256_crlf`` are the authorities
and the raw-bytes ``sha256`` is informational, exactly as the cost-barrier lane
established in WP-7E. A file differing by line endings alone is the same file.

Modes::

    python scripts/recovery_input_evidence.py --verify        # default, read-only
    python scripts/recovery_input_evidence.py --capture       # author: record the evidence
    python scripts/recovery_input_evidence.py --materialize   # verify, then place gitignored targets
    python scripts/recovery_input_evidence.py --json

Exit codes: 0 verified, 2 integrity failure, 3 blocked (bundle absent).

Not a signature: integrity here is a digest chain anchored in the commit that
carries it. A party able to rewrite the artefacts, the evidence and this checker
together defeats it. That limitation is stated, not hidden.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

EVIDENCE_DIR = "data/recovery/wp8/evidence"
INPUTS_DIR = f"{EVIDENCE_DIR}/inputs"
SIDECAR = f"{EVIDENCE_DIR}/INPUT_EVIDENCE.json"

AUDIT = "data/recovery/ACTIVE_ECONOMIC_AUDIT.json"
STATE_VIEW = "data/recovery/CAMPAIGN_STATE_VIEW.json"
MANIFEST = "data/rfc049/PREREGISTRATION_MANIFEST.json"

COMMITTED = "COMMITTED"
EXTERNAL_GENERATED = "EXTERNAL_GENERATED"
EXTERNAL_LIVE = "EXTERNAL_LIVE"
EXTERNAL_DATASET = "EXTERNAL_DATASET"

PUBLISHED_SOURCES = "published_sources"
DATED_SNAPSHOT = "dated_snapshot"
PREREGISTRATION_MANIFEST = "preregistration_manifest"
COMMITTED_AUTHORITY = "committed"

VERIFIED = "VERIFIED"
DRIFTED = "DRIFTED"
NOT_MATERIALIZED = "NOT_MATERIALIZED"
UNRESOLVED = "UNRESOLVED"

EXIT_OK = 0
EXIT_INTEGRITY = 2
EXIT_BLOCKED = 3

DECLARED_INPUTS: tuple[dict[str, Any], ...] = (
    {
        "path": "reports/strategy-baseline/TIMEFRAME_AUDIT.json",
        "class": EXTERNAL_GENERATED,
        "slug": "TIMEFRAME_AUDIT.json",
        "role": "per-timeframe (15m/30m/1h) parity-engine totals, BASE and ZERO_COST, with DEV/VAL/OOS",
        "required_for_reproduction": True,
        "authority": {"kind": PUBLISHED_SOURCES, "artifact": AUDIT},
        "consumers": ("active_economic_audit", "recovery_verify"),
    },
    {
        "path": "reports/strategy-baseline/REGIME_ANALYSIS.json",
        "class": EXTERNAL_GENERATED,
        "slug": "REGIME_ANALYSIS.json",
        "role": "D-05 regime-conditional cells used by the robustness attribution",
        "required_for_reproduction": True,
        "authority": {"kind": PUBLISHED_SOURCES, "artifact": AUDIT},
        "consumers": ("active_economic_audit",),
    },
    {
        "path": "reports/strategy-baseline/COST_BARRIER.json",
        "class": EXTERNAL_GENERATED,
        "slug": "COST_BARRIER.json",
        "role": "market-horizon source: median bars needed to cover the round trip",
        "required_for_reproduction": True,
        "authority": {"kind": PUBLISHED_SOURCES, "artifact": AUDIT},
        "consumers": ("active_economic_audit", "cost_barrier_explorer"),
    },
    {
        "path": "reports/alpha-recovery-v1/STRATEGY_FAILURE_MATRIX.md",
        "class": EXTERNAL_GENERATED,
        "slug": "STRATEGY_FAILURE_MATRIX.md",
        "role": "ARP-001 strategy failure matrix: per-family entry-drift evidence",
        "required_for_reproduction": True,
        "authority": {"kind": PUBLISHED_SOURCES, "artifact": AUDIT},
        "consumers": ("active_economic_audit",),
    },
    {
        "path": "data/st6/ST6_HEALTH_STATUS.json",
        "class": EXTERNAL_LIVE,
        "slug": "ST6_HEALTH_STATUS.json",
        "role": "forward-regime lane's health and standing-state declaration (governance mirror)",
        "required_for_reproduction": True,
        "authority": {"kind": DATED_SNAPSHOT, "artifact": SIDECAR},
        "attested_fields": (
            ("status", "LANE_STATE"),
            ("standing_state.NEXT_CAMPAIGN", "NEXT_CAMPAIGN"),
            ("standing_state.LIVE_TRADING", "LIVE_TRADING"),
        ),
        "consumers": ("campaign_state_view", "recovery_verify"),
    },
    {
        "path": "PAPER_DATA_24H_REPORT.json",
        "class": COMMITTED,
        "slug": None,
        "role": "the paper lane's closed 24h data-accumulation report (PAPER_24H_DATA_FAILED)",
        "required_for_reproduction": True,
        "authority": {"kind": COMMITTED_AUTHORITY, "artifact": None},
        "consumers": ("active_economic_audit", "campaign_state_view", "recovery_verify"),
    },
    {
        "path": "data/raw/alpha001/BTC-USDT_1d.json",
        "class": EXTERNAL_DATASET,
        "slug": None,
        "role": "frozen price series pinned by the RFC-049 preregistration manifest",
        "required_for_reproduction": False,
        "authority": {"kind": PREREGISTRATION_MANIFEST, "artifact": MANIFEST},
        "consumers": ("campaign_state_view",),
    },
    {
        "path": "data/raw/alpha001/ETH-USDT_1d.json",
        "class": EXTERNAL_DATASET,
        "slug": None,
        "role": "frozen price series pinned by the RFC-049 preregistration manifest",
        "required_for_reproduction": False,
        "authority": {"kind": PREREGISTRATION_MANIFEST, "artifact": MANIFEST},
        "consumers": ("campaign_state_view",),
    },
)

DECLARATION = {entry["path"]: entry for entry in DECLARED_INPUTS}

_HEAD_CACHE: dict[tuple[str, str], bytes | None] = {}


# --------------------------------------------------------------------------- #
# digests
# --------------------------------------------------------------------------- #


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def eol_forms(data: bytes) -> dict[str, bytes]:
    lf = data.replace(b"\r\n", b"\n")
    return {"EXACT": data, "LF": lf, "CRLF": lf.replace(b"\n", b"\r\n")}


def content_forms(data: bytes) -> dict[str, Any]:
    """The forms a digest may legitimately be taken in, and which one these bytes are."""
    return {
        "sha256": sha256_bytes(data),
        "sha256_lf": sha256_bytes(eol_forms(data)["LF"]),
        "sha256_crlf": sha256_bytes(eol_forms(data)["CRLF"]),
        "bytes": len(data),
        "line_endings": "CRLF" if b"\r\n" in data else "LF",
    }


def grade(pin: str | None, data: bytes | None) -> str:
    """Grade bytes against a recorded digest, tolerating a line-ending-only difference.

    ``DRIFTED`` is the only failing case: the content moved. A difference that is
    line endings alone is what a checkout does to a text file, so calling it drift
    would make every recorded digest unverifiable off the machine that wrote it -
    the defect this module exists to close.
    """
    if pin is None:
        return UNRESOLVED
    if data is None:
        return NOT_MATERIALIZED
    forms = eol_forms(data)
    if sha256_bytes(forms["EXACT"]) == pin or sha256_bytes(forms["LF"]) == pin:
        return VERIFIED
    return DRIFTED


def content_grade(pin: dict[str, Any] | None, data: bytes | None) -> str:
    """Grade against a content-form pin (the convention for everything committed)."""
    if not pin or not (pin.get("sha256_lf") or pin.get("sha256_crlf")):
        return UNRESOLVED
    if data is None:
        return NOT_MATERIALIZED
    forms = content_forms(data)
    if pin.get("sha256_lf") and forms["sha256_lf"] == pin["sha256_lf"]:
        return VERIFIED
    if pin.get("sha256_crlf") and forms["sha256_crlf"] == pin["sha256_crlf"]:
        return VERIFIED
    return DRIFTED


# --------------------------------------------------------------------------- #
# git readers: the commit is the authority for committed content
# --------------------------------------------------------------------------- #


def git(*args: str, root: Path | None = None) -> str | None:
    out = subprocess.run(
        ["git", *args], cwd=str(root or ROOT), capture_output=True, text=True, check=False
    )
    return out.stdout if out.returncode == 0 else None


def head_commit(root: Path | None = None) -> str:
    return (git("rev-parse", "HEAD", root=root) or "").strip()


def committed_bytes(rel: str, root: Path | None = None) -> bytes | None:
    """The bytes of ``rel`` as committed at HEAD, or None when it is not tracked there."""
    base = root or ROOT
    key = (str(base), rel)
    if key in _HEAD_CACHE:
        cached: bytes | None = _HEAD_CACHE[key]
        return cached
    out = subprocess.run(
        ["git", "show", f"HEAD:{rel}"], cwd=str(base), capture_output=True, check=False
    )
    data = out.stdout if out.returncode == 0 else None
    _HEAD_CACHE[key] = data
    return data


def tracked(rel: str) -> bool:
    return (
        subprocess.run(
            ["git", "ls-files", "--error-unmatch", rel],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        ).returncode
        == 0
    )


def committed_tree_entries(prefix: str) -> list[str]:
    """Paths committed at HEAD under ``prefix``: the repository's own view of its tree."""
    return [
        line
        for line in (git("ls-tree", "-r", "--name-only", "HEAD", prefix) or "").splitlines()
        if line
    ]


def reset() -> None:
    _HEAD_CACHE.clear()


# --------------------------------------------------------------------------- #
# resolution
# --------------------------------------------------------------------------- #


def evidence_path(rel: str) -> str | None:
    entry = DECLARATION.get(rel)
    return f"{INPUTS_DIR}/{entry['slug']}" if entry and entry.get("slug") else None


def resolve(rel: str) -> dict[str, Any]:
    """Resolve one declared input to the bytes a consumer must read.

    The answer is a function of the commit, not of the machine: committed paths are
    read from HEAD, external paths from the evidence copy the repository carries. A
    working-tree read is only ever a fallback and says so, so a fallback cannot be
    mistaken for a certified reconstruction.
    """
    entry = DECLARATION.get(rel)
    cls = entry["class"] if entry else COMMITTED
    data: bytes | None = None
    origin = "ABSENT"
    if cls in (EXTERNAL_GENERATED, EXTERNAL_LIVE):
        evidence = evidence_path(rel)
        if evidence:
            data = committed_bytes(evidence)
            if data is not None:
                origin = "EVIDENCE_COPY"
            elif (ROOT / evidence).exists():
                data = (ROOT / evidence).read_bytes()
                origin = "EVIDENCE_COPY_UNCOMMITTED"
        if data is None and (ROOT / rel).exists():
            data = (ROOT / rel).read_bytes()
            origin = "WORKTREE_FALLBACK"
    elif cls == EXTERNAL_DATASET:
        # not needed to reproduce any finding: a local materialization is graded as an
        # observation against the frozen manifest digest, never read into a finding.
        # The origin names the *route*, not this machine's state: it stays
        # LOCAL_MATERIALIZATION whether or not the dataset is present here (``present``
        # says which), because a published artefact must not encode which machine built
        # it - that is the defect WP-8C removed, and this input is where it survived
        # longest (WP-8H: the clean-checkout rehearsal found it, the state digest did not).
        if (ROOT / rel).exists():
            data = (ROOT / rel).read_bytes()
        origin = "LOCAL_MATERIALIZATION"
    else:
        data = committed_bytes(rel)
        if data is not None:
            origin = "HEAD"
        elif (ROOT / rel).exists():
            data = (ROOT / rel).read_bytes()
            origin = "WORKTREE_FALLBACK"
    return {
        "path": rel,
        "class": cls,
        "origin": origin,
        "present": data is not None,
        "bytes": data,
        "forms": content_forms(data) if data is not None else None,
    }


def resolve_bytes(rel: str) -> bytes | None:
    data: bytes | None = resolve(rel)["bytes"]
    return data


def resolve_json(rel: str) -> Any:
    data = resolve_bytes(rel)
    if data is None:
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def resolve_text(rel: str) -> str:
    data = resolve_bytes(rel)
    return data.decode("utf-8", errors="replace") if data is not None else ""


# --------------------------------------------------------------------------- #
# authority: what does the published record itself vouch for?
# --------------------------------------------------------------------------- #


def dig(obj: Any, dotted: str) -> Any:
    current = obj
    for part in dotted.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def sidecar_document() -> dict[str, Any]:
    data = committed_bytes(SIDECAR)
    if data is None and (ROOT / SIDECAR).exists():
        data = (ROOT / SIDECAR).read_bytes()
    if data is None:
        return {}
    try:
        document: dict[str, Any] = json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return document


def authority_pin(rel: str) -> dict[str, Any] | None:
    """The digest a published record vouches for, if any.

    The artefact (or, for a live file, the dated snapshot's own capture record) is
    the authority - not this file and not the capture machine. The evidence copy is
    admissible only while it reproduces that digest. Reading the authority from the
    *commit* is what stops an uncommitted rewrite of the artefact from re-anchoring
    the chain in its own favour.
    """
    entry = DECLARATION.get(rel)
    if not entry:
        return None
    kind = entry["authority"]["kind"]
    if kind == COMMITTED_AUTHORITY:
        data = committed_bytes(rel)
        return {"source": "HEAD", "sha256": sha256_bytes(data)} if data is not None else None
    if kind == PREREGISTRATION_MANIFEST:
        manifest = json.loads((committed_bytes(MANIFEST) or b"{}").decode("utf-8") or "{}")
        for group in ("price_series", "signal_series"):
            record = ((manifest.get("dataset_hashes") or {}).get(group) or {}).get(rel)
            if record and record.get("sha256"):
                return {
                    "source": f"{MANIFEST}:dataset_hashes.{group}.{rel}",
                    "sha256": record["sha256"],
                }
        return None
    if kind == DATED_SNAPSHOT:
        record = (sidecar_document().get("inputs") or {}).get(rel) or {}
        if not record.get("sha256_lf"):
            return None
        return {
            "source": f"{SIDECAR}:inputs.{rel}",
            "sha256_lf": record["sha256_lf"],
            "sha256_crlf": record.get("sha256_crlf"),
            "sha256": record.get("sha256"),
            "captured_commit": record.get("captured_commit"),
        }
    artifact = entry["authority"]["artifact"]
    data = committed_bytes(artifact)
    if data is None:
        return None
    try:
        payload = json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    for row in payload.get("sources") or []:
        if str(row.get("path")) == rel:
            if row.get("sha256_lf"):
                return {
                    "source": f"{artifact}:sources[].sha256_lf",
                    "sha256_lf": row["sha256_lf"],
                    "sha256_crlf": row.get("sha256_crlf"),
                    "sha256": row.get("sha256"),
                }
            if row.get("sha256"):
                return {"source": f"{artifact}:sources[].sha256", "sha256": row["sha256"]}
    return None


def evidence_forms(rel: str) -> dict[str, Any] | None:
    """The evidence copy's identity, taken from the commit that carries it.

    ``in_head`` is part of the record on purpose: an evidence copy that exists only
    on a working tree is not evidence a clean checkout can use, and the consumer's
    reproducibility invariant reads this flag to fail on exactly that.
    """
    evidence = evidence_path(rel)
    if not evidence:
        return None
    data = committed_bytes(evidence)
    if data is not None:
        return {**content_forms(data), "path": evidence, "in_head": True}
    if (ROOT / evidence).exists():
        return {**content_forms((ROOT / evidence).read_bytes()), "path": evidence, "in_head": False}
    return None


def declared_record(rel: str) -> dict[str, Any]:
    """The deterministic declaration of one input: what it is, what it answers to and
    what evidence the repository carries for it.

    Deliberately free of anything that varies per machine (presence, the digest of a
    local original). Those are observations: reported next to this record, never
    inside the identity a certification rests on.
    """
    entry = DECLARATION.get(rel, {"path": rel, "class": COMMITTED, "role": "", "consumers": ()})
    record: dict[str, Any] = {
        "path": rel,
        "class": entry["class"],
        "role": entry.get("role", ""),
        "required_to_reproduce_a_finding": bool(entry.get("required_for_reproduction")),
        "authority": entry["authority"],
    }
    if entry.get("attested_fields"):
        record["attested_fields"] = [dotted for dotted, _field in entry["attested_fields"]]
    evidence = evidence_forms(rel)
    if evidence:
        record["evidence_copy"] = {k: v for k, v in evidence.items() if k != "path"}
        record["evidence_path"] = evidence["path"]
    return record


def observe(rel: str) -> dict[str, Any]:
    """What this machine happens to hold, graded. Volatile by construction."""
    resolved = resolve(rel)
    entry = DECLARATION.get(rel, {})
    evidence = evidence_path(rel)
    live = (ROOT / rel).read_bytes() if (ROOT / rel).exists() else None
    pin = authority_pin(rel)
    forms = content_forms(live) if live is not None else None
    record: dict[str, Any] = {
        "path": rel,
        "class": resolved["class"],
        "resolved_from": resolved["origin"],
        "present_on_this_machine": live is not None,
        "local_forms": forms,
        "local_reproduces_the_authority": (
            (grade(pin.get("sha256"), live) == VERIFIED or content_grade(pin, live) == VERIFIED)
            if (pin and live is not None)
            else None
        ),
    }
    if entry.get("attested_fields"):
        payload = json.loads(live.decode("utf-8")) if live is not None else {}
        record["attested_field_values"] = {
            dotted: dig(payload, dotted) for dotted, _field in entry["attested_fields"]
        }
        snapshot = resolve_bytes(rel)
        snapshot_payload = json.loads((snapshot or b"{}").decode("utf-8")) if snapshot else {}
        record["attested_fields_match_the_snapshot"] = record["attested_field_values"] == {
            dotted: dig(snapshot_payload, dotted) for dotted, _field in entry["attested_fields"]
        }
    if evidence and (ROOT / evidence).exists():
        copy = (ROOT / evidence).read_bytes()
        if pin:
            record["evidence_reproduces_the_authority"] = (
                grade(pin.get("sha256"), copy) == VERIFIED or content_grade(pin, copy) == VERIFIED
            )
        record["local_matches_the_evidence_copy"] = (
            live is not None
            and forms is not None
            and content_forms(copy)["sha256_lf"] == forms["sha256_lf"]
        )
    if entry.get("class") == EXTERNAL_LIVE:
        record["note"] = (
            "a live lane file: the certified state reads the dated snapshot the repository carries, "
            "and this observation is what the file says right now"
        )
    return record


def observations() -> list[dict[str, Any]]:
    return [observe(rel) for rel in sorted(DECLARATION)]


def declarations() -> dict[str, Any]:
    return {rel: declared_record(rel) for rel in sorted(DECLARATION)}


def reproduction_evidence_failures() -> list[str]:
    """Inputs whose findings cannot be reconstructed from what the repository carries."""
    failures: list[str] = []
    for rel, record in sorted(declarations().items()):
        if not record["required_to_reproduce_a_finding"]:
            continue
        if record["class"] == COMMITTED:
            if committed_bytes(rel) is None:
                failures.append(f"{rel} is declared committed but is not in HEAD")
            continue
        evidence = record.get("evidence_copy")
        if not evidence:
            failures.append(
                f"{rel} carries no evidence copy, so a clean checkout cannot reconstruct it"
            )
            continue
        if not evidence.get("in_head"):
            failures.append(
                f"{record['evidence_path']} is not committed, so a clean checkout cannot use it"
            )
        pin = authority_pin(rel)
        if not pin:
            failures.append(f"{rel} has no published authority digest to answer to")
            continue
        data = (
            committed_bytes(record["evidence_path"])
            or (ROOT / record["evidence_path"]).read_bytes()
        )
        if not (grade(pin.get("sha256"), data) == VERIFIED or content_grade(pin, data) == VERIFIED):
            failures.append(
                f"{record['evidence_path']} does not reproduce the digest {pin['source']} records for {rel}"
            )
    return failures


def declared_input_failures() -> list[str]:
    """Every declared input must be accounted for: present, or absent-and-declared.

    A working-tree fallback is a failure by construction: an uncommitted file must
    not stand in for a certified input.
    """
    failures: list[str] = []
    for rel, record in sorted(declarations().items()):
        resolved = resolve(rel)
        origin = resolved["origin"]
        if origin in ("WORKTREE_FALLBACK", "EVIDENCE_COPY_UNCOMMITTED"):
            failures.append(
                f"{rel} was resolved from {origin} ({resolved['class']}): an uncommitted file must "
                "not stand in for a certified input"
            )
        elif origin == "ABSENT" and record["class"] == COMMITTED:
            failures.append(f"{rel} is declared COMMITTED but resolves nowhere")
    return failures


# --------------------------------------------------------------------------- #
# capture / verify / materialize
# --------------------------------------------------------------------------- #


def write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def check(name: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"check": name, "result": "PASS" if ok else "FAIL", "detail": detail}


def _capture_generated(
    rel: str, entry: dict[str, Any], checks: list[dict[str, Any]], failures: list[str]
) -> dict[str, Any] | None:
    target = ROOT / rel
    pin = authority_pin(rel)
    if not target.exists():
        failures.append(f"{rel} is not on this machine, so there is nothing to capture")
        return None
    if not pin:
        failures.append(
            f"{rel} has no published authority digest; capturing it would create evidence nobody published"
        )
        return None
    data = target.read_bytes()
    status = grade(pin.get("sha256"), data)
    checks.append(
        check(
            f"capture:{rel}:reproduces_the_published_pin",
            status == VERIFIED,
            f"status {status} against {pin['source']} = {str(pin.get('sha256'))[:16]}...",
        )
    )
    if status != VERIFIED:
        failures.append(
            f"{rel} does not reproduce the digest {pin['source']} recorded ({status}); capturing it "
            "would create evidence for a revision nobody published"
        )
        return None
    return {"pin": pin, "data": data}


def _capture_live(
    rel: str, entry: dict[str, Any], checks: list[dict[str, Any]], failures: list[str]
) -> dict[str, Any] | None:
    """Snapshot a live lane file without letting a governance change slide in.

    A live file cannot answer to a digest published once. What is certified is the
    attested field projection; if the live file states a different value for one of
    those fields than the snapshot it replaces, the capture stops for review.
    """
    target = ROOT / rel
    if not target.exists():
        failures.append(f"{rel} is not on this machine, so there is nothing to snapshot")
        return None
    data = target.read_bytes()
    fields = entry.get("attested_fields") or ()
    projection = {
        dotted: dig(json.loads(data.decode("utf-8")), dotted) for dotted, _field in fields
    }
    previous = (sidecar_document().get("inputs") or {}).get(rel) or {}
    previous_projection = previous.get("attested_fields") or {}
    changed = {
        k: (previous_projection.get(k), v)
        for k, v in projection.items()
        if k in previous_projection and previous_projection[k] != v
    }
    checks.append(
        check(
            f"capture:{rel}:attested_fields_unchanged_since_the_last_snapshot",
            not changed,
            f"attested {projection}" + (f"; changed {changed}" if changed else ""),
        )
    )
    if changed:
        failures.append(
            f"{rel} states different values for its attested governance fields than the snapshot it "
            f"would replace ({changed}); a governance change has to be reviewed, not snapshotted"
        )
        return None
    # the snapshot must not silently contradict what the published view already certifies
    certified = _published_certified(rel, fields)
    contradictory = {
        field: (certified.get(field), projection[dotted])
        for dotted, field in fields
        if certified.get(field) is not None and certified.get(field) != projection[dotted]
    }
    checks.append(
        check(
            f"capture:{rel}:agrees_with_the_published_view",
            not contradictory,
            f"published {certified}"
            + (f"; contradictions {contradictory}" if contradictory else ""),
        )
    )
    if contradictory:
        failures.append(
            f"{rel} contradicts the values the published state view certifies for {rel} "
            f"({contradictory}); a live file may not quietly overturn a certified governance state"
        )
        return None
    published = authority_pin(rel)
    matched = None
    if published and previous.get("sha256"):
        matched = grade(previous["sha256"], data) == VERIFIED
    return {
        "pin": {"source": f"{SIDECAR}:inputs.{rel}", "how": "the dated snapshot this run writes"},
        "data": data,
        "attested": projection,
        "certified": certified,
        "published_pin_at_capture": published,
        "published_pin_matched": matched,
    }


def _published_certified(rel: str, fields: Any) -> dict[str, Any]:
    """The values the *published* state view certifies for the campaign that declares ``rel``."""
    data = committed_bytes(STATE_VIEW)
    if data is None:
        return {}
    try:
        view = json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    for campaign in view.get("campaigns") or []:
        if any(fact.get("source") == rel for fact in campaign.get("facts") or []):
            effective = campaign.get("effective_state") or {}
            return {field: effective.get(field) for _dotted, field in fields if field in effective}
    return {}


def capture() -> tuple[dict[str, Any], int]:
    """Author-side: copy each external input into the evidence bundle, verifying the
    authority the published record states for it."""
    checks: list[dict[str, Any]] = []
    failures: list[str] = []
    records: dict[str, Any] = {}
    for rel, entry in sorted(DECLARATION.items()):
        if not entry.get("slug"):
            continue
        captured = (
            _capture_live(rel, entry, checks, failures)
            if entry["class"] == EXTERNAL_LIVE
            else _capture_generated(rel, entry, checks, failures)
        )
        if captured is None:
            continue
        evidence = ROOT / INPUTS_DIR / entry["slug"]
        evidence.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, evidence)
        record = {
            "source_path": rel,
            "evidence_path": f"{INPUTS_DIR}/{entry['slug']}",
            "class": entry["class"],
            "role": entry.get("role", ""),
            "required_to_reproduce_a_finding": bool(entry.get("required_for_reproduction")),
            "captured_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "captured_commit": head_commit(),
            "reason": (
                f"{rel} is {entry['class'].lower()} and is not in the repository, so a clean checkout "
                "cannot read it. This copy is byte-identical to the file the published artefact was "
                "built from."
            ),
            **content_forms(captured["data"]),
            "pin_authority": {
                **captured["pin"],
                "how": (
                    "the published artefact recorded this digest for this input when it was built; the copy "
                    "is admissible only while it reproduces that digest"
                ),
            },
            "not_a_signature": (
                "integrity here is a digest chain anchored in the commit that carries it, not a "
                "signature: a party able to rewrite the artefact, this copy and the checker together "
                "defeats it, and that is stated as a limitation rather than hidden"
            ),
        }
        if entry["class"] == EXTERNAL_LIVE:
            record["attested_fields"] = captured["attested"]
            record["published_certified_at_capture"] = captured["certified"]
            record["pin_authority"] = {
                "kind": DATED_SNAPSHOT,
                "source": f"{SIDECAR}:inputs.{rel}",
                "how": (
                    "a live lane file moves by design, so its authority is this dated capture and the "
                    "attested field projection it records, not a digest published once"
                ),
            }
            record["published_pin_at_capture"] = captured["published_pin_at_capture"]
            record["published_pin_matched"] = captured["published_pin_matched"]
        records[rel] = record
    sidecar = {
        "artifact": "RECOVERY_INPUT_EVIDENCE",
        "work_package": "WP-8B: input authority for the ACTIVE recovery lane",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_by": "scripts/recovery_input_evidence.py --capture",
        "head": head_commit(),
        "admissible_byte_conventions": (
            "sha256_lf and sha256_crlf are the authorities; sha256 records the bytes of the tree that "
            "wrote the manifest and is informational. A checkout with core.autocrlf rewrites line "
            "endings without touching content, so requiring the raw digest would make the bundle "
            "unverifiable everywhere but on the machine that wrote it"
        ),
        "inputs": records,
        "classes": {
            COMMITTED: "tracked at HEAD; read from the commit, never from the working tree",
            EXTERNAL_GENERATED: "gitignored local research output; the repository carries an evidence copy",
            EXTERNAL_LIVE: "another lane's live state file; the repository carries a dated snapshot",
            EXTERNAL_DATASET: "gitignored raw input pinned by a frozen manifest; not needed to reproduce a finding",
        },
        "not_a_signature": "see scripts/recovery_input_evidence.py: a digest chain anchored in this commit, not a signature",
    }
    write_json(ROOT / SIDECAR, sidecar)
    return {
        "action": "capture",
        "head": head_commit(),
        "status": "VERIFIED" if not failures else "INTEGRITY_FAILURE",
        "captured": sorted(records),
        "checks": checks,
        "failures": failures,
    }, (EXIT_OK if not failures else EXIT_INTEGRITY)


def verify() -> tuple[dict[str, Any], int]:
    sidecar = ROOT / SIDECAR
    if committed_bytes(SIDECAR) is None and not sidecar.exists():
        return {
            "action": "verify",
            "head": head_commit(),
            "status": "BLOCKED_MISSING_INPUT",
            "message": f"{SIDECAR} is absent, so no external input can be reconstructed",
            "failures": [f"{SIDECAR} absent"],
        }, EXIT_BLOCKED
    document = sidecar_document()
    checks: list[dict[str, Any]] = []
    failures: list[str] = []
    for rel, record in sorted(document.get("inputs", {}).items()):
        evidence_rel = record["evidence_path"]
        data = committed_bytes(evidence_rel)
        if data is None:
            checks.append(
                check(
                    f"verify:{rel}:evidence_copy_committed", False, f"{evidence_rel} is not in HEAD"
                )
            )
            failures.append(f"{evidence_rel} is absent from the commit")
            continue
        forms = content_forms(data)
        if forms["sha256_lf"] != record["sha256_lf"]:
            checks.append(
                check(
                    f"verify:{rel}:evidence_content_unchanged",
                    False,
                    f"{forms['sha256_lf'][:16]} != captured {record['sha256_lf'][:16]}",
                )
            )
            failures.append(f"{evidence_rel} content changed since capture")
            continue
        checks.append(
            check(f"verify:{rel}:evidence_content_unchanged", True, forms["sha256_lf"][:16])
        )
        if record.get("published_pin_matched") is False:
            checks.append(
                check(
                    f"verify:{rel}:published_pin_matched_at_capture",
                    False,
                    "the live file had already moved past the published digest when it was snapshotted",
                )
            )
    failures.extend(declared_input_failures())
    failures.extend(reproduction_evidence_failures())
    return {
        "action": "verify",
        "head": head_commit(),
        "status": "VERIFIED" if not failures else "INTEGRITY_FAILURE",
        "checks": checks,
        "checks_total": len(checks),
        "checks_failed": sum(1 for c in checks if c["result"] != "PASS"),
        "failures": failures,
        "captured_commit": document.get("captured_commit"),
    }, (EXIT_OK if not failures else EXIT_INTEGRITY)


def materialize() -> tuple[dict[str, Any], int]:
    """Place the evidence copies at their declared paths for producers that read the
    local path by design (the cost-barrier explorer). Only gitignored targets are
    written; a published artefact is never touched."""
    report, code = verify()
    if code == EXIT_BLOCKED:
        return report, code
    placed: list[str] = []
    for rel, entry in sorted(DECLARATION.items()):
        if entry["class"] != EXTERNAL_GENERATED or not entry.get("slug"):
            continue
        evidence = ROOT / INPUTS_DIR / entry["slug"]
        target = ROOT / rel
        if not evidence.exists():
            continue
        if not target.exists() or target.read_bytes() != evidence.read_bytes():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(evidence, target)
        placed.append(rel)
    return {**report, "action": "materialize", "placed": placed}, code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Input authority for the ACTIVE recovery lane.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--capture", action="store_true", help="author: record the evidence bundle")
    group.add_argument(
        "--materialize", action="store_true", help="verify, then place the gitignored targets"
    )
    group.add_argument("--verify", action="store_true", help="verify the bundle (default)")
    parser.add_argument("--json", action="store_true", help="print the full report")
    args = parser.parse_args(argv)

    if args.capture:
        report, code = capture()
    elif args.materialize:
        report, code = materialize()
    else:
        report, code = verify()
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(
            json.dumps(
                {
                    "action": report.get("action"),
                    "status": report.get("status"),
                    "failures": report.get("failures", [])[:8],
                    "checks_failed": report.get("checks_failed"),
                },
                indent=2,
            )
        )
    return code


if __name__ == "__main__":
    sys.exit(main())
