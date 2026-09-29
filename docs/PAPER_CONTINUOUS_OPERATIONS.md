# PAPER CONTROLS OPERATIONS — running the lab continuously

> Estado: operativo. Este documento describe cómo dejar TRADING AGENTIC PORTABLE
> corriendo en **PAPER** de forma continua, con el colector de microestructura
> forward y el laboratorio de estrategias en paralelo.
>
> **No hay ruta a LIVE.** Ningún hijo del supervisor tiene credenciales de
> ejecución; el único broker en el proceso PAPER es `PaperBroker`.

---

## 1. Un solo comando

```bash
uv run python scripts/start_paper_lab.py
```

o, sin `uv`:

```bash
.venv/Scripts/python.exe scripts/start_paper_lab.py
```

Esto arranca **cuatro** procesos bajo un supervisor portable (`§27`-`§31`):

| proceso | crítico | qué es | comando |
| --- | --- | --- | --- |
| `paper` | sí | runtime PAPER continuo | `scripts/autonomous_paper.py --continuous` |
| `collector` | sí | captura forward read-only | `scripts/forward_collector.py --mode run` |
| `retention` | no | compactación + lineage | `scripts/forward_retention.py --loop` |
| `strategy_lab` | no | pass read-only de research | `scripts/paper_lab_research.py --loop` |

`paper` y `collector` corren en **procesos separados**: el fallo de uno no puede
tumbar al otro (`§26`). El supervisor los reinicia de forma independiente con
backoff y, si uno entra en crash loop, lo marca `FAILED` y deja de reintentarlo
(`§29`). `retention` y `strategy_lab` son mantenimiento: si se rompen, el sistema
queda `DEGRADED`, no `FAILED` (`§16`).

### Opciones útiles

```bash
--duration-hours 2          # el laboratorio se detiene solo a las 2 h
--assets BTC,ETH,SOL        # universo PAPER
--timeframe 5m              # timeframe del runtime
--provider ccxt             # ccxt (datos reales) | fake (sin red)
--raw-hot-hours 2           # ventana caliente de RAW antes de compactar
--delete-when-free-below N  # 0 = compactar sin borrar nunca (por defecto)
--collector-max-bytes N     # guarda de disco del colector (última barrera)
--dry-run                   # imprime el plan y no arranca nada
```

Antes de arrancar en serio, revisa el plan:

```bash
uv run python scripts/start_paper_lab.py --dry-run
```

`LAB_PLAN.json` queda escrito en el directorio del run con exactamente la misma
información que se va a ejecutar.

---

## 2. Parar (un comando, o Ctrl-C)

Tres formas equivalentes; las tres vacían estado y finalizan manifiestos (`§51`):

```bash
# 1) Ctrl-C en la terminal del supervisor
# 2) un archivo STOP en el directorio del run
printf 'stop\n' > reports/paper-lab/<run-id>/STOP
# 3) el propio launcher
uv run python scripts/start_paper_lab.py --stop reports/paper-lab/<run-id>
```

Qué hace la parada, en orden:

1. el loop PAPER termina **el ciclo en curso** y persiste su estado;
2. el colector deja de ingerir, cierra el writer y sella los segmentos;
3. `retention` no vuelve a correr;
4. el supervisor hace `terminate()` a cada hijo y, si no responde, `kill()`;
5. se escriben `SYSTEM_HEARTBEAT.json`, `LAB_RUN_REPORT.{json,md}` y
   `SYSTEM_DAILY_REPORT.{json,md}`.

---

## 3. Reiniciar y recuperar

```bash
uv run python scripts/start_paper_lab.py --run-id <el-mismo-run-id>
```

* **PAPER**: `PaperStateStore` + `StartupReconcilerV4` recargan el estado desde
  `paper_state.json`; las decisiones económicas ya emitidas no se duplican
  (`IdempotencyGuard`).
