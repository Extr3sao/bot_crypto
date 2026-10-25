# EXECUTION_COST_MODEL_V4 — coste por activo medido (research-only)

> Máquina: `docs/EXECUTION_COST_MODEL_V4.json`. Código:
> `src/trading_bot/research/microstructure/cost_model_v4.py` (compone
> `cost_model_v3.py`, no lo duplica). Aritmética de fee/slippage/impact/funding
> **sin cambios** respecto a V3.

Fase: MICROSTRUCTURE-EDGE & FORWARD-DATA V1. Fecha: 2026-09-28.

## 1. Qué cambia respecto a V3

| dimensión | V3 | V4 |
| --- | --- | --- |
| spread | constante majors plana **1.0 bps** (ESTIMATED) | **medido por activo** (OBSERVED) desde captura forward propia |
| volatilidad | factor 1.0 (ASSUMED) | **medida por activo** sobre klines reales de 5m (OBSERVED) |
| granularidad | escenario | escenario **x activo** |
| maker | fila teórica | fila teórica + `maker_status = EXECUTION_DEPENDENT` |

## 2. Entradas medidas (reales, read-only)

| activo | spread medio observado | n | p50 | p95 | vol 5m realizada |
| --- | --- | --- | --- | --- | --- |
| BTCUSDT | **0.0012 bps** | 37 | 0.0012 | 0.0012 | 12.69 bps |
| ETHUSDT | **0.0375 bps** | 37 | 0.0375 | 0.0375 | 16.71 bps |
| SOLUSDT | **0.8422 bps** | 37 | 0.8422 | 0.8422 | 18.88 bps |

* Fuente del spread: `reports/microstructure-v2/forward/forward_1790595680.jsonl`
  (captura propia, `bookTicker` rest read-only; 111 registros, 37 por símbolo).
* Fuente de la volatilidad: `reports/microstructure-v1/data/KLINES_<SYM>_5m.json`
  (59,905 barras reales, 2026-03-01..2026-09-25).
* El recuento de observaciones y la ruta de origen viajan **dentro** de la
  entrada del modelo: un spread sin observaciones no se modela como cero
  (`AssetMarketInput` lanza excepción).

## 3. Resultado: coste round-trip por activo

Intención de referencia: `size = 1,000 USD`, `liquidity_regime = normal`,
entrada y salida `market`, escenario `BINANCE_SPOT_STANDARD_TAKER` (venue real
del runtime, VIP0), horizonte 25 min.

| activo | fee | spread | slippage+impact | funding | **RT total** | break-even | requerido 1.5x |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BTC | 20.0 | 0.0012 | 3.4988 | 0.0 | **23.500** | 23.500 | **35.250** |
| ETH | 20.0 | 0.0375 | 3.7233 | 0.0 | **23.761** | 23.761 | **35.641** |
| SOL | 20.0 | 0.8422 | 3.8445 | 0.0 | **24.687** | 24.687 | **37.030** |

Stress (sobre el coste medido): `1.25x / 1.5x / 2.0x` por activo en el JSON.
Variante con el spread **p95**: idéntica hasta el 4º decimal — a 1,000 USD el
spread no mueve la barrera.

## 4. La conclusión económica de V4

```text
fee (20.0 bps de 23.5)  = 85.1% de la barrera
slippage+impact (3.5)   = 14.9%
spread (0.001..0.84)    = 0.0..3.6%
```

La barrera **no** es un problema de spread ni de elección de activo: es la
tarifa taker VIP0 al 100% del notional. La dimensión "activo" vale **1.19 bps**
de diferencia entre BTC y SOL, mientras que el edge bruto más alto medido en la
fase es de **+6.43 bps**: la diferencia entre "casi" y "no" es de un orden de
magnitud, no de un 5%.

`REQUIRED_GROSS_EDGE_BPS` = 35.25 / 35.64 / 37.03 frente a un máximo medido de
+6.43 bps ⇒ **deficit mínimo de 28.8 bps**.

## 5. Gate maker (§14-15)

```text
MAKER EDGE GATE = FAIL
maker_fee_bps = 10.0 == taker_fee_bps = 10.0 (VIP0, Binance Spot)
fill_evidence_available = false
```

A VIP0 la orden pasiva **no reduce la tarifa**, y en esta fase no existe ningún
`FillEvidence` (probabilidad de fill, tiempo a fill, fills parciales, selección
adversa). Por tanto la fila maker se publica marcada
`EXECUTION_DEPENDENT` y **nunca** se usa para admission. Una hipótesis que sólo
sea viable en maker queda clasificada como dependiente de ejecución hasta que
exista evidencia de fill.

## 6. Qué NO afirma este modelo

* No afirma que el spread sea estable fuera de la ventana capturada (100 s).
* No modela impacto de mercado real para tamaños mayores: extrapola V3.
* No afirma que otro venue/producto no pueda ser viable; sólo caracteriza el
  venue que el runtime usa hoy.
* No convierte la tarifa en coste cero por descuentos no confirmados
  (`discount_applicability` sigue siendo `POSSIBLE`/`NOT_APPLICABLE`).
