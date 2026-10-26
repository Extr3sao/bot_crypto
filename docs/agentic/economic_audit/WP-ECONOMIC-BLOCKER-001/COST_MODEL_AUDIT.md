# COST_MODEL_AUDIT — WP-ECONOMIC-BLOCKER-001

> **Pregunta**: ¿cuánto cuesta realmente cada operación, y de qué está hecho ese coste?
>
> **Respuesta corta**: **20 de los ~22,8 bps son comisiones del venue, KNOWN**. El
> resto (slippage, impacto, spread) es ESTIMATED/OBSERVED y suma 2,8 bps. Como
> el máximo bruto medido de cualquier estrategia es 8,91 bps, **el veredicto no
> depende de ninguna estimación**: aunque slippage e impacto fuesen cero, seguiría
> siendo negativo (−11,09 bps).

Datos: [`COST_MODEL_AUDIT.json`](COST_MODEL_AUDIT.json) y los bloques de coste
extraídos a [`COST_OBSERVED.json`](COST_OBSERVED.json), generados por
[`scripts/wp_eco001_cost_audit.py`](../../../../scripts/wp_eco001_cost_audit.py).

---

## 1. Qué calcula el motor

`trading_bot.autonomous.costs.CostEngine` evalúa `COST_MODEL_V3` en cada ciclo
para el escenario de admisión `BINANCE_SPOT_STANDARD_TAKER` (spot Binance, VIP0,
pago en quote asset). Términos aditivos, en bps de notional, ida y vuelta:

| componente | valor @ 1 000 USD | clase | fuente | ¿cómo se conoce? |
| --- | ---: | --- | --- | --- |
| `exchange_fee_entry` | 10,000 | KNOWN | `SRC-01` | tarifa publicada del venue, nivel VIP0 |
| `exchange_fee_exit` | 10,000 | KNOWN | `SRC-01` | ídem |
| `spread` | 0,0012 | OBSERVED | `SRC-07` | `spread_bps` del snapshot de mercado de ese ciclo |
| `slippage` | 2,632 | ESTIMATED | `MODEL-V3` | 1,0 bps base × liquidez 1,0 × tamaño 1,316 × volatilidad 1,000 |
| `market_impact` | 0,158 | ESTIMATED | `MODEL-V3` | desplazamiento por tamaño sobre el slippage base |
| `funding_carry` | 0 | KNOWN | — | spot: no hay funding |
| **total** | **22,7918** | | | **87,75 % KNOWN** |

Sin cargo en esta ruta: `adverse_selection`, `missed_fill_penalty` y
`fill_probability_inflation` — son términos **solo de maker**. Detalle relevante:
en este nivel `maker_fee_bps == taker_fee_bps == 10,0`, así que **ejecutar pasivo
no ahorra ni un bp**; `EXECUTION_COST_MODEL_V4` ya registró `maker_gate: FAIL` por
esa misma razón y por falta de evidencia de fills.

## 2. Recomputación de lo que el runtime registró

Se extrajeron los **24 bloques `CostBreakdown`** que emitieron los tres runs PAPER
de `WP-PAPER-REAL-DATA-001`, con el SHA-256 de cada `traces.jsonl`, y se
reintrodujeron en `CostEngine.evaluate` con su mismo tamaño, spread y horizonte:

| run | bloques | activo | spread (bps) | registrado | recomputado | Δ |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| `run-a-1h` | 9 | BTC / ETH / SOL | 0,001252 / 0,043307 / 0,998752 | 22,7918 / 22,8339 / 23,7893 | idéntico | ≤ 5,0e-09 |
| `run-b-5m` | 9 | BTC / ETH / SOL | 0,001253 / 0,043320 / 0,998851 | 22,7918 / 22,8339 / 23,7894 | idéntico | ≤ 5,0e-09 |
| `run-c-controlled-exec` | 6 | BTC / ETH / SOL | 0,001247 / 0,043168 / 0,995272 | 22,7918 / 22,8337 / 23,7858 | idéntico | ≤ 5,0e-09 |

**Los 24 de 24 coinciden**, con delta máximo absoluto de `5,04e-09` bps (ruido de
coma flotante). El rango "22,8–23,8 bps" que se citaba en entregas anteriores no
era una incertidumbre: era **la diferencia entre activos**, con SOL pagando ~1 bp
de spread y BTC ~0,001 bps. La descomposición del coste queda confirmada, no
supuesta.

