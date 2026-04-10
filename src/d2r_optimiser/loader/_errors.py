"""Loader error types — separated to avoid circular imports."""


class LoaderError(Exception):
    """Raised when a data file is malformed or cannot be loaded."""
