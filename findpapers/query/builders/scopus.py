"""Scopus query builder."""

from __future__ import annotations

import re

from findpapers.core.query import Query, QueryNode
from findpapers.query.builder import QueryBuilder, QueryValidationResult
from findpapers.query.builders.common import (
    convert_expression,
    get_effective_filter,
    iter_term_nodes,
)


class ScopusQueryBuilder(QueryBuilder):
    """Build Scopus-compatible query expressions."""

    _SUPPORTED_FILTERS = {"ti", "abs", "key", "au", "pu", "af", "tiabs", "tiabskey"}

    def validate_query(self, query: Query) -> QueryValidationResult:
        """Validate whether Scopus supports this query.

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
                    error_message=f"Filter '{filter_code}' is not supported by Scopus.",
                )
            if not term.value:
                continue

            first_wildcard = min(
                [index for index in (term.value.find("*"), term.value.find("?")) if index != -1],
                default=-1,
            )
            if first_wildcard != -1 and first_wildcard < 3:
                return QueryValidationResult(
                    is_valid=False,
                    error_message=(
                        "Scopus wildcards require at least 3 characters before '*' or '?'."
                    ),
                )

            if re.search(r"[-.][*?]|[*?][-.]", term.value):
                return QueryValidationResult(
                    is_valid=False,
                    error_message="Scopus does not support wildcard combined with hyphen or dot.",
                )
        return QueryValidationResult(is_valid=True)

    def convert_query(self, query: Query) -> str:
        """Convert query into Scopus syntax.

        Parameters
        ----------
        query : Query
            Query to convert.

        Returns
        -------
        str
            Scopus query string.
        """
        connector_map = {
            "and": "AND",
            "or": "OR",
            "and not": "AND NOT",
        }

        def convert_term(term_node: QueryNode) -> str:
            term = term_node.value or ""
            quoted = f'"{term}"'
            filter_code = get_effective_filter(term_node)

            if filter_code == "ti":
                return f"TITLE({quoted})"
            if filter_code == "abs":
                return f"ABS({quoted})"
            if filter_code == "key":
                return f"KEY({quoted})"
            if filter_code == "au":
                return f"AUTH({quoted})"
            if filter_code == "pu":
                return f"SRCTITLE({quoted})"
            if filter_code == "af":
                return f"AFFIL({quoted})"
            if filter_code == "tiabs":
                return f"TITLE-ABS({quoted})"
            return f"TITLE-ABS-KEY({quoted})"

        return convert_expression(query.root, convert_term, connector_map)

    def preprocess_terms(self, query: Query) -> Query:
        """Return query unchanged for Scopus.

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
        """Check filter support for Scopus.

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
        """Return query without expansion for Scopus.

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
