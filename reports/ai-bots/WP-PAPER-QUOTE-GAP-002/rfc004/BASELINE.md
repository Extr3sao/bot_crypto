# BASELINE — RFC-PAPER-RECOVERY-004 / WP-003-01-00

Captura **read-only** antes de la primera edición. Worktree `bot-freebuff-recovery-004`,
creado desde el commit de evidencia de RFC003 y limpio en el momento de la captura.

| Hecho | Valor |
|---|---|
| `HEAD` | `0c074fb4f3e22bb10407cb8af12ae94f8db480bc` (`wp/paper-resume-001` → rama nueva `wp/recovery-004`) |
| `git status --porcelain -uall` | vacío, 0 ficheros |
| submódulos | ninguno |
| plataforma | Windows 10.0.26200, NTFS, `os.name=nt` |
| intérprete | `.venv/Scripts/python.exe` (Python 3.11.15, `uv sync --frozen`) |
| `uv.lock` | `ff7082182db53356e025e44952509b3147ee31f786874f1bd61ba25c55a1a9d0` |
| suite base | `695 passed`, `exit 0`, 1027.9 s (`vision + paper + risk + market_data`) |

## Qué se ha medido antes de tocar nada

- Los puntos reales de persistencia: `BOOK.json.tmp` (write → flush → fsync), copia de la
  generación anterior a `.prev` (fsync), `os.replace`, `_fsync_dir` (que en `nt` **no hace
  nada**), y el evento `COMMIT` (append → flush → fsync). El ledger de sesión escribe y
  fsyncea una línea por fila.
- La autoridad real: **el libro** (`BOOK.json`) es la verdad económica; el ledger es una
  proyección append-only; `BOOK_EVENTS.jsonl` cuenta *cómo* se hizo verdad. `reconcile_book`
  nunca lee el ledger. Esto **contradice** la propuesta de §5.1 del RFC, que asume que el
  ledger es autoritativo: el diseño conserva el contrato existente y lo declara.
- El punto de `COMMIT`: un compás está comprometido cuando `save()` vuelve con
  `os.replace` hecho. El ACK es el fsync del evento `COMMIT`, que ocurre **después**; por
  eso el ACK no puede preceder a la materialización.
- Que el lane no importa `ccxt`: sólo `vision/provider.py` (httpx) tiene capacidad de red,
  y el lane recibe el proveedor. El incidente de RFC003 (`ccxt.binance()` hace HTTP en el
  constructor) sigue siendo la razón para aislar la red a nivel de proceso.

## Defectos que el baseline ya deja a la vista

1. El commit que contabiliza una reconstrucción de hueco publica `risk_equity` distinto de
   `marked_equity` (`9997.26097534` vs `9996.3809662` en la semilla del laboratorio): la
   parte no realizada del cierre se cuenta dos veces y el libro queda **irreanudable**
   (`RISK_MISMATCH`). Está medido en `test_the_commit_that_books_a_reconstruction_can_be_resumed`.
2. No existe ningún punto de inyección en las llamadas de persistencia, así que la ventana
   `ledger fsync → book replace` no se había interrumpido nunca en el runtime real.
3. Una cola rota en `BOOK_EVENTS.jsonl` o en el ledger de sesión hace fallar la siguiente
   apertura en vez de clasificarse.
4. Una fila `CLOSE` no lleva identidad económica, así que un compás re-ejecutado tras una
   caída escribe una segunda fila por un solo efecto.

Los cuatro se abordan en `PERSISTENCE_PROTOCOL.md`; el 1 es un arreglo de runtime, no de
laboratorio, y por eso lleva test propio en la suite.

## Lo que el baseline **no** demuestra

- `POWER_LOSS_DURABILITY_NOT_VERIFIED`: NTFS no permite fsync de directorio desde Python y
  ningún escenario de este WP corta la alimentación. Un `os.replace` que devuelve 0 prueba
  el orden lógico, no la persistencia tras un corte eléctrico.
- Nada sobre el exchange: `EXTERNAL_ORDERS / RECONCILIATION = NOT_VERIFIABLE`.
- Nada sobre rentabilidad: `PAPER_VALIDATION = NOT_PERFORMED`.
