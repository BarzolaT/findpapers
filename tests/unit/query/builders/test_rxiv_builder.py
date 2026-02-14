"""Tests for bioRxiv/medRxiv shared query builder behavior."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from findpapers.core.query import Query
from findpapers.query.builders.biorxiv import BiorxivQueryBuilder
from findpapers.query.builders.medrxiv import MedrxivQueryBuilder
from findpapers.query.builders.rxiv import RxivQueryBuilder


def test_rxiv_rejects_and_not(parse_and_propagate: Callable[[str], Query]) -> None:
    """Rxiv builders reject AND NOT operator."""
    query = parse_and_propagate("[a] AND NOT [b]")
    result = BiorxivQueryBuilder().validate_query(query)
    assert result.is_valid is False


def test_rxiv_expands_or_and_groups(parse_and_propagate: Callable[[str], Query]) -> None:
    """Rxiv builders expand OR groups joined by AND into combinations."""
    query = parse_and_propagate("([a] OR [b]) AND ([c] OR [d])")
    expanded = BiorxivQueryBuilder().expand_query(query)
    assert len(expanded) == 4


def test_rxiv_build_execution_plan_uses_union_expression(
    parse_and_propagate: Callable[[str], Query],
) -> None:
    """Rxiv execution plan combines expanded queries using OR (set union)."""
    query = parse_and_propagate("([a] OR [b]) AND ([c] OR [d])")
    plan = BiorxivQueryBuilder().build_execution_plan(query)
    assert len(plan.request_payloads) == 4
    assert plan.combination_expression == "q0 OR q1 OR q2 OR q3"


@pytest.mark.parametrize(
    "builder_class",
    [BiorxivQueryBuilder, MedrxivQueryBuilder],
)
def test_rxiv_supports_tiabs_filter_only(
    parse_and_propagate: Callable[[str], Query],
    builder_class: type[RxivQueryBuilder],
) -> None:
    """Rxiv builders validate tiabs and reject other filter codes."""
    builder = builder_class()

    supported_query = parse_and_propagate("tiabs[graph]")
    supported_result = builder.validate_query(supported_query)
    assert supported_result.is_valid is True

    unsupported_query = parse_and_propagate("ti[graph]")
    unsupported_result = builder.validate_query(unsupported_query)
    assert unsupported_result.is_valid is False


@pytest.mark.parametrize(
    "builder_class",
    [BiorxivQueryBuilder, MedrxivQueryBuilder],
)
def test_rxiv_tiabs_conversion_payload(
    parse_and_propagate: Callable[[str], Query],
    builder_class: type[RxivQueryBuilder],
) -> None:
    """Rxiv builders convert tiabs query to abstract_title payload."""
    query = parse_and_propagate("tiabs[graph]")
    converted = builder_class().convert_query(query)
    assert converted == {
        "field": "abstract_title",
        "match": "match-all",
        "terms": ["graph"],
    }
