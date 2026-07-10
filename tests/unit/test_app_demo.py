"""Unit tests for the ``scan --demo`` CLI surface (TSK-103.5.2.1 + F5).

The ``_run_single_iteration`` function is the core of both the
``scan --demo`` and ``run --mode`` CLI sub-commands. It wires up:

1. ``build_demo_settings``: 5 pares USDT en mode=paper.
2. ``build_demo_fetcher``: pre-pobla ``FakeMarketDataSource`` con
   volumes/spreads/OHLCV realistas.
3. ``build_filter_set_per_mode``: 4 ``FilterRegistry`` per VALID_MODES
   (volume, spread, atr; orden perf volume->spread->atr).
4. ``UniverseScanner.run()``: la iteracion real.

These tests bring the previously-omitted ``src/trading_bot/app.py``
under the 90% coverage gate (removed from ``tool.coverage.run.omit``
in ``pyproject.toml`` so the coverage report now sees ``_cmd_scan``,
``_cmd_run``, ``_cmd_config_check``, ``_run_single_iteration``,
``_build_demo_scanner``, ``_print_demo_results``, ``_build_parser``,
``main``, etc.).
"""

from __future__ import annotations

import argparse

import pytest

from trading_bot.app import (
    _build_demo_scanner,
    _build_parser,
    _cmd_config_check,
    _cmd_run,
    _cmd_scan,
    _print_demo_results,
    _run_single_iteration,
    main,
)
from trading_bot.scanner.types import MarketSnapshot

# 5 pares DEFAULT_DEMO_PAIRS in app.py: BTC, ETH, SOL, AVAX, MATIC.
EXPECTED_PAIR_COUNT = 5

REQUIRED_SNAPSHOT_FIELDS: tuple[str, ...] = (
    "symbol",
    "last_price",
    "volume_24h_usdt",
    "spread_bps",
    "atr_pct",
    "volatility_pct",
    "active",
    "rejection_reason",
    "timestamp",
    "rank_score",
)


# ===========================================================================
# _run_single_iteration
# ===========================================================================


def test_run_single_iteration_paper_returns_snapshots_and_counters() -> None:
    """The demo iteration returns ``(snapshots, counters)`` matching the
    5 DEFAULT_DEMO_PAIRS."""
    snapshots, counters = _run_single_iteration("paper")

    assert len(snapshots) == EXPECTED_PAIR_COUNT
    assert counters.pairs_processed == EXPECTED_PAIR_COUNT


def test_run_single_iteration_paper_snapshots_are_market_snapshot_instances() -> None:
    """Each snapshot is a ``MarketSnapshot`` (frozen dataclass per spec)."""
    snapshots, _ = _run_single_iteration("paper")

    for snap in snapshots:
        assert isinstance(snap, MarketSnapshot)


def test_run_single_iteration_paper_snapshots_have_all_required_fields() -> None:
    """Each snapshot exposes the 10 required fields (spec section 2)."""
    snapshots, _ = _run_single_iteration("paper")

    for snap in snapshots:
        for field_name in REQUIRED_SNAPSHOT_FIELDS:
            assert hasattr(snap, field_name), (
                f"MarketSnapshot missing {field_name!r} (spec section 2)"
            )


def test_run_single_iteration_paper_produces_active_and_inactive_mix() -> None:
    """With the default demo data the scanner should produce a mix of
    ACTIVE and INACTIVE snapshots (the fake source is tuned for that
    per TSK-103.5.2.1 round-7 review)."""
    snapshots, _ = _run_single_iteration("paper")

    active = [s for s in snapshots if s.active]
    inactive = [s for s in snapshots if not s.active]

    assert len(active) >= 1, "demo debe producir al menos 1 par ACTIVE"
    assert len(inactive) >= 1, "demo debe producir al menos 1 par INACTIVE"
    assert len(active) + len(inactive) == EXPECTED_PAIR_COUNT


def test_run_single_iteration_paper_inactive_snapshots_have_rejection_reason() -> None:
    """Pine contract: cada snapshot inactivo lleva su rejection_reason."""
    snapshots, _ = _run_single_iteration("paper")

    inactive = [s for s in snapshots if not s.active]
    for snap in inactive:
        assert snap.rejection_reason, f"{snap.symbol} esta inactivo pero sin rejection_reason"


def test_run_single_iteration_paper_counters_add_up() -> None:
    """Pine contract: counters add up to pairs_processed."""
    _, counters = _run_single_iteration("paper")

    assert counters.pairs_active + counters.pairs_inactive == counters.pairs_processed
    assert counters.scanner_errors == 0  # fake source nunca falla


