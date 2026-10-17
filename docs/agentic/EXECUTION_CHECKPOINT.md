# Execution checkpoint — reanudación entre sesiones

> Documento vivo. **Antes de empezar cualquier sesión**: leer este fichero y validarlo contra Git
> (`git log -1`, `git status --porcelain`, rama actual). Si hay discrepancia, manda Git y este
> fichero se corrige con el estado real. **Después de cada paquete de trabajo relevante**:
> actualizar las secciones marcadas.
>
> Política completa en `AGENTS.md` §7. Reglas de campaña: `FALSE_SUCCESS=0`, `BUILDER != VERIFIER`,
> nada de trading real, credenciales, apalancamiento ni cambios de límites de riesgo.

*Última actualización: 2026-10-17T09:10Z, sesión de WP-EDGE-015 (holdout con barras + carril extendido).*

## 1. Objetivo actual

**WP-EDGE-015** (RFC-EDGE-015): pasar de demostrar que el motor funciona a buscar y validar
estrategias con ventaja económica neta, sin inventar rentabilidad ni tocar los límites de riesgo.
Entregables en `reports/economic-recovery/RFC-EDGE-015/`: `RUN_REPORT.md/json`, `FINAL_REPORT.md`,
`INFORME_EJECUTIVO.md`, `ALPHA_EXPERIMENT_MATRIX.csv`, `ALPHA_RESULTS.json`,
`PROSPECTIVE_PAPER_REPORT.json` (en `experimental_paper/`), `INDEPENDENT_VERIFICATION.json/md`,
`PARITY_DIVERGENCE_EXPLAINED.json/md`, el par de congelación/captura del holdout
(`OOS_PREREGISTRATION_V2.json`, `OOS_CAPTURE_MANIFEST_V2.json`) y el registro de candidatas
`config/strategy_candidates_edge15.json`.

**Resultado de la ronda: `NO_ECONOMIC_EDGE_FOUND`.** Ninguna familia cubre sus costes con muestra
suficiente. No hay promoción, no se tocaron límites y el holdout ya acumula sus primeras barras
prospectivas (3, sin puntuar).

## 2. Estado Git

- Rama: `agent/edge-recovery/WP-EDGE-00-baseline`.
- Commits de esta ronda: `b4ff588` — *Freeze the WP-EDGE-015 protocol before its data…*;
  `a6943c4` — *Preregister the holdout in one commit and capture it in another…*;
  `c8c208d` — *Write down what the search found, including the family it rejected…* (informes);
  más el commit de la re-verificación que sigue a este checkpoint.
- Re-verificación ejecutada a las 09:5xZ sobre el árbol de trabajo: `edge15_verify.py` **35/35**
  `VERIFIED` (V33/V34 añadidas: una ruta registrada tiene que poder releerse desde un checkout
  limpio, y la rebanada que el manifiesto hashea tiene que ser la que Git publica; V35 re-deriva la
  comparación CURRENT vs PROPOSED desde la matriz y `config/risk.yaml`, y se probó que un dato
  manipulado la pone en `NOT_VERIFIED`),
  `edge14r_verify.py` 32/32 `VERIFIED`.
- Últimos commits de la ronda: `d45a1fa` — *Capture the first prospective hour, and record paths a
  clean checkout can follow…*; después el de informes y el de re-verificación.
- **No preparar ni tocar** lo ajeno: `data/st6/**`, `.ci/**`, `docs/research/work_packages/**`,
  `reports/economic-recovery/RFC-EDGE-014/**`, `evidence/real_decisions/**`, los tests nuevos de
  `swing`/`rfc035*` de otro agente, y en general los ~156 ficheros sucios de otras líneas de trabajo.

## 3. Hecho (con evidencia ejecutada)

### P0 — defectos de certificación

| Defecto | Estado | Evidencia |
| --- | --- | --- |
| `order_check=false` en el holdout 14R | **cerrado**: protocolo en dos fases (congelación en un commit, captura en otro proceso) | `OOS_CAPTURE_MANIFEST_V2.json`: `ORDER_VERIFIED`, 5 cláusulas, congelado 07:15:28Z → commit `b4ff588` (07:19:24Z) → captura 07:20:21Z; blob LF-normalizado `cea0be8934…` idéntico al fichero en disco. Re-capturado 09:01:39Z: **3 barras prospectivas** (apertura 08:00Z, una por símbolo), estado `OOS_ACCRUING_WITH_PROSPECTIVE_BARS`, `scoring_run=false` |
| manifiestos con rutas absolutas del host | **cerrado**: el manifiesto escribe rutas relativas al repo, el verificador re-ancla la ruta congelada de 14R por su cola y V33/V34 exigen que un checkout limpio pueda releer y publicar lo mismo | `edge15_oos_preregistration.py` (`_rel`), `edge15_verify.py` (`_resolve`, V33, V34) |
| verificador = constructor (`engine_parity`) | **cerrado**: import eliminado (no acotado); regla, indicador, convenciones de comisión y curva de equity re-implementados | `edge15_verify.py` V31 (no importa constructor), `edge14r_verify.py` V32; 14R re-verificado 32/32 |
| identidad por `(symbol, opened_at, entry_price)` | **cerrado**: el broker acuña `position_id`/`entry_order_id`/`exit_order_id`/`trade_id`, continúa la secuencia tras `restore()` | `broker.py`; `tests/unit/paper/test_broker_identity.py` (8 pruebas: colisión de reloj congelado, continuidad tras `restore()` y reloj de replay determinista); la verificación encontró que el carril compartía libro entre símbolos (56 ids, 24 distintos) y se corrigió con un libro por símbolo |
| una sola cifra de equity | **cerrado**: `accounting_snapshot()` separa caja, realizado, no realizado y patrimonio a mercado, con la comisión de entrada devengada como término propio y 4 identidades | `broker.py`; V22/V23 sobre el carril: identidades correctas en los 3 libros |
| divergencias de Jesse (7,02 bps) y VeighNa (2 operaciones) | **cerradas**: descomposición exacta | `PARITY_DIVERGENCE_EXPLAINED.json/.md`: `6.985523 (precio) + (−0.059751) (comisión realizada del motor) + 0.095587 (convención propia) = 7.021359`, error 0,0; las 42 restantes dentro de 1 bps; las 2 de VeighNa son las dos últimas entradas de la regla |

