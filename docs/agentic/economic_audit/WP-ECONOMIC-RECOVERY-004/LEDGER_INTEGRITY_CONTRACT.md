# Contrato de identidad del ledger de admisión — v1

**Identificador:** `strategy-admission-ledger-identity-v1`
**Sujeto:** `config/strategy_admission.json` (`_schema_version: strategy-admission-ledger-v1`)
**Estado:** vigente desde WP-ECONOMIC-RECOVERY-004.

---

## 1. Qué problema resuelve

El ledger es la única fuente de «¿puede esto ejecutarse en PAPER?». Su contenido se deriva
de dos artefactos commiteados y sus bytes son deterministas
([`scripts/build_strategy_admission.py`](../../../../scripts/build_strategy_admission.py)).
Hasta WP-003 estaba pinneado **sólo por bytes**, y ese pin se calculó sobre una copia de
trabajo Windows: `6c4dd0be…` es el render CRLF de la revisión `ddaf14d1`, no el blob de
ninguna revisión. Un pin de bytes no puede distinguir dos preguntas distintas:

| pregunta | qué la responde |
| --- | --- |
| ¿este fichero es exactamente el artefacto que se publicó? | SHA-256 de bytes |
| ¿este fichero **dice** lo mismo que el ledger certificado? | **identidad semántica** (este contrato) |

La primera es cierta en un checkout con LF y falsa en el mismo checkout si git reescribe
los finales de línea. La segunda debe ser cierta en ambos, y falsa en cuanto cambie una
decisión. Este contrato define la segunda sin tocar la primera: el pin de bytes se
conserva y se sigue comprobando.

> Este contrato **no** sustituye la identidad física de la evidencia inmutable. El input
> `COST_BARRIER.json` y los artefactos publicados siguen verificándose por SHA-256 de bytes.

---

## 2. Dominio semántico

El estado del ledger es el documento JSON completo **menos** las claves declaradas como
metadatos de procedencia:

```python
PROVENANCE_KEYS = ("_generated_by",)
```

| clave | clase | por qué |
| --- | --- | --- |
| `_schema_version` | semántica | cambia el significado de todo lo demás |
| `_claim` | semántica | es la regla que el ledger afirma aplicar |
| `_sources[].path` | semántica | nombra la dependencia de la que deriva cada decisión |
| `_sources[].sha256` | semántica | fija **qué revisión** de la dependencia se usó; una dependencia distinta es otra decisión |
| `_admission_cost_model` | semántica | declara contra qué modelo de costes se decide |
| `_period` | semántica | la ventana de la que proceden los números |
| `strategies.*` (todas las claves) | semántica | `status`, `admitted_for_paper`, `expected_gross_edge_bps`, `edge_evidence`, `rationale`, `timeframe`, `family`, `source_doc`, `known` |
| `_generated_by` | **procedencia** | nombra el script que renderizó el fichero, no una decisión; regenerar con otro nombre no cambia quién puede operar |

No hay ninguna otra exclusión. En particular **no** se excluyen importes, umbrales,
veredictos, digests de dependencias ni la lista de estrategias: si cambia alguno, cambia
la identidad.

---

## 3. Serialización canónica

```
state   := documento_parseado sin PROVENANCE_KEYS
sobre   := {"contract": "strategy-admission-ledger-identity-v1", "state": state}
canónico:= json.dumps(sobre, indent=2, sort_keys=True, ensure_ascii=False)
digest  := sha256(canónico.encode("utf-8")).hexdigest()
```

Propiedades que impone la definición, y por qué:

| propiedad | causa |
| --- | --- |
| **independiente de LF/CRLF** | la identidad se calcula sobre el documento **parseado**; los bytes del fichero no entran en el cálculo |
| **independiente de indentación, orden de claves y espacios** | `sort_keys=True` y una indentación fija |
| **reproducible entre ejecuciones** | sin tiempo, sin rutas absolutas, sin estado del proceso; `ensure_ascii=False` evita que la configuración regional cambie el resultado |
| **sensible a cualquier cambio semántico** | todo el documento entra salvo `_generated_by` |
| **versionada** | el identificador del contrato entra en el hash: cambiar el dominio o la canonicalización obliga a un identificador nuevo, y un consumidor que no lo conozca debe **rechazar** el pin, no reinterpretarlo |

