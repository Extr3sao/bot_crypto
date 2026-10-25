"""The phase-2 slice extractor refuses before it invents.

The point of these tests is not that a happy path works. It is that every way of producing a slice
that would *look* like phase-2 evidence without being an honest projection of stored bars — an
empty window, a regenerated file, a duplicate bar, an unclosed bar, a corrupt line the selection
happens to skip — ends in a refusal with a non-zero exit code.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))

import exp004a_capture as capture  # noqa: E402
from exp004a_capture import (  # noqa: E402
    EXIT_CONTRACT,
    EXIT_EMPTY,
    SliceError,
    SliceSpec,
    build_slice,
    load_declaration,
    main,
    resolve_spec,
    write_slice,
)

HOUR = 3_600_000
START = "2026-10-22T00:00:00Z"
END = "2026-10-23T00:00:00Z"


def _ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def _row(
    open_ms: int, *, fetched_ms: int | None = None, closed: bool = True, interval: str = "1h"
) -> dict:
    return {
        "ts": open_ms,
        "interval": interval,
        "closed": closed,
        "fetched_at_ms": fetched_ms if fetched_ms is not None else open_ms + HOUR + 60_000,
        "open": 100.0,
        "close": 101.0,
    }


def _series(tmp_path: Path, rows: list[dict], name: str = "BTC.jsonl") -> Path:
    path = tmp_path / name
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def _spec(source: Path, *, start: str = START, end: str = END) -> SliceSpec:
    return SliceSpec(
        dataset_id="EXP-004A-1H-BTC",
        asset="BTC",
        interval="1h",
        source=source,
        period_start_ms=_ms(start),
        period_end_ms=_ms(end),
        lag_bound_ms=7_200_000,
        coverage_required=0.9,
        generator_command="python scripts/exp004a_capture.py --slice 1h:BTC",
        raw_file="data/exp004a/EXP-004A-1H-BTC.raw.jsonl",
        normalized_file="data/exp004a/EXP-004A-1H-BTC.jsonl",
    )


# --------------------------------------------------------------------------- #
# the declaration is the contract
# --------------------------------------------------------------------------- #
def test_the_declared_slice_resolves_and_names_a_bar_series() -> None:
    declaration = load_declaration()
    spec = resolve_spec("1h:BTC", declaration)
    assert spec.interval == "1h"
    assert spec.period_start_ms == _ms("2026-10-22T00:00:00Z")
    assert spec.period_end_ms == _ms("2027-01-20T00:00:00Z")
    assert spec.lag_bound_ms == 7_200_000
    assert spec.source.as_posix().endswith("data/forward/edge03/1h/BTC.jsonl")


def test_the_declared_tape_slice_is_refused_rather_than_given_an_invented_rule() -> None:
    """``st6:tape`` declares "4h slot, 3 rounds of 15s", which is not a bar in a series."""
    with pytest.raises(SliceError, match="not a bar series"):
        resolve_spec("st6:tape", load_declaration())


def test_an_undeclared_slice_is_refused() -> None:
    with pytest.raises(SliceError, match="is not declared"):
        resolve_spec("1h:XRP", load_declaration())


def test_a_slice_without_a_colon_is_refused() -> None:
    with pytest.raises(SliceError, match=r"<interval>:<asset>"):
        resolve_spec("1hBTC", load_declaration())


# --------------------------------------------------------------------------- #
# selection
# --------------------------------------------------------------------------- #
def test_only_bars_opening_inside_the_window_are_selected(tmp_path: Path) -> None:
    source = _series(
        tmp_path,
        [
            _row(_ms("2026-10-21T23:00:00Z")),  # before the window
            _row(_ms(START)),  # exactly at the start: included
            _row(_ms("2026-10-22T01:00:00Z")),
            _row(_ms("2026-10-22T23:00:00Z")),
            _row(_ms(END)),  # exactly at the end: excluded
        ],
    )
    payload, manifest = build_slice(_spec(source))
    lines = payload.decode().splitlines()
    assert manifest["row_count"] == 3
    assert manifest["first_open_utc"] == "2026-10-22T00:00:00.000Z"
    assert manifest["last_open_utc"] == "2026-10-22T23:00:00.000Z"
    assert [json.loads(line)["ts"] for line in lines] == [
        _ms(START),
        _ms("2026-10-22T01:00:00Z"),
        _ms("2026-10-22T23:00:00Z"),
    ]


def test_selected_lines_are_the_source_bytes_not_a_re_serialisation(tmp_path: Path) -> None:
    rows = [_row(_ms("2026-10-22T00:00:00Z")), _row(_ms("2026-10-22T01:00:00Z"))]
    path = tmp_path / "BTC.jsonl"
    # Deliberately irregular spacing: a re-serialisation would lose it.
    text = "".join(
        f'{{"ts": {row["ts"]},   "interval": "1h", "closed": true, '
        f'"fetched_at_ms": {row["fetched_at_ms"]}}}\n'
        for row in rows
    )
    path.write_bytes(text.encode())
    payload, _ = build_slice(_spec(path))
    assert payload == text.encode()


def test_late_bars_are_kept_and_counted_so_admission_can_reject_the_day(tmp_path: Path) -> None:
    punctual = _row(_ms("2026-10-22T00:00:00Z"))
    late = _row(_ms("2026-10-22T01:00:00Z"), fetched_ms=_ms("2026-10-25T00:00:00Z"))
    _payload, manifest = build_slice(_spec(_series(tmp_path, [punctual, late])))
    assert manifest["row_count"] == 2
    assert manifest["observed"]["bars_outside_lag_bound"] == 1
    assert manifest["observed"]["late_bars_kept"] is True


def test_an_empty_window_is_an_error_not_an_empty_dataset(tmp_path: Path) -> None:
    source = _series(tmp_path, [_row(_ms("2026-10-21T00:00:00Z"))])
    with pytest.raises(SliceError, match="empty slice is not a dataset"):
        build_slice(_spec(source))


def test_an_unclosed_bar_blocks_the_slice(tmp_path: Path) -> None:
    source = _series(tmp_path, [_row(_ms("2026-10-22T00:00:00Z"), closed=False)])
    with pytest.raises(SliceError, match="not closed"):
        build_slice(_spec(source))


def test_a_duplicate_open_instant_is_refused(tmp_path: Path) -> None:
    row = _row(_ms("2026-10-22T00:00:00Z"))
    source = _series(tmp_path, [row, dict(row)])
    with pytest.raises(SliceError, match="repeats a bar open instant"):
        build_slice(_spec(source))


def test_an_unordered_store_is_refused(tmp_path: Path) -> None:
    source = _series(
        tmp_path,
        [_row(_ms("2026-10-22T02:00:00Z")), _row(_ms("2026-10-22T01:00:00Z"))],
    )
    with pytest.raises(SliceError, match="not ordered"):
        build_slice(_spec(source))


def test_a_corrupt_line_outside_the_window_still_fails_the_whole_slice(tmp_path: Path) -> None:
    """The corrupt line could be the one bar whose absence admits a day; selection must not skip it."""
    good = _row(_ms("2026-10-22T00:00:00Z"))
    path = tmp_path / "BTC.jsonl"
    path.write_text(json.dumps(good) + "\n{not json\n", encoding="utf-8")
    with pytest.raises(SliceError, match="not JSON"):
        build_slice(_spec(path))


def test_a_missing_source_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(SliceError, match="does not exist"):
        build_slice(_spec(tmp_path / "absent.jsonl"))


# --------------------------------------------------------------------------- #
# writing
# --------------------------------------------------------------------------- #
def test_the_manifest_digest_matches_the_written_bytes(tmp_path: Path) -> None:
    source = _series(tmp_path, [_row(_ms("2026-10-22T00:00:00Z"))])
    payload, manifest = build_slice(_spec(source))
    dataset, manifest_path = write_slice(payload, manifest, tmp_path / "out")
    import hashlib

    assert hashlib.sha256(dataset.read_bytes()).hexdigest() == manifest["sha256"]
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["row_count"] == 1


def test_the_source_prefix_digest_addresses_only_the_selected_bars(tmp_path: Path) -> None:
    source = _series(
        tmp_path,
        [_row(_ms("2026-10-22T00:00:00Z")), _row(_ms("2026-10-24T00:00:00Z"))],
    )
    _, manifest = build_slice(_spec(source))
    assert manifest["source"]["prefix_bytes"] < manifest["source"]["total_bytes_at_read"]
    assert manifest["source"]["prefix_sha256"] != manifest["source"]["sha256_at_read"]


def test_a_slice_is_written_once(tmp_path: Path) -> None:
    source = _series(tmp_path, [_row(_ms("2026-10-22T00:00:00Z"))])
    payload, manifest = build_slice(_spec(source))
    write_slice(payload, manifest, tmp_path / "out")
    with pytest.raises(SliceError, match="already exists"):
        write_slice(payload, manifest, tmp_path / "out")


def test_the_same_source_yields_the_same_manifest_bytes(tmp_path: Path) -> None:
    source = _series(
        tmp_path,
        [_row(_ms("2026-10-22T00:00:00Z")), _row(_ms("2026-10-22T01:00:00Z"))],
    )
    left = write_slice(*build_slice(_spec(source)), tmp_path / "a")
    right = write_slice(*build_slice(_spec(source)), tmp_path / "b")
    assert left[1].read_bytes() == right[1].read_bytes()


# --------------------------------------------------------------------------- #
# the declared command line
# --------------------------------------------------------------------------- #
def test_the_cli_reports_an_unopened_window_with_exit_3(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _series(tmp_path, [_row(_ms("2026-10-21T00:00:00Z"))])
    code = main(["--slice", "1h:BTC", "--out", str(tmp_path / "out"), "--source", str(source)])
    assert code == EXIT_EMPTY
    assert not (tmp_path / "out").exists()
    assert json.loads(capsys.readouterr().err)["ok"] is False


def test_the_cli_writes_the_slice_the_declaration_names(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _series(tmp_path, [_row(_ms("2026-10-22T00:00:00Z"))])
    code = main(
        [
            "--slice",
            "1h:BTC",
            "--out",
            str(tmp_path / "out"),
            "--source",
            str(source),
            "--period-start",
            START,
            "--period-end",
            END,
        ]
    )
    assert code == capture.EXIT_OK
    assert (tmp_path / "out" / "EXP-004A-1H-BTC.jsonl").is_file()
    printed = json.loads(capsys.readouterr().out)
    assert printed["manifest"]["dataset_id"] == "EXP-004A-1H-BTC"


def test_the_cli_refuses_the_tape_slice_with_a_contract_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--slice", "st6:tape", "--dry-run"]) == EXIT_CONTRACT
    assert "not a bar series" in json.loads(capsys.readouterr().err)["error"]


# --------------------------------------------------------------------------- #
# provenance: a correct slice is not an authorised one
# --------------------------------------------------------------------------- #
def test_the_capture_is_blocked_without_a_declaration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """RFC §7: a missing declaration is a BLOCK, and nothing is written."""
    source = _series(tmp_path, [_row(_ms("2026-10-22T00:00:00Z"))])
    code = main(
        [
            "--slice",
            "1h:BTC",
            "--out",
            str(tmp_path / "out"),
            "--source",
            str(source),
            "--declaration",
            str(tmp_path / "absent.json"),
        ]
    )
    assert code == EXIT_CONTRACT
    assert not (tmp_path / "out").exists()
    printed = json.loads(capsys.readouterr().err)
    assert printed["defects"][0]["code"] == "DECLARATION_MISSING"


def test_a_slice_fetched_before_the_declaration_took_effect_is_not_eligible(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """RFC §7: the bars exist and are well formed, and they still do not count."""
    source = _series(
        tmp_path,
        [_row(_ms("2026-10-22T00:00:00Z"), fetched_ms=_ms("2026-10-21T09:00:00Z"))],
    )
    code = main(
        ["--slice", "1h:BTC", "--out", str(tmp_path / "out"), "--source", str(source)]
    )
    assert code == capture.EXIT_NOT_ELIGIBLE
    assert not (tmp_path / "out").exists()
    assert "before" in json.loads(capsys.readouterr().err)["error"]


def test_a_rehearsal_may_not_extend_the_declared_window(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _series(tmp_path, [_row(_ms("2026-10-22T00:00:00Z"))])
    code = main(
        [
            "--slice",
            "1h:BTC",
            "--out",
            str(tmp_path / "out"),
            "--source",
            str(source),
            "--period-end",
            "2027-06-01T00:00:00Z",
        ]
    )
    assert code == EXIT_CONTRACT
    assert "never extend" in json.loads(capsys.readouterr().err)["error"]


def test_the_written_manifest_names_the_declaration_and_commit_it_ran_under(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _series(tmp_path, [_row(_ms("2026-10-22T00:00:00Z"))])
    code = main(["--slice", "1h:BTC", "--out", str(tmp_path / "out"), "--source", str(source)])
    assert code == capture.EXIT_OK
    manifest = json.loads(capsys.readouterr().out)["manifest"]
    provenance = manifest["provenance"]
    assert provenance["eligible"] is True
    assert provenance["declaration_id"] == "EXP-004A.datasets.phase2/v1"
    assert len(provenance["generator"]["commit"]) == 40
    assert provenance["declaration_commit"]
    assert provenance["temporal"]["external_timestamp"] == "UNAVAILABLE"
    written = json.loads(
        (tmp_path / "out" / "EXP-004A-1H-BTC.MANIFEST.json").read_text(encoding="utf-8")
    )
    assert written["provenance"] == provenance
