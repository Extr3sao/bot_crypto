# SUPERVISOR INTEGRATION AUDIT — TAP-SUPERVISOR-INTEGRATION-001

## Informe ejecutivo (una página)

**Veredicto: `INTEGRATION_PATH_IDENTIFIED`. `READY: NO`.**

**¿Cómo incorporamos el supervisor a `main` con el menor riesgo y el mínimo trabajo necesario
para conseguir una campaña PAPER real?**

**No fusionando la lane. Migrando 47 rutas, y demostrándolo con una sesión real.**

| Alternativa | Coste | Resultado medido |
| --- | --- | --- |
| A · fusionar `codepaper/supervisor-001` | 301 commits, 1804 rutas, +1 660 730 líneas | merge **sin conflictos** (`merge-tree` exit 0, árbol `1053827…`) y, aun así, inaceptable: arrastra 1 248 rutas de informes, 450 `.py` ajenos al supervisor y un test heredado roto |
| B · integrar por componentes funcionales | — | la lane no está particionada así: el 69 % de sus rutas son informes; no hay frontera que separar |
| **C · migrar el runtime mínimo** | **47 rutas** (35 módulos nuevos, 7 modificados, 2 de config, `pyproject.toml` + `uv.lock`, `.gitignore`) | **68 de los 110 ficheros del cierre de imports ya son byte-idénticos en `main`**; la rebanada arranca y **completa una sesión PAPER real** sobre `main`, pero deja **6 tests heredados en rojo** |

El número que decide es **47**, no **301**. Cierre estático de imports desde los ocho entry
points del supervisor: **110 ficheros**; 68 idénticos en `main`, 35 ausentes, 7 distintos.
Más **2 ficheros de configuración** que ningún grafo de imports puede ver y que costaron una
sesión fallida descubrir. El resto —1 248 rutas de `reports/` y `docs/`, 355 `.py` que no
alcanza ningún script— es investigación, no runtime.

**Lo probado, ejecutado y no deducido:**

- La rebanada de 42 ficheros sobre `main` (más `matplotlib` declarado y dos configs) **arranca
  y termina una sesión PAPER real**: `STOP_COMPLETED (CLEAN_END)`, 1 ciclo, `live_orders 0`,
  runtime estable, árbol limpio. Sin credenciales: datos públicos de Binance REST.
- En la lane, la misma orden ejecuta **5 ciclos**; una **campaña real con un crash** produce
  `RECOVERED`, cadena `INTACT` de 13 líneas y `live_orders 0` en 5 minutos.
- El supervisor **se niega a avanzar** cuando debe: sin progreso (`STOP_NO_PROGRESS`), con el
  árbol sucio (`RUNTIME_PATHS_DIRTY`), y sin ciclos (`STOP_BLOCKED`). Tres negativas
  nombradas, no tres reintentos silenciosos.

**Lo que impide decir `READY` (tres puertas, ninguna de Git):**

1. **Contrato de riesgo sin reconciliar.** La lane cambia `risk/manager.py` (+339/−9) y añade
   `risk/defensive_blocks.py`; eso rompe **dos tests heredados**
   (`tests/unit/risk/test_futures_independent_verifier.py`) **también en la lane**, que nunca
   actualizó ese fichero. No es un artefacto de la migración: es una regresión viva que la
   fusión heredaría. Decide el risk-manager: ¿los 28 checks nuevos por decisión
   (`bracket_provenance` entre ellos) son el contrato correcto?
2. **Ningún verificador juzga una campaña real.** Sobre la campaña real: el verificador de
   lock la **rechaza** (`UNSUPPORTED_CAMPAIGN_SCHEMA`, espera `TAP_PAPER_LOCK_CAMPAIGN_V1`) y
   el de supervisor **crashea** (`FileNotFoundError: campaign/scenarios/SCENARIOS.json`, ruta
   que solo tiene el fixture). El PASS 33/33 del RFC sigue siendo sobre fixture.
3. **B1 sin reproducir.** 8 corridas hoy (5 aisladas + 3 de la suite `ops` completa), 0 fallos:
   el fallo histórico bajo carga no se reprodujo, así que no sé si está arreglado o escondido.

