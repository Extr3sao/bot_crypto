# WP-EDGE-02 — Registro de ejecucion

| | |
|---|---|
| paquete de trabajo | `WP-EDGE-02` |
| HEAD al ejecutar | `cb94dd2` (sobre el cierre de WP-EDGE-01 `87f2357`) |
| rama | `agent/edge-recovery/WP-EDGE-00-baseline` |
| huella del paquete ahora (`_git_state`) | `c63b559f1d1cb5489741837e093e017d641f9595860c204789ad1ffeb2e897ac` |
| modo | backtest determinista y reconstruccion determinista sobre el corpus local: 0 ordenes, 0 credenciales, 0 llamadas de red (las unicas sondas de red son las de `git ls-remote`, registradas abajo) |
| veredictos | `INSUFFICIENT_EVIDENCE` (tendencia 4h) · `AUDIT_PASS` (rechazos de H6) |
| capital real | ninguno. No se declara `CERTIFIED` ni `PRODUCTION_READY` |

## 1. Que se ejecuto

| paso | comando | resultado |
|---|---|---|
| constructor 02A+02B | `python scripts/edge01_robustness_experiments.py --experiment all` | 8 + 7 artefactos, exit 0 |
| verificador independiente | `python scripts/edge01_wp02_verify.py --experiment all` | 21/21 comprobaciones en verde, exit 0 |
| auto-test del verificador | `... --self-test` | 10 sabotajes, 10 detectados, 0 sin detectar |
| pruebas | `pytest tests/unit/research/test_edge01_*.py -q` | **148 passed**, exit 0 (22 nuevas) |

El constructor y el verificador son procesos separados: `scripts/edge01_wp02_verify.py` **no importa nada de `trading_bot`**. Lee los artefactos publicados, el corpus local y los artefactos de WP-EDGE-01, reafirma las declaraciones congeladas y **reimplementa** los procedimientos estadisticos (tabla t y expansion de Cornish-Fisher, regla de lag de Newey-West, bootstrap de bloques con xorshift64* sembrado) en vez de importarlos.

## 2. WP-EDGE-02A — robustez de tendencia 4h

### 2.1 Reproduccion del cierre anterior

| campo | publicado por WP-EDGE-01 | recomputado | igual |
|---|---|---|---|
| operaciones OOS | 52 | 52 | si |
| neto OOS | 208,0056 | 208,0056 | si |
| expectativa OOS | 4,0001 | 4,0001 | si |
| mayor operacion / neto | 0,7987 | 0,7987 | si |

16 de 16 comparaciones iguales (`DEV:BASE`, `VAL:BASE`, `OOS:BASE`, `OOS:2X_FEES`). El ruleset congelado, el corpus, los componentes de coste y la politica de riesgo no se movieron.

### 2.2 Cartera por ventana y escenario

| ventana | escenario | ops | neto | expectativa | PF | drawdown | Sharpe | exposicion | mayor op / neto |
|---|---|---|---|---|---|---|---|---|---|
| DEV | BASE | 223 | 1.921,1792 | 8,6152 | 1,7782 | 4,2793% | — | 24,5997% | 0,0673 |
| VAL | BASE | 58 | 4,5253 | 0,0780 | 1,0068 | 4,1002% | — | 29,0259% | 27,5248 |
| OOS | BASE | 52 | 208,0056 | 4,0001 | 1,3312 | 2,5670% | 0,6658 | 19,4641% | **0,7987** |
| OOS | 2X_FEES | 52 | 160,6723 | 3,0899 | 1,2461 | 2,7025% | — | 19,4641% | 1,0267 |
| OOS | ADVERSE | 52 | 146,8908 | 2,8248 | 1,1926 | 2,7312% | — | 19,4641% | 1,1205 |

`ADVERSE` es el plano del propio arnes: fees x2 y slippage/impacto x3, derivado de los mismos componentes.

### 2.3 Sensibilidad: sin las k mayores ganadoras

| run | k=0 (base) | k=1 | k=3 | retirado en k=1 |
|---|---|---|---|---|
| `DEV:BASE` | 1.921,1792 | 1.791,8199 | 1.543,5448 | 129,3592 |
| `VAL:BASE` | 4,5253 | **−120,0341** | −266,0739 | 124,5594 |
| `OOS:BASE` | 208,0056 | **41,8740** | **−221,3291** | 166,1317 |
| `OOS:2X_FEES` | 160,6723 | −4,2921 | −264,9675 | 164,9644 |
| `OOS:ADVERSE` | 146,8908 | −17,7020 | −276,3397 | 164,5928 |

