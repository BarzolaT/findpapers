class SearchRunnerNotExecutedError(RuntimeError):
    """Raised when SearchRunner results are accessed before running."""


class UnsupportedQueryError(ValueError):
    """Raised when a query uses features not supported by a specific database."""
