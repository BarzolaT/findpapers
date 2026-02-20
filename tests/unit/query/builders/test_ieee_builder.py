"""Tests for IEEE query builder."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from findpapers.core.query import FilterCode, NodeType, Query, QueryNode
from findpapers.query.builders.ieee import IEEEQueryBuilder


def _make_term_query(term: str, filter_code: FilterCode | None = None) -> Query:
    """Build a minimal single-term Query bypassing the global validator."""
    term_node = QueryNode(node_type=NodeType.TERM, value=term, filter_code=filter_code)
    root = QueryNode(node_type=NodeType.ROOT, children=[term_node])
    return Query(raw_query=f"[{term}]", root=root)


def test_ieee_single_term_field_payload(parse_and_propagate: Callable[[str], Query]) -> None:
    """IEEE returns dedicated field parameter for simple queries."""
    query = parse_and_propagate("ti[graph neural networks]")
    converted = IEEEQueryBuilder().convert_query(query)
    assert converted == {"article_title": "graph neural networks"}


@pytest.mark.parametrize(
    ("query_string", "expected_payload"),
    [
        ("ti[quantum]", {"article_title": "quantum"}),
        ("abs[quantum]", {"abstract": "quantum"}),
        ("key[quantum]", {"index_terms": "quantum"}),
        ("au[quantum]", {"author": "quantum"}),
        ("src[quantum]", {"publication_title": "quantum"}),
        ("af[quantum]", {"affiliation": "quantum"}),
    ],
)
def test_ieee_supports_direct_field_filters(
    parse_and_propagate: Callable[[str], Query],
    query_string: str,
    expected_payload: dict[str, str],
) -> None:
    """IEEE maps direct single-term filters to dedicated API params."""
    query = parse_and_propagate(query_string)
    result = IEEEQueryBuilder().validate_query(query)
    assert result.is_valid is True
    converted = IEEEQueryBuilder().convert_query(query)
    assert converted == expected_payload


def test_ieee_supports_tiabs_filter(parse_and_propagate: Callable[[str], Query]) -> None:
    """IEEE tiabs filter maps to title-or-abstract expression."""
    query = parse_and_propagate("tiabs[quantum]")
    result = IEEEQueryBuilder().validate_query(query)
    assert result.is_valid is True
    converted = IEEEQueryBuilder().convert_query(query)
    assert "querytext" in converted
    assert '"Article Title":"quantum"' in converted["querytext"]
    assert '"Abstract":"quantum"' in converted["querytext"]


def test_ieee_supports_tiabskey_filter(parse_and_propagate: Callable[[str], Query]) -> None:
    """IEEE tiabskey filter maps to title-or-abstract-or-key expression."""
    query = parse_and_propagate("tiabskey[quantum]")
    result = IEEEQueryBuilder().validate_query(query)
    assert result.is_valid is True
    converted = IEEEQueryBuilder().convert_query(query)
    assert "querytext" in converted
    assert '"Article Title":"quantum"' in converted["querytext"]
    assert '"Abstract":"quantum"' in converted["querytext"]
    assert '"Index Terms":"quantum"' in converted["querytext"]


def test_ieee_rejects_question_mark_wildcard() -> None:
    """IEEE rejects queries that contain the '?' wildcard."""
    # Bypass global validator to inject a '?' term directly into the builder
    query = _make_term_query("mach?ne")
    result = IEEEQueryBuilder().validate_query(query)
    assert result.is_valid is False
    assert "?" in (result.error_message or "")


def test_ieee_rejects_short_star_wildcard_prefix() -> None:
    """IEEE rejects '*' wildcard when the prefix has fewer than 3 characters."""
    # Bypass global validator to inject a short-prefix wildcard directly
    query = _make_term_query("al*")
    result = IEEEQueryBuilder().validate_query(query)
    assert result.is_valid is False
    assert "*" in (result.error_message or "")


def test_ieee_accepts_long_enough_star_wildcard(
    parse_and_propagate: Callable[[str], Query],
) -> None:
    """IEEE accepts '*' wildcard when the prefix has at least 3 characters."""
    query = parse_and_propagate("[neural*]")
    result = IEEEQueryBuilder().validate_query(query)
    assert result.is_valid is True


@pytest.mark.parametrize(
    ("query_string", "expected_field"),
    [
        ("abs[a] AND abs[b]", '"Abstract"'),
        ("key[a] AND key[b]", '"Index Terms"'),
        ("au[a] AND au[b]", '"Authors"'),
        ("src[a] AND src[b]", '"Publication Title"'),
        ("af[a] AND af[b]", '"Affiliation"'),
        ("tiabs[a] AND tiabs[b]", '"Article Title"'),
    ],
)
def test_ieee_multi_term_convert_query_field_mapping(
    parse_and_propagate: Callable[[str], Query],
    query_string: str,
    expected_field: str,
) -> None:
    """IEEE multi-term queries use the querytext field with proper field expressions."""
    query = parse_and_propagate(query_string)
    converted = IEEEQueryBuilder().convert_query(query)
    assert "querytext" in converted
    assert expected_field in converted["querytext"]


def test_ieee_multi_term_tiabskey_includes_all_fields(
    parse_and_propagate: Callable[[str], Query],
) -> None:
    """IEEE multi-term tiabskey maps to title, abstract, and index-terms expression."""
    query = parse_and_propagate("tiabskey[a] AND tiabskey[b]")
    converted = IEEEQueryBuilder().convert_query(query)
    assert "querytext" in converted
    expr = converted["querytext"]
    assert '"Article Title"' in expr
    assert '"Abstract"' in expr
    assert '"Index Terms"' in expr


def test_ieee_expand_query_returns_single_query(
    parse_and_propagate: Callable[[str], Query],
) -> None:
    """expand_query returns a single-element list (no expansion for IEEE)."""
    query = parse_and_propagate("[deep learning] AND [neural networks]")
    expanded = IEEEQueryBuilder().expand_query(query)
    assert len(expanded) == 1
    assert expanded[0] is query


def test_ieee_single_term_tiabs_payload(parse_and_propagate: Callable[[str], Query]) -> None:
    """_single_term_payload for tiabs returns querytext with title-or-abstract expression."""
    query = parse_and_propagate("tiabs[quantum]")
    converted = IEEEQueryBuilder().convert_query(query)
    assert "querytext" in converted
    assert '"Article Title"' in converted["querytext"]
    assert '"Abstract"' in converted["querytext"]
    # Should NOT contain Index Terms for tiabs
    assert '"Index Terms"' not in converted["querytext"]
