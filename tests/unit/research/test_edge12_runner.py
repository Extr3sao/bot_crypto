"""WP-EDGE-12B — the regressions behind the mechanism decision.

The runner's deliverable is a *decision*, and a decision is the easiest thing in this
campaign to get right by accident: the report says ``LOGON_TRIGGER`` and a reader has no
way to tell whether the host refused S4U or whether nobody asked it. Two defects this
package closed while checking that are the reason these tests exist:

* the S4U probe registered the committed proposal **unchanged**, so the scheduler read
  the principal back as ``Interactive`` and the probe would have called a mechanism
  viable that it had never exercised;
* the verdict was "the registration was accepted" rather than "the registration was
  accepted **and the scheduler read ``S4U`` back**".

So what is asserted here is the shape of the definition the probe registers — that it is
a different definition, that the difference is the one intended, and that the lane's own
action is not in it. Registering the lane's action under a probe's name would let the
probe write an out-of-phase tick into the very ledger the continuity reading measures.

Nothing here registers a task, reads the scheduler or touches the host.

Research only: public market data, no credentials, no orders, no capital.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from trading_bot.research.edge12 import runner  # noqa: E402

#: The registration the lane actually carries, as WP-EDGE-04R read it back: an interactive
#: principal, a quarter-hour cadence with its own phase, and the observer's own action.
LIVE_EVIDENCE = {
    "task": {
        "task_name": "TradingAgentic-EDGE04-Forward",
        "user_id": "HOST\\operator",
        "logon_type": "InteractiveToken",
        "wake_to_run": "true",
        "restart_count": "2",
        "triggers": [{"type": "MSFT_TaskTimeTrigger", "start_boundary": "2026-10-01T00:07:00"}],
        "actions": [
            {
                "command": "C:\\Python\\python.exe",
                "arguments": "scripts/edge04_observer.py --scheduled --due",
                "working_directory": "C:\\repo",
            }
        ],
    }
}


def _probe(tmp_path) -> dict:
    return runner.s4u_probe_definition(
        evidence=LIVE_EVIDENCE, scratch=tmp_path, interval_minutes=15
    )


# ------------------------------------------------------------------ the S4U probe's shape
def test_the_s4u_probe_registers_a_definition_that_is_really_s4u(tmp_path):
    """The registration must change the principal, and the XML must say so."""
    definition = _probe(tmp_path)
    assert definition["logon_type"] == "S4U"
    assert definition["logon_type_the_live_task_has"] == "InteractiveToken"
    assert "<LogonType>S4U</LogonType>" in definition["xml"]
    assert "InteractiveToken" not in definition["xml"]


def test_the_s4u_probe_never_carries_the_lane_own_action(tmp_path):
    """A probe that ran the lane's action would write an out-of-phase tick into the ledger."""
    definition = _probe(tmp_path)
    xml = definition["xml"]
    assert "edge04_observer.py" not in xml
    assert "--scheduled" not in xml
    assert definition["swapped"] == {"command": "cmd.exe", "arguments": "/c exit 0"}
    assert "cmd.exe" in xml


def test_the_probe_carries_the_live_phase_and_the_live_home(tmp_path):
    """The cadence's own StartBoundary is carried over, so the probe does not move the phase."""
    definition = _probe(tmp_path)
    carried = definition["carried_over"]
    assert carried["start_boundary"] == "2026-10-01T00:07:00"
    assert carried["user_id"] == "HOST\\operator"
    assert carried["working_directory"] == "C:\\repo"
    assert carried["interval_minutes"] == 15
    assert carried["wake_to_run"] is True
    assert "<StartBoundary>2026-10-01T00:07:00</StartBoundary>" in definition["xml"]


def test_the_scheduler_s_string_true_is_read_as_a_boolean(tmp_path):
    """``bool("False")`` is ``True``, and the scheduler spells booleans out."""
    assert runner._as_bool("true") is True
    assert runner._as_bool("False") is False
    assert runner._as_bool(True) is True
    assert runner._as_bool(None) is False
    assert "true" in _probe(tmp_path)["xml"]


# ------------------------------------------------------------------------ the decision
def _probes(*, registration_ok: bool, left_behind: bool = False) -> dict:
    def row(verdict: str, **extra: object) -> dict:
        return {"verdict": verdict, **extra}

    return {
        "probes": {
            "S4U_PROPOSAL": row(
                "VIABLE" if registration_ok else "NEEDS_ELEVATION",
                registration_ok=registration_ok,
                task_left_behind=left_behind,
                registration_output="Acceso denegado.",
                read_back_is_s4u=registration_ok,
            ),
            "S4U_BARE": row("NEEDS_ELEVATION"),
            "SYSTEM_PRINCIPAL": row("NEEDS_ELEVATION"),
            "WINDOWS_SERVICE": row("NOT_ATTEMPTED_NEEDS_ELEVATION", why_not_attempted="no token"),
            "AUTHORISED_SERVICE_ACCOUNT": row("NO_ACCOUNT_DESIGNATED", why_not_attempted="none"),
            "INDEPENDENT_HOST_RUNNER": row("NO_AUTHORISED_INFRASTRUCTURE_FOUND", reading="none"),
            "LOGON_TRIGGER": row("VIABLE", detail="registration accepted"),
            "WITNESS_ACTION": row("VIABLE"),
        },
        "additive_levers": {"scheduled_launches": 223},
    }


