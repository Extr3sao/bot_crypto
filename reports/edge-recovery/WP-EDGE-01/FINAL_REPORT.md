# FINAL REPORT — WP-EDGE-01, cierre de investigacion y ejecucion H6/OOS

> Registrado el 2026-10-12 sobre la rama `agent/edge-recovery/WP-EDGE-00-baseline`. Este informe
> responde a las seis preguntas del encargo de cierre; los dos experimentos que lo sustentan viven en
> `retest-h6/` y `oos-trend-4h/`, cada uno con su `*_VERIFICATION.json` producido por un proceso
> aparte que no importa el paquete. El registro legible por maquina esta en `closure/RUN_REPORT.json`.

---

## 1. Que gana y que pierde, en DEV y fuera de muestra

| libro | DEV | VAL | OOS | veredicto de la campana |
|---|---|---|---|---|
| `edge_intra_01` (intradia, 15m) | -496,4298 | -479,1833 | -94,8077 | `REJECT` |
| `edge_intra_02` (retest + FVG) | -189,8769 | — | — | `REJECT` |
| `edge_intra_02_no_fvg` | -500,8327 | — | — | `REJECT` |
| `edge_trend_01_4h` | **+1.921,1792** | +4,5253 | +208,0056 | `INSUFFICIENT_EVIDENCE` |
| `edge_trend_01_1d` | +926,5089 | — | — | `INSUFFICIENT_EVIDENCE` |

Nada pasa la puerta de admision de la campana. El unico libro con un neto materialmente positivo en
DEV es el 4h tendencial, y su unica muestra fuera de muestra util es OOS (VAL es plano: +4,53 USDT en
58 operaciones).

Los cinco veredictos, los cinco numeros DEV de la tabla y los tres OOS **no se movieron** al cambiar
el codigo durante este cierre: la campana se re-ejecuto entera y `STRATEGY_RESULTS.json` quedo byte a
byte igual que en `HEAD`. Lo que cambio en los artefactos del WP es la huella del codigo y el
registro de hipotesis, no una cifra.

## 2. H6: la entrada por retest mejora la expectativa, no el neto

`ABL-EDGE01-H6`, en `retest-h6/`. Las senales son las CONGELADAS; lo unico que cambia es como se
ejecutan. Tres ramas por ventana, y la regla economica y la de ejecucion se congelaron antes de
correr ninguna.

| rama (`DEV`, `BASE`) | operaciones | neto | expectativa | win rate | profit factor | dd | exposicion |
|---|---|---|---|---|---|---|---|
| `frozen_market` (libro publicado) | 290 | -496,43 | -1,7118 | 19,31% | 0,3224 | 5,04% | 1,57% |
| `plan_market` (el mismo plan a mercado) | 290 | -496,43 | -1,7118 | 19,31% | 0,3224 | 5,04% | 1,57% |
| `plan_limit` (limite en el nivel) | 372 | **-495,88** | **-1,3330** | 9,41% | 0,2912 | 5,00% | 0,99% |

- **Veredicto**: **`RETEST_IMPROVES_NET`** con lectura de ejecucion **`VIABLE`**. OOS, que no decide:
  -55,7084 USDT en 54 operaciones con 9,26% de win rate, frente al libro congelado en esa misma
  ventana (-94,8077 en 63 operaciones, 17,46%). El win rate baja tambien fuera de la ventana de
  diseno: la entrada en el nivel gana menos veces y cobra mas por operacion.
- **Ejecucion**: 686 ordenes planificadas en DEV, 372 rellenas (**54,23%**), 128 caducadas, 183
  rechazadas por el presupuesto de riesgo en el momento del toque y 3 canceladas al terminar la
  ventana. Fuera de la ventana de diseno el relleno sube: VAL 76,86% y OOS 81,82%.
- **Confirmacion**: VAL +121,74 USDT mejor que el libro congelado y OOS +39,10, las dos con el mismo
  signo y sin re-ajustar nada.
- **El brazo de control es la parte fuerte del experimento**: `plan_market` reproduce el libro
  congelado **exactamente** (-496,4298 / -1,7118). La diferencia entre ramas es el precio de entrada,
  no un conjunto distinto de senales.
- **Cambio de forma, no solo de tamano**: entrar en el nivel NO gana mas veces — el win rate cae de
  19,31% a 9,41% y el profit factor tambien baja (0,3224 a 0,2912) —, gana mas por operacion: menos
  entradas, mas lejos del stop y un pago medio mayor. La exposicion baja (1,57% a 0,99%) y el
  drawdown casi no se mueve (5,04% a 5,00%). Es la firma de "se compra la extension": dejando de
  perseguir la ruptura desaparecen las operaciones que se llenaban tarde y se quedaban sin recorrido.
