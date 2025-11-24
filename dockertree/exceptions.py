"""
Custom exception hierarchy for Dockertree.

These exceptions allow command and orchestration layers to communicate
structured failure information without duplicating logging or exit logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class DockertreeError(Exception):
    """Base exception carrying structured error metadata."""

    message: str
    error_code: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    exit_code: int = 1

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


class DockertreeCommandError(DockertreeError):
    """Raised when a CLI command encounters a recoverable failure."""


class PrerequisiteError(DockertreeError):
    """Raised when environment or prerequisite checks fail."""


