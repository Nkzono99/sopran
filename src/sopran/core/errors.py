from __future__ import annotations


class SopranError(Exception):
    """Base class for SOPRAN public exceptions."""


class DatasetNotFoundError(SopranError, LookupError):
    """Raised when a requested dataset or shard is not available."""
