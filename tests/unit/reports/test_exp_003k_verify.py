"""003K — un verificador que no puede fallar no prueba nada.

``scripts/exp_003k_verify.py`` no solo recorre los artefactos: construye árboles de corrida
sintéticos con una mentira concreta dentro y exige que su propio check correspondiente
falle. Estos tests fijan las dos mitades:

1. los seis controles negativos (look-ahead, fill anterior a la respuesta, cierre contado
   dos veces, neto manipulado, selección que ignora su regla, éxito falso) se detectan;
2. un árbol sintético **sin** mentira pasa los mismos checks, para que el control no esté
   "detectando" algo que en realidad rompe cualquier ledger válido.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

import exp_003k_verify as verifier  # noqa: E402


@pytest.fixture(scope="module")
def controls() -> tuple[list[dict], bool]:
    return verifier.negative_controls()


def test_every_negative_control_is_caught(controls) -> None:
    results, all_caught = controls
    assert len(results) == 6
    missed = [item["control"] for item in results if not item["caught"]]
    assert missed == []
    assert all_caught is True


@pytest.mark.parametrize(
    "control,check",
    [
        ("N1_look_ahead_trace", "VK4_point_in_time"),
        ("N2_fill_before_answer", "VK5_fill_after_answer"),
        ("N3_double_counted_close", "VK7_no_double_counting"),
        ("N4_tampered_net", "VK6_accounting_identities"),
        ("N5_false_selection", "VK8_selection_rule"),
        ("N6_false_success", "VK10_verdict_rule"),
    ],
)
def test_each_control_is_caught_by_the_check_it_targets(controls, control: str, check: str) -> None:
    results, _ = controls
    match = next(item for item in results if item["control"] == control)
    assert match["check"] == check
    assert match["caught"] is True
    assert match["detail"].startswith("caught")


def test_a_clean_synthetic_tree_passes_the_same_checks(tmp_path: Path) -> None:
    root = verifier._synthetic_root(tmp_path)
    entries_by_run = {
        run_dir: verifier._load_ledger(run_dir / "ledger.jsonl")
        for run_dir in verifier._runs(root)
    }

    audit = verifier.Audit(root=root)
    verifier.check_point_in_time(root, audit)
    verifier.check_fill_timing(root, audit, entries_by_run)
    verifier.check_accounting(root, audit, entries_by_run)
    verifier.check_no_double_counting(root, audit, entries_by_run)

    states = {check.code: (check.ok, check.status) for check in audit.checks}
    assert states["VK4_point_in_time"] == (True, "PASS")
    assert states["VK5_fill_after_answer"] == (True, "PASS")
    assert states["VK6_accounting_identities"] == (True, "PASS")
    assert states["VK7_no_double_counting"] == (True, "PASS")
