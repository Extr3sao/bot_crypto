# OPERATIONAL_BLOCKERS — qué impide integrar y qué puede esperar

> Verificado el 2026-10-23 sobre `codepaper/supervisor-001` @ `3b758e22`,
> worktree aislado creado desde ese commit y retirado al cerrar la auditoría (FINAL_REPORT §8); `main` no se tocó.
> Cada bloqueo lleva comando, salida y clasificación.

Clasificación:

- **BLOCKER**: impide integrar o impide creer la evidencia. Hay que resolverlo antes de seguir.
- **HAZARD**: no impide integrar, pero produce números falsos si alguien lo lee en un gate.
- **CAN WAIT**: deuda real, sin efecto sobre la decisión de admisión.

Convención de cada bloqueo: **Fuente** = artefacto o fichero citado · **Evidencia** = comando
ejecutado con su salida y exit code · **Decisión** = la clasificación (BLOCKER / HAZARD / CAN WAIT)
y quién lo arregla.

---

## B1 — `test_windowless` está rojo, y 2 de las 3 causas las puso el propio lane del supervisor

**BLOCKER** (para un merge verde; no para la economía).

```
cd ../CODEX-PAPER-ADMISSION-DIAG-001
PYTHONPATH=$PWD/src ../bot\ freebuff/wt-sup001/.venv/Scripts/python.exe \
  -m pytest tests/unit/ops/test_windowless.py -q
→ 1 failed, 12 passed · exit 1
```

El test `test_no_controlled_launcher_can_start_an_unhidden_child`
(`tests/unit/ops/test_windowless.py:292-296`) ejecuta `scripts/ops_background_audit.py::scan()`
y exige 0 hallazgos `HIGH`. Hallazgos reales hoy:

| # | Fichero:línea | Introducido por | Lane |
| --- | --- | --- | --- |
| 1 | `scripts/exp004a_verify.py:1216` | `a3a22e3e` (2026-10-21) | EXP-004A |
| 2 | `tests/unit/ops/test_paper_lock_campaign.py:44` | `ce02a810` (2026-10-23) | **supervisor-001** |
| 3 | `tests/unit/ops/test_session_status.py:65` | `ce02a810` (2026-10-23) | **supervisor-001** |

Código: `POPEN_WITHOUT_WINDOWLESS` — `subprocess.Popen(...)` sin `CREATE_NO_WINDOW`.

**Matiz que corrige el informe del lane:** `RUN_REPORT.json` lo declara
`preexisting_failure`. Es cierto que el test ya estaba rojo en el commit base `60455b46`
(por el hallazgo 1), pero **el lane añadió 2 de los 3**, y el recuento de offenders pasó de 1 a 3.
Un lector del `RUN_REPORT` cree que no empeoró; empeoró.

**Arreglo:** envolver los dos `Popen` de test en `trading_bot.ops.windowless.spawn()` (o el
helper que ya usan los demás tests), y decidir el de `exp004a_verify.py` en su lane.
Coste: minutos. Riesgo: nulo. **No lo hice**: esta directiva prohíbe implementar.

---

## B2 — `uv.lock` no resuelve `matplotlib`: el entorno «congelado» queda incompleto en silencio

**BLOCKER** (reproducibilidad; y bloquea el lane de visión).

```
uv lock --check
→ "The lockfile at `uv.lock` needs to be updated, but `--check` was provided." · exit 1

uv sync --frozen --dry-run
→ exit 0 … pero no lista matplotlib
```

`pyproject.toml` declara `matplotlib>=3.8,<4.0` (necesario para
`src/trading_bot/vision/chart.py`, que lo importa **en top-level**, L36-42).
`uv.lock` contiene **0** referencias a `matplotlib`:

| Paquete | En `uv.lock` | En `uv sync --frozen --dry-run` |
| --- | ---: | ---: |
| `matplotlib` | 0 | 0 |
| `contourpy` | 0 | 0 |
| `cycler` | 0 | 0 |
| `fonttools` | 0 | 0 |
| `kiwisolver` | 0 | 0 |
| `pillow` | 0 | 0 |
| `pyparsing` | 1 | 1 |

**Lo peligroso es el modo de fallo:** `uv sync --frozen` **sale con 0** y produce un entorno
que no satisface `pyproject.toml`. Cualquier CI o checkout limpio que use ese comando cree que
instaló el proyecto; el import de `trading_bot.vision.chart` fallará en tiempo de ejecución, no
de instalación. `uv lock --check` sí lo detecta (exit 1), pero no se está ejecutando en ningún
gate visible.

**Arreglo:** `uv lock` (actualiza el lock a los 6 paquetes) + commit del lock + añadir
`uv lock --check` al gate. **No lo hice**: cambiaría el lock compartido y es trabajo de otro lane.

---

## B3 — La evidencia del supervisor no está versionada: no viaja con el commit

**BLOCKER** (para «reproducible desde Git»; es el mismo defecto que el repo ya cerró en otros lanes).

```
git check-ignore -v reports/ai-bots/CODEX-PAPER-SUPERVISOR-001/campaign/VERIFICATION.json
→ .gitignore:463:reports/ai-bots/*   reports/ai-bots/CODEX-PAPER-SUPERVISOR-001/campaign/VERIFICATION.json

git log -1 --format=%h -- reports/ai-bots/CODEX-PAPER-SUPERVISOR-001/campaign/VERIFICATION.json
→ (vacío: nunca se ha commiteado)
```

Consecuencia: el commit del supervisor son **8 ficheros y 3 257 líneas** (código + tests):

```
scripts/paper_supervisor.py · scripts/paper_supervisor_campaign.py · scripts/paper_supervisor_verify.py
src/trading_bot/ops/paper_supervisor.py · src/trading_bot/ops/session_status.py
tests/unit/ops/test_paper_supervisor*.py · tests/unit/ops/test_session_status.py
```

