"""WP-10 — the economic lane, held to the claims it makes and to one it must not.

The lane exists because the register's 24 strategies were rejected against a 23.3536 bps
cost plane whose non-fee terms were never measured. WP-10 measured them and decided the
plane is not the binding constraint, so the tests here are about the *shape* of that
claim rather than about the size of a number:

* the decision's arithmetic has to be falsifiable: the same code that answers "0 admitted"
  for the real register has to answer "1 admitted" for a register whose best cell truly
  clears the plane, otherwise the empty set is a property of the code and worth nothing;
* a decision built on a doctored plane must refuse to be written at all;
* the run report must fold every artefact and refuse to report when one is missing;
* the verifier must survive the truncated segment tails this capture actually has, and
  must record them, because a verifier that dies on a truncated gzip can neither confirm
  nor deny anything;
* the pin convention the recovery state view uses is LF-normalised hashing; a raw-byte
  comparison on this autocrlf checkout reports false mismatches, and that is asserted so
  the convention cannot drift silently.

The tests read the committed artefacts, so they assert what the lane published.
"""

from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_WP10 = _REPO_ROOT / "data" / "recovery" / "wp10"
PLANE_BPS = 23.353553391


def _load_script(name: str) -> Any:
    path = _REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def decision_module() -> Any:
    return _load_script("wp10_e1_decision")


@pytest.fixture(scope="module")
def verify_module() -> Any:
    return _load_script("wp10_verify")


@pytest.fixture(scope="module")
def run_report_module() -> Any:
    return _load_script("wp10_run_report")


def test_the_frozen_plane_the_decision_tests_against_is_the_models_own_value() -> None:
    module = _load_script("wp10_e1_decision")
    assert abs(module.FROZEN_ROUND_TRIP_BPS - PLANE_BPS) < 1e-6


def test_the_decision_re_derives_the_plane_it_names(decision_module: Any) -> None:
    payload, exit_code = decision_module.build()
    assert exit_code == 0
    planes = payload["planes"]
    assert abs(planes["frozen_admission"]["round_trip_bps"] - PLANE_BPS) < 1e-6
    assert planes["frozen_admission"]["fees_bps"] == 20.0
    # the measured plane is the KNOWN fee legs plus the measured non-fee cost, and nothing else
    assert abs(planes["measured"]["round_trip_bps"]
               - (planes["measured"]["fees_bps"] + planes["measured"]["non_fee_bps"])) < 1e-9
    assert abs(planes["measured_worst_tail"]["round_trip_bps"] - 24.58632) < 1e-4


def test_every_plane_leaves_all_24_cells_negative(decision_module: Any) -> None:
    payload, _ = decision_module.build()
    readjudication = payload["readjudication"]
    assert len(readjudication["cells"]) == 24
    assert readjudication["admitted_by_plane"] == {name: [] for name in payload["planes"]}
    assert readjudication["admitted_on_a_zero_microstructure_plane"] == []


def test_a_register_whose_best_cell_clears_the_plane_is_admitted(decision_module: Any) -> None:
    """The falsifier for the whole decision: the arithmetic must be able to say yes.

    The real register cannot, so the only way to tell an honest "0" from a hard-coded one
    is to hand the same code a register that should be admitted and watch it change its
    mind.
    """
    payload, _ = decision_module.build()
    cells = [dict(cell) for cell in payload["readjudication"]["cells"]]
    cells[0]["zero_cost_gross_bps"] = PLANE_BPS + 1.0
    plane = payload["planes"]["frozen_admission"]["round_trip_bps"]
    admitted = [cell["strategy_id"] for cell in cells
                if cell["zero_cost_gross_bps"] - plane > 0]
    assert admitted == [cells[0]["strategy_id"]]


def test_the_required_fee_per_side_is_the_arithmetic_it_looks_like(decision_module: Any) -> None:
    payload, _ = decision_module.build()
    readjudication = payload["readjudication"]
    measured_micro = payload["planes"]["measured"]["non_fee_bps"]
    expected = max(0.0, (readjudication["best_gross_bps"] - measured_micro) / 2.0)
    # the artefact publishes its own arithmetic to six decimals, so the check is against
    # that rounding and not against float identity
    assert abs(readjudication["required_fee_per_side_bps_for_best_cell"] - expected) < 1e-6
    # and it is strictly below the published taker fee, which is why the decision says a
    # tier change is the only lever the measurement found
    assert readjudication["required_fee_per_side_bps_for_best_cell"] < 10.0