def test_run_single_iteration_backtest_mode_also_works() -> None:
    """The function accepts the ``backtest`` mode (otro VALID_MODE)."""
    snapshots, counters = _run_single_iteration("backtest")

    assert len(snapshots) == EXPECTED_PAIR_COUNT
    assert counters.pairs_processed == EXPECTED_PAIR_COUNT


def test_run_single_iteration_research_mode_also_works() -> None:
    """The function accepts the ``research`` mode (otro VALID_MODE)."""
    snapshots, counters = _run_single_iteration("research")

    assert len(snapshots) == EXPECTED_PAIR_COUNT
    assert counters.pairs_processed == EXPECTED_PAIR_COUNT


# ===========================================================================
# _build_demo_scanner
# ===========================================================================


def test_build_demo_scanner_returns_universe_scanner() -> None:
    """Pine contract: _build_demo_scanner returns a fully wired
    UniverseScanner with synthetic data."""
    from trading_bot.scanner.scanner import UniverseScanner

    scanner = _build_demo_scanner("paper")
    assert isinstance(scanner, UniverseScanner)


# ===========================================================================
# _print_demo_results
# ===========================================================================


def test_print_demo_results_returns_zero_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    """_print_demo_results is the user-facing formatter; must return 0."""
    snapshots, counters = _run_single_iteration("paper")
    exit_code = _print_demo_results(snapshots, counters, mode="paper")
    assert exit_code == 0

    captured = capsys.readouterr()
    # Verifica que imprime las secciones clave del formato tabla.
    assert "Market scanner iteration" in captured.out
    assert "Counters" in captured.out
    assert "pairs_processed" in captured.out


def test_print_demo_results_handles_empty_snapshots(capsys: pytest.CaptureFixture[str]) -> None:
    """_print_demo_results debe manejar lista vacia sin crashear."""
    from trading_bot.scanner.scanner import CounterSnapshot

    empty_counters = CounterSnapshot(
        pairs_processed=0, pairs_active=0, pairs_inactive=0, scanner_errors=0
    )
    exit_code = _print_demo_results([], empty_counters, mode="paper")
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "sin snapshots" in captured.out
    assert "0 pares activos" in captured.out  # warning for 0 ACTIVE


# ===========================================================================
# _build_parser
# ===========================================================================


def test_build_parser_has_all_subcommands() -> None:
    """Pine contract: parser expone los 5 sub-comandos documentados."""
    parser = _build_parser()
    # Public-API-safe: check via format_help() substring match. Avoids
    # the private _actions / _SubParsersAction internals that have
    # been renamed in some Python 3.13+ argparse refactors.
    help_text = parser.format_help()
    for cmd in ("config-check", "scan", "run", "place-order", "kill-switch", "status"):
        assert cmd in help_text, f"subcommand {cmd!r} missing from parser help"


def test_build_parser_scan_defaults_to_paper_and_demo() -> None:
    """Pine contract: scan sin flags = --demo + --mode paper."""
    parser = _build_parser()
    args = parser.parse_args(["scan"])
    assert args.demo is True
    assert args.mode == "paper"


def test_build_parser_scan_no_demo_flag() -> None:
    """Pine contract: scan --no-demo desactiva el flag demo."""
    parser = _build_parser()
    args = parser.parse_args(["scan", "--no-demo"])
    assert args.demo is False


def test_build_parser_run_defaults_to_continuous_loop() -> None:
    """Pine contract: run sin flags adicionales deja el loop continuo activo."""
    parser = _build_parser()
    args = parser.parse_args(["run"])
    assert args.mode == "paper"
    assert args.loop_seconds == 30
    assert args.once is False
    assert args.web_port == 0
    assert args.web_host == "127.0.0.1"


def test_build_parser_place_order_requires_explicit_fields() -> None:
    """place-order debe parsear su contrato base sin ambigüedad."""
    parser = _build_parser()
    args = parser.parse_args(
        [
            "place-order",
            "--symbol",
            "BTC/USDT",
            "--side",
            "buy",
            "--order-type",
            "market",
            "--amount",
            "0.001",
            "--confirm-live",
        ]
    )
    assert args.symbol == "BTC/USDT"
    assert args.side == "buy"
    assert args.order_type == "market"
    assert args.amount == 0.001
    assert args.confirm_live is True


# ===========================================================================
# _cmd_scan
# ===========================================================================


