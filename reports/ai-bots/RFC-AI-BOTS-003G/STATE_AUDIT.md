# STATE_AUDIT — RFC-TAP-AI-BOTS-003G

**Auditoría hecha antes de escribir código el 2026-10-19.** Cada fila es un comando
ejecutado en esta sesión; si un dato no se midió, se dice.

## 1. Git y worktrees

```text
$ git rev-parse HEAD
fe9b5e2623b0d023833249e9687b753eaacd27d4
$ git branch --show-current
agent/ai-bots/RFC-TAP-AI-BOTS-003
$ git log --oneline -3
fe9b5e2 Start automated children without a console window
0841d37 State why the clean-archive rehearsal still covers the published head
e7f9314 Pin the bars a paper run consumed, not just the file it read
```

`git worktree list` registraba **9** worktrees, tres de ellos con el directorio ya ausente
(`prunable`). `git worktree prune` retiró **sólo la metainformación** de esos tres; ningún
worktree existente se modificó. Quedan seis:

| Worktree | HEAD | Rama |
| --- | --- | --- |
| `bot freebuff` (canónico) | `fe9b5e2` | `agent/ai-bots/RFC-TAP-AI-BOTS-003` |
| `bot-freebuff-rfc035s3-lab` | `7e21f7c` | detached |
| `bot_crypto_003d` | `0841d37` | `agent/ai-bots/RFC-TAP-AI-BOTS-003D` |
| `bot_crypto_004` | `34cf269` | `agent/ai-critic/RFC-TAP-AI-BOTS-004` |
| `bot_crypto_004g` | `0954d63` | `agent/ai-critic/RFC-TAP-AI-BOTS-004G` |
| `bot_crypto_005` | `d808322` | `agent/market/RFC-TAP-MARKET-005` |
| `bot_crypto_roadmap` | `ef6dae4` | `project/roadmap-trading-agentic` |

## 2. Estado de 003D, 003E y 003F

### 003D — verificado, **sin commitear**, en otro worktree

```text
$ git -C ../bot_crypto_003d log --oneline -1
0841d37 State why the clean-archive rehearsal still covers the published head
$ git -C ../bot_crypto_003d status --short
 M docs/agentic/EXECUTION_CHECKPOINT.md
?? data/quote-feed-1m/
?? scripts/ai_bots_003d_capture.py
?? scripts/ai_bots_003d_fetch_quotes.py
?? scripts/ai_bots_003d_verify.py
?? src/trading_bot/vision/quotes.py
?? tests/unit/vision/test_minute_quote_feed.py
```

La rama `003D` no tiene commits propios: su trabajo está en el árbol de ese worktree. En el
árbol canónico la dependencia ya estaba importada (mismos ficheros sin seguimiento), que es
donde se ejecutó y verificó (10 PASS / 4 mutaciones según su verificador). **Ese worktree no
se ha tocado en esta sesión.**

### 003E/003F — implementados en el árbol canónico, **sin commitear**

```text
$ git status --short -- src/trading_bot/vision scripts/ai_bots_003e_verify.py tests/unit/vision data/quote-feed-1m
 M src/trading_bot/vision/execution.py       (+41 líneas: QuoteRange, SubBarQuoteFeed)
 M src/trading_bot/vision/lane.py            (+155 líneas: subbar_entries, rango post-fill)
?? src/trading_bot/vision/quotes.py
?? scripts/ai_bots_003e_verify.py
?? tests/unit/vision/test_minute_quote_feed.py
?? tests/unit/vision/test_subbar_execution.py
?? data/quote-feed-1m/                        (6,8 MB, no ignorado)
```

`reports/ai-bots/RFC-AI-BOTS-003E/` y `.../003F/` existen en disco; `reports/*` está ignorado
(`.gitignore:463`), así que **no están en Git**. 003G no los reescribe: los audita.

### Procedencia del RFC 003F — reconstruido, no original

Comprobado ahora, no heredado del informe anterior:

```text
$ git log --all --oneline -- '*003F*'                 -> vacío
$ git log --all --name-only --diff-filter=A | grep -i 003F -> vacío
```

Por tanto `RFC-TAP-AI-BOTS-003F.md` es una reconstrucción y así queda marcado en su cabecera.
**El RFC 003G, en cambio, lo entregó el operador**: su fichero
[RFC-TAP-AI-BOTS-003G.md](../../../RFC-TAP-AI-BOTS-003G.md) declara esa procedencia.

## 3. Bloqueo de disco — inventario previo y limpieza conservadora

