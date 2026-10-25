# Conciliación — paquete `EXP-003N_preflight_blocked_20261020` contra este repositorio

**Fecha:** 2026-10-21 · **Checkout:** este (`bot freebuff`) · **Rama:** `agent/ai-bots/RFC-TAP-AI-BOTS-003`
**HEAD al abrir:** `cd3fc31` · **HEAD al cerrar:** `277d1df` (otro agente commiteó `6b0dac1` y `277d1df` durante esta conciliación)
**Objeto:** decidir si el paquete recibido describe trabajo pendiente y qué parte de él es adoptable.
No crea un experimento, no escribe datos y no autoriza ninguna ejecución económica.

---

## 0. Qué se recibió, y comprobado contra qué

Cuatro ficheros sueltos más el zip que los contiene. Digests `sha256` calculados aquí:

| Fichero | sha256 |
| --- | --- |
| `EXP-003N_preflight_blocked_20261020.zip` | `64b35db12827138d662d8a90c8fc6f90f0c4550b97d552d6a8ba7286771b767f` |
| `FINAL_REPORT.md` | `8ddad44eefc11ae5e91caba13690f782232f4d4f5bb88d5dc4ee69d0cf5c1a8c` |
| `RUN_REPORT.json` | `83c53deed6397678d837bc214fccd29b0f69e7c6b1c84cbaecd159d967289c83` |
| `RUN_REPORT.md` | `e0c7dfd5200daf4e155e1b44e16a11cba68c48c20ca9ae79b95dcf2d1508bfaf` |

Los tres coinciden con el `evidence/SHA256SUMS.txt` del paquete, y `evidence/SHA256_CHECK.log` termina en
`OK` para sus 17 ficheros. **El paquete es internamente consistente.** Lo que se discute no es su integridad
sino su premisa.

El zip trae además lo que los cuatro ficheros sueltos sólo citaban: `scripts/exp003n_preflight.py`
(313 líneas), `tests/test_exp003n_preflight.py` y los tres `config/*.json`. Se extrajo a un directorio
temporal, **fuera del repositorio**, y nada de él se ha copiado al árbol.

---

## 1. Los cinco bloqueos, uno por uno

El paquete declara `B01…B05` y un gate `BLOCKED_BY_AUTHORITATIVE_RUNTIME_AND_DATA`.

| Declarado | Estado real | Evidencia |
| --- | --- | --- |
| **B01** sin checkout autoritativo ni HEAD | **Falso.** Es este repositorio: `origin = github.com/Extr3sao/bot_crypto.git`. El sandbox buscó `Extr3sao/Bot-Trading`, que no es el remoto de este proyecto | `git remote -v`; `RUN_REPORT.md` §1 del paquete |
| **B02** sin datos de N con SHA-256 ni procedencia | **Falso.** Los tres ficheros de 1m existen en disco y sus digests coinciden aquí, uno a uno, con los congelados en `DESIGN.json`; los bytes quedan fuera de Git por regenerables, certificados por digest y manifiesto | `sha256sum reports/ai-bots/EXP-003K-CANDIDATE-001/dataset/*.jsonl.gz` → `7fbdfefa…`, `cf04dc37…`, `33342aac…` |
| **B03** sin prereg congelado | **Cierto para el borrador, falso para el experimento.** El borrador está en `DRAFT_UNFROZEN` con **43** valores `null` y `origin: reconstructed_from_prior_session_summary_not_runtime` | `config/preregistration.json` §`status` |
| **B04** sin inventario de ejecuciones N previas | **Falso.** Hay **1** ejecución, cerrada y publicada en `HEAD` | `reports/ai-bots/EXP-003N-GROSS-FIRST-DISCOVERY-001/` |
| **B05** sin ejecución ni verificador | **Falso.** Se ejecutó y se verificó con un programa separado del builder | `analysis/DECISION.json`, `analysis/VERIFICATION.json` |

Los cinco bloqueos describen un mundo en el que `EXP-003N` no ha ocurrido. Ha ocurrido, y terminó sin
candidato vivo:

- `counts`: **13 `REJECT`**, **10 `INSUFFICIENT_EVIDENCE`**, **1 `EXPERIMENT`**, **0 `ADVANCE`**.
- Holdout `2026-08-06 → 2026-08-20`: `status: CLOSED`; V4 confirma `0 rows at or after 2026-08-06T00:00:00Z`.
- V5: **6 692** retornos forward recalculados desde barras, **0** discrepancias.
- Verificador: **12/12** checks `PASS`, **10/10** controles negativos detectados.
- Procedencia declarada por sus autores: **retrospectivo con protocolo declarado**, no prospectivo
  (`design/PREREGISTRATION.md` §0).

---

## 2. La prueba decisiva: el gate del paquete rechaza su propio experimento

No hace falta argumentarlo. Se ejecutó el gate recibido, **sin modificar su código**, sobre una copia
temporal cuyo ledger de ejecuciones previas se rellenó con el resultado real del inventario
(`inventory_completed: true`, `exp003n_executions: 1`):

```
python scripts/exp003n_preflight.py --repo . --mode authorize
→ exit 2 · decision: BLOCKED · 109 errores
→ PRIOR_EXP003N_RUNS_FOUND_RETROSPECTIVE_ONLY
```

