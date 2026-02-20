"""Tests for Scopus query builder."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from findpapers.core.query import Query
from findpapers.query.builders.scopus import ScopusQueryBuilder


def test_scopus_conversion(parse_and_propagate: Callable[[str], Query]) -> None:
    """Scopus maps filters and connectors to native syntax."""
    query = parse_and_propagate("ti[transformer] AND abs[attention]")
    converted = ScopusQueryBuilder().convert_query(query)
    assert converted == 'TITLE("transformer") AND ABS("attention")'


def test_scopus_rejects_hyphen_wildcard_combination(
    parse_and_propagate: Callable[[str], Query],
) -> None:
    """Scopus rejects wildcard terms combined with hyphen or dot."""
    query = parse_and_propagate("[art-*]")
    result = ScopusQueryBuilder().validate_query(query)
    assert result.is_valid is False


@pytest.mark.parametrize(
    ("query_string", "expected_expression"),
    [
        ("ti[graph]", 'TITLE("graph")'),
        ("abs[graph]", 'ABS("graph")'),
        ("key[graph]", 'KEY("graph")'),
        ("au[graph]", 'AUTH("graph")'),
        ("src[graph]", 'SRCTITLE("graph")'),
        ("aff[graph]", 'AFFIL("graph")'),
        ("tiabs[graph]", 'TITLE-ABS("graph")'),
        ("tiabskey[graph]", 'TITLE-ABS-KEY("graph")'),
    ],
)
def test_scopus_supports_all_filters_in_conversion(
    parse_and_propagate: Callable[[str], Query],
    query_string: str,
    expected_expression: str,
) -> None:
    """Scopus conversion supports each documented filter code."""
    query = parse_and_propagate(query_string)
    result = ScopusQueryBuilder().validate_query(query)
    assert result.is_valid is True
    converted = ScopusQueryBuilder().convert_query(query)
    assert converted == expected_expression