### P1/P2 — búsqueda de alpha y costes

Cinco familias mecánicamente distintas, auditadas contra las ya rechazadas
(`rejected_family_audit`). Cola reservada (30 % final, parámetros congelados de antemano):

| familia | operaciones | bruto/op | neto 1× | neto 2× | decisión |
| --- | ---: | ---: | ---: | ---: | --- |
| `mean_reversion_vol_liq` | 811 | +54,84 bps | +21 075 | −2 326 | `EXPERIMENT_COST_FRAGILE` |
| `vol_regime_breakout` | 171 | +223,79 bps | +33 367 | +28 465 | `REJECT_OUTLIER_DRIVEN` (las 5 mejores = 1,31× todo el bruto; mediana negativa) |
| `trend_pullback` | 895 | −37,04 bps | −58 809 | −84 464 | `REJECT` |
| `cross_sectional_rotation` | 355 | −35,63 bps | −11 465 | −16 605 | `REJECT` |
| `maker_only_spread_capture` | — | — | — | — | `DEFER_NO_FILL_MODEL` (sin modelo de cola/fills) |

Comparación **CURRENT vs PROPOSED** con los mismos datos, capital (10 000 USDT) y restricciones
(tamaño de orden 333,33 USDT de la política real, leído por el constructor y re-leído por el
verificador): CURRENT se lee del ledger autoritativo (0 estrategias admitidas → plano, 0 operaciones)
y ninguna propuesta lo sustituye → `NO_PROPOSAL_BEATS_CURRENT`. La matriz lleva ahora `decision` y
`current_runtime_net_bps_total` en cada fila.

Modelo de costes por venue y producto con procedencia declarada (`KNOWN` comisión 10 bps/lado,
`ESTIMATED` medio spread, `HYPOTHESIS` slippage √tamaño e impacto lineal): BTC/ETH 23,3536 bps;
SOL 25,30 bps; alt fino 28,96 bps por vuelta completa a 200 USDT. Ningún coste cero en la
certificación. Sensibilidad 1×/2×/3× en cada fila de la matriz.

### P3 — carril prospectivo experimental

6 003 barras exploradas, 210 ciclos de decisión con el `PaperBroker` y la política de
`config/risk.yaml` reales: 182 `NO_TRADE`, 14 entradas, 14 salidas protectoras, **28 órdenes
simuladas**, −12,81 USDT realizado (bruto −3,48 / comisiones 9,33), identidades contables correctas,
ledger autoritativo con sha256 idéntico antes y después, familias rechazadas registradas como
negativas a operar, 0 órdenes enviadas. Etiqueta `EXPERIMENTAL_PROSPECTIVE_PAPER` en cada ciclo.
`--extend-prospective` añade las barras capturadas (3, una por símbolo): **0 ciclos prospectivos**,
0 señales forzadas, PnL `DESCRIPTIVE` −12,809961 / `PROSPECTIVE` 0,000000 USDT. Una barra alcanzada
saltando > 1,5 h se trata como calentamiento (`NO_TRADE/GAP_BRIDGE_WARMUP`).
Hallazgo de riesgo (no de estrategia): los stops por defecto (0,5 %/0,75 %) son mucho más estrechos
que el horizonte de la familia superviviente, así que todas las posiciones cerraron por stop.

### P4 — verificación y pruebas

- `scripts/edge15_verify.py` (no importa ningún módulo constructor): **35/35, veredicto VERIFIED**.
- `scripts/edge14r_verify.py` con la comprobación de holdout endurecida: **32/32, VERIFIED**.
- Causalidad de las familias: 10 pruebas que truncan la serie y exigen que la historia ya cerrada se
  reproduzca idéntica.
- `ruff check`, `ruff format --check` y `mypy` limpios en los ficheros del paquete (re-ejecutado
  07:53Z: RUFF=0, FMT=0 —9 ficheros ya formateados—, MYPY=0 sobre 7 ficheros).