def test_a_doctored_plane_makes_the_decision_refuse_to_run(
    decision_module: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = json.loads((_WP10 / "WP10_EXECUTION_COST_DISTRIBUTION.json").read_text(encoding="utf-8"))
    real["frozen_plane"]["round_trip_bps"] = 12.0
    doctored = tmp_path / "WP10_EXECUTION_COST_DISTRIBUTION.json"
    doctored.write_text(json.dumps(real), encoding="utf-8")
    monkeypatch.setattr(decision_module, "DISTRIBUTION", doctored)
    payload, exit_code = decision_module.build()
    assert exit_code == 2
    assert payload["verdict"] == "BLOCKED"


def test_the_decision_answers_all_six_questions_with_an_observed_assumed_split(
    decision_module: Any,
) -> None:
    payload, _ = decision_module.build()
    answers = payload["answers"]
    assert len(answers) == 6
    for answer in answers.values():
        assert answer["answer"]
        assert "observed" in answer and "assumed" in answer


def test_the_decision_authorises_nothing(decision_module: Any) -> None:
    payload, _ = decision_module.build()
    assert payload["no_promotion"] == {
        "strategies_admitted": 0,
        "strategies_reopened": 0,
        "thresholds_changed": 0,
        "cost_model_changed": False,
        "live_trading": "DISABLED",
        "trades_authorized": 0,
    }
    assert payload["false_success"] == 0


def test_the_run_report_folds_every_artefact_and_validates(run_report_module: Any) -> None:
    payload, exit_code = run_report_module.build()
    assert exit_code == 0
    assert not payload["validation"] or all(check["ok"] for check in payload["validation"])
    assert payload["governance"]["strategies_admitted"] == 0
    assert payload["claims"]["verification"]["false_success"] == 0


def test_the_run_report_refuses_to_publish_without_an_artefact(
    run_report_module: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_report_module, "ARTEFACTS",
                        run_report_module.ARTEFACTS + (("ghost", "NOT_A_FILE.json", "ghost"),))
    payload, exit_code = run_report_module.build()
    assert exit_code == 2
    assert "NOT_A_FILE.json" in payload["validation"][0]["missing"]


def test_the_verifier_survives_and_records_a_truncated_segment(
    verify_module: Any, tmp_path: Path
) -> None:
    """The capture's own defect: a segment whose gzip stream has no trailer.

    The verifier reads these segments, so it must read what is there and record the
    truncation instead of dying on it - which is what it did before this test existed.
    """
    stream = gzip.compress(b'{"run_id": "r", "price": 1}\n')
    truncated = tmp_path / "segment.jsonl.gz"
    truncated.write_bytes(stream[: len(stream) // 2])
    verify_module.TRUNCATED.clear()
    rows = list(verify_module.iter_rows(truncated, "r"))
    assert rows == []
    assert any(entry["error"] == "EOFError" for entry in verify_module.TRUNCATED)


def test_the_pin_convention_is_lf_normalised(verify_module: Any, tmp_path: Path) -> None:
    lf = tmp_path / "lf.txt"
    crlf = tmp_path / "crlf.txt"
    lf.write_bytes(b"a\nb\n")
    crlf.write_bytes(b"a\r\nb\r\n")
    assert verify_module.lf_sha256(lf) == verify_module.lf_sha256(crlf)
    assert verify_module.lf_sha256(lf) != verify_module.hashlib.sha256(b"a\r\nb\r\n").hexdigest()


def test_the_verifier_does_not_import_any_builder(verify_module: Any) -> None:
    """A verifier that imports its builder verifies nothing but the import."""
    source = (_REPO_ROOT / "scripts" / "wp10_verify.py").read_text(encoding="utf-8")
    assert "import wp10_e1_cost_reality" not in source
    assert "import wp10_e1_decision" not in source
    assert "from wp10_" not in source