El libro OOS sobrevive a perder su mejor operacion (+41,87) pero no a perder tres (−221,33). En VAL el mismo libro ya es negativo quitando una sola operacion. Es la confirmacion cuantitativa del diagnostico de H3: la lectura esta concentrada, no distribuida.

### 2.4 Incertidumbre (95%)

| run | HAC | bootstrap | lag |
|---|---|---|---|
| `DEV:BASE` | [2,4224; 14,8079] | [2,7683; 14,3655] | 4 |
| `VAL:BASE` | [−10,4540; 10,6101] | [−9,4843; 10,6886] | 3 |
| `OOS:BASE` | **[−9,2735; 17,2738]** | [−6,7735; 15,6310] | 3 |
| `OOS:2X_FEES` | [−10,1570; 16,3367] | [−7,6606; 14,6925] | 3 |
| `OOS:ADVERSE` | [−10,3781; 16,0277] | [−7,8881; 14,4110] | 3 |

El intervalo OOS **contiene el 0** por los dos metodos. Solo DEV (la ventana de diseno) tiene un intervalo positivo, que no es evidencia fuera de muestra.

### 2.5 Contribucion en OOS

| libro / contexto | ops | neto | expectativa | win rate |
|---|---|---|---|---|
| BTC (libro propio) | 18 | 3,0607 | 0,1700 | 50,0000% |
| ETH (libro propio) | 16 | 281,6015 | 17,6001 | 43,7500% |
| SOL (libro propio) | 18 | −75,5490 | −4,1972 | 38,8889% |
| contexto `BULL` | 41 | 177,4313 | 4,3276 | 41,4634% |
| contexto `SIDEWAYS` | 4 | 89,4535 | 22,3634 | 75,0000% |
| contexto `BEAR` | 7 | −58,8791 | −8,4113 | 42,8571% |
| estado de tendencia `UP` (todos) | 52 | 208,0056 | 4,0001 | 44,2308% |

Por periodos: `2025H1` 24 ops +22,7467; `2025H2` 21 ops +244,1381; `2026Q1` 7 ops −58,8791.

### 2.6 Ajustado al riesgo (OOS, BASE)

| lectura | candidato | mejor buy & hold |
|---|---|---|
| retorno | 2,0801% | — |
| drawdown | 2,5670% | 73,2008% (SOL) |
| Sharpe anualizado | 0,6658 | — |
| MAR (neto / drawdown en capital) | 0,8103 | — |
| retorno / drawdown | 0,8103 | −0,5990 (BTC) |

El candidato bate a los tres buy & hold en retorno/drawdown en la misma ventana y el mismo plano de costes, con una utilizacion de capital mucho menor (19,46% de exposicion). Es la unica comparacion en la que la lectura es claramente favorable.

### 2.7 Periodos adicionales

- Ultima barra del corpus 4h: `2026-02-28T20:00:00+00:00`; fin de la ventana de diseno: `2026-02-28T00:00:00+00:00`.
- Barras sin usar: **5 por activo = 0,83 dias**, por debajo del minimo declarado de 30 dias.
- `additional_independent_periods_available`: **no**. Un periodo genuinamente nuevo exige corpus nuevo.

### 2.8 Veredicto

**`INSUFFICIENT_EVIDENCE`** — no se admite a PAPER. Fallos declarados: `concentration_within_limit` (0,7987 > 0,50) y, como lectura de intervalo, `hac_interval_upper_end_positive` pasa pero el intervalo contiene el 0 (`interval_reading`). Sin fallos decisivos. La regla de decision completa y la propuesta NO aplicada (criterio consciente del tamano) estan en `trend-robustness/ROBUSTNESS.json#experiment.decision_rule`.

## 3. WP-EDGE-02B — auditoria de los rechazos de riesgo de H6

### 3.1 Reproduccion

90 comparaciones (operaciones, neto, expectativa, ordenes, rellenos, fill rate) contra `RETEST.json`, todas iguales.

### 3.2 Reconstruccion de ordenes y rechazos (ventana primaria `DEV:BASE` / `plan_limit`)

| desenlace | ordenes |
|---|---|
| `filled` | 372 |
| `expired` | 128 |
| `refused_by_risk_budget` | **183** |
| `cancelled_window_end` | 3 |
| total | **686** |

Motivos de los 183: `risk_drawdown_halt` **148**, `risk_loss_cooldown` **35** (suma exacta, y coincide con el numero de ordenes con desenlace de rechazo).

### 3.3 Cada rechazo contra el estado reconstruido

| ambito | rechazos | justificados |
|---|---|---|
| ventana primaria | 183 | **183** |
| todas las ventanas y ramas (DEV/VAL/OOS x BASE/2X_FEES x 3 ramas) | 2.734 | **2.734** |
| a mas de 0,02 puntos porcentuales del umbral | 0 | — |

