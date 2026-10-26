# FINAL REPORT — TAP-INTEGRATION-ADMISSION-002 (cierre de integración + recuperación de admisión)

**Worktree:** `ff-wt-adm002`
**Branch:** `admission/integration-002`
**Base auditada:** `main` = `e67194e7` (intacta; el verificador lo comprueba antes y después)
**Fecha (UTC):** 2026-10-25
**Continuación de:** la entrega anterior en `55f991b7` (mismo informe, ahora con el gate recalculado sobre este árbol)

---

## 0. Las cinco respuestas, separadas

| Estado | Veredicto | Qué lo sostiene | Qué falta |
| --- | --- | --- | --- |
| `INTEGRATION_STATUS` | **PARTIAL — GO local, NO_GO en runner** | gate recalculado en `76e8ec0b`: **15/15 pasos**, `false_success 0`, manifiesto de 258 ficheros; verificador independiente 15/15; rama publicada y PR **#18** abierto; los cuatro workflows se ejecutaron de verdad y **fallan**, con causa raíz identificada en cada uno (§1.8) | un runner con feed de mercado para que el gate pueda certificar, y sacar CI Baseline de su deuda heredada |
| `GOVERNANCE_STATUS` | **BLOCKED** | G1 sigue `OPEN_SIGNOFF`; branch protection ilegible (401, sin `gh`); el workflow se declara voluntario | firma del risk-manager y toggle del administrador |
| `PAPER_RUNTIME_STATUS` | **PARTIAL (más fuerte que en la entrega anterior)** | sesión real de **7 ciclos** en mercado abierto: 45 decisiones, 9 aprobaciones, **2 fills PAPER abiertos** (BTC long, ETH short), reconciliación completa, 0 órdenes live; el domingo la misma lane daba 0 fills por `WEEKEND_BLOCK`, así que el bloqueo era de calendario y no de motor | un **cierre** de trade en vivo (hoy: 2 posiciones abiertas, 0 cerradas) y `strategy_id` propagado (B10) |
| `STRATEGY_ADMISSION_STATUS` | **NO_GO** | 0 de 24 admitidas; las 24 se reclasifican por aritmética, no por etiqueta: 17 `NO_GROSS_EDGE`, 7 `COST_KILLED` | una estrategia que supere el suelo de costes |
| `PROFITABILITY_EVIDENCE_STATUS` | **NEGATIVE** | mejor bruto medido 8.912 bps/operación contra 12.177 bps (línea observada más barata) y 23.354 bps (línea del runtime); 0 celdas alcanzan cualquiera de las dos | un mecanismo cuyo bruto supere el suelo **antes** de hablar de fills |

`FALSE_SUCCESS = 0` en los tres artefactos de verificación. `BUILDER != VERIFIER`: `tools/admission_verify.py` y
`tools/strategy_economics.py` no importan el código que construyó el gate ni la auditoría económica.

---

## 1. WP-01 — Cierre de integración

### 1.1 Commits

| Commit | Contenido | Estado |
| --- | --- | --- |
| `55f991b7` | punta de la entrega anterior | base |
| `9ece4b0e` | versiona la auditoría y cierra la fuga de `__pycache__` | local |
| `600e744d` | A8 (certificado PAPER atado a HEAD) + S3, y el gate recalculado | local |
| `b633ecce` | reparación de bytes RFC-048 (dos tests rojos → verdes) | local |
| `9d622bb5` | A9 (recomputación del gate como artefacto) + S4 + economía de las 24 | local |

Ningún commit fusiona, cherry-pickea ni reescribe la lane `audit/supervisor-integration-001`. `main` no se toca.
`git rev-list --merges main..HEAD` sigue vacío.

### 1.2 Defectos encontrados y cerrados en este pase

1. **La carpeta de la auditoría estaba ignorada y el árbol se declaraba limpio.** `reports/ai-bots/*` se ignora en bloque;
   la negación se abre nivel a nivel. **Efecto colateral nuevo:** esa negación ganaba al `__pycache__/` del repo
   (*last match wins*), así que un `.pyc` del verificador iba a entrar en el commit. Se vuelve a cerrar justo debajo, y
   `git add -An` lo confirma: 23 ficheros de evidencia, ninguno de caché.
2. **Los payloads RFC-048 no eran los bytes que `PROVENANCE.json` certifica.** Seis descargas se cometieron con LF
   mientras la procedencia registró los bytes CRLF: `bracket_provenance` fallaba en las 28 decisiones y
   `tests/unit/risk/test_futures_independent_verifier.py` tenía **2 tests rojos en árbol limpio**. Añadir un CR por
   línea reproduce el `sha256` **y** el tamaño registrados exactamente (no se adivina: se reconstruye), y
   `data/rfc048/raw/** -text` impide que git lo normalice otra vez, igual que ya se hace con `data/rfc049/**` y
   `data/recovery/wp7|wp8/evidence/**`. Resultado: 8/8 tests verdes.
3. **El verificador dependía de la configuración de checkout (cerrado).** `core.autocrlf` pasó a `true` en el
   `.git/config` compartido durante este pase — no lo cambió esta auditoría, y por eso queda registrado en vez de
   corregido en silencio. A3 y A6 crean un worktree del commit que certificó la evidencia; con `autocrlf=true` git
   reescribe los seis scripts al extraerlos, los seis hashes del contrato dejan de cuadrar y `verify` falla por un
   motivo que no tiene nada que ver con el commit juzgado. El verificador fija ahora `core.autocrlf=false` y
   `core.eol=lf` en ese único comando: juzga blobs, no la máquina que los lee. **Sin ese pin, A3 y A6 salían rojos con
   la evidencia intacta**, que es la peor clase de rojo: el que enseña a ignorar el rojo.

