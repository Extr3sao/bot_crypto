# NEXT_EXPERIMENT — EXP-MAKER-LINE-001

> Pre-registrado el 2026-10-26 por WP-TDM-016, **antes** de descargar un solo tick.
> Sustituye a `CODEX-PAPER-ADMISSION-DIAG-001/NEXT_EXPERIMENT.md` con una pregunta
> más estrecha y un umbral numérico derivado, no una intención.
> `NEXT_EXPERIMENT.json` contiene los mismos campos en forma legible por máquina.

---

## 1. La pregunta, en una línea

**¿Cuál es el coste de ejecución maker *medido* —no asumido— de `volatility@30m` a 200 USD
en USDⓈ-M profundo, y está por debajo de 4.912 bps por ida y vuelta?**

## 2. De dónde sale 4.912

No es un umbral elegido: es una resta con los dos términos ya medidos.

| Término | Valor | Clase | Fuente |
| --- | ---: | --- | --- |
| Gross de `volatility@30m` (194 trades) | **8.912 bps/trade** | medido | `COST_BARRIER_EXPLORER.json` → `cells[]` |
| Comisiones maker USDⓈ-M VIP0 (2 + 2) | **4.000 bps RT** | conocido (tarifa publicada) | `venue_grid[BINANCE_USDM_PERP_MAKER].components` (KNOWLEDGE=KNOWN) |
| **Presupuesto de ejecución** | **4.912 bps** | derivado | 8.912 − 4.000 |
| Coste de ejecución que el modelo **asume** hoy | 5.250 bps | asumido | 1.000 selección adversa + 0.250 fill perdido + 4.000 inflación de tasa de llenado |

Consecuencia exacta: la línea maker modelada son 9.250 bps porque **asume** 5.250 bps de
ejecución. Con 4.912 o menos, el neto de la celda es ≥ 0 y la línea deja de matarla. Con 4.913
o más, no hay estrategia del universo OHLCV intradía que pueda pagar su propio coste.

Es la única incógnita que queda entre el mejor activo del repositorio y la admisión PAPER:
el gross está medido, las comisiones son tarifa publicada, y lo único supuesto es la ejecución.

## 3. Hipótesis

| | |
| --- | --- |
| **H1** | El coste de ejecución maker medido (selección adversa + penalización por fill perdido) es **< 4.912 bps** en `volatility@30m` y/o `@1h`, con IC95 % bootstrap inferior del neto > 0. |
| **H0** | El coste medido es **≥ 4.912 bps**, o la selección adversa se come el gross. |
| **Predicción declarada ahora** | **H0.** EXP-003M ya midió **+2.057 bps de selección adversa por fill** en spot y un techo bruto que cubre **0.356×** el suelo de comisiones, con **0/24** puntos del barrido cola×latencia en neto positivo. Se declara para que un resultado favorable sea informativo y no una sorpresa narrada después. |

## 4. Diseño (congelado)

- **Población:** `volatility@30m` (194 trades) y `volatility@1h` (96). Controles de muestra
  grande: `mean_reversion@30m` (934) y `trend@30m` (1 562). BTCUSDT, ETHUSDT, SOLUSDT.
- **Periodo:** W1–W7 (2026-03-01 → 2026-09-24). Holdout 2026-08-06 → 08-20 **cerrado**, igual
  que en EXP-003M.
- **Ejecución:** post-only en el mejor bid/ask, entrada y salida. Si no llena en N barras la
  señal caduca: cuenta como *no-trade*, nunca como pérdida (así el neto no se maquilla
  eliminando las malas).
- **Motor de fills:** `scripts/exp_003m_fills.py` (reutilizado, no reescrito), parametrizado de
  spot a USDⓈ-M.
- **Coste:** `COST_MODEL_V3` con Binance USDⓈ-M VIP0: maker 2 bps/lado, taker 5 bps/lado; el
  *funding* se aplica solo si el horizonte cruza un timestamp de funding, y se **mide**.
- **Datos nuevos (única dependencia externa):** `aggTrades` + `bookTicker` públicos de USDⓈ-M
  para los mismos 42 pares `(símbolo, día)` de EXP-003M (`GET /fapi/v1/aggTrades`,
  `GET /fapi/v1/ticker/bookTicker`), sin claves.
- **Prohibido en este experimento:** re-tuning de parámetros, búsqueda de umbrales, nuevo
  indicador, abrir el holdout, tocar el ledger, tocar los criterios de admisión, órdenes live.

## 5. Gates pre-registrados

