# RUN_REPORT — WP-ECONOMIC-RECOVERY-007

## 1. Comandos y resultados

| # | comando | exit | salida |
| --- | --- | --- | --- |
| 1 | `python scripts/multi_family_backtest.py --dump-trades --out reports/economic/w006` | 0 | `MULTI_FAMILY_RESULTS.json`, `MULTI_FAMILY_RUN.json`, `TRADES.csv` (23 444 operaciones), 4m33s |
| 2 | `python scripts/w006_verify.py` | 0 | `INDEPENDENT_VERIFICATION.json` — 10/10 checks PASS sobre 23 444 operaciones |
| 3 | `python scripts/w007_classify.py` | 0 | `ECONOMIC_CLASSIFICATION.json` — 1 EXPERIMENT, 5 REJECT, 0 ADMIT |

`time` de la matriz: `real 4m32.981s`. Reproducible: sin aleatoriedad, sin reloj, sin red
en la evaluación (los datos ya están en el manifiesto con su hash).

## 2. Entradas

| entrada | ruta | sha256 (12) |
| --- | --- | --- |
| manifiesto de datos | `data/economic/w006/MANIFEST.json` | ver `MULTI_FAMILY_RUN.json` |
| BTCUSDT 5m | `data/economic/w006/datasets/BTCUSDT_5m.json` | fijado en el manifiesto |
| ETHUSDT 5m | `data/economic/w006/datasets/ETHUSDT_5m.json` | fijado en el manifiesto |
| SOLUSDT 5m | `data/economic/w006/datasets/SOLUSDT_5m.json` | fijado en el manifiesto |

Los digests se verifican al cargar: un dataset alterado aborta la evaluación con exit 2
(probado en `tests/unit/research/test_w006_engine.py`).

## 3. Qué se evaluó

- 6 familias productivas × 4 escenarios de coste × 3 activos × 120 días de barras 5m.
- Particiones cronológicas publicadas en el artefacto: DEV 50 %, VAL 25 %, OOS 25 %.
- Sin ajuste de hiperparámetros: se ejecutan los parámetros de producción tal cual.
- `ZERO_COST` se publica como diagnóstico y queda excluido de la regla de admisión.

## 4. Verificación independiente

`scripts/w006_verify.py` recalcula desde el CSV y las barras, sin importar el motor:

| check | resultado |
| --- | --- |
| identidad `net = gross − spread − slippage − fees` | PASS (residuo máximo ≤ 4·0,5e−6, derivado de la precisión publicada) |
| gross recalculado desde precios de referencia y cantidad | PASS |
| costes recalculados desde bps y nocional | PASS |
| fills recalculados desde el modelo de costes | PASS |
| causalidad: entrada exactamente una barra después de la señal | PASS |
| realismo de salidas (stop/target dentro de la barra, flip al open) | PASS |
| MFE/MAE recalculados sobre la exposición real | PASS |
| particiones según los límites publicados | PASS |
| agregados publicados = sumas del CSV | PASS |
| ninguna operación durante el warmup | PASS |

## 5. Resultado económico

Ver [FINAL_REPORT.md](FINAL_REPORT.md). Resumen: **ninguna estrategia admitida**;
`mean_reversion` es la única con edge bruto positivo (+242,81) y queda en `EXPERIMENT`
porque paga 1 048,87 de costes que su edge no cubre (0,1389 por operación frente a 0,60).

## 6. Limitaciones

- Un solo venue, tres activos, 120 días: suficiente para rechazar en esta muestra, no para
  declarar muerta una familia en todos los mercados.
- Spread modelado como 0 bps y estresado en 2X_COST; no hay datos de libro para medirlo.
- Sin modelo de fills maker: todos los fills son taker con slippage declarado.
- Los resultados son sensibles al tamaño (tope de 500 de nocional); con otro sizing los
  importes cambian, la relación edge/coste no.
