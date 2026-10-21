# FINAL REPORT — WP-003-04 · Desbloquear la integración en `main`

**WP:** WP-003-04 · **PR:** [#17](https://github.com/Extr3sao/bot_crypto/pull/17) · **Rama:** `wp/isolation-005`
**Repositorio:** `https://github.com/Extr3sao/bot_crypto.git`
**Fecha:** 2026-10-21 (UTC)

## Decisión: `BLOCKED`

No es un `NO_GO` del código: es un `BLOCKED` de la **entrega**, con causa medida y reparable.

WP-003-03 está validado (PAPER, datos registrados, verificación independiente `PASS`) y su huella en el rojo de CI es **cero** después de `e450a238`. Lo que impide fusionar es deuda de **otros** work packages sobre la que este encargo prohíbe actuar sin autorización: reformatear 617 ficheros de 178 commits ajenos, reescribir 611 errores de tipos en 105 ficheros ajenos, y fusionar ramas hermanas de las que dependen dos tests ya commiteados.

---

## 1. Los tres hechos que deciden

1. **Tres de los siete checks que fallan en el PR ya fallaban en la base.** En `5e6f9632` (`origin/main`, run `35724120977`): `Format + Lint` **success**, `Type check` **success**, `pip-audit` **failure**, `Tests + Coverage` **failure**, `Smoke` **failure** en `Set up job`. Ninguna rama puede poner verde lo que la base tiene rojo.
2. **La base no falla por tests, falla por umbral:** en local, `origin/main` da **582 passed** y **cobertura 62.34 %** frente al **90 %** exigido. `pip-audit` arrastra **80 avisos en 9 paquetes**; el job de smoke muere en `Set up job` antes del checkout (infraestructura).
3. **El rojo que sí aporta la acumulación no es de este WP.** De los 617 ficheros sin formatear, **0** son de WP-003-03; de los 44 ficheros con lint, **0**; de los 622 errores de mypy, **11**, todos en los dos ficheros del WP, ya corregidos → **611** restantes, todos ajenos.

---

## 2. Criterios de aceptación del encargo

| # | Criterio | Estado | Evidencia |
| --- | --- | --- | --- |
| 1 | Flujo PAPER ejecutado realmente | **CUMPLIDO** | re-ejecución completa del laboratorio con el código corregido, `LAB_EXIT=0` |
| 2 | Evidencia de ejecución reproducible | **CUMPLIDO** | verificador con `--repeat`: `economic digests identical across two independent runs` |
| 3 | Aislamiento de órdenes reales validado | **CUMPLIDO (por proceso)** | `no_external_network`, `abuse_battery`: 13 refusals / 8 escenarios, 0 llamadas a venue |
| 4 | Reconciliación PAPER comprobada | **CUMPLIDO** | `restart_reconciled`: 23 intents persistidos/recuperados, 0 cloids duplicados, Δequity 0.0 |
| 5 | Tests y verificaciones independientes superados | **NO CUMPLIDO** | colección rota por 2 imports de ramas hermanas · `101 failed / 4362 passed / 14 errors`, **0** de WP-003-03 · 18/18 + 11/11 del artefacto PAPER sí pasan |
| 6 | Sin operaciones con capital real | **CUMPLIDO** | `TRADING_BOT_MODE=paper`, política de aislamiento en cada proceso hijo, 0 rutas a venue |
| 7 | Informes completos y coherentes | **CUMPLIDO** | `RUN_REPORT.md/json`, `FINAL_REPORT.md/json`, checkpoint |
| 8 | Commits publicados y SHA remoto comprobado | **PARCIAL** | rama publicada y comprobada con `ls-remote`; `main` **no** actualizado → `MAIN_SYNCED = NO` |

**Resultado:** 6 de 8 cumplidos; el 5 y el 8 dependen de decisiones y deuda ajenas. Por eso `DELIVERY_STATUS = BLOCKED`.

---

## 3. Qué se ha ejecutado realmente en este WP

1. **Auditoría de Git y GitHub medida**, no heredada: SHA locales y remotos, 259 commits de `main` sin publicar, PR de 493 commits / 3 447 ficheros / +2 721 865 líneas, `mergeable_state = unstable`.
2. **Reproducción local de las cuatro gates** en árboles limpios de `ffda06d5`, `1d2192b0` y `5e6f9632`, con la toolchain del lock (`ruff 0.15.20`, `mypy 2.1.0`, Python 3.11) — las mismas versiones en la base y en la rama, así que no hay deriva de herramienta.
3. **Atribución por cohorte** de los 617 ficheros, 44 ficheros y 622 errores: `git log --diff-filter=A` por fichero contra tres conjuntos de commits.
4. **Reparación de la parte propia**: `e450a238` corrige los 11 errores de mypy de WP-003-03 y deja `mypy .` en 611.
5. **Re-ejecución y verificación independiente** del flujo PAPER con el código corregido: `PASS`, 18/18, 11/11, digests idénticos.
6. **Diagnóstico de las dos dependencias rotas**: los tests están en esta rama; los módulos, en `wp003i/reproducibility` y `wp003j/runtime`.

---

## 4. Operaciones PAPER (heredadas de WP-003-03, re-verificadas aquí)

| Escenario | Decisiones | TRADE | NO_TRADE | Órdenes | Fills |
| --- | --- | --- | --- | --- | --- |
| `E2E-COMMITTED` (ledger comprometido) | 480 | 0 | 479 (+1 SHADOW) | **0** | 0 |
| `E2E-SCENARIO` (ledger de escenario declarado) | 480 | 32 | 448 | **23** | 21 abiertos / 21 cerrados |
| `E2E-RESTART` | 120 | 0 | 120 | 0 nuevas | 21/21 restaurados, `RECOVERED` |

PnL realizado 87.651526 USDT · comisiones 10.5 · 5/5 identidades contables · 0 cloids duplicados · 9 TRADE sin fill con razón registrada · 1 080 decisiones con PIT correcto · 13 refusals en 8 escenarios de abuso · 0 eventos de red auditados.

Estos números **no** se han vuelto a generar desde cero para este WP: se han **re-verificado** con una segunda ejecución independiente del mismo laboratorio, que reprodujo los mismos digests económicos. Esa es la diferencia entre “el informe lo dice” y “el verificador lo rehace”.

---

## 5. Lo que falta, en orden, y quién lo desbloquea

| # | Acción | Coste medido | Quién |
| --- | --- | --- | --- |
| P1 | Baseline de CI en `main`: umbral de cobertura (62.34 % real), `pip-audit` (80 avisos), acción del job de smoke | 3 gates rojos sin relación con la PR | pipeline |
| P2 | Publicar los 259 commits de `main` local (fast-forward, sin force) o declararlos abandonados | 0 conflictos | titular |
| P3 | Deuda de formato en un commit mecánico | **617 ficheros, +37 469 / −18 032 líneas** | titular (autorización) |
| P4 | Deuda de lint | 122 auto-fixables + 73 manuales en 44 ficheros | dueños de cada WP |
| P5 | Deuda de tipos | **611 errores en 105 ficheros** | dueños de cada WP |
| P6 | Auto-contención: integrar `wp003i/reproducibility` y `wp003j/runtime`, o traer los 2 módulos | 2 dependencias | titular |

Con P1–P6 hechos, la PR pasa de 493 commits a 234 y de 7 checks rojos a 0; entonces sí procede merge + verificación final.

---

## 6. Limitaciones que se conservan (no son PASS)

- `OS_SANDBOX = NOT_AVAILABLE`: la barrera es **por proceso**; no hay contención de SO acreditada.
- `EXTERNAL_SESSION = NOT_PERFORMED`: la política de paper deniega la red, así que no hay sesión PAPER conectada a fuentes externas.
- El ledger del escenario con órdenes es **declarado**, no un ledger comprometido; el comprometido produce `NO_TRADE` por diseño.
- `SPREAD = ESTIMATED` en el modelo de costes.
- La suite de la rama **falla**: `101 failed, 4362 passed, 14 errors` en 37 minutos. Ninguno de los 115 nodos rojos es de WP-003-03 (96 de los commits no publicados de `main`, 19 de la rama previa); los 20 tests de `test_paper_e2e_00{1,2,3}` pasan. No se presenta como verde: se presenta como rojo ajeno y atribuido.
- La protección de rama de `main` no se pudo verificar (API 401 sin autenticación): **`UNKNOWN`**, no “sin protección”.
- `pip-audit` no se puede poner verde sin subir dependencias (afecta también a la base).

---

## 7. GITHUB_SYNC

| Campo | Valor |
| --- | --- |
| `repository` | `https://github.com/Extr3sao/bot_crypto.git` |
| `local_branch` | `wp/isolation-005` |
| `remote_branch` | `origin/wp/isolation-005` |
| `local_head_sha` | el de `GITHUB_SYNC.json` (se escribe tras publicar) |
| `remote_head_sha` | `ls-remote --heads origin wp/isolation-005` |
| `default_branch_sha` | `5e6f9632e8d9c15dabd60ea92ac68f350ca28c9d` |
| `commits_pending` | 0 en la rama tras el push; **259** entre `main` local y `origin/main` |
| `push_result` | ver `GITHUB_SYNC.json` |
| `pull_request_url` | https://github.com/Extr3sao/bot_crypto/pull/17 |
| `merge_result` | `NOT_MERGED` — gates rojos |
| `sync_status` | `REMOTE_BRANCH_SYNCED` |
| `verification_timestamp` | 2026-10-21 (UTC) |

Un commit no puede contener su propio SHA: el registro nombra el tip que `ls-remote` devolvió **después** del push y declara el desfase de un commit por construcción.

---

## 8. Estados (separados, sin PASS global)

```
IMPLEMENTATION_STATUS      PASS
TEST_STATUS                FAIL        (2 collection errors; base 582 passed)
RUNTIME_VALIDATION         PASS        (PAPER, recorded data)
NETWORK_ISOLATION          PASS        (process-scoped)
EXTERNAL_ORDER_PREVENTION  PASS        (process-scoped)
OS_SANDBOX                 NOT_AVAILABLE
PAPER_VALIDATION           PASS        (offline, declared scenario ledger)
INDEPENDENT_VERIFICATION   PASS        (18/18 + 11/11, exit 0)
CI_STATUS                  RED         (7/7 en la PR; 3/5 en la base)
GITHUB_SYNC                REMOTE_BRANCH_SYNCED
MAIN_SYNCED                NO
DELIVERY_STATUS            BLOCKED
PRODUCTION_READY           NOT_CLAIMED
FALSE_SUCCESS              0
```

No hay ningún fallo presentado como superado. `PRODUCTION_READY` no se declara: el encargo lo prohíbe y la evidencia no lo sostiene.
