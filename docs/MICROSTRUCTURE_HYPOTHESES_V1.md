# MICROSTRUCTURE_HYPOTHESES_V1 — pre-registro (§21-31, §52)

> **Estado: PRE-REGISTRADO.** Este documento se escribe ANTES de ejecutar
> cualquier experimento de la fase EXECUTION-COST & MICROSTRUCTURE-EDGE-V1.
> Los umbrales, horizontes y reglas de señal quedan fijados aquí. Ningún
> valor se ajusta después de ver resultados. Si un resultado es negativo, no
> se re-optimiza la regla.

## 0. Venue y producto bajo investigación

| item | valor | evidencia |
| --- | --- | --- |
| venue | Binance | `config/realdata/exchange.yaml` `id: binance` |
| producto | Spot | `account_type: spot`, `default_type: spot` |
| sandbox | true (testnet, read-only en runtime) | `exchange.sandbox: true` |
| símbolos target | BTC/USDT, ETH/USDT, SOL/USDT | `config/realdata/assets.yaml` enabled |
| order types | market/limit, `post_only_default: true` | `exchange.yaml` |
| derivados | EXCLUIDOS del runtime | `excluded_markets: [Derivatives, Options]` |

La investigación de microstructure **puede** usar datos públicos de USD-M
perp (funding, premium, OI) como *información*, pero **no** cambia el venue de
ejecución del runtime. Cualquier edge derivado de derivados queda
`DERIVATIVES_RESEARCH_JUSTIFIED` o `DERIVATIVES_NO_EVIDENCE`, nunca ejecutado.

## 1. Coste de admission (pre-registrado)

Coste round-trip de referencia para admission = **REALISTIC_RETAIL** (taker
VIP0, sin descuentos asumidos): **23.5 bps**. Stress: **1.5X = 35.25 bps**,
**2X = 47.0 bps**. `ZERO_COST` es solo diagnóstico y **nunca** admission.

`REQUIRED_EDGE_BPS = 23.5 * 1.5 = 35.25 bps` de edge bruto por trade para que
una candidata quede con margen material sobre el coste (§42).

## 2. Horizontes (label) (§30-31)

Para barras de 5m: `1, 5, 15, 30, 60` barras = 5m, 25m, 75m, 2.5h, 5h.

Cada hipótesis tiene un **horizonte primario pre-registrado** (el que decide).
Los demás se reportan solo como contexto y NO se usan para promocionar.

## 3. Splits temporales (§38)

| split | ventanas | rango |
| --- | --- | --- |
| DEV | W1-W4 | 2026-03-01 .. 2026-06-30 |
| VAL | W5-W6 | 2026-07-01 .. 2026-08-31 |
| OOS | W7 | 2026-09-01 .. 2026-09-24 |

No random split. El OOS nunca se mira para elegir reglas.

## 4. Filtros secuenciales obligatorios (§32-36, §53)

```
Filter 0  INFO CONTENT  — ¿la feature tiene relación estable con forward returns?
Filter 1  GROSS EDGE    — ¿expectancy bruta > 0? (si no -> REJECT)
Filter 2  COST SURVIVAL — ¿edge bruto - COST_MODEL_V2 > 0 con margen?
Filter 3  SPLITS        — DEV > 0, VAL > 0, OOS > 0
Filter 4  COST STRESS   — sobrevive 1.5X y 2X?
Filter 5  ADMISSION     — criterios §41
```

Early stop: si Filter 1 falla en DEV, la línea se detiene y se clasifica
`NO_GROSS_EDGE`. No se gasta computación en OOS de una idea inviable.

## 5. Reglas de señal pre-registradas

Todas son reglas simples de umbral, sin optimización de parámetros. Las
direcciones y umbrales se fijan aquí.

### M-01 — ORDER FLOW IMBALANCE (`S-01`)
- Feature: `flow_imbalance_z` (z-score rolling-20 de
  `flow_imbalance = (taker_buy - taker_sell) / volume`).
- Regla: `z > +2.0` -> long; `z < -2.0` -> short; `|z| <= 2` -> flat.
- Horizonte primario: **5 barras (25 min)**.
- Dirección: **no asumida** — se determina por el signo empírico en DEV y se
  aplica igual en VAL/OOS (si DEV dice reversión, se testa reversión en todo).