4. **El verificador contaba mal los fills cuando había fills.** A10 comparaba `summary.fills` con el número de
   filas `FILL` de todos los ledgers de ciclo, pero cada ledger lista **todas** las posiciones abiertas al final de
   su ciclo: una entrada de BTC aparecía en cinco ledgers y el verificador contaba 9 filas para 2 posiciones. La
   sesión del domingo tenía 0 fills y el error era invisible. Se cierra contando `position_id` distintos por
   `phase` (`OPEN_ENTRY`/`CLOSE_EXIT`) y S5 se reapunta al mensaje nuevo para que un `summary` que se atribuya un
   fill de más siga haciendo fallar A10 (`tampered fills judged=FAIL`). **No se relajó la comprobación**: se cambió
   la unidad de cuenta a la que el artefacto realmente usa.

### 1.3 Credenciales y alcance

Barrido sobre los 286 ficheros de `reports/ai-bots/TAP-INTEGRATION-ADMISSION-002/` (5,6 MB): AWS, GitHub tokens,
PEM privadas, `Bearer`, pares `*_API_KEY|SECRET` y asignaciones largas → **0 coincidencias**. Fuera del alcance de esta
auditoría no se tocó nada; los cambios son la carpeta de evidencia, `.gitignore`, `.gitattributes` y los seis payloads
RFC-048 que los tests exigen.

### 1.4 Gate recalculado

No se reutiliza el `PASS` de `9a420ff1`: se volvió a ejecutar el gate sobre este árbol, dos veces.

| Ejecución | Commit | Resultado | Evidencia |
| --- | --- | --- | --- |
| intermedia | `600e744d` | `PASS` 15/15, `false_success 0`, manifiesto 260 | `evidence/gate_at_600e744d/` |
| anterior | `9d622bb5` | `PASS` 15/15, `false_success 0`, manifiesto 260 | `evidence/gate_at_9d622bb5/` |
| **esta entrega** | **`76e8ec0b`** | **`PASS` 15/15**, `false_success 0`, manifiesto **258**, 1.336 s | `evidence/gate_at_76e8ec0b/` |

Las dos corrieron con el árbol limpio y con `--out` fuera del repositorio (el gate se niega a escribir dentro del árbol
que juzga). La ejecución de esta entrega corresponde a la punta ejecutable `76e8ec0b`: `git diff --name-only 76e8ec0b
HEAD` sólo puede tocar `reports/`, y el verificador lo comprueba (A9, `executable_delta = 0`).

### 1.5 Verificador independiente

`tools/admission_verify.py` — 15 claims, `verdict PASS`, `false_success 0`:

| Claim | Qué prueba |
| --- | --- |
| `A1` | la rama del informe es la del disco y `main` es ancestro sin merges |
| `A2` | los manifiestos de GATE-001 siguen describiendo los ficheros (525 hashes) |
| `A3` | el informe del gate es una pasada de este código y `verify` la re-deriva |
| `A4` | la sesión PAPER ejecutó ciclos, no dejó locks y no envió órdenes live |
| `A5` | el ledger de admisión no admite ninguna estrategia |
| `A6` | el check rechaza evidencia manipulada y acepta la entregada |
| `A7` | la clausura de imports del runtime está completa (338 módulos, 2.435 imports, 0 sin resolver) |
| `A8` | el runtime grabado por la sesión PAPER es el de HEAD (14 hashes vía `git show HEAD:`) y el delta desde que corrió no toca nada ejecutable (`executable_delta = 0`) |
| `A9` | el gate se recalculó en `76e8ec0b`, pasó los 15 pasos, no cambió la política de riesgo, y su manifiesto se re-hashea (258/258) |
| `A10` | la sesión larga corrió en vivo, llegó al risk gate, no envió una orden live, y el número de fills del resumen coincide con las **posiciones distintas** de los ledgers (no con las filas, que son acumulativas) |
| `S1`–`S5` | autocontroles: romper la cadena hace fallar A4, admitir una estrategia hace fallar A5, mover un hash de runtime o un delta ejecutable hace fallar A8, editar el manifiesto hace fallar A9, y atribuirse un fill de más hace fallar A10 |

Los cuatro autocontroles existen porque un verificador que no puede fallar no verifica: cada uno muta el artefacto y
exige el `FAIL`.

### 1.6 Compatibilidad con `origin/main`

- `git fetch origin main` → `origin/main` = `5e6f9632`, **sin commits nuevos** en el remoto.
- `git merge-base --is-ancestor origin/main HEAD` → **sí**. `HEAD..origin/main = 0`; `origin/main..HEAD = 280`.
- `git merge-tree --write-tree origin/main HEAD` devuelve **exactamente** el árbol de `HEAD`
  (`70a4df2f…`): integrar es un no-op, no hay conflictos que resolver ni ficheros que cambien.
- Con la `main` local (`e67194e7`): merge sin conflictos, también árbol idéntico.
- **Consecuencia que hay que decir en voz alta:** un PR a `main` no entregaría esta auditoría sola, entregaría **280
  commits** (los 263 que la `main` local ya tenía por delante del remoto más los 17 de esta rama). El PR #18 lo
  confirma: 279 commits y 2.782 ficheros en el diff. Es una decisión de gobernanza, no un detalle de integración.

### 1.7 Tests sobre el resultado integrado

Subconjunto que fija el código migrado (paper, risk, ops de lock, visión causal y sesión):

```
.venv/Scripts/python.exe -m pytest tests/unit/paper tests/unit/risk \
  tests/unit/ops/test_single_writer_lock.py tests/unit/ops/test_paper_lock_campaign.py \
  tests/unit/ops/test_session_status.py tests/unit/vision/test_closed_trade_cycle.py \
  tests/unit/vision/test_causal_execution.py tests/unit/vision/test_prospective_session.py \
  tests/unit/vision/test_session_lock_recovery.py tests/unit/vision/test_session_provenance.py -q
```

