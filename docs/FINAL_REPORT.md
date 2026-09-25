# FINAL_REPORT — RUNTIME HARDENING phase (PAPER_RUNTIME_HARDENED_VERIFIED)

```text
PHASE: RUNTIME_HARDENING + STARTUP_RECONCILIATION + RECERTIFICATION + REAL-DATA PAPER
HEAD BEFORE: c4a1e02
VERIFIED_COMMIT: runtime-code commit b1f427e (+ docs-only successors, diff
  proven empty for src/ scripts/ tests/ config/); verifier 11/11 re-executed
  in the fresh worktree at f6626b6, 3570fd7 and at final HEAD e458477
  (= git rev-parse HEAD; see docs/INDEPENDENT_RECERTIFICATION.md coverage rule)
BRANCH: main
COMMITS (phase):
  daf54af feat(paper): durable state + startup reconciliation V4 + closed-candle gate
  c21a44a fix(paper): risk engine sees restored exposure (PORTFOLIO-CONTEXT-01)
  eb0468e feat(paper): provider-output sanitization + failure-policy tests (§14)
  b1f427e chore(config): realdata profile (binance testnet, read-only)
  f6626b6 + 3570fd7 docs(paper): hardening deliverables + recert fixed-point
WORKTREE_STATUS: clean (porcelain = 0); reports/runs captures gitignored by policy

RUNTIME ENTRYPOINT: scripts/start_paper_trading.py (PAPER-only)
REAL-DATA PROVIDER: Binance testnet spot via existing CCXT hub (read-only,
  no credentials; config/realdata profile, CL-4 no-fallback)
PAPER COMMAND: uv run python scripts/start_paper_trading.py --assets BTC,ETH,SOL
  --timeframe 5m --max-cycles 2 --provider ccxt --interval 0
  --config-dir config/realdata --state-path <path> [--fresh]

STARTUP RECONCILIATION: IMPLEMENTED + EXECUTED — StartupReconcilerV4 wired;
  statuses CONSISTENT/RECOVERED/MISMATCH/FATAL; equity identity enforced;
  corrupt file fail-closed with .corrupt backup (docs/STARTUP_RECONCILIATION_CONTRACT.md)
PROCESS RESUME: durable snapshot per session (crash window ≤ 1 session);
  restart → RECOVERED proven live (RUN-C) and in 10 crash-matrix tests
EXECUTION IDEMPOTENCY: exactly-once via durable intent ledger (pre-broker-call
  registration) + engine/broker duplicate gates; live-suppressed 6+2+3 dups
UNKNOWN ORDER RECOVERY: ledger marks sent-before-fill ⇒ retry suppressed
  (fail closed); materialization only from durable position rows (tested)
PORTFOLIO RECOVERY: broker book + risk counters + exposure map restored
  BEFORE next decision; live veto "Max open positions reached (3)" on
  restored book; zero-exposure assumption impossible (tested)
DECISION TRACE RECOVERY: chain (intent→order→fill→position→closed-trade)
  reconstructable from durable rows keyed by cloid/symbol; full
  snapshot→strategy→signal→proposal→decision→risk→intent→order→fill→outcome
  replay-by-run_id API remains DEFERRED P2 (recorded)

TEMPORAL INTEGRITY: PASS — sanitizer→closed-candle(V3)→trim→context validation
  (4 layers); real-feed PIT capture PASS; 13 provider-failure policy tests;
  timeout/network errors propagate (never silent NO_TRADE)
REAL-DATA PAPER: PASS — REAL-DATA-PAPER-01 + RUN-B/C/D on Binance testnet,
  read-only, no credentials; forming candle excluded (PIT capture file)
RISK BYPASS: NOT FOUND — single execute_signal call-site post-approval;
  veto paths incl. restored-exposure max-open veto (live evidence)
BUILDER/VERIFIER INDEPENDENCE: PROCESS_INDEPENDENCE = PASS (fresh worktree,
  fresh venv, raw outputs, read-only verifier);
  BUILDER_VERIFIER_ROLE_INDEPENDENCE = PARTIAL (same actor session authored
  commits and ran verification; verifier script itself from a prior session,
  unmodified). PARTIAL not upgraded — full PASS needs an external verifier actor
FRESH CHECKOUT VALIDATION: PASS — ../tap_recert worktree at c4a1e02 (584/11-of-11)
  and at b1f427e (607 tests, verifier 11/11, mypy 0/238, ruff clean, porcelain 0)

TESTS:
- unit:        full unit scope green (crash matrix 10 + provider policy 13 new)
- contract:    provider failure policy pinned (test_provider_failures.py)
- integration: paper e2e 001/002/003 green
- runtime:     verifier 11/11 on clean HEAD (primary + fresh worktree)
- e2e:         RUN-A..RUN-E through the real entrypoint, exit 0 each
- adversarial: crash boundaries A–H, unknown outcome, duplicate callback,
               equity tampering, corrupt file, exposure visibility, forming/
               future/stale/duplicate/out-of-order/invalid provider data
- total:       607 passed, 0 failed, 0 skipped (myPy 0/238, ruff clean)

RUN-A: deterministic NO_TRADE (fake) — fail-closed strategy stage, reasons recorded
RUN-B: TRADE lifecycle (real data, fresh book) — 3 orders cycle 1; duplicates suppressed after
RUN-C: crash+restart+reconciliation (real book) — RECOVERED; post-restart zero re-execution;
       restored-exposure hard veto live
RUN-D: duplicate/retry intent (real data) — cycle 1: 2 orders; cycle 2: 2 dups, 0 orders
RUN-E: REAL-DATA-PAPER-01 — real feed, paper path, state persisted, PIT capture PASS

FALSE_SUCCESS: 0 — every claim maps to an executed command/test on VERIFIED_COMMIT;
  one earlier closure-proof method (git-status-only) self-corrected to fresh-checkout
  protocol; RUN-E pre-fix observation re-anchored to final-HEAD run (both recorded)
DEFECTS FIXED: zero-persistence restart (GAP-R1), forming-candle leak on real feeds,
  risk zero-exposure assumption after restart, duplicate-retry across restart
DEFECTS OPEN: none on phase scope; deferred recorded (replay API P2; MISMATCH
  auto-repair deliberately absent; V1/V3 orphan modules awaiting cleanup phase)
BLOCKERS: none for this phase

EVIDENCE FILES:
  docs/STARTUP_RECONCILIATION_CONTRACT.md   docs/CRASH_RECOVERY_MATRIX.md
  docs/INDEPENDENT_RECERTIFICATION.md       docs/REAL_DATA_PAPER_RUN.md
  docs/RUN_REPORT.md (+json)                docs/runtime_authority_map.md (updated)
  docs/PAPER_OPERATIONAL_GAP_ANALYSIS.md    (GAP-R1/R5 closed)
  reports/runs/* (raw stdout + PIT capture) tests/unit/paper/{test_paper_recovery,
  test_provider_failures}.py

FINAL STATUS: PAPER_RUNTIME_HARDENED_VERIFIED
NOT: LIVE_READY / PRODUCTION_READY / PROFITABLE / CERTIFIED_FOR_CAPITAL

NEXT PHASE (gate met): MULTI_AGENT_RUNTIME_INTEGRATION gap analysis — decide
  which agentic capabilities are runtime-reachable and measure incremental
  value against THIS deterministic baseline (CONTROL) before any adoption.
```
