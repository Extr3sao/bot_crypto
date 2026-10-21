# RUN_REPORT — WP-PAPER-RESUME-001

**Fecha:** 2026-10-20 · **Rama:** `agent/ai-bots/RFC-TAP-AI-BOTS-003`
**Modo:** PAPER · **LIVE:** no habilitado (`live_orders=0`) · **`REAL_MODEL_CALLED=false`**
**`FALSE_SUCCESS=0`** · **Veredicto del drill:** **PASS** (`RT-07`, `REC-03`, `REC-04`, `REC-05`)

Los números de este informe salen de `drill/DRILL.json`, `VERIFICATION.json` y los hashes de los
ficheros que se ejecutaron ([scripts/make_resume_report.py](../../../scripts/make_resume_report.py)
los regenera desde disco). Nada está transcrito a mano salvo los resultados de tests, que llevan
su comando y su exit code.

---

## 1. El defecto que se cierra

`roundtrip-5m` terminó con **dos cortos abiertos**: `RUN_END` publicó las posiciones y nada las
restauró. Un reinicio empezaba plano, así que las dos posiciones sólo podía cerrarlas el proceso
que ya no existía. El mapa de runtime lo dejó escrito como hueco:

> «no hay persistencia del libro en esta ruta; un reinicio empieza plano»

Ahora hay un libro en disco (`STATE/BOOK.json`), un punto de commit por vela, y una sesión que
se niega a arrancar plana si el libro dice que había exposición.

## 2. Entorno congelado

```text
$ git rev-parse --abbrev-ref HEAD && git rev-parse HEAD
agent/ai-bots/RFC-TAP-AI-BOTS-003
<HEAD del commit que contiene este informe>          # DRILL.json guarda el suyo
```

| fichero | sha256 (primeros 16) |
| --- | --- |
| `src/trading_bot/vision/durable.py` | `00e4f414dd9808d4` |
| `src/trading_bot/vision/prospective.py` | `2e4c026db6e20a83` |
| `src/trading_bot/vision/lane.py` | `fd5b6114b49dbaa3` |
| `src/trading_bot/vision/ledger.py` | `2eb5b6a70ce2d46b` |

`DRILL.json → environment.runtime_sha256` lleva los hashes completos **del momento del drill**;
`RUN_REPORT.json` los recalcula al generarse. El drill se repitió después del último cambio de
código para que ambas cosas sean el mismo byte.

## 3. Dataset

Minutos reales archivados (`binance_spot_rest_1m`), resampleados a 5m, **sin red durante el drill**:

| símbolo | barras 5m | ventana (UTC) | `minutes_sha256` |
| --- | --- | --- | --- |
| `ETH/USDT` | 144 | `2026-10-20T08:55Z → 20:50Z` | `aa7f0845a7ca20d4…` |
| `SOL/USDT` | 144 | `2026-10-20T08:55Z → 20:50Z` | `64b777f320bc1960…` |

## 4. Experimento A/B

Misma campaña, mismos minutos, dos formas de vivirla:

- **A — continua:** un proceso de principio a fin (1 sesión).
- **B — interrumpida:** un proceso que **muere sin cierre ordenado** (`TerminateProcess` a los
  9.0 s, exit code 1) y otro que **reanuda el mismo libro** y termina.

| | A (continua) | B (interrumpida) |
| --- | --- | --- |
| sesiones | 1 (`A-continuous`) | 2 (`B-1` muerta, `B-2` reanudada) |
| `state_digest` | `ee315b364bef5622…` | `ee315b364bef5622…` ← **idéntico** |
| barrera final | `1792529400000` | `1792529400000` |
| velas comprometidas | 144 | 144 |
| filas en `BOOK_EVENTS.jsonl` | 145 (`A-continuous`) | 145 = 68 de `B-1` + 77 de `B-2` |
| operaciones cerradas | 16 | 16 |
| posiciones abiertas al final | 2 | 2 |
| diferencias campo a campo | — | **ninguna** |

**Qué recuperó `B-2` exactamente** (`drill/B/B-2.json → recovery`):

```text
RECOVERED at bar 1792506600000: 2 open, 8 closed, equity 10008.28548442
resume_from_ms = 1792506900000        (la vela siguiente a la barrera, no la última vista)
9/9 checks en ok                      (contract, barrier, dataset_prefix, equity_identity,
                                       closed_history, position_structure, risk_vs_mark,
                                       resume_bar_available, barrier_is_continuous)
```

`B-1` murió en la vela 68 de 144 **con dos posiciones abiertas**: es el escenario del defecto, no
una variante cómoda. `B-2` no empezó plano, no reabrió las posiciones y no volvió a cobrar la
comisión de entrada (16 cierres en ambos brazos, no 16 y 18).

