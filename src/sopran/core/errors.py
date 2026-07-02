from __future__ import annotations


class SopranError(Exception):
    """Base class for SOPRAN public exceptions."""


class ConfigError(SopranError, ValueError):
    """Raised when configuration cannot be resolved or validated."""


class DatasetNotFoundError(SopranError, LookupError):
    """Raised when a requested dataset or shard is not available."""


class DownloadError(SopranError, OSError):
    """Raised when raw data download or local acquisition fails."""


class DecodeError(SopranError, ValueError):
    """Raised when mission data decoding fails."""


class SchemaError(SopranError, ValueError):
    """Raised when data does not match a SOPRAN schema."""


class FrameTransformError(SopranError, ValueError):
    """Raised when coordinate or frame transformation fails."""


class PipelineError(SopranError, RuntimeError):
    """Raised when pipeline planning or execution fails."""


class BackendError(SopranError, RuntimeError):
    """Raised when an external or Rust backend stage fails."""