- Pruebas dirigidas re-ejecutadas 09:07Z: `tests/unit/paper` (suite entera) → **64 passed**;
  `tests/unit/paper/test_broker_identity.py` tiene 8 pruebas (incluye reloj de replay determinista:
  dos ejecuciones del mismo replay hashean igual, `889734699a8d…`).
- `tests/unit/research/test_alpha15_causality.py` → 9 passed (causalidad de las familias).
- Suite completa (dos tramos, 07:24-07:39Z): **2562 passed + 1455 passed**, 3 fallos, ninguno del
  paquete: (a) `test_two_fills_in_the_same_clock_tick_cannot_share_an_identity` — la primera
  versión dependía de la resolución del reloj del host; se reescribió para construir la colisión
  explícitamente y ahora pasa (incluida en los 16 de arriba); (b) y (c) dos pruebas de
  `test_st6_forward_regime.py` que comparan artefactos `data/st6/**` regenerados por la tarea
  programada — línea de trabajo ajena, se registran como **limitación**, no como superadas.

## 4. Pendiente

1. **Holdout prospectivo `OOS_ACCRUING_WITH_PROSPECTIVE_BARS`**: 3 barras (una por símbolo), ninguna
   puntuada y ninguna leída por la selección. Sigue acumulando: cada hora cerrada añade una barra por
   símbolo con `--capture` (idempotente, sólo añade lo nuevo) y después hay que **commitear el slice
   antes de verificar**, porque V34 falla si el fichero que el manifiesto hashea no es el que Git
   publica. No hay muestra para inferir nada todavía.
2. **Ninguna estrategia admitida**: sigue siendo el freno correcto. Candidatas registradas
   deshabilitadas (`RESEARCH_CANDIDATE` 12, `RESEARCH_REQUIRED` 3, `paper_candidates: []`).
3. **Hipótesis siguiente** (fijada por la evidencia): familia cuyo bruto por operación supere con
   margen la vuelta completa de su nivel (≥ 24 bps en primer nivel, ≥ 29 bps en alt fino) y aguante
   el multiplicador adverso; menos operaciones y más grandes en BTC/ETH, y brazo maker sólo cuando
   exista un modelo de fills validado contra ejecuciones reales.

## 5. Bloqueos / items abiertos (no ocultar)

- **Guardián de disco** en `INSUFFICIENT_FREE_SPACE` (4,17 GiB libres, frente a 5,9 GiB al
  principio de la sesión: el árbol de `.git` y los artefactos de otras líneas crecen). **No se ha
  relajado**; el paquete escribió sólo bajo su propio directorio y no añadió corpus nuevos.
- **Contención con la tarea programada ST6** (entorno, no defecto): puede hacer esperar a los tests
  de `test_st6_scheduler.py`.
- `quiet_runtime_logs` sigue dejando el structlog global en CRITICAL en procesos largos del
  *runtime*; el guardia existente es de tests. Arreglo de producción **pendiente** y fuera de este
  paquete (requiere su RFC).
- El filtro de percentil de ATR de la familia de reversión es una **aproximación de 50 cubos**
  (declarada en `ALPHA_RESULTS.json`); por eso la evidencia decisiva se publica por operación.

## 6. Comandos de reanudación

```bash
# 0. Estado real
git -C "$(git rev-parse --show-toplevel)" log --oneline -3
git -C "$(git rev-parse --show-toplevel)" status --porcelain | head -40

# 1. Reproducir el paquete completo (rápido: ~1 min)
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge15_alphas.py
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge15_paper_lane.py --extend-prospective
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge15_parity_explain.py
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge15_verify.py   # 34/34
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge14r_verify.py   # 32/32

# 2. Holdout: congelar (una vez) y capturar (repetible, sólo añade lo nuevo).
#    Orden obligatorio: capturar -> commitear el slice y el manifiesto -> verificar
#    (V34 rechaza un slice que Git todavía no publica).
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge15_oos_preregistration.py --capture

# 3. Gates de estilo, tipos y pruebas
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python -m ruff check scripts/edge15_*.py scripts/edge14r_verify.py src/trading_bot/research/economic_recovery/alpha15.py src/trading_bot/paper/broker.py
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python -m mypy scripts/edge15_*.py src/trading_bot/research/economic_recovery/alpha15.py src/trading_bot/paper/broker.py
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python -m pytest tests/unit/paper tests/unit/research/test_alpha15_causality.py -q

# 4. Suite completa (log persistente; ~26 min)
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python -m pytest tests/unit -q \
  --tb=short -rf -p no:cacheprovider > /tmp/edge15/unit_tests_full.log 2>&1; echo "EXIT=$?"
```

## 7. Protocolo de actualización

- Al **cerrar un hito**: marcar la fila correspondiente en §3 y actualizar §4/§5.
- Al **cortarse la sesión**: anotar el comando exacto que se estaba ejecutando y su log.
- **Nunca** mover un elemento de §4 a §3 sin evidencia ejecutada (log, artefacto, exit code).
