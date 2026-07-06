"""Tests/bdd/step_defs package marker.

Pytest auto-discovers test_*.py files in this directory; the empty
``__init__.py`` ensures the directory is treated as a Python package
so module-relative imports resolve cleanly.  The step definitions
themselves are registered globally to pytest-bdd's step registry at
collection time, regardless of whether they live in conftest.py
(root consolidation per the F2 market_scanner pine) or in
per-feature step_defs/*.py modules (per the F4 TSK-200.4.5 choice).
"""
