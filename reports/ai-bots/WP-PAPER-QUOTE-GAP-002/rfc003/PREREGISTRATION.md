# PREREGISTRATION — RFC-PAPER-QUOTE-GAP-003

| Campo | Valor |
|---|---|
| RFC | `RFC-PAPER-QUOTE-GAP-003` |
| WP objetivo | `WP-PAPER-QUOTE-GAP-002` |
| Fase | `A — Laboratory gap recovery certification` |
| Alcance | `OFFLINE / LAB ONLY` |
| Escrito | `2026-10-21`, **antes** de ejecutar tests, commit o re-ejecución |
| Política | `BUILDER != VERIFIER`; un `PASS` de Fase A no implica PAPER ni LIVE |

Este documento se escribe **antes** de tocar el árbol. Su función es impedir el sesgo de
post-hoc: los criterios de cierre, las predicciones y los fallos adversarios que deben ser
rechazados quedan fijados aquí, y `FINAL_REPORT` sólo puede diferir de ellos declarando la
diferencia y su causa.

## 1. Baseline capturado (read-only, sin ediciones)

Comandos ejecutados tal cual, con salida persistida en `.tmp/rfc003/`:

```
git rev-parse HEAD                     -> fefb0771036c33c648ecb2ed11cb28e8c2b49264
git rev-parse --abbrev-ref HEAD        -> wp/paper-resume-001
git status --porcelain=v2 --untracked-files=all -> 144 entradas (8 modificadas, 137 sin seguimiento)
git diff --stat                        -> 8 files changed, 1009 insertions(+), 30 deletions(-)
git diff --check                       -> exit 2 (4 líneas: pyproject.toml CRLF)
git log -5 --oneline                   -> fefb077, 9800925, 10919df, f014813, b0e1549
```

### 1.1 Hallazgos de baseline que condicionan el plan

| ID | Hecho medido | Consecuencia |
|---|---|---|
| `B1` | **Todo el código del WP es untracked**: `vision/durable.py`, `vision/gap_recovery.py`, 7 ficheros de test, 6 scripts, 2 RFC. | `ACC-001` no puede cumplirse sin commit. Es la forma extrema de `O1`. |
| `B2` | `reports/ai-bots/*` está en `.gitignore:463`. `WP-PAPER-RESUME-001/` y `WP-PAPER-QUOTE-GAP-002/` **no tienen re-inclusión**, a diferencia de `RFC-AI-BOTS-002/003/003G/003H` y `EXP-003M`. | La raíz real de `O2`: la evidencia nunca fue versionable. `EVIDENCE_SHA` es imposible sin corregir el `.gitignore` con el mecanismo que el repo ya usa. |
| `B3` | `data/quote-feed-1m/` (7,07 MB, 3 ficheros) es untracked y **tres** ficheros de test lo exigen comprobando `sha256` contra `SOURCE_MANIFEST.json`. | Sin commitear el fixture, un checkout limpio no puede reproducir la suite. El repo ya versiona corpus con manifiesto (`data/rfc049` 94 ficheros, `data/edge08`). |
| `B4` | `pyproject.toml` está almacenado en el índice **con CRLF** (`i/crlf`), con `core.autocrlf=true` global. | Causa exacta de `O6`/`diff --check rc=2`: el CR final se reporta como trailing whitespace en cada línea añadida. Es un defecto de almacenamiento, no de contenido. |
| `B5` | El intérprete disponible es el venv compartido `hermes-agent` (`AppData\Local\hermes\hermes-agent\venv`). Sin `PYTHONPATH`, `find_spec('trading_bot')` devuelve `None`. | Confirma `O1`: no hay instalación que ate el paquete a este árbol. El pin `pythonpath=["src"]` es la única atadura y estaba sin commitear. |
| `B6` | El drill usa `--archive reports/ai-bots/WP-PAPER-QUOTE-GAP-002/archive` (copia dentro del WP: `ETHUSDT.jsonl`, `SOLUSDT.jsonl`, `EVENTS.jsonl`, `MANIFEST.json`, 1,4 MB). El `DEFAULT_ARCHIVE` del script apunta a `WP-PAPER-ROUNDTRIP-001/...`, que **no existe** en disco. | `ACC-005` es alcanzable, pero sólo si se versiona el `archive/` del WP y se invoca con `--archive` explícito. El default roto debe documentarse, no "arreglarse" moviendo datos. |
| `B7` | Hay 23 worktrees registrados, con `Downloads/bot freebuff` como tronco y este directorio como worktree. | El riesgo de contaminación no es hipotético: el mismo venv sirve a varios árboles. |

