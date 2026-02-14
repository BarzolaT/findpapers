"""OpenAlex query builder."""

from __future__ import annotations

import itertools

from findpapers.core.query import NodeType, Query, QueryNode
from findpapers.query.builder import QueryBuilder, QueryValidationResult
from findpapers.query.builders.common import (
    clone_query,
    get_effective_filter,
    has_wildcard,
    iter_connectors,
    iter_term_nodes,
)


class OpenAlexQueryBuilder(QueryBuilder):
    """Build OpenAlex-compatible query parameter dictionaries."""

    _SUPPORTED_FILTERS = {"ti", "abs", "key", "au", "pu", "af", "tiabs", "tiabskey"}

    def validate_query(self, query: Query) -> QueryValidationResult:
        """Validate whether OpenAlex supports this query.

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
                    error_message=f"Filter '{filter_code}' is not supported by OpenAlex.",
                )
            if term.value and (has_wildcard(term.value) or "~" in term.value):
                return QueryValidationResult(
                    is_valid=False,
                    error_message="Wildcards are not supported by OpenAlex.",
                )
        return QueryValidationResult(is_valid=True)

    def convert_query(self, query: Query) -> dict:
        """Convert query into OpenAlex filter syntax.

        Parameters
        ----------
        query : Query
            Query to convert.

        Returns
        -------
        dict
            OpenAlex parameters.
        """
        connectors = set(iter_connectors(query.root))
        if "or" in connectors or "and not" in connectors:
            return {"search": self._to_openalex_boolean_search(query.root)}

        filters: list[str] = []
        for term_node in iter_term_nodes(query.root):
            term = term_node.value or ""
            filter_code = get_effective_filter(term_node)
            filters.append(self._build_filter_fragment(filter_code, term))
        return {"filter": ",".join(filters)}

    def preprocess_terms(self, query: Query) -> Query:
        """Return query unchanged for OpenAlex.

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
        """Check filter support for OpenAlex.

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
        """Return query without expansion for OpenAlex.

        Parameters
        ----------
        query : Query
            Input query.

        Returns
        -------
        list[Query]
            Single query list.
        """
        # OpenAlex lacks field-aware OR inside `filter` for mixed cases. We first split
        # `tiabskey` into concrete filters and then decompose pure OR branches into
        # independent AND-only queries that can be executed separately.
        expanded = self._expand_tiabskey(query)

        final_queries: list[Query] = []
        for expanded_query in expanded:
            connectors = set(iter_connectors(expanded_query.root))
            if "or" in connectors and "and not" not in connectors:
                clauses = self._to_dnf_with_filters(expanded_query.root)
                final_queries.extend(
                    self._build_queries_from_clauses(clauses, expanded_query.raw_query)
                )
            else:
                final_queries.append(expanded_query)

        return final_queries

    def _build_filter_fragment(self, filter_code: str, term: str) -> str:
        """Build OpenAlex filter fragment for one term.

        Parameters
        ----------
        filter_code : str
            Effective filter code.
        term : str
            Search term.

        Returns
        -------
        str
            OpenAlex filter fragment.
        """
        encoded_term = f'"{term}"' if " " in term else term
        if filter_code == "ti":
            return f"title.search.no_stem:{encoded_term}"
        if filter_code == "abs":
            return f"abstract.search.no_stem:{encoded_term}"
        if filter_code == "key":
            return f"concepts.display_name:{encoded_term}"
        if filter_code == "au":
            return f"authorships.author.display_name.search:{encoded_term}"
        if filter_code == "pu":
            return f"primary_location.source.display_name.search:{encoded_term}"
        if filter_code == "af":
            return f"authorships.institutions.display_name.search:{encoded_term}"
        if filter_code == "tiabs":
            return f"title_and_abstract.search.no_stem:{encoded_term}"
        return f"search:{encoded_term}"

    def _to_openalex_boolean_search(self, node: QueryNode) -> str:
        """Convert query node to OpenAlex boolean search expression.

        Parameters
        ----------
        node : QueryNode
            Query node.

        Returns
        -------
        str
            Boolean search expression.
        """
        if node.node_type == NodeType.TERM:
            term = node.value or ""
            return f'"{term}"' if " " in term else term

        connector_map = {"and": "AND", "or": "OR", "and not": "NOT"}
        parts: list[str] = []
        for child in node.children:
            if child.node_type == NodeType.CONNECTOR and child.value:
                parts.append(connector_map[child.value])
                continue
            converted = self._to_openalex_boolean_search(child)
            if child.node_type == NodeType.GROUP:
                parts.append(f"({converted})")
            else:
                parts.append(converted)
        return " ".join(parts)

    def _expand_tiabskey(self, query: Query) -> list[Query]:
        """Expand terms with tiabskey into tiabs/key alternatives.

        Parameters
        ----------
        query : Query
            Query to expand.

        Returns
        -------
        list[Query]
            Expanded list of queries.
        """
        # We iteratively split one `tiabskey` term at a time to avoid recursive tree
        # mutation complexity and to preserve stable term positions per branch.
        pending = [clone_query(query)]
        results: list[Query] = []

        while pending:
            current = pending.pop()
            terms = list(iter_term_nodes(current.root))
            split_index = next(
                (
                    index
                    for index, term in enumerate(terms)
                    if get_effective_filter(term) == "tiabskey"
                ),
                None,
            )

            if split_index is None:
                results.append(current)
                continue

            tiabs_query = clone_query(current)
            key_query = clone_query(current)

            tiabs_terms = list(iter_term_nodes(tiabs_query.root))
            key_terms = list(iter_term_nodes(key_query.root))

            tiabs_terms[split_index].filter_code = "tiabs"
            key_terms[split_index].filter_code = "key"

            pending.extend([tiabs_query, key_query])

        return results

    def _to_dnf_with_filters(self, node: QueryNode) -> list[list[tuple[str, str]]]:
        """Convert query subtree to DNF preserving effective filters.

        Parameters
        ----------
        node : QueryNode
            Query node.

        Returns
        -------
        list[list[tuple[str, str]]]
            Clauses of (term, filter_code).
        """
        if node.node_type == NodeType.TERM:
            return [[(node.value or "", get_effective_filter(node))]]

        operands: list[QueryNode] = [
            child for child in node.children if child.node_type in (NodeType.TERM, NodeType.GROUP)
        ]
        connectors: list[str] = [
            child.value
            for child in node.children
            if child.node_type == NodeType.CONNECTOR and child.value
        ]

        if not operands:
            return [[]]

        current = self._to_dnf_with_filters(operands[0])
        for index, connector in enumerate(connectors, start=1):
            right = self._to_dnf_with_filters(operands[index])
            if connector == "or":
                current = current + right
            elif connector == "and":
                # Cartesian product between left/right clauses keeps all valid
                # conjunction combinations when collapsing `(A OR B) AND (C OR D)`.
                product: list[list[tuple[str, str]]] = []
                for left_clause, right_clause in itertools.product(current, right):
                    product.append(left_clause + right_clause)
                current = product
            else:
                # `AND NOT` cannot be safely distributed into independent field
                # filters for this fallback path, so keep terms together.
                return [
                    [
                        (
                            term_node.value or "",
                            get_effective_filter(term_node),
                        )
                        for term_node in iter_term_nodes(node)
                    ]
                ]
        return current

    def _build_queries_from_clauses(
        self,
        clauses: list[list[tuple[str, str]]],
        raw_query: str,
    ) -> list[Query]:
        """Build Query objects from DNF clauses.

        Parameters
        ----------
        clauses : list[list[tuple[str, str]]]
            DNF clauses.
        raw_query : str
            Original query string.

        Returns
        -------
        list[Query]
            Expanded queries.
        """
        queries: list[Query] = []
        for clause in clauses:
            children: list[QueryNode] = []
            for index, (term, filter_code) in enumerate(clause):
                if index > 0:
                    children.append(QueryNode(node_type=NodeType.CONNECTOR, value="and"))
                children.append(
                    QueryNode(node_type=NodeType.TERM, value=term, filter_code=filter_code)
                )
            queries.append(
                Query(
                    raw_query=raw_query, root=QueryNode(node_type=NodeType.ROOT, children=children)
                )
            )
        return queries
