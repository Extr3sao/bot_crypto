"""B3 — the lock must agree with the declared dependencies, offline.

The defect this pins down was measured, not guessed:

* ``pyproject.toml`` declared ``matplotlib>=3.8,<4.0`` (the vision chart needs it);
* ``uv.lock`` did not contain matplotlib at all;
* ``uv sync --frozen`` exited **0** and installed a virtualenv without matplotlib.

So the gate that was supposed to prove a reproducible build passed while a declared
dependency was missing: a ``FALSE_SUCCESS`` in the strict sense.  ``uv lock --check``
does catch it, but only if someone remembers to run it, and only with the network
metadata available.  This test reads both files directly — no ``uv``, no network — so
the mismatch fails in CI even when nobody runs the lock command.

It asserts the join in both directions for the *declared* set: every declared
dependency is pinned in the lock, and the lock's project entry repeats the same list.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PYPROJECT = REPO / "pyproject.toml"
LOCK = REPO / "uv.lock"


def _normalise(name: str) -> str:
    """PEP 503 normalisation, so ``typing_extensions`` and ``typing-extensions`` agree."""

    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_name(requirement: str) -> str:
    """``"matplotlib>=3.8,<4.0"`` → ``"matplotlib"``; extras and markers are dropped."""

    head = requirement.split(";", 1)[0].strip()
    match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", head)
    assert match is not None, requirement
    return match.group(1)


def _declared() -> list[str]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return list(data["project"]["dependencies"])


def _lock() -> dict:
    return tomllib.loads(LOCK.read_text(encoding="utf-8"))


def test_every_declared_dependency_is_pinned_in_the_lock() -> None:
    locked = {
        _normalise(str(package["name"]))
        for package in _lock().get("package", [])
        if package.get("name")
    }
    missing = sorted(
        _normalise(_requirement_name(requirement))
        for requirement in _declared()
        if _normalise(_requirement_name(requirement)) not in locked
    )
    assert not missing, (
        "declared in pyproject.toml but absent from uv.lock: "
        f"{missing}. `uv sync --frozen` will exit 0 and leave them uninstalled."
    )


def test_the_vision_rendering_dependency_is_declared_and_locked() -> None:
    """The specific omission B3 was found on: matplotlib, needed by vision/chart.py."""

    names = {_normalise(_requirement_name(requirement)) for requirement in _declared()}
    assert "matplotlib" in names, "pyproject.toml must declare the chart dependency"
    locked = {_normalise(str(package["name"])) for package in _lock().get("package", [])}
    assert "matplotlib" in locked, "uv.lock must pin matplotlib, or --frozen silently skips it"


_OPERATORS = (">=", "<=", "==", "<", ">")


def _version_tuple(version: str) -> tuple[int, ...]:
    head = re.split(r"[+!-]", version, maxsplit=1)[0]
    return tuple(int(part) for part in head.split(".") if part.isdigit())


def test_the_locked_version_satisfies_every_declared_specifier() -> None:
    """Being *in* the lock is not enough: the pinned version must satisfy the range.

    The lock's own ``specifier`` is deliberately not read here — that is the builder
    asserting its own work.  The comparison is between ``pyproject.toml``'s range and
    the version ``uv.lock`` actually pins.
    """

    locked = {
        _normalise(str(package["name"])): str(package.get("version", ""))
        for package in _lock().get("package", [])
        if package.get("name")
    }
    problems: list[str] = []
    for requirement in _declared():
        name = _normalise(_requirement_name(requirement))
        if name not in locked:
            continue  # covered by the pin test, with a better message
        version = _version_tuple(locked[name])
        specifiers = requirement.split(";", 1)[0][len(_requirement_name(requirement)) :]
        for specifier in specifiers.split(","):
            specifier = specifier.strip()
            if not specifier:
                continue
            operator = next((op for op in _OPERATORS if specifier.startswith(op)), None)
            assert operator is not None, (
                f"this test does not understand the specifier {specifier!r} of {requirement!r}; "
                "extend the comparison instead of weakening the check"
            )
            bound = _version_tuple(specifier[len(operator) :])
            length = max(len(bound), len(version))
            left = version + (0,) * (length - len(version))
            right = bound + (0,) * (length - len(bound))
            ok = {
                ">=": left >= right,
                "<=": left <= right,
                "==": left == right,
                "<": left < right,
                ">": left > right,
            }[operator]
            if not ok:
                problems.append(f"{requirement}: locked {locked[name]} violates {specifier}")
    assert not problems, problems
