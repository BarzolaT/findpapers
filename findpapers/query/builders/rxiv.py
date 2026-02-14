"""Shared query builder logic for bioRxiv and medRxiv."""

from __future__ import annotations

import itertools
import logging

from findpapers.core.query import NodeType, Query, QueryNode
from findpapers.query.builder import QueryBuilder, QueryValidationResult
from findpapers.query.builders.common import (
    get_effective_filter,
    has_wildcard,
    iter_connectors,
    iter_term_nodes,
)

LOGGER = logging.getLogger(__name__)


class RxivQueryBuilder(QueryBuilder):
    """Base class for Rxiv family query builders."""

    QUERY_COMBINATIONS_WARNING_THRESHOLD = 20

    def validate_query(self, query: Query) -> QueryValidationResult:
        """Validate whether Rxiv endpoints support this query.

        Parameters
        ----------
        query : Query
            Query to validate.

        Returns
        -------
        QueryValidationResult
            Validation result.
        """
        for connector in iter_connectors(query.root):
            if connector == "and not":
                return QueryValidationResult(
                    is_valid=False,
                    error_message="Operator 'AND NOT' is not supported by Rxiv APIs.",
                )

        for term in iter_term_nodes(query.root):
            filter_code = get_effective_filter(term)
            if not self.supports_filter(filter_code):
                return QueryValidationResult(
                    is_valid=False,
                    error_message=f"Filter '{filter_code}' is not supported by Rxiv APIs.",
                )
            if term.value and has_wildcard(term.value):
                return QueryValidationResult(
                    is_valid=False,
                    error_message="Wildcards are not supported by Rxiv APIs.",
                )

        return QueryValidationResult(is_valid=True)

    def convert_query(self, query: Query) -> dict:
        """Convert a simple Rxiv query into API parameters.

        Parameters
        ----------
        query : Query
            Query to convert.

        Returns
        -------
        dict
            Rxiv search parameters.
        """
        terms = [term.value for term in iter_term_nodes(query.root) if term.value]
        connectors = set(iter_connectors(query.root))
        if connectors == {"or"}:
            return {"field": "abstract_title", "match": "match-any", "terms": terms}
        return {"field": "abstract_title", "match": "match-all", "terms": terms}

    def preprocess_terms(self, query: Query) -> Query:
        """Return query unchanged for Rxiv APIs.

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
        """Check whether Rxiv supports a filter code.

        Parameters
        ----------
        filter_code : str
            Filter code.

        Returns
        -------
        bool
            True for supported filters.
        """
        return filter_code == "tiabs"

    def expand_query(self, query: Query) -> list[Query]:
        """Expand query into conjunction combinations for Rxiv limitations.

        Parameters
        ----------
        query : Query
            Query to expand.

        Returns
        -------
        list[Query]
            Expanded simple queries.
        """
        # DNF guarantees a top-level OR of conjunctions. Each conjunction can be executed
        # as an independent query and later combined by union in the searcher.
        dnf_clauses = self._to_dnf(query.root)
        expanded = [self._clause_to_query(clause, query.raw_query) for clause in dnf_clauses]
        if len(expanded) > self.QUERY_COMBINATIONS_WARNING_THRESHOLD:
            LOGGER.warning(
                "The query generated %s combinations for %s. Search will run but may be slow.",
                len(expanded),
                self.__class__.__name__,
            )
        return expanded

    def _build_combination_expression(self, expanded_queries: list[Query]) -> str:
        """Build result-combination expression for expanded rxiv queries.

        Parameters
        ----------
        expanded_queries : list[Query]
            Queries returned by ``expand_query``.

        Returns
        -------
        str
            Union expression because DNF expansion for rxiv decomposes OR branches.
        """
        if not expanded_queries:
            return ""
        if len(expanded_queries) == 1:
            return "q0"
        return " OR ".join(f"q{index}" for index in range(len(expanded_queries)))

    def _to_dnf(self, node: QueryNode) -> list[list[str]]:
        """Convert query subtree to disjunctive normal form term clauses.

        Parameters
        ----------
        node : QueryNode
            Node to normalize.

        Returns
        -------
        list[list[str]]
            DNF clauses where each clause is a list of AND terms.
        """
        if node.node_type == NodeType.TERM:
            return [[node.value or ""]]

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

        current = self._to_dnf(operands[0])
        for index, connector in enumerate(connectors, start=1):
            right = self._to_dnf(operands[index])
            if connector == "or":
                current = current + right
            else:
                product = []
                for left_clause, right_clause in itertools.product(current, right):
                    product.append(left_clause + right_clause)
                current = product
        return current

    def _clause_to_query(self, clause: list[str], raw_query: str) -> Query:
        """Build a Query object from a DNF clause.

        Parameters
        ----------
        clause : list[str]
            List of terms that must be combined with AND.
        raw_query : str
            Original query string for reference.

        Returns
        -------
        Query
            Expanded simple query.
        """
        children: list[QueryNode] = []
        for index, term in enumerate(clause):
            if index > 0:
                children.append(QueryNode(node_type=NodeType.CONNECTOR, value="and"))
            children.append(QueryNode(node_type=NodeType.TERM, value=term))
        return Query(
            raw_query=raw_query, root=QueryNode(node_type=NodeType.ROOT, children=children)
        )
