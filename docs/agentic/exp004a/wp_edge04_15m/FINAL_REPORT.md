# WP-EDGE04-RECOVERY-15M — el corpus 15m no está perdido: es irrepetible

**Dictamen: `BLOCKED_WITH_EVIDENCE`.** El corpus congelado de 15m se identifica ahora sin
ambigüedad, su productor original está localizado y se ha re-ejecutado. La conclusión no es
«no lo encuentro» sino algo más incómodo y más útil: **los bytes no se pueden volver a
producir desde el exchange**, porque la última fila de cada shard se escribió mientras su
propia barra seguía abierta.

| Criterio de aceptación | Resultado |
|---|---|
| 1. Corpus completo y SHA-256 exactos | **FAIL** — 3/3 shards presentes en la búsqueda, 0 con los bytes del pin |
| 2. Observación real, nueva, durable | **FAIL** — no se intentó: el gate del pin impide el tick |
| 3. Verificadores críticos PASS | **FAIL** — `edge03_verify` aborta en el pin, `edge04_verify` 7/15 |
| 4. Tarea programada funcional sin falsas señales | **PARTIAL** — correcta y aparcada; su estado dice la verdad |
| 5. `FALSE_SUCCESS = 0` | **PASS** |
| 6. Verificación independiente y commits trazables | **PASS** |

---

## 1. Primero, la identidad: el pin no es un hash de archivo

`edge01.data._digest` no digiere el archivo, digiere `sha256(nombre + sha256(bytes))`. Por eso
un valor de pin no se puede contrastar con un candidato sin conocer el hash del archivo, y por
eso el bloqueo anterior parecía opaco.

Ese hash existe, escrito antes de la pérdida: `data/economic001/EVIDENCE_CLOSURE.json`
(commit `6b4edd45`, 2026-10-08) registra los `sha256` de los doce shards de ALPHA-003.
Recomputando el pin a partir de ellos:

| Activo | `sha256` registrado | Pin recomputado | Pin congelado |
|---|---|---|---|
| BTC | `60b0630153dc8e87…` | `cd1d2ea256a97f7c` | `cd1d2ea256a97f7c` ✓ |
| ETH | `b3b1f02e9a299500…` | `b8fd5744cc66f635` | `b8fd5744cc66f635` ✓ |
| SOL | `d3a637c2f5e98c12…` | `72a268137cbe944b` | `72a268137cbe944b` ✓ |

**El corpus congelado de 15m es, con 3/3 de coincidencia, `data/raw/alpha003/price/<SYM>USDT_15m.json`.**
Y sus tamaños están en `reports/edge-recovery/WP-EDGE-06/STORAGE_INVENTORY.json`: BTC
4.497.888 bytes, ETH 4.466.466 bytes. SOL no aparece (el inventario sólo lista los archivos
mayores de cada subárbol), y eso se registra como ausencia, no se estima.

## 2. El productor existía, y por eso nadie lo encontraba

`scripts/alpha003_run.py` (commit `71dd6fac`, 2026-10-07) es el único código que escribió esos
shards:

```
ccxt.binanceusdm.fetch_ohlcv(symbol, tf, since=2024-10-01T00:00:00Z, limit=1000)
    → pagina con since = último_ts + 1, corta en el primer lote incompleto
    → path.write_text(json.dumps(rows))          # separadores por defecto, sin indent
```

La búsqueda anterior no lo encontró por dos motivos mecánicos, no por falta de esfuerzo: el
nombre se compone como `f"{symbol}_{timeframe}.json"` con `symbol` ya siendo `BTCUSDT`, de modo
que ningún texto del productor contiene la cadena `BTCUSDT_15m.json`; y `data/raw` está en
`.gitignore`, así que ninguna versión del repositorio guardó los bytes.

## 3. Reejecutado: la estructura vuelve entera, los bytes no

Ejecutado con `ccxt 4.5.63` contra `fapi.binance.com`, truncando en el último instante congelado
(`1791372600000` = 2026-10-07T11:30Z):

