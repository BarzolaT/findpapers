"""Tests for Semantic Scholar query builder."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from findpapers.core.query import Query
from findpapers.query.builders.semantic_scholar import SemanticScholarQueryBuilder


def test_semantic_scholar_rejects_key_filter(
    parse_and_propagate: Callable[[str], Query],
) -> None:
    """Semantic Scholar does not support key filter."""
    query = parse_and_propagate("key[vision]")
    result = SemanticScholarQueryBuilder().validate_query(query)
    assert result.is_valid is False


def test_semantic_scholar_rejects_publication_filter(
    parse_and_propagate: Callable[[str], Query],
) -> None:
    """Semantic Scholar builder does not support publication field filter."""
    query = parse_and_propagate("src[nature]")
    result = SemanticScholarQueryBuilder().validate_query(query)
    assert result.is_valid is False


def test_semantic_scholar_rejects_author_filter(
    parse_and_propagate: Callable[[str], Query],
) -> None:
    """Semantic Scholar bulk search does not support author field filter in builder."""
    query = parse_and_propagate("au[smith]")
    result = SemanticScholarQueryBuilder().validate_query(query)
    assert result.is_valid is False


def test_semantic_scholar_allows_prefix_wildcard(
    parse_and_propagate: Callable[[str], Query],
) -> None:
    """Semantic Scholar bulk search supports '*' prefix wildcard usage."""
    query = parse_and_propagate("[mach*]")
    result = SemanticScholarQueryBuilder().validate_query(query)
    assert result.is_valid is True


@pytest.mark.parametrize(
    ("query_string", "expected_payload"),
    [
        ("tiabs[protein folding]", {"query": '"protein folding"'}),
    ],
)
def test_semantic_scholar_supports_all_filters_in_conversion(
    parse_and_propagate: Callable[[str], Query],
    query_string: str,
    expected_payload: dict[str, str],
) -> None:
    """Semantic Scholar conversion supports all currently allowed filters."""
    query = parse_and_propagate(query_string)
    result = SemanticScholarQueryBuilder().validate_query(query)
    assert result.is_valid is True
    converted = SemanticScholarQueryBuilder().convert_query(query)
    assert converted == expected_payload


def test_semantic_scholar_preserves_boolean_connectors(
    parse_and_propagate: Callable[[str], Query],
) -> None:
    """Semantic Scholar conversion keeps + and | operators for bulk syntax."""
    query = parse_and_propagate("[machine learning] OR [healthcare]")
    converted = SemanticScholarQueryBuilder().convert_query(query)
    assert converted == {"query": '"machine learning" | healthcare'}
