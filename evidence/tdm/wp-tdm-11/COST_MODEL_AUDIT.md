# WP-TDM-11 — COST MODEL AUDIT (revisado)

**Fuente de verdad:** `src/trading_bot/research/microstructure/cost_model_v3.py` en `e67194e7`, ejecutado.
**Evidencia:** `g0.json → costs`, `verification.json → V8`, `retro.json → primary.cost_sensitivity`.
**Revisión 2:** corrige el hallazgo H-01 de la revisión 1, que era erróneo. Ver §3.

---

## 1. Qué se ejecutó

`default_model()` → `BINANCE_SPOT_STANDARD_TAKER`, `size_usd=1000`, `horizon_minutes=30`,
`liquidity_regime="normal"`, `volatility_bps=0`, `spread_bps=None`, `market`/`market`.

| Componente | bps | Clase |
| --- | --- | --- |
| `exchange_fee_entry` | 10,0000 | KNOWN |
| `exchange_fee_exit` | 10,0000 | KNOWN |
| `spread` (½ spread × 2 patas taker) | 1,0000 | **ESTIMATED** |
| `slippage` (1,0 × liq × size 1,3162 × vol 1,0 × 2) | 2,6325 | ESTIMATED |
| `market_impact` (0,25 × (size−1) × 2) | 0,1581 | ESTIMATED |
| **Total round-trip** | **23,7906** | ESTIMATED |

Δ frente al `23,79` publicado: **+0,0006 bps**. Clase global `ESTIMATED` porque ningún componente es
OBSERVED (el spread es el valor por defecto de la spec, no una medición de libro).

`size_f = 1 + √(1000 / 10 000) = 1,3162`; a 1 000 USD el impacto aporta 0,66 % del total.

## 2. Los 10 escenarios del modelo

| Escenario | Producto | Round-trip | Clase |
| --- | --- | --- | --- |
| `BINANCE_USDM_PERP_MAKER` (p=0,5) | USDⓈ-M Perp | **9,2500** | ASSUMED |
| `BINANCE_USDM_PERP_TAKER` | USDⓈ-M Perp | 13,7906 | ESTIMATED |
| `MEXC_SPOT_TAKER` | Spot | 17,7906 | ESTIMATED |
| `BINANCE_SPOT_BNB_TAKER` | Spot | 18,7906 | ESTIMATED |
| `BINANCE_SPOT_STANDARD_TAKER` (**primario**) | Spot | **23,7906** | ESTIMATED |
| `BYBIT_SPOT_TAKER` | Spot | 23,7906 | ESTIMATED |
| `OKX_SPOT_TAKER` | Spot | 23,7906 | ESTIMATED |
| `BINANCE_SPOT_BNB_MAKER` (p=0,5) | Spot | 31,2500 | ASSUMED |
| `BINANCE_SPOT_STANDARD_MAKER` (p=0,5) | Spot | 41,2500 | ASSUMED |
| `KRAKENPRO_SPOT_TAKER` | Spot | 83,7906 | ESTIMATED |

Maker spot = 20 (fee inflada) + 1,0 (adverse selection) + 0,25 (missed fill) + 20 (1/p−1) = **41,25**.
Maker perp = 4,0 (fee 2 bps ×2) + 1,0 + 0,25 + 4,0 (1/p−1 sobre 4 bps) = **9,25**.

## 3. H-01 — **retractado**: el 9,25 sí está modelado

La revisión 1 de este documento afirmó que "el 9,25 bps no existe en el código". **Es falso.** Es
`BINANCE_USDM_PERP_MAKER`, se reproduce exactamente (9,2500) y TDM-10 lo citó bien.

**Causa del error:** la tabla de escenarios se imprimió por consola y un `UnicodeEncodeError` (el tier
contiene `Ⓢ`, U+24C8) truncó la salida tras cuatro filas; leí la cola truncada como si fuera la lista
completa. La comprobación `V8` del verificador lo detectó al comparar el total recalculado contra todos los
escenarios. Registrado en `RUN_REPORT.json → errors E4`; los documentos afectados quedan corregidos y la
conclusión económica no cambia (§5).

