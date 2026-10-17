# Execution checkpoint — reanudación entre sesiones

> Documento vivo. **Antes de empezar cualquier sesión**: leer este fichero y validarlo contra Git
> (`git log -1`, `git status --porcelain`, rama actual). Si hay discrepancia, manda Git y este
> fichero se corrige con el estado real. **Después de cada paquete de trabajo relevante**: actualizar
> las secciones marcadas.
>
> Política completa en `AGENTS.md` §7. Reglas de campaña: `FALSE_SUCCESS=0`, `BUILDER != VERIFIER`,
> nada de trading real, credenciales, apalancamiento ni cambios de límites de riesgo.

*Última actualización: 2026-10-17T16:25Z, sesión de recuperación de WP-EDGE-017.*

## 0. Diagnóstico de la sesión (el bloqueo no era el que parecía)

La rama remota estaba en `2536928`, pero **el trabajo de EDGE-017 no faltaba: existía en local y no
estaba publicado**. Al abrir esta sesión, `HEAD` era `c3e030a` con 4 commits por delante de
`origin` (`5b86b65`, `ffd5105`, `9733f12`, `c3e030a`). El bloqueo real era *publicación + verificación
independiente*, no ausencia de código.

Esta sesión, por tanto, **no reutilizó los resultados anteriores**: volvió a ejecutar los tests y los
verificadores, reprodujo los defectos de `2536928` con código ejecutable y añadió el hueco que
quedaba abierto en 017A.

## 1. Estado Git (verificado contra `origin`)

- Rama: `agent/edge-recovery/WP-EDGE-00-baseline`.
- **Publicado y verificado**: push de código `2536928..1869f53` y push de este checkpoint
  `1869f53..14e892c`, ambos fast-forward y sin `--force`; tras el segundo,
  `git rev-parse origin/agent/edge-recovery/WP-EDGE-00-baseline` = `14e892c7eae5b4367b4e478cc896eb5f79d12033`
  = `HEAD`. La corrección de esta misma línea se publica en el commit siguiente: la cabecera
  vigente se comprueba con `git rev-parse origin/agent/edge-recovery/WP-EDGE-00-baseline`, no
  leyéndola aquí.
- Commits publicados en esta sesión:
  - `1ad3a37` — *Serialise the holdout capture so two collectors cannot lose each other's bars.*
    (transacción de escritor único + 4 tests + C12/M12 del verificador + replay de prefijos).
  - `1869f53` — *Refuse a futures size whose quantity quotient overflows instead of crashing.*
    (defecto ajeno a EDGE-017, encontrado por la suite de propiedades; se declara aparte).
- Commits publicados por la sesión anterior, ya en `origin`: `5b86b65` (reparación de código),
  `ffd5105` (evidencias), `9733f12` (digests del holdout), `c3e030a` (auditoría económica).
- **No tocar** lo ajeno: `data/st6/**`, `.ci/**`, `data/recovery/wp8/**`,
  `evidence/real_decisions/**`, `reports/economic-recovery/RFC-EDGE-014*/**`,
  `reports/economic-recovery/RFC-EDGE-016/INDEPENDENT_VERIFICATION.json` y los ~160 ficheros sucios
  de otras líneas.

## 2. Hecho y verificado en esta sesión (evidencia ejecutada, no heredada)

