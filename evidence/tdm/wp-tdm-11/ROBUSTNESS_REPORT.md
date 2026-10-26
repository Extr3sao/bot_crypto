# WP-TDM-11 — ROBUSTNESS REPORT

**Regla:** `TDM11-H1` — `momentum@5m`, SHORT, `regime_trend == "down"`, entrada en el open de `i+1`,
salida en el close de `i+7` (30 min), una posición a la vez.
**Ventana evaluada:** DEV `2026-06-25T00:00Z → 2026-09-25T00:00Z` (92 días).
**Rol de la ventana:** `RETROSPECTIVE_OOS_PRE_SELECTION` — **no** es la evaluación confirmatoria, que no se
ha ejecutado (ver `DATASET_PROVENANCE.json`).
**Evidencia:** `RETROSPECTIVE_LEDGER.csv` · `retro.json` · `controls.json` · `verification.json`

---

## 1. Resultado primario

| Métrica | Valor |
| --- | --- |
| Operaciones | **115** (mínimo preregistrado: 36 → potencia suficiente) |
| Días cubiertos | 89,57 |
| Operaciones/día (solo régimen bajista) | 1,284 |
| Edge bruto medio | **−12,577 bps** |
| sd por operación | 56,503 bps |
| IC95 bruto (bootstrap estacionario, bloques de 1 día) | **[−24,27, −0,39]** |
| Edge neto medio @23,7906 | **−36,368 bps** |
| IC95 neto | **[−48,06, −24,18]** |
| Win rate (neto) | 18,26 % |
| Profit factor | 0,1892 |
| Max drawdown | −4 287,05 bps |
| PnL acumulado normalizado | −4 182,27 bps |

**Decisión:** `NO_GO_ALPHA`, `reason_code = NET_CI_UPPER_BELOW_ZERO`.
La cota superior del IC del neto es **−24,18 bps**: el escenario más favorable que el remuestreo produce
sigue perdiendo 24 bps por operación.

## 2. La incertidumbre no depende del método de intervalo

| Método | IC95 bruto | Cota superior |
| --- | --- | --- |
| Bootstrap estacionario (primario) | [−24,27, −0,39] | −0,39 |
| Bootstrap de bloques circular (bloque 2) | [−23,96, −0,73] | −0,73 |
| t analítica | [−22,90, −2,25] | −2,25 |
| **Jackknife** (verificador, V7) | — | **−2,25** |

Cuatro estimadores independientes, cuatro cotas superiores negativas. La más frágil es la del bootstrap
percentil (−0,39 bps): se reporta como tal, y por eso la decisión **no** se apoya en ella sino en el IC del
neto (−24,18).

## 3. Sensibilidad al coste

| Coste | Escenario | Neto medio | IC95 neto |
| --- | --- | --- | --- |
| 0,00 | lema (sin coste) | −12,58 | [−24,27, −0,39] |
| 9,25 | `BINANCE_USDM_PERP_MAKER` | −21,83 | [−33,52, −9,64] |
| 13,79 | `BINANCE_USDM_PERP_TAKER` | −26,37 | [−38,06, −14,18] |
| 18,79 | `BINANCE_SPOT_BNB_TAKER` | −31,37 | [−43,06, −19,18] |
| **23,79** | **primario spot taker** | **−36,37** | **[−48,06, −24,18]** |
| 41,25 | spot maker p=0,5 | −53,83 | [−65,52, −41,64] |

**Con coste cero ya se pierde.** Ningún escenario del modelo, ni siquiera uno más barato que el más barato
existente, cambia el signo. Esto es lo que hace que el veredicto sobreviva al hecho de que el coste del
lado corto no esté verificado (funding no cobrado, fill maker asumido).

## 4. La selección no sobrevive al cambio de ventana

| Ventana | n | Bruto medio | Neto medio | IC95 (cota inferior) |
| --- | --- | --- | --- | --- |
| HOLD (donde se eligió la regla, expuesto) | 68 | **+13,29** | −10,50 | −2,64 (bloques) |
| DEV (anterior a la selección, expuesto) | 115 | **−12,58** | −36,37 | −24,27 (bootstrap estacionario) |

La misma regla, con la misma definición, cambia de signo entre dos meses contiguos. **La evidencia de
selección ni siquiera es positiva neta** (+13,29 bruto contra 23,79 de coste) y su cota inferior por bloques
ya cruza cero (−2,64). Esto reproduce, en dirección inversa, el patrón que TDM-10 documentó con
`breakout@1h` (positivo en DEV, negativo en HOLD): la ventana decide el signo, no la regla.

## 5. Estabilidad interna

