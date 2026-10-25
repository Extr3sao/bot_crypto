# WP-051-02D — changelog

**Run**: `wp051-02d/EXP-004A/2026-10-21` · rama `agent/ai-bots/RFC-TAP-AI-BOTS-003`

## Commits de este WP

| Commit | Qué cambia | Por qué |
| --- | --- | --- |
| `fc036d9` | `src/trading_bot/research/prospective/provenance.py`; gobernanza en `scripts/exp004a_capture.py`; 22 pruebas nuevas y 5 añadidas al extractor | El comando declarado podía producir un slice perfecto sin que ninguna declaración nombrase el código que lo produjo |
| `a179ed0` | `config/preregistrations/EXP-004A.datasets.phase2.json` | La declaración phase 1 no puede nombrar un commit que aún no existía; la sucesora lo hace sin reescribirla |
| `e170ae1` | Contraste por id de objeto de Git en lugar de bytes de checkout | La declaración se guarda en LF y este host la restaura en CRLF: comparar bytes bloqueaba por el motivo equivocado |

## Ficheros tocados

### Nuevos

- `src/trading_bot/research/prospective/provenance.py` — contrato de la declaración sucesora,
  autoridad temporal, vínculo al commit del generador y elegibilidad por barra.
- `config/preregistrations/EXP-004A.datasets.phase2.json` — declaración phase 2 versionada.
- `scripts/exp004a_provenance_preflight.py` — 15 controles de procedencia (builder).
- `scripts/exp004a_provenance_verify.py` — verificador independiente (5 controles + sello).
- `tests/unit/research/test_exp004a_provenance.py` — 22 pruebas.
- `docs/agentic/exp004a/wp051_02d/**` — este paquete.

### Modificados

- `scripts/exp004a_capture.py` — `--declaration`, `authorize()` antes de construir, bloque
  `provenance` en el manifiesto, exit 5 para captura no elegible, comprobación de que un ensayo no
  extiende la ventana declarada.
- `src/trading_bot/research/prospective/__init__.py` — exporta el contrato nuevo.
- `tests/unit/research/test_exp004a_capture.py` — 5 pruebas nuevas de gobernanza.

### No modificados (a propósito)

- `config/preregistrations/EXP-004A.datasets.json` — byte a byte igual, blob `43c9deea…`.
- `config/preregistrations/EXP-004A.json` — preregistro congelado intacto.
- `src/trading_bot/research/prospective/admission.py` — la regla C-004 no se toca.
- `docs/agentic/exp004a/independent/**` — la decisión independiente no se reescribe.
- Cualquier artefacto sellado, dataset histórico o fichero de otro WP.

## Decisiones registradas

1. **Sucesora, no corrección retroactiva.** Se crea un documento nuevo con identidad propia
   (`EXP-004A.datasets.phase2/v1`) que referencia la original por `sha256` y blob. La original no se
   abre en escritura: hay una prueba que lo comprueba.
2. **Sin enmienda al gate.** La sucesión se admite porque `prereg_gate.evaluate()` recibe el registro
   por parámetro y la sucesora conserva el esquema de entradas. Lo que el gate no verifica —la
   sucesión misma— se verifica en preflight y en el verificador. No se ha relajado ninguna regla.
3. **Un solo campo mutable.** `generator_code_commit` es lo único que puede diferir por entrada;
   cualquier otra deriva se nombra campo por campo y bloquea.
4. **Vigencia antes de la ventana.** `effective_from_utc = 2026-10-21T16:00:00Z`, anterior a la
   apertura del 2026-10-22 y posterior al commit de la declaración. Una captura solo es elegible si
   cada barra fue ingestada después de ese instante.
5. **Se declara el reloj que se tiene.** El registro de procedencia escribe
   `external_timestamp = UNAVAILABLE` en lugar de sugerir una notarización inexistente.
