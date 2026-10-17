# T-NF-NOF1 · Traza observada (qué se vio, qué no)

## Ejecutado de verdad

| # | operación REA | evidence_id | resultado |
|---|---|---|---|
| 1 | `analyze-javascript-application` sobre los 12 chunks públicos | `ev_aee35b0f11df7a73b082c5cbc72e10c97f27b22917da003998d93eaa455617fc` | exit 0, 59,9 s |
| 2 | `list-browser-targets` sobre Chrome 155 CDP loopback | `ev_f7020db13e2de339e89e64231dd55522fe97ab8d17447644e8dfb5ef0961bb00` | exit 0 |
| 3 | `capture-web-screenshot` de `https://www.nof1.ai/` | `ev_47c01accd3491fd6e10e893f8a045e5fee226fa520f648f4460396a619efbaf1` | exit 0, PNG de viewport |
| 4 | `analyze-web-bundle` de la misma página | `ev_82d99570975285bde3570fb1b4002ea6b323fefed4308ce5c39ac23d0621d56c` | exit 0, 43 scripts, 0 fallos |

## Lo que la evidencia sí sostiene

* El sitio público sirve **12 chunks** con digest de directorio `5fbc183a…744b9`; se
  parsearon 12/12 sin fallos, 231.769 nodos AST y **15 hallazgos**.
* El grafo estático contiene 36 nodos (12 assets, 10 módulos, 7 endpoints, 6 desconocidos)
  y 43 relaciones. Los «endpoints» extraídos son identificadores minificados (`dpl`, `a`,
  `b`, `cookie`, `/_next/image`): la minificación destruye los nombres que darían sentido
  al flujo.
* La captura de runtime confirma que la página es un frontend Next.js y que el bundle
  observado se parsea completo (43 scripts, 191.416 nodos).

## Lo que la evidencia NO sostiene (y por eso no se certifica)

* **No se ejecutó el JavaScript del target**: la propia limitación de REA lo dice
  («JavaScript and HTML were parsed as inert text»). No hay traza de ejecución.
* **No se observó ninguna llamada multimodal**: ni petición, ni imagen adjunta, ni
  respuesta JSON del modelo, ni decisión, ni riesgo, ni orden. El análisis estático de un
  bundle minificado no llega a esa cadena.
* La cobertura semántica es **parcial/truncada** y 2 ficheros agotaron el heap del worker
  (`1ht6x9rgxdzh-.js`, `2-93uiwpd3jjk.js`): sus hechos semánticos no están.
* Por tanto: `REA_TARGET_OBSERVED = YES` (superficie y estructura),
  `UPSTREAM_RUNTIME_REPRODUCED = NO`, `BEHAVIOR_RECONSTRUCTED = NO`.

## Comparación con nuestro runtime

El patrón que nos interesa (PNG → llamada multimodal → decisión → riesgo → paper) **no se
puede comparar** con lo observado en nof1: allí no hay traza de ese flujo, sólo estructura
de bundle. Clasificación: `NOT_COMPARABLE` (no «equivalente» ni «divergente»), y la
decisión de adopción queda `DEFER`, no `ADOPT_VERIFIED`.