| Momento | Resultado |
| --- | --- |
| antes de la reparación RFC-048 | **2 failed, 317 passed** (`bracket_provenance`, 28/28 decisiones) |
| después de la reparación RFC-048 | `319 passed, 0 failed` (exit 0, 4 min 17 s) |
| **después del falso éxito y de las sesiones nuevas (`76e8ec0b`)** | **`320 passed, 0 failed`** (exit 0, 4 min 0 s) |

La suite completa `pytest tests/unit` no se ejecuta aquí (subconjuntos ya tardan >3,5 min en esta máquina y la suite
completa >27 min); se declara en §7 en vez de presentarla como corrida.

### 1.8 Publicación y GitHub Actions (lo que dijo el runner, no el banner)

La rama se publicó y el PR quedó abierto: **#18**, `admission/integration-002` → `main`, `mergeable: true`,
`mergeable_state: unstable`. GitHub ejecutó **cuatro workflows** sobre el resultado del merge
(`1b42bca3`, `refs/pull/18/merge`) y **los cuatro terminaron en `failure`**. No se declara ninguno verde:

| Workflow | Run | Conclusión | Dónde falla |
| --- | ---: | --- | --- |
| Integration gate | `40219499778` | `failure` | preflight **PASS**; job del gate: `C1`, `A1`, `J1`, `J2`, `J3`, `J4`, `J5`, `M1`, `V2` y la revisión independiente |
| recovery-determinism | `40219499708` | `failure` | `test_active_recovery_wp.py` y `test_recovery_determinism.py` (3 tests) |
| Cost-barrier drift gate | `40219499649` | `failure` | *Certification record* (exit 4) y *Keep the evidence* (no había `.ci/`) |
| CI Baseline | `40219499648` | `failure` | Ruff, Mypy, pip-audit y smoke PR-pipeline; `tests-and-coverage` cancelado por el fail-fast |

#### 1.8.1 El gate se negó a certificar, y dijo por qué

`GATE_REPORT.json` del artefacto `integration-gate-evidence`: `verdict FAIL`, 15 pasos → **4 PASS, 9 FAIL,
2 NOT_TESTED, 0 BLOCKED**, `false_success 0`, manifiesto de **44** ficheros. El gate **no** aprobó nada; el
`FAIL` es correcto. La causa raíz de los nueve pasos es una: **el runner no tiene feed de mercado**. La frase
está en el log del entrypoint, no inferida:

```
[wp04] BLOCKED — no cycle could be executed on the live feed
```

Lo que se midió a partir de ahí:

- `C1_SUPERVISOR_CAMPAIGN` **FAIL a los 420.9 s**, que es el `--wait-cycle-timeout-s` de la propia campaña (no un
  timeout del gate): sin un ciclo no hay campaña. Por eso `C2` (escenarios) y `V1` (verificador del supervisor)
  quedan `NOT_TESTED`, `J1` no encuentra su informe, y `M1` no encuentra `SUPERVISOR_VERIFICATION.json`.
- `C3_LOCK_CAMPAIGN` **salió 0 con `{"iterations": 1, "cycles": [], "locks": 0}`**, y `J5` lo delató
  (`iterations=1 races=0 sites=['None']`). Sobre una campaña vacía, `J2` sólo pudo detectar **1 de 9** mutaciones.
  Es decir: el **único falso éxito del runner estaba en el código de salida de la campaña**, no en el veredicto
  del gate, que siguió siendo `FAIL`.
- La revisión independiente (`review_gate.py`) ni siquiera pudo correr sus controles: la mutación que borra
  `iteration-03/RECOVERY.json` lanzó `FileNotFoundError` porque la campaña murió en la iteración 1. El paso falla
  cerrado, pero el diagnóstico se pierde detrás de un traceback.

#### 1.8.2 El falso éxito, cerrado con código y con test

`scripts/paper_lock_campaign.py` devolvía `0` cuando el estado final era `RECOVERED` **o `READY`** — y `READY`
es exactamente lo que reporta un directorio de sesión vacío. Un feed bloqueado, un `NO_SESSION_START` y una
campaña completa de seis crash sites eran indistinguibles por el exit code. Ahora:

- el resumen imprime `failures` y `requested_iterations`;
- `CAMPAIGN.json` registra `failures`;
- el exit code exige **todos** los crash sites pedidos, **ninguno** con `failure`, y un estado final sano;
- `tests/unit/ops/test_paper_lock_campaign.py::test_a_blocked_feed_cannot_exit_zero` reproduce el camino del
  runner (stream vacío → `READY`) y exige `1`.

Commit **`76e8ec0b`**. El gate completo se volvió a correr después del cambio, sobre el árbol limpio de ese
commit: **PASS 15/15**, `false_success 0`, 1.336 s, manifiesto de 258 ficheros (`evidence/gate_at_76e8ec0b/`).
Las seis iteraciones de la campaña de locks corrieron sin `failure`, así que el camino sano no se rompió al
endurecer el código de salida.

#### 1.8.3 CI Baseline nunca estuvo verde: la deuda es anterior a esta rama

No es una regresión de este trabajo, y se puede demostrar con los mismos comandos sobre el commit base:

| Comprobación | `origin/main` = `5e6f9632` | base `e67194e7` | rama `76e8ec0b` |
| --- | ---: | ---: | ---: |
| ficheros `.py` versionados | **239** | 818 | 894 |
| `ruff format --check .` | 0 ficheros | **444 ficheros** | 484 ficheros |
| `mypy .` | verde (239 ficheros) | **297 errores / 38 ficheros** | 343 errores / 50 ficheros |

- **`origin/main` está 263 commits por detrás de la `main` local** y su CI verde de septiembre se ejecutó sobre
  un árbol de 239 ficheros. El "baseline" que GitHub considera `main` no es el árbol sobre el que se construyó
  esta auditoría; el PR #18 lo enseña en su propio diff: **279 commits y 2.782 ficheros**.
