# RUN REPORT — RFC-PAPER-RECOVERY-004

- `run_id`: `rfc004-20261021T150123Z`
- `source_commit`: `33ea87b5a881856e588dfb97e3a305037c2fca6f`
- `code_sha`: `33ea87b5a881856e588dfb97e3a305037c2fca6f`
- Decisión: **PASS (LAB ONLY)**
- `PAPER_VALIDATION = NOT_PERFORMED` · `EXTERNAL / RECONCILIATION = NOT_VERIFIABLE`

## Matriz de crashes

| ID | Adversario | Failpoint | Veredicto |
|---|---|---|---|
| `CR-00` | no crash: the reference run | `—` | PASS |
| `CR-01` | before the first durable write of the closing session | `ledger.before_write` | PASS |
| `CR-02` | after the ledger row was written, before its fsync | `ledger.after_write` | PASS |
| `CR-03` | the new book was written and fsynced, the replace has not happened | `book.after_tmp_fsync` | PASS |
| `CR-04` | the temporary projection is partly written | `book.after_tmp_write` | PASS |
| `CR-05` | the previous generation was copied, the replace has not happened | `book.after_prev_copy` | PASS |
| `CR-06` | the replace landed, the COMMIT event was never written | `book.after_replace` | PASS |
| `CR-07` | after ACK: the bar is committed | `bar.after_commit` | PASS |
| `CR-08` | the same operation_id retried three times | `ledger.after_fsync` | PASS |
| `CR-09` | two processes resume the same book at the same instant | `—` | PASS |
| `CR-10` | an orphan lock and a live lock around the same book | `—` | PASS |
| `CR-11` | a committed book and a committed ledger row are edited | `—` | PASS |
| `CR-12` | the projection is one commit behind, then one commit ahead | `—` | PASS |
| `CR-13` | an orphan temporary book and a replace that cannot land | `—` | PASS |
| `CR-14` | a committed book from RFC003 (WP-PAPER-QUOTE-GAP-002 drill A) | `—` | PASS |
| `CR-16` | the live order route and a socket, with the network denied process-wide | `—` | PASS |

## Suite

`.venv/Scripts/python.exe -m pytest -q tests/unit/vision tests/unit/paper tests/unit/risk` → **577 passed in 521.57s (0:08:41)**, `exit 0`, 521.57 s.

Repo completo: 101 fallos, de los cuales
0 no fallaban ya en el commit
padre `0c074fb4f3e22bb10407cb8af12ae94f8db480bc` (mismo conjunto de
ids). La suite de aceptación es el corte `vision/paper/risk`, que sale 0.

## Red

1 llamada(s) de socket auditada(s), todas loopback (control positivo);
`external_attempts = 0`. La ruta live devuelve
`2` sin `--confirm-live`.

## Equivalencia económica

`all_recovered_equal_control = True`; discrepancias:
ninguna.

## Coste

`failpoints.trigger` sin armar: 1414.6630000323057 ns/llamada
(200000 llamadas medidas). El `save` no cambia de forma: mismas
escrituras, mismos fsync.
