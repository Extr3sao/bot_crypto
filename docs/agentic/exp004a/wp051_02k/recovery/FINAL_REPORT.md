# WP-051-02K — recuperación de EXP-004A: dictamen

**Dictamen:** `BLOCKED_WITH_EVIDENCE`
**Fecha:** 2026-10-23 · **Paquete:** WP-051-02K · **Fase:** recuperación (WP-01…WP-05)

> Los componentes versionados se recuperaron y se verificaron byte a byte contra el commit que los
> declaró. Los dos almacenes que la campaña escribe —`data/forward/edge03` y
> `data/forward/edge04`— **no existen en ningún sitio**: no están en Git, no están en disco, no hay
> copia publicada más allá del 15 de octubre. Sin ellos no hay reanudación posible, y reconstruirlos
> sería inventar el dato que el experimento debía observar.

---

## HEAD

`1d2192b0` en `main` (checkout compartido, con cambios de otros agentes en `src/` que este paquete
no toca ni commitea). El árbol de recuperación quedó en `9983b050c8e241ef9d8365c8ffc33c95df1658dd`,
el commit del paquete 02K.

## WORKTREE

| Campo | Valor |
| --- | --- |
| Ruta | `C:\Users\GVLLFR0035\Downloads\exp004a-recovery-02k` |
| Rama | `recovery/exp004a-02k-9983b050` (creada por este paquete apuntando al commit huérfano) |
| HEAD | `9983b050` — verificado |
| Estado al crear | limpio (`git status --porcelain` vacío) |
| Tamaño | 423 MB (237 MB versionados + 186 MB de `.venv` reconstruido con `uv sync --frozen`) |
| Operaciones destructivas | **ninguna**: ni `reset --hard`, ni `clean`, ni checkout que pise trabajo ajeno |

El commit era **inalcanzable** (aparecía como `dangling commit` en `git fsck`) porque la rama
`wp/exp004a-051-02h` fue borrada con el worktree. Crear la rama `recovery/…` lo ancla: ya no puede
ser recolectado, y el árbol completo de la época queda reproducible con una orden.

## SOURCE

Fuente autoritativa: **el propio repositorio**, commit `9983b050`, cuyo árbol contiene el contrato,
los entrypoints y el guard. No se usó ninguna fuente externa, ni fixture sintético, ni copia de otro
worktree. Antes de recuperar se comprobó que el commit y sus blobs existen (`git cat-file`), que el
árbol se puede exportar (3837 ficheros) y que había espacio (18,867 GiB libres).

Búsqueda de los almacenes, con resultado negativo y método declarado:

| Búsqueda | Alcance | Resultado |
| --- | --- | --- |
| directorios `edge04*` | todo `C:\Users` (recursivo) | solo `edge04r` de tests y snapshots de 0 B |
| `runs.jsonl` de 4.247.224 B (huella del store vivo) | todo `C:\Users` | ninguno |
| `data/forward` en los cinco worktrees | `bot freebuff`, `wt-sup001`, `ff-wt-base`, `ff-wt-mt0004`, `ff-wt-trunkfmt` | ausente en los cinco |
| commits huérfanos con `data/forward` o `daily/2026-10-2*` | 91 commits colgados | solo `reports/edge-recovery/WP-EDGE-04/evidence` (copia publicada) |
| Papelera de reciclaje | `C:\$Recycle.Bin` | 9,8 MB, sin relación |
| `G:` | raíz | vacía salvo `$RECYCLE.BIN` |

## RECOVERY

Inventario completo: [RECOVERY_INVENTORY.json](docs/agentic/exp004a/wp051_02k/recovery/RECOVERY_INVENTORY.json).
**13 `FOUND_VALID` · 2 `ABSENT` · 0 `CORRUPTED` · 0 `FOUND_UNVERIFIED`.**

| Componente | Clase | Evidencia |
| --- | --- | --- |
| `contract_phase3`, `contract_phase2`, `contract_root` | `FOUND_VALID` | byte-idénticos a sus blobs |
| `capture_runner_02f`, `capture_runner_02g`, `capture_verifier_02g` | `FOUND_VALID` | blobs `2fec1484…`, `20503fb2…` = los que el contrato declara |
| `observer`, `observer_watchdog`, `closure` | `FOUND_VALID` | byte-idénticos; el guard ejecuta |
| `engine`, `store_module` | `FOUND_VALID` | `incremental.py` = `engine_block 75d73669…` del contrato |
| `shard_store_phase3` (`data/exp004a/phase3`) | `FOUND_VALID` | 50 ficheros, 24 manifiestos, 0 días de producción |
| `published_prefix` (`reports/edge-recovery/WP-EDGE-04/evidence`) | `FOUND_VALID` | 29/29 ficheros contra su `SNAPSHOT.json` |
| **`store_forward_edge04`** | **`ABSENT`** | el store vivo de la fase 3: `runs.jsonl` 941 líneas, 11 shards diarios |
| **`store_forward_edge03`** | **`ABSENT`** | el store de fase 1/2 que lee el verificador 02G |

