"""Tests for arXiv query builder."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from findpapers.core.query import Query
from findpapers.query.builders.arxiv import ArxivQueryBuilder


def test_arxiv_hyphen_preprocess(parse_and_propagate: Callable[[str], Query]) -> None:
    """arXiv replaces hyphen by space before conversion."""
    query = parse_and_propagate("[covid-19]")
    builder = ArxivQueryBuilder()
    preprocessed = builder.preprocess_terms(query)
    assert preprocessed.root.children[0].value == "covid 19"


def test_arxiv_conversion_default_filter(parse_and_propagate: Callable[[str], Query]) -> None:
    """arXiv default filter expands to title OR abstract."""
    query = parse_and_propagate("[machine learning]")
    converted = ArxivQueryBuilder().convert_query(query)
    assert 'ti:"machine learning"' in converted
    assert 'abs:"machine learning"' in converted


def test_arxiv_build_execution_plan_single_query(
    parse_and_propagate: Callable[[str], Query],
) -> None:
    """Single-query plans expose one payload and identity combination expression."""
    query = parse_and_propagate("[foundation model]")
    plan = ArxivQueryBuilder().build_execution_plan(query)
    assert len(plan.request_payloads) == 1
    assert plan.combination_expression == "q0"


@pytest.mark.parametrize(
    ("query_string", "expected_fragment"),
    [
        ("ti[graph]", "ti:graph"),
        ("abs[graph]", "abs:graph"),
        ("au[smith]", "au:smith"),
        ("tiabs[graph]", "%28ti:graph OR abs:graph%29"),
    ],
)
def test_arxiv_supports_all_filters_in_conversion(
    parse_and_propagate: Callable[[str], Query],
    query_string: str,
    expected_fragment: str,
) -> None:
    """arXiv conversion supports each documented filter code."""
    query = parse_and_propagate(query_string)
    result = ArxivQueryBuilder().validate_query(query)
    assert result.is_valid is True
    converted = ArxivQueryBuilder().convert_query(query)
    assert expected_fragment in converted