| ID | Gate | Umbral | Por qué |
| --- | --- | --- | --- |
| G1 | Reproduce el gross publicado | ±0.5 bps de 8.912 / 6.276 | si no reproduce, el motor de fills no es el mismo |
| G2 | Muestra | ≥ 100 trades por celda, ≥ 30 en OOS | criterio c1 vigente |
| **G3** | **Coste de ejecución medido** | **< 4.912 bps** | el umbral de §2, el gate que decide |
| G4 | Neto medido | net bps/trade > 0 y IC95 % bootstrap (bloques móviles) inferior > 0 | criterio c2 + significancia |
| G5 | Estrés de coste | con 2× el coste medido, PF > 0.9 | criterio c7 vigente |
| G6 | Drawdown | DD máximo ≤ 10 % de la equity inicial simulada | criterio c6, hoy `null` en las 24 celdas |
| G7 | No-dominancia | ninguna ventana aporta > 60 % del net positivo | criterio c8, hoy `null` |
| G8 | Tasa de llenado | se publica; no es gate | contexto: un net positivo que solo mejora por llenar menos se marca `FILL_SELECTED` y **no** se promociona |
| G9 | Clase de evidencia | `MEASURED_FROM_OBSERVED_TAPE`; sin libro L2 la cola se barre, no se mide | el veredicto máximo es `CANDIDATE_FOR_PREREGISTRATION`, nunca `PAPER_CANDIDATE` por sí solo |

G6 y G7 están aquí porque la auditoría WP-016A mostró que **c6 y c8 figuran como `null` en las
24 celdas**: sin medirlos, ninguna candidata futura podría superar la conjunción pre-registrada
aunque G1–G5 salieran bien.

## 6. Criterio de muerte, decidido ahora

Si el coste de ejecución medido es **≥ 4.912 bps**, se cierra la lane OHLCV intradía completa:
no se financia otra campaña de indicadores sobre 5m/15m/30m/1h. El trabajo siguiente sería
mecanismo distinto (funding/basis/order flow) u horizonte multi-día, y eso es otra directiva.

Si es **< 4.912 bps**, el resultado **no** admite nada por sí solo: produce el artefacto que
`scripts/build_strategy_admission.py` lee, y la admisión se decide aplicando los criterios
vigentes, sin tocarlos.

## 7. Entregables

```
reports/ai-bots/EXP-MAKER-LINE-001/
  PREREGISTRATION.md              # este diseño, congelado antes de descargar la cinta
  RUN_REPORT.json|md              # comandos, exit codes, salidas
  FILL_MODEL.json                 # barrido cola × latencia, tasa de llenado, selección adversa
  ECONOMICS.json                  # gross/net/expectancy/DD/dominancia por celda y escenario
  INDEPENDENT_VERIFICATION.json   # verificador que NO importa el motor (BUILDER != VERIFIER)
  FINAL_REPORT.md                 # GO/NO_GO con la tabla de gates
```

`INDEPENDENT_VERIFICATION.json` debe recalcular cada número desde la cinta cruda, ejecutar ≥ 8
mutaciones (gross inflado, comisión bajada, trades eliminados, tasa de llenado movida, DD
recortado, veredicto invertido, umbral de G3 desplazado, IC ensanchado) y publicar
`false_success`. Un `false_success > 0` retira el veredicto.

## 8. Coste y duración

Offline, 0 claves, 0 órdenes. Una descarga pública (~GB) y ~1 h de CPU para el barrido.
Reutiliza el motor de fills de EXP-003M, `COST_MODEL_V3`, las señales de D-01 y el patrón de
verificador independiente de EXP-003M/003P. Lo único nuevo es **una cinta de futuros**.

## 9. Qué decisión habilita

- **G3 pasa y G1–G7 también** ⇒ existe una celda con evidencia económica medida; se aplica el
  pipeline de admisión autorizado y, si admite, se abre PAPER con datos reales de mercado
  (72 h, metodología de `docs/paper-trading-methodology.md`). Ese es el camino a LIVE, y no
  se recorre en este WP.
- **G3 falla** ⇒ `ECONOMIC_BLOCKED` definitivo para la lane intradía con costes minoristas, con
  una medición en la mano en lugar de una estimación.

## 10. Lo que este WP **no** ha hecho

- No ha descargado la cinta ni ejecutado el experimento: lo pre-registra.
- No ha admitido ninguna estrategia ni ha colocado una sola orden PAPER con datos reales,
  porque el ledger admite 0/24 y forzarlo sería relajar el control que impide exactamente eso.
- No ha tocado LIVE, ni capital real, ni los criterios de admisión, ni el ledger a mano.
