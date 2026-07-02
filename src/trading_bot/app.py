"""Entry point CLI del bot.

Sprint target: arranca el bot en modo seguro (``paper``) con scheduler
configurable. La implementación real se introduce en Fase 1+.
"""

from __future__ import annotations

import argparse
import sys

from trading_bot import __version__


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

    sub.add_parser("config-check", help="Valida los archivos YAML.")
    sub.add_parser("run", help="Arranca el bot (modo seguro por defecto).")
    sub.add_parser("kill-switch", help="Activa/desactiva el kill switch.")
    sub.add_parser("status", help="Muestra estado actual del bot.")

    return parser


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada mínimo.

    Por ahora solo expone la CLI y valida que la configuración carga.
    Las fases 1–9 introducirán los comandos reales.
    """
    parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.command is None:
        parser.print_help()
        return 0

    # Comandos stubs. La lógica real llega en fases sucesivas.
    if args.command == "config-check":
        print("[stub] config-check: pendiente. Ver tasks/backlog.md.")
        return 0
    if args.command == "run":
        print("[stub] run: pendiente. El bot no está implementado aún.")
        return 0
    if args.command == "kill-switch":
        print("[stub] kill-switch: pendiente.")
        return 0
    if args.command == "status":
        print("[stub] status: pendiente.")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
