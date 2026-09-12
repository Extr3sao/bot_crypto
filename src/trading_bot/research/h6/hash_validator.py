"""SHA256 validator — strict 64 hex chars, fail-closed manifest construction.

EXT-MANIFEST-HASH-001 repair: H6_MANIFEST_V2 contained a 71-char malformed
ledger hash due to manual copy-paste ( bb2b43c...71 vs correct 64 ).
All V3 hashes must be generated programmatically and validated.
"""

from __future__ import annotations

import re

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def validate_sha256(value: str, field_name: str = "sha256") -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name}: expected str, got {type(value).__name__}")
    if len(value) != 64:
        raise ValueError(f"{field_name}: expected 64 chars, got {len(value)}: {value!r}")
    if not _SHA256_RE.match(value):
        raise ValueError(f"{field_name}: not lowercase hex [0-9a-f]{{64}}: {value!r}")
    return value


def assert_all_shas(mapping: dict, prefix: str = "") -> None:
    """Walk mapping and validate any key ending with sha256/sha."""
    for k, v in mapping.items():
        lk = k.lower()
        if lk.endswith("sha256") or lk.endswith("_sha"):
            if isinstance(v, str):
                validate_sha256(v, f"{prefix}{k}")
        elif isinstance(v, dict):
            assert_all_shas(v, prefix=f"{prefix}{k}.")
