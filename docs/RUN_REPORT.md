# RUN_REPORT — consolidated

Phase 1 (PAPER_OPERATIONAL): DEMO-PAPER-01 — see history section below.
Phase 2 (RUNTIME HARDENING): RUN-A..RUN-E — current section.

## Hardening-phase runs (final HEAD `b1f427e`)

Full details per run: `docs/REAL_DATA_PAPER_RUN.md`, `docs/CRASH_RECOVERY_MATRIX.md`.
Raw stdout captures: `reports/runs/*` (gitignored output dir by policy).

| Field | Value |
| --- | --- |
| run_ids | RUN-A, RUN-B, RUN-C, RUN-D, RUN-E (=REAL-DATA-PAPER-01) |
| commit | `b1f427e` (all five, plus fresh-worktree recert 607 tests + verifier 11/11) |
| provider | RUN-A: fake (deterministic) · RUN-B/C/D/E: Binance **testnet** spot, read-only, no credentials |
| dataset fingerprint | per-context `sha256:` content fingerprints (engine `_fingerprint`); PIT capture file for real feed |
| assets / timeframe | BTC,ETH,SOL (RUN-D: BTC,ETH) · 5m |
| initial persisted state | RUN-A/D: none (fresh, `CONSISTENT`) · RUN-E: rotated (`--fresh`) · RUN-C: RUN-E's book |
| restored state | RUN-C: 3 open positions, 3 intents, equity 10000.0 (identity verified), risk counters |
| reconciliation actions | `RECOVERED` restore (no economic rewrites); duplicate intents suppressed; exposure mirrored into risk |
| execution intents / orders / fills | RUN-B: 3 intents, 3 orders, 3 fills · RUN-D: 2/2/2 · RUN-E(final): 0 new orders (book full) |
| risk decisions | RUN-C post-restore: `risk_rejected=3` "Max open positions reached (3)" (hard veto on restored exposure) |
| portfolio before→after | RUN-B: 10000→10000 +3 open positions · RUN-C: unchanged book, veto enforced |
| errors / retries | 0 errors · retries = duplicate intents suppressed (3/3, 2/2) |
| duplicates suppressed | RUN-B: 6 across 2 cycles · RUN-D: 2 · RUN-C post-restart: 3 |
| final outcome | RUN-A NO_TRADE (valid) · RUN-B TRADE lifecycle · RUN-C RECOVERED+VETO · RUN-D exactly-once · RUN-E real-data paper path OK |
| evidence refs | `reports/runs/*.log`, `reports/runs/REAL-DATA-PIT-CAPTURE.txt`, `docs/INDEPENDENT_RECERTIFICATION.md` |

## PIT capture (real feed, §15)

`latest_consumed_data_time (1790325600000) <= decision_time (1790325945000)`;
forming candle excluded; closed rule `open+tf <= decision_time` verified.
File: `reports/runs/REAL-DATA-PIT-CAPTURE.txt`.

## RUN_REPORT.json (machine-readable, hardening phase)

```json
{
  "phase": "RUNTIME_HARDENING",
  "verified_commit": "b1f427ec5daeed7cc9fe054d4b841a4952bc8f15",
  "runs": {
    "RUN-A": {"provider": "fake", "decision": "NO_TRADE", "orders": 0, "exit": 0},
    "RUN-B": {"provider": "binance_testnet", "orders_cycle1": 3, "duplicates": 6, "exit": 0},
    "RUN-C": {"provider": "binance_testnet", "reconciliation": "RECOVERED", "restored_positions": 3,
               "restored_intents": 3, "post_restart_orders": 0, "risk_veto": "max_open_positions(3)", "exit": 0},
    "RUN-D": {"provider": "binance_testnet", "orders_cycle1": 2, "duplicates_cycle2": 2, "exit": 0},
    "RUN-E": {"provider": "binance_testnet", "decision": "NO_TRADE_ON_FULL_BOOK", "risk_rejected": 3,
               "pit_capture": "reports/runs/REAL-DATA-PIT-CAPTURE.txt", "exit": 0}
  },
  "temporal_integrity": "PASS (real-feed PIT capture + 13 provider-failure policy tests)",
  "exactly_once": "PASS (unit + live duplicate suppression across cycles and restart)",
  "false_success": 0,
  "fresh_checkout_validation": {"commit": "b1f427e", "pytest": 607, "verifier": "11/11", "mypy": 0, "ruff": "clean"}
}
```

---

# History — DEMO-PAPER-01 (PAPER_OPERATIONAL phase, HEAD 5e6f963)

- run_id: `DEMO-PAPER-01` · 2026-09-25 · commit `5e6f963` · provider `fake` (deterministic synthetic)
- assets BTC/ETH/SOL 5m · 2 sessions · exit 0
- decision **NO_TRADE** (first-class): signals_generated=0, rejections `no_alpha_in_direction:ANY` per symbol
- TRADE leg evidence (same engine, deterministic data): verifier 11/11 — 3 orders, slippage 1bp + commission 5bp, SL/TP close, realized −1492.02, equity identity 10000 → 8507.98
- capture: `reports/runs/DEMO-PAPER-01-stdout.log`