| hecho | comando | resultado |
| --- | --- | --- |
| Los 4 defectos de captura de `2536928` se reproducen al ejecutar su código | `python scripts/edge17_prefix_replay.py` → `PREFIX_REPLAY.log` | **9/9 detectados**: 3 filas → 2 (barra destruida), 1000 de 2600 barras (página única), `captured_bars_per_symbol=1` con 3 filas, `duplicate_keys=0` por tautología |
| Los tests nuevos detectan los defectos si se reintroducen (M1–M4) | mismo script, módulo mutado en `PYTHONPATH` | 3, 3, 3 y 1 tests fallan respectivamente |
| Sin el lock, dos capturas simultáneas fallan | mismo script, `slice_lock` neutralizado | 1 test falla (lost update / carrera de `os.replace`) |
| La captura ya es de escritor único | `tests/unit/research/test_edge17_capture.py` | **19 passed** (15 previos + 4 nuevos) |
| Sin regresiones en el plano afectado | `pytest tests/unit/paper tests/unit/risk tests/unit/research/test_edge17_capture.py` | **225 passed** en 8,3 s |
| La suite de propiedades del plano de futuros queda verde | `pytest tests/unit/risk/test_futures_falsification_regressions.py` | **43 passed** (antes: `OverflowError` en `instruments.py:202`) |
| Verificador independiente de EDGE-017 | `python scripts/edge17_verify.py` | **28/28 checks, 12/12 fallos detectados** (C12 y M12 son nuevos) |
| Verificador de EDGE-015 | `python scripts/edge15_verify.py` | **35/35**, `VERIFIED` |
| Verificador de EDGE-016 | `python scripts/edge16_verify.py` | **42/44**, mutaciones **38/38**; V57 y V58 siguen fallando (ver §5) |
| Lint y tipos | `ruff check` / `mypy` sobre los ficheros tocados | OK |
| Espacios en blanco | `git diff --check` | OK |

### Qué cambió de verdad en 017A

`write_slice_atomic` impedía un fichero a medias, **no** un *lost update*: el colector leía la
slice, pasaba minutos descargando y escribía una fusión construida sobre esa foto vieja; una segunda
captura que terminase en medio perdía todo lo que había añadido. Ahora:

- `oos_capture.slice_lock` toma un fichero hermano con `O_CREAT|O_EXCL` (atómico en todas las
  plataformas), con timeout que **falla en vez de escribir** y reclamación de locks huérfanos.
- `oos_capture.merge_and_write` hace *lock → re-lee → fusiona → `os.replace`*, y devuelve
  `rows_before`/`sha256_before` leídos **dentro** del lock (la foto previa al fetch ya no es la base
  de la escritura).
- `scripts/edge15_oos_preregistration.py` escribe ambas slices sólo por `merge_and_write`; la
  reanudación (`next_since_ms`) sigue usando la lectura previa, que es sólo para decidir el `since`.
- El verificador independiente añade C12 (la slice sólo se escribe por la transacción) y M12
  (inyección que lo rompe).

## 3. Estado de los bloques 017A–017E

| bloque | estado | evidencia de esta sesión |
| --- | --- | --- |
| 017A captura prospectiva | **cerrado y ampliado**: append-only, atómico, reanudable, paginado, sólo barras cerradas y ahora **escritor único** | replay 9/9; 19 tests; C12 |
| 017B presupuesto de disco | **verificado, no regenerado**: la tasa es una medición (9 576,3 B/h frente al fallback de 240 MB/h), guardián con reserva 2 GB, 1,5× y válvula 64 MiB intactos | checks S1–S3 del verificador |
| 017C coste dentro del riesgo | **verificado, no regenerado**: `PaperBroker` cobra comisión + medio spread + slippage; `RiskManager.mark_equity` marca el equity neto antes de decidir | checks N1–N9; 146/110/67 operaciones y −238,77/−293,03/−294,06 USDT en `NET_RISK_REPLAY.json` |
| 017D bloqueos defensivos | **verificado**: cableados en `start_paper_trading → run_cycle_sync`, con condiciones medidas por el scanner y fallo cerrado; política y fin de semana sin tocar | checks D1–D3 |
| 017E pruebas y evidencias | **parcial**: verificado lo anterior; la suite completa **no** se re-ejecutó en esta sesión | ver §4 |

**Aviso de método:** los artefactos de 017B/017C (replay económico, medición de almacenamiento) se
produjeron en la sesión anterior; esta sesión los **re-verificó** (28/28) pero **no los regeneró**.
No se presentan como ejecución nueva.