Lección de método: **no leer una tabla de la consola sin comprobar que el proceso terminó con éxito.**

## 4. H-02 — el coste del lado corto no está verificado

| Hecho | Consecuencia |
| --- | --- |
| El escenario primario es **Spot** | un Spot no admite posición corta: la regla no es ejecutable ahí |
| Existe `BINANCE_USDM_PERP_*` | un corto **sí** es representable en perp |
| `funding_carry` solo se emite si `funding_rate_bps_per_interval > 0`; el default es 0 | un hold de 30 min que cruce un pago de funding **no lo paga** |
| `funding_source_id = SRC-05` existe en la spec perp | el dato está previsto pero no se usa por defecto |
| Maker perp asume **p = 0,5** de fill | el 9,25 incluye esa apuesta, no una medición |

Estado: `COST_UNVERIFIED_FOR_SHORT`. El coste de una regla corta está **subestimado** en todos los
escenarios disponibles; ninguno incorpora borrow ni funding realizado.

## 5. Por qué el coste no decide este veredicto

`net = gross − cost`, con `cost ≥ 0`. Ventana retrospectiva (n = 115):

| Coste aplicado | Media neta | IC95 (bootstrap de bloques) |
| --- | --- | --- |
| 0,00 bps (lema, sin coste) | −12,58 | [−24,27, **−0,39**] |
| **9,25 (perp maker)** | **−21,83** | [−33,52, −9,64] |
| 13,79 (perp taker) | −26,37 | [−38,06, −14,18] |
| 18,79 (BNB taker) | −31,37 | [−43,06, −19,18] |
| **23,79 (primario)** | **−36,37** | [−48,06, −24,18] |
| 41,25 (spot maker p=0,5) | −53,83 | [−65,52, −41,64] |

Con coste **cero** la cota superior del edge bruto ya es −0,39 (bootstrap) / −2,25 (analítica). Ningún
borrow, funding o fee no contabilizado puede convertir un edge bruto negativo en neto positivo: solo puede
empeorarlo. El defecto H-02 queda **declarado y no decisivo** para este veredicto; sí sería decisivo para
cualquier hipótesis con edge bruto positivo, que no es el caso.

## 6. Anti-doble-conteo

| Comprobación | Resultado |
| --- | --- |
| Suma de componentes = total | **sí** (V8, 1e-9) |
| Spread solo sobre patas taker (`0,5 × taker_legs`) | sí — 1,0 bps con 2 patas |
| Fee una vez por pata | sí — 10 + 10 |
| `funding_carry` con tasa 0 | no se emite (correcto: evita un cargo ficticio) |
| Coste restado una sola vez por operación | sí (V5/V6, control C-07) |
| Tabla de sensibilidad | resta el coste al **mismo** IC bruto; nunca al neto |

## 7. Riesgo residual

1. **Spread ESTIMADO a 1 bp**: no hay libro en los datasets; es el componente más volátil y es una constante.
2. **Slippage constante por pata**, sin impacto temporal ni colas.
3. **Maker con p = 0,5 fijo**, sin modelo de cola.
4. **Funding perp no cobrado** (H-02).
5. Sin coste de oportunidad de capital, sin conversión USDT, sin borrow spot.

Los cinco empujan el coste hacia arriba: ninguno rescata el signo.

## 8. Veredicto del audit

`COST_MODEL_REPRODUCED`: 23,7906 (spot taker), 41,25 (spot maker) y **9,25 (perp maker)** salen del código
con Δ ≤ 0,001 bps.
`COST_UNVERIFIED_FOR_SHORT`: funding no cobrado y fill pasivo asumido.
El veredicto económico de `TDM11-H1` **no depende** de ninguna de las dos cosas.