Lo único que sobrevive del store es su **prefijo publicado** (13–15 de octubre): 196 de las 941
líneas de `runs.jsonl`, 3 de los 11 shards diarios. Se verificó con dos comparaciones
independientes: contra el `SNAPSHOT.json` de la publicación (29/29 ficheros coinciden, con
normalización CRLF↔LF, que es la razón por la que un fichero idéntico puede hashear distinto) y
contra los hashes que 02K tomó del store vivo: **2 de 3 shards coinciden** (`2026-10-13`,
`2026-10-14`); **`2026-10-15` difiere** porque la copia publicada es anterior a la versión
write-once final de ese día. Eso no es corrupción: es un prefijo, y el registro 02K es la autoridad
sobre los bytes finales de los 11 días.

## INTEGRITY

Informe completo: [INTEGRITY_REPORT.json](docs/agentic/exp004a/wp051_02k/recovery/INTEGRITY_REPORT.json).
**11 PASS · 2 FAIL · 0 SKIP.**

| Comprobación | Estado |
| --- | --- |
| `SOURCE_COMMIT_CHECKED_OUT` | PASS |
| `CONTRACT_DECLARES_ITS_GENERATOR` (4/4 objetos presentes) | PASS |
| `CONTRACT_SUPERSEDES_HASH_MATCHES` (fase 2, CRLF-aware) | PASS |
| `PHASE3_SHARD_MANIFESTS_VERIFY` — 24/24 manifiestos, 864 filas de ensayo | PASS |
| `PUBLISHED_PREFIX_VERIFIES` — 29/29 | PASS |
| `PUBLISHED_PREFIX_VERSUS_THE_RECORD` — 3/11 días, 2 coinciden | PASS |
| `RECORD_BYTES_STILL_MATCH_THEIR_COMMIT` — 12/12 | PASS |
| `GUARD_IS_OPERABLE` | PASS |
| `RUNNER_IS_EXECUTABLE` | PASS |
| `TESTS_PASS` | PASS |
| `SPACE_WITHIN_THE_FROZEN_BUDGET` | PASS |
| **`GUARD_TASK_POINTS_AT_A_LIVE_SCRIPT`** | **FAIL** |
| **`FORWARD_STORE_STILL_EXISTS`** | **FAIL** |

Dos matices que el recuento esconde:

1. Las **864 filas verificadas son de ensayo** (`/rehearsal/`, `prospective=false`,
   `counts_toward_coverage=false`). Producción admisible: **0 filas**, coherente con una ventana que
   abrió el 2026-10-23 y cuyo primer día quedó excluido por capacidad.
2. El contrato declara `shard_root: data/exp004a/phase3`, y ese árbol **está íntegro**; lo que falta
   es el store del observador (`data/forward/edge04`), que es otro artefacto y no está versionado.

## TESTS

| Dónde | Resultado |
| --- | --- |
| Worktree recuperado | **59 passed** — 32 de la suite de la época (incluye `test_contract_reads_the_frozen_window`, que **pasa** aquí) + 27 de la suite de continuación |
| `main` (checkout compartido) | 27 passed; 1 test de la suite 02K **no evaluable** (el contrato no está en este árbol) |

El mismo test que falla en `main` pasa en el worktree: la diferencia es la presencia del contrato,
no una aserción relajada — la aserción no se tocó.

## RUNTIME

| Programa | Comando | Resultado |
| --- | --- | --- |
| Runner 02F | `--check` (lee el mundo, no escribe) | **exit 0**; informa `edge03` ausente y 14 filas de fase 2 por serie (`BELOW_DECLARED`) |
| Verificador 02G | `--claim docs/…/wp051_02g/RUN_REPORT.json` | **exit 4**: `FileNotFoundError … data/forward/edge03/1h/BTC.jsonl` |
| Guard | `--help` | **exit 0** |
| Guard | `--task-status` | tarea registrada; **acción apuntando a un script borrado** |

La tarea programada `\TradingAgentic-EDGE04-Watchdog` sigue registrada y se ejecuta cada 15 minutos,
pero su acción es `"…\bot-freebuff-exp004a-02h\scripts\edge04_watchdog.py" --state-root
"…\bot freebuff\data\forward\edge04"`: **ni el script ni el store existen**. Último resultado
registrado: `2`. Es una alarma que no puede sonar, y se reporta como defecto del guard, no como
guard operativo.

## VERIFIER

- Capacidad, dentro del worktree:
  `INDEPENDENT_VERIFICATION_02K_CONTINUATION.json` → **15 PASS · 0 FAIL · 9 SKIP · exit 0**. Los
  `SKIP` son las comprobaciones de manifiesto de limpieza: en ese árbol no se borró nada.
- Capacidad, en `main` (tras re-medir): **23 PASS · 0 FAIL · 1 SKIP · exit 0**.
- Auditoría de recuperación: `11 PASS · 2 FAIL`, y los dos fallos son los bloqueos reales.
- `person_independence: false` — otro programa no es otra persona.

