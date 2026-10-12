# WP-EDGE-02 — Informe final

**Veredictos: `INSUFFICIENT_EVIDENCE` (tendencia 4h, no pasa a PAPER) · `AUDIT_PASS` (los 183 rechazos de H6 son correctos).**
**No se declara `CERTIFIED` ni `PRODUCTION_READY`. No se ha activado ni se activa trading con dinero real.**

Base: HEAD `cb94dd2`, sobre el cierre de WP-EDGE-01 (`87f2357`). Todo lo que sigue esta en los artefactos de esta carpeta y lo recomputa un proceso aparte que no importa el paquete.

---

## 1. Que gana y que pierde, en DEV y fuera de muestra

| libro | DEV | VAL | OOS | veredicto |
|---|---|---|---|---|
| `edge_intra_01` (raices intradia) | −496,4298 | −479,1833 | −94,8077 | `REJECT` |
| `edge_intra_02` | −189,8769 | — | — | `REJECT` |
| `edge_intra_02_no_fvg` | −500,8327 | — | — | `REJECT` |
| `edge_intra_01r` plan limit (H6) | −495,8756 | −357,4437 | −55,7068 | mejora la expectativa, sigue perdiendo |
| `edge_trend_01` 4h | **+1.921,1792** | +4,5253 | **+208,0056** | `INSUFFICIENT_EVIDENCE` |
| `edge_trend_01` 4h con coste adverso | — | — | +146,8908 | mismo veredicto |

**Gana**: solo el libro tendencial 4h, y solo en DEV con claridad. Fuera de muestra anota +208,01 USDT en 52 operaciones, y sigue positivo cuando el coste se estresa (2x fees +160,67; fees x2 y slippage/impacto x3 +146,89) y cuando se le quita su mejor operacion (+41,87).

**Pierde**: la ruptura intradia, en todas sus variantes, en las tres ventanas. Al quitarle al libro tendencial OOS sus **tres** mayores ganadoras pasa a **−221,33**, y en VAL basta quitar **una** para dejarlo en −120,03: la lectura positiva esta concentrada, no distribuida. El intervalo de confianza del 95% sobre la expectativa OOS ([−9,27; 17,27] por Newey-West, [−6,77; 15,63] por bootstrap de bloques) **contiene el 0** por los dos metodos. Por activo, el OOS lo carga ETH (+281,60 en libro propio) mientras BTC queda plano (+3,06) y SOL pierde (−75,55).

## 2. Mejora H6 realmente la expectativa neta?

**Si, y esta medido.** El plan de retest (misma senal congelada, misma parada, mismo objetivo, mismo presupuesto, mismos costes; solo cambia el precio de entrada) pasa de −1,7118 a **−1,3330 USDT por operacion** en DEV (+0,3788, un 22% mejor), con el brazo de control `plan_market` reproduciendo el libro congelado **exactamente** (−496,4298 / −1,7118). La mejora se repite fuera de la ventana de diseno: VAL +121,74 y OOS +39,10.

**Pero no lo vuelve rentable.** El neto absoluto sigue negativo porque el plan rellena menos operaciones (372 de 686 ordenes; 54,23%), y una mejora por operacion que reduce la participacion deja el neto plano. Este WP anade el dato que faltaba: **de las 183 ordenes que llegaron al nivel y fueron rechazadas, 148 las bloqueo el halt de drawdown del 5% y 35 el cooldown de 3 perdidas — y las 183 son correctas.** No hay un error de ejecucion escondido detras de la falta de participacion: el libro pierde dinero, y el presupuesto de riesgo esta haciendo su trabajo.

## 3. Merece la tendencia 4h pasar a PAPER?

**No.** La regla de robustez congelada de nueve criterios falla uno declarado —el de concentracion: la mayor operacion es el **0,7987** del neto OOS contra el limite **0,50** que fijo WP-EDGE-01, que este WP **no relaja**— y la incertidumbre no permite afirmar una expectativa positiva (el intervalo contiene el 0).

Lo que **si** pasa: neto positivo en BASE y en los dos planos de coste estresados, 52 operaciones (por encima del suelo de 30), 2 de 3 libros por activo positivos, 2 de 3 periodos positivos, drawdown del 2,57% frente al 73,20% del buy & hold mas profundo, y mejor retorno/drawdown que los tres buy & hold (0,8103 frente a −0,5990 del mejor de ellos) con solo un 19,46% de exposicion. Nada se promociona: la tuberia de paper no se toco.

**Propuesta, no aplicacion**: un criterio de concentracion consciente del tamano (por ejemplo medido contra la suma de las k mayores ganadoras o contra el beneficio bruto) es un experimento **nuevo** con su propia pre-registracion, y esta registrado como propuesta en `ROBUSTNESS.json#experiment.decision_rule.proposal_not_applied`. Aplicarlo aqui para que este libro pase es exactamente lo que este WP se prohibe.

## 4. Que tests fallan y por que

