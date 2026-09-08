# IDENTITY_RECONCILIATION — EXTERNAL-AUDIT-RECONCILIATION-01

Checkpoint: EXTERNAL-AUDIT-RECONCILIATION-01
Authoritative project: **Trading Agentic Portable** (package `crypto-scalping-agentic-bot`)
Date: 2026-09-08
Rule applied: no finding from the external audit is accepted as fact about this
project until identity is proven. Findings are re-audited against current HEAD.

## 0. Claimed identities in the external audit

| Claimed name | Public resolution (2026-09-08) |
| --- | --- |
| `Extr3sao/Bot-Trading` | GitHub API returns **404 Not Found** (repository not publicly resolvable under this owner/name) |
| `AETHEL/AstraQuant` | GitHub API returns **404 Not Found** (repository not publicly resolvable under this owner/name) |

## 1. Current repository identity (measured, not assumed)

| Field | Value |
| --- | --- |
| `origin` fetch/push | `https://github.com/Extr3sao/bot_crypto.git` |
| Current HEAD | `a282fcca2098e3623c50b3c1033ef75e30337659` (`a282fcc`, branch `feat/ma-2-specialist-opportunity-swarm`) |
| HEAD subject | `docs(demo): CERT-DEMO-PAPER-01 round-2 record - full fresh re-verification at exact 1dfeea8, 27/27 gates` |
| Directory identity | `src/trading_bot/` package with `agents, app.py, backtesting, config, demo, domain, execution, indicators, market_data, multi_agent, paper, portfolio, research, risk, scanner, strategies, ...` |
| Package identity | `pyproject.toml` → `name = "crypto-scalping-agentic-bot"`, version `0.1.0`, Python `>=3.11` |
| Runtime entrypoints | `src/trading_bot/app.py` (live-disabled runtime), `src/trading_bot/demo/paper_multi_agent.py` (DEMO-PAPER-01 / POC01 paper runtime), `src/trading_bot/paper/paper_cycle.py` |
| Runtime banner | `TRADING AGENTIC PORTABLE - PAPER MODE (LIVE DISABLED)` (demo entrypoint) |

## 2. Commit-hash reconciliation (decisive evidence)

The external audit cites three hashes as the audited state:

| Hash | Exists in this object DB? | Ancestor of HEAD? | Subject / date |
| --- | --- | --- | --- |
| `3c274cc` | YES (`git cat-file -t` → commit) | NO (side branch) | `fix(poc01): start campaign dashboard serve thread + safe stop` — 2026-09-06 |
| `bb46c92` | YES | NO (side branch) | `ADMISSION-FOUNDATION-01: registry, state machine, builder/verifier, confirmation V2, shadow plane` — 2026-09-07 |
| `39578a6` | YES | NO (side branch) | `ADMISSION-FOUNDATION-01: evidence — registry seed + CONF-EDGE-002-001 manifest` — 2026-09-07 |

SHA-1 object hashes cannot be manufactured in a different history. The presence
of all three audited hashes in this repository's object database is **cryptographic
proof that the external audit was executed against this project's history**, even
though the names it uses (`Bot-Trading`, `AstraQuant`) do not match the current
remote (`Extr3sao/bot_crypto`) and do not resolve publicly.

The audited commits are **not ancestors of current HEAD** (`a282fcc`): they live on
side branches/worktrees (e.g. the `admission-foundation-01` worktree present in
`.worktrees/`). Therefore the audit describes **side-branch state**, not current
HEAD, and every claimed gap was re-audited against HEAD directly.

## 3. Verdict

**SAME_HISTORY_DIFFERENT_NAME** (with a remote-name mismatch caveat):

- The audited commit hashes belong to *this* repository's object database → same history.
- The audited names (`Extr3sao/Bot-Trading`, `AETHEL/AstraQuant`) do not match the
  current remote (`Extr3sao/bot_crypto`) and are not publicly resolvable → the
  names are stale aliases / renamed identities, not a different codebase.
- `RELATED_REPOSITORY` and `DIFFERENT_REPOSITORY` are excluded by the hash evidence.
- `SAME_REPOSITORY` (exact name match) is excluded by the remote mismatch.

Consequence per the checkpoint directive: findings from the external audit are
**admissible as claims only**; each was re-audited against current HEAD
(`a282fcc`) in `docs/external-audit-01/GAP_MATRIX.md`. No finding was applied
without local source + runtime evidence.

## 4. merge-base notes

- `3c274cc`, `bb46c92`, `39578a6` are all NOT ancestors of HEAD; no merge-base
  computation is required to reject "audit == HEAD" equivalence. Where a finding
  depended on side-branch code (e.g. ADMISSION-FOUNDATION-01 shadow plane), the
  gap matrix classifies it against HEAD state, not branch state.

## 5. Decision record

1. Treat the external audit as an **input claim list**, not as facts.
2. Re-audit every claim at HEAD `a282fcc` (see `GAP_MATRIX.md`).
3. Do not import code, config, or governance state from the audited names.
4. POC01 remains frozen and untouched by this reconciliation (see FINAL_REPORT).
