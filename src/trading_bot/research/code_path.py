"""Shared Code Path Validator (P21).

Verifies that research and live trading use the SAME strategy code.
P21 contract: avoid maintaining two different implementations of a strategy.

Provides:
- Code hash computation for strategy modules
- Cross-comparison between research and live code paths
- Drift detection over time
"""

from __future__ import annotations

import hashlib
import inspect
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog


@dataclass(frozen=True, slots=True)
class CodeHash:
    """Hash of a strategy module's source code."""

    module_path: str
    code_hash: str  # SHA256 of source code
    computed_at: int  # epoch ms

    @property
    def short_hash(self) -> str:
        return self.code_hash[:12]


@dataclass(frozen=True, slots=True)
class CodePathValidation:
    """Result of comparing research vs live code paths."""

    research_hash: CodeHash
    live_hash: CodeHash
    paths_match: bool
    validated_at: int

    @property
    def status(self) -> str:
        return "MATCH" if self.paths_match else "DRIFT_DETECTED"


class SharedCodePathValidator:
    """Verifies research and live share the same strategy code (P21).

    P21 contract:
    - The code of the signal used in research and live must share
      as much logic as possible.
    - Avoid maintaining two different implementations.
    - Detect drift automatically.
    """

    def __init__(self) -> None:
        self._log = structlog.get_logger("code_path_validator")

    def hash_module(self, module: Any) -> CodeHash:
        """Compute SHA256 hash of a module's source code.

        Args:
            module: A Python module or class with __module__ or __file__

        Returns:
            CodeHash with the hash and timestamp
        """
        source = self._get_source(module)
        code_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()

        return CodeHash(
            module_path=getattr(module, "__file__", str(module)),
            code_hash=code_hash,
            computed_at=int(time.time() * 1000),
        )

    def hash_file(self, path: Path | str) -> CodeHash:
        """Compute SHA256 hash of a file's content."""
        file_path = Path(path)
        source = file_path.read_text(encoding="utf-8")
        code_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()

        return CodeHash(
            module_path=str(file_path),
            code_hash=code_hash,
            computed_at=int(time.time() * 1000),
        )

    def validate(
        self,
        research_module: Any,
        live_module: Any,
    ) -> CodePathValidation:
        """Validate that research and live use the same code.

        Args:
            research_module: The strategy module/class used in research
            live_module: The strategy module/class used in live trading

        Returns:
            CodePathValidation with match status
        """
        research_hash = self.hash_module(research_module)
        live_hash = self.hash_module(live_module)

        paths_match = research_hash.code_hash == live_hash.code_hash

        if paths_match:
            self._log.info(
                "code_path.match",
                research=research_hash.short_hash,
                live=live_hash.short_hash,
            )
        else:
            self._log.warning(
                "code_path.drift_detected",
                research=research_hash.short_hash,
                live=live_hash.short_hash,
            )

        return CodePathValidation(
            research_hash=research_hash,
            live_hash=live_hash,
            paths_match=paths_match,
            validated_at=int(time.time() * 1000),
        )

    def validate_files(
        self,
        research_path: Path | str,
        live_path: Path | str,
    ) -> CodePathValidation:
        """Validate that two files contain the same code."""
        research_hash = self.hash_file(research_path)
        live_hash = self.hash_file(live_path)

        paths_match = research_hash.code_hash == live_hash.code_hash

        return CodePathValidation(
            research_hash=research_hash,
            live_hash=live_hash,
            paths_match=paths_match,
            validated_at=int(time.time() * 1000),
        )

    def _get_source(self, module: Any) -> str:
        """Get source code from a module or class."""
        try:
            return inspect.getsource(module)
        except (TypeError, OSError):
            # Built-in or unable to get source — use repr as fallback
            return repr(module)


__all__ = [
    "CodeHash",
    "CodePathValidation",
    "SharedCodePathValidator",
]