- Los **484** ficheros que Ruff reformatearía incluyen los 444 que ya fallaban en el commit base; el resto son
  ficheros de la lane migrada, copiados byte a byte para que su `sha256` siguiera cuadrando con el manifiesto de
  rutas. Reformatearlos en masa habría invalidado esa procedencia, así que no se hizo.
- Los **343** errores de Mypy son 297 heredados más 46 que aparecen al añadir `scripts` a `mypy_path` en el
  `pyproject.toml` de la lane. El cambio es intencional (type-check de `scripts/`), pero hoy deja el gate rojo.
- `pip-audit` falla por avisos **nuevos** en dependencias fijadas (nltk, pip, urllib3, setuptools); el workflow
  sólo ignora `PYSEC-2026-597`.
- El job `smoke-pr-pipeline` no llega ni a ejecutarse: `microsoft/powershell@v1.1.0` responde
  **"Unable to resolve action … repository not found"**. La acción no existe; el job nunca pudo pasar.

Los 12 runs de CI Baseline sobre `main` desde 2026-07-10 terminaron en `failure`. Ningún commit, ni el de
esta rama ni los de `main`, ha visto ese workflow verde.

#### 1.8.4 Los otros dos rojos son de bytes, no de lógica

- **recovery-determinism**: `data/recovery/ACTIVE_ECONOMIC_AUDIT.json` publicado lleva
  `payload_sha256 = c6ea3438…` y el reconstruido en un checkout limpio de Linux da `023b66ff…`; el test lo dice
  con todas las letras: *"the committed audit is stale: re-run scripts/active_economic_audit.py"*. El mismo
  workflow **pasa** en `fix/tdm14a` (runs `40294382261`, `40295127315`), así que no es un workflow roto: es este
  artefacto, en esta rama.
