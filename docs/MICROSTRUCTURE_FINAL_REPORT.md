# MICROSTRUCTURE_FINAL_REPORT — MICROSTRUCTURE-EDGE & FORWARD-DATA V1 / V2

Fecha: 2026-09-28. HEAD base de la fase: `3896f4e` (runtime verificado,
`SHADOW_DECISION_RUNTIME_VERIFIED`).

> Este documento **actualiza** el informe de `MICROSTRUCTURE-FINAL-V1`
> (2026-09-26). La sección histórica de V1 se conserva al final; el veredicto de
> esta fase la amplía, no la contradice.

## 1. Veredicto

```text
FINAL STATUS: MICROSTRUCTURE_NO_EDGE_FOUND
PAPER CANDIDATES: 0
FALSE_SUCCESS: 0
```

La frase completa: **no hay edge explotable en las hipótesis históricamente
testeables**, ahora incluidas cuatro que V1 no había medido (M-02 flow impulse,
M-07 OI x precio, M-09 lead/lag de flujo, M-10 flow cross-sectional). Las dos
dimensiones que quedan vivas **no son resolubles con histórico** y se declaran
como tales, sin inventar resultados sobre datos que no existen.

## 2. Qué se hizo (ejecución real, no documental)

1. **Pre-registro** antes de ejecutar: `docs/MICROSTRUCTURE_HYPOTHESES_V2.md`
   (reglas, horizontes, umbrales, asignación de coste, escalera de filtros).
2. **Código nuevo**, con tests: panel cross-asset PIT
   (`flow_panel.py`: agregación minuto→5m, panel de reloj común, lead/lag que
   rechaza `lag < 0`, flow impulse, cuadrantes OI, estadística tie-aware) y
   **`cost_model_v4.py`** (coste por activo con spread y volatilidad medidos,
   componiendo V3 sin duplicar su aritmética).
3. **Captura forward real** (`microstructure_collector.py`, 102.4 s,
   read-only): 11,346 registros, 0 duplicados, 0 desorden.
4. **Experimentos** (`scripts/microstructure_edge_v2.py`) sobre 4,032 slices de
   reloj común (14 días reales de aggTrades), sin huecos en el panel.
5. **Verificación externa de la agregación**: el volumen agregado coincide
   **exactamente** con el volumen de klines reales (ratio 1.0 en 288 barras por
   activo).
6. **Verificación independiente** de los artefactos
   (`docs/MICROSTRUCTURE_V2_INDEPENDENT_VERIFICATION.md`), y gates
   ruff/mypy/pytest sobre el HEAD final.

## 3. Resultado económico

Coste real por activo (`EXECUTION_COST_MODEL_V4`, 1,000 USD, market/market):

| activo | RT coste | requerido 1.5x |
| --- | ---: | ---: |
| BTC | 23.500 bps | 35.250 bps |
| ETH | 23.761 bps | 35.641 bps |
| SOL | 24.687 bps | 37.030 bps |

Mejor gross edge medido en la fase: **+6.43 bps** (M-02-ETH, DEV, n=168).

```text
déficit mínimo frente a break-even ........... 17.07 bps
déficit mínimo frente a required (1.5x) ...... 28.82 bps
peso de la tarifa en la barrera .............. 85.1%  (20.0 de 23.5 bps)
```

Dónde está el dinero del problema: **no** en el spread (0.001–0.84 bps) ni en
elegir activo (1.19 bps de diferencia BTC↔SOL), sino en la tarifa taker VIP0.
Y aun eliminando la tarifa, la señal no llega: con coste cero el máximo gross es
+6.43 bps.

## 4. Hipótesis nuevas: qué se midió y qué se rechazó

| hipótesis | n | gross DEV | net DEV | clasificación |
| --- | :-: | ---: | ---: | --- |
| M-02 flow impulse (BTC/ETH/SOL) | 131–168 | +1.40 / **+6.43** / +5.12 | −22.1 / −17.3 / −19.6 | `COST_KILLED` x3 |
| M-07 OI x precio | ~130 por celda (sólo OOS) | — | — | `LIMITED_HISTORY` x3 |
| M-09 BTC flow → ETH/SOL | 3,948 | +0.61 / +0.52 | −23.2 / −24.2 | `COST_KILLED` x2 |
| M-10 cross-sectional flow | 3,962 | +0.01 … +0.41 | −23.5 … −24.6 | `COST_KILLED` x2, `NO_INFORMATION` x2 |

Dos hallazgos honestos que merecen quedar escritos:

* **M-09 es la estructura más limpia jamás medida aquí**: lead/lag de flujo BTC
  con IC +0.027, n≈3,950 y monotonicidad **+1.0** en ETH. Sigue siendo 40x
  demasiado pequeña (top−bottom +3.67 bps frente a 23.5 bps de coste) y su signo
  se invierte en OOS.
* **M-02-SOL parece estable y no lo es**: gross positivo en DEV, VAL y OOS
  (+5.1 / +7.3 / +16.4) pero **6/14 días positivos**, con dos días
  (`2026-03-12` +49.6 bps, `2026-07-12` +48.1 bps) aportando casi todo. Es
  exactamente el patrón que un análisis por splits habría promocionado por
  error; el control a nivel de día lo desmonta.