| Activo | Filas | Primera | Última | Bytes | Registrado | Δ | sha256 | Pin | ¿Pin? |
|---|---|---|---|---|---|---|---|---|---|
| BTC | 70.703 | 1727740800000 | 1791372600000 | 4.497.889 | 4.497.888 | **+1** | `4830906879e6238d` | `b21d66e3aa2292ea` | no |
| ETH | 70.703 | 1727740800000 | 1791372600000 | 4.466.467 | 4.466.466 | **+1** | `511de6ac63eceb64` | `9b9eaca812a7dbac` | no |
| SOL | 70.703 | 1727740800000 | 1791372600000 | 4.095.008 | — | — | `00daffcdd9dc6da4` | `9ba67d2602574211` | no |

70.703 filas, mismo primer y último timestamp, mismos huecos: **exactamente** lo que
WP-EDGE-01 registró. Un byte de diferencia en los dos shards cuyo tamaño está en acta.

**El control de 5m es el que convierte esto en una medición.** El tamaño registrado de
`BTCUSDT_5m.json` es 13.389.298; mi serie cortada en el mismo instante daba 124 bytes menos, es
decir exactamente dos filas de 62 bytes, lo que sitúa la última fila del archivo original en la
barra de las 11:40 — el productor corrió entre las 11:40 y las 11:45 UTC. Cortando ahí:

| Control | Valor |
|---|---|
| Filas | 212.109 |
| Bytes | 13.389.298 |
| Registrado | 13.389.298 (**Δ = 0**) |
| sha256 | `092a0c5c56064e76` ≠ `4413f407bca6ae52` |

Tamaño **exacto**, hash distinto. La receta es fiel y la diferencia no es de formato ni de filas
que falten en el exchange: es de **valores**.

## 4. La causa: la última fila se escribió con la barra aún abierta

El exchange devuelve la barra en curso. Cuando el productor escribió, la última fila de cada
shard era una barra que todavía se estaba formando; en los minutos siguientes su `close`,
`high`, `low` y `volume` se movieron hasta los valores definitivos que hoy sirve la API. Esos
valores intermedios no se publican en ningún sitio — no hay tick a tick que los reconstruya, y
el instante exacto de captura sólo se conoce con una ventana de cinco minutos.

Por eso el corpus es **irrepetible por construcción**, no por un archivo que falte. Y por eso
sustituirlo por el shard recién descargado sería exactamente lo prohibido: no es el corpus
congelado, es uno parecido.

*Incertidumbre que se declara, no se esconde*: no se puede descartar que el exchange haya
corregido además alguna barra antigua entre el 7 y el 24 de octubre. En cualquiera de los dos
casos los bytes no son re-derivables, que es lo que decide este WP.

## 5. Búsqueda de copias: lo que se miró y lo que salió

| Fuente | Alcance | Resultado |
|---|---|---|
| Perfil de usuario (`Downloads`, `incident-backup-20261023`, `AppData/Local/Temp`) + `data/`, `reports/`, `docs/` | **136.888 archivos** | 15 con nombre compatible, todas hasheadas, **0 coinciden** |
| Árboles `alpha003` | mismos roots | **0** |
| Otras unidades (`G:`) | 8.372 archivos | **0** |
| Git (todas las ramas, todos los objetos) | 1 objeto `*_15m.json` (mi propio informe), 155 blobs huérfanos, el mayor 3,58 MB < 4,5 MB | **nada** |
| Git LFS | `.gitattributes` sin `filter=lfs`, `git lfs ls-files` vacío | **nada** |
| Papelera (`C:\$Recycle.Bin`) | 12 archivos, 41 entradas ilegibles declaradas | **nada** |

Las 15 coincidencias de nombre son productos de ALPHA-002 (ratios long/short, open interest):
mismo nombre, otra cosa.

## 6. Los gates, ejecutados, sin relajarlos

- `assert_frozen_corpus()` → `FileNotFoundError: …\data\raw\alpha003\price\BTCUSDT_15m.json`.
- **Prueba de no-sustitución**: los shards recién descargados se copiaron a un root de corpus
  aislado (nunca a `data/`) y el pin los rechazó con `…changed: shard digest is b21d66e3…, the
  frozen value is cd1d2ea2…`. Es el test que habría cazado a un builder que «recuperase» el
  corpus bajándolo.
