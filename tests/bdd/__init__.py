"""Pytest-bdd scenarios for the scanner package (TSK-103.5.2).

23 escenarios (6 pre-existentes en ``bdd/features/market_scanner.feature``
+ 17 nuevos anyadidos en F5) se distribuyen entre los 7 step_defs
modules en ``tests/bdd/step_defs/``. Una vez ``pytest --collect-only``
sea verde en los 23 scenarios, F5 stub ``TSK-103.5.7.7`` se cierra.

Estructura:

    tests/bdd/
        __init__.py                  # este archivo (docstring-only)
        conftest.py                  # pytest-bdd glue + re-exports conftest
        step_defs/
            __init__.py              # package marker
            test_snapshot_steps.py       # RF-2 + RNF-6 (3 scenarios)
            test_state_steps.py          # RF-3.x + RF-5.x (3 scenarios)
            test_runtime_steps.py        # RF-6.x + RF-7.x (3 scenarios)
            test_ast_and_registry_steps.py  # RF-8 + RF-9 (3 scenarios)
            test_scoring_steps.py        # RF-10 (2 scenarios)
            test_edge_steps.py           # CL-1 + CL-3 + CL-6 (3 scenarios)
"""
