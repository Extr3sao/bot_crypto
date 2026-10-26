"""El panel del carril de visión: datos reales, estados honestos y ninguna cifra inventada.

El patrón que se prueba no es cosmético: un panel que rellena con ceros un directorio vacío
es un panel que declara «sin pérdidas» cuando en realidad declara «sin datos». Los tres
estados que importan son ``ABSENT`` (nada publicado), ``FAILED`` (el verificador encontró un
fallo) y ``VERIFIED`` (comparación publicada y aceptada por un verificador independiente).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
ARTIFACTS = REPO / "reports" / "ai-bots" / "RFC-AI-BOTS-003E"

from trading_bot.observability.vision_panel import build_vision_lane_panel  # noqa: E402


def _copy_package(destination: Path, *, verification: dict[str, Any] | None) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("COMPARISON.json", "CAPTURE.json"):
        (destination / name).write_bytes((ARTIFACTS / name).read_bytes())
    if verification is not None:
        (destination / "VERIFICATION.json").write_text(
            json.dumps(verification, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return destination


def test_the_real_package_is_verified_and_says_so():
    panel = build_vision_lane_panel(ARTIFACTS)

    assert panel["available"] is True
    assert panel["state"] == "VERIFIED"
    assert panel["decision"] == "ADOPT"
    assert panel["gates_evaluated"]["G4_economy"] is True
    assert panel["gates_evaluated"]["G5_ai_cost"] is True
    #: El proveedor es un guion; el panel no puede insinuar que se llamó a un modelo.
    assert panel["real_model_called"] is False
    scenario = panel["scenarios"]["proposed_900ms"]
    assert scenario["sub_bar_fills"] == 34
    assert scenario["quote_lag_ms_median"] == 59_100
    #: Cada cifra viene con la huella del fichero del que salió.
    for source in panel["sources"].values():
        assert len(str(source["sha256"])) == 64


def test_an_empty_directory_is_absent_not_zero():
    panel = build_vision_lane_panel(REPO / "reports" / "ai-bots" / "RFC-AI-BOTS-003E-absent")

    assert panel["available"] is False
    assert panel["state"] == "ABSENT"
    assert "not present" in panel["reason"]
    assert "scenarios" not in panel


def test_a_failed_verification_outranks_every_figure(tmp_path):
    verification = {
        "passed": 11,
        "failed": 1,
        "gates": {"G4_economy": True},
        "decision": "ADOPT",
        "verifier": "scripts/ai_bots_003e_verify.py",
    }
    panel = build_vision_lane_panel(_copy_package(tmp_path / "failed", verification=verification))

    assert panel["state"] == "FAILED"
    assert "1 failure" in panel["reason"]
    #: Las cifras siguen ahí —ocultarlas sería otra forma de mentir— pero el estado manda.
    assert panel["available"] is True


def test_a_published_comparison_without_a_verifier_is_partial(tmp_path):
    panel = build_vision_lane_panel(_copy_package(tmp_path / "pending", verification=None))

    assert panel["state"] == "PARTIAL"
    assert panel["verification"] is None
    assert "no independent verifier" in panel["reason"]


def test_the_dashboard_renders_the_card_from_the_payload():
    script = REPO / "scripts" / "paper_lab_dashboard.py"
    spec = importlib.util.spec_from_file_location("paper_lab_dashboard", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    payload: dict[str, Any] = {
        "dashboard": {"live_control": False},
        "vision_lane": build_vision_lane_panel(ARTIFACTS),
        "controls": {"read_only": True, "start": "x", "status": "x", "stop": "x", "restart": "x"},
    }
    page = module.render_page(payload)

    assert "VISION LANE" in page
    assert "VERIFIED" in page
    assert "-79.180509" in page