- **Lo que NO se puede decir**: la expectativa mejora (+0,3788 por operacion, +22%) pero el neto se
  queda plano porque el plan participa menos; el neto absoluto sigue siendo negativo, asi que la
  ruptura intradia no es rentable ni con esta entrada. Y el relleno NO se asume: se modela con libro
  de ordenes simple, al nivel y nunca mejor, pagando los mismos costes que una entrada a mercado.

## 3. Tendencia 4h: no hay evidencia suficiente para PAPER

`OOS-EDGE01-TREND-4H`, en `oos-trend-4h/`, sin tocar un solo parametro. La puerta de PAPER se
congelo antes de correr la descomposicion.

| criterio (congelado antes de medir) | resultado | detalle |
|---|---|---|
| `oos_net_positive` | PASS | +208,01 USDT |
| `oos_net_positive_under_2x_fees` | PASS | +160,67 USDT |
| `oos_trades_floor` (>=30) | PASS | 52 operaciones |
| `no_single_trade_carries_the_net` (<=50%) | **FAIL** | la mayor operacion es **79,87%** del neto |
| `assets_positive` (>=2 de 3) | PASS | BTC +3,06 y ETH +281,60; SOL -75,55 |
| `drawdown_below_buy_and_hold` | PASS | 2,57% frente a 49,84% / 62,22% / 73,20% de buy & hold |
| `periods_positive` (>=2 de 3) | PASS | dos de los tres periodos declarados |

**Veredicto: `NOT_SUFFICIENT_EVIDENCE`.** La razon es exactamente la que H3 nombro: la ventana fuera
de muestra es una sola operacion. Los libros por activo lo confirman (con 2x fees BTC pasa a -14,68,
SOL a -90,10 y solo ETH se mantiene positivo, en 266,79), y VAL es plano. La regla de admision del propio WP coincide:
`INSUFFICIENT_EVIDENCE`. **Nada va a PAPER** y la tuberia de paper no se ha tocado.

## 4. Que pruebas fallan y por que

Ninguna prueba de esta cadena falla en el codigo final. El estado se midio, no se deduce del
codigo: 126/126 en los seis ficheros `test_edge01_*.py`, 3/3 en las tres regresiones de
recuperacion y `PASS` en el ensayo de checkout limpio (`closure/CLEAN_CHECKOUT_REHEARSAL.json`,
rehecho sobre el commit final y con 0 rutas publicadas movidas).

| prueba | estado | causa |
|---|---|---|
| `tests/unit/research/test_edge01_*.py` (6 ficheros) | **126 pasan / 0 fallan** | incluye las 12 nuevas del cierre |
| `test_state_view_is_deterministic` | **pasa** (antes fallaba) | vista de estado derivada regenerada y commiteada con sus fuentes |
| `test_repeated_reproduction_is_byte_identical` | **pasa** (antes fallaba) | idem; la auditoria economica ya era consistente |
| `test_the_clean_checkout_rehearsal_passes_on_this_commit` | **pasa** (antes fallaba) | el ensayo exige rutas cubiertas limpias: se cumple al commitear la revision regenerada |

Los tres fallos eran **del mecanismo, no de la evidencia**. Lo medido: la vista de estado publicada
(generada el 2026-10-11 a head `9b9a4b8a`) declaraba `e7bee5d8` mientras una reconstruccion en un
worktree limpio de HEAD produce `8bbd684d`. La vista es una funcion del commit y se lee desde
`git show HEAD:`: la unica reparacion honesta es regenerarla con su script y commitearla junto a las
fuentes que se movieron. No se ha editado ninguna prueba, no se ha tocado el JSON a mano y no se ha
reescrito evidencia historica: la revision anterior sigue en su commit y la divergencia queda
documentada en ADR-0031. Se verifico ademas que el pivote es estable (reconstruirla dos veces da el
mismo `payload_sha256`) para descartar que la vista se lea a si misma.

## 5. Commits locales y publicacion

- Los commits locales, con su sha y su asunto, estan listados en `closure/RUN_REPORT.json#commits` y
  en `git_sync_status.json#local.commits_created_by_this_wp`.
