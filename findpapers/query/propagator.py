"""Filter propagation logic for query nodes."""

from __future__ import annotations

from typing import Optional

from findpapers.core.query import NodeType, Query, QueryNode


class FilterPropagator:
    """Propagates filter specifiers through query tree nodes.

    This class handles the logic of inheriting filter codes from parent nodes
    to child nodes in the query tree, following the rule: innermost filter wins.
    """

    def propagate(self, query: Query) -> Query:
        """Propagate filter specifiers through the query tree.

        This modifies the query in-place by updating inherited_filter_code
        and children_match_filter attributes on all nodes.

        Parameters
        ----------
        query : Query
            The query whose tree needs filter propagation.

        Returns
        -------
        Query
            The same query with updated filter inheritance.
        """
        query.root.propagate_filters()  # type: ignore[attr-defined]
        return query


def propagate_filters(node: QueryNode, parent_filter: Optional[str] = None) -> None:
    """Propagate filter specifier from parent nodes to children.

    This function calculates inherited_filter_code and children_match_filter for all nodes:
    1. inherited_filter_code: The effective filter (explicit or inherited from parent)
    2. children_match_filter: For GROUP nodes, whether all children use the group's filter
    3. filter_code: Preserved as-is from the original query (not modified)

    The innermost group always wins - filter closest to a term is applied.

    This is added as a method to QueryNode in the propagator module.

    Parameters
    ----------
    node : QueryNode
        The node to propagate filters from.
    parent_filter : str | None
        Filter inherited from the parent node.
    """
    # Determine inherited filter: explicit filter overrides inherited one
    node.inherited_filter_code = node.filter_code if node.filter_code is not None else parent_filter

    if node.node_type == NodeType.TERM:
        # Terminal node: inherited_filter_code is already set
        pass
    elif node.node_type in (NodeType.ROOT, NodeType.GROUP):
        # Propagate to children
        for child in node.children:
            propagate_filters(child, node.inherited_filter_code)  # type: ignore[arg-type]

        # For GROUP nodes, check if all children match the group's filter
        if node.node_type == NodeType.GROUP:
            node.children_match_filter = _check_children_match_filter(node)


def _check_children_match_filter(node: QueryNode) -> bool:
    """Check if all children use the same filter as this GROUP node.

    Parameters
    ----------
    node : QueryNode
        The GROUP node to check.

    Returns
    -------
    bool
        True if all children (recursively) use the group's inherited_filter_code.
    """
    group_filter = node.inherited_filter_code

    for child in node.children:
        if child.node_type == NodeType.CONNECTOR:
            continue
        elif child.node_type == NodeType.TERM:
            if child.inherited_filter_code != group_filter:
                return False
        elif child.node_type == NodeType.GROUP:
            # Check if nested group and its children use the same filter
            if not _check_node_uses_filter(child, group_filter):
                return False

    return True


def _check_node_uses_filter(node: QueryNode, target_filter: Optional[str]) -> bool:
    """Recursively check if a node and all its children use the target filter.

    Parameters
    ----------
    node : QueryNode
        The node to check.
    target_filter : str | None
        The filter to match against.

    Returns
    -------
    bool
        True if the node and all descendants use the target filter.
    """
    if node.node_type == NodeType.CONNECTOR:
        return True
    elif node.node_type == NodeType.TERM:
        return node.inherited_filter_code == target_filter
    elif node.node_type in (NodeType.GROUP, NodeType.ROOT):
        for child in node.children:
            if not _check_node_uses_filter(child, target_filter):
                return False
        return True
    return True


# Monkey-patch the propagate_filters method onto QueryNode
QueryNode.propagate_filters = propagate_filters  # type: ignore[attr-defined]
