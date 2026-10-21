# RUN REPORT — RFC-PAPER-QUOTE-GAP-003 (Fase A)

| Campo | Valor |
|---|---|
| WP | `WP-PAPER-QUOTE-GAP-002` |
| Fase | `A — laboratory gap recovery certification` |
| `CODE_SHA` | `aab65cf9d60e520119426fc74bccd84e110eee1e` |
| commit del test post-`COMMIT` | `fed5476452fc94308c28f62905f78391a6e41d23` |
| Entorno | clone limpio + `uv sync --frozen --all-extras` (Python 3.11.15) |
| PAPER | `NOT_PERFORMED` · LIVE `NOT_AUTHORIZED` · reconciliación `NOT_VERIFIABLE` |

## Comandos, con su código de salida

| # | comando | exit | artefacto |
|---|---|---|---|
| 1 | `git status --porcelain=v2 --untracked-files=all` + `git diff --check` (baseline) | 0 / 2 | `BASELINE_AUTHORITY.json` |
| 2 | `git clone --no-hardlinks <worktree> <temp>/rfc003-clean` | 0 | `CLEAN_CHECKOUT_REPORT.json` |
| 3 | `uv sync --frozen --all-extras` | 0 | `evidence/requirements.frozen.txt` |
| 4 | `pytest --collect-only -q tests/unit/{vision,paper,risk,market_data}` | 0 | `evidence/collect.txt` |
| 5 | `pytest -v -p no:warnings --tb=short <ids>` ×5 tramos disjuntos | 0×5 | `evidence/part-1..5.log` |
| 6 | `ruff check` (17 ficheros del RUN_REPORT de WP-002) | 0 | `evidence/ruff.log` |
| 7 | `mypy` (7 ficheros) | 0 | `evidence/mypy.log` |
| 8 | `python scripts/quote_feed_source.py verify` | 0 | `evidence/quote_feed_verify.log` |
| 9 | `python scripts/verify_quote_gap.py --lab … --negative-controls --json …` | 0 | `evidence/verification_replay.json` |
| 10 | `pytest tests/unit/vision/test_session_recovery.py -v` en `fed5476` | 0 | `evidence/post-commit.log` |
| 11 | `python rfc003/tools/probe_no_orders.py` (frontera armada) | 0 | `evidence/no_order_probe.log` |
| 12 | `python rfc003/tools/verify_phase_a.py --checkout <clean>` | 0 | `PHASE_A_VERIFICATION.json` |

## Suite

- Recogidos en el checkout limpio: **694** (coincide exacto con lo auditado en A5, delta 0).
- Cinco tramos **disjuntos** (intersección vacía, unión = colección): `310 + 240 + 92 + 33 + 19`.
- Resultado: **694 passed, 0 failed, 0 errors**, cinco exit 0.
- Duración: 510 s + 42 s + 22 s + 3 s + 3 s.
- Identidad por node ID: `node_ids_sha256` del conjunto y de cada tramo en `SUITE_IDENTITY.json`.

## Runtime

- `import trading_bot` desde el venv del clone → `<clean>/src/trading_bot/__init__.py`.
- 20 ficheros hashean a su blob de `HEAD` bajo la política EOL del repo (`git hash-object --path`).
- `ruff` 0 · `mypy` 0 · `quote_feed_source verify` 0.
- Loopback PIP: no se instaló nada fuera del `uv.lock`; el lock tuvo que regenerarse (ver defectos).

## Datos

- `minutes_sha256` y `bars_sha256` de `ETHUSDT` y `SOLUSDT` re-derivados desde `archive/` (144 velas de 5 m, 720 minutos).
- Cadena del colector: **3034** eventos, cabeza `b92e522603df519f…` = `MANIFEST.events_sha256`.
- Sin sustitución de fixtures: el `archive/` del WP es el input sellado.

## Verificación y negativos

- Replay del verificador del WP: **83/83**, mismos nombres de control, mismo `first_failure`, `lab_sha256` igual.
- Verificador independiente: **9/9** comprobaciones.
- Adversarios: **10/10** rechazados; `unsupported_pass_count = 0` (alcance: esta certificación).

## Evidencia

`rfc003/evidence/` — logs primarios (`collect.txt`, `part-*.log`, `ruff.log`, `mypy.log`, `quote_feed_verify.log`, `post-commit.log`, `no_order_probe.log`, `verification_replay.json`, `requirements.frozen.txt`). Todos con su `sha256` y tamaño en `EVIDENCE_MANIFEST.json`.
