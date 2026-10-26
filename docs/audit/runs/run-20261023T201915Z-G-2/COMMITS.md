# COMMITS — G-2

Branch `audit/mt0004-negative-controls`. Not pushed, not merged.

| # | Commit | Message | Files | Lines |
|---|---|---|---|---|
| 1 | `164e2d48` | Specify the hot stop before writing it, and prove the path it protects | 2 | +234 / −1 |
| 2 | `1f33421c` | Close the stop at the boundary the order actually crosses | 6 | +1570 / −10 |
| 3 | *(this commit)* | Record the G-2 run against the commit it verified | run docs | see below |

## 1 — contract (`164e2d48`)

- `docs/audit/G-2.md` (new): claim, preflight evidence, REQ/ACC, exact
  `allowed_paths`/`forbidden_paths`, linearization argument, stop conditions.
- `docs/audit/runtime_authority_map.md`: G-2 row now names the gate; §8 adds the
  boundary diagram and the two paths it deliberately does not cover.

## 2 — implementation (`1f33421c`)

| File | Nature |
|---|---|
| `src/trading_bot/autonomous/hot_stop.py` | **new** — gate, control file, audit, lock |
| `src/trading_bot/autonomous/runtime.py` | +34/−0 — default gate, cycle poll, dispatch inside the boundary |
| `src/trading_bot/app.py` | +66/−1 — `kill-switch` implemented; `status` still a stub |
| `tests/unit/autonomous/test_hot_engage.py` | **new** — 12 tests |
| `tests/unit/test_app_cli_contract.py` | `DECLARED_UNIMPLEMENTED` → `{status}`; 4 new CLI tests |
| `scripts/audit/g2_mutants.py` | **new** — 7-mutant matrix |

**Not touched:** `autonomous/decision.py`, `paper/**`, `config/**`,
`execution/**`, `tests/unit/autonomous/test_decision_kill_switch.py`,
`tests/unit/autonomous/test_kill_switch_negative.py`,
`scripts/audit/negative_controls.py`, `.github/**`, `pyproject.toml`,
`uv.lock`, `.gitignore`.

## 3 — this commit

Run reports, the offline trace script and its output, the mutation matrix
result, the verifier's `verification.json`, and the backlog update.

Its SHA cannot appear in this file (a commit cannot name itself). Obtain it
with `git log -1 --format=%H -- docs/audit/runs/run-20261023T201915Z-G-2/FINAL_REPORT.md`.

## Why the split

Commit 1 freezes the scope before any code exists, so "the implementation
stayed inside `allowed_paths`" is a claim about commit 2 measured against a
document that predates it — not a post-hoc description. Commit 3 keeps the
evidence and the verified commit distinguishable: `1f33421c` is what the
verifier reads, and the reports describe it rather than being part of it.
