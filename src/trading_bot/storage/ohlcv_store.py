"""SQLite-backed OHLCV store con ``PRAGMA user_version`` schema versioning.

Disenado para persistencia cruda de velas OHLCV (TSK-102). NO cubre
``signals``/``orders``/``fills``/``risk_decisions``; esos vienen bajo
TSK-100 (SQLAlchemy + Alembic, Pri 8 sprint-002).

Schema versioning:
- ``CURRENT_SCHEMA_VERSION`` pin a 1 (v1 inicial).
- ``_run_migrations``: lee ``PRAGMA user_version`` y aplica deltas
  incrementales. Idempotente: si ya esta en v1, no hace nada.
- Sin Alembic: TSK-100 lo introducira con SQLAlchemy.

Upsert strategy:
- ``INSERT ... ON CONFLICT (symbol, timestamp) DO UPDATE`` last-write-wins.
  Vela reciente puede recibir correcciones tardias (vela "en curso").
  Vela historica NO deberia cambiar; si lo hace, pines via
  ``test_upsert_same_key_with_updated_values_overwrites``.

Riesgos pineados (ver retrieval-log 2026-07-04 03:00):
- (R1) Concurrencia SQLite: ``PRAGMA journal_mode=WAL`` activado por
  defecto para evitar ``database is locked`` cuando TSK-104+
  introduzca lectura concurrente desde scheduler.
- (R2) Path resolution: rutas relativas se resuelven respecto al CWD
  al instanciar. El bot arranca con CWD = repo root.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

import structlog

from trading_bot.market_data.types import OHLCV

# Schema version actual. Si esto sube a 2, anadir `_SCHEMA_V2_DDL` y
# extender el `if version < 2:` branch de `_run_migrations()`.
CURRENT_SCHEMA_VERSION: int = 1

# DDL v1: tabla OHLCV + index en (symbol, timestamp DESC) para queries
# "ultimas N velas de BTC/USDT". PRIMARY KEY compuesta aporta la
# idempotencia del upsert via ON CONFLICT.
_SCHEMA_V1_DDL: tuple[str, ...] = (
    """
    CREATE TABLE ohlcv (
        symbol TEXT NOT NULL,
        timestamp INTEGER NOT NULL,
        open REAL NOT NULL,
        high REAL NOT NULL,
        low REAL NOT NULL,
        close REAL NOT NULL,
        volume REAL NOT NULL,
        PRIMARY KEY (symbol, timestamp)
    )
    """,
    "CREATE INDEX idx_ohlcv_symbol_ts ON ohlcv (symbol, timestamp DESC)",
)


class OHLCVStore:
    """Persistencia cruda en SQLite para velas OHLCV."""

    def __init__(self, database_url: str) -> None:
        self._log = structlog.get_logger(self.__class__.__module__)
        db_path = _parse_sqlite_url(database_url)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        # WAL: previene "database is locked" en lecturas concurrentes
        # futuras (TSK-104+ scheduler). isolation_level=None para
        # manejar transacciones explicitas via BEGIN/COMMIT si necesario.
        self._conn = sqlite3.connect(str(db_path), isolation_level=None)
        # Hardening (closing review F1): si un PRAGMA o _run_migrations
        # levanta, cerramos la conexion antes de propagar la excepcion.
        # Sin esto, el caller recibe un OHLCVStore con _conn a medio
        # inicializar y cualquier uso posterior falla silenciosamente.
        # sqlite3.Connection.close() es idempotente (CPython 3.11+), asi
        # que el __exit__ posterior (vía ``with OHLCVStore(...) as
        # store:``) sigue siendo seguro aunque ya este cerradas.
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._run_migrations()
        except Exception:
            self._conn.close()
            raise

    @property
    def db_path(self) -> Path:
        return self._db_path

    def upsert_ohlcv(self, ohlcv_list: Iterable[OHLCV]) -> int:
        """Inserta velas nuevas / actualiza existentes (last-write-wins)."""
        rows = [
            (o.symbol, o.timestamp, o.open, o.high, o.low, o.close, o.volume) for o in ohlcv_list
        ]
        if not rows:
            return 0
        sql = (
            "INSERT INTO ohlcv (symbol, timestamp, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (symbol, timestamp) DO UPDATE SET "
            "open=excluded.open, high=excluded.high, low=excluded.low, "
            "close=excluded.close, volume=excluded.volume"
        )
        cur = self._conn.executemany(sql, rows)
        return cur.rowcount

    def get_ohlcv(self, symbol: str, limit: int = 100) -> list[OHLCV]:
        """Devuelve las ultimas N velas de un simbolo en orden DESC.

        P1 round-2 (TSK-102): selecciona ``symbol`` ademas del resto de
        columnas y reconstruye OHLCV con ``symbol`` para que el
        round-trip connector -> fetcher -> store preserva el binding
        exchange sin perdida de metadata. Sin esto, OHLCV.symbol seria
        missing a pesar de que el SQL DDL pineaba PK compuesta
        ``(symbol, timestamp)``.
        """
        cur = self._conn.execute(
            "SELECT symbol, timestamp, open, high, low, close, volume "
            "FROM ohlcv WHERE symbol = ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (symbol, limit),
        )
        return [
            OHLCV(
                symbol=str(r[0]),
                timestamp=int(r[1]),
                open=float(r[2]),
                high=float(r[3]),
                low=float(r[4]),
                close=float(r[5]),
                volume=float(r[6]),
            )
            for r in cur.fetchall()
        ]

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------------
    # Context manager protocol (F2 round-1 review)
    # ------------------------------------------------------------------------
    # Sin esto, callers que olviden ``close()`` leak sqlite3.Connection.
    # TSK-104+ (scheduler) y backtest loop son lugares tipicos donde
    # ocurrira el descuido; pin contractualmente con ``with``.
    def __enter__(self) -> OHLCVStore:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.close()

    # ------------------------------------------------------------------------
    # Schema migrations
    # ------------------------------------------------------------------------
    def _run_migrations(self) -> None:
        cur = self._conn.execute("PRAGMA user_version")
        row = cur.fetchone()
        # Siempre devuelve (version,) 1-tupla; default 0.
        version = int(row[0]) if row else 0
        if version < 1:
            self._log.info(
                "ohlcv_store_migration_v1_start",
                from_version=version,
                db_path=str(self._db_path),
                # F3 (round-1 review): pinear absolute path + cwd para
                # visibilidad operacional. Si la URL es relativa y CWD !=
                # repo root, el DB aparece en lugar inesperado; este log
                # permite a ops detectarlo antes de que el bot escriba
                # estado en una locacion incorrecta.
                db_path_resolved=str(self._db_path.resolve()),
                cwd=Path.cwd().as_posix(),
            )
            for ddl in _SCHEMA_V1_DDL:
                self._conn.execute(ddl)
            self._conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
            self._log.info("ohlcv_store_migration_v1_done")
        # Futuros deltas: if version < 2: migrate_v1_to_v2() ...


def _parse_sqlite_url(database_url: str) -> Path:
    """Mini-parser para URLs ``sqlite:///<path>``.

    Soporta:
    - ``sqlite:///<path>`` (relativo: ``sqlite:///data/storage/bot.db``)
    - ``sqlite:////<path>`` (absoluto: ``sqlite:////var/data/bot.db``)

    Cualquier otro esquema (postgresql/mysql/in-memory) levanta
    ``NotImplementedError`` per scope TSK-102; TSK-100 lo amplia con
    SQLAlchemy.

    El path resuelto se interpreta respecto al CWD al instanciar
    ``OHLCVStore``. El bot debe arrancar con CWD = repo root.
    """
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise NotImplementedError(
            f"TSK-102 solo soporta '{prefix}<path>'. URL recibida: "
            f"{database_url!r}. TSK-100 ampliara con SQLAlchemy para "
            f"otros backends (postgresql, mysql, in-memory, etc.)."
        )
    # Strip 10 chars: "sqlite:///"
    path_str = database_url[len(prefix) :]
    return Path(path_str)


def _is_absolute_path(path_str: str) -> bool:
    """Cross-platform absolute-path detection via string inspection.

    Por que NO usar ``pathlib.Path.is_absolute()``: en Windows,
    ``Path("/var/data/bot.db").is_absolute()`` retorna ``False`` porque
    pathlib exige drive letter (``C:/...``) para considerar absoluta
    una ruta. Pero un caller que pasa ``sqlite:////var/data/bot.db``
    desde YAML espera que esa ruta sea absoluta en el host destino -y
    en cualquier Linux/Unix corriendo el bot (Docker compose, CI, VPS),
    ``/var/data/bot.db`` ES absoluta.

    Esta helper detecta absolutos via heuristica de string:
    - ``/foo`` -> POSIX root / Windows "rooted at current drive".
    - ``\\\\foo`` -> Windows root o UNC.
    - ``C:`` / ``C:\\\\`` / ``C:/`` -> Windows drive letter.

    NO confundir con ``Path.is_absolute()``: si necesitas OS-native
    semantics, usa esa. Esta helper es para el contrato cross-platform
    del modulo (los tests no fallan en Windows cuando el caller
    documento una ruta absoluta via la convencion ``sqlite:////<path>``).
    """
    if path_str.startswith(("/", "\\")):
        return True
    return bool(len(path_str) >= 2 and path_str[0].isalpha() and path_str[1] == ":")


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "OHLCVStore",
    "_is_absolute_path",
    "_parse_sqlite_url",
]
