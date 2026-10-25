# PAPER_ADMISSION_DIAGNOSIS — por qué ninguna estrategia está admitida

> Fuente primaria: `config/strategy_admission.json` (24 entradas), generado por
> `scripts/build_strategy_admission.py` a partir de dos artefactos commiteados.
> Verificado el 2026-10-23 sobre `codepaper/supervisor-001` @ `3b758e22`.

---

## 1. Respuesta corta

**Ninguna estrategia está admitida porque la conjunción que el constructor exige es falsa para
las 24 entradas.** No hay un bug de admisión, ni un flag apagado, ni un entorno mal configurado:
hay tres cerrojos independientes y cada uno basta por sí solo.

| # | Cerrojo | Estado medido | Evidencia |
| --- | --- | --- | --- |
| L1 | Criterios de admisión pre-registrados (`c1..c8`) | **0/6 familias** los superan | `docs/STRATEGY_ADMISSION_MATRIX.md`: net negativo y PF 0.50–0.72 en las 6; `c2`, `c3`, `c4` y `c7` fallan en todas |
| L2 | Línea de coste del runtime | 23.35 bps RT (admisión) / 12.18 bps RT (taker más barato observado) frente a un **máximo gross de 8.91 bps** | `data/recovery/COST_BARRIER_EXPLORER.json`, `cells[].runtime_admission_rt_bps` y `reachability.frontier` |
| L3 | Procedencia de la muestra | 18 de 24 entradas declaran `sample_trades = 0` («sample size unproven») | `config/strategy_admission.json`, campo `edge_evidence.sample_trades` |

L1 vacía la lista `paper_candidates`; L2 hace que, aunque se llenara, el net seguiría siendo
negativo; L3 impide promocionar las celdas de 15m/30m/1h sin volver a medir.

---

## 2. La regla exacta que se aplica

`scripts/build_strategy_admission.py` L91-96:

```python
if family in paper_candidates and gross_bps > 0:
    status = "PAPER_CANDIDATE"
elif gross_bps > 0:
    status = "COST_KILLED"
else:
    status = "NO_GROSS_EDGE"
admitted = status == "PAPER_CANDIDATE"
```

`paper_candidates` viene de `docs/STRATEGY_ADMISSION_MATRIX.json`. Hoy es **vacío** (0/6).
Por tanto:

```
admitted(strategy) = (family ∈ paper_candidates) ∧ (gross_bps > 0)
                   = False ∧ … = False        para las 24 entradas
```

**Corolario incómodo y deliberado:** una celda con gross positivo (+8.91 bps) sigue sin poder
ser `PAPER_CANDIDATE` mientras su familia no esté en `paper_candidates`. El estado
`COST_KILLED` no es un paso previo a la admisión: es un diagnóstico terminal en este esquema.
Cambiar eso **sería cambiar los criterios de admisión**, que esta directiva prohíbe.

### Los dos criterios que hacen imposible «ya casi»

`docs/STRATEGY_ADMISSION_CRITERIA.md` (pre-registrados en `c1ffbaa`, antes de resultados):

- **c2**: net > 0 tras costes BASE y expectancy/trade > 0.
- **c7**: PF con **2X_COST** > 0.9 — sobrevivir al doble de coste sin colapsar.

Con un techo de gross de 8.91 bps y una línea de 12.18 bps, c2 es aritméticamente inalcanzable
para toda la población evaluada; c7 lo es todavía más. No es un margen que se cierre con más
muestras, es un signo.

---

## 3. Motivo de rechazo, estrategia por estrategia

Los 24 identificadores son `familia@timeframe`. `rationale` es literal del ledger.

| Estrategia | Gross (bps/trade) | Trades (explorer) | Estado | Motivo registrado |
| --- | ---: | ---: | --- | --- |
| `volatility@30m` | **+8.912** | 194 | COST_KILLED | gross > 0 pero sin `paper_candidates`; muestra no publicada (ledger `sample_trades=0`) |
| `volatility@1h` | **+6.276** | 96 | COST_KILLED | ídem; 96 trades < mínimo c1 (≥100) |
| `mean_reversion@30m` | **+5.472** | 934 | COST_KILLED | ídem |
| `mean_reversion@15m` | **+2.714** | 1 579 | COST_KILLED | ídem |
| `trend@30m` | **+2.206** | 1 562 | COST_KILLED | ídem |
| `mean_reversion@5m` | **+1.485** | 3 190 | COST_KILLED | `c2,c3,c4,c7` fallan; OOS net −169.88 |
| `trend@15m` | **+1.284** | 1 616 | COST_KILLED | ídem D-01 |
| `breakout@5m` | −0.084 | 2 426 | NO_GROSS_EDGE | `c2,c3,c4,c7`; OOS −138.81 |
| `breakout@1h` | −0.222 | 710 | NO_GROSS_EDGE | D-01 |
| `ema_crossover@30m` | −0.726 | 3 214 | NO_GROSS_EDGE | D-01 |
| `ema_crossover@1h` | −0.964 | 2 620 | NO_GROSS_EDGE | D-01 |
| `ema_crossover@15m` | −1.122 | 2 913 | NO_GROSS_EDGE | D-01 |
| `trend@1h` | −1.252 | 1 405 | NO_GROSS_EDGE | D-01 |
| `trend@5m` | −1.645 | 1 291 | NO_GROSS_EDGE | `c2,c3,c4,c7`; OOS −17.35 |
| `breakout@30m` | −1.792 | 1 281 | NO_GROSS_EDGE | D-01 |
| `breakout@15m` | −1.822 | 2 042 | NO_GROSS_EDGE | D-01 |
| `momentum@5m` | −1.884 | 2 526 | NO_GROSS_EDGE | `c2,c3,c4,c7`; OOS −205.41 |
| `mean_reversion@1h` | −2.226 | 448 | NO_GROSS_EDGE | D-01 |
| `momentum@1h` | −2.334 | 2 304 | NO_GROSS_EDGE | D-01 |
| `momentum@30m` | −2.612 | 2 957 | NO_GROSS_EDGE | D-01 |
| `momentum@15m` | −3.972 | 3 003 | NO_GROSS_EDGE | D-01 |
| `ema_crossover@5m` | −4.561 | 1 725 | NO_GROSS_EDGE | `c2,c3,c4,c7`; OOS −144.38 |
| `volatility@5m` | −4.735 | 520 | NO_GROSS_EDGE | `c2,c3,c4,c7`; OOS −52.11 |
| `volatility@15m` | −7.064 | 277 | NO_GROSS_EDGE | D-01 |

