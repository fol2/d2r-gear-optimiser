"""Shared utilities for domain models."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Return current UTC time (timezone-aware)."""
    return datetime.now(UTC)
