# WP-TDM-11 — FINAL REPORT

**RFC:** RFC-TDM-011 · **Hipótesis:** `TDM11-H1` · **Fecha:** 2026-10-25
**Commit:** `e67194e79a42aef2a2ded3aca21ac4a0ea3689c5` · **Worktree aislado**, checkout compartido intacto.

## VEREDICTO

> ### `NO_GO_ALPHA`
> La regla SHORT-bajista preregistrada **pierde 36,37 bps netos por operación** y su IC95 completo está por
> debajo de cero ([−48,06, −24,18]) en la única ventana temporalmente independiente disponible.
> **Estado operativo:** `AWAITING_NEW_DATA` — la ventana confirmatoria **nunca se abrió**.
> **`FALSE_SUCCESS = 0`.**

La hipótesis no espera datos nuevos para ser juzgada: ya está refutada con la evidencia anterior a la
ventana donde se eligió. No hace falta esperar al 2026-11-21 para repetirla.

---

## 1. Qué se ejecutó realmente

Siete scripts nuevos en un worktree aislado, sin red, sin órdenes y sin tocar un solo archivo existente:

| Fase | Ejecución | Resultado |
| --- | --- | --- |
| 11A | reconciliación de TDM-08/10, hashes, datasets, costes, reproducción de la afirmación direccional | 5/5 gates PASS + **1 hallazgo** |
| 11B | potencia sobre DEV y firma SHA-256 del preregistro | `ef68b4c3…` a las 11:49:52Z |
| 11C | gate de disponibilidad de muestra nueva (solo reloj y tasa preregistrada) | `AWAITING_NEW_DATA` |
| 11D | evaluación retrospectiva + 11 controles adversariales | 115 operaciones · **11/11** |
| 11D | verificación independiente de implementación | **12/12** |
| 11E | manifiesto, hashes y publicación versionada | 10 artefactos |

**No ejecutado, y declarado:** PAPER, LIVE, sizing, risk, admission, execution, accounting, evaluación
confirmatoria, y cualquier modificación de archivos existentes.

## 2. Qué estrategias se evaluaron

**Una.** `momentum@5m` SHORT con filtro `regime_trend == "down"`, entrada en el open de la barra siguiente,
hold fijo de 30 minutos, una posición a la vez, BTC/ETH/SOL. Parámetros de la familia congelados en el repo
(MACD 12/26/9, momentum 10 barras, umbral 0,5 %); ninguno se ajustó.

Se eligió entre las cubetas `down` con edge positivo y `n ≥ 40` en el HOLD **por tamaño de muestra, no por
edge**, y se documentó que la idea nació de mirar datos expuestos. Comparadores preregistrados, solo
descriptivos: no operar (0 bps), SHORT sin filtro de régimen y ambas direcciones con filtro.

## 3. Qué resultados se reprodujeron

| Elemento de WP-TDM-10 | Reproducción |
| --- | --- |
| 24 celdas del HOLD | **24/24**, mismas operaciones celda a celda |
| Operaciones del HOLD | **16 316**, exactas |
| Cubetas `trend=down` | **23/23** recuentos exactos |
| Hashes de 7 entregables | **7/7** |
| 24 datasets sellados | **24/24**, 0 duplicados, 0 huecos, solape DEV∩HOLD = 0 ms |
| Spec congelada | `8964d314…`, intacta |
| 23,7906 bps / 41,25 bps / 9,25 bps | reproducidos con Δ ≤ 0,001 |

**Lo que no se reprodujo:** la afirmación "5 de 6 mejores cubetas son SHORT en bajista". Son **3 de 6**, y
`regime_table.csv` no tiene columna de dirección: la atribución nunca fue publicada como dato. Las 24
celdas de TDM-10 están bien; la frase que las describe no.

## 4. Qué costes se utilizaron

| Escenario | bps | Papel |
| --- | --- | --- |
| `BINANCE_SPOT_STANDARD_TAKER` | **23,7906** | **primario** (fees 20 + spread 1 + slippage 2,63 + impacto 0,16) |
| `BINANCE_USDM_PERP_MAKER` (p=0,5) | 9,25 | suelo del modelo |
| `BINANCE_USDM_PERP_TAKER` | 13,79 | corto ejecutable |
| `BINANCE_SPOT_BNB_TAKER` | 18,79 | spot más barato |
| `BINANCE_SPOT_STANDARD_MAKER` (p=0,5) | 41,25 | maker con fill incierto |
| coste cero | 0,00 | lema de independencia |

Todos negativos, **incluido el coste cero** (−12,58 neto, IC superior −0,39): el coste no decide este
veredicto, solo lo agrava. El coste del lado corto queda `COST_UNVERIFIED_FOR_SHORT` porque el funding perp
no se cobra por defecto y el fill maker es una asunción.

## 5. Resultado económico

