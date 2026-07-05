"""Entry point CLI del bot.

Comandos disponibles:

- ``config-check``: valida los archivos YAML y .env. No toca la red.
- ``scan --demo``: ejecuta UNA iteracion del ``UniverseScanner`` con
  datos sinteticos (``FakeMarketDataSource``). Util para verificar
  que el orquestador, los filtros y el scoring funcionan end-to-end
  sin necesitar credenciales de un exchange real. Fase 1+.
- ``run --mode <MODE>``: arranca el bot en un modo dado. Por ahora
  delega a ``scan --demo`` para paper/backtest/research; live/shadow
  requieren exchange connector cableado (pendiente).
- ``kill-switch``, ``status``: stubs para Fase 2+. Reservados.

Fase objetivo: 1 (market data + scanner operativos); 2+ agrega
scheduler, execution, risk policies.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import TYPE_CHECKING

from pydantic import ValidationError

from trading_bot import __version__
from trading_bot.config import load_settings

if TYPE_CHECKING:
    from trading_bot.scanner.scanner import CounterSnapshot, UniverseScanner
    from trading_bot.scanner.types import MarketSnapshot

# Default universe for `scan --demo`. Extracted as a module constant so
# tests and BBDs that need a different pair set can pass their own
# ``pairs=`` argument explicitly without depending on a hidden default.
DEFAULT_DEMO_PAIRS: list[tuple[str, bool]] = [
    ("BTC/USDT", True),
    ("ETH/USDT", True),
    ("SOL/USDT", True),
    ("AVAX/USDT", True),
    ("MATIC/USDT", True),
]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trading-bot",
        description="crypto-scalping-agentic-bot CLI",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"trading-bot {__version__}",
    )

    sub = parser.add_subparsers(dest="command", required=False)

    # ------------------------------------------------------------------
    # config-check
    # ------------------------------------------------------------------
    config_parser = sub.add_parser("config-check", help="Valida los archivos YAML y .env.")
    config_parser.add_argument(
        "--config-dir",
        default="config",
        help="Directorio con los YAML (default: ./config).",
    )
    config_parser.add_argument(
        "--env-file",
        default=".env",
        help="Path al .env (default: ./.env). Pasar vacio para no cargar.",
    )

    # ------------------------------------------------------------------
    # scan (Fase 1+ : una iteracion del scanner)
    # ------------------------------------------------------------------
    scan_parser = sub.add_parser(
        "scan",
        help="Ejecuta una iteracion del UniverseScanner. --demo usa datos sinteticos.",
    )
    scan_parser.add_argument(
        "--demo",
        action="store_true",
        default=True,
        help="Usa FakeMarketDataSource (datos sinteticos, sin exchange). DEFAULT.",
    )
    scan_parser.add_argument(
        "--no-demo",
        dest="demo",
        action="store_false",
        help="[reservado] Intenta usar ExchangeConnector real. Sin implementacion todavia.",
    )
    scan_parser.add_argument(
        "--mode",
        default="paper",
        choices=["research", "backtest", "paper", "live", "shadow_live"],
        help="Modo del scanner (default: paper).",
    )
    scan_parser.add_argument(
        "--config-dir",
        default="config",
        help="Directorio con los YAML (default: ./config).",
    )
    scan_parser.add_argument(
        "--env-file",
        default=".env",
        help="Path al .env (default: ./.env). Pasar vacio para no cargar.",
    )

    # ------------------------------------------------------------------
    # run (placeholder, Fase 1+ delegara a scheduler)
    # ------------------------------------------------------------------
    run_parser = sub.add_parser("run", help="Arranca el bot (modo seguro por defecto).")
    run_parser.add_argument(
        "--mode",
        default="paper",
        choices=["research", "backtest", "paper", "live", "shadow_live"],
        help="Modo del bot (default: paper). Por ahora delega a scan --demo.",
    )

    sub.add_parser("kill-switch", help="Activa/desactiva el kill switch.")
    sub.add_parser("status", help="Muestra estado actual del bot.")

    return parser


# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------


def _cmd_config_check(args: argparse.Namespace) -> int:
    env_file = args.env_file if args.env_file else None
    try:
        settings = load_settings(config_dir=args.config_dir, env_file=env_file)
    except ValidationError as exc:
        sys.stderr.write("ERROR: la configuracion no es valida.\n\n")
        sys.stderr.write(exc.json(indent=2) + "\n")
        return 1

    print("Configuracion valida.")
    print(f"  mode:                 {settings.runtime.mode.value}")
    print(f"  live_trading_enabled: {settings.runtime.live_trading_enabled}")
    print(f"  pairs enabled:        {sum(1 for pair in settings.universe.pairs if pair.enabled)}")
    print(f"  strategies:           {len(settings.strategies.strategies)}")
    return 0


def _build_demo_scanner(mode: str) -> "UniverseScanner":
    """Construye un ``UniverseScanner`` pre-cargado con datos sinteticos.

    Pipeline:
    1. ``build_demo_settings``: 5 pares USDT en mode=paper.
    2. ``build_demo_fetcher``: pre-pobla ``FakeMarketDataSource`` con
       volumes/spreads/OHLCV realistas.
    3. ``build_filter_set_per_mode``: 4 ``FilterRegistry`` per VALID_MODES
       (volume, spread, atr; orden perf volume->spread->atr).
    4. ``UniverseScanner`` DI: source + registry_per_mode + settings.

    ``kill_switch_enabled=False`` explicito: el demo debe iterar
    sobre los pares; el kill switch esta cubierto por su propio
    scenario BDD (RF-4) en ``tests/bdd/step_defs/test_runtime_steps.py``.
    """
    from trading_bot.market_data.fake import (
        build_demo_fetcher,
        build_demo_settings,
    )
    from trading_bot.scanner.mode_filters import build_filter_set_per_mode
    from trading_bot.scanner.scanner import UniverseScanner

    settings = build_demo_settings(pairs=DEFAULT_DEMO_PAIRS, mode=mode, kill_switch_enabled=False)
    source = build_demo_fetcher(settings)
    registry_per_mode = build_filter_set_per_mode(settings)
    return UniverseScanner(
        source=source,
        registry_per_mode=registry_per_mode,  # type: ignore[arg-type]
        settings=settings,
    )


def _run_single_iteration(mode: str) -> tuple[list["MarketSnapshot"], "CounterSnapshot"]:
    """Ejecuta una iteracion del scanner demo. Retorna (snapshots, counters).

    Extraido de ``_cmd_scan`` para que tanto ``scan`` como ``run``
    puedan invocarlo sin construir ``argparse.Namespace`` falsos.
    """
    scanner = _build_demo_scanner(mode=mode)
    snapshots = asyncio.run(scanner.run())
    return snapshots, scanner.counters


def _print_demo_results(
    snapshots: list["MarketSnapshot"], counters: "CounterSnapshot", mode: str
) -> int:
    """Imprime los snapshots en formato tabla + counters. Retorna exit code."""
    print()
    print("=" * 78)
    print(f"Market scanner iteration -- DEMO mode (mode={mode}, synthetic data)")
    print("=" * 78)
    if not snapshots:
        print()
        print("  (sin snapshots en esta iteracion)")
    else:
        print()
        print(f"  {'SYMBOL':<14} {'LAST':>10} {'VOL_24H_USDT':>16} {'SPR_BPS':>9} {'ATR%':>7} {'SCORE':>7}  STATUS")
        print("  " + "-" * 76)
        for snap in snapshots:
            atr = f"{snap.atr_pct:.2f}" if snap.atr_pct is not None else "  n/a"
            status = "ACTIVE" if snap.active else f"INACTIVE ({snap.rejection_reason})"
            print(
                f"  {snap.symbol:<14} "
                f"{snap.last_price:>10.2f} "
                f"{snap.volume_24h_usdt:>16,.0f} "
                f"{snap.spread_bps:>9.2f} "
                f"{atr:>7} "
                f"{snap.rank_score:>7.3f}  {status}"
            )
    print()
    print("Counters (pine contract: spec section 10):")
    print(f"  pairs_processed:  {counters.pairs_processed}")
    print(f"  pairs_active:     {counters.pairs_active}")
    print(f"  pairs_inactive:   {counters.pairs_inactive}")
    print(f"  scanner_errors:   {counters.scanner_errors}")
    print()
    if counters.pairs_active == 0:
        print("NOTA: 0 pares activos. Si esperabas ver ACTIVE, los filtros son")
        print("      demasiado estrictos para los datos sinteticos por defecto.")
    return 0


def _cmd_scan(args: argparse.Namespace) -> int:
    if not args.demo:
        sys.stderr.write(
            "ERROR: --no-demo (exchange connector real) no esta implementado todavia. "
            "Usa --demo para validar la orquestacion con datos sinteticos. "
            "Pendiente: TSK-101 wiring (CCXTExchangeConnector + OHLCVFetcher).\n"
        )
        return 2

    snapshots, counters = _run_single_iteration(mode=args.mode)
    return _print_demo_results(snapshots, counters, mode=args.mode)


def _cmd_run(args: argparse.Namespace) -> int:
    """Stub del scheduler. Por ahora delega a ``_run_single_iteration``
    (el nucleo de ``scan --demo``) para que el usuario pueda ver el
    orquestador funcionando en ``paper`` sin tener que aprender dos
    sub-comandos. La implementacion real (scheduler APScheduler +
    loop continuo) entra en Fase 2.
    """
    print(f"[run] scheduler real pendiente; ejecutando una iteracion --demo (mode={args.mode}).")
    snapshots, counters = _run_single_iteration(mode=args.mode)
    return _print_demo_results(snapshots, counters, mode=args.mode)


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada principal."""
    parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "config-check":
        return _cmd_config_check(args)
    if args.command == "scan":
        return _cmd_scan(args)
    if args.command == "run":
        return _cmd_run(args)
    if args.command == "kill-switch":
        print("[stub] kill-switch: pendiente.")  # pragma: no cover  # stub hasta Fase 2+
        return 0
    if args.command == "status":
        print("[stub] status: pendiente.")  # pragma: no cover  # stub hasta Fase 2+
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
