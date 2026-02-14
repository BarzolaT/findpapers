"""Abstract interfaces for database-specific query builders."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Union

from findpapers.core.query import Query


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

    request_payloads: list[Union[str, Dict]]
    combination_expression: str


class QueryBuilder(ABC):
    """Abstract base class for database-specific query builders."""

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
    def convert_query(self, query: Query) -> Union[str, Dict]:
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

    @abstractmethod
    def preprocess_terms(self, query: Query) -> Query:
        """Preprocess query terms before conversion.

        Parameters
        ----------
        query : Query
            Query to preprocess.

        Returns
        -------
        Query
            Preprocessed query.
        """

    @abstractmethod
    def supports_filter(self, filter_code: str) -> bool:
        """Check whether the builder supports a filter code.

        Parameters
        ----------
        filter_code : str
            Filter code to check.

        Returns
        -------
        bool
            True when the filter is supported.
        """

    @abstractmethod
    def expand_query(self, query: Query) -> List[Query]:
        """Expand query into multiple queries when necessary.

        Parameters
        ----------
        query : Query
            Query to expand.

        Returns
        -------
        list[Query]
            Expanded query list.
        """

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
