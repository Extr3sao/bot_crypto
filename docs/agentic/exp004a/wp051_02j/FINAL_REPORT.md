# WP-051-02J — recuperación operativa de la campaña de 90 días

**Paquete:** WP-051-02J · **Experimental:** EXP-004A fase 3 · **Fecha:** 2026-10-23 ·
**Dictamen:** `BLOCKED` (capacidad `INSUFFICIENT`; alarma y programa `PASS`)

> El defecto que se podía arreglar aquí, se arregló: la alarma ahora está programada, se dispara
> sola, y deja un recibo del sistema operativo. El que no se podía arreglar sin permiso, no se
> arregló: C: tiene **3,26 GiB** libres contra los **14,57 GiB** que pide la distribución de
> caídas medidas. Nada de lo observado se reescribió y no se movió un control de la campaña.

---

## 1. Identidad del árbol

| Campo | Valor |
| --- | --- |
| Worktree | `C:\Users\GVLLFR0035\Downloads\bot-freebuff-exp004a-02h` |
| Rama | `wp/exp004a-051-02h` |
| HEAD | `7f9758d9bbff55dd2cbc01a1146f8a2ed5d49b77` |
| Estado | 1 fichero modificado (`scripts/edge04_watchdog.py`, +333/−4), 5 sin seguimiento (los de este paquete) |
| Store de la campaña | `C:\Users\GVLLFR0035\Downloads\bot freebuff\data\forward\edge04` (read-only para estas herramientas) |
| Contrato de la campaña | `config/preregistrations/EXP-004A.datasets.phase3.json` — `git diff` exit 0 |

## 2. Capacidad, antes y después

| Momento | Libre | Uso | Fuente |
| --- | --- | --- | --- |
| Diagnóstico (11:33Z) | **3,621 GiB** | 98,48 % | `DIAGNOSIS.json` |
| Tras la limpieza autorizada (11:34Z) | **3,594 GiB** | 98,49 % | `CLEANUP_EVIDENCE.json` |
| Al recalcular el presupuesto (11:52Z) | **3,248 GiB** | — | `CAPACITY_PLAN.json` |

Lo eliminado por este paquete: **1.421.356 B (1,36 MiB)** en 14 directorios `__pycache__`
propios, todos sin seguimiento. No es una limpieza simbólica: es la única que estaba autorizada.
El volumen se movió −0,9 MiB en los 12 s de la operación, que es ruido de otras manos.

### El presupuesto, medido en distribución (11 días de lecturas del propio lane, 929 ticks)

| Medida | Valor |
| --- | --- |
| Caída intradía p50 | 6,96 GiB |
| **Caída intradía p90** | **12,467 GiB** |
| Caída máxima observada | 14,583 GiB (`2026-10-19`) |
| Cambio neto mediano | **−1,661 GiB/día** (7 días gastando, 4 recuperando) |
| Huella propia de la campaña | **1,16 MB/día → 0,0972 GiB en 90 días** |
| Suelo de protección (intacto) | 2 GiB |
| **Requerido (p90 + suelo + crecimiento propio)** | **14,565 GiB** |
| Requerido con la peor caída | 16,680 GiB |
| Ticks rechazados en el histórico | 162 |

`INSUFFICIENT`: faltan **11,317 GiB** para el escenario p90. La cifra de 16,68 GiB del informe
02I no era el margen necesario sino *la peor caída ya ocurrida*; el presupuesto correcto es
14,57 GiB, y sigue siendo inalcanzable con lo que hay en el disco.

**El crecimiento de la campaña no es el problema** (0,1 GiB en todo el trimestre). El problema es
la variabilidad del host: caídas de 5–15 GiB dentro del mismo día.

## 3. De dónde sale el consumo

`CONSUMPTION_ATTRIBUTION.json`: 43 intervalos de 12 s (11,1 min), 1,499 GiB caídos, **99,6 %**
explicado por contadores de escritura por proceso.

| Proceso | Escrito durante las caídas | Intervalos |
| --- | --- | --- |
| `python.exe` | 1.347 MiB | 26 |
| `bun.exe` | 452 MiB | 36 |
| `SearchIndexer.exe` | 290 MiB | 13 |
| `chrome.exe` | 246 MiB | 96 |
| `git.exe` | 78 MiB | 1 |

Ninguno de los árboles vigilados creció (`%TEMP%` +4,7 KiB; `C:\ESD`, `wsl`, `Playwright`,
`Windows\Temp`, `SoftwareDistribution` sin cambio). Conclusión honesta: **el consumo medido no es
un árbol que se pueda borrar**; es escritura de procesos con asignación diferida (paginación,
cachés del sistema, compresión, otros repos). Y una parte de ese `python.exe` es **este mismo
diagnóstico**: medir cuesta disco, y así queda registrado.

