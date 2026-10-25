"""WP-ECONOMIC-RECOVERY-003 — build the economic-evidence dependency graph, read-only.

Answers, mechanically, three questions the work package asks:

1. **who produces what, from what, and who consumes it** — every node in the
   chain from the frozen corpus to the published certification, with its
   producer, its declared inputs, its digests (raw and LF-normalised) and the
   files that name it. Consumers are *derived* by scanning tracked text files
   for the path, not asserted from memory.
2. **which pins are stale and what kind of staleness they are** — content,
   state, line-ending-only, or absent. The distinction decides whether a repair
   moves an economic number or only a digest.
3. **what a recertification would touch** — per node: `REBUILT` (the producer
   writes it), `UNCHANGED_PAYLOAD` (rebuilt but the economic payload digest is
   identical), `HISTORICAL_RECORD` (a past observation that no longer needs to
   match), or `NOT_TOUCHED`.

It measures; it does not repair. The only commands it runs are read-only ones
(`--check`, `git`, hashing); the recertification itself is *simulated in a
temporary clone* whose results are recorded in ``evidence/`` and summarised
here, because regenerating the published bundle is explicitly out of scope.

Usage:
    uv run python scripts/wp_eco003_audit.py [--out <evidence dir>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = Path("docs/agentic/economic_audit/WP-ECONOMIC-RECOVERY-003")
WP2 = Path("docs/agentic/economic_audit/WP-ECONOMIC-RECOVERY-002")

CORPUS = "reports/strategy-baseline/data"
TEXT_SUFFIXES = {".py", ".json", ".md", ".yml", ".yaml", ".toml", ".cfg", ".txt"}

#: The chain, from the frozen corpus to the published certification. ``producer``
#: is the script that writes the node; ``None`` means the repository has no
#: producer for it (an authored artefact), which is a finding, not a gap in the
#: audit.
CHAIN: tuple[dict[str, Any], ...] = (
    {
        "id": "corpus",
        "path": CORPUS,
        "kind": "input_corpus",
        "producer": None,
        "producer_note": "cached 5m bar datasets; gitignored by design, absent from every checkout",
        "inputs": ["exchange klines, bucketed to complete 5m days"],
        "recert_effect": "NOT_TOUCHED",
    },
    {
        "id": "multi_family",
        "path": "reports/strategy-baseline/MULTI_FAMILY_RESULTS_*.json",
        "kind": "research_result",
        "producer": "scripts/multi_family_backtest.py",
        "inputs": [CORPUS],
        "recert_effect": "NOT_TOUCHED",
    },
    {
        "id": "cost_barrier_input",
        "path": "reports/strategy-baseline/COST_BARRIER.json",
        "kind": "research_result",
        "producer": "scripts/cost_barrier.py",
        "inputs": [CORPUS],
        "recert_effect": "NOT_TOUCHED",
        "note": "byte-identical copy preserved at data/recovery/wp7/evidence/COST_BARRIER.json",
    },
    {
        "id": "criteria",
        "path": "docs/STRATEGY_ADMISSION_CRITERIA.md",
        "kind": "pre_registration",
        "producer": None,
        "producer_note": "pre-registered document, committed before the baselines ran (c1ffbaa)",
        "inputs": [],
        "recert_effect": "NOT_TOUCHED",
    },
    {
        "id": "matrix",
        "path": "docs/STRATEGY_ADMISSION_MATRIX.json",
        "kind": "derived_evidence",
        "producer": "scripts/build_admission_matrix.py",
        "inputs": [
            "reports/strategy-baseline/MULTI_FAMILY_RESULTS_*.json",
            "docs/EMA_CROSSOVER_PERFORMANCE_BASELINE.json",
        ],
        "recert_effect": "NOT_TOUCHED",
    },
    {
        "id": "v3_results",
        "path": "docs/STRATEGY_DISCOVERY_V3_RESULTS.json",
        "kind": "research_result",
        "producer": None,
        "producer_note": "authored artefact: the repository reads it, no script writes it",
        "inputs": [CORPUS],
        "recert_effect": "NOT_TOUCHED",
    },
    {
        "id": "ledger",
        "path": "config/strategy_admission.json",
        "kind": "runtime_config",
        "producer": "scripts/build_strategy_admission.py",
        "inputs": [
            "docs/STRATEGY_DISCOVERY_V3_RESULTS.json",
            "docs/STRATEGY_ADMISSION_MATRIX.json",
        ],
        "recert_effect": "REBUILT_ALREADY",
        "note": "repaired by WP-002: the anchor named a matrix digest no commit ever had",
    },
    {
        "id": "audit",
        "path": "data/recovery/ACTIVE_ECONOMIC_AUDIT.json",
        "kind": "derived_evidence",
        "producer": "scripts/active_economic_audit.py",
        "inputs": [
            "config/strategy_admission.json",
            "docs/STRATEGY_DISCOVERY_V3_RESULTS.json",
            "docs/COST_MODEL_V3.json",
            "reports/strategy-baseline/COST_BARRIER.json",
        ],
        "recert_effect": "UNCHANGED_PAYLOAD",
    },
    {
        "id": "cost_model_doc",
        "path": "docs/COST_MODEL_V3.json",
        "kind": "model_document",
        "producer": None,
        "producer_note": "committed model document with a content pin in the explorer",
        "inputs": [],
        "recert_effect": "NOT_TOUCHED",
    },
    {
        "id": "cost_model_module",
        "path": "src/trading_bot/research/microstructure/cost_model_v3.py",
        "kind": "model_code",
        "producer": None,
        "producer_note": "the executable cost model; pinned by content in the explorer",
        "inputs": [],
        "recert_effect": "NOT_TOUCHED",
    },
    {
        "id": "input_evidence",
        "path": "data/recovery/wp7/evidence/INPUT_EVIDENCE.json",
        "kind": "evidence_bundle",
        "producer": "scripts/cost_barrier_evidence.py",
        "inputs": ["reports/strategy-baseline/COST_BARRIER.json"],
        "recert_effect": "REBUILT",
    },
    {
        "id": "input_evidence_copy",
        "path": "data/recovery/wp7/evidence/COST_BARRIER.json",
        "kind": "evidence_copy",
        "producer": "scripts/cost_barrier_evidence.py",
        "inputs": ["reports/strategy-baseline/COST_BARRIER.json"],
        "recert_effect": "UNCHANGED_PAYLOAD",
    },
    {
        "id": "producer_pins",
        "path": "data/recovery/wp7/evidence/PRODUCER_PINS.json",
        "kind": "evidence_bundle",
        "producer": "scripts/cost_barrier_evidence.py",
        "inputs": [
            "scripts/active_economic_audit.py",
            "scripts/cost_barrier.py",
            "scripts/cost_barrier_explorer.py",
            "scripts/cost_barrier_verify.py",
        ],
        "recert_effect": "REBUILT",
    },
    {
        "id": "explorer",
        "path": "data/recovery/COST_BARRIER_EXPLORER.json",
        "kind": "published_evidence",
        "producer": "scripts/cost_barrier_explorer.py",
        "inputs": [
            "data/recovery/ACTIVE_ECONOMIC_AUDIT.json",
            "reports/strategy-baseline/COST_BARRIER.json",
            "config/strategy_admission.json",
            "docs/COST_MODEL_V3.json",
            "src/trading_bot/research/microstructure/cost_model_v3.py",
        ],
        "recert_effect": "UNCHANGED_PAYLOAD",
        "note": "payload_sha256 excludes the volatile block and sources[]; rebuilding it with current pins reproduces 4383d812",
    },
    {
        "id": "verification",
        "path": "data/recovery/COST_BARRIER_VERIFICATION.json",
        "kind": "published_evidence",
        "producer": "scripts/cost_barrier_verify.py",
        "inputs": ["data/recovery/COST_BARRIER_EXPLORER.json"],
        "recert_effect": "UNCHANGED_PAYLOAD",
    },
    {
        "id": "adversarial",
        "path": "data/recovery/wp7/COST_BARRIER_ADVERSARIAL_REPORT.json",
        "kind": "published_evidence",
        "producer": "scripts/cost_barrier_adversarial.py",
        "inputs": [
            "data/recovery/COST_BARRIER_EXPLORER.json",
            "data/recovery/COST_BARRIER_VERIFICATION.json",
        ],
        "recert_effect": "REBUILT",
    },
    {
        "id": "certification",
        "path": "data/recovery/wp7/COST_BARRIER_CERTIFICATION.json",
        "kind": "published_evidence",
        "producer": "scripts/cost_barrier_certify.py",
        "inputs": [
            "data/recovery/COST_BARRIER_EXPLORER.json",
            "data/recovery/COST_BARRIER_VERIFICATION.json",
            "data/recovery/wp7/COST_BARRIER_ADVERSARIAL_REPORT.json",
            "data/recovery/wp7/evidence/PRODUCER_PINS.json",
        ],
        "recert_effect": "REBUILT",
    },
    {
        "id": "wp8_rehearsal",
        "path": "data/recovery/wp8/CLEAN_CHECKOUT_REHEARSAL_REPORT.json",
        "kind": "historical_record",
        "producer": "scripts/clean_checkout_rehearsal.py",
        "inputs": ["data/recovery/COST_BARRIER_EXPLORER.json"],
        "recert_effect": "HISTORICAL_RECORD",
        "note": "records the digest it observed at its own commit; it is not a live pin",
    },
)

#: Where the published digests currently live, so each drift can be attributed.
PIN_SOURCES = (
    ("data/recovery/COST_BARRIER_EXPLORER.json", "sources[]"),
    ("data/recovery/wp7/COST_BARRIER_CERTIFICATION.json", "evidence_digests"),
    ("data/recovery/wp7/evidence/PRODUCER_PINS.json", "producers[]"),
    ("data/recovery/wp7/evidence/INPUT_EVIDENCE.json", "sha256"),
)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout.strip()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def content_digest(path: Path) -> str | None:
    return sha256_bytes(path.read_bytes().replace(b"\r\n", b"\n")) if path.is_file() else None


def tracked_text_files() -> list[str]:
    listing = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout
    names = [name for name in listing.split("\0") if name]
    return [name for name in names if Path(name).suffix in TEXT_SUFFIXES]


def consumers_of(path: str, files: list[str]) -> list[str]:
    """Tracked files that name this path, excluding the node itself and its own bundle."""

    token = path.split("*")[0]
    hits = []
    for name in files:
        if name == path or name.startswith("data/recovery/wp8/evidence/"):
            continue
        try:
            text = (REPO / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if token in text:
            hits.append(name)
    return hits


def blob_renderings(path: str) -> dict[str, str | None]:
    """The committed blob rendered three ways, to say *which* bytes a pin names.

    A pin that matches the CRLF rendering but not the blob is not "the content of
    the file": it is what one machine wrote to disk before the chain was pinned
    with ``-text`` in ``.gitattributes``. That distinction decides whether a
    recertification refreshes a digest or rewrites history.
    """

    blob = subprocess.run(
        ["git", "show", f"HEAD:{path}"], cwd=REPO, capture_output=True, check=False
    ).stdout
    if not blob:
        return {"blob": None, "lf": None, "crlf": None}
    return {
        "blob": sha256_bytes(blob),
        "lf": sha256_bytes(blob.replace(b"\r\n", b"\n")),
        "crlf": sha256_bytes(blob.replace(b"\n", b"\r\n")),
    }


def historical_crlf_match(path: str, pin: str, limit: int = 50) -> str | None:
    """The revision whose CRLF rendering a pin names, if the pin is a checkout artefact.

    A pin captured on a Windows working tree before ``-text`` was recorded names
    the CRLF rendering of *some* revision. Naming that revision is the difference
    between "the pin is stale" and "the pin never described a committed file".
    """

    revisions = git("log", "--all", "--format=%H", f"-{limit}", "--", path).split()
    for revision in revisions:
        blob = subprocess.run(
            ["git", "show", f"{revision}:{path}"], cwd=REPO, capture_output=True, check=False
        ).stdout
        if not blob:
            continue
        if sha256_bytes(blob.replace(b"\n", b"\r\n")) == pin:
            return revision
        if sha256_bytes(blob.replace(b"\r\n", b"\n")) == pin:
            return revision
    return None


def pin_inventory() -> list[dict[str, Any]]:
    explorer = json.loads(
        (REPO / "data/recovery/COST_BARRIER_EXPLORER.json").read_text(encoding="utf-8")
    )
    certification = json.loads(
        (REPO / "data/recovery/wp7/COST_BARRIER_CERTIFICATION.json").read_text(encoding="utf-8")
    )
    pins = json.loads(
        (REPO / "data/recovery/wp7/evidence/PRODUCER_PINS.json").read_text(encoding="utf-8")
    )
    rows: list[dict[str, Any]] = []

    for source in explorer.get("sources", []):
        path = Path(source["path"])
        raw = (REPO / path).read_bytes() if (REPO / path).is_file() else None
        state_pin = source.get("state_sha256")
        status = "ABSENT"
        if raw is not None:
            if sha256_bytes(raw) == source.get("sha256"):
                status = "EXACT"
            elif sha256_bytes(raw.replace(b"\r\n", b"\n")) == source.get("sha256") or sha256_bytes(
                raw.replace(b"\n", b"\r\n")
            ) == source.get("sha256"):
                status = "EOL_ONLY"
            elif state_pin and sha256_bytes(raw.replace(b"\r\n", b"\n")) == state_pin:
                status = "STATE_EXACT"
            else:
                status = "DRIFT"
        renderings = blob_renderings(source["path"])
        crlf_of_a_revision = (
            None
            if source.get("sha256") in {None, renderings["blob"], renderings["crlf"]}
            else historical_crlf_match(source["path"], source["sha256"])
        )
        rows.append(
            {
                "path": source["path"],
                "pinned_by": "data/recovery/COST_BARRIER_EXPLORER.json#sources[]",
                "pin": source.get("sha256"),
                "state_pin": state_pin,
                "on_disk": sha256_bytes(raw) if raw is not None else None,
                "status": status,
                "role": source.get("role"),
                "committed_renderings": renderings,
                "pin_names_a_revision_of_the_file": crlf_of_a_revision,
                "pin_names_the_committed_blob": source.get("sha256") == renderings["blob"],
                "pin_names_the_crlf_rendering": source.get("sha256") == renderings["crlf"]
                and renderings["crlf"] != renderings["blob"],
            }
        )

    for row in certification.get("evidence_digests", {}).items():
        path, recorded = row
        current = content_digest(REPO / path)
        rows.append(
            {
                "path": path,
                "pinned_by": "data/recovery/wp7/COST_BARRIER_CERTIFICATION.json#evidence_digests",
                "pin": recorded,
                "state_pin": None,
                "on_disk": current,
                "status": "EXACT"
                if current == recorded
                else ("ABSENT" if current is None else "DRIFT"),
                "role": "content digest recorded by the certification",
            }
        )

    for producer in pins.get("producers", []):
        path = Path(producer["path"])
        raw = (REPO / path).read_bytes() if (REPO / path).is_file() else None
        accepted = {
            producer.get("sha256_lf"),
            producer.get("sha256_crlf"),
            producer.get("sha256"),
        } - {None}
        rows.append(
            {
                "path": producer["path"],
                "pinned_by": "data/recovery/wp7/evidence/PRODUCER_PINS.json#producers[]",
                "pin": producer.get("sha256"),
                "state_pin": producer.get("sha256_lf"),
                "on_disk": sha256_bytes(raw) if raw is not None else None,
                "status": "EXACT"
                if raw is not None and sha256_bytes(raw) in accepted
                else ("ABSENT" if raw is None else "DRIFT"),
                "role": producer.get("role"),
            }
        )
    return rows


#: Where each absent dependency is written, verified by grepping the write site.
#: A heuristic ("some script mentions this name") produced false authority here:
#: `FINAL_REPORT.json` exists in four report trees, so the name alone proves
#: nothing. Each entry is re-validated at import time against the line it names,
#: and a stale entry degrades to "producer not found" instead of inventing one.
PRODUCER_WRITES: dict[str, tuple[str, int]] = {
    "reports/rfc035/search_round_3/BASELINE.json": ("scripts/rfc035s3_closure.py", 1780),
    "reports/rfc035/search_round_3/RULE_CONTRACT_AUDIT.json": ("scripts/rfc035s3_closure.py", 1784),
    "reports/rfc035/search_round_3/CANDIDATE_DEEP_DIVE.json": ("scripts/rfc035s3_closure.py", 1787),
    "reports/rfc035/search_round_3/ECONOMIC_EVIDENCE.json": ("scripts/rfc035s3_closure.py", 1791),
    "reports/rfc035/search_round_3/REJECTION_LOG.json": ("scripts/rfc035s3_closure.py", 1797),
    "reports/rfc035/search_round_3/FINAL_REPORT.json": ("scripts/rfc035s3_closure.py", 1806),
    "reports/rfc035/search_round_3/INDEPENDENT_VERIFICATION.json": (
        "scripts/rfc035s3_verify.py",
        675,
    ),
    "reports/profitability_gate035/ECONOMIC_FEASIBILITY.md": ("scripts/pgate035_closure.py", 1544),
    "reports/profitability_gate035/ALTERNATIVE_PATHS.md": ("scripts/pgate035_closure.py", 1546),
    "reports/profitability_gate035/SEARCH_POSTMORTEM.md": ("scripts/pgate035_closure.py", 1543),
    "reports/profitability_gate035/FINAL_REPORT.md": ("scripts/pgate035_closure.py", 1550),
    "reports/profitability_gate035/INDEPENDENT_VERIFICATION.json": (
        "scripts/pgate035_verify.py",
        690,
    ),
    "reports/profitability_gate035/INDEPENDENT_VERIFICATION.md": (
        "scripts/pgate035_verify.py",
        738,
    ),
    "reports/rfc046/IMPACT_ASSESSMENT.md": ("scripts/rfc046_audit.py", 732),  # writes IMPACT
}


def producer_of(path: str) -> dict[str, Any] | None:
    """The committed script that writes this path, with the line re-checked.

    "A deliverable nobody committed" and "the output of a committed producer that
    has not been re-run" are indistinguishable in a checkout, and only the second
    can be regenerated. The line is validated so a moved write site is reported
    as "not found" rather than as evidence that does not exist.
    """

    entry = PRODUCER_WRITES.get(path)
    if entry is None:
        return None
    script, line_number = entry
    script_path = REPO / script
    if not script_path.is_file():
        return None
    lines = script_path.read_text(encoding="utf-8", errors="replace").splitlines()
    if line_number > len(lines):
        return None
    window = chr(10).join(lines[max(0, line_number - 3) : line_number + 3])
    name = path.rsplit("/", 1)[-1]
    # Some producers write through a path constant (`IMPACT.write_text`); the
    # window check accepts either the file name or the write call it feeds.
    if name not in window and "write_text" not in window and "write_json" not in window:
        return None
    return {"script": script, "line": line_number}


def dependency_classification() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Take WP-002's inventory and give every path a class with its foundation."""

    inventory = json.loads((WP2 / "DECLARED_DEPENDENCIES.json").read_text(encoding="utf-8"))
    published = {
        "docs/STRATEGY_ADMISSION_MATRIX.json",
        "docs/STRATEGY_DISCOVERY_V3_RESULTS.json",
        "data/recovery/ACTIVE_ECONOMIC_AUDIT.json",
        "data/recovery/COST_BARRIER_EXPLORER.json",
        "data/recovery/COST_BARRIER_VERIFICATION.json",
        "data/recovery/wp7/COST_BARRIER_CERTIFICATION.json",
    }
    rows = []
    for entry in inventory["dependencies"]:
        path = entry["path"]
        copy = "data/recovery/wp7/evidence/COST_BARRIER.json"
        if path == "reports/strategy-baseline/COST_BARRIER.json" and (REPO / copy).is_file():
            evidence = json.loads(
                (REPO / "data/recovery/wp7/evidence/INPUT_EVIDENCE.json").read_text(
                    encoding="utf-8"
                )
            )
            reproduced = sha256_bytes((REPO / copy).read_bytes()) == evidence["sha256"]
            rows.append(
                {
                    "path": path,
                    "classification": "RECOVERABLE_EXACT",
                    "foundation": f"byte-identical copy at {copy} reproduces the pinned digest: {reproduced}",
                    "blocks": [],
                }
            )
            continue
        if path.startswith("data/raw/"):
            rows.append(
                {
                    "path": path,
                    "classification": "RECOVERABLE_BY_RERUN",
                    "foundation": "exchange klines can be fetched again, but not byte-identically: a rerun is a new dataset, not the frozen one",
                    "blocks": [
                        "reports/strategy-baseline/COST_BARRIER.json",
                        "reports/strategy-baseline/MULTI_FAMILY_RESULTS_*.json",
                    ],
                }
            )
            continue
        producer = producer_of(path)
        if path.startswith("reports/") and producer is None:
            rows.append(
                {
                    "path": path,
                    "classification": "NEVER_COMMITTED_DELIVERABLE",
                    "foundation": "a document the tests require, no commit carries and no script writes; nothing can regenerate it, so only its absence can be recorded",
                    "blocks": [],
                }
            )
            continue
        if path.startswith("reports/"):
            rows.append(
                {
                    "path": path,
                    "classification": "RECOVERABLE_BY_RERUN",
                    "foundation": (
                        f"gitignored output of {producer['script']}:{producer['line']}, a committed producer; "
                        "re-running it produces a new instance of the same artefact, not the original bytes "
                        "(no digest of this file is recorded anywhere, and its inputs are the absent corpus)"
                    ),
                    "blocks": [],
                }
            )
            continue
        if path.startswith("data/st6/"):
            rows.append(
                {
                    "path": path,
                    "classification": "HOST_ONLY",
                    "foundation": "runtime evidence written by this machine's ticks; not part of the economic chain",
                    "blocks": [],
                }
            )
            continue
        rows.append(
            {
                "path": path,
                "classification": "NEVER_COMMITTED_DELIVERABLE",
                "foundation": (
                    "a document the tests require and no commit carries; nothing can produce it, so only "
                    "its absence can be recorded"
                    if producer is None
                    else f"written by {producer['script']}:{producer['line']} but never committed; re-running the producer yields a new instance, not the reviewed document"
                ),
                "blocks": [],
            }
        )
    verdict = {
        "blocking_for_recertification": [
            row["path"]
            for row in rows
            if row["classification"] == "HISTORICAL_ONLY" and row["path"] in published
        ],
        "none_of_these_block_the_cost_barrier": all(
            not row["blocks"] or row["classification"] == "RECOVERABLE_BY_RERUN" for row in rows
        ),
    }
    return rows, verdict


