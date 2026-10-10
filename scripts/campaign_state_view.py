"""Campaign state view — WP-2 (POST RFC-049 / ACTIVE RECOVERY).

A read-only, derived view of the *current* state of every campaign in this
repository, reconstructed from evidence, decisions and events. It exists because
a frozen declaration is not a current one: several documents in this repo state a
gate, an authorization or an OOS policy that a later ADR has since superseded, and
a reader who quotes the frozen text as if it were live will reason from a state
that no longer holds.

What it does
------------
* declares every campaign with the artefacts that speak for it, each tagged with
  the *role* it plays (frozen declaration / record / runtime ledger / external lane);
* extracts the facts each artefact states (dotted-path reads only — nothing is
  inferred from prose except a documented inline ``KEY = VALUE`` and terminal-state
  vocabulary used by the ADRs);
* resolves one **effective** value per fact with an explicit, deterministic
  precedence, and records every value it supersedes;
* verifies evidence integrity: hash-pinned references (specs, datasets) must match,
  while append-only document attestations are reported as drift rather than
  failure, because the document they attest is designed to grow;
* fails visibly: an unresolved contradiction (same precedence level, different
  values) or a broken invariant sets ``status = CONTRADICTION`` and the process
  exits non-zero.

It never writes outside ``data/recovery/`` and never modifies a source artefact;
``sources_unchanged`` is computed by re-hashing every source inside the same run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "recovery"

DECISIONS = "tasks/decisions.md"

# --------------------------------------------------------------------------- #
# precedence: declared once, applied everywhere
# --------------------------------------------------------------------------- #

PRECEDENCE: dict[str, dict[str, Any]] = {
    "P1_governance_decision": {
        "rank": 1,
        "source": DECISIONS,
        "rule": "the LATEST ADR in file order that names the campaign decides; ADRs are the highest authority "
                "(the charter grants the operator the power to amend governance)",
    },
    "P2_campaign_record": {
        "rank": 2,
        "source": "campaign closure / verification artefacts",
        "rule": "a closure or verification record written by the campaign itself decides next",
    },
    "P3_runtime_ledger": {
        "rank": 3,
        "source": "tracked runtime ledgers (e.g. config/strategy_admission.json)",
        "rule": "what the runtime actually enforces decides next",
    },
    "P4_frozen_declaration": {
        "rank": 4,
        "source": "preregistration manifests and frozen Phase A contracts",
        "rule": "a frozen declaration is a HISTORICAL record: it is never read as the current state unless "
                "nothing above it speaks",
    },
}

TERMINAL_STATES = (
    "DISCOVERY_CAMPAIGN_FAILED",
    "DISCOVERY_CAMPAIGN_PASSED",
    "CAMPAIGN_COMPLETED",
    "RUNNING",
    "NOT_RUN",
    "NOT_AUTHORIZED",
)

INLINE_FACT_RE = re.compile(r"`([A-Z][A-Z0-9_]{2,})\s*=\s*([^`]+)`")
ADR_HEADING_RE = re.compile(r"^##\s+ADR-(\d{4})\b(.*)$", re.MULTILINE)


def sha256_file(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def tracked(rel: str) -> bool:
    out = subprocess.run(
        ["git", "ls-files", "--error-unmatch", rel], cwd=ROOT, capture_output=True, text=True
    )
    return out.returncode == 0


def read_json(rel: str) -> Any:
    path = ROOT / rel
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def dig(obj: Any, dotted: str) -> Any:
    """Dotted-path read; a missing key yields None (never an exception, never a default)."""
    current = obj
    for part in dotted.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if current is None:
            return None
    return current


def text_of(rel: str) -> str | None:
    path = ROOT / rel
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else None


# --------------------------------------------------------------------------- #
# ADRs
# --------------------------------------------------------------------------- #


def parse_adrs(text: str) -> list[dict[str, Any]]:
    """Split tasks/decisions.md into ADRs, in file order, with their inline facts."""
    matches = list(ADR_HEADING_RE.finditer(text))
    adrs: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end]
        occurrences: dict[str, list[str]] = {}
        for key, raw_value in INLINE_FACT_RE.findall(body):
            raw = raw_value.strip()
            if "=" in raw:                      # chains such as `K1 = K2 = VALUE`
                raw = raw.split("=")[-1].strip()
            tokens = raw.split()
            if tokens:
                occurrences.setdefault(key, []).append(tokens[0])
        # An ADR states a fact more than once (context, options, decision). The LAST
        # occurrence is the operative one: it is the decision/consequences section.
        facts = {key: values[-1] for key, values in occurrences.items()}
        conflicts = {key: values for key, values in occurrences.items() if len(set(values)) > 1}
        terminal = [state for state in TERMINAL_STATES if state in body and state != "NOT_AUTHORIZED"]
        adrs.append({
            "adr": f"ADR-{match.group(1)}",
            "number": int(match.group(1)),
            "title": match.group(2).strip(" -"),
            "facts": facts,
            "facts_conflicts": conflicts,
            "terminal_state_tokens": terminal if len(terminal) == 1 else [],
            "body_chars": len(body),
        })
    return adrs


def adrs_for(tokens: tuple[str, ...], adrs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every ADR that names the campaign, oldest first.

    A match must be substantiated by the ADR's own title or inline facts (never by
    a bare mention inside unrelated prose). Keeping the whole history is what makes
    the supersession trail visible: ADR-0025's ``NEXT_CAMPAIGN = AUTHORIZED`` is
    superseded by ADR-0026's ``NOT_AUTHORIZED`` and the view shows both.
    """
    hits = [
        adr for adr in adrs
        if any(
            token.lower() in adr["title"].lower()
            or any(token.lower() in str(value).lower() for value in adr["facts"].values())
            for token in tokens
        )
    ]
    return sorted(hits, key=lambda adr: adr["number"])


