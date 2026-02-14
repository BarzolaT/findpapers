"""arXiv query builder."""

from __future__ import annotations

from findpapers.core.query import Query, QueryNode
from findpapers.query.builder import QueryBuilder, QueryValidationResult
from findpapers.query.builders.common import (
    clone_query,
    convert_expression,
    get_effective_filter,
    has_wildcard,
    iter_term_nodes,
    quote_term,
)


class ArxivQueryBuilder(QueryBuilder):
    """Build arXiv-compatible query expressions."""

    _SUPPORTED_FILTERS = {"ti", "abs", "au", "tiabs"}

    def validate_query(self, query: Query) -> QueryValidationResult:
        """Validate whether arXiv supports this query.

        Parameters
        ----------
        query : Query
            Query to validate.

        Returns
        -------
        QueryValidationResult
            Validation result.
        """
        for term in iter_term_nodes(query.root):
            filter_code = get_effective_filter(term)
            if not self.supports_filter(filter_code):
                return QueryValidationResult(
                    is_valid=False,
                    error_message=f"Filter '{filter_code}' is not supported by arXiv.",
                )
            if term.value and has_wildcard(term.value):
                continue
        return QueryValidationResult(is_valid=True)

    def convert_query(self, query: Query) -> str:
        """Convert query into arXiv search expression.

        Parameters
        ----------
        query : Query
            Query to convert.

        Returns
        -------
        str
            arXiv query string.
        """
        preprocessed = self.preprocess_terms(query)

        connector_map = {
            "and": "AND",
            "or": "OR",
            "and not": "ANDNOT",
        }

        def convert_term(term_node: QueryNode) -> str:
            term = quote_term(term_node.value or "")
            filter_code = get_effective_filter(term_node)

            if filter_code == "ti":
                return f"ti:{term}"
            if filter_code == "abs":
                return f"abs:{term}"
            if filter_code == "au":
                return f"au:{term}"
            return f"(ti:{term} OR abs:{term})"

        converted = convert_expression(preprocessed.root, convert_term, connector_map)
        return converted.replace("(", "%28").replace(")", "%29")

    def preprocess_terms(self, query: Query) -> Query:
        """Replace hyphens with spaces for arXiv compatibility.

        Parameters
        ----------
        query : Query
            Query to preprocess.

        Returns
        -------
        Query
            Query with terms normalized for arXiv.
        """
        cloned_query = clone_query(query)
        for term in iter_term_nodes(cloned_query.root):
            if term.value:
                term.value = term.value.replace("-", " ")
        return cloned_query

    def supports_filter(self, filter_code: str) -> bool:
        """Check filter support for arXiv.

        Parameters
        ----------
        filter_code : str
            Filter code to check.

        Returns
        -------
        bool
            True when supported.
        """
        return filter_code in self._SUPPORTED_FILTERS

    def expand_query(self, query: Query) -> list[Query]:
        """Return query without expansion for arXiv.

        Parameters
        ----------
        query : Query
            Input query.

        Returns
        -------
        list[Query]
            Single query list.
        """
        return [query]
