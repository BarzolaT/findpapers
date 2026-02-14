"""Tests for OpenAlex query builder."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from findpapers.core.query import Query
from findpapers.query.builders.openalex import OpenAlexQueryBuilder


def test_openalex_rejects_wildcards(parse_and_propagate: Callable[[str], Query]) -> None:
    """OpenAlex rejects wildcard terms."""
    query = parse_and_propagate("[gene*]")
    result = OpenAlexQueryBuilder().validate_query(query)
    assert result.is_valid is False


def test_openalex_default_filter_mapping(parse_and_propagate: Callable[[str], Query]) -> None:
    """OpenAlex default mapping uses title_and_abstract search field."""
    query = parse_and_propagate("[federated learning]")
    converted = OpenAlexQueryBuilder().convert_query(query)
    assert "title_and_abstract.search.no_stem" in converted["filter"]


def test_openalex_or_uses_search_mode(parse_and_propagate: Callable[[str], Query]) -> None:
    """OpenAlex uses boolean search mode for OR expressions."""
    query = parse_and_propagate("[alpha] OR [beta]")
    converted = OpenAlexQueryBuilder().convert_query(query)
    assert "search" in converted
    assert "OR" in converted["search"]


def test_openalex_expands_tiabskey(parse_and_propagate: Callable[[str], Query]) -> None:
    """OpenAlex expands tiabskey into multiple queries."""
    query = parse_and_propagate("tiabskey[cancer]")
    expanded = OpenAlexQueryBuilder().expand_query(query)
    assert len(expanded) == 2


def test_openalex_build_execution_plan_tracks_combination(
    parse_and_propagate: Callable[[str], Query],
) -> None:
    """OpenAlex execution plan exposes how expanded results must be merged."""
    query = parse_and_propagate("tiabskey[cancer]")
    plan = OpenAlexQueryBuilder().build_execution_plan(query)
    assert len(plan.request_payloads) == 2
    assert plan.combination_expression == "q0 OR q1"


@pytest.mark.parametrize(
    ("query_string", "expected_fragment"),
    [
        ("ti[cancer]", "title.search.no_stem:cancer"),
        ("abs[cancer]", "abstract.search.no_stem:cancer"),
        ("key[cancer]", "concepts.display_name:cancer"),
        ("au[cancer]", "authorships.author.display_name.search:cancer"),
        ("pu[cancer]", "primary_location.source.display_name.search:cancer"),
        ("af[cancer]", "authorships.institutions.display_name.search:cancer"),
        ("tiabs[cancer]", "title_and_abstract.search.no_stem:cancer"),
        ("tiabskey[cancer]", "search:cancer"),
    ],
)
def test_openalex_supports_all_filters_in_conversion(
    parse_and_propagate: Callable[[str], Query],
    query_string: str,
    expected_fragment: str,
) -> None:
    """OpenAlex conversion supports each documented filter code."""
    query = parse_and_propagate(query_string)
    result = OpenAlexQueryBuilder().validate_query(query)
    assert result.is_valid is True
    converted = OpenAlexQueryBuilder().convert_query(query)
    assert "filter" in converted
    assert expected_fragment in converted["filter"]
