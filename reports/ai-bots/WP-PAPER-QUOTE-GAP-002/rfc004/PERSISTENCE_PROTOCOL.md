# PERSISTENCE PROTOCOL — lo que el runtime garantiza y lo que no

Este documento describe el protocolo **tal como queda implementado** en
`src/trading_bot/vision/{durable,ledger,lane,failpoints}.py`, con la autoridad que el
código ya tenía (libro > ledger). No propone un modelo nuevo: fija el existente, cierra la
ventana que no estaba instrumentada y declara su alcance.

## 1. Escritura de un compás

```
1  validar intención, precios e idempotencia           (en memoria; nada durable)
2  aplicar fills/cierres al broker y al risk engine
3  ledger.append(FILL|CLOSE, operation_id=…)           fsync por fila  (proyección: puede ir por delante)
4  _commit(barrier=n):
4a     failpoint bar.before_commit
4b     escribir BOOK.json.tmp  → flush → fsync          failpoints after_tmp_write / after_tmp_fsync
4c     copiar BOOK.json → BOOK.json.prev → fsync        failpoint after_prev_copy
4d     os.replace(tmp, BOOK.json)                       **COMMIT** · failpoint after_replace
4e     fsync del directorio                             no-op en nt · failpoint after_dir_fsync
4f     append BOOK_EVENTS.jsonl (COMMIT) → fsync         **ACK** · failpoints event.after_write / after_fsync
5  failpoint bar.after_commit
```

Invariantes:

- **Un solo escritor.** `SessionLock` con `O_CREAT|O_EXCL`, pid+host+token, relevo serializado
  por un segundo fichero; un lock cuyo pid vive se respeta siempre (un timeout no es permiso).
- **Ninguna generación desaparece.** `.prev` es una *copia*, no un rename: nunca existe un
  instante en que `BOOK.json` no esté. Un `.prev` sin `BOOK.json` es una rotación
  interrumpida → `REFUSED_AMBIGUOUS_COMMIT`, nunca «el libro antiguo».
- **El ACK no precede a la materialización.** El evento `COMMIT` se escribe después del
  `replace`. Si el proceso muere entre 4d y 4f, el libro está comprometido y el evento
  falta: `recover()` lo llama `commit_event_lag` y **no** inventa un rollback.
- **El `digest` viaja dentro del fichero.** Un byte editado en `body` no cuadra con su
  digest → `CorruptBook` + cuarentena `BOOK.corrupt.<ms>.json`, sin reparación.

## 2. Exactly-once del efecto económico

El efecto vive **una vez** en `BOOK.json` (`closed_trades`/`open_positions`), y la barrera
impide re-procesar un compás ya cubierto. La proyección puede repetirse; para que eso no se
convierta en evidencia duplicada:

- Cada fila económica lleva `operation_id = <book_id>|CLOSE|<position_id>` (o `|FILL|`).
- `DecisionLedger.append` compara la fila nueva con la ya comprometida: si son iguales
  salvo el reloj (`recorded_at_utc`), no escribe y cuenta `duplicates_suppressed`; si
  difieren en cualquier campo, lanza **`OperationConflict`** y no escribe nada.
- La deduplicación es por proceso y por fichero de ledger. La garantía económica no depende
  de ella: depende de la barrera. La deduplicación protege la **evidencia**.

## 3. Recuperación (`LaneBookStore.recover`)

| Condición | Resultado |
|---|---|
| no hay libro, ni `.prev`, ni `.tmp` | `NO_CHANGE` |
| libro íntegro, evento congruente, proyección congruente | `NO_CHANGE` |
| libro íntegro con `.tmp` huérfano, evento retrasado o cola `REPAIR` | `RECOVERED` |
| libro con filas de proyección no comprometidas | `RECOVERED` (se listan) |
| `BOOK.json` ausente con `.prev` o `.tmp` presente | `REFUSED_AMBIGUOUS_COMMIT` |
| digest/parseo/esquema incorrectos | `REFUSED_CORRUPTION` |
| el ledger no tiene una fila para un cierre comprometido | `REFUSED_CORRUPTION` / `PROJECTION_BEHIND_AUTHORITY` |
| dos filas con el mismo `operation_id` | `REFUSED_CORRUPTION` / `DUPLICATE_OPERATION` |
| `BOOK.lock` con un pid vivo | `BLOCKED_LOCK` |

Reglas de cola:

- **Ledger**: una cola sin `\n` final, o una última línea que no parsea, es una escritura
  interrumpida: se recorta y el recorte se escribe en `<ledger>.torn.json`
  (`reason`, `offset`, `dropped_bytes`, `dropped_preview`) antes de continuar. Una línea rota
  **con una buena después** es una edición y no se toca (`verify_chain` la rechaza).
- **Eventos**: misma regla, y el recorte se registra como fila `REPAIR` *dentro* del propio
  log, de modo que la ausencia de un `COMMIT` no se pueda confundir con un log que nunca lo
  tuvo.
- Nunca se re-emiten al ledger las transacciones ya confirmadas para «ponerse al día».

## 4. Portabilidad y alcance de la garantía

| Nivel | Estado | Evidencia |
|---|---|---|
| `PROCESS_CRASH_VERIFIED` | **sí** | 16 escenarios con `os._exit` en la llamada real, recuperados por procesos nuevos |
| `OS_FILESYSTEM_DURABILITY_VERIFIED` | **no** | NTFS: `os.open(dir)` + `fsync` no existe en Python/Windows; el `replace` es atómico por el FS pero no hay fsync de directorio |
| `POWER_LOSS_DURABILITY_NOT_VERIFIED` | **obligatorio** | ningún escenario corta la alimentación; una emulación no se etiqueta como corte real |

Por eso el informe distingue siempre «el proceso murió y la cuenta se recuperó» de «los
bytes sobreviven a un corte eléctrico». Lo primero está medido; lo segundo no.

## 5. Coste

- Con nada armado, `failpoints.trigger` es una lectura de caché y un `return`: medido en el
  informe (`performance.trigger_ns`), no estimado.
- El `save` añade seis llamadas inertes y ninguna escritura; el fsync y el `replace` no se
  han movido.
- `recover()` es lectura pura y sólo corre al reanudar.

## 6. Failpoints

Ver `FAILPOINT_MATRIX.json`. Reglas duras: por defecto **OFF**; para armarse exigen
`TRADING_BOT_FAILPOINT` **y** `TRADING_BOT_FAILPOINT_SANDBOX`, y el fichero a interrumpir
debe estar dentro del sandbox (si no, `FailpointRefused`). Al dispararse llaman a
`os._exit` —no lanzan una excepción— para que ningún `except` del runtime pueda convertir
una caída en un éxito. El laboratorio es el único que arma el entorno; el proceso de tests
nunca lo hace salvo con un hook de observación explícito.