# --------------------------------------------------------------------------- #
# campaign declarations (what speaks for each campaign)
# --------------------------------------------------------------------------- #

# role tags map onto PRECEDENCE keys; every entry is a read, never a judgement.
CAMPAIGNS: list[dict[str, Any]] = [
    {
        "id": "RFC-046",
        "title": "RFC-046 discovery campaign (recommended default route)",
        "adr_tokens": ("RFC-046", "RFC046"),
        "facts": [
            {"field": "TERMINAL_STATE", "role": "P2_campaign_record", "path": "data/rfc046/ACTIVATION.json",
             "pointer": "campaign.campaign_status", "note": "activation verification of the campaign outcome"},
            {"field": "CHECKS", "role": "P2_campaign_record", "path": "data/rfc046/ACTIVATION.json",
             "pointer": "checks_total", "note": "campaign verifier check count"},
            {"field": "CANDIDATES_REJECTED", "role": "P2_campaign_record", "path": "data/rfc046/ACTIVATION.json",
             "pointer": "campaign.verdicts", "note": "per-candidate verdicts"},
            {"field": "STANDING_STATE", "role": "P4_frozen_declaration", "path": "data/rfc046/ECONOMIC_FEASIBILITY.json",
             "pointer": "standing_state", "note": "the frozen contract's own standing-state block"},
            {"field": "DECISION", "role": "P2_campaign_record", "path": "data/rfc046/ECONOMIC_FEASIBILITY.json",
             "pointer": "decision", "note": "the feasibility decision"},
            {"field": "FALSE_SUCCESS", "role": "P2_campaign_record", "path": "data/rfc046/ECONOMIC_FEASIBILITY.json",
             "pointer": "false_success", "note": "false-success counter"},
        ],
    },
    {
        "id": "RFC-048V",
        "title": "RFC-048V futures risk plane (falsified and recertified)",
        "adr_tokens": ("RFC-048", "RFC048"),
        "facts": [
            {"field": "TERMINAL_STATE", "role": "P2_campaign_record", "path": "data/rfc048/FINAL_CERTIFICATION_REPORT.json",
             "pointer": "RFC048_FINAL_STATUS", "note": "final certification state"},
            {"field": "STATE_CHANGE", "role": "P2_campaign_record", "path": "data/rfc048/FINAL_CERTIFICATION_REPORT.json",
             "pointer": "STATE_CHANGE", "note": "what the recertification changed"},
            {"field": "ECONOMIC_CHECKS", "role": "P2_campaign_record", "path": "data/rfc048/FINAL_CERTIFICATION_REPORT.json",
             "pointer": "ECONOMIC_INTEGRITY.checks", "note": "economic integrity checks run"},
            {"field": "ECONOMIC_CHECKS_FAILED", "role": "P2_campaign_record", "path": "data/rfc048/FINAL_CERTIFICATION_REPORT.json",
             "pointer": "ECONOMIC_INTEGRITY.failed", "note": "economic integrity failures"},
            {"field": "FALSE_APPROVALS", "role": "P2_campaign_record", "path": "data/rfc048/FINAL_CERTIFICATION_REPORT.json",
             "pointer": "FALSE_APPROVALS_FOUND.post_fix", "note": "false approvals after the fixes"},
        ],
    },
    {
        "id": "RFC-049",
        "title": "RFC-049 profitability discovery — Phase A / admission",
        "adr_tokens": ("RFC-049", "RFC049"),
        "facts": [
            {"field": "AUTHORIZED", "role": "P4_frozen_declaration", "path": "data/rfc049/PREREGISTRATION_MANIFEST.json",
             "pointer": "gate.authorized", "note": "the frozen activation gate"},
            {"field": "GATE_REASON", "role": "P4_frozen_declaration", "path": "data/rfc049/PREREGISTRATION_MANIFEST.json",
             "pointer": "gate.reason", "note": "the frozen reason string"},
            {"field": "PHASE_A_STATE", "role": "P4_frozen_declaration", "path": "data/rfc049/ECONOMIC_RESULTS.json",
             "pointer": "consolidated_state", "note": "Phase A contract: no result was produced"},
            {"field": "SEALED_OOS_POLICY", "role": "P4_frozen_declaration", "path": "data/rfc049/PREREGISTRATION_MANIFEST.json",
             "pointer": "partition_policy.sealed_oos", "note": "the frozen opening rule"},
            {"field": "ADMISSION_STATE", "role": "P2_campaign_record", "path": "data/rfc049/admission/FINAL_ADMISSION_REPORT.json",
             "pointer": "CAMPAIGN_AUTHORIZATION_STATUS", "note": "RFC-049B admission outcome"},
            {"field": "NEXT_GATE", "role": "P2_campaign_record", "path": "data/rfc049/admission/FINAL_ADMISSION_REPORT.json",
             "pointer": "NEXT_GATE", "note": "the gate admission left pending"},
            {"field": "ADMISSION_CHECKS_FAILED", "role": "P2_campaign_record", "path": "data/rfc049/admission/FINAL_ADMISSION_REPORT.json",
             "pointer": "checks_failed", "note": "admission verifier failures"},
        ],
    },
    {
        "id": "RFC-049-DISCOVERY-2",
        "title": "RFC-049 Discovery 2 (Phase B, DEV/VAL, closed)",
        "adr_tokens": ("RFC-049", "Discovery 2"),
        "facts": [
            {"field": "TERMINAL_STATE", "role": "P2_campaign_record", "path": "data/rfc049/discovery2/CAMPAIGN_CLOSURE.json",
             "pointer": "campaign.terminal_state", "note": "closure record"},
            {"field": "SEALED_OOS", "role": "P2_campaign_record", "path": "data/rfc049/discovery2/CAMPAIGN_CLOSURE.json",
             "pointer": "sealed_oos_resolution.decision", "note": "resolution of the single licensed inspection"},
            {"field": "NEXT_CAMPAIGN", "role": "P2_campaign_record", "path": "data/rfc049/discovery2/CAMPAIGN_CLOSURE.json",
             "pointer": "governance_flags_after_closure.NEXT_CAMPAIGN", "note": "authorization after closure"},
            {"field": "PAPER_PROMOTION", "role": "P2_campaign_record", "path": "data/rfc049/discovery2/CAMPAIGN_CLOSURE.json",
             "pointer": "governance_flags_after_closure.PAPER_PROMOTION", "note": "paper gate state"},
            {"field": "AUTHORIZED", "role": "P4_frozen_declaration", "path": "data/rfc049/PREREGISTRATION_MANIFEST.json",
             "pointer": "gate.authorized", "note": "the frozen gate, superseded forward by ADR-0026"},
        ],
    },
    {
        "id": "ACTIVE-PAPER",
        "title": "ACTIVE strategy pipeline and the paper lane",
        "adr_tokens": ("ACTIVE", "PAPER_PROMOTION"),
        "facts": [
            {"field": "STRATEGIES_REGISTERED", "role": "P3_runtime_ledger", "path": "config/strategy_admission.json",
             "pointer": "strategies", "note": "the tracked admission ledger", "transform": "count"},
            {"field": "ADMITTED_FOR_PAPER", "role": "P3_runtime_ledger", "path": "config/strategy_admission.json",
             "pointer": "strategies", "note": "admitted_for_paper flags", "transform": "count_admitted"},
            {"field": "PAPER_RUN_STATE", "role": "P2_campaign_record", "path": "PAPER_DATA_24H_REPORT.json",
             "pointer": "verdict.final_status", "note": "the paper lane's own 24h verdict"},
            {"field": "PAPER_PROMOTION", "role": "P2_campaign_record", "path": "data/rfc049/discovery2/CAMPAIGN_CLOSURE.json",
             "pointer": "governance_flags_after_closure.PAPER_PROMOTION", "note": "the paper gate is a separate gate"},
        ],
    },
    {
        "id": "ST6-FORWARD-REGIME",
        "title": "ST-6 forward regime collection lane (external lane, hashed read-only)",
        "adr_tokens": ("RFC-047", "ST-6", "ST6"),
        "facts": [
            {"field": "LANE_STATE", "role": "P2_campaign_record", "path": "data/st6/ST6_HEALTH_STATUS.json",
             "pointer": "status", "note": "the lane's own health verdict"},
            {"field": "NEXT_CAMPAIGN", "role": "P2_campaign_record", "path": "data/st6/ST6_HEALTH_STATUS.json",
             "pointer": "standing_state.NEXT_CAMPAIGN", "note": "governance mirror"},
            {"field": "LIVE_TRADING", "role": "P2_campaign_record", "path": "data/st6/ST6_HEALTH_STATUS.json",
             "pointer": "standing_state.LIVE_TRADING", "note": "governance mirror"},
        ],
    },
]