**Sobre los dos digests.** `state_digest` cubre el libro económico y **debe** coincidir: es la
invariante `RT-07`. `integrity_digest` cubre además la cadena de sesiones, así que difiere por
diseño (A tiene una apertura de sesión, B dos). Comparar el segundo habría declarado un fallo
falso; comparar sólo el primero habría ocultado una sesión que no se registró.

## 5. Verificación independiente

`scripts/verify_paper_resume.py` no importa el verificador de la librería: recalcula el libro
desde los ficheros publicados.

```text
26/26 checks PASS          exit 0
9/9  controles negativos   detectados
FALSE_SUCCESS = 0
```

| control negativo | lo mata |
| --- | --- |
| `pnl_inflado` | `A.equity_identity` |
| `equity_inventada` | `A.equity_identity` |
| `posicion_duplicada` | `A.no_shared_identity` |
| `posicion_a_la_vez_cerrada` | `A.no_shared_identity` |
| `nocional_incoherente` | `A.position_structure` |
| `riesgo_desalineado` | `A.risk_agrees_with_mark` |
| `digest_falso` | `A.integrity_digest` |
| `cierres_borrados` | `A.equity_identity` |
| `sin_reinicio_real` | `b.restarted` |

Dos de ellos no los mata el hash, los mata la aritmética: un `BOOK.json` con el hash recalculado
encima sigue sin financiarse (`equity_identity`) y una posición con el nocional multiplicado por
10 sigue sin cuadrar con precio × cantidad (`position_structure`).

## 6. Comandos ejecutados (exit code real)

```text
pytest tests/unit/vision/test_durable_book.py tests/unit/vision/test_session_recovery.py \
       tests/unit/vision/test_session_durable.py tests/unit/vision/test_prospective_session.py -q
  51 passed                                                          exit 0
pytest tests/unit/vision tests/unit/paper tests/unit/risk tests/unit/market_data -q
  641 passed, 14 failed                                              exit 1
pytest tests/unit/vision/test_minute_quote_feed.py \
       tests/unit/vision/test_subbar_execution.py -q    (con data/quote-feed-1m copiado)
  22 passed                                                          exit 0
ruff check <10 ficheros nuevos o tocados>                            exit 0
mypy src/trading_bot/vision/{durable,prospective,lane}.py
  Success: no issues found in 3 source files                         exit 0
python scripts/paper_resume_drill.py --archive <roundtrip-5m/market-1m> … --kill-after 9
  verdict PASS (RT-07, REC-03, REC-04, REC-05)                       exit 0
python scripts/verify_paper_resume.py --drill … --negative-controls
  26/26, 9/9 controles                                               exit 0
```

**Los 14 fallos son de fixture, no de código.** `test_minute_quote_feed.py` y
`test_subbar_execution.py` leen `data/quote-feed-1m/`, que esta copia del repo no trae (vive en el
checkout hermano). Con el directorio presente, **los mismos dos ficheros dan 22 passed / 0
failed**. Se copió, se midió y se borró: el árbol no queda con datos ajenos.

## 7. Defectos del arnés encontrados y corregidos en esta pasada

Ninguno de los dos afectaba al producto, pero los dos podían producir un PASS falso:

1. **El drill heredaba libros de la corrida anterior.** Un hijo veía la barrera ya en la última
   vela, salía limpio en 4.4 s y el A/B comparaba un libro viejo consigo mismo — con un `PASS`
   en la salida. Ahora el drill borra `A/` y `B/` antes de empezar (`shutil.rmtree`).
2. **El veredicto no exigía que el kill hubiera ocurrido.** `REC-04` se publicaba como
   `NOT_EXERCISED` y el veredicto global seguía diciendo `PASS`. Ahora `verdict=PASS` exige
   `killed=True`, y cuando no lo hay el `DRILL.json` lleva `note` explicando que no se midió nada.

Y uno del producto, que sólo se veía al leer el libro real:

3. **`RECOVERY.checks` publicaba frases de fallo en checks que pasaban**
   (`equity_identity: ok=true, detail="initial 10000.0 + sum(closed pnl) 8.285 != equity 10008.285"`).
   Quien lee eso en un incidente no puede saber a cuál de las dos señales creer. `_check` ahora
   separa `detail` (lo observado al pasar) de `fail_detail` (la frase del fallo), y el test
   `test_a_passing_check_never_carries_the_text_of_a_failure` lo sostiene.

## 8. Lo que este informe **no** afirma

- No afirma nada sobre LIVE: no hay ruta de orden, `live_orders=0`, `live_enabled=false`.
- No afirma nada sobre el modelo real: la señal es el provider determinista del replay.
- No afirma nada sobre latencia de red: el drill corre sobre minutos ya archivados.
- No cubre dos escritores simultáneos sobre libros **distintos** del mismo `book_id`; cubre el
  caso de dos procesos sobre el mismo directorio, que es lo que el `SessionLock` resuelve.
- Los 641 tests de la suite amplia no incluyen los 14 de fixture ausente; se midieron aparte y se
  reportan como lo que son.
