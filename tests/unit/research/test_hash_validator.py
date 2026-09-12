"""EXT-MANIFEST-HASH-001 — SHA256 validator."""

from __future__ import annotations

import hashlib

import pytest

from trading_bot.research.h6.hash_validator import assert_all_shas, validate_sha256


def _valid_sha() -> str:
    return hashlib.sha256(b"hello").hexdigest()


def test_63_fails() -> None:
    with pytest.raises(ValueError, match="64 chars"):
        validate_sha256("a" * 63)


def test_65_fails() -> None:
    with pytest.raises(ValueError, match="64 chars"):
        validate_sha256("a" * 65)


def test_71_fails() -> None:
    malformed = "bb2b43c27a88bf9ff334fa5adcc753f5b34976d2b4df9061de34a94507d2bd8f58752dc"
    assert len(malformed) == 71
    with pytest.raises(ValueError):
        validate_sha256(malformed)


def test_non_hex_fails() -> None:
    bad = "z" * 64
    with pytest.raises(ValueError):
        validate_sha256(bad)


def test_uppercase_fails() -> None:
    good = _valid_sha()
    bad = good.upper()
    with pytest.raises(ValueError):
        validate_sha256(bad)


def test_correct_64_pass() -> None:
    good = _valid_sha()
    assert validate_sha256(good) == good


def test_assert_all_shas_detects_malformed_nested() -> None:
    good = _valid_sha()
    bad = "b" * 71
    with pytest.raises(ValueError):
        assert_all_shas({"outer": {"inner_sha256": bad}})
    # good passes
    assert_all_shas({"ledger_sha256": good})


def test_actual_ledger_sha_passes() -> None:
    actual = "bb2b43c27a88bf9fe3ec22573903a61007f046ddc1256b5caa3e788cba15e714"
    assert validate_sha256(actual) == actual
    claim = "bb2b43c27a88bf9ff334fa5adcc753f5b34976d2b4df9061de34a94507d2bd8f58752dc"
    with pytest.raises(ValueError):
        validate_sha256(claim)