- **Cost-barrier drift gate**: fallan 2 tests de contrato porque los `sha256` de los productores se fijaron
  sobre los bytes **CRLF** de esta máquina; el propio verificador emite el aviso `EOL_ONLY` ("git rewrote the
  bytes on checkout"). En Linux el checkout es LF y el digest deja de cuadrar. Es la misma clase de defecto que
  los payloads RFC-048 de §1.2.3, en otro bundle.

#### 1.8.5 Segunda ronda: la misma pared, y el falso éxito ya no aparece

Tras publicar `266761bf` (el cierre del falso éxito y las sesiones nuevas), GitHub volvió a ejecutar los cuatro
workflows. Resultado: **los cuatro vuelven a fallar, y ahora por lo que deben**:

| Workflow | Run | Conclusión |
| --- | ---: | --- |
| Integration gate | `40308569940` | `failure` — merge commit `c1cecb72`: 3 PASS, 9 FAIL, 3 NOT_TESTED, `false_success 0` |
| recovery-determinism | `40308570056` | `failure` (B14: el audit sigue obsoleto) |
| Cost-barrier drift gate | `40308570059` | `failure` (B13: digests sobre CRLF) |
| CI Baseline | `40308569933` | `failure` (B12: deuda heredada) |

La diferencia que importa está en un solo paso:

```
C3_LOCK_CAMPAIGN  FAIL  exit 1:
  "iteration-01:NO_CYCLE_BEFORE_CRASH",
  "incomplete:1/6 crash sites"
```

Antes ese mismo paso devolvía `0` con `{"iterations": 1, "cycles": [], "locks": 0}` y el gate lo contaba como
`PASS`. Ahora falla con el motivo escrito y arrastra `J2`/`V2` a `NOT_TESTED` en lugar de fabricar un contrato
verde sobre una campaña vacía. El número de `PASS` baja de 4 a 3: **el gate es más débil en apariencia y más
honesto en realidad.**

Ninguno de los dos se ha "arreglado" relajando la comprobación: quedan como bloqueos B11–B14 en §4.

---

## 2. WP-02 — Diagnóstico de las 24 estrategias rechazadas

Todo lo de esta sección se recalcula con `tools/strategy_economics.py` desde tres artefactos
(`config/strategy_admission.json`, `data/recovery/ACTIVE_ECONOMIC_AUDIT.json`,
`data/recovery/COST_BARRIER_EXPLORER.json`) **sin importar** el código que los produjo. Resultado:
`evidence/STRATEGY_ECONOMICS.json`, `verdict PASS`, `problems []`, `false_success 0`, y tres autocontroles que
demuestran que el clasificador reacciona al número.

### 2.1 Clasificación (no se copia la etiqueta: se recalcula)

| Clase | Celdas | Regla aplicada |
| --- | ---: | --- |
| `NO_GROSS_EDGE` | **17** | bruto a coste cero ≤ 0 |
| `COST_KILLED` | **7** | bruto a coste cero > 0 pero ≤ 12 bps (línea de investigación sobre la que se midió) |
| Bruto que supera la línea de investigación | **0** | — |

Las 7 `COST_KILLED` son `mean_reversion@5m` (+1.485), `mean_reversion@15m` (+2.714), `mean_reversion@30m` (+5.472),
`trend@15m` (+1.284), `trend@30m` (+2.206), `volatility@1h` (+6.276) y `volatility@30m` (+8.912, el máximo).
La coincidencia con el ledger es total (`recomputed_matches_ledger: true`); el único desacuerdo de procedencia es
`breakout@5m` con **0.026 bps** (−0.11 en el ledger de 5m, −0.084 en la auditoría de timeframes, dos motores y dos
precisiones), muy por debajo de la tolerancia de 0.05 que el propio informe publica.

### 2.2 Economía reconstruida por celda

| Celda | Bruto bps | Ops | PF (base) | WR % | Payoff | MFE/MAE % | Neto base USD | OOS bruto bps |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| volatility@30m | +8.912 | 194 | **0.9402** | 62.37 | 0.5672 | 0.828/0.725 | **−24.62** | +3.116 |
| volatility@1h | +6.276 | 96 | **0.8441** | 63.54 | 0.4843 | 0.920/0.791 | −36.04 | −4.518 |
| mean_reversion@30m | +5.472 | 934 | **0.8619** | 59.74 | 0.5808 | 0.765/0.764 | −274.77 | −5.602 |
| mean_reversion@15m | +2.714 | 1579 | **0.7801** | 54.78 | 0.6439 | 0.646/0.666 | −703.12 | +3.192 |
| trend@30m | +2.206 | 1562 | **0.8110** | 63.44 | 0.4673 | 0.909/0.914 | −738.71 | −1.846 |
| mean_reversion@5m | +1.485 | 3190 | **0.6746** | 46.49 | 0.7766 | 0.466/0.473 | −1514.34 | +0.321 |
| trend@15m | +1.284 | 1616 | **0.7831** | 60.89 | 0.5030 | 0.832/0.836 | −871.90 | +2.082 |
| … otras 17 celdas | ≤ 0 | 277–3214 | 0.5017–0.9293 | — | — | — | negativas | — |
| volatility@30m | +8.912 | 194 | 0.9402 | 62.37 | 0.5672 | 0.828/0.725 | −24.62 | +3.116 |
| volatility@1h | +6.276 | 96 | — | — | — | — | — | −4.518 |
| mean_reversion@30m | +5.472 | 934 | — | — | — | — | — | −5.602 |
| mean_reversion@15m | +2.714 | 1579 | — | — | — | — | — | +3.192 |
| trend@30m | +2.206 | 1562 | — | — | — | — | — | −1.846 |
| mean_reversion@5m | +1.485 | 3190 | — | — | — | — | — | +0.321 |
| trend@15m | +1.284 | 1616 | — | — | — | — | — | +2.082 |
| breakout@5m | −0.084 | 2426 | 0.9972 | 40.64 | — | 0.536/0.483 | −10.19 | — |
| … otras 16 celdas | ≤ 0 | 448–3214 | — | — | — | — | — | — |

El detalle completo, con comisiones implícitas (≈10.004 bps/operación), slippage implícito (1.444 bps), turnover
y particiones, está en `evidence/STRATEGY_ECONOMICS.json` (`cells[*]`).

**El dato que cierra la discusión, y que las etiquetas escondían:** con la línea de coste **base** aplicada, **las 24
celdas tienen profit factor < 1** (rango 0.5017–0.9402), **las 24 tienen neto negativo**, la mejor pierde **−24.62 USD**
y la esperanza por operación va de **−2.538 a −18.908 bps**. Es decir: las 7 celdas "con ventaja bruta" ya pierden
dinero en la línea sobre la que se midieron. `c2` (net > 0) y `c3` (PF > 1) fallan en las 24 antes de llegar a la
línea del runtime. El "bruto positivo" es un artefacto de medir a coste cero, no un candidato.

**Turnover:** 207 días de ventana (2026-03-01..2026-09-24, calculado de la cadena `_period` del ledger). El rango va de
0.46 ops/día (`volatility@15m`, 277 ops) a 15.41 ops/día (`mean_reversion@5m`, 3190 ops) — es decir, de 169 a 5.625
round trips al año, cada uno pagando la línea completa.

**Drawdown:** **no publicado en ninguna celda** (`max_drawdown: null` en las 24,
`cells_with_drawdown_published: 0`). No se reconstruye porque exigiría reejecutar la curva de equity, y los datos de
barras de la ventana W1–W7 no están en el repositorio (`data/` no contiene el dataset de 187.392 barras). Se declara
hueco, no se inventa.

### 2.3 Las cuatro líneas de coste y la distancia real

| Línea | Escenario | bps RT | Clase de conocimiento | Celdas que la superan |
| --- | --- | ---: | --- | ---: |
| investigación (donde se midió el bruto) | contrato 500 USD | 12.000 | — | **0** |
| más barata **observada** | `BINANCE_USDM_PERP_TAKER` | 12.177 | `ESTIMATED` | **0** |
| **runtime** (la que aplica la admisión) | `BINANCE_SPOT_STANDARD_TAKER` | 23.354 | — | **0** |
| más barata **cualquiera** | `MEXC_SPOT_TAKER` maker | 1.250 | `ASSUMED` | 7 |

Sólo 7 celdas serían alcanzables aceptando una comisión **supuesta** (maker MEXC a 0 bps), y ninguna con costes
observados. La distancia no es de afinado: el mejor bruto es **0.73×** la línea observada y **0.38×** la del runtime.

### 2.4 Las dos magnitudes en la misma regla

El artefacto del coste publica, por timeframe y activo, la mediana del movimiento absoluto de una barra. Dividiendo
coste y bruto por esa mediana (BTC):

| Timeframe | Mediana | Barras que cuesta el runtime | Barras que captura el mejor | Ratio |
| --- | ---: | ---: | ---: | ---: |
| 5m | 6.83 bps | 3.419 | 0.217 (`mean_reversion@5m`) | **15.8×** |
| 15m | 9.38 bps | 2.490 | 0.289 (`mean_reversion@15m`) | **8.6×** |
| 30m | 13.26 bps | 1.761 | 0.672 (`volatility@30m`) | **2.6×** |
| 1h | 18.62 bps | 1.254 | 0.337 (`volatility@1h`) | **3.7×** |

Conclusión cuantitativa: en todos los horizontes la mejor celda captura entre **0.2 y 0.7 barras** de movimiento
direccional neto mientras el round trip cuesta entre **1.25 y 3.4 barras**. El hueco se estrecha con el horizonte pero
no se cierra: es estructural, no de calibración.

### 2.5 Causa raíz (y qué no es causa)

Dos fallos apilados, no uno:

1. **Sin ventaja (17/24).** Cinco de las seis familias tienen bruto ≤ 0 a coste cero con muestras de 448–3.214
   operaciones. No es falta de datos: la muestra es suficiente en 23 de 24 celdas.
2. **Ventaja por debajo del suelo (7/24).** Las celdas con bruto positivo no llegan ni a la línea observada más barata.

No son causas: la sesión PAPER (0 fallos de runtime, reconciliación completa), la frecuencia (el turnover no explica
nada: las celdas de mayor bruto son las de menor frecuencia, y las de 30m superan a las de 5m), ni la implementación
del motor (la paridad está probada por el gate).

**Inestabilidad de partición:** 17 de 24 celdas cambian de signo entre desarrollo, validación y out-of-sample. El caso
extremo es el mejor: `volatility@30m` da **+21.33 bps DEV, −14.24 bps VAL, +3.12 bps OOS**. Un promedio positivo sobre
particiones que no comparten signo no es una ventaja; es un artefacto de agregación, y por eso las 7 celdas
`COST_KILLED` no se promocionan aunque la media sea positiva.

**La refutación a nivel de mecanismo:** `EXP-003M` ya probó el candidato que mejor se veía (`5m/mean_reversion`) con
fills maker realistas sobre `aggTrades` (42 pares símbolo-día, 680.484 operaciones). El techo de bruto por operación
cerrada es **0.2669 USDT** (F0: todo toque lleno al precio mejorado, cola cero) contra un suelo de comisiones de
**0.7500 USDT** sobre 500 USDT: cobertura **0.356×**. Los 24 puntos del barrido de cola y latencia dan neto negativo,
0/24 positivos. Un fill más realista sólo puede empeorar el bruto, así que el problema no es de fills: es que el bruto
por operación no cubre las comisiones.

**Y una segunda razón, independiente de la economía:** el criterio pre-registrado `c6` exige drawdown máximo ≤ 10 %, y
ese dato no existe en ningún artefacto. Aunque una celda fuera rentable, hoy **no podría admitirse**, porque `c6` no es
evaluable. `c1..c9` sólo se aplicaron a 5m (`DEF-ACT-02`); las celdas de 15m/30m/1h no tienen veredicto propio.

### 2.6 Experimentos offline permitidos (sin relajar controles)

Sólo tres líneas, y todas como **hipótesis nuevas pre-registradas**, nunca como reajuste de las cerradas. Los
criterios `c1..c9` no se tocan; el presupuesto es de cálculo, no de riesgo.

| # | Hipótesis | Por qué el dato la sostiene | Qué la mataría |
| --- | --- | --- | --- |
| E-1 | **Construcción de entrada, no de salida.** La esperanza directa a +1/+3/+6/+12/+24 barras es negativa en todas las familias; el bruto no mejora moviendo stops o targets | El signo negativo aparece en la entrada, antes de cualquier salida | una familia cuyo bruto no cambie al sustituir el gatillo de entrada por su versión invertida/aleatoria (es decir, si no hay información en la señal) |
| E-2 | **Horizonte 30m–1h con captura de varias barras.** El bruto por operación crece con el horizonte hasta 30m y el coste por operación no | La relación barras-pagadas/barras-capturadas es 2.6× a 30m frente a 15.8× a 5m | que a 1h el bruto vuelva a negativo (ya ocurre en 4 de 6 familias) |
| E-3 | **Plano de coste medido, no supuesto.** Sustituir `BINANCE_SPOT_STANDARD` (23.35 bps) por el plano del venue real (13.79 bps perp, 9.25 maker RT) con spread observado en lugar de estimado | El runtime cobra casi el doble de lo que cuesta el venue donde opera | que el spread observado empuje la línea por encima de la estimada |

Lo que **no** se propone: reajustar parámetros sobre la misma ventana, buscar una ventana mejor para las mismas reglas,
relajar `c7` (2× coste), admitir con coste maker supuesto, ni promocionar cualquier resultado que no traiga partición
DEV/VAL/OOS con el mismo signo.

**Protocolo obligatorio antes de pedir admisión** (idéntico para las tres): pre-registro con `id` nuevo y ventana
`W8+` reservada y no mirada; congelar el dataset por `sha256`; `c1..c9` completos, incluido `c6` con curva de equity
propia; partición DEV/VAL/OOS con el **mismo signo** en las tres; supervivencia a 2× coste; y prueba de que el bruto
por operación supera el suelo **en el techo del modelo de fills**, no en el escenario favorable. Ningún resultado
dentro de muestra se declara rentable: esta sección no afirma que exista una estrategia viable, sólo qué se puede
probar para encontrarla.

---

## 3. WP-03 — PAPER de extremo a extremo, tres recorridos separados

### 3.1 Recorrido A — sesión con datos reales, decisiones trazables y fills

Dos sesiones con el mismo entrypoint, la misma máquina y el mismo `mode: PAPER`; lo único que cambia es el
calendario, y con él el resultado:

| Hecho | domingo 2026-10-25 (`9d622bb5`) | **lunes 2026-10-26 (`76e8ec0b`, esta entrega)** |
| --- | --- | --- |
| ciclos ejecutados / bloqueados | 6 / 0 | **7 / 0** |
| barras de decisión | 6 | 7 (10:04 … 10:10 UTC) |
| `data_delay_ms` | 7.684 | **4.199** (`MEASURED_AT_SESSION_START`) |
| decisiones registradas | 30 | **45** |
| aprobaciones de riesgo (`approved=true`) | 16 | **9** |
| gated / rechazadas | 3 / 1 | **0 / 4** (`RUN_ENDED_WITH_ORDER_PENDING`) |
| **fills abiertos** | **0** | **2** (BTC long, ETH short) |
| trades cerrados | 0 | 0 |
| órdenes live | **0** | **0** |
| equity | 10.000 → 10.000 | 10.000 → **9.998,78** marcada (−1,22 no realizado, 1,00 de comisiones) |
| drawdown de la ventana | 0 | **0,0141 %** |
| reconciliación / drift de runtime | 12/12 / `[]` | completa / `[]` |

```bash
python scripts/def_run_019_prospective_run.py --out <dir>/session \
  --symbols BTCUSDT ETHUSDT --timeframe 1m --window-bars 120 --warmup-minutes 120 \
  --max-cycles 7 --duration-s 900 --latency-ms 30000
```

`RUN_META.json` de la sesión del lunes: `commit = 76e8ec0bfeb7`, `dirty_paths = []`, `mode = PAPER`,
`live_enabled = false`. Evidencia: `evidence/paper_session_long/`; la sesión corta de 2 ciclos también se rehízo en
el mismo commit (`evidence/paper_session/`), que es lo que permite a A8 comparar contra `HEAD` sin delta ejecutable.

**Lo que cambia el diagnóstico, otra vez, y esta vez a favor de que el carril funciona:** el domingo las 3 opiniones
aprobadas murieron en `WEEKEND_BLOCK` (*"policy sets weekend_trading=false; no discretionary entries"*,
`config/risk.yaml:52`). El lunes, con el mercado abierto y la misma política, el runtime **abrió dos posiciones
PAPER** (BTC long y ETH short, 500 USDT cada una, comisión de entrada 0,5 USDT por lado) y las mantuvo abiertas al
cierre. No hubo ni una orden live. Es decir: el carril PAPER **sí llega a fills con datos reales**; lo que no había
era un día en que la política permitiera entrar. `strategy_id` sigue siendo `null` (B10).

**Un defecto que sólo aparece cuando hay fills, y que el verificador cazó:** A10 comparaba `summary.fills` con el
número de filas `FILL` de todos los ledgers, pero cada ledger de ciclo lista **todas** las posiciones abiertas al
final de ese ciclo. Una sola entrada de BTC aparecía en cinco ledgers y el verificador contaba 9 filas para 2
posiciones. Se corrigió contando `position_id` distintos con `phase = OPEN_ENTRY`/`CLOSE_EXIT`, y el autocontrol S5
sigue exigiendo que un `summary` que se atribuya un fill de más haga fallar A10. Sin ese control, el número del
resumen habría pasado por bueno con cualquier conteo.

### 3.2 Recorrido B — ejercicio determinista de propuestas, órdenes, fills y contabilidad

Ejecutado por los tests, que es donde el ciclo de trade se ejerce de verdad: `tests/unit/paper/test_paper_cycle.py`,
`tests/unit/vision/test_closed_trade_cycle.py`, `tests/unit/vision/test_causal_execution.py`,
`tests/unit/vision/test_def_run_016_opinion_lifecycle.py`, `tests/unit/ops/test_paper_lock_campaign.py`.
Resultado dentro del subconjunto de §1.7 sobre `76e8ec0b`: **`320 passed, 0 failed`** (exit 0, 4 min 0 s). Aquí sí se abren y
cierran posiciones, se cobran comisiones y se comprueba que un cierre no ocurre antes de su entrada; en la sesión
real del lunes, además, se abrieron dos posiciones con datos de mercado.

### 3.3 Recorrido C — ejecución prolongada para observar oportunidades reales

**No se ha ejecutado una ventana nueva de 24 h en este pase, y no se presenta como ejecutada.** Lo que sí hay, y está
en `data/recovery/ACTIVE_ECONOMIC_AUDIT.json` → `paper_lane`:

| Hecho de `paper-lab-continuous-02` | Valor |
| --- | --- |
| estado final | `PAPER_24H_DATA_FAILED` |
| cobertura | **4.16 h** de 24 (17.3 %) |
| causa | el colector alcanzó su presupuesto de **800 MB** y paró limpio |
| ciclos / paper trades / shadow trades | 337 / 0 / 0 |
| `no_trade_kind` | `NO_TRADE_STRATEGIC` |

Una ventana de 24 h no cabe en este pase y, con 0 estrategias admitidas, su resultado esperado es
`NO_TRADE_STRATEGIC`: repetirla no añadiría evidencia sobre oportunidades. Lo que sí añadiría valor es arreglar el
presupuesto de disco (4.61 GB/día proyectados) para que la ventana pueda completarse cuando exista un candidato.

---

## 4. Bloqueos, responsables y acción mínima

| # | Bloqueo | Estado | Responsable | Acción mínima |
| --- | --- | --- | --- | --- |
| B1 | G1 sin firma (veto semanal de pérdida) | **OPEN** | risk-manager | firmar el cambio o revertir el roll |
| B2 | Gate no es required check | **BLOCKED** | administrador del repositorio | activar el status check (comando en §1.8) |
| B3 | Workflow nunca ejecutado en GitHub | **cerrado** | — | ejecutado: 4 workflows, 4 `failure`, causas en §1.8 |
| B4 | 0 estrategias admitidas | **NO_GO** | quant-researcher / strategy-engineer | un mecanismo cuyo bruto supere el suelo (§2.6) |
| B5 | Evidencia de la auditoría sin versionar | **cerrado** | — | `.gitignore` versiona la carpeta y cierra la fuga de `.pyc` |
| B6 | Verificador podía dar por bueno un ciclo bloqueado o un certificado viejo | **cerrado** | — | A4 cruza `exit_code`/`cycles_blocked`/`closed_trades`; A8 ata el runtime a HEAD; S3/S4 lo demuestran |
| B7 | **La política bloquea entradas en fin de semana** (`weekend_trading: false`) | **OPEN (nuevo)** | risk-manager | decidir si un activo 24/7 debe heredar el calendario de renta variable. **No se ha cambiado**: es un límite de riesgo |
| B8 | `c6` (drawdown ≤ 10 %) no evaluable: ninguna celda publica drawdown | **OPEN (nuevo)** | backtest-engineer | publicar la curva de equity y el drawdown de las 24 celdas |
| B9 | `c1..c9` sólo aplicados a 5m (`DEF-ACT-02`) | **OPEN** | quant-researcher | matriz de admisión por timeframe, o admitir que 15m/30m/1h no tienen veredicto |
| B10 | La sesión PAPER no atribuye `strategy_id` (sale `null`) | **OPEN (nuevo)** | strategy-engineer | propagar la estrategia desde la señal al resumen y al ledger |
| B11 | **El gate no puede certificar en un runner alojado**: no hay feed de mercado, así que `C1` muere a los 420 s y `C3` se queda en una iteración (§1.8.1) | **OPEN (nuevo)** | observability-engineer / backtest-engineer | runner self-hosted con datos, o feed de replay determinista; **no** se fabrican señales ni fills |
| B12 | **CI Baseline nunca ha estado verde** (12/12 `failure` desde 2026-07-10) y su "verde" de `origin/main` se midió sobre 239 ficheros, 263 commits por detrás (§1.8.3) | **OPEN (nuevo)** | context-engineer | decidir qué árbol es `main`, y reformatear/ tipar el árbol real en un PR aparte |
| B13 | Los `sha256` de los productores del cost-barrier se fijaron sobre bytes CRLF: en Linux fallan 2 tests de contrato (§1.8.4) | **OPEN (nuevo)** | backtest-engineer | fijar los bytes (`-text`) o hacer el digest insensible a EOL, igual que en RFC-048 |
| B14 | `data/recovery/ACTIVE_ECONOMIC_AUDIT.json` está obsoleto: reconstruido en limpio da otro `payload_sha256` (§1.8.4) | **OPEN (nuevo)** | backtest-engineer | volver a generarlo en un checkout limpio y versionar el resultado |

Ninguno de estos bloqueos se ha "resuelto" cambiando un umbral. Los dos que tocaban límites de riesgo (B7) o
gobernanza (B2, B1) quedan explícitamente sin tocar.

---

## 5. Siguiente paso operativo (comandos exactos)

Los pasos 1–2 ya están hechos: rama publicada (`admission/integration-002`), **PR #18** abierto y cuatro
workflows ejecutados (§1.8). Lo que queda no es publicar, es decidir y reparar:

```bash
# 1. el falso éxito ya está cerrado; falta el feed para que el gate pueda certificar (B11)
python scripts/tap_integration_gate.py run --out /tmp/gate --label local:$(git rev-parse --short HEAD)

# 2. regenerar en un checkout limpio lo que hoy sólo cuadra en Windows (B13, B14)
python scripts/cost_barrier_evidence.py --materialize
python scripts/active_economic_audit.py

# 3. gobernanza (administrador, no ingeniería): sigue BLOCKED sin `gh` en esta máquina
gh api repos/Extr3sao/bot_crypto/branches/main/protection --jq '.required_status_checks.contexts'
```

El orden importa: B13/B14 son reproducibilidad; B11 es la condición para que el gate pase de "voluntario y rojo en
CI" a "required check que puede ponerse verde". Ninguno de los dos se resuelve tocando umbrales.

---

## 6. Evidencias y verificación independiente

| Artefacto | Qué prueba |
| --- | --- |
| `evidence/ADMISSION_VERIFICATION.json` | 15 claims, `verdict PASS`, `false_success 0` |
| `evidence/STRATEGY_ECONOMICS.json` | las 24 celdas recalculadas, 3 autocontroles, `verdict PASS` |
| `evidence/gate_at_9d622bb5/**` | el gate recalculado en la entrega anterior (15/15, 260 hashes) |
| `evidence/gate_at_76e8ec0b/**` | **el gate recalculado sobre la punta de esta entrega** (15/15, 258 hashes, `false_success 0`) |
| `evidence/gate_at_600e744d/**` | la primera recomputación, conservada para que el recálculo sea auditable |
| `evidence/paper_session/**` | la sesión PAPER de 2 ciclos de la entrega anterior |
| `evidence/paper_session_long/**` | la sesión de 6 ciclos con señales reales, 16 aprobaciones y 0 fills |
| `reports/ai-bots/TAP-INTEGRATION-GATE-001/evidence/**` | la evidencia del gate de la entrega anterior (525 hashes) |

Reproducción (determinista, sin red):

```bash
.venv/Scripts/python.exe reports/ai-bots/TAP-INTEGRATION-ADMISSION-002/tools/admission_verify.py
.venv/Scripts/python.exe reports/ai-bots/TAP-INTEGRATION-ADMISSION-002/tools/strategy_economics.py
```

`sha256` del verificador y de su resultado, y `sha256` del informe económico, se recalculan en
`evidence/ADMISSION_VERIFICATION.json` (`head`, `claims`) — no se copian aquí para que no puedan quedar obsoletos.

---

## 7. Límites de este informe

1. **Sí hubo ejecución en `ubuntu-latest`, y falló**: cuatro workflows, cuatro `failure`, con causa raíz por
   workflow en §1.8. Lo que sigue sin poder afirmarse es que el gate **pase** en Linux: sin feed de mercado no
   hay ciclos, y sin ciclos no hay campaña que certificar (B11). El `PASS` de este informe es de Windows.
2. **La suite completa `pytest tests/unit` no se ejecutó**: se corrió el subconjunto que fija el código migrado
   (§1.7) y se declara.
3. **`c6`/drawdown y spread observado no existen** en ningún artefacto; no se estiman (§2.2).
4. **La ventana larga de PAPER no se repitió**: 0 fills con causa nombrada (`WEEKEND_BLOCK`), y una ventana de 24 h
   excede este pase (§3.3).
5. **`origin/main` está 263 commits por detrás de la `main` local** (medido en este pase); cualquier lectura de CI
   remoto describe un árbol antiguo —239 ficheros `.py` frente a 894— y el PR #18 lo expone en su diff: 279
   commits y 2.782 ficheros (§1.6, §1.8.3).
6. **Este informe no declara ninguna estrategia rentable.** La evidencia disponible es negativa, y las tres hipótesis
   de §2.6 son propuestas de experimento, no resultados.
