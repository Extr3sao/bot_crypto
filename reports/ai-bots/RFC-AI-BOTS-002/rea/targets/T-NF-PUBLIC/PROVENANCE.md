# T-NF-PUBLIC · procedencia del artefacto

**Estado: `UNATTRIBUTED_NO_DEPLOYMENT_RECEIPT`.** Este dossier describe un artefacto
observado en una URL pública. No afirma de qué repositorio ni de qué commit salió.

## Qué se conserva

Todo lo obtenido el 2026-10-17 sigue aquí, con sus hashes intactos:

| operación | `evidence_id` | sujeto |
| --- | --- | --- |
| `analyze_javascript_application` (12 chunks) | `ev_aee35b0f11df7a73b082c5cbc72e10c97f27b22917da003998d93eaa455617fc` | `5fbc183a1c15b1ffe993669699205a944dc72237d241c7db5a55c54681ff44b9` |
| `list_browser_targets` (Chrome 155, perfil vacío, CDP loopback) | `ev_f7020db13e2de339e89e64231dd55522fe97ab8d17447644e8dfb5ef0961bb00` | — |
| `capture_web_screenshot` | `ev_47c01accd3491fd6e10e893f8a045e5fee226fa520f648f4460396a619efbaf1` | PNG de viewport |
| `analyze_web_bundle` | `ev_82d99570975285bde3570fb1b4002ea6b323fefed4308ce5c39ac23d0621d56c` | 43 scripts, 0 fallos |

Los 12 digests por fichero están en `TARGET_BASELINE.json`. Nada de esto se borró ni se
reasignó: la evidencia decía la verdad sobre **lo que se descargó**; lo que estaba mal era
la etiqueta del origen.

## Qué se corrigió y por qué

La v3 archivó estos chunks bajo `195440/nof1.ai` en el commit `5d27641`. La v3.1 midió ese
commit (clon aislado, `5d27641dfa47cc942aa0709ffb3f5237de876373`, árbol `b3ae235a0ff6555ff7a77c5c76c93cad2b1f5463`) y encontró una
contradicción de sistema de build, no una simple falta de prueba:

| hecho | bundle servido en www.nof1.ai | repo `195440/nof1.ai` @ `5d27641` |
| --- | --- | --- |
| marcador `__NEXT` | presente en 9 de 12 ficheros | 0 ficheros en todo el árbol |
| marcador `turbopack` | presente en 7 de 12 | 0 |
| rutas `_next/static` | presentes en 3 | 0 |
| dependencia `next` en `package.json` | — | ausente; el build es `tsdown` |
| identificadores del repo (`open-nof1`, `voltagent`, `gate-api`, `195440`, `vt_`) | 0 ocurrencias | presentes por diseño |
| dashboard propio | — | `https://open-nof1.195440.com/` (HTML+JS estático) |

Un repositorio sin Next.js **no puede** producir chunks de Turbopack con ese esquema de
nombres. La asociación no era sólo no demostrada: es refutada por el artefacto.

Ver `../T-NF-NOF1/PROVENANCE.md` para la medición completa del repositorio real.
