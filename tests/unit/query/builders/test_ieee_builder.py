"""Tests for IEEE query builder."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from findpapers.core.query import Query
from findpapers.query.builders.ieee import IEEEQueryBuilder


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
        ("pu[quantum]", {"publication_title": "quantum"}),
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
