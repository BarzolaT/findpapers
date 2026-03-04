"""Abstract interfaces for database-specific query builders."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict

from findpapers.core.query import FilterCode, Query


@dataclass(slots=True)
class QueryValidationResult:
    """Validation result for database-specific query compatibility.

    Attributes
    ----------
    is_valid : bool
        Whether the query is valid for the target database.
    error_message : str | None
        Human-readable error when validation fails.
    """

    is_valid: bool
    error_message: str | None = None


@dataclass(slots=True)
class QueryExecutionPlan:
    """Execution metadata produced by a query builder.

    Attributes
    ----------
    request_payloads : list[str | dict]
        Payloads that must be sent by the searcher.
    combination_expression : str
        Expression describing how searcher results should be combined.
        The expression uses aliases `q0`, `q1`, ... and boolean operators
        `AND`, `OR`, and `NOT` with set semantics:
        - `AND`: intersection of result sets
        - `OR`: union of result sets
        - `NOT`: difference (left minus right)
    """

    request_payloads: list[str | Dict]
    combination_expression: str


class QueryBuilder(ABC):
    """Abstract base class for database-specific query builders.

    Subclasses must declare the set of supported filter codes by overriding
    ``_SUPPORTED_FILTERS`` and must implement ``validate_query`` and
    ``convert_query``.  The remaining methods have sensible defaults that
    subclasses may override when they need custom behaviour:

    * ``supports_filter`` – returns ``True`` iff ``filter_code`` is in
      ``_SUPPORTED_FILTERS``.
    * ``preprocess_terms`` – returns the query unchanged.
    * ``expand_query`` – returns a single-element list containing the original
      query.
    """

    # Override in subclasses to declare which FilterCodes are accepted.
    _SUPPORTED_FILTERS: frozenset[FilterCode] = frozenset()

    @abstractmethod
    def validate_query(self, query: Query) -> QueryValidationResult:
        """Validate if this builder supports the given query.

        Parameters
        ----------
        query : Query
            Parsed query object.

        Returns
        -------
        QueryValidationResult
            Validation result with compatibility information.
        """

    @abstractmethod
    def convert_query(self, query: Query) -> str | Dict:
        """Convert Query into a database-specific payload.

        Parameters
        ----------
        query : Query
            Parsed query object.

        Returns
        -------
        str | dict
            Query string for URL-based APIs or parameter dictionary for REST APIs.
        """

    def preprocess_terms(self, query: Query) -> Query:
        """Preprocess query terms before conversion.

        The default implementation returns the query unchanged. Override this
        method when the target database requires term normalisation (e.g.
        hyphen removal).

        Parameters
        ----------
        query : Query
            Query to preprocess.

        Returns
        -------
        Query
            Preprocessed query.
        """
        return query

    def supports_filter(self, filter_code: FilterCode) -> bool:
        """Check whether the builder supports a filter code.

        Returns ``True`` iff ``filter_code`` is present in
        ``_SUPPORTED_FILTERS``.  Override when more complex logic is needed.

        Parameters
        ----------
        filter_code : FilterCode
            Filter code to check.

        Returns
        -------
        bool
            True when the filter is supported.
        """
        return filter_code in self._SUPPORTED_FILTERS

    def expand_query(self, query: Query) -> list[Query]:
        """Expand query into multiple queries when necessary.

        The default implementation returns a single-element list containing
        the original query unchanged.  Override this method for databases that
        require query decomposition (e.g. OpenAlex DNF expansion).

        Parameters
        ----------
        query : Query
            Query to expand.

        Returns
        -------
        list[Query]
            Expanded query list.
        """
        return [query]

    def build_execution_plan(self, query: Query) -> QueryExecutionPlan:
        """Build request payloads and result-combination instructions.

        Parameters
        ----------
        query : Query
            Parsed query object.

        Returns
        -------
        QueryExecutionPlan
            Request payloads and expression for combining results.
        """
        expanded_queries = self.expand_query(query)
        request_payloads = [
            self.convert_query(expanded_query) for expanded_query in expanded_queries
        ]
        combination_expression = self._build_combination_expression(expanded_queries)
        return QueryExecutionPlan(
            request_payloads=request_payloads,
            combination_expression=combination_expression,
        )

    def _build_combination_expression(self, expanded_queries: list[Query]) -> str:
        """Build default combination expression for expanded queries.

        Parameters
        ----------
        expanded_queries : list[Query]
            Queries returned by ``expand_query``.

        Returns
        -------
        str
            Combination expression.
        """
        if not expanded_queries:
            return ""
        if len(expanded_queries) == 1:
            return "q0"
        return " OR ".join(f"q{index}" for index in range(len(expanded_queries)))