Fuente de gross/trades: `data/recovery/COST_BARRIER_EXPLORER.json` → `cells[]`
(cada celda publica `zero_cost_gross_bps`, `ledger_status`, `trades`).
El ledger redondea a 2 decimales (`6.28` vs `6.276`); aquí se usa el valor sin redondear.

**No hay estrategias «sin evaluar» en el sentido de ausentes:** las 24 tienen gross medido.
Lo que falta es muestra *publicada* en 18 de ellas (§4) y OOS en **todas** las de 15m/30m/1h.

---

## 4. La diferencia entre «evaluada» y «con datos suficientes»

| Población | Qué tiene | Qué le falta |
| --- | --- | --- |
| 6 familias @5m | gross zero-cost, net/PF BASE, PF DEV, PF OOS, PF 2X, OOS net, trades | superar c2/c3/c4/c7 (no lo hacen) |
| 7 celdas @15m/30m/1h con gross > 0 | gross zero-cost, conteo de trades recuperable del explorer (194–1 616) | **OOS propio**, drawdown, PF 2X, y `sample_trades` en el ledger (18 entradas a 0) |
| 11 celdas restantes @15m/30m/1h | gross zero-cost negativo | nada: gross ≤ 0 cierra el caso |

Tres matices que importan para no sobreactuar:

1. El `sample_trades = 0` del ledger **no significa que no haya trades**: significa que el
   documento fuente (`docs/STRATEGY_DISCOVERY_V3_RESULTS.json`, bloque D-01) no los publicó. El
   explorer sí los recuperó de `reports/strategy-baseline/TIMEFRAME_AUDIT.json`. Es un hueco de
   **procedencia**, no de datos.
2. `volatility@1h` tiene 96 trades y `volatility@30m` 194: la primera **no llega** al mínimo de
   100 de c1; la segunda lo supera pero no tiene OOS ni drawdown.
3. Ninguna celda de 15m/30m/1h tiene `drawdown` medido, y en las 6 familias @5m `c6_dd` y
   `c8_no_window_dominance` figuran como `null` (`unknown_checks` de
   `docs/STRATEGY_ADMISSION_MATRIX.json`). Por tanto **c6 y c8 son «no verificados» en todo el
   universo**, no «aprobados». El rechazo actual no depende de ellos (c2/c3/c4/c7 son `false`),
   pero una candidata futura sí tendría que medirlos.

---

## 5. Qué tendría que cambiar (y qué no)

| Cambio | ¿Sirve? | Por qué |
| --- | --- | --- |
| Editar el ledger a mano | **No** | El ledger se regenera desde artefactos; un `PAPER_CANDIDATE` sin evidencia se rechaza al cargar (docstring de `admission_ledger.py`) |
| Bajar el umbral de admisión | **No, y está prohibido** | Esta directiva: «No cambiar límites de riesgo ni criterios de admisión» |
| Cambiar el runtime | **No** | El runtime ya hace lo correcto: se niega |
| Producir un artefacto de investigación nuevo que ponga una familia en `paper_candidates` con gross > 0 **y** net > 0 **y** OOS > 0 **y** PF 2X > 0.9 | **Sí** | Es la única puerta que el constructor reconoce; no requiere tocar código |
| Medir una línea de coste real por debajo del gross máximo | **Sí, y es lo más barato** | Convierte L2 de «imposible» en «medible»: ver `NEXT_EXPERIMENT.md` |

**Decisión:** el bloqueo es de **evidencia económica**, no de ingeniería. Cualquier trabajo
adicional sobre el runtime PAPER (supervisor, locks, procedencia) no mueve la admisión ni un
ápice: `def_run_019_close.py` L508-511 ya lo dice — *«la admisión no depende de este WP; la
procedencia de sesión no convierte un NO_GO en GO»*.

---

## 6. Reproducción

```bash
python - <<'PY'
import json
s=json.load(open("config/strategy_admission.json"))["strategies"]
print(len(s), sum(v["admitted_for_paper"] for v in s.values()))          # 24 0
print(sum(v["edge_evidence"]["sample_trades"]==0 for v in s.values()))    # 18
print(sorted((v["expected_gross_edge_bps"],k) for k,v in s.items())[-3:])  # 5.47, 6.28, 8.91
PY
```

Salida esperada: `24 0`, `18`, `[(5.472,'mean_reversion@30m'), (6.276,'volatility@1h'), (8.912,'volatility@30m')]`.