…mientras los **27 artefactos**, los **5 episodios**, `CAMPAIGN.json`, `VERIFICATION.json` y los
logs viven solo en este disco, bajo una ruta ignorada. Los veredictos citados (PASS 33/33,
5 recuperaciones) **no se pueden re-derivar de un checkout limpio**.

**Arreglo:** promover el paquete a una ruta versionada (como ya se hizo con
`reports/ai-bots/EXP-003M-*`, 529 ficheros trackeados) o añadir una excepción de `.gitignore`
para este paquete. Decisión de quién posee el paquete, no mía.

---

## B4 — El verificador de lock juzga una campaña de supervisor y escupe `false_success=2`

**HAZARD** (no bloquea el merge; envenena cualquier gate que lo ejecute).

```
cd ../CODEX-PAPER-ADMISSION-DIAG-001        # mismo commit, misma evidencia
paper_supervisor_verify.py --campaign …/supervisor-001/campaign
→ PASS · 33/33 · false_success 0 · exit 0

paper_lock_campaign_verify.py --campaign …/supervisor-001/campaign   # el OTRO verificador
→ FAIL · 28/32 · false_success 2 · exit 1
```

Causa raíz, no interpretación: `paper_lock_campaign_verify.py` lee la evidencia de
`<campaign>/iterations/iteration-*` (L75) y este directorio **no tiene `iterations/`**: tiene
`episodes/episode-01..05.json`. `CAMPAIGN.json` declara
`schema_version: TAP_PAPER_SUPERVISOR_CAMPAIGN_V1`, y el verificador **no comprueba ese campo**
antes de juzgar. Resultado: 4 checks caen por falta de sujeto
(`at_least_five_recoveries`, `both_crash_sites_covered`, `concurrent_reclaim_has_one_winner`,
`stale_owner_was_refused`) y 10 mutaciones se marcan `invalid` (no hay nada que mutar).

**Interpretación honesta:** esto **no** prueba que la recuperación no ocurrió. Prueba que dos
herramientas con el mismo flag `--campaign` aceptan directorios de contratos distintos y una de
ellas emite un `FAIL`/`false_success=2` legítimo según su propio contrato. Si un release gate
corre ambos sobre `reports/`, el gate se pone rojo para siempre.

**Arreglo:** que cada verificador exija su `schema_version` y **refuse** (exit 2) un directorio
ajeno, en vez de juzgarlo. Coste: ~10 líneas + 1 test.

---

## B5 — `main` se movió durante la auditoría; el proyecto real vive en la rama

**CAN WAIT** (pero hay que saberlo antes de integrar).

| Hecho | Valor |
| --- | --- |
| `main` al empezar | `1d2192b0` (2026-10-12) |
| `main` al terminar la auditoría | `0e13160a` — **se movió durante la auditoría**: observé `1d2192b0`, luego `47ca8dac`, y al cerrar `0e13160a`; este último es el único que queda en la historia (el intermedio fue reemplazado) |
| commits en la rama que `main` no tiene | **301** |
| commits en `main` que la rama no tiene | **1** (`0e13160a`, 49 ficheros, solo `docs/agentic/exp004a/wp051_02k/**` + 2 tests) |
| ficheros en `main` / en la rama | 2 000 / 3 712 |
| simulación de merge (`git merge-tree --write-tree main codepaper/supervisor-001`) | **exit 0, sin conflictos** |
| solape entre `0e13160a` y los 8 ficheros del supervisor | **ninguno** |

**Decisión:** el supervisor se puede integrar sin sobrescribir nada ajeno: el merge es limpio y
no toca los ficheros que `main` acaba de mover. Pero **`main` no es el proyecto**: es una
fotografía del 12 de octubre más un commit de otro lane. Cualquier afirmación del tipo «esto ya
está en main» es falsa para 1 712 ficheros.

---

## B6 — 18 de 24 entradas del ledger declaran muestra 0

**CAN WAIT** para la decisión (el gross ya las mata), **BLOCKER** para cualquier futura promoción.

`config/strategy_admission.json` → `edge_evidence.sample_trades == 0` en todas las entradas de
15m/30m/1h, con la nota *«trade count not published for this timeframe -> sample size unproven»*.
El documento fuente (`docs/STRATEGY_DISCOVERY_V3_RESULTS.json`, bloque D-01) no publicó conteos;
el explorer sí los recuperó (194, 96, 934, 1 579…). Es un hueco de procedencia, y el runtime lo
trata como muestra insuficiente — correctamente.

---

## Resumen ejecutivo

| ID | Bloqueo | Clase | Quién lo arregla | Efecto sobre la admisión |
| --- | --- | --- | --- | --- |
| B1 | `test_windowless` rojo (3 offenders, 2 del lane) | **BLOCKER** | supervisor-001 + exp004a | ninguno |
| B2 | `uv.lock` sin `matplotlib`; `--frozen` sale 0 igualmente | **BLOCKER** | quien posea el entorno | ninguno |
| B3 | evidencia del supervisor ignorada por `.gitignore:463` | **BLOCKER** | supervisor-001 | ninguno |
| B4 | dos verificadores, un flag, sin guarda de schema | HAZARD | ops | ninguno |
| B5 | `main` stale y en movimiento; merge limpio | CAN WAIT | integración | ninguno |
| B6 | 18/24 entradas con muestra 0 | CAN WAIT | research | impide promover 15m/30m/1h |

**Ninguno de los seis bloqueos, arreglado, admitiría una sola estrategia.** Son condiciones para
*creer* el estado actual, no para cambiarlo. La admisión se mueve con evidencia económica
(`NEXT_EXPERIMENT.md`), no con estas reparaciones.