**Ninguno.** Los tres fallos del workstream de recuperacion quedaron resueltos en WP-EDGE-01 (reparando el mecanismo: la vista de estado se regenero con su script y se commiteo con sus fuentes, ADR-0031) y siguen verdes. En este WP:

- `pytest tests/unit/research/test_edge01_*.py -q` → **148 passed**, exit 0 (22 nuevas en `test_edge01_wp02_robustness.py`).
- El verificador independiente: **9/9** (tendencia) y **12/12** (riesgo) en verde, exit 0.
- El auto-test del verificador: **10 sabotajes, 10 detectados, 0 sin detectar**.

Un defecto **si** aparecio y esta corregido, con prueba de regresion: `DEF-EDGE02-01`. El envoltorio observador leia el mapping de posiciones con `positions or {}`, y un dict vacio pero vivo es falsy: una entrada tomada con el libro plano perdia su propio tamano. Lo detectaron los **propios invariantes de entrada** en la primera corrida (15 filas `notional_at_or_above_minimum` con notional 0), no una revision a ojo. Es el argumento que justifica declararlos antes de correr.

## 5. Commits locales y publicacion

| sha | asunto |
|---|---|
| `cb94dd2` | Stress the frozen 4h trend reading and audit H6's 183 risk refusals. [WP-EDGE-02] |
| `f886e53` | Record the WP-EDGE-02 closure: verdicts, refusals, digests and the blocked push. [WP-EDGE-02] |
| `6070806` | Record that a full re-run reproduces the WP-EDGE-02 tables byte for byte. [WP-EDGE-02] |

Tres commits de este WP sobre `87f2357`: codigo, verificador, pruebas, artefactos, ADR-0032 y la excepcion de `.gitignore` que versiona esta evidencia; el registro de ejecucion y este informe; y la reproducibilidad byte a byte de una segunda corrida completa. Medido al escribirse esta correccion (`git rev-list --count 4be09fb..HEAD`): **23 commits** por delante de `4be09fb`, mas el commit que lleva la correccion.

**Publicacion: `BLOCKED_GITHUB_AUTH`, no verificada.** Se sono de nuevo desde cero y con refspec explicito:

- la rama no tiene upstream (`exit 128`), asi que un `git push` normal ni llega al remoto;
- con el refspec explicito el push **se cuelga**: el helper `manager` (Git Credential Manager) abre su propio dialogo, que `GIT_TERMINAL_PROMPT=0` no suprime (`exit 124` al cortar a los 60 s);
- con el helper desactivado falla rapido: `fatal: could not read Username for 'https://github.com': terminal prompts disabled` (`exit 128`);
- la lectura anonima funciona (61 ramas) y `refs/heads/agent/edge-recovery/*` sigue **vacio**.

No hay token en el entorno, no hay `~/.git-credentials`, no hay `gh`. **No se ha leido, pedido, almacenado ni impreso ningun token**; el procedimiento exacto de desbloqueo (9 pasos, con cuatro vias alternativas y su comprobacion) esta en `RUN_REPORT.json#push.unlock_procedure`. Los commits locales quedan intactos.

## 6. Bloqueos y siguiente accion concreta

1. **Push bloqueado por credenciales** (arriba). Solo lo desbloquea un operador: token con permiso de escritura en `Extr3sao/bot_crypto`, o `gh auth login`, o el helper interactivo una sola vez. Afecta tambien a WP-EDGE-01, cuyos commits siguen sin publicar.
2. **La concentracion del 4h es el bloqueo real de la investigacion**, no el numero de operaciones. La siguiente accion concreta: un experimento **nuevo y pre-registrado** que fije un criterio de concentracion consciente del tamano (declarado antes de medir, con la misma muestra OOS) y, en paralelo, un candidato que no dependa de una sola operacion: menos exposicion a un activo (ETH carga el 135% del neto OOS mientras SOL resta) o un filtro de participacion por regimen (`BEAR` es el unico contexto negativo: −58,88 en 7 operaciones).
3. **Un periodo genuinamente nuevo exige corpus nuevo.** El corpus 4h congelado termina en la ultima barra del OOS (5 barras de barrido, 0,83 dias). La feed de 15m llega a 2026-10-07, asi que hay material para 2026-03 → 2026-10, pero construir un 4h desde 15m es un corpus distinto por diseno y tiene que entrar como experimento nuevo con su propia declaracion, no como una extension retroactiva de este.
4. **La auditoria de riesgo cierra la pregunta de la ejecucion, no la de la estrategia.** Con los 183 rechazos justificados, la unica via para dar participacion al libro intradia es un ruleset que no pierda dinero mientras el halt del 5% esta activo; relajar el halt o el cooldown esta descartado por este WP.

**No declarado**: `CERTIFIED`, `PRODUCTION_READY`, rentabilidad, o cualquier autorizacion de capital. Los numeros son DEV/VAL/OOS sin libro de ordenes historico, solo lado largo (spot).
