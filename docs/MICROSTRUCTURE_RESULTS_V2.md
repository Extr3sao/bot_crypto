# MICROSTRUCTURE_RESULTS_V2 — resultados de las hipótesis nuevas

> Máquina: `docs/MICROSTRUCTURE_RESULTS_V2.json`. Registro:
> `docs/MICROSTRUCTURE_EXPERIMENT_REGISTRY_V2.json`. Pre-registro:
> `docs/MICROSTRUCTURE_HYPOTHESES_V2.md`. Driver:
> `scripts/microstructure_edge_v2.py`.

Fecha: 2026-09-28. Coste: `EXECUTION_COST_MODEL_V4`. **No** se re-ejecutó
ninguna hipótesis de V1: su evidencia sigue en
`docs/MICROSTRUCTURE_RESULTS_V1.json`.

## 1. Dataset (real, read-only)

| item | valor |
| --- | --- |
| ticks | `data.binance.vision` spot daily aggTrades (SRC-04) |
| muestra | 42 ficheros = 14 días (12 y 24 de cada mes, 2026-03..09) |
| panel | **4,032 slices** con reloj común BTC/ETH/SOL |
| huecos del panel | **0** (`max_gap_ms = 300,000` = exactamente una barra de 5m) |
| duplicados / desorden | 0 / 0 |
| barras por día | 288 (= día completo) |

### Verificación externa de la agregación

El volumen agregado por barra se contrastó contra el volumen real de
`KLINES_<SYM>_5m.json` en los mismos buckets:

| símbolo | barras comparadas | ratio medio | ratio mín | ratio máx |
| --- | --- | --- | --- | --- |
| BTCUSDT | 288 | **1.0** | 1.0 | 1.0 |
| ETHUSDT | 288 | **1.0** | 1.0 | 1.0 |
| SOLUSDT | 288 | **1.0** | 1.0 | 1.0 |

Coincidencia exacta: la agregación minuto→5m no pierde ni inventa volumen.

## 2. Resultados por hipótesis (horizonte primario)

| candidata | h | n | gross DEV | net DEV | coste | IC DEV | clasificación |
| --- | :-: | :-: | ---: | ---: | ---: | ---: | --- |
| M-02-BTC | 5 | 137 | +1.399 | −22.101 | 23.500 | +0.048 | **COST_KILLED** |
| M-02-ETH | 5 | 168 | **+6.427** | −17.334 | 23.761 | −0.014 | **COST_KILLED** |
| M-02-SOL | 5 | 131 | +5.119 | −19.568 | 24.687 | −0.113 | **COST_KILLED** |
| M-07-BTC | 15 | 0 | — | — | 23.500 | — | **LIMITED_HISTORY** |
| M-07-ETH | 15 | 0 | — | — | 23.761 | — | **LIMITED_HISTORY** |
| M-07-SOL | 15 | 0 | — | — | 24.687 | — | **LIMITED_HISTORY** |
| M-09-BTC→ETH | 5 | 3,948 | +0.606 | −23.155 | 23.761 | +0.027 | **COST_KILLED** |
| M-09-BTC→SOL | 5 | 3,948 | +0.518 | −24.169 | 24.687 | +0.025 | **COST_KILLED** |
| M-10-BTC | 5 | 3,962 | +0.008 | −23.492 | 23.500 | +0.010 | **COST_KILLED** |
| M-10-ETH | 5 | 3,962 | +0.283 | −23.478 | 23.761 | −0.028 | **COST_KILLED** |
| M-10-SOL | 5 | 3,962 | +0.083 | −24.604 | 24.687 | −0.004 | **NO_INFORMATION** |
| M-10-PANEL-DISPERSION | 5 | 3,962 | +0.406 | −23.577 | 23.761* | −0.003 | **NO_INFORMATION** |

\* coste = media de los tres costes por activo (pre-registrado).

```text
COST_KILLED 7 | LIMITED_HISTORY 3 | NO_INFORMATION 2
PAPER_CANDIDATES = 0
```