### 1.2 Diferencias con la auditoría A5

A5 decía «sin `PYTHONPATH`, `import trading_bot` resuelve a `Downloads/bot freebuff/src`». En el
baseline de hoy `find_spec('trading_bot')` devuelve `None`: el paquete no es importable en
absoluto sin ayuda. La conclusión de A5 (`O1`, no hay atadura al árbol) se mantiene; el
mecanismo concreto era otro. Se registra la discrepancia en vez de heredar la frase.

## 2. Alcance del commit `CODE_SHA`

Entra:

- `src/trading_bot/vision/{lane,ledger,prospective,quotes,durable,gap_recovery}.py`
- `tests/unit/vision/{test_gap_recovery,test_gap_recovery_venue,test_durable_book,test_session_durable,test_session_recovery}.py`
- `scripts/{quote_gap_lab,verify_quote_gap,quote_feed_source,paper_resume_drill,make_quote_gap_evidence,make_resume_report,verify_paper_resume}.py`
- `pyproject.toml` (pin `pythonpath`, ya en disco)
- `.gitattributes` (fixture 1m byte-exacto), `.gitignore` (re-inclusión de evidencia)
- `data/quote-feed-1m/{SOURCE_MANIFEST.json,AAVEUSDT…json,UNIUSDT…json}`
- `docs/rfc/RFC-050…md`, `docs/rfc/RFC-051…md`, `docs/runtime/runtime_authority_map.md`,
  `docs/agentic/EXECUTION_CHECKPOINT.md`
- `reports/ai-bots/WP-PAPER-QUOTE-GAP-002/` y `WP-PAPER-RESUME-001/` (informes y `archive/`)

No entra: `.tmp/**` (logs y estados efímeros), ni ningún cambio ajeno no identificado.

**Atribución:** los 8 ficheros modificados y los 19 untracked de alcance provienen del trabajo
de `WP-PAPER-RESUME-001` / `WP-PAPER-QUOTE-GAP-002` en este mismo worktree, ya descritos en sus
`RUN_REPORT`. No se ha detectado trabajo de otro autor en el diff (`git diff` completo revisado
antes del commit). No se usa `git add -A`.

## 3. Predicciones preregistradas

Se declaran ahora y se contrastan después. Una predicción fallida no se borra: se explica.

| ACC | Predicción | Confianza |
|---|---|---|
| `ACC-001` | Se consigue `CODE_SHA` con todo el runtime ensayado dentro. | Alta |
| `ACC-002` | Checkout limpio + venv nuevo importa desde el propio checkout; el control negativo con `PYTHONPATH` al hermano **debe fallar cerrado**. | Alta |
| `ACC-003` | El total será **694** o un delta explicable por node ID; los cinco tramos serán disjuntos. | Media |
| `ACC-004` | `83/83` y `10/10` reproducen; `ruff`/`mypy` a 0 en el alcance de A5. | Alta |
| `ACC-005` | Barras, minutos y cadena de 3.034 eventos se re-derivan del `archive/` del WP. | Alta |
| `ACC-006` | PRE_COMMIT reproducible desde los 14 kills; POST_COMMIT automatizable; sin doble cierre. | Media |
| `ACC-007` | Logs primarios versionados bajo `evidence/`. | Alta |
| `ACC-008` | `order_submit_attempts` medible con transporte espía; `external_orders=NOT_VERIFIABLE`. | Media |
| `ACC-009` | `unsupported_pass_count=0` sobre los 10 negativos. | Media-baja |
| `ACC-010` | `EVIDENCE_SHA` verificable desde checkout limpio. | Alta |
| `ACC-011` | Verificador independiente que no importa `trading_bot`. | Alta |
| `ACC-012` | `PAPER_VALIDATION=NOT_PERFORMED`, `LIVE=NOT_AUTHORIZED`, `exchange_reconciliation=NOT_VERIFIABLE`. | Alta |