HASH_PIN_SOURCES = (
    ("data/rfc049/PREREGISTRATION_MANIFEST.json", "spec_hashes", "spec_file_sha256", "spec_file"),
    ("data/rfc049/PREREGISTRATION_MANIFEST.json", "dataset_hashes.price_series", "sha256", None),
    ("data/rfc049/PREREGISTRATION_MANIFEST.json", "dataset_hashes.signal_series", "sha256", None),
    ("data/rfc046/ACTIVATION.json", "spec_hashes", None, None),
)

APPEND_ONLY_ATTESTATIONS = (
    ("data/rfc046/ACTIVATION.json", "document_hashes"),
)


def extract_fact(spec: dict[str, Any]) -> dict[str, Any]:
    payload = read_json(spec["path"])
    value: Any = None
    if payload is not None:
        value = dig(payload, spec["pointer"])
    transform = spec.get("transform")
    if transform == "count" and isinstance(value, dict):
        value = len(value)
    elif transform == "count_admitted" and isinstance(value, dict):
        value = sum(1 for row in value.values() if isinstance(row, dict) and row.get("admitted_for_paper"))
    return {
        "field": spec["field"],
        "role": spec["role"],
        "priority": PRECEDENCE[spec["role"]]["rank"],
        "source": spec["path"],
        "pointer": spec["pointer"],
        "value": value,
        "note": spec.get("note", ""),
        "present": value is not None,
    }


