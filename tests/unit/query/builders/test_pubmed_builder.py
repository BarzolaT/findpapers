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
    """PubMed expands tiabskey into tiab OR ot."""
    query = parse_and_propagate("tiabskey[heart attack]")
    converted = PubmedQueryBuilder().convert_query(query)
    assert '"heart attack"[tiab]' in converted
    assert '"heart attack"[ot]' in converted


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
        ("key[cancer]", '"cancer"[ot]'),
        ("au[cancer]", '"cancer"[au]'),
        ("src[cancer]", '"cancer"[journal]'),
        ("aff[cancer]", '"cancer"[ad]'),
        ("tiabs[cancer]", '"cancer"[tiab]'),
        ("tiabskey[cancer]", '("cancer"[tiab] OR "cancer"[ot])'),
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


def test_pubmed_group_filter_optimization(
    parse_and_propagate: Callable[[str], Query],
) -> None:
    """PubMed wraps group at tag level when all children share the filter."""
    query = parse_and_propagate("ti([cancer] OR [tumor])")
    converted = PubmedQueryBuilder().convert_query(query)
    assert converted == '("cancer" OR "tumor")[ti]'


def test_pubmed_group_filter_optimization_tiabs(
    parse_and_propagate: Callable[[str], Query],
) -> None:
    """PubMed optimises tiabs group with native [tiab] postfix tag."""
    query = parse_and_propagate("tiabs([a] OR [b])")
    converted = PubmedQueryBuilder().convert_query(query)
    assert converted == '("a" OR "b")[tiab]'


def test_pubmed_group_filter_no_optimization_on_tiabskey(
    parse_and_propagate: Callable[[str], Query],
) -> None:
    """PubMed falls back to per-term for tiabskey (compound: tiab + ot)."""
    query = parse_and_propagate("tiabskey([a] OR [b])")
    converted = PubmedQueryBuilder().convert_query(query)
    # Per-term expansion: each term gets (tiab OR ot)
    assert '"a"[tiab]' in converted
    assert '"b"[tiab]' in converted


def test_pubmed_group_filter_no_optimization_on_mixed(
    parse_and_propagate: Callable[[str], Query],
) -> None:
    """PubMed falls back to per-term when children use different filters."""
    query = parse_and_propagate("ti([a] OR abs[b])")
    converted = PubmedQueryBuilder().convert_query(query)
    assert '"a"[ti]' in converted
    assert '"b"[ab]' in converted


def test_pubmed_nested_group_optimization(
    parse_and_propagate: Callable[[str], Query],
) -> None:
    """PubMed optimises nested groups independently."""
    query = parse_and_propagate("ti([a] AND abs([b] OR [c]))")
    converted = PubmedQueryBuilder().convert_query(query)
    assert '"a"[ti]' in converted
    assert '("b" OR "c")[ab]' in converted
