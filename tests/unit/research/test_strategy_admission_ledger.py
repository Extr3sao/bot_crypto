"""The admission ledger must be exactly what its committed sources produce.

`config/strategy_admission.json` is the only thing standing between a research
verdict and the paper runtime: the runtime reads it and refuses to guess, so a
ledger that has drifted from the artifacts it names is worse than a missing one,
because it keeps answering.

WP-ECONOMIC-BLOCKER-001 found the defect this file guards: the ledger recorded a
SHA-256 for `docs/STRATEGY_ADMISSION_MATRIX.json` that matched no committed
revision of that file, so `scripts/build_strategy_admission.py --check` exited 1
and nobody noticed — the verdicts themselves were right, so nothing failed at
runtime and nothing complained at build time. There was no test that looked.

These tests look. They compare the committed bytes to the rebuilt bytes (the
whole artefact, not a summary of it), they verify every source digest against the
file it names, and they pin the two properties a future edit is most likely to
break: the file's bytes must not depend on the platform, and no strategy may be
admitted without a measured positive gross edge.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parents[3]
LEDGER = REPO / "config" / "strategy_admission.json"
BUILDER = REPO / "scripts" / "build_strategy_admission.py"


def load_builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_strategy_admission", BUILDER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rebuilt_bytes() -> bytes:
    """The artefact as `main()` writes it — same call, same serialisation."""

    payload = load_builder().build()
    return (json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n").encode(
        "utf-8"
    )


def first_difference(committed: bytes, rebuilt: bytes) -> str:
    left = committed.splitlines()
    right = rebuilt.splitlines()
    for index, (old, new) in enumerate(zip(left, right, strict=False), start=1):
        if old != new:
            return f"line {index}:\n  committed: {old.decode('utf-8', 'replace')}\n  rebuilt  : {new.decode('utf-8', 'replace')}"
    return f"committed has {len(left)} lines, rebuilt has {len(right)}"


def test_the_committed_ledger_is_what_the_committed_artifacts_produce() -> None:
    committed = LEDGER.read_bytes()
    rebuilt = rebuilt_bytes()
    assert committed == rebuilt, (
        "config/strategy_admission.json is stale: it is not what "
        "scripts/build_strategy_admission.py derives from its committed sources. "
        "Regenerate it with `uv run python scripts/build_strategy_admission.py`.\n"
        + first_difference(committed, rebuilt)
    )


def test_every_source_the_ledger_names_is_the_file_on_disk_and_the_revision_at_head() -> None:
    payload = json.loads(LEDGER.read_bytes())
    sources = payload["_sources"]
    assert sources, "a ledger with no declared sources cannot be reproduced"
    for source in sources:
        path = REPO / source["path"]
        assert path.is_file(), source["path"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == source["sha256"], (
            f"{source['path']} does not have the digest the ledger records for it: "
            f"recorded {source['sha256']}, on disk {digest}"
        )


def test_the_ledger_bytes_do_not_depend_on_the_platform() -> None:
    # Path.write_text translates "\n" to the host separator, so a Windows rebuild used to rewrite
    # all 547 lines of a tracked artefact and make its bytes depend on who ran the builder.
    committed = LEDGER.read_bytes()
    assert b"\r\n" not in committed, "the ledger carries CRLF: its bytes are host-dependent"
    assert rebuilt_bytes() == committed, "a rebuild must be byte-identical, separators included"


def test_no_strategy_is_admitted_without_a_measured_positive_gross_edge() -> None:
    payload = json.loads(LEDGER.read_bytes())
    admitted = {
        sid: entry for sid, entry in payload["strategies"].items() if entry["admitted_for_paper"]
    }
    for strategy_id, entry in admitted.items():
        assert entry["status"] == "PAPER_CANDIDATE", strategy_id
        assert (entry["expected_gross_edge_bps"] or 0) > 0, strategy_id
    # every entry answers, including the ones it knows nothing about: silence is not an answer the
    # runtime can act on, so absence is represented as UNKNOWN rather than as an omitted key
    for strategy_id, entry in payload["strategies"].items():
        assert entry["known"] is True, strategy_id
        assert entry["status"] in {
            "PAPER_CANDIDATE",
            "COST_KILLED",
            "NO_GROSS_EDGE",
            "UNKNOWN",
        }, strategy_id