* **Colector**: `state/<run-id>.json` guarda `last_agg_trade_id`, `gap_seq` y
  contadores; un reinicio con el mismo `--run-id` continúa sin cortar la cadena
  de ids. Los segmentos a medio escribir quedan marcados como *partial tail* y el
  manifiesto los declara.
* **Retention**: es idempotente; un corte entre el agregado y el marcador se
  repara en la siguiente pasada.

---

## 4. Inspección

```bash
# ¿está sano el conjunto?
cat reports/paper-lab/<run-id>/SYSTEM_HEARTBEAT.json

# ¿qué hizo PAPER?
cat reports/paper-lab/<run-id>/../autonomous-paper/<run-id>/PAPER_DAILY_REPORT.md
tail -20 reports/paper-lab/<run-id>/../autonomous-paper/<run-id>/heartbeat.jsonl

# ¿qué capturó el colector?
cat reports/microstructure-forward-lab/state/<run-id>.json
cat reports/microstructure-forward-lab/manifest/<run-id>.json

# ¿qué dice el laboratorio de estrategias?
cat reports/microstructure-forward-lab/STRATEGY_LAB_REPORT.json

# ¿qué haría retention? (no toca nada)
uv run python scripts/forward_retention.py --root reports/microstructure-forward-lab \
    --run-id <run-id> --raw-hot-hours 2 --dry-run

# informe combinado
uv run python scripts/system_daily_report.py --lab-run-dir reports/paper-lab/<run-id>
```

`SYSTEM_HEARTBEAT.json` incluye: estado del sistema (`HEALTHY`/`DEGRADED`/`FAILED`),
estado y PID de cada proceso, número de reinicios, disco libre, memoria, y el
contenido del heartbeat de cada hijo (último ciclo PAPER, eventos/gaps/reconexiones
del colector).

---

## 5. Dónde vive cada cosa

```text
RAW HOT            reports/microstructure-forward-lab/segments/     (bounded by --raw-hot-hours)
AGGREGATED         reports/microstructure-forward-lab/aggregated/   (1m/5m/15m/30m, indefinido)
LINEAGE            reports/microstructure-forward-lab/lineage/      (RAW -> AGGREGATE, indefinido)
MANIFESTS          reports/microstructure-forward-lab/manifest/     (indefinido)
STATE              reports/microstructure-forward-lab/state/        (reanudación del colector)
PAPER RUN          reports/autonomous-paper/<run-id>/               (traces, outcomes, informes)
SUPERVISOR RUN     reports/paper-lab/<run-id>/                      (plan, logs, heartbeat, informes)
BROKER STATE       reports/paper-lab/<run-id>/paper_state.json
ADMISSION LEDGER   config/strategy_admission.json                   (autoridad de admisión)
```

Nada en `reports/` se borra nunca por política de retención (`§6`): sólo los
segmentos RAW, y sólo tras comprobar que el agregado existe, re-hashea al hash
que la línea de linaje registró, y que la ventana fue sellada.

---

## 6. Estado esperado de las estrategias

```text
REJECTED            no puede rutear
RESEARCH_REQUIRED   no puede rutear
PAPER_CANDIDATE     elegible para promoción
PAPER_ACTIVE        única que participa en PAPER
PAPER_RETIRED       no abre posiciones nuevas
```

Hoy el ledger no admite ninguna estrategia, así que el resultado correcto de un
run PAPER es **muchas decisiones `NO_TRADE`, 0 trades de sombra y 0 trades PAPER**.
Eso es un PASS, no un fallo: no se activa ninguna estrategia históricamente
rechazada para fabricar actividad.

---

## 7. Guarda de disco

El colector mantiene `--max-total-bytes` como **última** barrera: si se alcanza,
escribe el evento `DISK_LIMIT_REACHED`, sella y para **limpiamente** (manifiesto
completo, sin pérdida silenciosa). Antes de llegar ahí, el sistema intenta
rotación → compresión → compactación/retención. El borrado de RAW es *demand
driven*: sólo con `--delete-when-free-below` y disco por debajo de ese umbral.
