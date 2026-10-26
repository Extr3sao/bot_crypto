"""The admission ledger's identity must not depend on how its bytes were rendered.

WP-ECONOMIC-RECOVERY-003 found the defect this file guards: the ledger was pinned by a
digest computed over the CRLF rendering of an *older* revision, so the pin described a
working tree rather than a commit, and no checkout could ever match it. The repair is a
versioned semantic identity (``docs/agentic/economic_audit/WP-ECONOMIC-RECOVERY-004/
LEDGER_INTEGRITY_CONTRACT.md``) published next to the byte pin, not instead of it.

Two implementations of that contract exist on purpose — the explorer writes the pin, the
gate re-derives it — so these tests hold them together: same identity across LF and CRLF,
same identity across processes, a different identity for every semantic edit, and no
identity at all for a document that does not claim the schema. They also pin the gate's
decision rule, which requires *both* identities: a foreign byte pin stays a finding even
when the state happens to match.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
LEDGER_REL = "config/strategy_admission.json"
LEDGER = ROOT / LEDGER_REL
EXPLORER = ROOT / "scripts" / "cost_barrier_explorer.py"
GATE = ROOT / "scripts" / "cost_barrier_gate.py"
CONTRACT = "strategy-admission-ledger-identity-v1"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def explorer():
    return load(EXPLORER, "cost_barrier_explorer_contract")


@pytest.fixture(scope="module")
def gate():
    return load(GATE, "cost_barrier_gate_contract")


@pytest.fixture()
def ledger_doc() -> dict[str, Any]:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def render(document: dict[str, Any], eol: str = "\n") -> bytes:
    return (
        (json.dumps(document, indent=2, ensure_ascii=False) + "\n")
        .replace("\n", eol)
        .encode("utf-8")
    )


#: Every kind of edit the contract must treat as a change of state. Named at module level
#: so the parametrisation does not have to build a ledger to discover them.
MUTATIONS = (
    "admission_decision",
    "strategy_status",
    "economic_value",
    "sample_size",
    "strategy_added",
    "dependency_digest",
    "dependency_path",
    "period",
    "claim",
    "cost_model",
    "schema",
)


def semantic_mutations(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """One edit per kind of thing the ledger decides, each with a name."""

    def edit(mutator) -> dict[str, Any]:
        clone = copy.deepcopy(document)
        mutator(clone)
        return clone

    first = next(iter(document["strategies"]))
    return {
        "admission_decision": edit(
            lambda d: d["strategies"][first].__setitem__(
                "admitted_for_paper", not d["strategies"][first]["admitted_for_paper"]
            )
        ),
        "strategy_status": edit(
            lambda d: d["strategies"][first].__setitem__("status", "PAPER_CANDIDATE")
        ),
        "economic_value": edit(
            lambda d: d["strategies"][first].__setitem__(
                "expected_gross_edge_bps", d["strategies"][first]["expected_gross_edge_bps"] + 0.01
            )
        ),
        "sample_size": edit(
            lambda d: d["strategies"][first]["edge_evidence"].__setitem__(
                "sample_trades", d["strategies"][first]["edge_evidence"]["sample_trades"] + 1
            )
        ),
        "strategy_added": edit(
            lambda d: d["strategies"].__setitem__("ghost@5m", d["strategies"][first])
        ),
        "dependency_digest": edit(lambda d: d["_sources"][1].__setitem__("sha256", "0" * 64)),
        "dependency_path": edit(lambda d: d["_sources"][0].__setitem__("path", "docs/OTHER.json")),
        "period": edit(lambda d: d.__setitem__("_period", "W1-W8 1999-01-01..1999-02-01")),
        "claim": edit(lambda d: d.__setitem__("_claim", "anything is admitted")),
        "cost_model": edit(lambda d: d.__setitem__("_admission_cost_model", "COST_MODEL_V0")),
        "schema": edit(lambda d: d.__setitem__("_schema_version", "strategy-admission-ledger-v2")),
    }


def test_the_two_implementations_and_the_contract_agree_on_the_committed_ledger(explorer, gate):
    document = json.loads(LEDGER.read_text(encoding="utf-8"))
    from_explorer, contract = explorer.state_identity(LEDGER, LEDGER_REL)
    from_gate = gate.ledger_state_digest(document)
    assert contract == CONTRACT == gate.LEDGER_IDENTITY_CONTRACT
    assert from_explorer is not None
    assert from_explorer == from_gate, (
        "the explorer and the gate disagree about the ledger's identity; the pin one writes "
        "could never be verified by the other"
    )
    assert len(from_explorer) == 64


def test_line_endings_do_not_change_the_identity(explorer, gate, ledger_doc):
    lf = explorer.ledger_state_sha256(json.loads(render(ledger_doc, "\n")))
    crlf = explorer.ledger_state_sha256(json.loads(render(ledger_doc, "\r\n")))
    assert lf == crlf, "a checkout convention changed the ledger's identity"
    assert gate.ledger_state_digest(json.loads(render(ledger_doc, "\r\n"))) == lf


def test_the_renderer_is_provenance_and_not_state(explorer, gate, ledger_doc):
    original = explorer.ledger_state_sha256(ledger_doc)
    renamed = copy.deepcopy(ledger_doc)
    renamed["_generated_by"] = "scripts/some_other_builder.py"
    assert explorer.ledger_state_sha256(renamed) == original
    assert gate.ledger_state_digest(renamed) == original


@pytest.mark.parametrize("kind", MUTATIONS)
def test_every_semantic_edit_changes_the_identity(explorer, gate, ledger_doc, kind):
    baseline = explorer.ledger_state_sha256(ledger_doc)
    mutated = semantic_mutations(ledger_doc)[kind]
    assert explorer.ledger_state_sha256(mutated) != baseline, (
        f"{kind} is semantically relevant but the identity did not change"
    )
    assert gate.ledger_state_digest(mutated) != baseline


def test_the_identity_is_reproducible_in_another_process(explorer, gate, ledger_doc):
    script = (
        "import hashlib, importlib.util, json, sys\n"
        f"spec = importlib.util.spec_from_file_location('e', {str(EXPLORER)!r})\n"
        "mod = importlib.util.module_from_spec(spec); sys.modules['e'] = mod\n"
        "spec.loader.exec_module(mod)\n"
        f"doc = json.loads(open({str(LEDGER)!r}, encoding='utf-8').read())\n"
        "print(mod.ledger_state_sha256(doc))\n"
    )
    digests = {
        subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        ).stdout.strip()
        for seed in ("0", "1", "12345")
    }
    assert digests == {explorer.ledger_state_sha256(ledger_doc)}, digests


def test_a_document_without_the_declared_schema_has_no_identity(explorer, gate, ledger_doc):
    foreign = copy.deepcopy(ledger_doc)
    foreign.pop("_schema_version", None)
    assert explorer.ledger_state_sha256(foreign) is None
    assert gate.ledger_state_digest(foreign) is None
    assert gate.state_digest(LEDGER_REL, json.dumps(foreign).encode(), CONTRACT) is None


def test_an_unknown_contract_yields_no_state_rather_than_a_guess(gate, ledger_doc):
    data = render(ledger_doc)
    assert gate.state_digest(LEDGER_REL, data, "some-future-contract-v9") is None
    assert gate.state_digest(LEDGER_REL, data, CONTRACT) == gate.ledger_state_digest(ledger_doc)


def pin_row(
    document: dict[str, Any], gate, *, sha256: str | None = None, contract: str | None = CONTRACT
):
    return {
        "path": LEDGER_REL,
        "sha256": sha256 or hashlib.sha256(render(document)).hexdigest(),
        "state_sha256": gate.ledger_state_digest(document),
        **({"state_contract": contract} if contract else {}),
    }


@pytest.fixture()
def ledger_tree(tmp_path, monkeypatch, gate, ledger_doc):
    """A tree the gate treats as its root, holding only the declared ledger."""

    (tmp_path / "config").mkdir()
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "DECLARED_INPUTS", ((LEDGER_REL, "admission ledger", True),))
    monkeypatch.setattr(gate, "PINNED_PATHS", (LEDGER_REL,))

    def write(payload: bytes) -> None:
        (tmp_path / LEDGER_REL).write_bytes(payload)

    write(render(ledger_doc))
    return write


def status_of(rows, gate):
    assert len(rows) == 1
    return rows[0]["pin_status"]


def test_the_gate_accepts_an_identical_ledger(ledger_tree, gate, ledger_doc):
    rows, defects = gate.input_rows({"sources": [pin_row(ledger_doc, gate)]})
    assert defects == []
    assert status_of(rows, gate) == gate.PIN_STATE_EXACT


def test_the_gate_accepts_a_crlf_rendering_of_the_same_state(ledger_tree, gate, ledger_doc):
    ledger_tree(render(ledger_doc, "\r\n"))
    row = pin_row(ledger_doc, gate, sha256=hashlib.sha256(render(ledger_doc)).hexdigest())
    rows, defects = gate.input_rows({"sources": [row]})
    assert defects == []
    assert rows[0]["byte_status"] == gate.PIN_EOL, "the bytes did move, and the gate must say so"
    assert status_of(rows, gate) == gate.PIN_STATE_EXACT


def test_a_semantic_edit_is_drift_even_if_the_pins_are_recomputed(ledger_tree, gate, ledger_doc):
    tampered = semantic_mutations(ledger_doc)["admission_decision"]
    ledger_tree(render(tampered))
    rows, _ = gate.input_rows({"sources": [pin_row(ledger_doc, gate)]})
    assert status_of(rows, gate) == gate.PIN_DRIFT


def test_a_foreign_byte_pin_is_drift_even_when_the_state_matches(ledger_tree, gate, ledger_doc):
    foreign = hashlib.sha256(b"some other artefact entirely").hexdigest()
    rows, _ = gate.input_rows({"sources": [pin_row(ledger_doc, gate, sha256=foreign)]})
    assert rows[0]["state_status"] == "EXACT", "the state is right; only the bytes are foreign"
    assert status_of(rows, gate) == gate.PIN_DRIFT, (
        "a valid digest belonging to another file must stay a finding"
    )


def test_an_unknown_contract_is_a_defect_not_a_pass(ledger_tree, gate, ledger_doc):
    rows, defects = gate.input_rows({"sources": [pin_row(ledger_doc, gate, contract="v9")]})
    assert defects and "does not implement" in defects[0]
    assert status_of(rows, gate) == gate.PIN_DRIFT


def test_an_absent_ledger_is_absent_not_drift(tmp_path, monkeypatch, gate, ledger_doc):
    (tmp_path / "config").mkdir()
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "DECLARED_INPUTS", ((LEDGER_REL, "admission ledger", True),))
    monkeypatch.setattr(gate, "PINNED_PATHS", (LEDGER_REL,))
    rows, defects = gate.input_rows({"sources": [pin_row(ledger_doc, gate)]})
    assert defects == []
    assert status_of(rows, gate) == gate.PIN_ABSENT


def test_the_ledger_pin_is_not_the_audit_convention(gate, ledger_doc):
    """The ledger has no payload_sha256: the generic rule must not invent an identity."""

    assert "payload_sha256" not in ledger_doc
    assert gate.state_digest(LEDGER_REL, render(ledger_doc)) is None, (
        "without a declared contract the ledger has no state identity; silence is not a pin"
    )
