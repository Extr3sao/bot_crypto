# WP-TDM-11 — INDEPENDENT VERIFICATION

**Verificador:** `scripts/tdm11_verify.py` (implementación separada, mismo operador)
**Evidencia:** `.tdm11/verification.json` · `.tdm11/verify.log` · `.tdm11/controls.json`
**Resultado:** **12/12 comprobaciones PASS**
**Estado de independencia:** **`INDEPENDENCE_NOT_DEMONSTRATED`** — ver §5

---

## 1. Qué se verificó, y cómo

| ID | Comprobación | Resultado | Observado |
| --- | --- | --- | --- |
| V1 | El preregistro sigue teniendo el SHA congelado | PASS | `ef68b4c3…`, firmado 11:49:52Z |
| V2 | Cada artefacto publicado coincide con el hash del manifiesto | PASS | 8/8, 0 discrepancias |
| V3 | Los 24 datasets sellados: hash, recuento, orden, unicidad | PASS | 24 archivos, 0 problemas |
| V4 | Ninguna barra confirmatoria leída | PASS | máx. `1792857000000` < corte `1792857600000` |
| V5 | Cada fila del ledger es causal, SHORT, régimen down, sin solape y bien valorada | PASS | 115 filas, 0 problemas |
| V6 | Los estadísticos recomputados desde el CSV coinciden | PASS | n=115, −12,577, PF 0,1892, DD −4 287,05 |
| V7 | La cota superior sigue siendo negativa con t analítica y jackknife | PASS | −2,2499 / −2,2499; neto −26,04 |
| V8 | Total = suma de componentes; el maker de futuros reproduce 9,25; funding no cobrado; primario Spot | PASS | 23,7906 · 41,25 · 9,25 · 10 escenarios |
| V9 | El mínimo de muestra se reproduce desde su propia dispersión | PASS | 36 |
| V10 | El gate de disponibilidad declara `AWAITING_NEW_DATA` sin acceso | PASS | 0 barras, 0 fetch |
| V11 | Los controles adversariales pasan en proceso limpio | PASS | 11/11, exit 0 |
| V12 | Re-ejecutar la evaluación reproduce el ledger byte a byte | PASS | `28d76c0b78a93711…` |

## 2. Independencia de implementación (sí)

El verificador **no reutiliza** el estimador del builder. Diferencias deliberadas:

| Aspecto | Builder | Verificador |
| --- | --- | --- |
| Intervalo | bootstrap estacionario de bloques, 10 000 réplicas | t analítica + **jackknife** |
| Z-score de tendencia | sums incrementales | `math.fsum` por ventana, segunda implementación |
| Precios y causalidad | construidos por el builder | **reconstruidos desde las barras crudas**, fila a fila contra el ledger |
| Coste | `CostModelV3.evaluate()` | recuento de componentes + barrido de los 10 escenarios |
| Reproducibilidad | hash esperado | re-ejecución en subproceso + comparación de hash |

Que el jackknife y la t analítica den la misma cota superior (−2,2499) que el bootstrap (−0,3929) es la
prueba de que el veredicto no es un artefacto del método de remuestreo.

## 3. El verificador encontró un error real

`V8` detectó que la afirmación "el 9,25 bps no está modelado" era **falsa**: `VENUE_SPECS` tiene 10
escenarios y `BINANCE_USDM_PERP_MAKER` = 9,25 bps. El error venía de una tabla de consola truncada
(`UnicodeEncodeError` por `Ⓢ`). Se corrigieron `GOVERNANCE_RECONCILIATION.md`, `COST_MODEL_AUDIT.md`, el
preregistro (enmienda 01) y el manifiesto (`errors E4`). **El veredicto no cambió**: con coste cero el
neto ya es negativo. Un verificador que nunca contradice al builder no sería un verificador.

## 4. Qué NO pudo verificar

1. **Estadística confirmatoria**: no existe. No hay `CONFIRMATORY_RESULTS.csv` ni `TRADE_LEDGER.csv`, y su
   ausencia es correcta: solo deben existir con muestra limpia ejecutada.
2. **Coste del lado corto**: el modelo no cobra funding y asume p=0,5 de fill; no hay evidencia de fills
   reales con la que validarlo. Es un defecto de evidencia, no de cálculo.
3. **Ausencia de look-ahead en los datos de origen**: se verifica la causalidad del *uso* (entrada en `i+1`,
   régimen trailing, `data_time <= decision_time`), no la integridad histórica del proveedor.
4. **Independencia de autor**: ver §5.

## 5. Independencia de autor — no demostrada

Builder y verificador son **el mismo agente**. La separación es de implementación y de contexto de
ejecución, no de identidad. Por tanto:

- **NO** se emite `CERTIFIED`;
- **NO** se presenta como revisión de terceros;
- el estado declarado es `INDEPENDENCE_NOT_DEMONSTRATED`, y cualquier lector debe tratar los resultados como
  verificados por segunda implementación, no por segunda persona.

Esto no invalida un resultado **negativo** obtenido con datos sellados y reproducibilidad byte a byte: un
sesgo del autor empujaría hacia el positivo, no hacia el negativo. Sí invalidaría un `RESEARCH_CANDIDATE`
emitido en solitario.

## 6. Controles adversariales re-ejecutados (11/11)

| Control | Qué demuestra |
| --- | --- |
| C-01 look-ahead de régimen → **+17,05** bps | el PIT no está filtrando futuro: si lo hiciera, el número sería ese |
| C-02 entrada en la barra de decisión → −11,98 | la latencia declarada se aplica de verdad (0,60 bps de diferencia) |
| C-03/C-10 frescura | una ventana prematura u obsoleta se rechaza |
| C-04/C-05/C-06 integridad | duplicados, desorden y solape se rechazan |
| C-07 doble coste | la resta única está garantizada |
| C-08 borde plantado **+12,95** (IC inf. +7,11) | el arnés **no es ciego**: detecta un edge que existe |
| C-09 inversión −18,66 | el signo se mide, no se asume |
| C-11 NO_TRADE | 0,00 > −36,37 |

## 7. Dictamen

`12/12 PASS` sobre lo que existe.
`NOT_EXERCISED` sobre lo que no existe (ventana confirmatoria, fills reales).
`INDEPENDENCE_NOT_DEMONSTRATED` sobre la autoría.
La verificación **sostiene** la cadena: preregistro congelado → evaluación causal → ledger reproducible →
decisión tipada. **No** certifica el WP como revisado externamente.