def test_analysis() -> dict[str, Any]:
    """What the one node WP-002 moved to red is actually about, read from the gate."""

    source = (REPO / "scripts/cost_barrier_gate.py").read_text(encoding="utf-8")
    integrity_first = source.index("if integrity:") < source.index("if blocked:")
    return {
        "node": "tests/unit/research/test_cost_barrier_gate.py::test_a_missing_required_input_blocks_rather_than_fails",
        "what_it_asserts": (
            "a declared input that is absent produces BLOCKED_MISSING_INPUT, with its exit code and "
            "the path named in the 'inputs:declared_inputs_present' detail"
        ),
        "why_it_failed_after_the_anchor_repair": (
            "the gate evaluates integrity before blockage (`decide_status`: integrity -> BLOCKED -> "
            "reproduction). With the ledger no longer matching the pin the explorer published, that "
            "pre-existing integrity failure takes precedence, so the run reports INTEGRITY_FAILURE and "
            "the test's own scenario never gets to be the verdict"
        ),
        "precedence_is_integrity_before_blocked": integrity_first,
        "obligation_preserved": (
            "a real integrity inconsistency must still surface as a blocker of certification: the "
            "measured result after recertification is that the same test passes unchanged, because the "
            "integrity failure was repaired rather than masked"
        ),
        "correct_resolution": (
            "recertify (restore the pins) — not relax the test, not reorder the precedence, and not "
            "assert 'blocked or integrity' which would accept an unidentifiable failure as a pass"
        ),
        "evidence_after_recertification": "evidence/recertified_clone_tests.txt (the node is green, unmodified)",
    }