Requisitos de admisión del sujeto: debe ser un objeto JSON, con
`_schema_version == "strategy-admission-ledger-v1"`. Un documento que no los cumple no
tiene identidad bajo este contrato y el consumidor **falla cerrado** (`None`, nunca un
digest calculado sobre algo distinto).

---

## 4. Dónde se implementa (y por qué tres veces)

| implementación | papel | importa al otro |
| --- | --- | --- |
| `scripts/cost_barrier_explorer.py` → `ledger_state_sha256()` | **productor** del pin que se publica en `sources[]` | no importa el gate |
| `scripts/cost_barrier_gate.py` → `ledger_state_digest()` | **verificador** del pin, independiente del productor | no importa el explorer |
| `scripts/wp_eco004_verify.py` → `ledger_state_from_contract()` | verificación independiente del WP | no importa ninguno de los dos |

La duplicación es deliberada y sigue la doctrina ya establecida en este lane («un gate que
importara la convención del productor no podría notar que la convención cambia»). El test
[`tests/unit/research/test_ledger_identity_contract.py`](../../../../tests/unit/research/test_ledger_identity_contract.py)
comprueba que las tres coinciden sobre el ledger commiteado y sobre variantes CRLF,
manipuladas y ausentes: la duplicación no puede divergir en silencio.

---

## 5. Publicación del pin

`sources[]` del explorer gana dos campos sólo donde aplica:

```json
{
  "path": "config/strategy_admission.json",
  "role": "tracked admission ledger: the only source of 'may this run PAPER?'",
  "exists": true,
  "tracked": true,
  "sha256": "…",              // identidad física (bytes)
  "state_sha256": "…",        // identidad semántica (este contrato)
  "state_contract": "strategy-admission-ledger-identity-v1"
}
```

`sources` es una clave volátil del explorer (`VOLATILE_KEYS`), así que añadir estos campos
**no cambia** el `payload_sha256`: la recertificación que los introduce sigue reproduciendo
la misma identidad económica.

## 6. Cómo decide el gate

Para una entrada con `state_sha256`:

```
EXACT_STATE  ⟺  state_sha256 == recalculo(bajo el contrato declarado)
                y  bytes == pin de bytes  ó  bytes == render LF/CRLF del pin
DRIFT        en cualquier otro caso
```

Es **más estricto** que juzgar sólo por estado: un pin de bytes que apunta a otro
artefacto (mismo hash válido, fichero equivocado) sigue siendo deriva, y una edición de
`_generated_by` también, porque el pin de bytes deja de coincidir. La tolerancia se limita
a la representación (LF/CRLF), que es exactamente el defecto que este contrato elimina.

Un `state_contract` declarado que el gate no implementa es un **defecto**
(`INTEGRITY_FAILURE`), no un aviso: aceptar un contrato desconocido equivaldría a aceptar
cualquier cosa que el productor decida llamar estado.

---

## 7. Fuera de alcance

- No es una firma. La autoridad es el commit que lo porta.
- No comprueba que los `_sources[].sha256` coincidan con los ficheros que nombran: eso lo
  hace `tests/unit/research/test_strategy_admission_ledger.py`, que es donde corresponde
  (el ledger no puede verificar sus propias dependencias desde dentro de su propio hash).
- No autoriza PAPER, promoción ni trading: `admitted_for_paper` sigue siendo `false` para
  las 24 entradas, y la certificación de la que forma parte no autoriza nada.

---

## 8. Versionado

- Cambiar `PROVENANCE_KEYS`, el dominio o la canonicalización ⇒ **identificador nuevo**
  (`…-v2`) y recertificación del bundle.
- El identificador viaja en el pin (`state_contract`) y dentro del hash (envelope), de modo
  que un pin antiguo no puede leerse bajo reglas nuevas por accidente.
- Un consumidor que encuentre un identificador que no implementa debe fallar cerrado.