| | |
| --- | --- |
| Ventana | DEV `2026-06-25 → 2026-09-25`, **anterior** a la selección |
| Operaciones | 115 (mínimo preregistrado 36) |
| Edge bruto | **−12,58 bps** · IC95 [−24,27, −0,39] |
| Edge neto @23,79 | **−36,37 bps** · IC95 [−48,06, −24,18] |
| Win rate / PF | 18,26 % / 0,19 |
| Max drawdown | −4 287 bps · acumulado −4 182 bps |
| Por activo | BTC −31,98 · ETH −43,07 · SOL −34,63 (**3/3 negativos**) |
| Por mitad temporal | −34,11 / −38,59 (**2/2 negativas**) |

**El dato que ordena todo:** la misma regla, en el HOLD donde se eligió, gana +13,29 bps brutos; en el mes
anterior pierde −12,58. Un cambio de ventana de 30 días invierte el signo. La "ventaja" era el mes, no la
regla.

**Y el control que mide la tentación:** con 12 barras de futuro en la etiqueta de régimen, esa misma regla
pasa de −12,58 a **+17,05 bps**. El premio de mirar el futuro es exactamente el tamaño del que haría falta
para declarar un candidato. Por eso el PIT se verifica con un control que falla de forma visible.

## 6. Qué verificó el auditor

12/12 comprobaciones PASS: hashes, integridad de datasets, causalidad fila a fila del ledger (entrada =
open de `i+1`, salida = close de `i+7`, régimen trailing, sin solape), recálculo de estadísticos desde el
CSV, IC por **t analítica y jackknife** (métodos distintos de los del builder), reproducibilidad byte a byte
(`28d76c0b…`), y gate de disponibilidad sin acceso a datos.

**El verificador encontró un error real del builder:** la afirmación de que el 9,25 bps no estaba modelado.
Era falsa (es `BINANCE_USDM_PERP_MAKER`). Corregido en gobernanza, audit y enmienda 01. El veredicto no
cambió porque el caso de coste cero ya falla.

**Límite:** `INDEPENDENCE_NOT_DEMONSTRATED`. Mismo agente en builder y verificador; hay independencia de
implementación, no de autor. No se emite `CERTIFIED` y este informe no es una revisión de terceros.

## 7. Defectos abiertos

| # | Defecto | Impacto |
| --- | --- | --- |
| 1 | Coste del corto sin verificar: funding perp no cobrado, fill maker asumido p=0,5 | bloquea cualquier PASS futuro, no este NO_GO |
| 2 | Spread ESTIMADO a 1 bp, sin libro | coste subestimado |
| 3 | Sin muestra confirmatoria (0,83 días, ~1,07 ops esperadas vs 36) | protocolo incompleto por diseño |
| 4 | Independencia de autor no demostrada | sin certificación externa |
| 5 | `reports/**` ignorado por Git | mitigado: evidencia en `evidence/tdm/wp-tdm-11/` |
| 6 | Afirmación direccional del RFC no soportada por su artefacto | corregida aquí, no en el informe histórico |

## 8. Qué merece continuar y qué debe descartarse

**Descartar:**
- `momentum@5m` SHORT + régimen bajista: **refutada** con potencia suficiente y en las tres variantes de IC.
- La idea de que "el lado corto en tendencia bajista" es una pista con soporte: se generó sobre 5 cubetas de
  58–85 operaciones con IC que cruzan cero, y se reduce a 3 de 6 al recomputarla.
- Cualquier esperanza de que un filtro de régimen rescate una familia sin edge: en DEV el filtro **empeoró**
  el resultado (−5,40 → −12,58).

**No descartar todavía:** el marco de preregistro + gate de potencia + controles adversariales, que
funcionó: impidió que un slice de 74 operaciones se convirtiera en un candidato.

**Continuar:** nada de esta hipótesis. El siguiente paso económicamente sensato no es otra búsqueda sobre
el mismo objeto.

## 9. Qué evidencia falta para el siguiente nivel

1. **Una entrada con edge bruto > coste antes de cualquier filtro**, en dos ventanas independientes. Sin eso,
   ningún filtro de régimen, salida o sizing convierte una pérdida en ganancia.
2. **Spread observado por barra** (bid/ask), no el 1 bp estimado.
3. **Evidencia de fills pasivos** (cola, tasa de ejecución) para poder usar el escenario 9,25 como algo más
   que un suelo teórico.
4. **Funding realizado** en holds que cruzan los 8 h, y coste de borrow si se insiste en spot.
5. **Un verificador con identidad separada**, no solo implementación separada.
6. **Una muestra confirmatoria real** (≥36 operaciones post-corte, hoy imposible antes del 2026-11-21) para
   cualquier hipótesis futura que sobreviva al punto 1.

---

**Declaración final:** se ejecutó lo que se dice que se ejecutó, no se ejecutó lo que se declara no
ejecutado, el veredicto se emite por criterios fijados antes del test, y ningún fracaso técnico se ha
convertido en `NO_GO` ni ninguna media positiva en candidato. `FALSE_SUCCESS = 0`.