La caída de 7,731 GiB del `2026-10-23T05:55:56Z` está registrada como la del día perdido, con el
guard actuando a 0,48 GiB.

### Las lecturas de 0,00 GiB no son un error de medición

`DISK_READING_SEMANTICS.json` → **`REAL_AVAILABILITY_ZERO`**:

- 7 lecturas exactamente `0` y 18 por debajo de 50 MiB;
- el par de instrumentos (`shutil.disk_usage` → `GetDiskFreeSpaceEx` y la llamada directa) coincide
  **byte a byte en todas**: 3.888.033.792 B, diferencia 0;
- el tick **escribió su propia línea de log** mientras reportaba 0 → había sectores para un log,
  no para el almacén;
- matiz que no se redondea: Windows reserva espacio que no ofrece al usuario, así que «0
  disponible» es agotamiento del **espacio disponible**, no del disco físico.

### Las 72 filas perdidas y su causa

`LOST_ROWS.json`, reconstruido hora a hora desde el store:

| Estado | Horas UTC | Por activo |
| --- | --- | --- |
| `LATE` (lag > 120 min) | 00, 01, 02 | 3 |
| `ADMISSIBLE` | 03–10 | 8 |
| `MISSING` | 11–23 | 13 |
| **Total declarado del día** | | **24 × 3 activos = 72** |

Cadena causal, con las horas exactas: el guard rechazó **25 ticks entre `00:10:56Z` y
`06:55:57Z`** con 0 GiB disponibles; las barras que se recuperaron después llegaron con **281, 221
y 161 minutos** de lag, por encima del límite de 120; la política de lag de la fase 3 excluye el
día completo si contiene una sola barra inadmisible. **Un día entero cuesta 72 filas, no una.**
De las 72, el store conserva **24 admisibles**, y aun así el día queda fuera: no se re-fetcheó,
no se re-timbró y no se reclasificó nada.

## 4. Alarma: DEF-02I-02 corregido, con dos testigos

Se reutilizó el único canal que existe y puede probar recepción: toast de Windows atribuido al
AUMID de PowerShell, con lectura de vuelta del historial de notificaciones por *tag*.

| Etapa | Evidencia | Instante |
| --- | --- | --- |
| Detección | máquina de estados del watchdog → `DEGRADED` (3,67 GiB < 5 GiB) | `2026-10-23T11:32:02Z` |
| Generación | `alert_id` determinista por transición + instante | — |
| Envío | toast, helper exit 0 | `11:27:46Z`, `11:27:58Z` |
| **Recepción** | `receipt: true`, historial del SO leído por tag (6 entradas) | verificado a `11:35:33Z` y de nuevo por el verificador |

- **Duplicados:** el ledger compara id y condición; una repetición dentro del *cooldown* de 6 h se
  registra como `suppressed` y **no llega al canal** (probado en test, no en producción).
- **Falta de ejecución del watchdog:** tarea independiente `TradingAgentic-EDGE04-Alarm` cada 10
  min; si `WATCHDOG.json` envejece más de 50 min, alerta. Y el watchdog degrada si el supervisor
  envejece más de 50 min: **cada uno vigila la ausencia del otro** (`SCHEDULER_EVIDENCE.json`,
  chequeo `SCHEDULE_FIRES_WITHOUT_AN_OPERATOR`).
- **Dos ciclos automáticos consecutivos, sin operador:**

| Tarea | Última ejecución | Resultado | Artefacto escrito | Desfase |
| --- | --- | --- | --- | --- |
| `…-Watchdog` | `2026-10-23T11:47:01Z` | 1 (`DEGRADED`) | `WATCHDOG.json` `11:47:02Z` | **1,0 s** |
| `…-Alarm` | `2026-10-23T11:48:01Z` | 0 (`WATCHDOG_ALIVE`) | `SUPERVISOR.json` `11:48:02Z` | **1,0 s** |

- `ALERT_DELIVERY = PASS_LOCAL`, `ALERT_REMOTE = BLOCKED`. Sin webhook, sin SMTP, sin permiso de
  event log: **una avería nocturna se registra, no se entrega**. `LastTaskResult` ya no es la
  única prueba porque hay un segundo proceso que lee el heartbeat del primero.

## 5. Candidatos de espacio: nada ajeno se tocó

60 candidatos, **38,40 GiB** clasificados. `SAFE_OWNED` 0,001 GiB (borrado). Todo lo demás queda
intacto con la acción exacta que requeriría autorización (`DIAGNOSIS.json`):