def test_cmd_scan_with_demo_runs_iteration(capsys: pytest.CaptureFixture[str]) -> None:
    """_cmd_scan con --demo (default) ejecuta la iteracion y retorna 0."""
    parser = _build_parser()
    args = parser.parse_args(["scan"])
    exit_code = _cmd_scan(args)
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "Market scanner iteration" in captured.out


def test_cmd_scan_with_no_demo_returns_error_code() -> None:
    """_cmd_scan con --no-demo (exchange connector no implementado)
    debe retornar exit code 2 + mensaje a stderr."""
    parser = _build_parser()
    args = parser.parse_args(["scan", "--no-demo"])
    exit_code = _cmd_scan(args)
    assert exit_code == 2


def test_cmd_run_once_executes_single_iteration(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """run --once debe ejecutar una sola iteracion y retornar 0."""
    parser = _build_parser()
    args = parser.parse_args(["run", "--mode", "paper", "--once"])
    exit_code = _cmd_run(args)
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "Market scanner iteration" in captured.out


def test_cmd_run_rejects_non_positive_loop_seconds() -> None:
    """run debe rechazar intervalos no positivos con exit code 2."""
    parser = _build_parser()
    args = parser.parse_args(["run", "--loop-seconds", "0"])
    exit_code = _cmd_run(args)
    assert exit_code == 2


def test_cmd_run_rejects_negative_web_port() -> None:
    """run debe rechazar web-port negativos con exit code 2."""
    parser = _build_parser()
    args = parser.parse_args(["run", "--web-port", "-1"])
    exit_code = _cmd_run(args)
    assert exit_code == 2


# ===========================================================================
# _cmd_config_check
# ===========================================================================


def test_cmd_config_check_succeeds_with_default_config(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Pine contract: config-check con config/ y .env por defecto
    debe validar OK (los YAMLs de config/ son validos por definicion
    per sprint-001 TSK-099)."""
    args = argparse.Namespace(config_dir="config", env_file=".env")
    exit_code = _cmd_config_check(args)
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "Configuracion valida" in captured.out


def test_cmd_config_check_with_invalid_config_returns_error_code(
    capsys: pytest.CaptureFixture[str],
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hermetic: config-check con un ValidationError debe retornar 1
    y el error a stderr. Usa monkeypatch sobre ``load_settings`` para
    evitar dependencias de PyYAML / filesystem / Pydantic schema."""
    from pydantic import ValidationError

    def _raise_validation_error(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise ValidationError.from_exception_data(
            "Settings",
            [
                {
                    "type": "missing",
                    "loc": ("universe",),
                    "input": {},
                    "msg": "Field required",
                }
            ],
        )

    monkeypatch.setattr("trading_bot.app.load_settings", _raise_validation_error)

    args = argparse.Namespace(config_dir="config", env_file="")
    exit_code = _cmd_config_check(args)
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "ERROR" in captured.err
    assert "no es valida" in captured.err


# ===========================================================================
# main()
# ===========================================================================


def test_main_no_command_prints_help_and_returns_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Pine contract: main sin sub-comando imprime help y retorna 0."""
    exit_code = main([])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "usage:" in captured.out.lower() or "trading-bot" in captured.out


def test_main_scan_runs_iteration(capsys: pytest.CaptureFixture[str]) -> None:
    """Pine contract: main con ``scan`` ejecuta el comando y retorna 0."""
    exit_code = main(["scan"])
    assert exit_code == 0


def test_main_run_runs_iteration(capsys: pytest.CaptureFixture[str]) -> None:
    """Pine contract: main con ``run --once`` ejecuta la iteracion y retorna 0."""
    exit_code = main(["run", "--mode", "paper", "--once"])
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "Market scanner iteration" in captured.out


def test_main_kill_switch_stub_returns_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Pine contract: kill-switch es un stub que retorna 0."""
    exit_code = main(["kill-switch"])
    assert exit_code == 0


def test_main_status_stub_returns_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Pine contract: status es un stub que retorna 0."""
    exit_code = main(["status"])
    assert exit_code == 0


def test_main_unknown_command_exits_via_argparse() -> None:
    """Pine contract: argparse rechaza comandos desconocidos ANTES de
    que ``main()`` los vea (SystemExit(2) per argparse convention)."""
    with pytest.raises(SystemExit) as excinfo:
        main(["nonexistent-command"])
    assert excinfo.value.code == 2  # argparse standard exit code for usage errors


def test_main_version_flag_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    """Pine contract: --version imprime la version y sale."""
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