- `scripts/edge03_verify.py` → salida 1: aborta dentro de `check_frozen_corpus` con el mismo
  `FileNotFoundError`, antes de completar sus 18 comprobaciones.
- `scripts/edge04_verify.py --state-root data/forward/edge04r01` → `VERIFY_FAIL` 7/15. Los 8
  fallos son consecuencia de que ningún tick llegó a consumir un slot: no hay `slots.jsonl`, ni
  `coverage.json`, ni evidencia diaria, ni publicación.

Ninguno de los fallos es de esta sesión: no se ha tocado código del experimento.

## 7. Estado operativo

`TradingAgentic-EDGE04-Forward` sigue **deshabilitada** y su acción es el lanzador
`scripts\edge04_forward_r01.cmd`, que nombra ambos roots y lleva escrita la condición de
rearme. El watchdog está listo (próxima ejecución 13:02). La tarea no finge: está parada porque
el gate está cerrado, no porque nadie sepa por qué.

## 8. Acción exacta siguiente

1. Conseguir `BTCUSDT_15m.json`, `ETHUSDT_15m.json` y `SOLUSDT_15m.json` **desde fuera de este
   host** (copia de `data/raw/alpha003/price` en otra máquina, backup, o el árbol original de
   ALPHA-003).
2. Comprobar `sha256` = `60b0630153dc8e87…` / `b3b1f02e9a299500…` / `d3a637c2f5e98c12…`, y
   `assert_frozen_corpus()` imprimiendo `15m:BTC cd1d2ea2…`.
3. Sólo entonces: `schtasks /change /tn TradingAgentic-EDGE04-Forward /enable`.

Re-congelar el corpus con los datos de hoy **no es esta reparación**: es otro experimento, con
otro pin, y no está autorizado aquí.

## 9. Defectos encontrados durante el trabajo

Los tres son míos, del verificador, y se corrigieron en vez de relajarse:

| Defecto | Efecto | Corrección |
|---|---|---|
| El subproceso del gate heredaba sólo `PYTHONPATH` | sin `SYSTEMROOT`, Windows no abre socket (`WinError 10106`): el gate «fallaba» por red, no por corpus | entorno heredado y `SystemExit(1)` en el hijo, para que el código de salida signifique algo |
| El ensayo de sustitución usaba un directorio temporal fuera del repo | `load_15m` registra la fuente como ruta relativa al checkout y lanzaba `ValueError` antes de llegar al pin | scratch dentro del árbol (`.tmp15m/`), nunca en `data/` |
| El escáner de órdenes se leía a sí mismo | el verificador nombra los verbos que prohíbe, así que siempre se declaraba culpable | se examinan sólo los dos scripts que tocan el mercado, con formas de llamada y no palabras |

Ninguno cambió el dictamen: los tres se detectaron precisamente porque el verificador se niega a
aceptar su propia palabra.

## 10. Verificación independiente

`scripts/edge04_15m_verify.py` no importa a los otros dos scripts: relee sus JSON, re-hashea los
bytes, re-deriva el pin y vuelve a ejecutar el gate y la prueba de sustitución. Resultado:
**13/13, `EVIDENCE_CONSISTENT_WITH_BLOCKED`, `FALSE_SUCCESS = 0`**. Si el replay hubiera
escrito el shard descargado en `data/raw`, la comprobación `SUBSTITUTE_IS_REFUSED` fallaría.

## 11. Artefactos

`RUN_REPORT.md`, `RUN_REPORT.json`, `EVIDENCE.json`, `FINAL_REPORT.md`, `VERIFIER.json` y `raw/`
(auditoría de fuentes, replay, salidas de los verificadores) en `docs/agentic/exp004a/wp_edge04_15m/`.
Los candidatos descargados viven en `.tmp15m/candidates/` (51 MB, sin seguimiento): nunca en
`data/raw`, para que nadie pueda confundirlos con el corpus.
