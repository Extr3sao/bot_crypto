"""WP-9B — the disk budget preflight, held to the defect it exists to prevent.

The first 24 h window stopped after 4.16 h because it was launched with an 800 MB
collector valve while its own measured rate was 192 MB/h. Every test here is written
against that arithmetic rather than against the shape of the code:

* the exact configuration that failed is refused **before anything starts**, with the
  numbers in the refusal;
* the one repair the preflight may make (autoscaling the valve) is explicit and
  recorded, and it cannot repair a host that is simply too small;
* the launcher's own entrypoint is exercised, not a copy of its logic, so a test that
  passes is a claim about `scripts/start_paper_lab.py` and not about a harness;
* the rate the launcher uses is the measured one when the audit is present, and the
  plan always names which source it used — a plan that cannot say where its rate came
  from is a number with no provenance.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from trading_bot.research.disk_budget import (
    DECLARED_FALLBACK_BYTES_PER_HOUR,
    STATE_COHERENT,
    STATE_INCOHERENT_BUDGET,
    STATE_INSUFFICIENT_FREE_SPACE,
    STATE_TIGHT,
    STATE_UNBOUNDED,
    plan_window,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]

#: The sealed window's own measurement (192.25 MB/h by 2026-09-30), to the byte: the
#: defect is arithmetic, so the test uses the real number rather than a round one.
MEASURED_BYTES_PER_HOUR = 192_251_690.906

#: The valve that window was launched with.
FAILED_VALVE_BYTES = 800_000_000

GB = 1_000_000_000


def _load_script(name: str) -> Any:
    path = _REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def launcher() -> Any:
    return _load_script("start_paper_lab")


# --------------------------------------------------------------------------- #
# the planner
# --------------------------------------------------------------------------- #


def test_the_valve_that_stopped_the_first_window_is_refused() -> None:
    """The regression: 800 MB cannot pay for 24 h at 192 MB/h, and that is decided here."""
    plan = plan_window(
        hours=24.0,
        collector_max_bytes=FAILED_VALVE_BYTES,
        free=16 * GB,
        rate_bytes_per_hour=MEASURED_BYTES_PER_HOUR,
        rate_source="measured",
    )
    assert plan.state == STATE_INCOHERENT_BUDGET
    assert plan.ok is False
    assert plan.hours_affordable_by_valve == pytest.approx(4.16, abs=0.01)
    assert "this is the defect that stopped the first 24 h window" in " ".join(plan.reasons)


def test_autoscaling_raises_the_valve_and_says_so() -> None:
    plan = plan_window(
        hours=24.0,
        collector_max_bytes=FAILED_VALVE_BYTES,
        free=16 * GB,
        rate_bytes_per_hour=MEASURED_BYTES_PER_HOUR,
        autoscale=True,
    )
    assert plan.state == STATE_COHERENT
    assert plan.autoscaled is True
    # the valve must pay for the whole window at the stress rate, not the mean
    assert plan.collector_max_bytes == plan.required_bytes_at_stress
    assert plan.collector_max_bytes > 24 * MEASURED_BYTES_PER_HOUR
    assert "autoscaled" in " ".join(plan.reasons)


def test_autoscaling_cannot_repair_a_host_that_is_too_small() -> None:
    """Disk size is not a preference: no flag changes free space."""
    plan = plan_window(
        hours=72.0,
        collector_max_bytes=1 * GB,
        free=6 * GB,
        rate_bytes_per_hour=MEASURED_BYTES_PER_HOUR,
        autoscale=True,
    )
    assert plan.state == STATE_INSUFFICIENT_FREE_SPACE
    assert plan.ok is False
    assert plan.autoscaled is False
    assert "free space cannot pay for the window" in " ".join(plan.reasons)


def test_the_reserve_is_spent_last_and_a_tight_valve_still_runs() -> None:
    """A valve that pays for the mean but not the peak warns instead of refusing."""
    tight = plan_window(
        hours=24.0,
        collector_max_bytes=int(24 * MEASURED_BYTES_PER_HOUR) + 1_000_000,
        free=16 * GB,
        rate_bytes_per_hour=MEASURED_BYTES_PER_HOUR,
        stress_multiplier=1.5,
    )
    assert tight.state == STATE_TIGHT
    assert tight.ok is True
    assert tight.recommended_collector_max_bytes == tight.required_bytes_at_stress
    assert tight.recommended_collector_max_bytes > tight.collector_max_bytes


def test_a_window_that_does_not_fit_the_reserve_is_refused_even_at_the_mean() -> None:
    plan = plan_window(
        hours=48.0,
        collector_max_bytes=100 * GB,
        free=int(9.5 * GB),
        rate_bytes_per_hour=MEASURED_BYTES_PER_HOUR,
        reserve_bytes=2 * GB,
    )
    assert plan.state == STATE_INSUFFICIENT_FREE_SPACE


def test_until_stopped_publishes_what_the_valve_and_the_disk_afford() -> None:
    plan = plan_window(
        hours=0.0,
        collector_max_bytes=1_100_000_000,
        free=16 * GB,
        rate_bytes_per_hour=MEASURED_BYTES_PER_HOUR,
    )
    assert plan.state == STATE_UNBOUNDED
    assert plan.ok is True
    assert plan.hours_affordable_by_valve == pytest.approx(5.72, abs=0.01)
    assert plan.hours_affordable_by_disk > plan.hours_affordable_by_valve


def test_the_overhead_term_is_added_to_the_rate_and_the_plan_is_honest_about_it() -> None:
    without = plan_window(hours=24.0, collector_max_bytes=100 * GB, free=16 * GB,
                          rate_bytes_per_hour=MEASURED_BYTES_PER_HOUR,
                          overhead_bytes_per_hour=0.0)
    with_overhead = plan_window(hours=24.0, collector_max_bytes=100 * GB, free=16 * GB,
                                rate_bytes_per_hour=MEASURED_BYTES_PER_HOUR,
                                overhead_bytes_per_hour=200_000.0)
    assert with_overhead.required_bytes > without.required_bytes
    assert with_overhead.effective_rate_bytes_per_hour == pytest.approx(
        MEASURED_BYTES_PER_HOUR + 200_000.0
    )


def test_an_undeclared_rate_is_the_declared_fallback_and_names_itself() -> None:
    plan = plan_window(hours=24.0, collector_max_bytes=100 * GB, free=16 * GB)
    assert plan.rate_bytes_per_hour == DECLARED_FALLBACK_BYTES_PER_HOUR
    assert "declared" in plan.rate_source
    assert plan.as_dict()["rate_source"] == plan.rate_source


def test_the_declared_fallback_is_conservative_against_the_measured_rate() -> None:
    """A fallback below the measured rate would under-provision the next window."""
    assert DECLARED_FALLBACK_BYTES_PER_HOUR >= MEASURED_BYTES_PER_HOUR


# --------------------------------------------------------------------------- #
# the launcher entrypoint
# --------------------------------------------------------------------------- #


def test_the_launcher_costs_the_declared_window_before_starting(launcher: Any) -> None:
    args = launcher.parse_args(["--duration-hours", "24", "--collector-max-bytes", "7000000000"])
    section, refused = launcher.disk_preflight(args)
    assert refused is None
    assert section["state"] == STATE_COHERENT
    assert section["rate_source"].startswith("measured by scripts/wp9_disk_budget_audit.py")
    assert section["refused"] is False
    assert section["required_gb_at_stress"] > 24 * MEASURED_BYTES_PER_HOUR / GB


def test_the_launcher_refuses_the_configuration_that_failed(launcher: Any, monkeypatch: Any,
                                                           capsys: Any) -> None:
    """Through `main()`: exit 4, nothing created, the arithmetic in the message."""
    run_id = "wp9-preflight-refusal"
    monkeypatch.setattr(
        launcher.sys,
        "argv",
        [
            "start_paper_lab.py",
            "--run-id",
            run_id,
            "--duration-hours",
            "24",
            "--collector-max-bytes",
            str(FAILED_VALVE_BYTES),
            "--dry-run",
        ],
    )
    assert launcher.main() == launcher.EXIT_DISK_PREFLIGHT
    printed = capsys.readouterr()
    plan = json.loads(printed.out)
    assert plan["disk"]["budget"]["state"] == STATE_INCOHERENT_BUDGET
    assert plan["disk"]["budget"]["hours_affordable_by_valve"] == pytest.approx(4.16, abs=0.01)
    assert "REFUSED" in printed.err


def test_the_launcher_autoscales_only_when_asked_and_the_children_get_the_new_valve(
    launcher: Any, monkeypatch: Any, capsys: Any, tmp_path: Any
) -> None:
    monkeypatch.setattr(
        launcher.sys,
        "argv",
        [
            "start_paper_lab.py",
            "--run-id",
            "wp9-preflight-autoscale",
            "--duration-hours",
            "24",
            "--collector-max-bytes",
            str(FAILED_VALVE_BYTES),
            "--autoscale-collector-budget",
            "--dry-run",
            # A fresh capture root: this test is about the disk valve, and the
            # capture-root preflight would otherwise refuse a root another run owns.
            "--data-root",
            str(tmp_path / "fresh-capture"),
        ],
    )
    assert launcher.main() == 0
    plan = json.loads(capsys.readouterr().out)
    budget = plan["disk"]["budget"]
    assert budget["autoscaled"] is True
    collector = next(p for p in plan["processes"] if p["name"] == "collector")
    valve = collector["command"][collector["command"].index("--max-total-bytes") + 1]
    assert int(valve) == budget["collector_max_bytes"] > FAILED_VALVE_BYTES


def test_the_launcher_refuses_a_window_the_host_cannot_pay_for(launcher: Any, monkeypatch: Any,
                                                              capsys: Any) -> None:
    """72 h at the measured rate needs more than this host has, so no flag lets it start."""
    monkeypatch.setattr(
        launcher.sys,
        "argv",
        [
            "start_paper_lab.py",
            "--run-id",
            "wp9-preflight-too-big",
            "--duration-hours",
            "72",
            "--collector-max-bytes",
            str(100 * GB),
            "--expected-bytes-per-hour",
            str(int(MEASURED_BYTES_PER_HOUR)),
            "--disk-reserve-gb",
            "100",
            "--dry-run",
        ],
    )
    assert launcher.main() == launcher.EXIT_DISK_PREFLIGHT
    plan = json.loads(capsys.readouterr().out)
    assert plan["disk"]["budget"]["state"] == STATE_INSUFFICIENT_FREE_SPACE


def test_an_operator_declared_rate_overrides_the_measurement_and_says_so(launcher: Any) -> None:
    args = launcher.parse_args(
        ["--duration-hours", "24", "--expected-bytes-per-hour", "500000000"]
    )
    section, refused = launcher.disk_preflight(args)
    assert refused is not None  # 12 GB needed against a 1.1 GB default valve
    assert section["rate_source"] == "operator: --expected-bytes-per-hour"
    assert section["required_gb_at_stress"] == pytest.approx(18.0, abs=0.01)


def test_the_committed_audit_is_the_source_of_the_measured_rate(launcher: Any) -> None:
    """The launcher's rate is a published artefact, re-readable by anyone."""
    audit = json.loads(
        (Path(launcher.DISK_AUDIT_PATH) if Path(launcher.DISK_AUDIT_PATH).is_absolute()
         else _REPO_ROOT / launcher.DISK_AUDIT_PATH).read_text(encoding="utf-8")
    )
    rate, overhead, source = launcher.resolve_capture_measurement(
        launcher.parse_args(["--duration-hours", "24"])
    )
    assert rate == audit["measurement"]["rates"]["planning_rate_bytes_per_hour"]
    assert overhead == audit["components"]["overhead_bytes_per_hour"]
    assert audit["verdict"] == "DISK_BUDGET_MEASURED"
    assert str(audit["windows"]["sealed"]["run_id"]) in source