def _decide(probes: dict) -> dict:
    return runner.decide(
        probes=probes,
        preflight_row={"verdict": "PREFLIGHT_PASS"},
        evidence=LIVE_EVIDENCE,
    )


def test_a_refused_registration_is_not_a_viable_mechanism():
    """The host refused it, so the dependence is not removed by this process."""
    decision = _decide(_probes(registration_ok=False))
    assert decision["selected"] == "LOGON_TRIGGER"
    assert decision["what_the_selected_mechanism_buys"]["removes_the_session_dependence"] is False
    assert decision["what_the_selected_mechanism_buys"]["bounds_recovery_after_a_sign_in"] is True
    assert "LOGON_TRIGGER" in decision["available_without_new_privileges"]
    assert decision["blocked"]["S4U_PROPOSAL"] == "NEEDS_ELEVATION"


def test_an_accepted_registration_removes_the_dependence_and_is_preferred():
    decision = _decide(_probes(registration_ok=True))
    assert decision["selected"] == "S4U_TASK"
    assert decision["what_the_selected_mechanism_buys"]["removes_the_session_dependence"] is True


def test_a_probe_task_left_behind_disqualifies_its_own_mechanism():
    """A mechanism whose rehearsal left a registration behind is not one to select."""
    decision = _decide(_probes(registration_ok=True, left_behind=True))
    assert decision["selected"] == "LOGON_TRIGGER"


def test_every_mechanism_the_rfc_names_is_evaluated_and_none_is_silent():
    decision = _decide(_probes(registration_ok=False))
    evaluated = {row["mechanism"] for row in decision["evaluations"]}
    assert evaluated == {mechanism for mechanism, _question in runner.MECHANISMS}
    assert all(row["verdict"] != "NOT_EVALUATED" for row in decision["evaluations"])
    # Every evaluation carries a detail, including the ones that were never attempted: a
    # mechanism that is listed without its reason reads as one that passed.
    assert all(row["detail"] for row in decision["evaluations"])


def test_the_decision_applies_nothing_and_authorises_nothing():
    decision = _decide(_probes(registration_ok=False))
    assert decision["applied_to_the_live_task"] is False
    assert decision["order_sent"] is False
    assert decision["promotion"] == "NONE"
    assert decision["hypothetical"] is True


# ------------------------------------------------------------------ the console's words
def test_an_utf8_console_answer_keeps_its_accents():
    assert runner._decode("Acción denegada".encode()) == "Acción denegada"


def test_a_console_answer_is_stripped_and_decoded_whatever_the_code_page():
    """A refusal is evidence, and evidence a reader cannot read is not evidence."""
    for encoding in ("utf-8", "cp850", "cp1252"):
        decoded = runner._decode("Acceso denegado\r\n".encode(encoding))
        assert decoded == "Acceso denegado"
    # No byte sequence may raise: the probe records what the tool said, not a traceback.
    assert isinstance(runner._decode(bytes(range(256))), str)


# ------------------------------------------------------------------------ the moved lines
def test_the_swapped_lines_are_counted_rather_than_claimed():
    """``only the action differs`` has to be a measurement, not an assertion."""
    left = "a\nb\nc\n"
    assert runner._moved_lines(left, left) == 0
    assert runner._moved_lines(left, "a\nb\nz\n") == 1
    assert runner._moved_lines(left, "a\nb\n") == 1
    assert runner._moved_lines("a\n", "a\nb\nc\n") == 2


def test_the_probe_definition_differs_from_the_one_it_is_derived_from(tmp_path):
    """The committed shape, built here, so the difference is measured and not asserted.

    The probe answers whether *this* definition can be registered with S4U from an
    unelevated process. A probe that re-registered the committed definition unchanged
    would answer whether an ``InteractiveToken`` task can be registered, which is a
    question nobody asked and whose answer is already on the host.
    """
    from trading_bot.research.edge04r import session as session_probe

    committed = session_probe.build_task_xml(
        user_id="HOST\\operator",
        command="C:\\Python\\python.exe",
        arguments="scripts/edge04_observer.py --scheduled --due",
        working_dir="C:\\repo",
        witness_path=tmp_path / "witness.txt",
        logon_type="InteractiveToken",
        interval_minutes=15,
        start_boundary="2026-10-01T00:07:00",
    )
    assert "--scheduled" in committed
    assert "InteractiveToken" in committed
    probe = _probe(tmp_path)["xml"]
    assert runner._moved_lines(committed, probe) > 0
    # The difference is the principal and the action payload, and nothing structural: the
    # trigger set and the number of actions are the same document's shape.
    assert probe.count("<Triggers>") == committed.count("<Triggers>") == 1
    assert probe.count("<Exec>") == committed.count("<Exec>")
