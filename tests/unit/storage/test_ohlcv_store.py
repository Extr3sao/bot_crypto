"""Tests for ``OHLCVStore`` + ``_parse_sqlite_url``.

Estrategia: ``tmp_path`` (pytest fixture) crea directorios temporales
reales y SQLite files reales. WAL puede no activarse en tmpfs en
algunos OS; el test acepta ``wal`` o ``memory`` como modo valido.

Convencion: cada test usa ``with OHLCVStore(...) as store:`` para
pine contractualmente el context manager protocol anadido en round-1
review (TSK-102). Esto evita connection leaks en callers que olviden
``close()``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from trading_bot.market_data.types import OHLCV
from trading_bot.storage.ohlcv_store import (
    CURRENT_SCHEMA_VERSION,
    OHLCVStore,
    _is_absolute_path,
    _parse_sqlite_url,
)


def _make_ohlcv(symbol: str, ts: int, close: float = 100.0) -> OHLCV:
    return OHLCV(
        symbol=symbol,
        timestamp=ts,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=10.0,
    )


# ---------------------------------------------------------------------------
# _parse_sqlite_url
# ---------------------------------------------------------------------------
def test_parse_relative_url_returns_relative_path() -> None:
    p = _parse_sqlite_url("sqlite:///data/storage/bot.db")
    assert p == Path("data/storage/bot.db")
    # cross-platform via helper: ``Path.is_absolute()`` retorna False en
    # Windows para rutas POSIX-like sin drive letter; _is_absolute_path
    # cierra esa brecha.
    assert not _is_absolute_path(p.as_posix())


def test_parse_absolute_url_returns_absolute_path() -> None:
    p = _parse_sqlite_url("sqlite:////var/data/bot.db")
    assert p == Path("/var/data/bot.db")
    # cross-platform check via helper: ``Path.is_absolute()`` retorna False
    # en Windows para rutas tipo ``/foo`` (sin drive letter). El caller
    # que pasa ``sqlite:////var/...`` SIEMPRE espera ruta absoluta en el
    # host destino; ver docstring de ``_is_absolute_path``.
    assert _is_absolute_path(p.as_posix())


def test_parse_unsupported_scheme_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="TSK-102 solo soporta"):
        _parse_sqlite_url("postgresql://localhost:5432/db")


# ---------------------------------------------------------------------------
# _is_absolute_path (cross-platform)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "path_str, expected",
    [
        # POSIX root / Windows rooted-at-current-drive.
        ("/var/data/bot.db", True),
        ("/data/storage/bot.db", True),
        # Windows root.
        ("\\var\\data\\bot.db", True),
        # Windows drive letter.
        ("C:/data/bot.db", True),
        ("c:\\data\\bot.db", True),
        ("D:", True),
        # UNC root.
        ("\\\\server\\share", True),
        # Relative paths.
        ("data/storage/bot.db", False),
        ("./data/bot.db", False),
        ("../data/bot.db", False),
        ("bot.db", False),
        ("", False),
    ],
)
def test_is_absolute_path_cross_platform(
    path_str: str, expected: bool,
) -> None:
    """Pinea la heuristica cross-platform de ``_is_absolute_path``.

    Si esto cambia, revisar contratos cross-platform (CI Windows, Mac
    dev box, Linux prod) — el parser no enrutara paths absolutos en
    hosts donde el helper retorne False.
    """
    assert _is_absolute_path(path_str) is expected


# ---------------------------------------------------------------------------
# OHLCVStore.__init__ + context manager
# ---------------------------------------------------------------------------
def test_init_creates_db_file_and_parent_dirs(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path}/subdir/bot.db"
    with OHLCVStore(url) as store:
        assert store.db_path == tmp_path / "subdir" / "bot.db"
        assert store.db_path.exists()
        assert store.db_path.parent.is_dir()


def test_init_migration_is_idempotent_across_reinits(tmp_path: Path) -> None:
    """Re-init sobre la misma DB no rompe ni downgrade."""
    url = f"sqlite:///{tmp_path}/bot.db"
    # Primera inicializacion: crea v1.
    with OHLCVStore(url):
        pass
    # Segunda inicializacion: lee v1 existente, no aplica migraciones.
    with OHLCVStore(url) as store:
        cur = store._conn.execute("PRAGMA user_version")
        assert cur.fetchone()[0] == CURRENT_SCHEMA_VERSION


def test_init_sets_wal_journal_mode(tmp_path: Path) -> None:
    """PRAGMA journal_mode activado (algun OS reporta ``memory`` en tmpfs)."""
    url = f"sqlite:///{tmp_path}/bot.db"
    with OHLCVStore(url) as store:
        cur = store._conn.execute("PRAGMA journal_mode")
        result = cur.fetchone()[0]
        assert result in ("wal", "memory")


def test_context_manager_closes_connection(tmp_path: Path) -> None:
    """F2 (round-1 review): pine contractualmente que ``__exit__``
    cierra la sqlite3.Connection. Sin esto, el connection leak seria
    invisible en tests y apareceria solo bajo carga (scheduler TSK-104+).
    """
    url = f"sqlite:///{tmp_path}/bot.db"
    outer_store = OHLCVStore(url)
    conn = outer_store._conn
    with outer_store as store:
        assert store is outer_store
        # Verificamos que la conexion sea usable dentro del with.
        cur = conn.execute("PRAGMA user_version")
        assert cur.fetchone()[0] == CURRENT_SCHEMA_VERSION
    # Tras __exit__, intentar usar la conexion cerrada debe fallar.
    # sqlite3.Connection.close() deja la conexion en estado 'closed';
    # ejecutar cualquier SQL lanza ``sqlite3.ProgrammingError``.
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


# ---------------------------------------------------------------------------
# upsert_ohlcv + get_ohlcv
# ---------------------------------------------------------------------------
def test_upsert_empty_list_is_noop_returns_zero(tmp_path: Path) -> None:
    with OHLCVStore(f"sqlite:///{tmp_path}/bot.db") as store:
        assert store.upsert_ohlcv([]) == 0


def test_upsert_then_get_round_trips_data(tmp_path: Path) -> None:
    with OHLCVStore(f"sqlite:///{tmp_path}/bot.db") as store:
        store.upsert_ohlcv([
            _make_ohlcv("BTC/USDT", 1672531200000, 100.0),
            _make_ohlcv("BTC/USDT", 1672534800000, 200.0),
        ])
        rows = store.get_ohlcv("BTC/USDT", limit=10)
        assert len(rows) == 2
        # get_ohlcv devuelve DESC; la primera fila debe ser ts mayor.
        assert rows[0].timestamp == 1672534800000
        assert rows[0].close == 200.0
        assert rows[1].timestamp == 1672531200000


def test_upsert_same_key_twice_does_not_duplicate(tmp_path: Path) -> None:
    """Idempotencia pineada via PK composta + ON CONFLICT DO UPDATE."""
    with OHLCVStore(f"sqlite:///{tmp_path}/bot.db") as store:
        for _ in range(2):
            store.upsert_ohlcv([_make_ohlcv("BTC/USDT", 1672531200000, 100.0)])
        rows = store.get_ohlcv("BTC/USDT", limit=10)
        assert len(rows) == 1


def test_upsert_same_key_with_updated_values_overwrites(tmp_path: Path) -> None:
    """Last-write-wins pineado (vela "en curso" actualiza su close)."""
    with OHLCVStore(f"sqlite:///{tmp_path}/bot.db") as store:
        store.upsert_ohlcv([_make_ohlcv("BTC/USDT", 1672531200000, 100.0)])
        store.upsert_ohlcv([_make_ohlcv("BTC/USDT", 1672531200000, 250.0)])
        rows = store.get_ohlcv("BTC/USDT", limit=10)
        assert len(rows) == 1
        assert rows[0].close == 250.0


def test_get_ohlcv_filters_by_symbol(tmp_path: Path) -> None:
    with OHLCVStore(f"sqlite:///{tmp_path}/bot.db") as store:
        store.upsert_ohlcv([
            _make_ohlcv("BTC/USDT", 1672531200000, 100.0),
            _make_ohlcv("ETH/USDT", 1672531200000, 200.0),
        ])
        btc = store.get_ohlcv("BTC/USDT", limit=10)
        eth = store.get_ohlcv("ETH/USDT", limit=10)
        assert len(btc) == 1
        assert btc[0].symbol == "BTC/USDT"
        assert len(eth) == 1
        assert eth[0].symbol == "ETH/USDT"


def test_get_ohlcv_empty_store_returns_empty_list(tmp_path: Path) -> None:
    with OHLCVStore(f"sqlite:///{tmp_path}/bot.db") as store:
        assert store.get_ohlcv("BTC/USDT", limit=10) == []


def test_get_ohlcv_limit_caps_results(tmp_path: Path) -> None:
    with OHLCVStore(f"sqlite:///{tmp_path}/bot.db") as store:
        store.upsert_ohlcv([
            _make_ohlcv("BTC/USDT", 1672531200000 + i * 1000)
            for i in range(50)
        ])
        rows = store.get_ohlcv("BTC/USDT", limit=10)
        assert len(rows) == 10


# ---------------------------------------------------------------------------
# Smoke test (cierre cobertura 89.x -> 90% via pytest --cov).
#
# Cubre el except block del hardening anadido en TSK-102 round-1 review:
# si un PRAGMA o ``_run_migrations`` levanta durante ``__init__``, la
# sqlite3.Connection se cierra ANTES de propagar la excepcion. Sin este
# cleanup, el caller veria un ``OHLCVStore`` con ``_conn`` a medio
# inicializar (silent resource leak que solo se manifiesta bajo carga,
# e.g. TSK-104+ scheduler con lectura concurrente).
# ---------------------------------------------------------------------------


def test_init_failure_closes_connection_and_reraises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Smoke (coverage gate): cuando un PRAGMA falla durante ``__init__``,
    el hardening del round-1 review (TSK-102) garantiza que:

      1. ``_conn.close()`` se invoca dentro del except block.
      2. La excepcion original se reraisa sin swap (no se re-empaqueta
         en un RuntimeError generico).

    Estrategia: stub ``sqlite3.connect`` con un ``MagicMock`` cuyo
    ``.execute(...)`` levanta ``sqlite3.DatabaseError`` en la primera
    llamada (PRAGMA ``journal_mode=WAL``). Verificar que ``close``
    fue llamado y que el error orignal se propaga al caller.
    """
    url = f"sqlite:///{tmp_path}/subdir/bot.db"
    fake_conn = MagicMock(spec=sqlite3.Connection)
    fake_conn.execute.side_effect = sqlite3.DatabaseError(
        "simulated WAL fail"
    )
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **kw: fake_conn)

    with pytest.raises(sqlite3.DatabaseError, match="simulated WAL fail"):
        OHLCVStore(url)

    # El except block debe llamar _conn.close() antes del reraise;
    # sin esto, una regresion dejaria la conexion abierta mientras
    # el caller recibe la excepcion (resource leak silencioso).
    assert fake_conn.close.called