| Ruta | Tamaño | Propietario | Riesgo | Alternativa | Acción que requiere autorización |
| --- | --- | --- | --- | --- | --- |
| `C:\Users\GVLLFR0035\AppData\Local\wsl` | 6,16 GiB | usuario (distros WSL), 279 h sin escribir | destruye el FS de la distro | `Optimize-VHD` (módulo Hyper-V) | `wsl --unregister <distro>` |
| `C:\ESD` | 4,58 GiB | staging de Windows Setup | rompe la recuperación/actualización | mover a otro volumen | borrar staging con permisos de administrador |
| `%LOCALAPPDATA%\ms-playwright` | 3,28 GiB | usuario (automatización) | los tests de otros proyectos lo re-descargan | compartir entre proyectos | borrar builds no usados |
| `%LOCALAPPDATA%\hermes` | 2,77 GiB | usuario (tooling) | pierde el runtime del agente | archivar a otro volumen | limpieza del dueño |
| `C:\tmp` | 1,98 GiB | sesiones anteriores de este repo | **activo/protegido** | — | no tocar |
| Worktrees en `Downloads` (`bot_crypto_004g`, `github analisis_e13bd`, `bot-freebuff-*`) | 0,46–0,99 GiB c/u | usuario/repo | pierde artefactos de experimentos previos | `git bundle` + `git archive` a otro volumen | borrar árboles ajenos a este paquete |
| `C:\Windows\SoftwareDistribution\Download` | 0,51 GiB | Windows Update | reintenta la descarga | `Dism /StartComponentCleanup` (admin) | limpieza de actualizaciones |
| `%TEMP%\pytest-reports2` | 0,46 GiB | cualquier proceso | basura de tests | — | purga del dueño de `%TEMP%` |
| `C:\Users\GVLLFR0035\Downloads\bot freebuff` | 8,23 GiB | usuario (worktree principal) | **activo** (ticks cada 15 min) | — | no tocar |

Suma aprobable ≈ **26,57 GiB**; tras un traslado/borrado de los cinco mayores habría margen para
el p90. No se solicitó elevación ni se borró nada ajeno: **la decisión es del dueño del host**.

## 6. La campaña no se movió

| Control | Estado |
| --- | --- |
| Inicio | `2026-10-23T00:00:00Z` — sin cambios |
| Fin preinscrito | `2027-01-21T00:00:00Z` — 90 días |
| Cobertura exigida | 0,9 — sin cambios |
| Filas declaradas | 6.480 — sin cambios |
| Suelo de protección | 2 GiB, y aviso a 5 GiB, en el módulo del guard — `FLOOR_UNCHANGED` |
| Store | `runs.jsonl` y `health.json` byte a byte idénticos tras ejecutar estas herramientas |
| Datos observados | ni una fila reescrita; el día perdido sigue perdido |

Y el lane sigue vivo, que es la otra mitad de la pregunta: el tick de `11:40:55Z` salió
`OBSERVED` con **3,36 GiB** libres y **3 barras nuevas**, y los tres activos tienen ya **11 filas**
del día (horas 00–10), de las cuales 8 son admisibles. Por encima del suelo de 2 GiB la campaña
observa; lo que no hace es publicar pesado, y eso es exactamente lo que el guard debe hacer.

Cobertura restante:

- filas aún alcanzables: **6.408 / 6.480** → techo **0,9889**; `COVERAGE_COMPLETE` es inalcanzable;
- suelo 0,9: **5.832 filas** → margen de **576 filas = 8 días completos** más, como máximo;
- días restantes de ventana: **89**.

## 7. Pruebas ejecutadas de verdad

`TEST_EVIDENCE.json` — `pytest tests/unit/research/test_exp004a_wp051_02j.py -q`:

```
15 passed in 0.13s        exit 0        suite sha256 20850bdf… (igual al del fichero en disco)
```

(duración total registrada por el recogedor, 1,84 s: incluye el arranque del intérprete).

Cubre: clasificación conservadora (nunca `SAFE_OWNED` para árboles ajenos; un proceso con handle
manda sobre la edad; mtime ilegible → `UNKNOWN`), reconstrucción del día perdido (admisible ≠
presente), presupuesto sobre p90 y no sobre el máximo, un solo rechazo histórico basta para
`INSUFFICIENT`, id de alerta determinista y válido como tag, supresión de duplicados, canalque no prueba recepción **no es entrega**, supervisor que grita ante watchdog callado, supervisor
callado que degrada al watchdog, y `--clean` que respeta lo que Git sigue. Además: un ledger que no
se puede escribir **devuelve `ERROR:` en vez de lanzar** (una avería no se convierte en dos) y la
evidencia se escribe de forma atómica, sin `.part` huérfanos al releerla.

Fallo conocido y ajeno a este paquete: ejecutar el **directorio** `tests/unit/research` completo
sigue rompiendo por un import preexistente en `test_exp004a_wp051_02g.py` (DEF-02I-08). Este
paquete no lo toca; su suite se ejecuta por fichero, con exit 0 real.

