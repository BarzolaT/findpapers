"""Exception hierarchy for the findpapers library.

All library-specific exceptions inherit from :class:`FindpapersError`,
allowing callers to catch ``FindpapersError`` as a single entry point for
any error raised by this package.  Each leaf exception also inherits from
the corresponding built-in type (``ValueError``, ``TypeError``) so that
existing ``except ValueError`` handlers continue to work.
"""


class FindpapersError(Exception):
    """Base exception for all findpapers-specific errors."""


class UnsupportedQueryError(FindpapersError, ValueError):
    """Raised when a query uses features not supported by a specific database."""


class ConnectorError(FindpapersError):
    """Raised when an external API connector encounters an unrecoverable error."""


class ExportError(FindpapersError):
    """Raised when export/import encounters an unsupported data type or format."""


class QueryValidationError(FindpapersError, ValueError):
    """Raised when a query string is invalid."""
