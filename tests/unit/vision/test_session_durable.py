"""WP-PAPER-RESUME-001 — la sesión prospective, reiniciada sobre el mismo libro.

El test unitario del lane demuestra que el libro se restaura. Éste demuestra lo que el
usuario ve: un segundo `ProspectiveSession` sobre el mismo `out_dir` **no empieza plano**.
Lo que se fija:

1. la sesión 1 escribe `STATE/BOOK.json` y cierra su cerrojo;
2. la sesión 2 arranca, encuentra el libro, lo reconcilia y lo dice en `SESSION_START`, en
   cada `CYCLE` y en la cadena de evidencia (que continúa, no se reinicia);
3. `session_index` avanza, no se repite;
4. un libro ilegible **no** se convierte en una sesión limpia: el primer ciclo sale
   `RECOVERY_BLOCKED`, sin relleno y sin decisión.

El veneno se sirve con un veneno sintético y un reloj falso: esto es un test de mecanismo,
no una validación de mercado, y así se declara.
"""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

from trading_bot.config.settings import load_settings
from trading_bot.market_data.minute_collector import (
    MINUTE_MS,
    KlinePage,
    MinuteCollector,
)
from trading_bot.vision.durable import LaneBookStore
from trading_bot.vision.ledger import read_entries, verify_chain
from trading_bot.vision.prospective import ProspectiveConfig, ProspectiveSession
from trading_bot.vision.settings import load_vision_config

REPO = Path(__file__).resolve().parents[3]
T0 = 1_700_000_000_000 - (1_700_000_000_000 % (5 * MINUTE_MS))
SYMBOLS = ("BTCUSDT", "ETHUSDT")


class FakeClock:
    def __init__(self, now_ms: int) -> None:
        self.now = int(now_ms)

    def __call__(self) -> int:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += int(float(seconds) * 1000)


