# MTM_EQUITY_VALIDATION — BURN-IN V2

## Seguridad PIT (§11)

- Precios usados: **PIT-snapshot** (mismo snapshot del ciclo que alimenta la
  decisión) — nunca `fetch_price` fresco posterior. Invariante:
  `price_time <= snapshot_time`.
- Falta de precio para una posición ⇒ `MTM_INCOMPLETE` + `missing_prices[]`.
  Nunca se inventa precio.
- Implementado en `harness.py` (`_mtm_snapshot`): extrae precios del snapshot,
  llama `broker.mark_to_market_equity(prices)`, fallback `cash_realized_equity`
  con status explícito si no hay precios.

## Campos por sesión (§10)

`cash_realized_equity`, `realized_pnl`, `unrealized_pnl`, `equity_mtm`,
`gross_exposure`, `open_positions`, `prices_used`, `status`,
`missing_prices[]` — persistidos en cada evento `paper.session` del
`events.jsonl` (arquitectura existente, sin DB nueva).

## Evidencia del run (en curso)

- 1523/1523 sesiones `MTM_OK`, `missing_prices` siempre vacío (BTC/ETH/SOL
  líquidos, snapshots completos).
- Serie: `peak_equity=9999.96`, `max_drawdown_abs=8.16`,
  `max_drawdown_pct=0.082%`, `ending_mtm_equity=9993.69`.
- Reconciliación contable: `equity_mtm ≈ cash+realized + unrealized` verificada
  por ciclo; identidad equity del reconciliador intacta (FATAL si se viola).

## Serie machine-readable (§32)

Integrada en `events.jsonl` (campo `mtm` de cada evento `paper.session`) —
sin infraestructura nueva. `RUN_SUMMARY.json` agrega peak/drawdown desde esa
serie.