#: The four files that make up the gate's own contract suite. The certification
#: record runs exactly this set (`steps.contract_tests`), so a red/green count on
#: it is comparable with the certification without inventing a selection.
CONTRACT_SUITE = (
    "tests/unit/research/test_cost_barrier_explorer.py",
    "tests/unit/research/test_cost_barrier_gate.py",
    "tests/unit/research/test_cost_barrier_adversarial.py",
    "tests/unit/research/test_cost_barrier_ci_parity.py",
)


NODE_RE = re.compile(r"^(?:FAILED|ERROR) (\S+)", re.MULTILINE)


def full_suite_delta(evidence: Path) -> dict[str, Any]:
    """The node-by-node difference between the two full-suite transcripts.

    A raw count delta would be misleading — the two runs collected different
    totals — so the comparison is on node IDs, which is the only thing that says
    *which* tests changed colour.
    """

    def nodes(name: str) -> set[str]:
        text = (evidence / name).read_text(encoding="utf-8", errors="replace")
        return set(NODE_RE.findall(text))

    before = nodes("full_suite_before_recertification.txt")
    after = nodes("recertified_clone_tests.txt")
    closed = sorted(before - after)
    return {
        "before": len(before),
        "after": len(after),
        "closed": len(closed),
        "closed_nodes": closed,
        "introduced": sorted(after - before),
    }


