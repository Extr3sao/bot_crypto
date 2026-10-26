# FINAL REPORT — TAP-SYNC-UNBLOCK-19 (contrato de configuración recuperado)

```text
TICKET:                         TAP-SYNC-UNBLOCK-19 — recuperar el contrato de configuración
BRANCH:                         fix/tap-sync-unblock-19  (aislada, de sync/uncommitted-main-20261025)
BASELINE_HEAD:                  6381c9f7fb536d5512d616860bc0cef13c8bea35  (== refs/pull/19/head, PR #19)
FINAL_HEAD:                     afd2c0c69e52d833705ce1641119b5ab2b4b0bcb
COMMITS:                        23359fca, 4cec0f0b, afd2c0c6
CHANGED_FILES:                  4 (+541 / −78)
COLLECTION:                     BASELINE exit 2 (ImportError YamlDirectorySource) -> FIX exit 0
CONFIG_TESTS:                   63 passed, exit 0 (worktree y clone)
FULL_SUITE (fix final):         116 failed, 3360 passed, 31 skipped, 36 errors  (exit 1, heredado)
FULL_SUITE (clone independiente):118 failed, 3358 passed, 31 skipped, 36 errors (exit 1, heredado)
BASELINE (misma selección):     275 failed, 3187 passed, 31 skipped, 36 errors  (exit 1)
NUEVOS FALLOS:                  0 en el worktree / 3 en el clone (ambientales, reproducidos en el clone del baseline)
NUEVOS ERRORES:                 0 (conjuntos de 36 idénticos)
FALLOS ARREGLADOS:              159
RUFF:                           226 -> 197 (exit 1) | FORMAT: 475 -> 473 (exit 1) | MYPY: 524/69 -> 385/54 (exit 1)
FICHEROS PROPIOS:               ruff 0, format 0, mypy 0 (exit 0)
FALSE_SUCCESS:                  0
PUSHED / MERGED:                no / no
```

## LO QUE SE REPARÓ

1. **Recolección**: `settings.py` en PR #19 era un *shim* de 27 líneas sin `YamlDirectorySource`,
   así que `tests/unit/config/test_failfast.py` ni siquiera se importaba (exit 2). Ahora la
   implementación Pydantic autoritativa (la misma que `main` y `admission/integration-002`,
   byte a byte) está restaurada.
2. **Los 6 YAML vuelven a llegar**: `universe`, `exchange`, `risk`, `strategies`, `indicators`,
   `runtime` estaban **ausentes** del objeto cargado; hoy llegan todos
   (`scalping_universe_v1`, 25 pairs, `binance` sandbox, `paper`, kill switch).
3. **Precedencia `env > YAML > defaults`**: `TRADING_MODE=live` se ignoraba en silencio
   (`mode: N/A`); ahora levanta `ValidationError` y arrancar en LIVE exige el kill switch.
4. **Economías inventadas fuera**: `ROUNDTRIP_COST_BPS = 891` y `STRATEGY_ADMISSION_CONFIG`
   desaparecieron; ninguna ejecución puede declararse rentable sobre números que ningún YAML declaró.
5. **Regresión propia detectada y corregida** (commit `afd2c0c6`): `_ccxt_connector()` seguía
   leyendo los campos planos del stub → `AttributeError`; ahora lee `settings.exchange.*`.
6. **7 tests nuevos de efectividad** (no de firma) en `tests/unit/config/test_settings_effective_behaviour.py`.

## QUÉ FUNCIONA DE VERDAD

- `from trading_bot.config.settings import YamlDirectorySource, Settings, load_settings` → exit 0.
- `tests/unit/config/` completo: **63 passed** (failfast, contrato `settings_contract.py` vía
  `test_settings_public_api.py`, carga de YAML, precedencia de env, config inválida,
  bloqueos LIVE/kill switch) — en el worktree **y** en un clone nuevo.
- Verificación independiente (`BUILDER != VERIFIER`): clone `git clone --no-hardlinks` con su
  propio `uv sync --frozen` reproduce **exactamente** los números (197/473/385, 63 passed, suite 118F).
- Delta de tests: **159 fallos arreglados, 0 nuevos, 0 errores nuevos**; los 115 fallos estables
  de los 3 primeros runs están **todos** en la baseline.

## QUÉ SIGUE FALLANDO (heredado, medido aparte)

- **Suite completa en rojo**: ~116 fallos y 36 errores (22 `test_ccxt_connector` por la firma de
  `CCXTExchangeConnector.__init__`, 14 `test_profitability_gate035`) — **idénticos en la baseline**.
- **Análisis estático en rojo**: ruff 197, format 473, mypy 385 (la baseline era 226/475/524 y
  `main` está en 130/444/297). Los 4 ficheros que yo toco: 3 limpios, `exchange_connector.py`
  conserva sus 22 ruff + 1 formato heredados.
- **Ambiental**: `data/rfc048/**` falla en cualquier clone limpio con `core.autocrlf=true`
  (reproducido en un clone del baseline).
- **D5**: `wiring._binance_builder` pasa una instancia `Exchange` donde se espera un callable
  → `TypeError` **igual en baseline y fix** (fichero de otro carril, sin cobertura).
- `REAL_MODEL_CALLED = false`, PAPER no ejecutado, `PROFITABLE = false`.

## PRÓXIMA ACCIÓN

Publicar `fix/tap-sync-unblock-19` y abrir el PR **contra `sync/uncommitted-main-20261025`**
(fast-forward desde `6381c9f7`): con eso el PR #19 deja de estar `BLOCKED`. En paralelo, el
carril de `main` debe atacar D1–D4, que son los que mantienen el tronco en rojo. Ninguno de los
dos pasos fusiona #18 ni #19 por sí solo.

Evidencia completa: [RUN_REPORT.md](RUN_REPORT.md), [RUN_REPORT.json](RUN_REPORT.json) y
[evidence/tap-sync-unblock-19/](evidence/tap-sync-unblock-19/).
