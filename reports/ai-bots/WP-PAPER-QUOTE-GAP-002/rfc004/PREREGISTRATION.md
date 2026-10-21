# PREREGISTRATION — RFC-PAPER-RECOVERY-004 / WP-003-01

Predicciones y oráculos fijados **antes** de ejecutar la matriz de crashes. El laboratorio
(`scripts/recovery_lab.py`) no decide qué es un PASS: compara lo observado con esta tabla, y
el verificador independiente vuelve a derivar el resultado desde los artefactos.

## Escenario y semilla

Una sesión `PAPER` sobre 22 velas de 1 h abre una posición y termina con ella abierta
(`OPEN_AT_END`). La reanudación recibe la misma serie con la vela 22 **ausente** y un feed
de 60 minutos que prueba que el stop se cruzó en el minuto 15 (`low=99.0`). Es el escenario
de regresión de WP-PAPER-RESUME-001, que aquí se corta en cada punto de escritura real.

- Semilla: 1 posición abierta, 0 cierres, barrera = vela 21, ledger con `RUN`.
- Control: reanudar sin caída → 1 cierre, 0 posiciones, `equity = 9996.380966197243`.
- Toda comparación es el **digest canónico**: proyección económica con `Decimal` exacto
  (posiciones, caja, cierres, comisiones, PnL, riesgo, marcas, pendientes, contrato,
  barrera), sin `session_id` ni contadores de sesión.

## Predicciones (selladas)

| # | Predicción | Cómo se refuta |
|---|---|---|
| P1 | Una caída **antes** del `replace` deja el libro de la semilla, sin el cierre | `canonical(post-crash) != canonical(seed)` o `closes != 0` |
| P2 | Una caída **después** del `replace` deja el cierre comprometido y el libro es reanudable | `closes != 1` o `store.recover()` no devuelve `NO_CHANGE`/`RECOVERED` |
| P3 | Exactamente **una** fila `CLOSE` por efecto, caiga donde caiga la caída | recuento de filas `CLOSE` ≠ 1, o `operation_id` duplicado |
| P4 | La segunda reanudación no escribe filas ni mueve un dígito | aparece una fila `CLOSE` nueva o el digest cambia |
| P5 | Un libro manipulado se rechaza (`CorruptBook`) y se conserva; una fila de ledger manipulada se rechaza (`OperationConflict`) | cualquiera de los dos se acepta o se «repara» |
| P6 | Dos reanudaciones simultáneas: una gana, la otra recibe `SessionBusy`, un solo cierre | dos cierres, o dos procesos corriendo |
| P7 | Un libro histórico de RFC003 se lee, su digest se re-deriva y ningún fichero cambia | cualquier `sha256` distinto tras dos pasadas |
| P8 | Cero peticiones externas; la ruta live se niega antes de abrir un socket | cualquier intento no-loopback o `place_order` con éxito |
| P9 | El alcance de durabilidad es `PROCESS_CRASH_VERIFIED` y `POWER_LOSS_DURABILITY_NOT_VERIFIED` | un informe que afirme más |

## Oráculos por escenario

| ID | Punto de corte | Estado esperado tras la caída | Oráculo final |
|---|---|---|---|
| `CR-00` | ninguno (control) | — | 1 cierre, digest = control, `exit 0` |
| `CR-01` | `ledger.before_write` | libro = semilla, 0 cierres | digest = control, 1 fila `CLOSE` |
| `CR-02` | `ledger.after_write` (sin fsync) | semilla o comprometido | digest = control, 1 fila `CLOSE` |
| `CR-03` | `book.after_tmp_fsync` | libro = semilla, `.tmp` completo | digest = control, 1 fila `CLOSE` |
| `CR-04` | `book.after_tmp_write` | libro = semilla, `.tmp` parcial | digest = control, 1 fila `CLOSE` |
| `CR-05` | `book.after_prev_copy` | libro = semilla, `.prev` = semilla | digest = control, 1 fila `CLOSE` |
| `CR-06` | `book.after_replace` | **comprometido** (barrera 21, 1 cierre) | digest = control, 1 fila `CLOSE` |
| `CR-07` | `bar.after_commit` (ACK) | comprometido | dos reanudaciones: 0 cierres nuevos, digest idéntico |
| `CR-08` | `ledger.after_fsync` × 3 reintentos | semilla + fila | 1 efecto, 1 fila, ≥1 duplicado suprimido |
| `CR-09` | sin failpoint, dos procesos | — | 1 proceso corre, 1 recibe `SessionBusy`, 1 cierre |
| `CR-10` | lock huérfano / lock vivo | — | huérfano relevado; vivo respetado; sin duplicado |
| `CR-11` | libro y ledger editados | libro manipulado | `CorruptBook` + cuarentena; `OperationConflict` |
| `CR-12` | proyección atrasada / adelantada | libro atrasado o adelantado | atrasado se reconstruye; adelantado se rechaza (`PROJECTION_BEHIND_AUTHORITY`) |
| `CR-13` | `.tmp` huérfano / `replace` fallido | — | no se adopta el `.tmp`; el fallo no deja estado parcial |
| `CR-14` | libro RFC003 (`drill/A`) | ninguno | lectura estable, 3 ficheros byte-idénticos |
| `CR-16` | ruta live + socket | — | `place_order` se niega (`exit 2`), hook de red real, 0 intentos externos |

`CR-15` (identidad falsificada) no es una fila del laboratorio: lo cubre
`scripts/verify_recovery.py` con sus propios controles negativos, cada uno de los cuales
debe ser **rechazado**.

## Regla de false success

- Un escenario sin hijo con `exit 86` no es PASS, aunque su estado final coincida.
- Un PASS con un check fallido dentro no es PASS.
- Un escenario que no se ejecuta queda declarado en `counts.not_testable`; nunca se cuenta
  como superado.
- `PAPER_VALIDATION = NOT_PERFORMED` y `EXTERNAL / RECONCILIATION = NOT_VERIFIABLE` no
  cambian por ningún resultado de este laboratorio.

## Enmiendas posteriores al primer arranque (declaradas, no silenciadas)

La primera pasada de la matriz (13/16) encontró tres defectos **en el propio laboratorio**,
no en el runtime. Se corrigen y se dejan escritos porque un preregistro que se edita sin
decirlo no vale nada:

1. **`CR-06` esperaba el estado final del control.** La caída cae en el commit *intermedio*
   del plan de hueco (barrera 21, no 24): el oráculo correcto es «el cierre está
   comprometido y el libro es reanudable», no «idéntico al control». El estado final sí debe
   coincidir, y se sigue exigiendo.
2. **`CR-10` exigía 0 cierres en la reanudación posterior al lock vivo.** Esa reanudación sí
   contabiliza el cierre: el oráculo correcto es `exit 0`, 1 cierre y digest = control.
3. **`CR-13` inspeccionaba el `.tmp` después de reanudar.** El `save` reutiliza ese nombre y
   el `replace` lo consume, así que el `.tmp` huérfano sólo es observable **antes** del
   siguiente commit. Se añade una lectura intermedia.
4. **`CR-14` pasaba un ledger vacío como proyección.** Un ledger vacío no es una proyección:
   hacía que `recover()` rechazara el libro histórico por «faltar» filas que nunca
   existieron. Ahora la comprobación de proyección sólo se hace si el ledger tiene filas.

Ninguna enmienda relaja un umbral: las cuatro cambian *qué se observa*, y las cuatro
endurecen el escenario correspondiente (`CR-06` y `CR-13` ahora exigen más, no menos).