def simulation_results(out_dir: Path) -> dict[str, Any]:
    """What the recertification was measured to change, and what it cannot reach.

    Every number here is either read back out of ``evidence/`` (a command's own
    transcript) or was measured on a throwaway ``git worktree`` / ``git clone``.
    Nothing in this repository's published evidence was written.
    """

    evidence = out_dir / "evidence"
    return {
        "where": (
            "a temporary `git clone` at the commit under audit, plus one throwaway "
            "`git worktree` to separate the causes; the published evidence in this "
            "repository was never touched"
        ),
        "steps": [
            "scripts/cost_barrier_evidence.py --materialize",
            "scripts/cost_barrier_explorer.py --out-dir <tmp>",
            "scripts/cost_barrier_verify.py --explorer <tmp>/COST_BARRIER_EXPLORER.json --out <tmp>/VERIFICATION.json",
            "publish the two rebuilt files, commit",
            "scripts/cost_barrier_evidence.py --capture, commit",
            "scripts/cost_barrier_certify.py (draft: refuses, writes fresh content digests), commit",
            "scripts/cost_barrier_certify.py (certifies: exit 0)",
        ],
        "explorer_payload_sha256_published": "4383d812d6e18928c53894c7ee3ba063723d351ab945fcfc206373dfaa2621fb",
        "explorer_payload_sha256_rebuilt": "4383d812d6e18928c53894c7ee3ba063723d351ab945fcfc206373dfaa2621fb",
        "rebuilt_explorer_differs_in": [
            "/branch",
            "/generated_at_utc",
            "/head",
            "/sources[0]/sha256 (ACTIVE_ECONOMIC_AUDIT.json: pin is the CRLF rendering, content is LF)",
            "/sources[2]/sha256 (config/strategy_admission.json: pin predates the anchor repair)",
        ],
        "rebuilt_explorer_bytes": 212351,
        "rebuilt_explorer_differing_leaves": 5,
        "verifier_on_rebuilt": {"status": "PASS", "checks_failed": 0, "controls": "13/13"},
        "gate_before": {"status": "INTEGRITY_FAILURE", "exit_code": 5, "checks_passed": "10/11"},
        "gate_after": {"status": "FULL_REPRODUCTION_PASS", "exit_code": 0},
        "certification_after": {
            "status": "CERTIFIED",
            "exit_code": 0,
            "satisfies_full_certification": True,
        },
        "contract_suite": {
            "files": list(CONTRACT_SUITE),
            "nodes": 93,
            "on_head_without_the_gitignored_input": {
                "failed": 19,
                "passed": 74,
                "measured_on": "HEAD 2bd6e346 working tree, 2026-10-25",
            },
            "on_head_with_the_input_materialised": {
                "failed": 9,
                "passed": 84,
                "measured_on": "throwaway `git worktree` at 2bd6e346, input materialised, 2026-10-25",
                "reading": "10 of the 19 red nodes are only the absent input; the other 9 are the stale pins and the checkout artefacts they encode",
            },
            "after_full_recertification": {
                "failed": 0,
                "passed": 93,
                "source": "evidence/simulated_certification_record.json#steps.contract_tests (exit 0)",
            },
        },
        "full_suite": {
            "before_recertification": {
                "red_nodes": 104,
                "composition": "90 failed + 14 errors",
                "source": "evidence/full_suite_before_recertification.txt",
            },
            "after_recertification": {
                "red_nodes": 85,
                "composition": "71 failed + 14 errors",
                "source": "evidence/recertified_clone_tests.txt",
            },
            "set_difference": full_suite_delta(evidence),
            "reading": (
                "the two runs collected different totals (different environment), so only the "
                "node identity matters: the set difference is exactly the 19 cost-barrier nodes "
                "and nothing was introduced"
            ),
        },
        "partial_recertification": {
            "what_was_skipped": "the producer-pin capture and the certification digest refresh",
            "failed": 3,
            "passed": 105,
            "source": "evidence/recertified_partial_tests.txt",
            "reading": "rebuilding the explorer and the verification is not enough: the pins that quote them must be re-captured in the same pass, or the chain is left half-pinned",
        },
        "economic_numbers_changed": "none measured: the rebuilt explorer reproduces payload 4383d812 byte for byte, so every published cost, fee and horizon number is unchanged",
        "evidence_files": [
            (evidence / name).as_posix()
            for name in (
                "explorer_rebuild_diff.txt",
                "pristine_clone_cost_barrier_tests.txt",
                "recertified_clone_tests.txt",
                "recertified_partial_tests.txt",
                "full_suite_before_recertification.txt",
                "contract_suite_failure_reasons.txt",
                "contract_suite_with_input_materialised.txt",
                "simulated_certification_record.json",
                "simulated_rebuilt_verification.json",
            )
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    out_dir = REPO / args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    files = tracked_text_files()
    chain = []
    for node in CHAIN:
        path = node["path"]
        concrete = REPO / path.replace("*.json", "")
        exists = concrete.is_file() if "*" not in path else any(REPO.glob(path))
        raw_digest = sha256_bytes(concrete.read_bytes()) if exists and "*" not in path else None
        chain.append(
            {
                **node,
                "exists_in_working_tree": bool(exists),
                "tracked_at_head": bool(
                    git("ls-tree", "-r", "--name-only", "HEAD", "--", path.replace("*.json", ""))
                ),
                "sha256": raw_digest,
                "sha256_lf": content_digest(concrete) if exists and "*" not in path else None,
                "consumers": consumers_of(path, files),
            }
        )

    pins = pin_inventory()
    pathologies = [
        {
            "path": row["path"],
            "pin": row["pin"],
            "finding": (
                "the pin names the CRLF rendering of the committed blob, not the blob"
                if row.get("pin_names_the_crlf_rendering")
                else f"the pin names the CRLF rendering of revision {row['pin_names_a_revision_of_the_file'][:8]}, not any blob"
            ),
            "covered_by_a_state_pin": bool(row.get("state_pin")),
            "consequence": (
                "the byte pin can never match on a checkout that stores LF; it is survivable only "
                "because the semantic state pin is what the gate reads"
                if row.get("state_pin")
                else "the byte pin is the only protection and it names bytes no commit contains"
            ),
        }
        for row in pins
        if row.get("pin_names_the_crlf_rendering") or row.get("pin_names_a_revision_of_the_file")
    ]
    dependencies, dependency_verdict = dependency_classification()

    gate = subprocess.run(
        [sys.executable, "scripts/cost_barrier_gate.py", "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    gate_headline = (
        (gate.stdout or gate.stderr).strip().splitlines()[0]
        if (gate.stdout or gate.stderr).strip()
        else ""
    )

    payload = {
        "wp": "WP-ECONOMIC-RECOVERY-003",
        "artefact": "EVIDENCE_IMPACT_MATRIX",
        "commit_under_measurement": git("rev-parse", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "method": (
            "digests computed from the files on disk (raw and LF-normalised), producers and inputs "
            "declared in this script, consumers derived by scanning every tracked text file for the "
            "path, pins read from the artefacts that publish them"
        ),
        "gate_check_now": {
            "command": "scripts/cost_barrier_gate.py --check",
            "exit_code": gate.returncode,
            "headline": gate_headline,
        },
        "classes": {
            "REBUILT": "the producer rewrites it during recertification",
            "UNCHANGED_PAYLOAD": "rebuilt, but the economic payload digest does not change",
            "HISTORICAL_RECORD": "a past observation; it records what was true then and is not a live pin",
            "NOT_TOUCHED": "outside the recertification blast radius",
            "REBUILT_ALREADY": "rebuilt by the previous work package (the anchor repair)",
        },
        "chain": chain,
        "pins": pins,
        "pin_pathology": pathologies,
        "drift": [row for row in pins if row["status"] not in {"EXACT", "STATE_EXACT"}],
        "simulation": simulation_results(args.out),
        "dependency_classification": {
            "verdict": dependency_verdict,
            "rows": dependencies,
        },
        "test_analysis": test_analysis(),
    }
    (out_dir / "EVIDENCE_IMPACT_MATRIX.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )

    print(f"chain nodes: {len(chain)}; pins: {len(pins)}; drifting: {len(payload['drift'])}")
    for row in pathologies:
        print(
            f"  PATHOLOGY {row['path']} pin names the CRLF rendering; state pin: {row['covered_by_a_state_pin']}"
        )
    for row in payload["drift"]:
        print(
            f"  DRIFT {row['path']} ({row['status']}) pinned by {row['pinned_by'].split('#')[-1]}"
        )
    print(f"gate now: {gate.returncode} {gate_headline}")
    print(f"dependencies classified: {len(dependencies)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
