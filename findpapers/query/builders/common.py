"""Shared helper functions for query builders."""

from __future__ import annotations

from collections.abc import Callable

from findpapers.core.query import ConnectorType, FilterCode, NodeType, Query, QueryNode

DEFAULT_FILTER_CODE: FilterCode = FilterCode.TITLE_ABSTRACT


def get_effective_filter(node: QueryNode) -> FilterCode:
    """Return effective filter code for a query node.

    Parameters
    ----------
    node : QueryNode
        Query node to inspect.

    Returns
    -------
    FilterCode
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


def iter_connectors(node: QueryNode) -> list[ConnectorType]:
    """Return connector values in a subtree.

    Parameters
    ----------
    node : QueryNode
        Root node of a subtree.

    Returns
    -------
    list[ConnectorType]
        Connector enum members in tree order.
    """
    values: list[ConnectorType] = []
    if node.node_type == NodeType.CONNECTOR and node.value:
        values.append(ConnectorType(node.value))
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
    connector_map: dict[ConnectorType, str],
    *,
    plain_term_converter: Callable[[QueryNode], str] | None = None,
    optimized_group_converter: Callable[[QueryNode, str], str | None] | None = None,
) -> str:
    """Convert query tree node to infix expression.

    When ``plain_term_converter`` and ``optimized_group_converter`` are provided,
    GROUP nodes whose ``children_match_filter`` is ``True`` are converted in a
    compact form: the children are rendered without per-term filter prefixes and
    the whole group is wrapped by a single filter call via
    ``optimized_group_converter``.  If that callback returns ``None`` the group
    falls back to the standard per-term conversion.

    Parameters
    ----------
    node : QueryNode
        Node to convert.
    term_converter : Callable[[QueryNode], str]
        Function that converts TERM nodes (including filter prefix).
    connector_map : dict[ConnectorType, str]
        Connector mapping for target database.
    plain_term_converter : Callable[[QueryNode], str] | None
        Function that converts TERM nodes **without** a filter prefix.
        Required for the group-level filter optimisation.
    optimized_group_converter : Callable[[QueryNode, str], str | None] | None
        Receives ``(group_node, plain_inner_expression)`` and returns a
        compact expression with the filter applied at the group level, or
        ``None`` to fall back to per-term conversion.

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
            parts.append(connector_map[ConnectorType(child.value)])
            continue

        # Optimisation: apply filter at group level when all children share it
        if (
            child.node_type == NodeType.GROUP
            and child.children_match_filter
            and plain_term_converter is not None
            and optimized_group_converter is not None
        ):
            inner_plain = convert_expression(child, plain_term_converter, connector_map)
            optimized = optimized_group_converter(child, inner_plain)
            if optimized is not None:
                parts.append(optimized)
                continue
            # Fall back to per-term conversion below

        converted = convert_expression(
            child,
            term_converter,
            connector_map,
            plain_term_converter=plain_term_converter,
            optimized_group_converter=optimized_group_converter,
        )
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