### M-02 — ORDER BOOK IMBALANCE (`S-02`)
- Requiere histórico de libro. **No existe** (bookTicker/depth son LIVE_ONLY,
  ver `MARKET_MICROSTRUCTURE_DATA_AUDIT.md`).
- Estado pre-registrado: `LIVE_ONLY` -> no testeable históricamente;
  planificado como `MICROSTRUCTURE-FORWARD-DATA-V1` (colector read-only).
- **No se fabrica un libro desde OHLCV (§16).**

### M-03 — FLOW + BREAKOUT (`S-03`)
- Regla: `ret_mom_bps > 0` (precio sube en 12 barras) **y** `flow_imbalance_z > +1`
  -> long; simétrico (ret < 0 y z < -1) -> short; si no, flat.
- Horizonte primario: **5 barras**.
- Objetivo: filtrar falsos breakouts con confirmación de flujo agresor.

### M-04 — FUNDING EXTREMES (`S-04`)
- Feature: `funding_z` (z-score rolling-21 sobre funding realizado 8h).
- Regla contraria pre-registrada: `funding_z > +2` -> short; `< -2` -> long.
- Horizonte primario: **30 barras (2.5h)**.

### M-05 — PREMIUM / BASIS (`S-05`)
- Feature: `premium_z` (z-score rolling-21 del premium index 5m,
  `(mark-index)/index`).
- Regla contraria pre-registrada: `premium_z > +2` -> short; `< -2` -> long.
- Horizonte primario: **15 barras (75 min)**.
- Basis: derivable del premium index; el endpoint `basis` retiene ~30d y su
  paginación es inestable -> `LIMITED_HISTORY`.

### M-06 — OPEN INTEREST + PRICE (`S-06`)
- Combinaciones: `ret_mom_bps` signo x `oi_change_z` signo (4 celdas).
- Dirección **no asumida**: se determina por celda en DEV; se testa cada celda
  por separado.
- Horizonte primario: **15 barras**.
- **Limitación pre-registrada**: OI histórico = solo ~30d (late-Aug .. Sep).
  Cae casi todo en OOS; DEV/VAL no tienen OI -> la hipótesis no puede pasar
  Filter 3 y queda `LIMITED_HISTORY` / forward-required.

### M-07 — FUNDING + OI + PRICE (`S-07`)
- Regla: `funding_z` extremo **y** `oi_change_z` mismo signo **y** `ret_mom_bps`
  mismo signo -> dirección contraria al crowding.
- Horizonte primario: **30 barras**.
- Debe superar a M-04 y M-06 por separado para justificar complejidad (§28).
- Limitación OI idéntica a M-06.

### M-08 — BTC LEAD/LAG (`S-08`)
- Regla: signo del retorno de BTC en la barra previa (`ret_1_btc`) -> posición
  en ETH y SOL en la barra siguiente; hold 1 bar.
- Horizonte primario: **1 barra**.
- PIT estricto: usa `available_at(bar t-1) <= open(t)` — sin leakage.

## 6. Criterios de admission (§41)

Una candidata puede ser `PAPER_CANDIDATE` solo si, con `REALISTIC_RETAIL`:
1. edge bruto medio > 0 y net > 0 con margen (net > 0.25 * coste).
2. n total >= 100 y n OOS >= 30.
3. PF_OOS > 1.0.
4. DEV > 0, VAL > 0, OOS > 0 (temporal stability).
5. sin NEGATIVE_ROBUST.
6. punto de integridad PIT sin violaciones.
7. coste entendido: sobrevive 1.5X con margen.

Estados: `NO_INFORMATION`, `NO_GROSS_EDGE`, `COST_KILLED`, `OOS_FAILED`,
`REGIME_FRAGILE`, `EXECUTION_MODEL_REQUIRED`, `RESEARCH_REQUIRED`,
`PAPER_CANDIDATE` (§54).

## 7. Qué NO se hará

- No más variantes de indicadores OHLCV.
- No grids de parámetros.
- No fabricar libro histórico desde OHLCV.
- No asumir maker fee 0, rebates, fills garantizados.
- No relajar estos criterios tras ver resultados.
- No tocar el core runtime (§50).

## 8. Errata / extensiones
Se añadirán aquí solo correcciones de **metodología** (nunca de umbrales tras
resultados), con fecha.