## SPACE

| Medida | Valor |
| --- | --- |
| Libre al empezar la recuperación | 18,867 GiB |
| Libre tras recuperar (medido por dos instrumentos, delta 0 B) | **14,9477 GiB** |
| Presupuesto congelado | **14,564 GiB** (sin tocar) |
| Margen | **+0,3837 GiB** |
| Coste de la recuperación | 423 MB (worktree 237 MB + `.venv` 186 MB) |

El margen bajó porque el host se movió durante la intervención (el indexador de Windows escribiendo
gigabytes, medido en la fase anterior), no porque la recuperación cueste 3,9 GiB. Aun así, 0,38 GiB
de holgura es fino y se declara como tal: un día peor consume el margen y vuelve a rechazar ticks.

## FALSE_SUCCESS

Lo que **no** se declara:

- **`CAPACITY=PASS` no es recuperación del experimento.** El disco cumple el presupuesto; la campaña
  no puede correr porque no hay store. Se mantienen separados en todos los artefactos.
- **59 tests en verde no son readiness.** `TEST_RESULT != CAMPAIGN_READINESS`; el gate del store es
  explícito y está en rojo.
- **864 filas verificadas no son 864 filas de campaña**: son de ensayo, con
  `counts_toward_coverage=false`.
- **El prefijo publicado no es el store.** 3 de 11 días, 196 de 941 líneas; usarlo como store sería
  reconstruir el dato que debía observarse.
- **La rama de recuperación no resucita la rama perdida**: ancla el commit, no el historial de la
  campaña.

## BLOCKERS

1. `FORWARD_STORE_ABSENT` — `data/forward/edge03` y `data/forward/edge04` no existen. Es el bloqueo
   duro: sin `runs.jsonl`/`slots.jsonl`/`alerts.jsonl` ni los shards diarios 16–23 de octubre, no hay
   estado del que reanudar, y el guard no tiene nada que vigilar.
2. `GUARD_TASK_BROKEN` — la tarea programada apunta a un script borrado; la alarma no puede disparar.
3. `SPACE_MARGIN_THIN` — 0,38 GiB sobre el presupuesto congelado; suficiente hoy, no holgado.

## DECISION

`BLOCKED_WITH_EVIDENCE`.

Se recuperó todo lo recuperable y se demostró con hashes. Lo que falta no es recuperable desde este
host: los dos almacenes eran datos ignorados por Git y fueron destruidos con el árbol de trabajo. La
única decisión honesta es no reanudar, no reconstruir y no declarar `READY_TO_RESUME`.

## NEXT_ACTION

Una sola, en este orden:

1. **Aportar `data/forward/edge04`** (y `edge03` si se va a re-verificar la fase 2) desde la copia de
   seguridad del host que corresponda —la campaña escribía en `…\bot freebuff\data\forward\edge04`
   hasta el 2026-10-23T13:43Z, con `runs.jsonl` de 941 líneas y 11 shards— y colocarlo en el mismo
   path relativo del worktree recuperado.
2. **Re-apuntar la tarea del guard** al worktree recuperado (`scripts/edge04_watchdog.py` con
   `--state-root …\exp004a-recovery-02k\data\forward\edge04`) y comprobar que dispara.
3. **Re-ejecutar** `python scripts/exp004a_wp051_02k_recovery_audit.py`: el dictamen solo cambia a
   `READY_TO_RESUME` cuando `FORWARD_STORE_STILL_EXISTS` y `GUARD_TASK_POINTS_AT_A_LIVE_SCRIPT`
   pasan y los manifiestos del store casan con los hashes que ya están registrados en
   `STORE_INTEGRITY.json`.

Si esa copia no existe, el dictamen pasa a `NOT_RECOVERABLE_FROM_THIS_HOST` y la campaña de 90 días
debe declararse perdida por causa de capacidad, no reiniciada en silencio.

## Artefactos

- [RECOVERY_INVENTORY.json](docs/agentic/exp004a/wp051_02k/recovery/RECOVERY_INVENTORY.json)
- [INTEGRITY_REPORT.json](docs/agentic/exp004a/wp051_02k/recovery/INTEGRITY_REPORT.json)
- [RUN_REPORT.json](docs/agentic/exp004a/wp051_02k/recovery/RUN_REPORT.json) · [RUN_REPORT.md](docs/agentic/exp004a/wp051_02k/recovery/RUN_REPORT.md)
- Evidencia cruda: [evidence/](docs/agentic/exp004a/wp051_02k/recovery/evidence) — `RUNNER_CHECK_02F.json`, `WATCHDOG_TASK.xml`, `WATCHDOG_TASK_STATUS.txt`, snapshots e integridad del worktree recuperado
- Código: [exp004a_wp051_02k_recovery_audit.py](scripts/exp004a_wp051_02k_recovery_audit.py) · [exp004a_wp051_02k_continue.py](scripts/exp004a_wp051_02k_continue.py) · [exp004a_wp051_02k_verify_continue.py](scripts/exp004a_wp051_02k_verify_continue.py)
