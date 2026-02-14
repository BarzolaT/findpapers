"""Shared helper functions for query builders."""

from __future__ import annotations

from collections.abc import Callable

from findpapers.core.query import NodeType, Query, QueryNode

DEFAULT_FILTER_CODE = "tiabs"


def get_effective_filter(node: QueryNode) -> str:
    """Return effective filter code for a query node.

    Parameters
    ----------
    node : QueryNode
        Query node to inspect.

    Returns
    -------
    str
        Explicit filter when present, otherwise inherited filter, otherwise default.
    """
    return node.filter_code or node.inherited_filter_code or DEFAULT_FILTER_CODE


def iter_term_nodes(node: QueryNode) -> list[QueryNode]:
    """Return all term nodes in a subtree.

    Parameters
    ----------
    node : QueryNode
        Root node of a subtree.

    Returns
    -------
    list[QueryNode]
        Term nodes found recursively.
    """
    terms: list[QueryNode] = []
    if node.node_type == NodeType.TERM:
        terms.append(node)
    for child in node.children:
        terms.extend(iter_term_nodes(child))
    return terms


def iter_connectors(node: QueryNode) -> list[str]:
    """Return connector values in a subtree.

    Parameters
    ----------
    node : QueryNode
        Root node of a subtree.

    Returns
    -------
    list[str]
        Connector values in lowercase.
    """
    values: list[str] = []
    if node.node_type == NodeType.CONNECTOR and node.value:
        values.append(node.value)
    for child in node.children:
        values.extend(iter_connectors(child))
    return values


def has_wildcard(term: str) -> bool:
    """Check if term contains wildcard characters.

    Parameters
    ----------
    term : str
        Input term.

    Returns
    -------
    bool
        True when term contains `*` or `?`.
    """
    return "*" in term or "?" in term


def quote_term(term: str) -> str:
    """Quote term preserving wildcard characters.

    Parameters
    ----------
    term : str
        Input term.

    Returns
    -------
    str
        Quoted term when it contains spaces, otherwise unchanged.
    """
    if " " in term:
        return f'"{term}"'
    return term


def convert_expression(
    node: QueryNode,
    term_converter: Callable[[QueryNode], str],
    connector_map: dict[str, str],
) -> str:
    """Convert query tree node to infix expression.

    Parameters
    ----------
    node : QueryNode
        Node to convert.
    term_converter : Callable[[QueryNode], str]
        Function that converts TERM nodes.
    connector_map : dict[str, str]
        Connector mapping for target database.

    Returns
    -------
    str
        Converted expression.
    """
    if node.node_type == NodeType.TERM:
        return term_converter(node)

    parts: list[str] = []
    for child in node.children:
        if child.node_type == NodeType.CONNECTOR and child.value:
            parts.append(connector_map[child.value])
            continue

        converted = convert_expression(child, term_converter, connector_map)
        if child.node_type == NodeType.GROUP:
            parts.append(f"({converted})")
        else:
            parts.append(converted)

    return " ".join(parts)


def clone_query(query: Query) -> Query:
    """Clone a query object using dict serialization.

    Parameters
    ----------
    query : Query
        Query object.

    Returns
    -------
    Query
        Deep-copied query.
    """
    return Query.from_dict(query.to_dict())