## 3. El resultado más informativo: M-02 (flow impulse)

M-02 es lo único que produce gross positivo de tamaño apreciable, y es
justamente donde la estabilidad falla:

| candidata | gross DEV | gross VAL | gross OOS | signos DEV/VAL/OOS | días positivos | días totales |
| --- | ---: | ---: | ---: | --- | ---: | ---: |
| M-02-BTC | +1.399 | −2.663 | +6.542 | + − + (**flip**) | 8 | 14 |
| M-02-ETH | +6.427 | −7.294 | +2.299 | + − + (**flip**) | 9 | 14 |
| M-02-SOL | +5.119 | +7.293 | +16.406 | + + + | **6** | 14 |

M-02-SOL es la única candidata con gross positivo en los tres splits... y aun
así **6/14 días positivos**, con el resultado dominado por dos días
(`2026-03-12` +49.6 bps y `2026-07-12` +48.1 bps). Su IC DEV (−0.113) es el
mayor medido en toda la fase, y no basta: el gross medio sigue estando 3.7x por
debajo del coste y no pasa un control de estabilidad a nivel de día.

Lectura honesta: `OBSERVED` + `INSUFFICIENT_SAMPLE`. No es un edge, y **no** se
declara como tal. La cifra que manda es el déficit: el mejor gross medido
(+6.43 bps) frente al coste mínimo (23.50 bps).

## 4. M-07 (OI x precio): medido, pero no testeable según lo pre-registrado

El open interest sólo existe para los días OOS (DEV y VAL quedan a `null`), así
que **ningún cuadrante puede elegirse en DEV** y la regla no se evalúa:

Distribución del retorno a 15 barras (75 min), 100% OOS:

| estado | BTC n / media | ETH n / media | SOL n / media |
| --- | --- | --- | --- |
| PRICE_UP_OI_UP | 130 / +0.39 | 126 / −1.24 | 154 / **+5.34** |
| PRICE_UP_OI_DOWN | 140 / −4.27 | 133 / +2.11 | 115 / +0.01 |
| PRICE_DOWN_OI_UP | 127 / **+6.27** | 142 / **+5.13** | 133 / **+5.12** |
| PRICE_DOWN_OI_DOWN | 141 / −1.92 | 137 / −0.69 | 121 / +0.54 |

Patrón observado (OBSERVED, no validated): en los tres activos el cuadrante
`precio baja + OI sube` muestra media positiva, y `OI baja` tiende a debilidad.
Con n≈130 por celda, sin DEV, y con |media| ≤ 6.3 bps frente a un coste de
23.5–24.7 bps, esto **no es** una candidata: es la hipótesis mejor posicionada
para una campaña de datos forward. `UNCHANGED` (7/6/24 barras) queda excluido.

## 5. Temporalidad y honestidad

* Ninguna candidata pasa Filter 1 (gross>0) **y** Filter 2 (net>0): el net DEV
  más alto es **−17.33 bps**.
* Diagnóstico zero-cost (nunca admission): incluso sin coste, el máximo gross
  es +6.43 bps ⇒ el bloqueo no es sólo tarifa, es ausencia de señal grande.
* `future_leaks_detected = 0`: la señal usa sólo barras cuyo `available_at`
  está en o antes del reloj de decisión.
* No se inventó ninguna observación: los días sin OI, sin bucket completo o
  sin barra en el panel se excluyen y se cuentan.

## 6. Qué significa para la fase

```text
MICROSTRUCTURE_NO_EDGE_FOUND  (se mantiene y se amplía)
PAPER_CANDIDATES = 0
```

Tres hipótesis nuevas (M-02, M-09, M-10) quedan **medidas y rechazadas por
coste**; una (M-07) queda **medida pero no testeable** por retención de datos.
El cuello de botella sigue siendo doble: la tarifa taker domina (85% de la
barrera) y la información disponible no genera gross edge del orden requerido.
