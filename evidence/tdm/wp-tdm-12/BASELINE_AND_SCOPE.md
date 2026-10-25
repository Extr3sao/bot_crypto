# WP-TDM-12 — BASELINE AND SCOPE

**RFC:** RFC-TDM-012 v1.0 · **Fecha:** 2026-10-25
**Worktree:** `C:\Users\GVLLFR0035\Downloads\ff-wt-tdm12` · **Rama:** `evidence/tdm12` · **HEAD:** `504256ec8934b97a6d405c202604ecac81a02346`
**Medido, no asumido:** todo lo de esta página sale de `.tdm12/review.json → preflight` en esta ejecución.

---

## 1. Estado Git real (T-01)

| Elemento | Valor |
| --- | --- |
| HEAD del worktree | `504256ec` ("Refute the short-in-downtrend lead…") |
| Rama | `evidence/tdm12`, creada desde el commit de evidencia de TDM-11 |
| Árbol con archivos trackeados modificados | **0** |
| Base del commit | `e67194e7` (TDM-11 se construyó encima) |
| Checkout compartido | HEAD `e67194e7`, **17** archivos trackeados modificados, **no tocados** |
| Python / plataforma | 3.11.15 · Windows 10.0.26200 |
| Red | no usada en ninguna fase |

El RFC pedía no asumir `e67194e7` ni `504256ec`: se resolvieron ambos. El checkout compartido sigue
exactamente donde estaba (17 modificaciones heredadas, ninguna revertida, ninguna limpiada, ninguna
commiteada).

**Método de aislamiento:** `git worktree` desde `504256ec`. Los datasets sellados se copiaron a
`data/tdm08` y `data/tdm10` del worktree y se re-verificaron contra sus manifiestos (24/24 hashes).

## 2. Qué se ha leído y qué no

| Leído | Estado |
| --- | --- |
| `evidence/tdm/wp-tdm-11/*` (10 archivos) | hashes comprobados contra blobs de `HEAD` |
| `data/tdm10` (DEV, 12 archivos) | hash + integridad |
| `data/tdm08` (HOLD, 12 archivos) | hash + integridad |
| `config/strategy_admission.json` | 24 entradas, 0 admitidas |
| `config/strategies.yaml` | 5 estrategias declaradas, ninguna `enabled` |
| `scripts/autonomous_paper.py`, `scripts/start_paper_trading.py` | registro de familias del runtime |
| `src/trading_bot/strategies/*`, `research/families/*` | implementaciones |

**No leído:** ninguna barra con `open_time >= 2026-10-24T16:00:00Z`. Los cargadores de ambos scripts
rechazan el dataset si aparece una, y `V4` de TDM-11 ya lo había comprobado sobre los mismos archivos.

## 3. Alcance ejecutado

**Dentro:**
- revisión de integridad y reproducción del paquete TDM-11 (12A);
- análisis de dependencia estadística y sensibilidad del intervalo (12A);
- inventario de estrategias realmente alcanzables desde el runtime (12B);
- registro de ventanas de datos con etiqueta de contaminación (12B);
- reevaluación retrospectiva de las 24 celdas ya existentes, sin retocar parámetros (12B);
- un veredicto de cribado: como máximo un `PREREG_CANDIDATE` o `NO_ELIGIBLE_CANDIDATE`.

**Fuera, y no ejecutado:** PAPER, SHADOW, CANARY, LIVE; cambios de sizing, leverage, límites, claves o
permisos; reescritura de costes/riesgo/ejecución; familias nuevas; ajuste de umbrales; refit; apertura de
una muestra confirmatoria; promoción de cualquier estrategia. **Órdenes: PAPER 0, LIVE 0.**

## 4. Restricciones autoimpuestas

1. Solo archivos nuevos; ningún archivo existente modificado (verificado con `git status`).
2. Parámetros de familia congelados: los hashes de los seis módulos se registran en
   `CANDIDATE_REGISTRY.json → parameter_hash`.
3. El mínimo de 36 operaciones de TDM-11 **no** se traslada: cada celda calcula su propio requisito de
   potencia a partir de su propia dispersión (§ `RETROSPECTIVE_TRIAGE_REPORT.md`).
4. Toda ventana usada para comparar candidatos queda etiquetada como expuesta; ninguna se reetiqueta
   como confirmatoria.

## 5. Entregables y ubicación

`evidence/tdm/wp-tdm-12/` — ruta **no ignorada** por Git (comprobado con `git check-ignore`), versionada en
el commit de cierre. `reports/**` sigue ignorado y no se usa como almacén de evidencia.
