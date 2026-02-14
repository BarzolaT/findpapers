"""PubMed query builder."""

from __future__ import annotations

from findpapers.core.query import Query, QueryNode
from findpapers.query.builder import QueryBuilder, QueryValidationResult
from findpapers.query.builders.common import (
    convert_expression,
    get_effective_filter,
    iter_term_nodes,
)


class PubmedQueryBuilder(QueryBuilder):
    """Build PubMed-compatible query expressions."""

    _SUPPORTED_FILTERS = {"ti", "abs", "key", "au", "pu", "af", "tiabs", "tiabskey"}

    def validate_query(self, query: Query) -> QueryValidationResult:
        """Validate whether PubMed supports this query.

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
                    error_message=f"Filter '{filter_code}' is not supported by PubMed.",
                )
            if term.value and "?" in term.value:
                return QueryValidationResult(
                    is_valid=False,
                    error_message="Wildcard '?' is not supported by PubMed.",
                )
            if term.value and "*" in term.value:
                wildcard_index = term.value.find("*")
                if wildcard_index < 4:
                    return QueryValidationResult(
                        is_valid=False,
                        error_message=(
                            "PubMed wildcard '*' requires at least 4 characters " "before '*'."
                        ),
                    )
        return QueryValidationResult(is_valid=True)

    def convert_query(self, query: Query) -> str:
        """Convert query into PubMed syntax.

        Parameters
        ----------
        query : Query
            Query to convert.

        Returns
        -------
        str
            PubMed query string.
        """
        connector_map = {
            "and": "AND",
            "or": "OR",
            "and not": "NOT",
        }

        def convert_term(term_node: QueryNode) -> str:
            term = term_node.value or ""
            filter_code = get_effective_filter(term_node)

            def tagged(tag: str) -> str:
                return f'"{term}"[{tag}]'

            if filter_code == "ti":
                return tagged("ti")
            if filter_code == "abs":
                return tagged("ab")
            if filter_code == "key":
                return tagged("mh")
            if filter_code == "au":
                return tagged("au")
            if filter_code == "pu":
                return tagged("journal")
            if filter_code == "af":
                return tagged("ad")
            if filter_code == "tiabskey":
                return f"({tagged('tiab')} OR {tagged('mh')})"
            return tagged("tiab")

        return convert_expression(query.root, convert_term, connector_map)

    def preprocess_terms(self, query: Query) -> Query:
        """Return query unchanged for PubMed.

        Parameters
        ----------
        query : Query
            Query to preprocess.

        Returns
        -------
        Query
            Unchanged query.
        """
        return query

    def supports_filter(self, filter_code: str) -> bool:
        """Check filter support for PubMed.

        Parameters
        ----------
        filter_code : str
            Filter code.

        Returns
        -------
        bool
            True when supported.
        """
        return filter_code in self._SUPPORTED_FILTERS

    def expand_query(self, query: Query) -> list[Query]:
        """Return query without expansion for PubMed.

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