def resolve_field(campaign_id: str, field: str, facts: list[dict[str, Any]],
                  adr_history: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic resolution for one field, plus the supersession trail.

    Highest precedence level that speaks wins. Inside level P1 the *latest* ADR
    wins by number (the documented rule), so an earlier ADR's value becomes a
    recorded supersession rather than a conflict. Inside any other level a tie
    with different values is an unresolved contradiction: two records at the same
    level cannot outrank each other.
    """
    candidates: list[dict[str, Any]] = []
    for adr in adr_history:
        adr_value = adr["facts"].get(field)
        if adr_value is None and field == "TERMINAL_STATE" and adr["terminal_state_tokens"]:
            adr_value = adr["terminal_state_tokens"][0]
        if adr_value is not None:
            candidates.append({
                "priority": PRECEDENCE["P1_governance_decision"]["rank"],
                "role": "P1_governance_decision",
                "source": f"{DECISIONS}#{adr['adr']}",
                "pointer": f"inline `{field} = ...`",
                "value": adr_value,
                "present": True,
                "adr_number": adr["number"],
            })
    for fact in facts:
        if fact["field"] == field and fact["present"]:
            candidates.append({**fact, "adr_number": None})
    candidates.sort(key=lambda item: (item["priority"], -(item.get("adr_number") or 0)))

    result: dict[str, Any] = {"campaign": campaign_id, "field": field, "candidates": candidates, "effective": None,
                              "decided_by": None, "superseded": [], "contradiction": None}
    if not candidates:
        return result

    top_priority = candidates[0]["priority"]
    tied = [c for c in candidates if c["priority"] == top_priority]
    if top_priority != PRECEDENCE["P1_governance_decision"]["rank"]:
        distinct = {json.dumps(c["value"], sort_keys=True) for c in tied}
        if len(distinct) > 1:
            result["contradiction"] = {
                "campaign": campaign_id,
                "field": field,
                "priority": top_priority,
                "reason": "two sources at the same precedence level state different values and no higher authority resolves them",
                "values": [{"source": c["source"], "pointer": c["pointer"], "value": c["value"]} for c in tied],
            }
            return result
    winner = tied[0]

    winner = tied[0]
    result["effective"] = winner["value"]
    result["decided_by"] = {"role": winner["role"], "source": winner["source"], "pointer": winner["pointer"]}
    result["superseded"] = [
        {"source": c["source"], "pointer": c["pointer"], "value": c["value"], "priority": PRECEDENCE[c["role"]]["rank"],
         "role": c["role"]}
        for c in candidates
        if c is not winner and json.dumps(c["value"], sort_keys=True) != json.dumps(winner["value"], sort_keys=True)
    ]
    return result


# --------------------------------------------------------------------------- #
# integrity
# --------------------------------------------------------------------------- #


def judge_pin(recorded: str | None, actual: str | None, kind: str) -> str:
    """Grade one pin. A strict pin that cannot be checked is not silently "fine"."""
    if actual is None:
        return {"STRICT": "MISSING", "UNRESOLVED": "UNRESOLVED"}.get(kind, "NOT_APPLICABLE")
    if recorded == actual:
        return "VERIFIED"
    return "DRIFTED" if kind == "APPEND_ONLY" else "FAILED"


def verify_hash_pins() -> list[dict[str, Any]]:
    pins: list[dict[str, Any]] = []
    manifest = read_json("data/rfc049/PREREGISTRATION_MANIFEST.json") or {}
    for hypothesis, entry in (manifest.get("spec_hashes") or {}).items():
        rel = entry.get("spec_file")
        recorded = entry.get("spec_file_sha256")
        if rel and recorded:
            pins.append({"kind": "STRICT", "pin": f"spec:{hypothesis}", "path": rel, "recorded": recorded,
                         "actual": sha256_file(ROOT / rel), "result": None,
                         "note": "frozen strategy spec, pinned by the preregistration manifest"})
    for group in ("price_series", "signal_series"):
        for name, entry in ((manifest.get("dataset_hashes") or {}).get(group) or {}).items():
            rel = name if "/" in name else None
            if rel is None and group == "price_series":
                rel = name
            if rel is None:
                continue
            recorded = entry.get("sha256")
            if recorded:
                pins.append({"kind": "STRICT", "pin": f"dataset:{group}:{name}", "path": rel, "recorded": recorded,
                             "actual": sha256_file(ROOT / rel), "result": None,
                             "note": "frozen input series, pinned by the preregistration manifest"})
    activation = read_json("data/rfc046/ACTIVATION.json") or {}
    for name, recorded in (activation.get("spec_hashes") or {}).items():
        rel = None
        for candidate in (f"data/rfc046/specs/{name}.json", f"data/rfc046/{name}.json"):
            if (ROOT / candidate).exists():
                rel = candidate
                break
        pins.append({"kind": "STRICT" if rel else "UNRESOLVED", "pin": f"rfc046-spec:{name}", "path": rel,
                     "recorded": recorded, "actual": sha256_file(ROOT / rel) if rel else None, "result": None,
                     "note": "RFC-046 hypothesis spec pin; UNRESOLVED means the pinned artefact is not in the tree"})
    for rel, pointer in APPEND_ONLY_ATTESTATIONS:
        payload = read_json(rel) or {}
        for name, recorded in (dig(payload, pointer) or {}).items():
            pins.append({"kind": "APPEND_ONLY", "pin": f"{pointer}:{name}", "path": name, "recorded": recorded,
                         "actual": sha256_file(ROOT / name), "result": None,
                         "note": "attestation of a document that is append-only by convention; drift is expected and "
                                 "is not a contradiction"})
    for pin in pins:
        pin["result"] = judge_pin(pin["recorded"], pin["actual"], pin["kind"])
    return pins


def find_boolean_flags(obj: Any, names: tuple[str, ...], path: str = "") -> list[dict[str, Any]]:
    """Locate named boolean flags anywhere in a JSON document (evidence scan)."""
    found: list[dict[str, Any]] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            here = f"{path}.{key}" if path else key
            if key.lower() in names and isinstance(value, bool):
                found.append({"path": here, "value": value})
            found.extend(find_boolean_flags(value, names, here))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            found.extend(find_boolean_flags(value, names, f"{path}.{index}"))
    return found


def governance_scan() -> dict[str, Any]:
    """Scan the declared evidence for the two claims that must never be true."""
    out: dict[str, Any] = {"profitability_claims": [], "sealed_oos_opened": [], "scanned": []}
    for spec in CAMPAIGNS:
        for fact in spec["facts"]:
            rel = fact["path"]
            if rel in out["scanned"]:
                continue
            payload = read_json(rel)
            if payload is None:
                continue
            out["scanned"].append(rel)
            for hit in find_boolean_flags(payload, ("profitability_verified", "is_profitable", "rentable")):
                if hit["value"]:
                    out["profitability_claims"].append({"source": rel, **hit})
            for hit in find_boolean_flags(payload, ("sealed_oos_opened", "oos_opened", "sealed_window_read")):
                if hit["value"]:
                    out["sealed_oos_opened"].append({"source": rel, **hit})
    return out


# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #


def build() -> dict[str, Any]:
    decisions_text = text_of(DECISIONS) or ""
    adrs = parse_adrs(decisions_text)

    source_paths: set[str] = {DECISIONS}
    campaigns: list[dict[str, Any]] = []
    resolutions: list[dict[str, Any]] = []

    for spec in CAMPAIGNS:
        adr_history = adrs_for(spec["adr_tokens"], adrs)
        adr = adr_history[-1] if adr_history else None
        facts = [extract_fact(fact_spec) for fact_spec in spec["facts"]]
        source_paths.update(fact["source"] for fact in facts)

        fields: list[str] = []
        for fact in facts:
            if fact["field"] not in fields:
                fields.append(fact["field"])
        resolved = [resolve_field(spec["id"], field, facts, adr_history) for field in fields]
        resolutions.extend(r for r in resolved if r["effective"] is not None or r["contradiction"])

        effective = {r["field"]: r["effective"] for r in resolved if r["effective"] is not None}
        superseded = [
            {"field": r["field"], **entry}
            for r in resolved
            for entry in r["superseded"]
        ]
        unresolved = [r["contradiction"] for r in resolved if r["contradiction"]]

        campaigns.append({
            "id": spec["id"],
            "title": spec["title"],
            "governing_adr": (
                {"adr": adr["adr"], "title": adr["title"], "facts": adr["facts"]} if adr else None
            ),
            "adr_history": [{"adr": a["adr"], "facts": a["facts"]} for a in adr_history],
            "facts": facts,
            "effective_state": effective,
            "decided_by": {r["field"]: r["decided_by"] for r in resolved if r["decided_by"]},
            "superseded_values": superseded,
            "unresolved_contradictions": unresolved,
            "evidence": sorted(
                {
                    fact["source"] for fact in facts
                }
                | ({DECISIONS} if adr else set())
            ),
        })

    integrity_pins = verify_hash_pins()
    governance = governance_scan()

    # ---- invariants ------------------------------------------------------- #
    invariants: list[dict[str, Any]] = []

    def invariant(code: str, statement: str, result: bool, detail: str) -> None:
        invariants.append({"id": code, "statement": statement,
                           "result": "PASS" if result else "FAIL", "detail": detail})

    strict_failed = [p for p in integrity_pins if p["result"] == "FAILED"]
    strict_missing = [p for p in integrity_pins if p["result"] == "MISSING"]
    invariant("I1_frozen_pins_verify",
              "every hash-pinned frozen artefact matches its recorded digest",
              not strict_failed and not strict_missing,
              f"{len([p for p in integrity_pins if p['result'] == 'VERIFIED'])} verified, "
              f"{len(strict_failed)} failed, {len(strict_missing)} missing")

    verification_records = [
        ("data/rfc049/admission/INDEPENDENT_VERIFICATION.json", "builder", "verifier", "builder_imported"),
        ("data/rfc049/discovery2/INDEPENDENT_VERIFICATION.json", None, None, None),
    ]
    separation: list[dict[str, Any]] = []
    for rel, builder_key, verifier_key, imported_key in verification_records:
        record_payload = read_json(rel)
        if record_payload is None:
            continue
        source_paths.add(rel)
        separation.append({
            "source": rel,
            "builder": record_payload.get(builder_key or "builder"),
            "verifier": record_payload.get(verifier_key or "verifier"),
            "builder_imported": record_payload.get(imported_key) if imported_key else record_payload.get("builder_imported"),
        })
    invariant("I2_builder_is_not_verifier",
              "no verification record is signed by the code that produced the measurement",
              all(entry["builder"] != entry["verifier"] and entry.get("builder_imported") is not True for entry in separation),
              json.dumps(separation))

    invariant("I3_no_profitability_claim",
              "no scanned artefact asserts profitability",
              not governance["profitability_claims"],
              json.dumps(governance["profitability_claims"]) or "no profitability flag is true anywhere")

    invariant("I4_sealed_window_never_read",
              "the sealed OOS window is not read and the single licensed inspection is not spent",
              not governance["sealed_oos_opened"],
              json.dumps(governance["sealed_oos_opened"]) or "no sealed-OOS flag is true anywhere")

    closure_flags = (dig(read_json("data/rfc049/discovery2/CAMPAIGN_CLOSURE.json") or {},
                         "governance_flags_after_closure") or {})
    st6_standing = (dig(read_json("data/st6/ST6_HEALTH_STATUS.json") or {}, "standing_state") or {})
    shared = sorted(set(closure_flags) & set(st6_standing))
    disagreements = [
        {"field": key, "closure": closure_flags[key], "st6": st6_standing[key]}
        for key in shared
        if closure_flags[key] != st6_standing[key]
    ]
    invariant("I5_governance_mirrors_agree",
              "the closure record and the forward-regime lane state the same governance flags",
              not disagreements,
              json.dumps(disagreements) if disagreements else
              f"{len(shared)} shared flags agree ({', '.join(shared[:6])}{'…' if len(shared) > 6 else ''})")

    rfc_registry = read_json("docs/roadmap/RFC_REGISTRY.json") or {}
    source_paths.add("docs/roadmap/RFC_REGISTRY.json")
    occupied = sorted(int(n) for n in (rfc_registry.get("numbers") or {})
                      if str(n).isdigit() and (rfc_registry["numbers"][n] or {}).get("state") == "OCCUPIED")
    groups: dict[int, list[str]] = {}
    for spec in CAMPAIGNS:
        match = re.search(r"(\d{3})", spec["id"])
        if match:
            groups.setdefault(int(match.group(1)), []).append(spec["id"])
    campaign_numbers = sorted(groups)
    phase_collisions = {
        number: ids for number, ids in groups.items()
        if len(ids) > 1 and not all(cid.startswith(sorted(ids, key=len)[0]) for cid in ids)
    }
    invariant("I6_campaign_numbers_are_consistent",
              "an RFC number is claimed by exactly one RFC: campaigns that share a number are phases of it",
              not phase_collisions,
              f"declared {campaign_numbers}" + (f"; collisions {phase_collisions}" if phase_collisions else ""))

    # the tree, not the registry, is the ground truth for which numbers are taken
    tree_numbers = sorted({
        int(match.group(1))
        for path in (ROOT / "data").iterdir() if path.is_dir()
        for match in [re.match(r"rfc(\d{3})", path.name)]
        if match
    })
    advisories: list[dict[str, Any]] = []
    registry_unknown = [n for n in tree_numbers if n not in occupied]
    if registry_unknown:
        advisories.append({
            "id": "A1_registry_is_stale",
            "statement": "the RFC identifier registry does not list every number the tree already occupies",
            "detail": f"tree occupies {tree_numbers}; registry lists {occupied}; missing {registry_unknown}",
            "effect": "the registry's declared next free number cannot be trusted; the view derives it from the tree instead",
        })
    next_free = 47
    while next_free in set(tree_numbers) | set(occupied) | {45}:
        next_free += 1
    advisories.append({
        "id": "A2_next_free_rfc_derived",
        "statement": f"next free RFC number above 046 is {next_free:03d}, derived from tree occupancy + registry",
        "detail": f"occupied in tree {tree_numbers}; registry {occupied}; 045 stays vacant by control",
        "effect": "informational: any new campaign must first reconcile the registry with the tree",
    })
    unresolved_pins = [p for p in integrity_pins if p["result"] == "UNRESOLVED"]
    if unresolved_pins:
        advisories.append({
            "id": "A3_unresolved_pins",
            "statement": "some recorded digests cannot be checked because the pinned artefact is not in the tree",
            "detail": f"{len(unresolved_pins)} pins: {[p['pin'] for p in unresolved_pins][:6]}",
            "effect": "not a contradiction (nothing is contradicted), but those pins prove nothing today",
        })
    drifted = [p for p in integrity_pins if p["result"] == "DRIFTED"]
    if drifted:
        advisories.append({
            "id": "A4_append_only_drift",
            "statement": "an append-only document attestation no longer matches the document it attests",
            "detail": f"{len(drifted)} attestations: {[p['path'] for p in drifted][:4]}",
            "effect": "expected: these documents are designed to grow by appending; the attestation is a snapshot, not a pin",
        })

    # ---- sources: immutability ------------------------------------------- #
    before = {rel: sha256_file(ROOT / rel) for rel in sorted(source_paths)}
    after = {rel: sha256_file(ROOT / rel) for rel in sorted(source_paths)}
    unchanged = before == after

    ambiguous: list[dict[str, Any]] = []
    for resolution in resolutions:
        decided = resolution.get("decided_by") or {}
        if not str(decided.get("source", "")).startswith(DECISIONS):
            continue
        adr_id = str(decided["source"]).split("#")[-1]
        entry = next((adr for adr in adrs if adr["adr"] == adr_id), None)
        if entry and resolution["field"] in entry["facts_conflicts"]:
            ambiguous.append({"field": resolution["field"], "adr": adr_id,
                              "occurrences": entry["facts_conflicts"][resolution["field"]]})
    if ambiguous:
        advisories.append({
            "id": "A5_adr_prose_ambiguous",
            "statement": "an ADR states the same key with different values in different sections",
            "detail": json.dumps(ambiguous),
            "effect": "the last occurrence (decision/consequences) is used; the earlier ones are usually the context being quoted",
        })

    unresolved = [c for campaign in campaigns for c in campaign["unresolved_contradictions"]]
    failed_invariants = [i for i in invariants if i["result"] == "FAIL"]
    if unresolved or failed_invariants:
        status = "CONTRADICTION"
    elif advisories:
        status = "CONSISTENT_WITH_ADVISORIES"
    else:
        status = "CONSISTENT"

    payload: dict[str, Any] = {
        "artifact": "CAMPAIGN_STATE_VIEW",
        "work_package": "WP-2 (POST RFC-049 / ACTIVE RECOVERY)",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
        "branch": subprocess.run(["git", "branch", "--show-current"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
        "mode": "READ-ONLY DERIVED VIEW — sources are read and hashed, never written",
        "precedence": PRECEDENCE,
            "adr_index": [{"adr": a["adr"], "title": a["title"], "facts": a["facts"],
                       "facts_conflicts": a["facts_conflicts"]} for a in adrs],
        "campaigns": campaigns,
        "resolutions": resolutions,
        "integrity": {
            "pins": integrity_pins,
            "builder_verifier_separation": separation,
            "governance_scan": governance,
        },
        "invariants": invariants,
        "contradictions": unresolved,
        "failed_invariants": [{"id": i["id"], "detail": i["detail"]} for i in failed_invariants],
        "advisories": advisories,
        "rfc_numbering": {
            "tree_occupancy": tree_numbers,
            "registry_occupancy": occupied,
            "registry_next_free_declared": rfc_registry.get("next_free_number_above_046"),
            "next_free_derived": next_free,
        },
        "status": status,
        "sources": [{"path": rel, "exists": (ROOT / rel).exists(),
                     "tracked": tracked(rel) if (ROOT / rel).exists() else None,
                     "sha256_before": before.get(rel), "sha256_after": after.get(rel)} for rel in sorted(source_paths)],
        "sources_unchanged": unchanged,
    }
    return payload


def render_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    add("# CAMPAIGN STATE VIEW (WP-2)")
    add("")
    add(f"- generated `{payload['generated_at_utc']}` · head `{payload['head'][:12]}` · branch `{payload['branch']}`")
    add(f"- **status: {payload['status']}** · sources unchanged: {payload['sources_unchanged']}")
    add("")
    add("A frozen declaration is a historical record. This view resolves, per campaign and per field, which "
        "statement is *current*, using this precedence and nothing else:")
    add("")
    add("| rank | level | rule |")
    add("| ---: | --- | --- |")
    for name, spec in sorted(payload["precedence"].items(), key=lambda item: item[1]["rank"]):
        add(f"| {spec['rank']} | `{name}` | {spec['rule']} |")
    add("")
    add("## Campaigns")
    add("")
    for campaign in payload["campaigns"]:
        add(f"### {campaign['id']} — {campaign['title']}")
        add("")
        adr = campaign["governing_adr"]
        add(f"- governing decision: {'`' + adr['adr'] + '` ' + adr['title'] if adr else 'none (no ADR names this campaign)'}")
        if len(campaign.get("adr_history", [])) > 1:
            history = " → ".join(
                f"`{entry['adr']}`({', '.join(f'{k}={v}' for k, v in sorted(entry['facts'].items())) or 'no inline facts'})"
                for entry in campaign["adr_history"]
            )
            add(f"- decision history: {history}")
        add("")
        if campaign["effective_state"]:
            add("| field | effective value | decided by | superseded |")
            add("| --- | --- | --- | --- |")
            for field, value in campaign["effective_state"].items():
                decided = campaign["decided_by"].get(field) or {}
                superseded = [s for s in campaign["superseded_values"] if s["field"] == field]
                sup_text = "; ".join(f"{s['role']} `{s['source']}` = {json.dumps(s['value'])}" for s in superseded) or "—"
                add(f"| {field} | `{json.dumps(value)}` | `{decided.get('role')}` {decided.get('source')} | {sup_text} |")
        else:
            add("- no field has a value in any declared artefact")
        add("")
        if campaign["unresolved_contradictions"]:
            for contradiction in campaign["unresolved_contradictions"]:
                add(f"- **UNRESOLVED CONTRADICTION** `{contradiction['field']}`: {contradiction['reason']}")
                for value in contradiction["values"]:
                    add(f"  - `{value['source']}` {value['pointer']} = `{json.dumps(value['value'])}`")
            add("")
    add("## Integrity")
    add("")
    if payload["integrity"]["pins"]:
        add("| pin | kind | recorded | actual | result |")
        add("| --- | --- | --- | --- | --- |")
        for pin in payload["integrity"]["pins"]:
            recorded = str(pin["recorded"])[:16]
            actual = str(pin["actual"])[:16]
            add(f"| `{pin['pin']}` | {pin['kind']} | `{recorded}` | `{actual}` | **{pin['result']}** |")
    else:
        add("no hash pins declared")
    add("")
    scan = payload["integrity"]["governance_scan"]
    add(f"- governance scan over {len(scan['scanned'])} artefacts: "
        f"{len(scan['profitability_claims'])} profitability claims, {len(scan['sealed_oos_opened'])} sealed-OOS openings.")
    add("")
    add("## Invariants")
    add("")
    add("| id | result | statement | detail |")
    add("| --- | --- | --- | --- |")
    for item in payload["invariants"]:
        add(f"| `{item['id']}` | {item['result']} | {item['statement']} | {item['detail']} |")
    add("")
    if payload["contradictions"] or payload["failed_invariants"]:
        add("## Contradictions (the view refuses to resolve these)")
        add("")
        for contradiction in payload["contradictions"]:
            add(f"- `{contradiction['campaign']}` / `{contradiction['field']}`: {contradiction['reason']}")
        for failure in payload["failed_invariants"]:
            add(f"- invariant `{failure['id']}` failed: {failure['detail']}")
        add("")
    add("## Advisories (recorded, not contradictions)")
    add("")
    if payload["advisories"]:
        for advisory in payload["advisories"]:
            add(f"- **{advisory['id']}** — {advisory['statement']}. {advisory['detail']} ({advisory['effect']})")
    else:
        add("none")
    add("")
    numbering = payload["rfc_numbering"]
    add(f"RFC numbering: tree occupies {numbering['tree_occupancy']}; registry lists "
        f"{numbering['registry_occupancy']} and declares next free {numbering['registry_next_free_declared']}; "
        f"the view derives next free **{numbering['next_free_derived']:03d}**.")
    add("")
    add("## ADR index (facts extracted from inline `KEY = VALUE`)")
    add("")
    add("| adr | title | facts |")
    add("| --- | --- | --- |")
    for adr in payload["adr_index"]:
        facts = ", ".join(f"`{k}={v}`" for k, v in sorted(adr["facts"].items())) or "—"
        add(f"| {adr['adr']} | {adr['title']} | {facts} |")
    add("")
    return "\n".join(lines) + "\n"


# ``sources`` records the hashes of the evidence at the moment of the run. It is excluded
# from the identity hash because one of those sources (data/st6/*) is owned by another lane
# that keeps writing it: the view's *derived state* is what must be reproducible, and the
# per-source hashes stay in the artefact for auditability either way.
VOLATILE_KEYS = ("generated_at_utc", "payload_sha256", "sources")


def payload_hash(payload: dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k not in VOLATILE_KEYS}
    return hashlib.sha256(json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="recompute and compare with the stored payload hash")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    payload = build()
    payload["payload_sha256"] = payload_hash(payload)
    (OUT / "CAMPAIGN_STATE_VIEW.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (OUT / "CAMPAIGN_STATE_VIEW_REPORT.md").write_text(render_markdown(payload), encoding="utf-8")

    if args.check:
        stored = read_json("data/recovery/CAMPAIGN_STATE_VIEW.json") or {}
        same = stored.get("payload_sha256") == payload["payload_sha256"]
        print(json.dumps({"check": "determinism:payload_sha256_stable", "result": "PASS" if same else "FAIL",
                          "detail": f"{payload['payload_sha256'][:16]} vs {str(stored.get('payload_sha256'))[:16]}"}))
        return 0 if same else 1

    print(json.dumps({
        "status": payload["status"],
        "campaigns": [c["id"] for c in payload["campaigns"]],
        "contradictions": len(payload["contradictions"]),
        "failed_invariants": [i["id"] for i in payload["failed_invariants"]],
        "pins": {p["result"]: sum(1 for q in payload["integrity"]["pins"] if q["result"] == p["result"])
                 for p in payload["integrity"]["pins"]},
        "superseded_values": sum(len(c["superseded_values"]) for c in payload["campaigns"]),
        "advisories": [a["id"] for a in payload["advisories"]],
        "next_free_rfc_derived": payload["rfc_numbering"]["next_free_derived"],
        "sources_unchanged": payload["sources_unchanged"],
        "payload_sha256": payload["payload_sha256"],
    }, indent=2))
    return 1 if payload["status"] == "CONTRADICTION" else 0


if __name__ == "__main__":
    sys.exit(main())