### 3.1 Predicciones de fallo (si ocurren, degradan la decisión)

- `P1` — la suite desde checkout limpio fallará en los tests que exigen `data/quote-feed-1m` si
  el fixture no se versiona con bytes idénticos (previsto y mitigado en `B3`).
- `P2` — `mypy` fallará si el alcance incluye módulos que A5 no declaró.
- `P3` — el control negativo `NEG-02` (código mutado tras `CODE_SHA`) podría **pasar** si el
  verificador compara contra el árbol de trabajo en lugar de contra `CODE_SHA`; si ocurre, es
  `unsupported_pass_count > 0` y la decisión baja a `FAIL`/`PARTIAL` sin discusión.
- `P4` — `git diff --check` seguirá en `rc=2` si me limito a tocar el contenido y no el
  almacenamiento del fichero. Se corrige en el índice, no con un formateo global.

## 4. Fallos adversarios que **deben** ser rechazados

Fijados antes de escribir el verificador, para que no se diseñen a la medida del resultado:

| Test | Alteración | Rechazo exigido |
|---|---|---|
| `NEG-01` | `PYTHONPATH` apuntando al checkout hermano | Gate de identidad de import aborta |
| `NEG-02` | Fichero de runtime alterado después de `CODE_SHA` | Verificador detecta hash ≠ `CODE_SHA` |
| `NEG-03` | Log primario eliminado o con un byte cambiado | Verificación de manifiesto falla |
| `NEG-04` | Node ID duplicado entre dos tramos | Gate de unicidad rechaza |
| `NEG-05` | Un tramo omitido | Gate de cobertura rechaza |
| `NEG-06` | Crash antes de persistir | Recuperación consistente e idempotente |
| `NEG-07` | Crash tras persistir + dos reanudaciones | Sin doble cierre, digest estable |
| `NEG-08` | Llamada al transporte LIVE sin autorización | Rechazo y registro del intento |
| `NEG-09` | `live_orders=0` falsificado / `ok:true` sin evidencia | El informe no lo acepta como medición |
| `NEG-10` | `vision/ledger.py` omitido del inventario; chain-head comparado como hash de fichero | Gate de esquema rechaza |

`unsupported_pass_count` = nº de estos casos en los que un artefacto inválido recibe `PASS`.
Objetivo: `0`. Alcance: **esta certificación de Fase A**, no el runtime de trading.

## 5. Criterios de cierre y regla decisoria

- `PASS (LAB ONLY)` sólo si los 12 ACC quedan demostrados con evidencia comprobable desde un
  checkout limpio del commit de evidencia.
- `PARTIAL` si falta cobertura o un artefacto primario.
- `FAIL` si hay divergencia funcional, doble cierre, o un negativo que pasa.
- `BLOCKED` si una fuente imprescindible (dato, dependencia, checkout) es irrecuperable. No se
  sustituye por sintético ni se declara equivalente.

## 6. Disposición de artefactos (decisión de layout)

El RFC §12 nombra `RUN_REPORT.md`/`RUN_REPORT.json`/`FINAL_REPORT.md` en el directorio del WP,
pero ese directorio **ya contiene** los `RUN_REPORT`/`FINAL_REPORT` de `WP-PAPER-QUOTE-GAP-002`,
que son evidencia histórica de otro WP y no deben sobrescribirse (AGENTS.md §7.5). Por tanto:

- `reports/ai-bots/WP-PAPER-QUOTE-GAP-002/rfc003/` alberga todos los artefactos nuevos,
  conservando los nombres pedidos.
- `GIT_AUTHORITY_AUDIT.md` / `.json` se actualizan **in situ**, porque son artefactos de la
  auditoría A5 que este RFC viene a cerrar.

## 7. Prohibiciones vigentes durante toda la ejecución

Sin LIVE, sin credenciales, sin llamadas a exchange, sin `git push`, sin `git add -A`, sin
reescritura de historia, sin tocar `archive/` ni los ledgers originales, sin cambiar sizing,
riesgo, estrategias ni PnL.