| Corte | Resultado |
| --- | --- |
| BTC (36 ops) | neto **−31,98** bps |
| ETH (35 ops) | neto **−43,07** bps |
| SOL (44 ops) | neto **−34,63** bps |
| Primera mitad temporal | neto **−34,11** bps |
| Segunda mitad temporal | neto **−38,59** bps |

**3/3 activos negativos y 2/2 mitades negativas.** No hay un subconjunto donde la regla gane.

## 6. Comparadores preregistrados (descriptivos)

| ID | Regla | n | Bruto medio | Neto @23,79 |
| --- | --- | --- | --- | --- |
| `C0` | No operar | — | 0,00 | **0,00** |
| `C1` | SHORT sin filtro de régimen | 1 621 | −5,40 | −29,19 |
| `C2` | Ambas direcciones + régimen bajista | 138 | −12,37 | −36,16 |
| **H1** | SHORT + régimen bajista | 115 | −12,58 | −36,37 |

El filtro de régimen **empeora** el resultado en DEV (−5,40 → −12,58). No se testearon inferencialmente:
son diagnósticos y así se declaran; ninguna comparación se usa para seleccionar nada.

## 7. Controles adversariales — 11/11

| ID | Control | Observado |
| --- | --- | --- |
| C-01 | etiquetas de régimen con 12 barras de futuro | **+17,05 bps** (n=90) frente a −12,58 con PIT |
| C-02 | entrada en el cierre de la barra de decisión | −11,98 (optimismo de **0,60 bps** frente a next-open) |
| C-03 | ventana que empieza antes del corte | rechazada |
| C-04 | barra duplicada | rechazada (3 problemas) |
| C-05 | timestamps desordenados | rechazado |
| C-06 | solape DEV/HOLD | rechazado |
| C-07 | coste restado dos veces | rechazado |
| C-08 | deriva negativa plantada (borde positivo) | **detectado**: 622 ops, +12,95 bps, IC95 inf. +7,11 |
| C-09 | deriva invertida | **−18,66 bps** (signo invertido) |
| C-10 | dataset obsoleto (>2 barras de retraso) | rechazado |
| C-11 | comparador NO_TRADE | 0,00 > −36,37 |

**C-01 es el control más informativo del WP:** doce barras de futuro en la etiqueta de régimen convierten
una regla que pierde 12,58 bps en una que gana 17,05. Cualquier trabajo futuro sobre esta hipótesis debe
demostrar PIT antes de reportar un número, porque el premio de mirar el futuro es exactamente del tamaño
del que haría falta para "aprobar".

## 8. Reproducibilidad

- Segunda ejecución limpia del evaluador: **ledger byte-idéntico**, SHA-256 `28d76c0b78a93711…` (V12).
- Estadísticos recomputados desde el CSV con otra implementación: coinciden (V6).
- Cada fila del ledger verificada contra las barras crudas: entrada = open de `i+1`, salida = close de
  `i+7`, régimen `down` en la barra de decisión, sin posiciones solapadas (V5, 0 problemas en 115 filas).
- El ledger contiene las 115 operaciones completas, no un resumen.

## 9. Qué habría cambiado el veredicto

1. Un edge bruto medio > +0,39 bps con `n ≥ 36` habría dejado el veredicto abierto.
2. Un edge bruto medio > +23,79 con cota inferior > 0 habría producido `RESEARCH_CANDIDATE`… salvo que el
   coste del corto sigue sin verificar, así que el máximo habría sido `INCONCLUSIVE` hasta modelar funding.
3. Un resultado positivo concentrado en un solo activo habría sido inestable por §5.

## 10. Límites declarados

1. **Una sola ventana retrospectiva**: los datos disponibles cubren 2026-06-25 → 2026-10-24 (~4 meses),
   de los cuales 92 días son DEV y 30 el HOLD expuesto; la ventana confirmatoria no existe todavía
   (`AWAITING_NEW_DATA`, fecha más temprana 2026-11-21).
2. DEV se usó para la potencia **y** para esta comprobación retrospectiva; la media DEV era visible al
   firmar el preregistro y así se declara. No se usó para elegir la regla (eso se hizo sobre HOLD).
3. Coste ESTIMATED y coste del corto no verificado (§4 del audit). Irrelevante para el signo, no para un
   eventual PASS.
4. Sin stops ni take-profits: la regla es un hold fijo de 30 min, no una política de salida.
5. Verificación de implementación, no de autor: `INDEPENDENCE_NOT_DEMONSTRATED`.
6. `reports/**` sigue ignorado por Git; la evidencia de este WP se publica en `evidence/tdm/wp-tdm-11/`.