## 8. Verificación independiente (`BUILDER != VERIFIER`)

`scripts/exp004a_wp051_02j_verify.py` → **15/15 PASS**, exit 0, sin importar el constructor:

```
DIAGNOSIS_PRESENT · CLASSIFICATION_IS_CONSERVATIVE · CANDIDATE_SIZES_RECOMPUTED ·
READING_SEMANTICS_RECOMPUTED · LOST_DAY_RECOMPUTED · CAPACITY_ARITHMETIC ·
ALERT_HAS_A_RECEIPT · NO_DUPLICATE_DELIVERY · CHANNELS_STATE_THEIR_LIMITS ·
SCHEDULE_FIRES_WITHOUT_AN_OPERATOR · TESTS_RAN_AND_PASSED · CONTRACT_UNCHANGED ·
FLOOR_UNCHANGED · TOOLS_DO_NOT_TOUCH_THE_STORE · VERDICT_IS_HONEST
```

El verificador vuelve a medir el volumen, re-cuenta las horas del día perdido, recalcula p90 y
presupuesto, **re-consulta `schtasks` por su cuenta** y **re-hashea la suite** antes de aceptar el
registro de tests. `INDEPENDENT_VERIFIER = PROGRAM_NOT_PERSON` sigue siendo cierto.

## 9. Riesgos pendientes

1. **`DEF-02I-01` BLOCKED.** 11,317 GiB de déficit frente al p90. Sin intervención del dueño del
   host, la campaña seguirá perdiendo días en cada episodio de 0 GiB. Margen actual: **8 días**.
2. **`ALERT_REMOTE` BLOCKED.** La alerta llega a esta máquina y a nadie más. Con el watchdog
   resuelto, el riesgo ya no es «nadie evalúa el estado» sino «nadie está delante a las 3:00».
3. **Origen de la caída no atribuido a un fichero.** 99,6 % del descenso está en contadores de
   proceso, 0 % en los árboles vigilados: no hay nada que borrar, hay que dejar de escribir tanto.
4. **`DEF-02I-07`**: `LogonType=Interactive` sin probar (requiere administrador). Una sesión
   cerrada detiene las dos tareas y el toast no puede mostrarse; el supervisor lo detectaría al
   reabrir, no mientras tanto.
5. **`DEF-02I-08`**: el directorio de tests sigue sin correr entero por un import ajeno.

## 10. Dictamen

**`BLOCKED`** — `capacity=INSUFFICIENT` (déficit 11,317 GiB en p90), `alerts=PASS_LOCAL`,
`alerts_remote=BLOCKED`, `schedule=PASS` (2/2 tareas disparando), `tests=PASS` (15/15),
`verification=PASS` (15/15), `campaign_controls=UNCHANGED`.

No se declara PASS: un `PASS` con 3,26 GiB libres y una caída p90 de 12,47 GiB sería exactamente
el falso éxito que este paquete existe para impedir. Lo que sí cambió: **el fallo ahora se ve, se
prueba y se registra sin que nadie esté mirando**.

## 11. Reanudación verificable

```bash
cd "/c/Users/GVLLFR0035/Downloads/bot-freebuff-exp004a-02h"
MAIN="/c/Users/GVLLFR0035/Downloads/bot freebuff"
PY="$MAIN/.venv/Scripts/python.exe"

"$PY" scripts/exp004a_wp051_02j_recovery.py --scheduler    # 2/2 firing, desfase ~1 s
"$PY" scripts/exp004a_wp051_02j_recovery.py --tests        # 15 passed, exit 0
"$PY" scripts/exp004a_wp051_02j_recovery.py --capacity     # INSUFFICIENT + déficit
"$PY" scripts/exp004a_wp051_02j_recovery.py --channels     # PASS_LOCAL / remote BLOCKED
"$PY" scripts/exp004a_wp051_02j_recovery.py --report       # veredicto BLOCKED
"$PY" scripts/exp004a_wp051_02j_verify.py                  # 15/15 PASS, exit 0
schtasks /query /tn TradingAgentic-EDGE04-Watchdog /v      # último resultado
schtasks /query /tn TradingAgentic-EDGE04-Alarm /v         # último resultado
```

Artefactos: `DIAGNOSIS.json`, `DISK_READING_SEMANTICS.json`, `LOST_ROWS.json`,
`CONSUMPTION_ATTRIBUTION.json`, `CAPACITY_PLAN.json`, `ALERT_CHANNELS.json`,
`SCHEDULER_EVIDENCE.json`, `TEST_EVIDENCE.json`, `CLEANUP_EVIDENCE.json`,
`INDEPENDENT_VERIFICATION_02J.json`, `FINAL_REPORT_02J.json`, este informe.
