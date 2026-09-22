"""Trade journal service — persists trade cases to SQLite (Fase 8).

Bridges the pipeline signals to the trade_journal domain types.
Each trade gets: entry thesis, outcome, chart snapshot reference.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import structlog

from trading_bot.paper.broker import ClosedTrade, PaperPosition
from trading_bot.strategies.types import Signal


class TradeJournal:
    """SQLite-backed trade journal.

    Stores trade cases with entry thesis, outcome, and metadata.
    Read-only queries for analysis. No auto-promotion of recommendations.
    """

    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self._db_path = str(db_path)
        # Asegurar que el directorio del archivo exista para persistencia a disco
        # (se omite para la BD en memoria ":memory:").
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._log = structlog.get_logger("trade_journal")
        # Desambiguador de ``trade_id``: dos aperturas del MISMO símbolo en el
        # MISMO milisegundo colisionan (``T-<ms>-<SYMBOL>`` es PRIMARY KEY y
        # ``time.time()*1000`` no es único por ms). Sufijo ``-N`` solo cuando el
        # base ya se usó en esta instancia; el formato documentado se preserva.
        self._trade_id_seen: dict[str, int] = {}
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                trade_id TEXT PRIMARY KEY,
                signal_id TEXT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                strategy TEXT,
                entry_price REAL,
                exit_price REAL,
                quantity REAL,
                notional_usdt REAL,
                pnl_net REAL,
                exit_reason TEXT,
                sl_pct REAL,
                tp_pct REAL,
                confidence REAL,
                timeframe TEXT,
                metadata_json TEXT,
                opened_at REAL,
                closed_at REAL,
                created_at REAL DEFAULT (strftime('%s', 'now'))
            );

            CREATE TABLE IF NOT EXISTS indicators (
                trade_id TEXT,
                indicator_name TEXT,
                value REAL,
                FOREIGN KEY (trade_id) REFERENCES trades(trade_id)
            );

            CREATE TABLE IF NOT EXISTS rejections (
                decision_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                strategy TEXT,
                timeframe TEXT,
                confidence REAL,
                price REAL,
                reason TEXT,
                blocked_by TEXT,
                metadata_json TEXT,
                rejected_at REAL,
                created_at REAL DEFAULT (strftime('%s', 'now'))
            );
        """)
        self._conn.commit()

    def record_open(self, signal: Signal, position: PaperPosition) -> str:
        """Record a new trade opening.

        Returns trade_id.
        """
        base_trade_id = f"T-{int(time.time() * 1000)}-{signal.symbol.replace('/', '')}"
        seq = self._trade_id_seen.get(base_trade_id, 0) + 1
        self._trade_id_seen[base_trade_id] = seq
        trade_id = base_trade_id if seq == 1 else f"{base_trade_id}-{seq}"
        self._conn.execute(
            """INSERT INTO trades
               (trade_id, signal_id, symbol, side, strategy, entry_price,
                quantity, notional_usdt, sl_pct, tp_pct, confidence,
                timeframe, metadata_json, opened_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trade_id,
                f"S-{int(signal.price * 1000)}",
                signal.symbol,
                signal.side,
                signal.strategy_name,
                position.entry_price,
                position.quantity,
                position.notional_usdt,
                position.stop_loss_pct,
                position.take_profit_pct,
                signal.confidence,
                signal.timeframe,
                json.dumps(signal.metadata),
                position.opened_at,
            ),
        )

        # Record indicator values from signal metadata
        for key, value in signal.metadata.items():
            if isinstance(value, (int, float)):
                self._conn.execute(
                    "INSERT INTO indicators (trade_id, indicator_name, value) VALUES (?, ?, ?)",
                    (trade_id, key, float(value)),
                )

        self._conn.commit()
        self._log.info("journal.trade_opened", trade_id=trade_id, symbol=signal.symbol)
        return trade_id

    def record_close(self, trade_id: str, trade: ClosedTrade) -> None:
        """Record a trade closing with PnL."""
        self._conn.execute(
            """UPDATE trades SET
               exit_price = ?, pnl_net = ?, exit_reason = ?, closed_at = ?
               WHERE trade_id = ?""",
            (trade.exit_price, trade.pnl, trade.exit_reason, trade.closed_at, trade_id),
        )
        self._conn.commit()
        self._log.info(
            "journal.trade_closed",
            trade_id=trade_id,
            pnl=trade.pnl,
            reason=trade.exit_reason,
        )

    def get_trade(self, trade_id: str) -> dict[str, Any] | None:
        """Get a single trade by ID."""
        row = self._conn.execute("SELECT * FROM trades WHERE trade_id = ?", (trade_id,)).fetchone()
        if row is None:
            return None
        return dict(row)

    def get_open_trades(self) -> list[dict[str, Any]]:
        """Get all open trades (no exit yet)."""
        rows = self._conn.execute(
            "SELECT * FROM trades WHERE closed_at IS NULL ORDER BY opened_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_closed_trades(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent closed trades."""
        rows = self._conn.execute(
            "SELECT * FROM trades WHERE closed_at IS NOT NULL ORDER BY closed_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def record_blocked(
        self,
        signal: Signal,
        reason: str,
        blocked_by: str | None = None,
    ) -> str:
        """Registra una señal que NO entró (bloqueada por riesgo) para auditoría.

        Guarda el motivo del bloqueo y la explicación que la estrategia había
        calculado, para auditar por qué el bot NO entró en una posición.
        Returns decision_id.
        """
        decision_id = f"B-{int(time.time() * 1000)}-{signal.symbol.replace('/', '')}"
        self._conn.execute(
            """INSERT INTO rejections
               (decision_id, symbol, side, strategy, timeframe, confidence,
                price, reason, blocked_by, metadata_json, rejected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                decision_id,
                signal.symbol,
                signal.side,
                signal.strategy_name,
                signal.timeframe,
                signal.confidence,
                signal.price,
                reason,
                blocked_by,
                json.dumps(signal.metadata),
                time.time(),
            ),
        )
        self._conn.commit()
        self._log.info(
            "journal.signal_blocked",
            decision_id=decision_id,
            symbol=signal.symbol,
            reason=reason,
            blocked_by=blocked_by,
        )
        return decision_id

    @staticmethod
    def _where_clauses(
        symbol: str | None,
        side: str | None,
        start: float | None,
        end: float | None,
        time_col: str,
    ) -> tuple[str, list[object]]:
        """Construye WHERE + params para los filtros de auditoría."""
        clauses: list[str] = []
        params: list[object] = []
        if symbol:
            clauses.append("symbol LIKE ? COLLATE NOCASE")
            params.append(f"%{symbol}%")
        if side:
            clauses.append("side = ? COLLATE NOCASE")
            params.append(side)
        if start is not None:
            clauses.append(f"{time_col} >= ?")
            params.append(start)
        if end is not None:
            clauses.append(f"{time_col} <= ?")
            params.append(end)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        return where, params

    def get_entry_decisions(
        self,
        limit: int = 500,
        *,
        symbol: str | None = None,
        side: str | None = None,
        start: float | None = None,
        end: float | None = None,
        status: str | None = None,
        reason: str | None = None,
    ) -> list[dict[str, Any]]:
        """Devuelve las decisiones (entradas + bloqueadas) para auditoría.

        Filtros opcionales: ``symbol`` (subcadena, case-insensitive),
        ``side`` (buy/sell), rango de fechas (``start``/``end`` epoch seconds,
        inclusivo), ``status`` ("entered"/"trade" solo entradas,
        "blocked" solo bloqueadas, None = ambas) y ``reason`` (coincidencia
        exacta del motivo de entrada, ej. al hacer clic en un motivo del
        win-rate).

        Cada decisión incluye el motivo, la explicación textual y los
        indicadores/parámetros sobre los que el bot basó su criterio (leídos
        de ``metadata_json``). Las entradas llevan ``kind="trade"`` y las
        bloqueadas ``kind="blocked"`` con su motivo de rechazo.
        """
        where_trades, params = self._where_clauses(symbol, side, start, end, "opened_at")
        where_rej, params_rej = self._where_clauses(symbol, side, start, end, "rejected_at")

        decisions: list[dict[str, Any]] = []

        include_trades = status in (None, "entered", "trade")
        include_blocked = status in (None, "blocked")

        if include_trades:
            rows = self._conn.execute(
                f"""SELECT trade_id, symbol, side, strategy, timeframe, confidence,
                           entry_price, quantity, sl_pct, tp_pct, pnl_net,
                           exit_reason, metadata_json, opened_at, closed_at
                    FROM trades{where_trades} ORDER BY opened_at DESC LIMIT ?""",
                (*params, limit),
            ).fetchall()
            for row in rows:
                meta: dict[str, Any] = {}
                try:
                    meta = json.loads(row["metadata_json"] or "{}")
                except (json.JSONDecodeError, TypeError):
                    meta = {}
                indicators = {
                    str(k): float(v) for k, v in meta.items() if isinstance(v, (int, float))
                }
                closed = row["closed_at"] is not None
                decisions.append(
                    {
                        "decision_id": row["trade_id"],
                        "trade_id": row["trade_id"],
                        "kind": "trade",
                        "status": "closed" if closed else "open",
                        "symbol": row["symbol"],
                        "side": row["side"],
                        "strategy": row["strategy"],
                        "timeframe": row["timeframe"],
                        "confidence": row["confidence"],
                        "entry_price": row["entry_price"],
                        "quantity": row["quantity"],
                        "sl_pct": row["sl_pct"],
                        "tp_pct": row["tp_pct"],
                        "pnl_net": row["pnl_net"],
                        "exit_reason": row["exit_reason"],
                        "opened_at": row["opened_at"],
                        "closed_at": row["closed_at"],
                        "reason": None,
                        "blocked_by": None,
                        "entry_reason": meta.get("entry_reason"),
                        "explanation": meta.get("explanation"),
                        "risk_reward_ratio": meta.get("risk_reward_ratio"),
                        "sl_price": meta.get("sl_price"),
                        "tp_price": meta.get("tp_price"),
                        "candle_direction": meta.get("candle_direction"),
                        "indicators": indicators,
                    }
                )

        if include_blocked:
            rows = self._conn.execute(
                f"""SELECT decision_id, symbol, side, strategy, timeframe,
                           confidence, price, reason, blocked_by, metadata_json,
                           rejected_at
                    FROM rejections{where_rej} ORDER BY rejected_at DESC LIMIT ?""",
                (*params_rej, limit),
            ).fetchall()
            for row in rows:
                meta = {}
                try:
                    meta = json.loads(row["metadata_json"] or "{}")
                except (json.JSONDecodeError, TypeError):
                    meta = {}
                indicators = {
                    str(k): float(v) for k, v in meta.items() if isinstance(v, (int, float))
                }
                decisions.append(
                    {
                        "decision_id": row["decision_id"],
                        "trade_id": row["decision_id"],
                        "kind": "blocked",
                        "status": "blocked",
                        "symbol": row["symbol"],
                        "side": row["side"],
                        "strategy": row["strategy"],
                        "timeframe": row["timeframe"],
                        "confidence": row["confidence"],
                        "entry_price": row["price"],
                        "quantity": None,
                        "sl_pct": None,
                        "tp_pct": None,
                        "pnl_net": None,
                        "exit_reason": None,
                        "opened_at": row["rejected_at"],
                        "closed_at": None,
                        "reason": row["reason"],
                        "blocked_by": row["blocked_by"],
                        "entry_reason": meta.get("entry_reason"),
                        "explanation": meta.get("explanation"),
                        "risk_reward_ratio": meta.get("risk_reward_ratio"),
                        "sl_price": meta.get("sl_price"),
                        "tp_price": meta.get("tp_price"),
                        "candle_direction": meta.get("candle_direction"),
                        "indicators": indicators,
                    }
                )

        if reason:
            decisions = [d for d in decisions if d.get("entry_reason") == reason]

        decisions.sort(key=lambda d: d.get("opened_at") or 0, reverse=True)
        return decisions[:limit]

    def _closed_rows(
        self,
        *,
        symbol: str | None = None,
        side: str | None = None,
        start: float | None = None,
        end: float | None = None,
    ) -> list[sqlite3.Row]:
        """Filas de trades cerrados con los filtros de auditoría aplicados."""
        where, params = self._where_clauses(symbol, side, start, end, "opened_at")
        # `where` empieza con " WHERE ", pero aquí ya fijamos la condicion de
        # cierre; convertirla a " AND ..." para evitar un WHERE duplicado.
        if where:
            where = where.replace(" WHERE ", " AND ", 1)
        return self._conn.execute(
            f"""SELECT symbol, side, strategy, pnl_net, metadata_json
                FROM trades WHERE closed_at IS NOT NULL{where}""",
            params,
        ).fetchall()

    @staticmethod
    def _win_rate_breakdown(
        rows: list[sqlite3.Row],
        key_fn: Callable[[sqlite3.Row], str],
        label_key: str,
        min_count: int,
        win_rate_threshold: float | None,
        min_trades_for_alert: int | None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
        """Agrupa trades cerrados por ``key_fn`` y calcula win-rate/PnL.

        Devuelve ``(grupos, overall, alerts)``. Cada grupo expone su etiqueta
        bajo ``label_key`` ("reason"/"strategy"/"symbol"), conteos,
        win-rate, PnL total/medio y pares que lo componen.
        """
        groups: dict[str, dict[str, Any]] = {}
        total: dict[str, float] = {
            "count": 0.0,
            "wins": 0.0,
            "losses": 0.0,
            "breakeven": 0.0,
            "total_pnl": 0.0,
        }

        for row in rows:
            label = key_fn(row)
            pnl = float(row["pnl_net"] or 0.0)
            g = groups.setdefault(
                label,
                {
                    label_key: label,
                    "count": 0,
                    "wins": 0,
                    "losses": 0,
                    "breakeven": 0,
                    "total_pnl": 0.0,
                    "symbols": set(),
                },
            )
            g["count"] += 1
            g["total_pnl"] += pnl
            g["symbols"].add(row["symbol"])
            if pnl > 0:
                g["wins"] += 1
            elif pnl < 0:
                g["losses"] += 1
            else:
                g["breakeven"] += 1

            total["count"] += 1
            total["total_pnl"] += pnl
            if pnl > 0:
                total["wins"] += 1
            elif pnl < 0:
                total["losses"] += 1
            else:
                total["breakeven"] += 1

        group_list: list[dict[str, Any]] = []
        for g in groups.values():
            if g["count"] < min_count:
                continue
            g["win_rate"] = round(g["wins"] / g["count"], 4) if g["count"] else 0.0
            g["avg_pnl"] = round(g["total_pnl"] / g["count"], 4) if g["count"] else 0.0
            g["symbols"] = sorted(g["symbols"])
            g["alert"] = False
            group_list.append(g)
        group_list.sort(key=lambda r: (-r["count"], -r["win_rate"]))

        overall = {
            "count": int(total["count"]),
            "wins": int(total["wins"]),
            "losses": int(total["losses"]),
            "breakeven": int(total["breakeven"]),
            "win_rate": round(total["wins"] / total["count"], 4) if total["count"] else 0.0,
            "total_pnl": round(total["total_pnl"], 4),
        }

        # Alerta por umbral de win-rate (configurable en runtime.audit).
        alerts: list[dict[str, Any]] = []
        if win_rate_threshold is not None and min_trades_for_alert is not None:
            for g in group_list:
                if g["count"] >= min_trades_for_alert and g["win_rate"] < win_rate_threshold:
                    g["alert"] = True
                    alerts.append(
                        {
                            label_key: g[label_key],
                            "count": g["count"],
                            "wins": g["wins"],
                            "losses": g["losses"],
                            "win_rate": g["win_rate"],
                            "total_pnl": g["total_pnl"],
                        }
                    )
            if (
                overall["count"] >= min_trades_for_alert
                and overall["win_rate"] < win_rate_threshold
            ):
                overall["alert"] = True
            else:
                overall["alert"] = False

        return group_list, overall, alerts

    @staticmethod
    def _win_rate_config(
        win_rate_threshold: float | None, min_trades_for_alert: int | None
    ) -> dict[str, Any]:
        return {
            "win_rate_threshold": win_rate_threshold,
            "min_trades_for_alert": min_trades_for_alert,
        }

    @staticmethod
    def _meta_entry_reason(row: sqlite3.Row) -> str:
        meta: dict[str, Any] = {}
        try:
            meta = json.loads(row["metadata_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            meta = {}
        return str(meta.get("entry_reason") or "sin motivo")

    def get_win_rate_by_entry_reason(
        self,
        *,
        symbol: str | None = None,
        side: str | None = None,
        start: float | None = None,
        end: float | None = None,
        min_count: int = 1,
        win_rate_threshold: float | None = None,
        min_trades_for_alert: int | None = None,
    ) -> dict[str, Any]:
        """Win-rate por motivo de entrada (trades cerrados).

        Agrupa las operaciones cerradas por el ``entry_reason`` guardado en
        ``metadata_json`` y calcula, para cada motivo: nº de operaciones,
        ganadas/perdidas/breakeven, win-rate, PnL total y medio. Devuelve
        también el agregado ``overall``. Acepta los mismos filtros que
        ``get_entry_decisions``. Si se pasan ``win_rate_threshold`` y
        ``min_trades_for_alert``, marca ``alert=True`` y lista en ``alerts``
        los motivos con muestra suficiente que quedan por debajo del umbral.
        """
        rows = self._closed_rows(symbol=symbol, side=side, start=start, end=end)
        reasons, overall, alerts = self._win_rate_breakdown(
            rows,
            self._meta_entry_reason,
            "reason",
            min_count,
            win_rate_threshold,
            min_trades_for_alert,
        )
        return {
            "reasons": reasons,
            "overall": overall,
            "alerts": alerts,
            "config": self._win_rate_config(win_rate_threshold, min_trades_for_alert),
        }

    def get_win_rate_by_strategy(
        self,
        *,
        symbol: str | None = None,
        side: str | None = None,
        start: float | None = None,
        end: float | None = None,
        min_count: int = 1,
        win_rate_threshold: float | None = None,
        min_trades_for_alert: int | None = None,
    ) -> dict[str, Any]:
        """Win-rate por estrategia (trades cerrados). Misma estructura que
        ``get_win_rate_by_entry_reason`` pero con la clave ``strategies``.
        """
        rows = self._closed_rows(symbol=symbol, side=side, start=start, end=end)
        strategies, overall, alerts = self._win_rate_breakdown(
            rows,
            lambda row: str(row["strategy"] or "sin estrategia"),
            "strategy",
            min_count,
            win_rate_threshold,
            min_trades_for_alert,
        )
        return {
            "strategies": strategies,
            "overall": overall,
            "alerts": alerts,
            "config": self._win_rate_config(win_rate_threshold, min_trades_for_alert),
        }

    def get_win_rate_by_symbol(
        self,
        *,
        symbol: str | None = None,
        side: str | None = None,
        start: float | None = None,
        end: float | None = None,
        min_count: int = 1,
        win_rate_threshold: float | None = None,
        min_trades_for_alert: int | None = None,
    ) -> dict[str, Any]:
        """Win-rate por par (trades cerrados). Misma estructura que
        ``get_win_rate_by_entry_reason`` pero con la clave ``symbols``.
        """
        rows = self._closed_rows(symbol=symbol, side=side, start=start, end=end)
        symbols, overall, alerts = self._win_rate_breakdown(
            rows,
            lambda row: str(row["symbol"]),
            "symbol",
            min_count,
            win_rate_threshold,
            min_trades_for_alert,
        )
        return {
            "symbols": symbols,
            "overall": overall,
            "alerts": alerts,
            "config": self._win_rate_config(win_rate_threshold, min_trades_for_alert),
        }

    def get_stats(self) -> dict[str, Any]:
        """Get aggregate trade statistics."""
        row = self._conn.execute("""
            SELECT
                COUNT(*) as total_trades,
                SUM(CASE WHEN pnl_net > 0 THEN 1 ELSE 0 END) as winning_trades,
                SUM(CASE WHEN pnl_net < 0 THEN 1 ELSE 0 END) as losing_trades,
                SUM(pnl_net) as total_pnl,
                AVG(pnl_net) as avg_pnl,
                MAX(pnl_net) as best_trade,
                MIN(pnl_net) as worst_trade,
                AVG(CASE WHEN pnl_net > 0 THEN pnl_net ELSE NULL END) as avg_win,
                AVG(CASE WHEN pnl_net < 0 THEN pnl_net ELSE NULL END) as avg_loss
            FROM trades WHERE closed_at IS NOT NULL
        """).fetchone()

        if row is None:
            return {"total_trades": 0}

        stats = dict(row)
        total = stats.get("total_trades", 0) or 0
        winning = stats.get("winning_trades", 0) or 0
        stats["win_rate"] = winning / total if total > 0 else 0.0
        return stats

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def __enter__(self) -> TradeJournal:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


__all__ = ["TradeJournal"]