## 4. Pendiente (lo que falta de verdad)

1. **Suite completa `pytest tests/unit`**: no re-ejecutada. El último registro es
   `4048 passed, 5 failed en 21:56` (`RFC-EDGE-017/FULL_UNIT_SUITE.log`), ya obsoleto. Un intento de
   `tests/unit/research` completo agotó 600 s (timeout, no fallo) por contención con la tarea ST6.
2. **Ninguna barra capturada al cierre en vivo**: las 9 del slice vienen de la primera captura
   corregida. La siguiente captura manual dentro de la hora produce las primeras barras «al cierre».
3. **Ninguna estrategia admitida** (`config/strategy_admission.json`).
4. **Sin planificador**: crear la tarea exige privilegios de administrador, no autorizados.
5. **Regenerar 017B/017C** si se exige evidencia posterior a `1ad3a37` (el replay no depende de la
   captura, pero hoy no se ha vuelto a ejecutar).

## 5. Bloqueos e incidencias declaradas (no ocultar)

- **Volumen al 99 %** (3,7 GB libres). El colector no es el problema (9,6 KB/h), pero el host no está
  sano y este paquete no reclamó espacio.
- **`edge16_verify.py` en 42/44**: V57 falla porque
  `RFC-EDGE-016/INDEPENDENT_VERIFICATION.json` ya estaba modificado por otra línea al abrir la
  sesión (y volver a ejecutar el verificador lo reescribe: **no se commiteó**); V58 porque
  `broker.py` cambió de línea con EDGE-017. Sus 38/38 mutaciones se siguen detectando.
- **Auditoría WP-8 desfasada** por `evidence/real_decisions/*.jsonl`, sucios de otra línea.
- **Defecto ajeno corregido**: `round_quantity_down` lanzaba `OverflowError` con `entry=2,1e-302`
  (cociente infinito). Se convirtió en rechazo (0,0) sin tocar ningún límite; commit `1869f53`,
  separado del paquete.

## 6. Comandos de reanudación

```bash
# 0. Estado real
git -C "$(git rev-parse --show-toplevel)" log --oneline -3
git -C "$(git rev-parse --show-toplevel)" status --porcelain | head -40
git -C "$(git rev-parse --show-toplevel)" rev-parse origin/agent/edge-recovery/WP-EDGE-00-baseline

# 1. Reproducir los defectos de captura (no toca red ni datos)
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge17_prefix_replay.py

# 2. Capturar (append-only, escritor único; después commitear antes de verificar)
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge15_oos_preregistration.py --capture

# 3. Verificadores
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge17_verify.py   # 28/28, 12/12
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge15_verify.py    # 35/35
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge16_verify.py    # 42/44 declarado

# 4. Gates
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python -m ruff check src/trading_bot/research/oos_capture.py scripts/edge15_oos_preregistration.py scripts/edge17_verify.py
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python -m mypy src/trading_bot/research/oos_capture.py
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python -m pytest tests/unit/paper tests/unit/risk tests/unit/research/test_edge17_capture.py -q

# 5. Suite completa (no ejecutada en esta sesión; ~22 min con ST6 activa)
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python -m pytest tests/unit -q --tb=short -rf -p no:cacheprovider > reports/economic-recovery/RFC-EDGE-017/FULL_UNIT_SUITE.log 2>&1; echo "EXIT=$?"
```

## 7. Protocolo de actualización

- Al **cerrar un hito**: marcar la fila correspondiente en §2/§3 y actualizar §4/§5.
- Al **cortarse la sesión**: anotar el comando exacto que se estaba ejecutando y su log.
- **Nunca** mover un elemento de §4 a §2/§3 sin evidencia ejecutada (log, artefacto, exit code).
- `reports/economic-recovery/*` está en `.gitignore`: los ficheros nuevos de evidencia se añaden con
  `git add -f` **sólo** si son propios del bloque.
