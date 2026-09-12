# Shadow Maturity Authority V2 — 48h Horizon (Corrected)

Corrects the V2 resolution's zero-horizon error.

| Capture | decision_time | maturity (48h) | old claimed |
|---|---|---|---|
| shadow:8c69b5c0 | 2026-09-09T21:15+00 | 2026-09-11T21:15+00 | 2026-09-09T21:15Z (0h) |
| shadow:82923f11 | 2026-09-09T21:15+00 | 2026-09-11T21:15+00 | 2026-09-09T21:15Z |
| shadow:a3a2a742 | 2026-09-10T05:00+00 | 2026-09-12T05:00+00 | 2026-09-10T05:00Z |
| shadow:ca69ab8a | 2026-09-10T05:00+00 | 2026-09-12T05:00+00 | 2026-09-10T05:00Z |
| shadow:75604a8b | 2026-09-10T05:05+00 | 2026-09-12T05:05+00 | 2026-09-10T05:05Z |
| shadow:f7acfb38 | 2026-09-10T05:05+00 | 2026-09-12T05:05+00 | 2026-09-10T05:05Z |
| shadow:f3b4035d | 2026-09-10T06:55+00 | 2026-09-12T06:55+00 | 2026-09-10T06:55Z |
| shadow:b171e069 | 2026-09-10T06:55+00 | 2026-09-12T06:55+00 | 2026-09-10T06:55Z |
| shadow:d6dbf740 | 2026-09-10T08:15+00 | 2026-09-12T08:15+00 | 2026-09-10T08:15Z |
| shadow:08f652ea | 2026-09-10T08:15+00 | 2026-09-12T08:15+00 | 2026-09-10T08:15Z |
| shadow:65a9243e | 2026-09-10T11:25+00 | 2026-09-12T11:25+00 | 2026-09-10T11:25Z |

Correct horizon: `2026-09-11T21:15+00 .. 2026-09-12T11:25+00`.

Policy: resolve only when `maturity_time <= current UTC` (true for all 11 only after `2026-09-12T11:25Z`); `SHADOW_RESOLUTION_LEDGER_V2` must reference `supersedes_invalid_resolution_id` and derive PIT first-touch with maturity cap; even 11/11 profitable remains `INSUFFICIENT_SAMPLE`.
