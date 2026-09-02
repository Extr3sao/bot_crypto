"""Integration test collection policy.

Orphaned v031-v033 tests: import modules (signal_types, execution_agent,
risk_guards, alpha_registry, signal_registry, market_scanner_agent,
replay_mode) that were never committed to this repository on any branch
(`git log --all` confirms). They cannot ever pass as-is and break collection
of the whole integration suite. Approved for exclusion from collection
(not deletion) — see docs/PAPER_L5_CERTIFICATION.md.
"""

collect_ignore_glob = [
    "test_v031_*.py",
    "test_v032_*.py",
    "test_v033_*.py",
]