* **M-07**: el cuadrante `precio baja + OI sube` da media positiva en los tres
  activos (+6.27 / +5.13 / +5.12 bps, n≈130, sólo OOS). `OBSERVED`,
  `INSUFFICIENT_SAMPLE`: no hay DEV donde elegir, así que la regla pre-registrada
  no se evalúa.

## 5. Integridad y disciplina

* PIT: reloj de decisión = **cierre** de barra; `available_at(feature) <=
  decision_time`; lead/lag con verificación por par y `lag < 0` prohibido por
  construcción ⇒ `future_leaks_detected = 0`.
* Panel: 4,032 slices, 288/día, **0 huecos**, 0 duplicados; buckets incompletos
  o fuera de la rejilla UTC se descartan (fail closed).
* Coste: un spread sin observaciones no se modela como cero
  (`AssetMarketInput` lanza excepción). `ZERO_COST` sólo diagnóstico.
* Dirección congelada desde DEV; ninguna regla se re-optimizó tras ver
  resultados; ninguna celda M-07 se eligió con OOS.
* **No se tocó el core runtime** (`RiskManager`, `PaperBroker`,
  `StartupReconciler`, hashing de `DecisionTrace`, contratos de outcome, replay,
  PIT): todo el trabajo vive en el DISCOVERY PLANE.

## 6. Entregables de esta fase

Docs: `MICROSTRUCTURE_HYPOTHESES_V2.md`, `EXECUTION_COST_MODEL_V4.md`,
`MICROSTRUCTURE_EXPERIMENT_REGISTRY_V2.md`,
`MICROSTRUCTURE_INFORMATION_CONTENT_V2.md`, `MICROSTRUCTURE_RESULTS_V2.md`,
`MICROSTRUCTURE_ADMISSION_V2.md`, `MICROSTRUCTURE_FINAL_REPORT.md` (este),
`MARKET_MICROSTRUCTURE_DATA_AUDIT.md` (actualizado),
`MICROSTRUCTURE_V2_INDEPENDENT_VERIFICATION.md`.
Máquina: `EXECUTION_COST_MODEL_V4.json`, `MICROSTRUCTURE_DATA_AUDIT_V2.json`,
`MICROSTRUCTURE_EXPERIMENT_REGISTRY_V2.json`,
`MICROSTRUCTURE_INFORMATION_CONTENT_V2.json`, `MICROSTRUCTURE_RESULTS_V2.json`,
`MICROSTRUCTURE_ADMISSION_V2.json`.
Código: `src/trading_bot/research/microstructure/{flow_panel,cost_model_v4}.py`,
`scripts/microstructure_edge_v2.py`, tests en
`tests/unit/microstructure/test_{flow_panel,cost_model_v4}.py`.
Artefactos de ejecución: `reports/microstructure-v2/{forward/,COLLECTION_REPORT.json,*.json}`.

## 7. Próxima fase recomendada (exactamente una)

```text
NEXT RECOMMENDED PHASE: MICROSTRUCTURE-FORWARD-COLLECTION-V1
```

Motivo: las dos únicas dimensiones que no están cerradas por datos son M-03
(book imbalance) y M-07 (OI con DEV/VAL reales), y **ninguna** puede resolverse
con histórico —el libro no existe y el OI se retiene ~31 días. Es la única vía
donde medir información nueva sigue siendo posible sin relajar el coste, y el
colector ya está implementado y validado (read-only, sin credenciales). Las
alternativas quedan descartadas por evidencia: `PAPER-CANDIDATE-INTEGRATION` no
tiene candidata que integrar; `EXECUTION-COST-MODEL-V2` ya se hizo (V3/V4) y el
hallazgo no es de fidelidad del modelo sino de magnitud de tarifa; `ALPHA-DISCOVERY-V4`
sobre OHLCV ya está agotada por V3+V1+V2.

Requisito duro para que esa fase pueda concluir algo: captura **continua** por
WebSocket (`@aggTrade`, `@depth` con reconciliación diff) y no sólo REST
polling, porque el propio manifiesto de esta fase midió un hueco de prints en
REST en ráfaga (BTCUSDT, `worst_step = 25`).

---

## 8. Sección histórica — V1 (2026-09-26, HEAD `5b4051e`)

```text
V1 FINAL STATUS: MICROSTRUCTURE_V1_NO_EDGE_FOUND
PAPER CANDIDATES: 0
```

* Hallazgo A: el coste real es ~23.5 bps RT (fee 10 bps/lado a VIP0), no los
  12 bps asumidos; `COST_MODEL_STATUS = OPTIMISTIC`; maker VIP0 = taker ⇒
  `MAKER EDGE GATE = FAIL`.
* Hallazgo B: techo de información testeable +2.36 bps (`flow_imbalance_z`) ⇒
  `COST_KILLED 3 | NO_GROSS_EDGE 5 | LIMITED_HISTORY 3 |
  EXECUTION_MODEL_REQUIRED 1`.
* M-02 (book) y OI > 30d: no testeables; no se declaró resultado sobre datos
  inexistentes.
* Decisión: `SPOT_INTRADAY_COST_BLOCKED`, `DERIVATIVES_NO_EVIDENCE`.
* Próxima fase propuesta entonces: `VENUE-AND-EXECUTION-RESEARCH-V1` (ejecutada,
  ver `VENUE_EXECUTION_FINAL_REPORT.md`).
