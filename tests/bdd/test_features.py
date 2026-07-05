"""Single pytest-bdd entry point.

All step definitions for ``bdd/features/market_scanner.feature``
(23 scenarios) live in ``tests/bdd/conftest.py`` (the standard
pytest-bdd Pattern A: step defs as globally-visible fixtures via
pytest's conftest mechanism).

This file exists for ONE reason: ``scenarios()`` generates test
functions in the module that calls it, and pytest does not collect
test functions from ``conftest.py``. Without this file, the 23
scenarios in ``bdd/features/market_scanner.feature`` would never
be picked up by pytest.

Why scoped to ``market_scanner.feature`` (not the whole ``bdd/features/``
directory): the other feature files (backtesting, emergency_pause,
execution_engine, paper_trading, risk_manager, signal_generation)
do NOT have step definitions yet, and several contain pre-existing
Gherkin parser errors (e.g., the Spanish "Y" step keyword is not
recognized by the current gherkin parser version). Pointing at the
directory would cause collection errors that mask the real
market_scanner regressions. When the other features get step
definitions wired up in conftest.py, broaden this path.

Anti-patterns (must NOT regress):

- Do NOT move step definitions to per-feature ``test_*.py`` files.
  pytest-bdd step definitions in ``test_*.py`` are namespaced
  per-module; that re-introduces the ``StepDefinitionNotFoundError``
  regression (149/161 failures in F5 round-17..23).
- Do NOT call ``scenarios()`` from ``conftest.py``. Pytest does not
  collect test functions from conftest.py; the call would be a
  silent no-op (or IndexError at collection time on some
  pytest-bdd versions).
- Do NOT broaden this path to the ``bdd/features/`` directory until
  every ``*.feature`` there has matching step definitions in
  conftest.py (otherwise the collection errors from missing step
  defs / Gherkin parser errors will mask real regressions).
"""

from __future__ import annotations

from pathlib import Path

from pytest_bdd import scenarios

# Sole scenarios() call site. Scoped to the ONE feature file whose
# step definitions are wired up in tests/bdd/conftest.py.
scenarios(
    str(Path(__file__).parents[2] / "bdd" / "features" / "market_scanner.feature")
)
