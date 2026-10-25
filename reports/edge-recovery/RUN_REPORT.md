# RUN REPORT - WP-EDGE-00 (primer resultado observable)

| | |
|---|---|
| **WP** | WP-EDGE-00 - runtime real, baseline y primer ciclo con decision observable |
| **run_id** | `wp-edge-00-smoke-real` |
| **commit** | `1d2192b0aec8cfe1bf2bfcaa308c4787229b3d22` (HEAD local; `origin/main` = 5e6f963, 259 commits por detras) |
| **branch** | `main` (worktree autoritativo) |
| **mode** | PAPER - sin claves, sin cuenta, sin ordenes reales |
| **entrypoint real** | `scripts/autonomous_paper.py` (datos reales) y `scripts/start_paper_trading.py` (fixture de reachability) |
| **resultado** | **PASS_RUNTIME_OBSERVED** - 6 decisiones, 0 trades, 0 acciones de produccion |
| **FALSE_SUCCESS** | **0** |

## 1. Que se ejecuto y con que datos

**Run real (datos de mercado reales, read-only):**

```text
python scripts/autonomous_paper.py --assets BTC,ETH,SOL --timeframe 5m --provider ccxt \
  --cycles 2 --interval 15 --run-id wp-edge-00-smoke-real \
  --run-root reports/edge-recovery/runs/WP-EDGE-00-smoke-real \
  --state-path <run>/paper_state.json --ledger config/strategy_admission.json \
  --horizon-minutes 5.0 --size-usd 1000.0 --no-shadow
```

- Fuente: **Binance spot publico via ccxt 4.5.63** (`environment = ccxt:binance`), velas 5m **cerradas** (100-120 por simbolo y ciclo).
- Universo: BTC/USDT, ETH/USDT, SOL/USDT. Regimen observado: `LOW_VOLATILITY`.
- Este run es **REAL_MARKET_DATA** (no replay historico, no sintetico). La ventana es de ~20 s (2 ciclos), no un periodo largo.

**Run de control (sintetico, etiquetado):** `scripts/start_paper_trading.py --provider fake --max-cycles 1` con un **ledger fixture controlado** (`CONTROLLED_TEST_FIXTURE`) que admite `ema_crossover@5m`, para probar que el camino de decision del motor de ciclo esta vivo: `contexts_built=3 > 0`, `router_invocations=3 > 0`, `strategy_invocations=3 > 0`. **Ningun numero de este run es evidencia de mercado.**

## 2. Decisiones observadas (run real)

| # | Activo | Modo | Clasificacion | Causa registrada | Riesgo | Orden? |
|---|---|---|---|---|---|---|
| 1 | BTC | NO_TRADE | NO_GROSS_EDGE | gross_edge_not_positive:-4.5600bps | PASS | False |
| 1 | ETH | NO_TRADE | NO_GROSS_EDGE | gross_edge_not_positive:-4.5600bps | PASS | False |
| 1 | SOL | NO_TRADE | CONTEXT_ERROR | context_error:AssetContextError: no bars at or before ts 1791795395133 for SOL | NOT_APPLICABLE | False |
| 2 | BTC | NO_TRADE | NO_GROSS_EDGE | gross_edge_not_positive:-4.5600bps | PASS | False |
| 2 | ETH | NO_TRADE | NO_GROSS_EDGE | gross_edge_not_positive:-4.5600bps | PASS | False |
| 2 | SOL | NO_TRADE | CONTEXT_ERROR | context_error:AssetContextError: no bars at or before ts 1791795415745 for SOL | NOT_APPLICABLE | False |

Totales: **6 decisiones**, **0 TRADE**, **6 NO_TRADE** = {"NO_TRADE_STRATEGIC": 4, "NO_TRADE_DATA": 2}.

- **4 `NO_TRADE_STRATEGIC`**: `ema_crossover@5m` emitio una senal (seleccionada por el router), pero el filtro economico la rechazo: ventaja bruta `-4.56 bps` < coste re-derivado `22.7918 bps` (fees 10+10 bps SRC-01 + spread observado), neto `-27.3518 bps`.
- **2 `NO_TRADE_DATA`**: SOL/USDT fue rechazado por el scanner (`volume_below_threshold`, 24h ~ 4.9 M USDT) y despues el ciclo fallo al construir su contexto (`AssetContextError`). Fail-closed correcto, pero la clasificacion es mejorable (defecto `DEF-WP00-01`).

Integridad: `trace_chain = {"ok": true, "records": 6, "broken_at": null, "detail": "hash chain intact"}`; `replay = {"attempted": 6, "ok": 6, "failed": 0, "statuses": {"PARTIAL": 6}, "failures": [], "market_data_accessed": false}`; `production_actions = 0`.

## 3. Economia del run (sin maquillar)

| Metrica | Valor |
|---|---|
| Ordenes creadas | 0 |
| Trades PAPER | 0 |
| Fees pagados (USDT) | 0.0 |
| Slippage pagado (USDT) | 0.0 |
| PnL realizado (USDT) | 0.0 |
| PnL no realizado (USDT) | 0.0 |
| PnL neto (USDT) | **0.0 - ZERO_BY_NO_TRADE** |
| Saldo inicial / equity final | 10 000.0 / 10 000.0 |
| Drawdown maximo | 0.0 bps |

**Por que 0:** el ledger no admite ninguna estrategia (`NO_GROSS_EDGE=17`, `COST_KILLED=7`, `PAPER_CANDIDATE=0`) y la unica senal viva quedo por debajo del coste. **El 0 no es un beneficio ni una perdida: es la consecuencia aritmetica de no abrir posicion.** Ningun resultado de este WP demuestra ventaja economica alguna.

## 4. Control de camino de decision (anti falso exito)

- `SMOKE_EXIT_ZERO != STRATEGY_PATH_VERIFIED` - invariante cubierta por `tests/unit/cert/test_paper_smoke_decision_path.py` (incluida en las 385 pruebas que pasan).
- El run real **no** pasa por una copia ni por un mock: es el entrypoint del checkout en HEAD.
- El ledger fixture esta etiquetado `CONTROLLED_TEST_FIXTURE` y su unico fin es la reachability.

## 5. Tests ejecutados

```text
python -m pytest tests/unit/autonomous tests/unit/paper tests/unit/cert tests/integration -q
-> 385 passed, 0 failed, 0 skipped (28.59 s)
```

## 6. Errores y limitaciones declaradas

- `ASSET_CONTEXT_SOL`: 2 `context_error` (ver seccion 2) - no silenciado: aparece en `errors[]` del RUN_REPORT del runtime y en esta tabla.
- `provider_verified=false` en el preflight (best-effort de mercados) - `DEF-WP00-03`.
- El replay de traces queda `PARTIAL` porque los outcomes aun no estan resueltos (horizonte 5m, sin posiciones): es honesto, no un fallo.
- Este run cubre **2 ciclos de 5m**, no es una campana ni una validacion estadistica.

## 7. Siguiente paso

WP-EDGE-01 (no ejecutado): registro de fuentes + features causales. Sin cambios de estrategia en este WP.