class SyntheticVenue:
    """Un venue con reloj: responde cualquier rango de minutos, sin red."""

    name = "synthetic_venue"

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.first_open_ms = T0

    def price(self, symbol: str, open_ms: int) -> float:
        index = (open_ms - self.first_open_ms) // MINUTE_MS
        base = 30_000.0 if symbol == "BTCUSDT" else 2_000.0
        drift = 25.0 if symbol == "BTCUSDT" else 2.0
        return base + drift * math.sin(index / 9.0) + 3.0 * math.sin(index / 2.3)

    def last_closed_open(self) -> int:
        return (self.clock() // MINUTE_MS) * MINUTE_MS - MINUTE_MS

    def server_time(self) -> int:
        return self.clock()

    def fetch(
        self,
        symbol: str,
        *,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 500,
    ) -> KlinePage:
        last = self.last_closed_open()
        stamps = list(range(self.first_open_ms, last + 1, MINUTE_MS))
        if start_ms is not None:
            stamps = [stamp for stamp in stamps if stamp >= int(start_ms)]
            stamps = stamps[: max(1, limit)]
        else:
            stamps = stamps[-max(1, limit) :]
        rows = []
        for stamp in stamps:
            price = self.price(symbol, stamp)
            rows.append(
                (stamp, price, price * 1.0008, price * 0.9992, price * 1.0001, 5.0)
            )
        return KlinePage(
            symbol=symbol,
            rows=tuple(rows),
            server_time_ms=self.clock(),
            received_at_ms=self.clock(),
        )


def _session(
    out: Path,
    clock: FakeClock,
    *,
    durable: bool,
    max_cycles: int = 2,
    start_ms: int | None = None,
) -> ProspectiveSession:
    clock.now = int(start_ms if start_ms is not None else T0 + 300 * MINUTE_MS)
    out.mkdir(parents=True, exist_ok=True)
    collector = MinuteCollector(
        source=SyntheticVenue(clock),
        root=out / "market-1m",
        symbols=SYMBOLS,
        local_clock=clock,
        settle_ms=0,
    ).open()
    vision = load_vision_config(env={})
    vision = replace(
        vision,
        lane=replace(vision.lane, timeframe="5m", window_bars=20, decision_every_bars=1),
    )
    settings = load_settings(config_dir=REPO / "config", env_file=None)
    return ProspectiveSession(
        config=ProspectiveConfig(
            symbols=SYMBOLS,
            timeframe="5m",
            window_bars=20,
            decision_every_bars=1,
            duration_s=1_500,
            poll_interval_s=15.0,
            settle_ms=0,
            latency_ms=30_000,
            warmup_minutes=120,
            max_cycles=max_cycles,
            durable=durable,
        ),
        out_dir=out,
        vision_config=vision,
        risk_policy=settings.risk,
        root=REPO,
        collector=collector,
        clock=clock,
        sleeper=clock.sleep,
    )


def _rows(out: Path) -> list[dict]:
    return [row["entry"] for row in read_entries(out / "STREAM.jsonl")]


def test_a_restarted_session_resumes_the_book_instead_of_starting_flat(tmp_path: Path) -> None:
    out = tmp_path / "session"
    clock = FakeClock(T0 + 300 * MINUTE_MS)
    first = _session(out, clock, durable=True, max_cycles=2).run()

    store = LaneBookStore(out / "STATE")
    book = store.load()
    assert book is not None, "la sesión durable tiene que dejar un libro en disco"
    assert book.barrier_ms is not None
    assert book.body["session_index"] == 1
    assert book.body["session_id"] == "session-001"
    assert first["cycles_executed"] >= 1

    #: La segunda sesión arranca 40 minutos más tarde sobre el *mismo* directorio.
    second = _session(
        out, clock, durable=True, max_cycles=2, start_ms=clock.now + 40 * MINUTE_MS
    ).run()

    assert second["cycles_executed"] >= 1
    book2 = store.load()
    assert book2 is not None
    assert book2.body["session_index"] == 2
    assert book2.body["session_ids"][:2] == ["session-001", "session-002"]
    assert book2.barrier_ms is not None and int(book2.barrier_ms) > int(book.barrier_ms)

    rows = _rows(out)
    starts = [row for row in rows if row["kind"] == "SESSION_START"]
    assert len(starts) == 2
    assert starts[0]["durable"]["recovered"] is False
    assert starts[1]["durable"]["recovered"] is True
    assert starts[1]["durable"]["barrier_ms"] == book.barrier_ms
    #: La limitación inferior de decisión de la sesión 2 es la barrera, no su arranque:
    #: las velas que el proceso anterior no llegó a ver tienen que poder decidirse.
    assert starts[1]["durable"]["decision_from_ms"] is None

    #: La evidencia es una sola cadena: el reinicio se añade, no se reescribe.
    chain = verify_chain(out / "STREAM.jsonl")
    assert chain["ok"] is True, chain
    assert chain["kinds"].get("SESSION_START") == 2
    cycles = [row for row in rows if row["kind"] == "CYCLE"]
    assert all(row["status"] == "EXECUTED" for row in cycles)
    for row in cycles:
        assert row["durable"] is not None
        assert row["durable"]["barrier_ms"] is not None
        assert row["ledger"]["prefix"]["skipped"] == "DURABLE_BOOK"


def test_the_second_session_does_not_reproduce_the_first_one_s_fills(tmp_path: Path) -> None:
    out = tmp_path / "session"
    clock = FakeClock(T0 + 300 * MINUTE_MS)
    _session(out, clock, durable=True, max_cycles=1).run()
    book = LaneBookStore(out / "STATE").load()
    assert book is not None
    fills_before = int(book.body["broker"]["fills_opened"])
    closed_before = len(book.closed_trades)

    _session(out, clock, durable=True, max_cycles=1, start_ms=clock.now + 20 * MINUTE_MS).run()

    book2 = LaneBookStore(out / "STATE").load()
    assert book2 is not None
    #: Ninguna vela se vuelve a procesar: no hay rellenos "repetidos", y los que hay son
    #: nuevos (o ninguno), nunca los mismos dos veces.
    assert int(book2.body["broker"]["fills_opened"]) >= fills_before
    assert len(book2.closed_trades) >= closed_before
    assert [row["position_id"] for row in book2.closed_trades] == list(
        dict.fromkeys(row["position_id"] for row in book2.closed_trades)
    )
    positions = [row["position_id"] for row in book2.open_positions]
    assert len(positions) == len(set(positions))


def test_a_non_durable_session_is_unchanged(tmp_path: Path) -> None:
    out = tmp_path / "session"
    summary = _session(out, FakeClock(T0 + 300 * MINUTE_MS), durable=False, max_cycles=1).run()

    assert summary["cycles_executed"] == 1
    assert not (out / "STATE").exists()
    rows = _rows(out)
    assert all("durable" not in row for row in rows if row["kind"] == "SESSION_START")


def test_a_corrupt_book_blocks_the_session_instead_of_emptying_it(tmp_path: Path) -> None:
    out = tmp_path / "session"
    clock = FakeClock(T0 + 300 * MINUTE_MS)
    _session(out, clock, durable=True, max_cycles=1).run()
    store = LaneBookStore(out / "STATE")
    raw = store.path.read_bytes()
    store.path.write_bytes(raw[: len(raw) // 2])

    summary = _session(
        out, clock, durable=True, max_cycles=1, start_ms=clock.now + 20 * MINUTE_MS
    ).run()

    assert summary["cycles_executed"] == 0  # un ciclo bloqueado no es un ciclo ejecutado
    rows = _rows(out)
    blocked = [row for row in rows if row["kind"] == "CYCLE"][-1]
    assert blocked["status"] == "RECOVERY_BLOCKED"
    assert blocked["reason"] == "CORRUPT_BOOK"
    assert blocked["fills"] == 0
    assert blocked["live_orders"] == 0
    #: Se conserva el original y no se escribe un libro nuevo encima del que no se entiende.
    assert list((out / "STATE").glob("BOOK.corrupt.*.json"))
    sessions = [row for row in rows if row["kind"] == "SESSION_START"]
    assert sessions[-1]["durable"]["blocked"]["code"] == "CORRUPT_BOOK"
    assert json.dumps(sessions[-1]["durable"]["blocked"]).find("corrupt") >= 0
