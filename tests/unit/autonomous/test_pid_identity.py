"""PID-reuse identity tests — GATE STRAT-HARDEN-002 §11.

The independent verifier found ``paper_lab_status.py`` reported
``collector alive=True`` for a PID that Windows had since recycled to
``svchost.exe``. Liveness that trusts a bare PID is false liveness; these tests
pin the identity check that fixes it.
"""

from __future__ import annotations

import os

import trading_bot.autonomous.observability as obs
from trading_bot.autonomous.observability import (
    _image_matches,
    process_alive,
    process_image,
)

LIVE_PID = os.getpid()


def test_image_matches_is_unknown_when_either_side_is_missing() -> None:
    assert _image_matches(None, "python.exe") is None
    assert _image_matches("python.exe", None) is None
    assert _image_matches("", "python.exe") is None


def test_image_matches_is_case_insensitive() -> None:
    assert _image_matches("python.exe", "python.exe") is True
    assert _image_matches("PYTHON.EXE", "python.exe") is True
    assert _image_matches("python.exe", "svchost.exe") is False


def test_process_alive_none_is_unknown_and_dead_pid_is_false() -> None:
    assert process_alive(None) is None
    assert process_alive(999_999_999) is False


def test_process_image_dead_pid_is_none() -> None:
    assert process_image(999_999_999) is None
    assert process_image(None) is None


def test_pid_reused_detects_a_recycled_pid(monkeypatch) -> None:
    # The exact verifier scenario: PID 6936 is alive, but it is not our child.
    monkeypatch.setattr(obs, "process_alive", lambda pid, **kw: pid is not None)
    monkeypatch.setattr(obs, "process_image", lambda pid: "svchost.exe")
    assert obs.pid_reused(6936, expected_image="python.exe") is True


def test_pid_reused_is_false_when_the_image_matches(monkeypatch) -> None:
    monkeypatch.setattr(obs, "process_alive", lambda pid, **kw: pid is not None)
    monkeypatch.setattr(obs, "process_image", lambda pid: "python.exe")
    assert obs.pid_reused(6936, expected_image="python.exe") is False


def test_pid_reused_is_false_when_no_expectation_is_known(monkeypatch) -> None:
    monkeypatch.setattr(obs, "process_alive", lambda pid, **kw: pid is not None)
    assert obs.pid_reused(6936, expected_image=None) is False


def test_process_alive_reports_false_for_an_image_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(obs, "process_image", lambda pid: "svchost.exe")
    assert obs.process_alive(LIVE_PID, expected_image="python.exe") is False


def test_process_alive_stays_true_when_the_image_is_unknown(monkeypatch) -> None:
    # Blindness must never be reported as death.
    monkeypatch.setattr(obs, "process_image", lambda pid: None)
    assert obs.process_alive(LIVE_PID, expected_image="python.exe") is True


def test_process_alive_without_expectation_is_unchanged() -> None:
    assert process_alive(LIVE_PID) is True