**Corrección de método (importante para quien lea mi primera cifra):** el cierre empezó
diciendo 19 ficheros. Estaba mal por tres motivos, cada uno encontrado ejecutando, no leyendo:
faltaba el *entry point hijo* del supervisor (`vision/prospective.py` quedaba oculto), los
imports relativos se resolvían contra el módulo en vez del paquete (`economic_recovery/costs.py`
desaparecía), y las dependencias de **configuración** no aparecen en ningún grafo de imports.
19 → 37 → 42 → 44 (con config) → 46 (con `pyproject.toml` y `uv.lock`) → 47 (con `.gitignore`).
Las cifras de este informe son las medidas después de esas correcciones; el detalle está en [DEPENDENCY_MAP.md](DEPENDENCY_MAP.md).

---

## 1. Referencias verificadas (no asumidas)

| Referencia | Declarada | Medida |
| --- | --- | --- |
| `main` | `e67194e7` | `e67194e7` ✅ |
| `codepaper/supervisor-001` | — | `3b758e22` (2026-10-23 20:56) |
| Commit de cierre del RFC | `fda95664` | `fda95664` ✅ |
| `main` → RFC | 305 | **307** = 301 lane + 6 del RFC/merge |
| `main` → lane | 301 | **301** ✅ |
| Commits de `main` ausentes en la lane | — | 4 |
| Merge-base `main`/lane | — | `1d2192b0` |
| Merge-base `main`/RFC | — | `0e13160a` |

`305` era correcto en `f118e556`; los dos commits de cierre del RFC lo suben a 307. No es una
discrepancia del trabajo previo: es un recuento anterior a dos commits.

## 2. Qué hay realmente en la lane

- **1 804 rutas**: 1 761 añadidas, 43 modificadas. **1 248** bajo `reports/`/`docs/` (69 %);
  **487** de código/config; **450** `.py` que `main` no tiene (lane: 1 257; `main`: 818).
- De los **301 commits**, por área dominante: 152 informes, 54 scripts, 33 docs, 31 tests,
  **21 `src/`**, 8 config/datos, 2 otros. Solo **38** tocan las 42 rutas del runtime.
- No es "la lane del supervisor": es el tronco de desarrollo del proyecto con el supervisor
  dentro. `main` se quedó atrás.

## 3. Dependencia del RFC `REPRO-001`

Sus seis scripts y ocho módulos de `ops/` no existen en `main`. Su `NO_GO` de integración era
correcto; sigue siéndolo. Añadido no obvio: **`main` ignora `reports/*`**, así que ningún
informe puede aterrizar allí sin la excepción de `.gitignore` que la lane trae — y esa
ausencia explica por qué todo el trabajo documental acabó en una rama y no en `main`. La rebanada de este informe los incluye: si se migra la rebanada, el
RFC pasa a ser aplicable encima.

## 4. Riesgo de fusionar la lane completa

- Mecánicamente **imposible de frenar por conflictos**: `merge-tree` exit 0, 0 conflictos.
  Con el RFC incluido, árbol `1a2f60b…`, también 0 conflictos y 2 012 ficheros.
- Semánticamente: 301 commits sin revisar, 450 `.py` nuevos, informes y experimentos mezclados
  con runtime, y el test de riesgo roto viaja en el merge. El conflicto cero es el peligro: no
  hay señal que obligue a mirar.

## 5. Lo que no verifiqué

- **Suite completa de `main`**: `pytest tests/unit` no terminó en 600 s. Medí las áreas
  afectadas (`tests/unit/paper`, `tests/unit/risk`), no el total. `NOT_TESTED`.
- **Campaña larga o económicamente significativa**: 5 minutos y 5 ciclos. Nada sobre
  rentabilidad; la admisión sigue `NO_GO`.
- **Ruta `ccxt` autenticada**: no usada, no necesaria para PAPER.
- **B2** (`verify_claims.py` no portable): no lo reaudité.
- **B1**: sin reproducción, sin diagnóstico.

Ninguna afirmación se apoya en un test que no ejecuté; lo no ejecutado aparece como
`NOT_TESTED`, `BLOCKED` o `FAIL`, nunca como `PASS`.
