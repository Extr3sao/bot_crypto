# WP-EDGE-08 — gate status

*As of `2026-10-14T20:37:22Z`. `promotion: NONE`, `order_sent: false`.*

| Arm | Track | Registered verdict | Failed | Frozen gate | Power | Cross-section load |
| --- | --- | --- | --- | --- | --- | --- |
| `edge06_trend_fixed` | CURRENT | **NOT_APPLICABLE** | — | REJECT | powered (oos n=144 >= 30) | not read |
| `edge07_active_thrust` | CURRENT | **NOT_APPLICABLE** | — | REJECT | powered (oos n=196 >= 30) | not read |
| `edge08_active_daybreak_1h` | ACTIVE | **REJECT** | P2, P3, P4, P5, P6, R1, R2, F1 | REJECT | powered (oos n=103 >= 30) | read |
| `edge08_active_multiday_range_1h` | ACTIVE | **REJECT** | P2, P3, P4, P5, R1, R2, S1, F1 | REJECT | powered (oos n=128 >= 30) | read |
| `edge08_active_stretch_revert_1h` | ACTIVE | **REJECT_NO_GROSS_EDGE** | C0 | — | — | not read |
| `edge08_quality_breakout_daily` | QUALITY | **REJECT** | P2, P3, P4, P5, P6, R1, R2, S1, F2 | REJECT | powered (oos n=30 >= 30) | read |
| `edge08_quality_pullback_daily` | QUALITY | **REJECT_NO_GROSS_EDGE** | C0 | — | — | not read |
| `edge08_quality_reversion_daily` | QUALITY | **REJECT_NO_GROSS_EDGE** | C0 | — | — | not read |
| `edge_trend_01_4h` | CURRENT | **NOT_APPLICABLE** | — | REJECT | powered (oos n=126 >= 30) | not read |

The frozen admission gate is the yardstick earlier work packages were judged by, reported here with `OOS` := the cross-section's decisive window for comparability. The registered verdict is the one ``PREREGISTRATION.json`` defines, and it is the one that counts.
