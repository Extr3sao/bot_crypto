"""003M — el sello tiene que morder, y el verificador no puede reescribirlo.

Un sello que no detecta una alteración es un adorno. Estos tests construyen un
experimento sintético mínimo, lo sellan, y comprueban que:

* verificarlo sin tocar nada pasa;
* cambiar un byte, borrar un fichero o añadir uno no sellado falla, con el motivo;
* el manifiesto no se contiene a sí mismo (hash circular imposible);
* no se sella con una verificación fallida ni con tests en rojo;
* el verificador se niega a escribir cuando ya hay sello;
* ``generate`` se niega a regenerar un experimento sellado.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
for extra in (REPO / "scripts", REPO / "src"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import exp_003m_pipeline as pipeline  # noqa: E402


def _experiment(root: Path, *, verification_failed: int = 0, tests_ok: bool = True) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name in pipeline.DELIVERABLES:
        (root / name).write_text(f"# {name}\n", encoding="utf-8")
    (root / "design").mkdir()
    (root / "design" / "DESIGN.json").write_text('{"experiment": "synthetic"}\n', encoding="utf-8")
    (root / "analysis").mkdir()
    verification = {
        "summary": {
            "checks": 3,
            "passed": 3 - verification_failed,
            "failed": verification_failed,
            "not_executed": 0,
            "failed_names": ["synthetic"] if verification_failed else [],
            "negative_controls": 2,
            "negative_controls_detected": 2,
        }
    }
    (root / "analysis" / "VERIFICATION.json").write_text(json.dumps(verification), encoding="utf-8")
    tests = {"all_passed": tests_ok, "commands": [], "totals": {}}
    (root / "analysis" / "TESTS.json").write_text(json.dumps(tests), encoding="utf-8")
    (root / "analysis" / "PROVENANCE.json").write_text(
        json.dumps({"commit": "deadbeef", "dirty_paths_sha256": "00"}), encoding="utf-8"
    )
    (root / "raw").mkdir()
    (root / "raw" / "cache.zip").write_bytes(b"cache")
    return root


def test_seal_and_verify_roundtrip(tmp_path: Path) -> None:
    out = _experiment(tmp_path / "exp")
    assert pipeline.seal(out) == 0
    result = pipeline.verify_seal(out)
    assert result["ok"] is True
    assert result["files"] == len(pipeline.DELIVERABLES) + 4


def test_manifest_never_contains_itself(tmp_path: Path) -> None:
    out = _experiment(tmp_path / "exp")
    pipeline.seal(out)
    text = (out / "SHA256SUMS.txt").read_text(encoding="utf-8")
    assert "SHA256SUMS.txt" not in text
    assert "SEAL.json" not in text
    marker = json.loads((out / "SEAL.json").read_text(encoding="utf-8"))
    assert marker["self_reference"].startswith("none")


def test_raw_cache_is_not_sealed(tmp_path: Path) -> None:
    out = _experiment(tmp_path / "exp")
    pipeline.seal(out)
    assert "raw/cache.zip" not in (out / "SHA256SUMS.txt").read_text(encoding="utf-8")


def test_altered_byte_is_detected(tmp_path: Path) -> None:
    out = _experiment(tmp_path / "exp")
    pipeline.seal(out)
    (out / "FINAL_REPORT.md").write_text("# FINAL_REPORT.md\nedited\n", encoding="utf-8")
    result = pipeline.verify_seal(out)
    assert result["ok"] is False
    assert any("altered" in problem for problem in result["problems"])


def test_deleted_file_is_detected(tmp_path: Path) -> None:
    out = _experiment(tmp_path / "exp")
    pipeline.seal(out)
    (out / "BASELINE.md").unlink()
    result = pipeline.verify_seal(out)
    assert result["ok"] is False
    assert any("missing" in problem for problem in result["problems"])


def test_unsealed_extra_file_is_detected(tmp_path: Path) -> None:
    out = _experiment(tmp_path / "exp")
    pipeline.seal(out)
    (out / "analysis" / "SNEAKED.json").write_text("{}\n", encoding="utf-8")
    result = pipeline.verify_seal(out)
    assert result["ok"] is False
    assert any("unsealed" in problem for problem in result["problems"])


def test_seal_refuses_when_verification_failed(tmp_path: Path) -> None:
    out = _experiment(tmp_path / "exp", verification_failed=1)
    with pytest.raises(SystemExit):
        pipeline.seal(out)
    assert not (out / "SHA256SUMS.txt").exists()


def test_seal_refuses_when_tests_failed(tmp_path: Path) -> None:
    out = _experiment(tmp_path / "exp", tests_ok=False)
    with pytest.raises(SystemExit):
        pipeline.seal(out)


def test_seal_refuses_without_a_deliverable(tmp_path: Path) -> None:
    out = _experiment(tmp_path / "exp")
    (out / "RUN_REPORT.json").unlink()
    with pytest.raises(SystemExit):
        pipeline.seal(out)


def test_verifier_refuses_to_write_once_sealed(tmp_path: Path) -> None:
    import exp_003m_verify as verifier

    out = _experiment(tmp_path / "exp")
    pipeline.seal(out)
    exit_code = verifier.main(["--out", str(out), "--write"])
    assert exit_code == 2
    #: and the sealed tree is untouched by the refusal
    assert pipeline.verify_seal(out)["ok"] is True


def test_generate_refuses_to_rewrite_a_sealed_experiment(tmp_path: Path) -> None:
    out = _experiment(tmp_path / "exp")
    pipeline.seal(out)
    with pytest.raises(SystemExit):
        pipeline.generate(out)
