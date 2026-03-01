"""Abstract base class for academic database search connectors.

Extends :class:`~findpapers.connectors.connector_base.ConnectorBase` with the
search-specific contract: query validation, paper fetching, and the public
:meth:`search` entry point used by the search runner.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from findpapers.core.paper import Paper
    from findpapers.core.query import Query
    from findpapers.query.builder import QueryBuilder, QueryValidationResult

from findpapers.connectors.connector_base import ConnectorBase
from findpapers.exceptions import UnsupportedQueryError

logger = logging.getLogger(__name__)

QUERY_COMBINATIONS_WARNING_THRESHOLD = 20


class SearchConnectorBase(ConnectorBase):
    """Abstract base class for academic database search connectors.

    Subclasses implement the search logic for a specific database and receive
    a database-specific ``QueryBuilder`` via dependency injection.  Each
    connector is responsible for:

    1. Validating the query against the database capabilities.
    2. Converting the query to the database-specific format.
    3. Executing HTTP requests with proper rate limiting (inherited from
       :class:`~findpapers.connectors.connector_base.ConnectorBase`).
    4. Parsing the API responses into :class:`~findpapers.core.paper.Paper` objects.
    """

    @property
    @abstractmethod
    def query_builder(self) -> "QueryBuilder":
        """Return the database-specific query builder.

        Returns
        -------
        QueryBuilder
            Builder used to validate and convert queries.
        """

    @abstractmethod
    def _fetch_papers(
        self,
        query: "Query",
        max_papers: Optional[int],
        progress_callback: Optional[Callable[[int, Optional[int]], None]],
    ) -> List["Paper"]:
        """Fetch papers from the database.

        Subclasses implement HTTP requests, rate limiting, pagination and
        response parsing here.

        Parameters
        ----------
        query : Query
            Pre-validated query object.
        max_papers : int | None
            Maximum papers to retrieve.  ``None`` means unlimited.
        progress_callback : Callable[[int, int | None], None] | None
            Optional callback invoked after each page / item with
            ``(items_processed, total_or_none)``.  ``items_processed`` counts
            every candidate item attempted (regardless of whether it was
            successfully parsed), so the bar always reaches ``total`` even
            when some items fail to parse.

        Returns
        -------
        list[Paper]
            Retrieved papers.

        Raises
        ------
        Exception
            Implementations may raise on network or parsing failures.
        """

    def search(
        self,
        query: "Query",
        max_papers: Optional[int] = None,
        progress_callback: Optional[Callable[[int, Optional[int]], None]] = None,
    ) -> List["Paper"]:
        """Execute search and return a list of papers.

        Validates the query first.  If validation fails the search is skipped
        for this database and an empty list is returned (warning is logged).

        Parameters
        ----------
        query : Query
            Parsed query object.
        max_papers : int | None
            Maximum number of papers to return.
        progress_callback : Callable[[int, int | None], None] | None
            Progress callback called as ``callback(current, total_or_none)``.

        Returns
        -------
        list[Paper]
            Retrieved papers, or empty list when query is incompatible.
        """
        validation: QueryValidationResult = self.query_builder.validate_query(query)

        if not validation.is_valid:
            raise UnsupportedQueryError(
                f"Search on '{self.name}' aborted: incompatible query. "
                + (validation.error_message or "")
            )

        try:
            return self._fetch_papers(query, max_papers, progress_callback)
        except Exception:
            logger.exception("Unexpected error while searching '%s'.", self.name)
            return []
