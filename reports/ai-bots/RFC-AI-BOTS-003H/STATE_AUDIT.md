# STATE_AUDIT — RFC-TAP-AI-BOTS-003H

**Auditoría hecha antes de tocar nada el 2026-10-19, con el árbol tal como estaba.** Cada fila
es un comando o una lectura de artefacto; lo que no se midió se dice.

## 1. Repositorio

```text
$ git rev-parse HEAD && git rev-parse --abbrev-ref HEAD
fe9b5e2623b0d023833249e9687b753eaacd27d4
agent/ai-bots/RFC-TAP-AI-BOTS-003
$ git log --oneline -1
fe9b5e2 Start automated children without a console window
$ git status --porcelain | wc -l
207
```

`fe9b5e2` sigue siendo HEAD: **nada de 003G ni de 003H estaba commiteado** al abrir este WP.

### 1.1 Propiedad de lo sucio (no se toca lo ajeno)

| Grupo | Rutas | Propiedad |
| --- | --- | --- |
| Cadena AI-BOTS | `src/trading_bot/vision/{lane,prospective,execution,quotes}.py`, `src/trading_bot/market_data/minute_collector.py`, `scripts/ai_bots_003*.py`, `tests/unit/vision/*`, `tests/unit/market_data/*` | trabajo de esta cadena (003D/003E/003F/003G/003H) |
| Informes | `RFC-TAP-AI-BOTS-003G.md`, `reports/ai-bots/RFC-AI-BOTS-003G/**` | 003G, conservado inmutable |
| Ajenos | `data/st6/**`, `data/recovery/wp8/**`, `reports/economic-recovery/**`, `scripts/{cap004c_verify,paper_lab_dashboard,st6_scheduler_witness}.py`, `src/trading_bot/research/economic_recovery/alpha15.py`, `evidence/real_decisions/**`, `RUN_REPORT.*`, `FINAL_REPORT.md` (raíz) | **otros WPs/agentes**: no se modifican, no se commitean, se reportan como pendientes |

`scripts/paper_lab_dashboard.py` aparece modificado por otro WP y **no** es el dashboard que
prueba `tests/unit/observability/test_dashboard_server.py` (ese es
`scripts/strategy_ecosystem_dashboard.py`, sin cambios).

## 2. Semántica de `costs_usdt` antes de 003H (D5)

Lectura directa del código en HEAD:

```text
lane.py:1365  "costs_usdt": round(sum(float(t.total_cost_usdt) for t in trades), 6)   # trades = broker.closed_trades
lane.py:1485  execution_cost = sum(float(trade.execution_cost_usdt) for trade in trades)
lane.py:1499  "execution_cost_usdt": round(execution_cost, 8)
broker.py:707 accrued_entry_commissions()  -> suma de comisiones de entrada de posiciones abiertas
broker.py:719 mark_to_market_equity()      -> resta esas comisiones devengadas
```

Conclusión medida: el broker **ya** sabía cuantificar el devengo y el equity marcado ya lo
descontaba; el resumen del lane agregaba únicamente operaciones cerradas, así que con una
posición viva publicaba `costs_usdt = 0`, `entry_commission_usdt = 0`,
`final_equity_usdt = 10 000,0` mientras `marked_equity_usdt = 9 998,371187`. La fila `FILL` no
llevaba comisión (claves verificadas en `cycle-0008/ledger.jsonl`), de modo que la acusación no
era reconstruible desde el ledger sin creer al resumen.

## 3. Duración de sesión: qué dijo cada sesión

| Sesión | Declarado | Arranque | Fin real | Ciclos | Por qué terminó |
| --- | --- | --- | --- | --- | --- |
| `003G/session` (publicada) | `duration_s=2400` (40 min), `--max-cycles 8` | 07:28:46Z | 08:00:12Z (31 min 26 s de reloj) | 8 | `max_cycles` alcanzado; ventana de barras 07:20→08:00, `data_time` 07:25→08:00 |
| `003G/session-aborted-aggregation` | `duration_s=3000` (**50 min**) | 06:58:41Z | 06:59:06Z | 0 (1 bloqueado) | defecto D1 (`INCOMPLETE_DECISION_BAR`) |
| `003G/session-venue-revision` | `duration_s=3000` (50 min) | 07:02:59Z | bloqueada | 4 | defecto D2 (`DUPLICATE_CONFLICT` en ETHUSDT) |
| `003G/session-preflight` | `duration_s=3000` (50 min) | 06:46:09Z | — | — | preflight, no versionada |

**La discrepancia es de atribución, no de cifras:** los 50 minutos declarados pertenecen a las
sesiones abortadas (06:58 y 07:02), no a la publicada, que declaró 40 minutos y fue detenida por
`--max-cycles 8` a los 31 min 26 s de reloj (40 minutos de tiempo de barra). 003G no afirmó en
ningún sitio que su sesión durase 50 minutos; lo que faltaba era esta tabla, que ahora queda
publicada. `session-venue-revision` y `session-aborted-aggregation` conservan su
`SESSION_START.json` original: no se han reescrito.

## 4. Fallo del dashboard bajo escritura concurrente (P4)

