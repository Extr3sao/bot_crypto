# Decision funnel report V2

The immutable V1 trace schema can represent every required decision stage, but it has not been wired into the active runtime. Therefore historic per-proposal traces reconstructed from aggregate telemetry are **0**; no missing event is inferred as a zero count. The prior R2 ledger remains the authority for 90 proposals, 6 `UNRESOLVED_CONFLICT` rejections and 11 `MAX_POSITIONS` risk rejections.

Economic transitions and terminal dispositions are `UNKNOWN` until native traces and separately sourced outcomes are collected.