Verificación adicional del modelo publicado: las tres cifras de
`docs/EXECUTION_COST_MODEL_V4.json` (BTC 23,500 / ETH 23,7608 / SOL 24,6867 bps
a 75 min) se re-derivan desde sus propios inputs medidos vía `asset_cost_v4` y
coinciden.

## 3. Sensibilidad: qué mueve el coste y qué no

Round-trip con spread por defecto (1,0 bps), tamaño y horizonte:

| tamaño USD | 5 min | 15 min | 60 min | 240 min |
| ---: | ---: | ---: | ---: | ---: |
| 250 | 23,395 | 23,395 | 23,395 | 23,395 |
| 1 000 | 23,791 | 23,791 | 23,791 | 23,791 |
| 5 000 | 24,768 | 24,768 | 24,768 | 24,768 |
| 25 000 | 26,953 | 26,953 | 26,953 | 26,953 |

Dos lecturas, ambas incómodas:

1. **El horizonte no cambia el coste** (spot, sin funding). Por tanto alargar la
   duración de la operación **no amortiza** la comisión: para bajar el coste por
   operación habría que reducir el número de operaciones, no su duración. En los
   datos medidos la ventaja bruta tampoco crece con el horizonte (§ admisión).
2. **El tamaño apenas mueve el coste**: de 250 a 25 000 USD pasa de 23,4 a 27,0
   bps. La comisión fija domina la estructura; el tamaño es un factor menor.

Además, el runtime evaluó con `volatility_bps = 0` (factor de volatilidad 1,000),
así que el slippage estimado es **optimista** en cualquier régimen volátil: el
coste real es ≥ 22,79, nunca menor. Eso refuerza el veredicto en lugar de ponerlo
en duda.

## 4. La barrera, en una línea

| magnitud | bps |
| --- | ---: |
| mejor ventaja bruta medida (cualquier estrategia, cualquier timeframe) | +8,91 |
| coste round-trip con el spread más estrecho (BTC) | 22,79 |
| coste round-trip con el spread más ancho (SOL) | 23,79 |
| **neto de la mejor estrategia (BTC)** | **−13,88** |
| **neto si se ignoran slippage e impacto (solo comisiones)** | **−11,09** |
| umbral de investigación usado en la admisión | 12,00 |
| brecha entre el umbral de investigación y el coste real | **+10,79** |

El umbral con el que se calcularon los checks de admisión (12 bps) está
**10,79 bps por debajo** del coste que el runtime aplica de verdad. Es decir: la
puerta de admisión se diseñó con un coste que el propio motor considera
insuficiente. Ninguna estrategia podía pasar "por economía" y ninguna lo hizo
tampoco por bruto.

## 5. Qué podría cambiar el veredicto (y qué no)

- **No**: re-estimar slippage/impacto. Son 2,79 bps de 22,79; llevarlos a cero no
  cambia el signo.
- **No**: cambiar el tamaño. Mueve el coste ~±4 bps en un rango de 100×.
- **No**: alargar el horizonte. No mueve el coste y el bruto no crece con él.
- **Sí, en teoría**: bajar el nivel de comisión del venue. Es un hecho de cuenta
  (VIP/volumen), no una decisión de modelado, y este WP no lo toca ni lo asume:
  no hay evidencia en el repo de que se cumplan los requisitos de volumen para un
  nivel superior. Cualquier cambio de ese tipo debería entrar como WP propio, con
  evidencia del tier real y sin tocar reglas de admisión a la vez.
- **Sí, en teoría**: una estrategia con bruto > 22,79 bps por operación y muestra
  publicada. Hoy no existe en el ledger.

## 6. Límites de este audit

- El coste es una **instantánea** (3 runs, 24 bloques, 3 activos), no una
  distribución por régimen. Declarado, no extrapolado.
- El spread es observado **en el snapshot del ciclo**, no ejecutado: no hay
  evidencia de fill real (el propio `maker_gate` de V4 lo dice).
- `funding_carry = 0` es correcto en spot y **no** se extiende a futuros.
- La volatilidad entró como 0 en el runtime; el modelo no se corrige aquí (eso
  cambiaría el comportamiento en producción), solo se documenta la dirección del
  sesgo.

## 7. Reproducir

```bash
uv run python scripts/wp_eco001_cost_audit.py     # recomputa los 24 bloques y el V4
uv run python scripts/wp_eco001_economics.py      # gross vs cost por estrategia
uv run python scripts/wp_eco001_verify.py         # verificación independiente
```