El estado NO se toma de la captura del auditor: se reconstruye desde el corpus 15m y el libro de operaciones publicado, barra a barra, en un proceso aparte. La curva de capital reconstruida coincide con la publicada en **26.113 de 26.113 barras**.

### 3.4 Invariantes

150 filas (10 invariantes x 15 ambitos rama/ventana), **0 fallos**. Incluye contabilidad (`10.000,00 − 495,8756 = 9.504,1244`), caja no negativa, sizing contra el 0,25% configurado, topes de notional por orden (500) / activo (10%) / total (25%), minimo (20), limite de 3 posiciones y de 20 operaciones diarias, un desenlace por orden, atribucion del motivo y ausencia de duplicados `(activo, instante, motivo)`.

### 3.5 Comparacion con el Risk Engine real

| | |
|---|---|
| misma regla dispara en runtime | 2.734 / 2.734 |
| reglas del runtime que el presupuesto de investigacion NO modela | kill switch, limite de perdida diaria, limite semanal, drawdown diario, bloqueo de fin de semana, bloqueo de spread, bloqueo de ATR |
| consecuencia | en vivo el mismo libro se bloquearia **al menos** igual, nunca menos |
| limites modificados | ninguno (comparados uno a uno con `config/risk.yaml`: 8/8 iguales) |

### 3.6 Veredicto

**`AUDIT_PASS`** — los 183 rechazos son correctos, no hay errores de accounting, ni estado obsoleto, ni rechazos duplicados. Son el halt del 5% y el cooldown de 3 perdidas haciendo su trabajo sobre un libro que pierde dinero.

## 4. Defecto encontrado y corregido

| | |
|---|---|
| id | `DEF-EDGE02-01` |
| donde | `src/trading_bot/research/edge01/risk_audit.py`, el envoltorio observador |
| sintoma | la primera corrida falló 15 filas de invariantes, todas `notional_at_or_above_minimum` con notional 0 |
| causa | el observador leia el mapping de posiciones con `positions or {}`; un dict vacio pero VIVO es falsy, asi que un dict nuevo lo sustituia y una entrada tomada con el libro plano perdia su propio tamano |
| arreglo | leer el mapping por identidad y sustituirlo solo si falta; despues, 150/150 invariantes |
| prueba de regresion | `tests/unit/research/test_edge01_wp02_robustness.py::test_observer_reads_a_live_but_empty_positions_mapping` |

Lo encontraron los propios invariantes de entrada del experimento, no una revision posterior: es el argumento a favor de declararlos antes de correr.

## 5. Verificacion independiente

| experimento | comprobaciones | resultado |
|---|---|---|
| tendencia | 9 | **9/9 en verde** |
| riesgo | 12 | **12/12 en verde** |
| auto-test | 10 sabotajes | **10 detectados, 0 sin detectar** |

Los sabotajes del auto-test (y la comprobacion que debe romper cada uno): mover el neto OOS, ensanchar el intervalo de bootstrap, declarar positivo un leave-out negativo, borrar la mayor operacion, promover un run que la regla rechaza, inventar un rechazo en un instante sin barra, cambiar el desenlace de una orden, blanquear un rechazo con un cooldown inexistente, invertir un invariante, y declarar `AUDIT_PASS` con artefactos que no lo sostienen.

## 6. Artefactos

| fichero | bytes | sha256 (16) |
|---|---|---|
| `h6-risk-audit/RISK_AUDIT.json` | 45782 | `b07565d2d5ab6073` |
| `h6-risk-audit/RISK_AUDIT.md` | 22935 | `d46a77fb5854f926` |
| `h6-risk-audit/RISK_AUDIT_EQUITY.csv` | 757924 | `86c8789280e3db1d` |
| `h6-risk-audit/RISK_AUDIT_INVARIANTS.csv` | 14809 | `f4020f34e2a18741` |
| `h6-risk-audit/RISK_AUDIT_ORDERS.csv` | 357066 | `daec77ace2bf83b4` |
| `h6-risk-audit/RISK_AUDIT_PRIMARY_REFUSALS.csv` | 61315 | `8a6ea8978951984d` |
| `h6-risk-audit/RISK_AUDIT_REFUSALS.csv` | 903008 | `477d6e327961ca89` |
| `trend-robustness/ROBUSTNESS.json` | 3360259 | `9915f017659b2dd4` |
| `trend-robustness/ROBUSTNESS.md` | 12138 | `20a919acf444db97` |
| `trend-robustness/ROBUSTNESS_CONTRIBUTION.csv` | 2852 | `c7660da87d09082b` |
| `trend-robustness/ROBUSTNESS_LEAVE_OUT.csv` | 1121 | `069d7ab862acc6f1` |
| `trend-robustness/ROBUSTNESS_RISK_ADJUSTED.csv` | 717 | `b667abafb69702a2` |
| `trend-robustness/ROBUSTNESS_UNCERTAINTY.csv` | 683 | `c00bd60a69b23b71` |
| `trend-robustness/ROBUSTNESS_WINDOWS.csv` | 866 | `eb7440d01c76cb9f` |
| `trend-robustness/TREND_TRADES.csv` | 300292 | `6443e42b85b557c3` |
| `VERIFICATION.json` | 4504 | `d43b3439c8e97674` |