Reproducido con el árbol quieto y un escritor ajeno limitado a un fichero de `reports/`:

```text
$ (escribir reports/ai-bots/.concurrency-probe.txt durante ~4 s) &
$ pytest tests/unit/observability/test_dashboard_server.py::test_runtime_artifacts_are_untouched_by_serving -q
1 failed in 37.62s
  Differing items:
  {'...reports\\ai-bots\\.concurrency-probe.txt': '30b10d...'} != {'...': '326d5a...'}
  Omitting 7844 identical items
```

Un solo fichero difiere, el del escritor ajeno: el dashboard no escribió nada. El defecto es del
**alcance del test** (hashea todo `reports/`, propiedad de quien escriba), no del servidor. Se
corrige aislando el sujeto (`tmp_path` con artefactos propios); la prueba sigue exigiendo que
los bytes servidos no cambien.

## 5. Integridad de datos, estado medido antes de 003H

| Garantía | Estado en HEAD | Evidencia |
| --- | --- | --- |
| Vela en formación no guardada | implementada | `test_a_forming_minute_is_never_stored` |
| `settle_ms` para velas recién cerradas | implementada (003G-D2) | `test_a_just_closed_minute_is_deferred_until_it_settles` |
| Revisión de vela → bloqueo sin reescritura | implementada | `DUPLICATE_CONFLICT` (31 eventos en `session-venue-revision/EVENTS.jsonl`) |
| Gaps, duplicados idénticos, desorden | implementadas | suite `tests/unit/market_data` |
| `data_time ≤ decision_time` | implementada y verificada | 8/8 ciclos de la sesión publicada |
| `delivery_latency` vs `quote_lag` | ambos medidos, sin test que fije la diferencia | 2 577-27 044 ms en la sesión publicada |

Lo que faltaba no era una protección, sino **un test que fijara la definición de cada instante**
para que una futura refactorización no las intercambiara sin romper nada.

## 6. Artefactos de 003G que NO se tocan

`reports/ai-bots/RFC-AI-BOTS-003G/**` completo: sesión publicada, sesiones abortadas, smoke,
`RUN_REPORT.*`, `VERIFICATION.*`, `STATE_AUDIT.md`, `runtime_authority_map.md`, `FINAL_REPORT.md`.
Los ficheros de código 003G (`lane.py`, `prospective.py`, `minute_collector.py`, tests) **sí**
evolucionan en 003H: por eso este WP no reescribe su verificación, sino que añade
`scripts/ai_bots_003h_verify.py` para las sesiones nuevas.

### 6.1 Consecuencia medida: el verificador de 003G pasa 24/25 sobre su propia sesión

```text
$ python scripts/ai_bots_003g_verify.py --session reports/ai-bots/RFC-AI-BOTS-003G/session --root .
[verify] 24 PASS / 1 FAIL
[verify] FAIL tested_runtime_equals_used_runtime:
  src/trading_bot/vision/lane.py        c20fe99f… -> e316b68e…
  src/trading_bot/vision/prospective.py e4ff5753… -> a6aa3610…
```

El único check que falla es **el que debe fallar**: 003H cambió esos dos ficheros, así que el
runtime que corrió la sesión de 003G ya no es el del árbol. No es una regresión del artefacto
—los otros 24 checks siguen recomputando sus cifras desde los bytes intactos— sino la prueba
de que la identidad de runtime se comprueba de verdad. Los hashes originales siguen dentro de
`SESSION_START.json → runtime_sha256`, de modo que el drift es medible y no se disimula. Este WP
no modifica el verificador de 003G ni su `VERIFICATION.md`.

## 7. Incidente declarado (003H-D6): una re-ejecución sobrescribió la verificación de 003G

Al comprobar que el verificador de 003G seguía funcionando sobre su sesión, se ejecutó

```text
$ python scripts/ai_bots_003g_verify.py --session reports/ai-bots/RFC-AI-BOTS-003G/session --root .
[verify] 24 PASS / 1 FAIL
```

El programa `main()` escribía `VERIFICATION.json` y `VERIFICATION.md` **dentro del directorio de
la sesión**: los dos ficheros de 003G (que decían 25 PASS / 0 FAIL) quedaron sobrescritos por la
re-verificación (24 PASS / 1 FAIL, drift de runtime). Los bytes de la sesión no se tocaron; el
texto original del informe se transcribe en `PRESERVED_003G_VERIFICATION.md`, marcado como
transcrito y no como artefacto restaurado.

**Corrección aplicada:** `--out-dir` en los dos verificadores (003G y 003H), de modo que
verificar una sesión ajena o congelada ya no escribe en ella. Las re-ejecuciones de comprobación
se hicieron después con `--out-dir logs/rfc003h/...`, y el directorio de 003G no se ha vuelto a
modificar (mtime 11:07).

**Qué dice hoy el directorio de 003G:** `VERIFICATION.json|md` = 24 PASS / 1 FAIL. Ese es el
estado real y no se disimula; el origen del único fallo es el cambio de `lane.py` y
`prospective.py` de este WP, con los hashes originales guardados en su `SESSION_START.json`.
