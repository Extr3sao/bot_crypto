"""CLI entry point for the config module.

Usage::

    python -m trading_bot.config --validate           # exit 0/1 + resumen
    python -m trading_bot.config --dump-json          # JSON completo
    python -m trading_bot.config --config-dir cfg/    # directorio YAML
    python -m trading_bot.config --env-file           # no cargar .env
"""

from __future__ import annotations

import argparse
import sys

from pydantic import ValidationError

from trading_bot.config.settings import load_settings


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m trading_bot.config",
        description="Validate and inspect the bot configuration.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Carga y valida los YAML y el .env; exit 0 si OK.",
    )
    parser.add_argument(
        "--dump-json",
        action="store_true",
        help="Serializa la configuracion resuelta a JSON (model_dump_json).",
    )
    parser.add_argument(
        "--config-dir",
        default="config",
        help="Directorio con los YAML (default: ./config).",
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path al .env (default: ./.env). Pasar vacio para no cargar.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not (args.validate or args.dump_json):
        parser.print_help()
        return 0

    env_file: str | None = args.env_file if args.env_file else None

    try:
        settings = load_settings(config_dir=args.config_dir, env_file=env_file)
    except ValidationError as exc:
        sys.stderr.write("ERROR: la configuracion no es valida.\n\n")
        sys.stderr.write(exc.json(indent=2) + "\n")
        return 1

    if args.dump_json:
        print(settings.model_dump_json(indent=2))
    else:
        rt = settings.runtime
        uni = settings.universe
        print("Configuracion valida.")
        print(f"  mode:                 {rt.mode.value}")
        print(f"  live_trading_enabled: {rt.live_trading_enabled}")
        print(f"  pairs enabled:        {sum(1 for p in uni.pairs if p.enabled)}")
        print(f"  strategies:           {len(settings.strategies.strategies)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
