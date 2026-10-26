"""RFC-DEF-018 / WP-018-02 — la procedencia de un run se demuestra, no se declara.

El defecto de 017 no fue perder un campo: fue publicar `resumed_from_ledger=true` sin
decir de qué ledger, con qué configuración ni con qué dataset venía el run. Estos casos
fijan el contrato nuevo: un run reconstruido enlaza su resumen con la cabecera `RUN`, el
cierre `RUN_END`, la cadena de sha256 y el dataset, y declara el acto de reanudación con
su commit. El verificador B lo recalcula por su cuenta; si algo no cuadra, FAIL.

No se prueba que B «diga PASS» en general: se prueba que deje de decirlo en cuanto un
byte de procedencia cambia, y que no indulte la evidencia vieja por ser vieja.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
LEDGER = (
    REPO
    / "reports"
    / "ai-bots"
    / "RFC-DEF-RUN-017"
    / "evidence"
    / "oos"
    / "runs"
    / "AAVEUSDT"
    / "defer"
    / "cost-1.0"
    / "2021-02-09.jsonl"
)
DATASET = REPO / "data" / "quote-feed-1m" / "AAVEUSDT_1m_2021-01-04_2021-02-17.json"
SYMBOL = "AAVE/USDT"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


oos = load_module("def_run_017_oos", REPO / "scripts" / "def_run_017_oos.py")
verifier = load_module("def_run_018_verify_b", REPO / "scripts" / "def_run_018_verify_b.py")


def task(day: int = 18667) -> dict[str, Any]:
    return {"symbol": SYMBOL, "lifecycle": "DEFER", "cost_multiplier": 1.0, "day": day}


def resume_history() -> list[dict[str, Any]]:
    return [
        {
            "attempt": 1,
            "at_utc": "2026-10-21T15:00:00Z",
            "at_commit": "a" * 40,
            "source_artifact_sha256": "b" * 64,
            "partition": "untouched_test",
            "ledgers_reused": 32,
            "ledgers_executed": 0,
        }
    ]


@pytest.fixture(scope="module")
def rows() -> list[dict[str, Any]]:
    payload, error = verifier.read_rows(LEDGER)
    assert error is None, error
    return payload


@pytest.fixture(scope="module")
def dataset() -> list[list[Any]]:
    loaded = json.loads(DATASET.read_text(encoding="utf-8"))
    return sorted(loaded, key=lambda row: int(row[0]))


@pytest.fixture()
def reconstructed() -> dict[str, Any]:
    return oos.result_from_ledger(task(), LEDGER, resumes=resume_history())


def head_of(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return next(row["entry"] for row in rows if row["entry"].get("kind") == "RUN")


def end_of(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return next(row["entry"] for row in reversed(rows) if row["entry"].get("kind") == "RUN_END")


def reasons(
    run: dict[str, Any],
    rows: list[dict[str, Any]],
    dataset: list[list[Any]],
    history: list[dict[str, Any]] | None,
) -> list[str]:
    return verifier.provenance_reasons(run, rows, dataset, history)


# --------------------------------------------------------------- procedencia completa


def test_a_direct_run_links_the_ledger_that_produced_it(reconstructed, rows, dataset):
    direct = copy.deepcopy(reconstructed)
    direct["provenance"]["method"] = "DIRECT"
    direct["provenance"]["resumes"] = []
    assert reasons(direct, rows, dataset, None) == []
    provenance = direct["provenance"]
    assert provenance["run_id"] == head_of(rows)["book_id"]
    assert provenance["started_at_utc"] == head_of(rows)["recorded_at_utc"]
    assert provenance["finished_at_utc"] == end_of(rows)["recorded_at_utc"]
    assert provenance["chain"]["rows"] == len(rows)
    assert provenance["chain"]["head_sha256"] == rows[-1]["sha256"]
    assert direct["ledger_sha256"] == hashlib.sha256(LEDGER.read_bytes()).hexdigest()


def test_a_resume_with_demonstrated_provenance_passes(reconstructed, rows, dataset):
    assert reconstructed["provenance"]["method"] == "LEDGER_RECONSTRUCTION"
    assert reconstructed["provenance"]["resumes"] == resume_history()
    assert reasons(reconstructed, rows, dataset, resume_history()) == []
    #: la economía no se toca: la reparación enlaza procedencia, no reescribe PnL.
    assert reconstructed["net_pnl_usdt"] == round(rebuilt_net(rows), 8)


def rebuilt_net(rows: list[dict[str, Any]]) -> float:
    return sum(
        float(row["entry"]["pnl_net_usdt"]) for row in rows if row["entry"].get("kind") == "CLOSE"
    )


def test_the_dataset_fingerprint_is_recomputed_with_b_own_code(rows, dataset):
    declared = head_of(rows)["dataset"][SYMBOL]
    first = verifier.to_ms(declared["first_open_utc"])
    window = [row for row in dataset if int(row[0]) >= first][: int(declared["bars"])]
    assert len(window) == int(declared["bars"])
    assert verifier.series_digest(window) == declared["sha256"]
    assert verifier.to_ms(declared["last_open_utc"]) == int(window[-1][0])


def test_the_original_commit_is_declared_absent_not_invented(reconstructed):
    provenance = reconstructed["provenance"]
    assert provenance["original_commit"] is None
    assert provenance["original_commit_source"] == "NOT_RECORDED_IN_LEDGER"


# ------------------------------------------------------------------- procedencia rota


def test_a_reconstruction_without_its_resume_history_fails(rows, dataset):
    bare = oos.result_from_ledger(task(), LEDGER)
    assert "resume_history_missing" in reasons(bare, rows, dataset, None)


def test_history_that_disagrees_with_the_artifact_fails(reconstructed, rows, dataset):
    other = [{**resume_history()[0], "attempt": 2}]
    found = reasons(reconstructed, rows, dataset, other)
    assert "resume_history_disagrees_with_artifact" in found


def test_a_legacy_resume_marker_is_not_grandfathered(reconstructed, rows, dataset):
    legacy = copy.deepcopy(reconstructed)
    legacy.pop("provenance")
    legacy["resumed_from_ledger"] = True
    found = reasons(legacy, rows, dataset, None)
    assert "legacy_resume_marker_without_provenance" in found


def test_an_artifact_that_declares_resumes_needs_a_block_on_every_run(reconstructed, rows, dataset):
    stripped = copy.deepcopy(reconstructed)
    stripped.pop("provenance")
    found = reasons(stripped, rows, dataset, resume_history())
    assert "artifact_declares_resume_but_run_has_no_provenance" in found


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("run_id", "def-run-017-OTRO", "run_id"),
        ("started_at_utc", "2026-10-21T00:00:00Z", "started_at_utc"),
        ("finished_at_utc", "2026-10-21T23:59:59Z", "finished_at_utc"),
        ("config_sha256", "0" * 64, "config_sha256"),
        ("original_commit_source", "", "original_commit_source_missing"),
    ],
)
def test_tampering_with_a_provenance_field_is_caught(
    reconstructed, rows, dataset, field, value, expected
):
    tampered = copy.deepcopy(reconstructed)
    tampered["provenance"][field] = value
    assert expected in reasons(tampered, rows, dataset, resume_history())


def test_swapping_the_declared_dataset_digest_is_caught(reconstructed, rows, dataset):
    tampered_rows = copy.deepcopy(rows)
    head = head_of(tampered_rows)
    head["dataset"][SYMBOL]["sha256"] = "f" * 64
    run = copy.deepcopy(reconstructed)
    run["provenance"]["dataset"][SYMBOL]["sha256"] = "f" * 64
    assert "dataset_sha256" in reasons(run, tampered_rows, dataset, resume_history())


def test_widening_the_declared_window_beyond_the_dataset_is_caught(reconstructed, rows, dataset):
    tampered_rows = copy.deepcopy(rows)
    head = head_of(tampered_rows)
    head["dataset"][SYMBOL]["bars"] = 10**6
    run = copy.deepcopy(reconstructed)
    run["provenance"]["dataset"][SYMBOL]["bars"] = 10**6
    assert "dataset_bars" in reasons(run, tampered_rows, dataset, resume_history())


def test_a_resume_without_a_commit_is_caught(reconstructed, rows, dataset):
    tampered = copy.deepcopy(reconstructed)
    tampered["provenance"]["resumes"][0]["at_commit"] = None
    assert "resume_commit_missing" in reasons(tampered, rows, dataset, None)


def test_a_chain_head_that_is_not_the_last_line_is_caught(reconstructed, rows, dataset):
    tampered = copy.deepcopy(reconstructed)
    tampered["provenance"]["chain"]["head_sha256"] = "0" * 64
    assert "chain_head" in reasons(tampered, rows, dataset, resume_history())


# --------------------------------------------------------------------------- recount


def test_recount_keeps_coverage_and_provenance(tmp_path, reconstructed):
    """Recontar contadores no puede reescribir la procedencia ni la cobertura."""
    payload = {
        "schema_version": "DEF_RUN_017_OOS_V1",
        "partition": "untouched_test",
        "resumes": resume_history(),
        "runs": [copy.deepcopy(reconstructed)],
    }
    original_deferred = payload["runs"][0]["deferred_slots"]
    payload["runs"][0]["deferred_slots"] = 0
    source = tmp_path / "OOS_RUNS_untouched_test.json"
    source.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    assert oos.recount("untouched_test", source_path=source) == 0
    after = json.loads(source.read_text(encoding="utf-8"))
    run = after["runs"][0]
    assert after["recount"]["provenance_unchanged"] is True
    assert after["recount"]["pnl_untouched"] is True
    assert after["recount"]["changed_runs"] == 1
    assert run["deferred_slots"] == original_deferred
    assert run["provenance"] == reconstructed["provenance"]
    assert run["minutes_observed"] == reconstructed["minutes_observed"]
    assert run["missing_minutes"] == reconstructed["missing_minutes"]
    assert run["bars"] == reconstructed["bars"]
    assert run["net_pnl_usdt"] == reconstructed["net_pnl_usdt"]