Completado el inventario honestamente, **la propia regla del paquete prohíbe crear `EXP-003N`**. Lo que el
sandbox presentó como «bloqueado por falta de checkout» es, en los hechos, un identificador gastado: el gate
acertó por el motivo equivocado.

Control de reproducibilidad: los 16 tests del paquete se re-ejecutaron aquí (Python 3.11.15) → **16/16 OK,
3.010 s**. El diagnóstico es reproducible; la premisa no.

---

## 3. Qué se adopta y qué no

**Se adopta, como mecanismo:** la forma del preflight fail-closed —digests reales de `raw` y `normalized`,
particiones sin solape dentro del embargo, **rechazo de un holdout ya inspeccionado**, `BUILDER != VERIFIER`,
`OFFLINE_ONLY`, ledger de ejecuciones previas obligatorio, prereg commiteado y ancestro del código—. Es más
estricto que `scripts/exp_003n_preregister.py --check`, que sólo compara digests de configs/dataset y exige
`holdout.status == "CLOSED"`. Merece portarse como guarda **parametrizada por identificador** para el próximo
experimento.

**No se adopta:** el `preregistration.json` como prereg de `EXP-003N`. Rellenar sus 43 `null` aquí sería
elegir candidato, splits y umbrales **después** de conocer el resultado — lo que el propio documento prohíbe.

**No se adopta:** el `prior_runs_ledger.json`. Sus cuatro entradas (`003J/003K/003L/003M`) están marcadas
`not_reverified` y quedan sustituidas por el inventario real, que incluye la quinta: `003N`.

**Coincidencia que sobrevive:** el borrador excluye `2026-08-06/2026-08-20` como holdout consumido. Es
exactamente la ventana que `EXP-003N` cerró. Ese dato era correcto y sigue siéndolo.

---

## 4. Un defecto que se observó y dejó de existir mientras se escribía esto

Primera medición, a `cd3fc31`: `SEAL.json` y `SHA256SUMS.txt` **no existían**, el comando de sello del
checkpoint no podía ejecutarse, y los ocho entregables narrativos (`FINAL_REPORT.md`, `RUN_REPORT.{md,json}`,
`INDEPENDENT_VERIFICATION.md`, `REJECTED_CANDIDATES.md`, `CANDIDATE_RANKING.md`, `STRATEGY_UNIVERSE.md`,
`ECONOMIC_SCREENING.csv`) estaban sin seguimiento, junto con `evidence/CLEAN_CHECKOUT_REPRODUCTION*`.

Segunda medición, a `277d1df`: el otro agente commiteó `6b0dac1` («Prove the gross-first numbers survive a
checkout, then seal them»). Ahora hay **31** ficheros versionados, el sello existe y **se verifica**:

```
29 filas en SHA256SUMS.txt · sha256sum -c → exit 0 (todas OK)
SEAL.json → design_sha256 a0776fa3fbe6d2e1… == el que V3 compara
```

Se registra como observación cerrada, no como defecto abierto. **No se tocó** ese árbol: los commits y la
publicación son del agente que los hizo.

---

## 5. Reanudación verificable

Ninguna de estas órdenes modifica el repositorio.

```bash
# 1. El paquete recibido: sello interno y tests
unzip -o -q "$HOME/Downloads/EXP-003N_preflight_blocked_20261020.zip" -d "$HOME/tmp-003n"
(cd "$HOME/tmp-003n/EXP-003N" && sha256sum -c evidence/SHA256SUMS.txt)
(cd "$HOME/tmp-003n/EXP-003N" && python -m unittest discover -s tests -v)          # 16/16

# 2. El experimento real, en este árbol
cd "$(git rev-parse --show-toplevel)"
(cd reports/ai-bots/EXP-003N-GROSS-FIRST-DISCOVERY-001 && sha256sum -c SHA256SUMS.txt)  # 29/29
python -c "import json;d=json.load(open('reports/ai-bots/EXP-003N-GROSS-FIRST-DISCOVERY-001/analysis/DECISION.json'));print(d['counts'],d['holdout_opened'])"
git ls-tree -r --name-only HEAD | grep -c EXP-003N                                     # 31
```

---

## 6. Lo que este documento no hace

- **No crea `EXP-003N`.** El identificador está gastado y su gate lo rechaza (§2).
- **No rellena el borrador.** Un prereg cuyos `null` se rellenan a posteriori no es un prereg.
- **No ejecuta economía.** `economic_executions: 0`; lo único que corrió fue el preflight, en copia temporal,
  y sus 16 tests.
- **No re-ejecuta el verificador de N** (`scripts/exp_003n_verify.py`): se leyó su salida publicada
  (12/12 `PASS`, 10/10 controles), no se reprodujo. `INDEPENDENT_VERIFIER = PROGRAM_NOT_PERSON` sigue siendo
  cierto.
- **No juzga si el veredicto de N es correcto**, sólo que existe, que está cerrado y que no es el trabajo que
  el paquete recibido describe como pendiente.

**Consecuencia para el siguiente experimento:** no puede llamarse `N`, no puede usar `2026-08-06 → 2026-08-20`
y no puede reutilizar las 24 celdas ya cribadas sobre BTC/ETH/SOL con los mismos 46 días. Lo que sí hereda es
la guarda del §3 y la disciplina de publicar sello y entregables **dentro** de Git.