Los digests completos estan en `RUN_REPORT.json#artifacts`.

## 7. Procedencia del codigo congelado

- Los **9 modulos del paquete que WP-EDGE-01 midio** quedan **byte a byte identicos** (comparacion directa fichero a fichero contra `source_digest.files` del artefacto OOS).
- **Anadidos**: `robustness.py`, `risk_audit.py`. Ningun otro cambio en el paquete.
- **Ningun script ni artefacto de WP-EDGE-01 editado**: `git status` sobre los cuatro scripts da vacio, y el ultimo commit que toca cada uno es de WP-EDGE-01 (`46b72fd`, `ab7be9c`, `90cee73`).
- La huella `616a86fa…` que registra el artefacto OOS **no se puede recomputar desde ningun commit**: el artefacto la tomo con `worktree_dirty = True`, o sea que identifica el ARBOL que corrio, no un commit. Lo que si es comprobable y se comprueba es la comparacion por fichero de arriba.
- Los dos modulos nuevos **no** se registran en `edge01/__init__.py` a proposito: seria cambiar uno de los nueve ficheros congelados por un motivo puramente cosmetico y dejaria de ser comparable la huella del paquete de las lineas congeladas.

## 8. Commits

| sha | asunto |
|---|---|
| `cb94dd2` | Stress the frozen 4h trend reading and audit H6's 183 risk refusals. [WP-EDGE-02] |

`WP-EDGE-02` aporta 1 commit sobre `87f2357` (que deja el arbol 19 commits por delante de la base `4be09fb`). El commit incluye codigo, verificador, pruebas, artefactos, el ADR-0032 y la excepcion de `.gitignore` que versiona esta evidencia.

## 9. Publicacion — `BLOCKED_GITHUB_AUTH`

| sonda | exit | resultado |
|---|---|---|
| `GIT_TERMINAL_PROMPT=0 git push --dry-run` | 128 | la rama no tiene upstream: no se intento ninguna escritura remota |
| `... git push --dry-run origin HEAD:refs/heads/agent/edge-recovery/WP-EDGE-02` | 124 | **se cuelga**: el helper configurado (`manager`, Git Credential Manager) abre su propio dialogo, que `GIT_TERMINAL_PROMPT` no suprime; cortado a los 60 s |
| `... git -c credential.helper= push --dry-run origin HEAD:...` | 128 | `fatal: could not read Username for 'https://github.com': terminal prompts disabled` |
| `GIT_TERMINAL_PROMPT=0 git ls-remote --heads origin` | 0 | lectura anonima OK: 61 ramas; `refs/heads/agent/edge-recovery/*` sigue **vacio** |

No hay `GITHUB_TOKEN`/`GH_TOKEN` en el entorno, no hay `~/.git-credentials`, no hay `gh` instalado y el helper es el interactivo. **No se ha leido, pedido, almacenado ni impreso ningun token.** El procedimiento exacto de desbloqueo (9 pasos, con cuatro vias alternativas y su comprobacion) esta en `RUN_REPORT.json#push.unlock_procedure`.

## 10. Limites

- El ruleset de tendencia ya se leyo en VAL y OOS dentro de WP-EDGE-01: esto es un analisis de sensibilidad y descomposicion de una corrida publicada, no una segunda muestra independiente.
- El criterio de concentracion es el 0,50 que congelo WP-EDGE-01; relajarlo es una propuesta de experimento nuevo y no se aplica aqui.
- El corpus congelado termina en la ultima barra del OOS (5 barras de barrido, 0,83 dias, por debajo del minimo declarado de 30 dias): no hay periodo independiente sin usar.
- El presupuesto de riesgo de investigacion modela un subconjunto de las reglas del runtime: el veredicto de la auditoria es sobre ese subconjunto.
- La auditoria observa el propio camino de entrada del simulador congelado en el mismo proceso; el estado independiente lo reconstruye un proceso aparte desde el corpus y el libro de operaciones.
- Solo lado largo (spot); sin libro de ordenes historico; ningun capital en riesgo.
