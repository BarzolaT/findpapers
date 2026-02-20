"""IEEE Xplore query builder."""

from __future__ import annotations

from findpapers.core.query import FilterCode, NodeType, Query, QueryNode
from findpapers.query.builder import QueryBuilder, QueryValidationResult
from findpapers.query.builders.common import (
    convert_expression,
    get_effective_filter,
    iter_term_nodes,
)


class IEEEQueryBuilder(QueryBuilder):
    """Build IEEE Xplore-compatible query payloads."""

    _SUPPORTED_FILTERS = frozenset(
        {
            FilterCode.TITLE,
            FilterCode.ABSTRACT,
            FilterCode.KEYWORDS,
            FilterCode.AUTHOR,
            FilterCode.SOURCE,
            FilterCode.AFFILIATION,
            FilterCode.TITLE_ABSTRACT,
            FilterCode.TITLE_ABSTRACT_KEYWORDS,
        }
    )

    def validate_query(self, query: Query) -> QueryValidationResult:
        """Validate whether IEEE supports this query.

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
                    error_message=f"Filter '{filter_code}' is not supported by IEEE.",
                )
            if not term.value:
                continue
            if "?" in term.value:
                return QueryValidationResult(
                    is_valid=False,
                    error_message="Wildcard '?' is not supported by IEEE.",
                )
            if "*" in term.value:
                prefix = term.value.split("*")[0]
                if len(prefix) < 3:
                    return QueryValidationResult(
                        is_valid=False,
                        error_message="Wildcard '*' requires at least 3 chars before '*'.",
                    )
        return QueryValidationResult(is_valid=True)

    def convert_query(self, query: Query) -> dict:
        """Convert query into IEEE payload.

        Parameters
        ----------
        query : Query
            Query to convert.

        Returns
        -------
        dict
            IEEE query parameters.
        """
        from findpapers.core.query import ConnectorType

        if self._is_simple_single_term(query):
            term_node = query.root.children[0]
            return self._single_term_payload(term_node)

        connector_map = {
            ConnectorType.AND: "AND",
            ConnectorType.OR: "OR",
            ConnectorType.AND_NOT: "NOT",
        }

        def convert_term(term_node: QueryNode) -> str:
            term = term_node.value or ""
            filter_code = get_effective_filter(term_node)
            if filter_code == FilterCode.TITLE:
                return f'"Article Title":{self._quote(term)}'
            if filter_code == FilterCode.ABSTRACT:
                return f'"Abstract":{self._quote(term)}'
            if filter_code == FilterCode.KEYWORDS:
                return f'"Index Terms":{self._quote(term)}'
            if filter_code == FilterCode.AUTHOR:
                return f'"Authors":{self._quote(term)}'
            if filter_code == FilterCode.SOURCE:
                return f'"Publication Title":{self._quote(term)}'
            if filter_code == FilterCode.AFFILIATION:
                return f'"Affiliation":{self._quote(term)}'
            if filter_code == FilterCode.TITLE_ABSTRACT:
                title_expr = f'"Article Title":{self._quote(term)}'
                abs_expr = f'"Abstract":{self._quote(term)}'
                return f"({title_expr} OR {abs_expr})"
            title_expr = f'"Article Title":{self._quote(term)}'
            abs_expr = f'"Abstract":{self._quote(term)}'
            key_expr = f'"Index Terms":{self._quote(term)}'
            return f"({title_expr} OR {abs_expr} OR {key_expr})"

        expression = convert_expression(query.root, convert_term, connector_map)
        return {"querytext": expression}

    def _is_simple_single_term(self, query: Query) -> bool:
        """Check whether query has one direct term node.

        Parameters
        ----------
        query : Query
            Query to inspect.

        Returns
        -------
        bool
            True for single-term query.
        """
        return (
            len(query.root.children) == 1
            and query.root.children[0].node_type == NodeType.TERM
            and query.root.children[0].value is not None
        )

    def _single_term_payload(self, term_node: QueryNode) -> dict:
        """Build payload for simple single-term query.

        Parameters
        ----------
        term_node : QueryNode
            Term node to convert.

        Returns
        -------
        dict
            IEEE parameters for single-field mode.
        """
        term = term_node.value or ""
        filter_code = get_effective_filter(term_node)
        mapping = {
            FilterCode.TITLE: "article_title",
            FilterCode.ABSTRACT: "abstract",
            FilterCode.KEYWORDS: "index_terms",
            FilterCode.AUTHOR: "author",
            FilterCode.SOURCE: "publication_title",
            FilterCode.AFFILIATION: "affiliation",
        }
        if filter_code in mapping:
            return {mapping[filter_code]: term}
        if filter_code == FilterCode.TITLE_ABSTRACT:
            return {
                "querytext": (
                    f'("Article Title":{self._quote(term)} OR ' f'"Abstract":{self._quote(term)})'
                )
            }
        return {
            "querytext": (
                f'("Article Title":{self._quote(term)} OR '
                f'"Abstract":{self._quote(term)} OR '
                f'"Index Terms":{self._quote(term)})'
            )
        }

    def _quote(self, term: str) -> str:
        """Quote terms for IEEE expression.

        Parameters
        ----------
        term : str
            Raw term.

        Returns
        -------
        str
            Quoted term string.
        """
        return f'"{term}"'