- La publicacion en GitHub sigue **bloqueada por credenciales** y se diagnostico otra vez desde cero
  tras los commits: `git push --dry-run` con `GIT_TERMINAL_PROMPT=0` devuelve
  `remote: No anonymous write access.` (exit 128). No hay `GITHUB_TOKEN`/`GH_TOKEN` en el entorno, no
  existe `~/.git-credentials`, no hay `gh` instalado y el helper configurado es `manager` (Git
  Credential Manager), que solo puede autenticar de forma interactiva. **No se ha leido, pedido,
  almacenado ni impreso ningun token.** El procedimiento exacto de desbloqueo esta en
  `closure/RUN_REPORT.json#push.unlock_procedure`.

## 6. Bloqueos y siguiente accion concreta

1. **Publicacion** (unico bloqueo de proceso): hace falta que el operador deje una credencial de
   escritura en su propia configuracion de git (helper con credencial almacenada o variable de
   entorno). Nada del WP depende de ello para ser auditable: la campana corre offline contra el
   corpus local y los verificadores leen solo los ficheros publicados.
2. **H6 es una mejora por operacion con participacion menor.** La siguiente pregunta util, con su
   propia regla congelada, es si una ventana de planificacion mas larga o una entrada parcial en el
   nivel convierte esa mejora por operacion en mejora de neto; y si los 183/686 rechazos del
   presupuesto en el toque son un problema de ejecucion o una proteccion trabajando (H5 ya mostro que
   ese presupuesto manda).
3. **La entrada no arregla la ruptura intradia**: con +0,3788 por operacion el neto sigue negativo.
   Antes de gastar mas ventanas en la entrada haria falta una razon para creer que el setup tiene
   bruto positivo en otra parte del embudo.
4. **El 4h tendencial no va a PAPER** por concentracion, no por signo. Volver a plantearlo exige una
   muestra OOS donde ninguna operacion concentre el neto (mas historia, mas activos, o un ruleset
   nuevo con su corrida pre-registrada), no un ajuste de parametros sobre la ventana ya leida.
5. **Limites de fondo, sin cambios**: solo DEV/VAL/OOS del corpus local, sin libro de ordenes
   historico, solo lado largo (spot), y ninguna conclusion autoriza capital real. No se declara
   `CERTIFIED` ni `PRODUCTION_READY`: no se cumple ningun gate para ello y no se ejecuta trading con
   capital real.

---

### Evidencia

| artefacto | contenido |
|---|---|
| `retest-h6/RETEST.json` y `RETEST.md` | las tres ramas, el destino de cada orden y el veredicto |
| `retest-h6/RETEST_TRADES.csv` | operaciones por rama, ventana y escenario |
| `retest-h6/RETEST_ORDERS.csv` | una fila por orden planificada, con su desenlace |
| `retest-h6/RETEST_SIGNALS.csv`, `RETEST_REFUSALS.csv` | senales con su plan y rechazos por motivo |
| `retest-h6/RETEST_VERIFICATION.json` | 15/15 comprobaciones, 19/19 mutaciones detectadas |
| `oos-trend-4h/OOS_TREND.json` y `OOS_TREND.md` | cartera, libros por activo, periodos, buy & hold y veredicto |
| `oos-trend-4h/OOS_TREND_TRADES.csv`, `OOS_TREND_ASSETS.csv`, `OOS_TREND_PERIODS.csv`, `OOS_TREND_REGIMES.csv`, `BUY_AND_HOLD.csv` | las cifras del informe, fila a fila |
| `oos-trend-4h/OOS_TREND_VERIFICATION.json` | 13/13 comprobaciones, 17/17 mutaciones detectadas |
| `RUN_REPORT.json`, `STRATEGY_RESULTS.json`, `TRADES.csv`, `INDEPENDENT_VERIFICATION.json` | la campana congelada y su verificacion (14/14) |
| `ablation-h1/`, `entry-timing-h2/`, `vol-filter-h4/`, `risk-budget-h5/` | las cuatro ablaciones, cada una re-anclada y verificada |
| `closure/RUN_REPORT.json` | registro del cierre: comandos, digests, veredictos, commits y bloqueo de push |
| `closure/CLEAN_CHECKOUT_REHEARSAL.json` | ensayo en checkout limpio del commit `af250f2` en esta sesion: `PASS`, 4/4 artefactos identicos, 0 rutas publicadas movidas |
| `closure/REPORT_FIGURES_CHECK.json` + `scripts/edge01_closure_report_check.py` | las 76 cifras de este informe, reformateadas desde los artefactos y exigidas literalmente en el texto: 76/76 |