Inventario medido antes de tocar nada (`/tmp/tap003g_disk_inventory_before.txt`):

```text
inventory_at=2026-10-19T06:32:45Z
24M     .mypy_cache
455K    .pytest_cache
54K     .ruff_cache
1.5M    .hypothesis
pyc_bytes=88456443              (84,4 MB en 391 directorios __pycache__)
C:  238G usado 219G  libres 19G  93%
```

El host había pasado de **0,77 GB libres** (estado declarado por 003F) a **19 GB** antes de
esta sesión: la liberación no la hizo 003G. Lo que sí hizo 003G, y sólo esto:

1. borró cachés regenerables (`.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `.hypothesis`,
   `__pycache__`): **≈108 MB**;
2. `git worktree prune`: metadatos de tres worktrees ya inexistentes.

**No se borró** ningún dato de mercado, ledger, informe ni evidencia de otros WPs
(`reports/cap004` 1,2 GB, `reports/microstructure-forward-continuous` 1,7 GB, etc. intactos).
Después de la limpieza: **20 GB libres**. Los artefactos de 003G (dos sesiones + tests) ocupan
menos de 5 MB, así que no se acerca a la reserva de 2 GB que vigila el proyecto.

## 4. Baseline técnica (medida)

| Comprobación | Comando | Resultado real |
| --- | --- | --- |
| Suite de visión completa | `pytest tests/unit/vision -q` | **TIMEOUT a 300 s**, sin resultado. No se declara PASS. Repetida después con más presupuesto (§7 del RUN_REPORT) |
| Sub-bar | `pytest tests/unit/vision/test_subbar_execution.py -q` | **6 passed**, 16,45 s |
| Tests 003D (feed 1 m) | `pytest tests/unit/vision/test_minute_quote_feed.py` | no ejecutado en esta sesión antes de escribir código; 16 passed según su bloque, **no re-medido aquí** |
| Import del colector nuevo | `python -c "import ..."` | OK |
| Red al proveedor | `GET /api/v3/time` | `server 2026-10-19T06:32:59.234Z`, `local …59.344Z`, **skew 110 ms** |
| Vela en formación real | `GET /api/v3/klines?interval=1m&limit=3` | última vela 06:32 con `closeTime 06:32:59.999`, reloj 06:32:59 → **aún abierta**; el colector debe ignorarla |

## 5. Baseline operativa

| Pieza | Estado al empezar | Consecuencia |
| --- | --- | --- |
| Runner PAPER de visión | `scripts/ai_bots_run.py` | replay de `data/edge08/universe-1h`; **no** es prospectivo |
| Colector de 1 m vivo | **no existía** | 003G lo añade |
| Feed histórico 1 m | `vision/quotes.py` (003D) | válido para cobertura; sin reloj de llegada |
| `subbar_entries` | implementado, **ningún runner lo activaba** | 003G lo activa sólo en PAPER |
| Motor de riesgo | `trading_bot/risk/manager.py` | único; no se toca |
| Broker PAPER | `trading_bot/paper/broker.py` | único; no se toca |
| Ruta LIVE | no existe en esta ruta | se verifica estáticamente |

## 6. Baseline económica (heredada, no re-medida)

De `reports/ai-bots/RFC-AI-BOTS-003F/FINAL_REPORT.md`, con proveedor `replay` y 34 trades:
neto CURRENT −97,926767 USDT, PROPOSED −79,180509, Δ +18,746258; DD 0,979268 % → 0,791805 %;
espera mediana 3 599 100 → 59 100 ms. **Es una mejora de ejecución, no de predicción**, y no
se reutiliza como resultado de 003G: la comparación de 003G se recalcula sobre los minutos
reales capturados en esta sesión.

## 7. Riesgos identificados antes de implementar

1. **La re-ejecución por prefijo puede divergir** si una orden pendiente se resuelve al llegar
   una vela nueva (fila `RUN_END`). Se trata como artefacto de truncamiento, no como decisión,
   y el verificador lo comprueba igual.
2. **El retardo del bootstrap no es un retardo de entrega**: una página histórica tiene
   `received_at` = instante de la petición. Se mide con minutos que cierran después del inicio.
3. **Un hueco no se puede rellenar hacia atrás** en un almacén append-only; por eso el
   colector rellena *antes* de aceptar el minuto posterior y bloquea si no puede.
4. **Dos escritores** sobre el mismo almacén/ledger se rechazan con lock.
5. **Sin clave de modelo**, el proveedor de la sesión es `paper-script`: mide fontanería y
   ejecución, no calidad de opinión. `REAL_MODEL_CALLED=false`.
