"""Tests for PubMed query builder."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from findpapers.core.query import Query
from findpapers.query.builders.pubmed import PubmedQueryBuilder


def test_pubmed_rejects_question_wildcard(parse_and_propagate: Callable[[str], Query]) -> None:
    """PubMed rejects '?' wildcard."""
    query = parse_and_propagate("[data?]")
    result = PubmedQueryBuilder().validate_query(query)
    assert result.is_valid is False


def test_pubmed_converts_tiabskey(parse_and_propagate: Callable[[str], Query]) -> None:
    """PubMed expands tiabskey into tiab OR mh."""
    query = parse_and_propagate("tiabskey[heart attack]")
    converted = PubmedQueryBuilder().convert_query(query)
    assert '"heart attack"[tiab]' in converted
    assert '"heart attack"[mh]' in converted


def test_pubmed_rejects_short_asterisk_wildcard(
    parse_and_propagate: Callable[[str], Query],
) -> None:
    """PubMed requires at least 4 characters before wildcard '*' character."""
    query = parse_and_propagate("[abc*]")
    result = PubmedQueryBuilder().validate_query(query)
    assert result.is_valid is False


@pytest.mark.parametrize(
    ("query_string", "expected_fragment"),
    [
        ("ti[cancer]", '"cancer"[ti]'),
        ("abs[cancer]", '"cancer"[ab]'),
        ("key[cancer]", '"cancer"[mh]'),
        ("au[cancer]", '"cancer"[au]'),
        ("src[cancer]", '"cancer"[journal]'),
        ("aff[cancer]", '"cancer"[ad]'),
        ("tiabs[cancer]", '"cancer"[tiab]'),
        ("tiabskey[cancer]", '("cancer"[tiab] OR "cancer"[mh])'),
    ],
)
def test_pubmed_supports_all_filters_in_conversion(
    parse_and_propagate: Callable[[str], Query],
    query_string: str,
    expected_fragment: str,
) -> None:
    """PubMed conversion supports each documented filter code."""
    query = parse_and_propagate(query_string)
    result = PubmedQueryBuilder().validate_query(query)
    assert result.is_valid is True
    converted = PubmedQueryBuilder().convert_query(query)
    assert expected_fragment in converted
