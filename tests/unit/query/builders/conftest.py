"""Shared fixtures for query builders tests."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from findpapers.core.query import Query
from findpapers.query.parser import QueryParser
from findpapers.query.propagator import FilterPropagator
from findpapers.query.validator import QueryValidator


@pytest.fixture
def parser() -> QueryParser:
    """Return parser fixture.

    Returns
    -------
    QueryParser
        Query parser.
    """
    return QueryParser()


@pytest.fixture
def validator() -> QueryValidator:
    """Return validator fixture.

    Returns
    -------
    QueryValidator
        Query validator.
    """
    return QueryValidator()


@pytest.fixture
def propagator() -> FilterPropagator:
    """Return propagator fixture.

    Returns
    -------
    FilterPropagator
        Filter propagator.
    """
    return FilterPropagator()


@pytest.fixture
def parse_and_propagate(
    parser: QueryParser,
    validator: QueryValidator,
    propagator: FilterPropagator,
) -> Callable[[str], Query]:
    """Return helper that validates, parses, and propagates a query.

    Parameters
    ----------
    parser : QueryParser
        Query parser.
    validator : QueryValidator
        Query validator.
    propagator : FilterPropagator
        Filter propagator.

    Returns
    -------
    Callable[[str], Query]
        Function that transforms a raw query string into a propagated query tree.
    """

    def _parse_and_propagate(query_string: str) -> Query:
        validator.validate(query_string)
        query = parser.parse(query_string)
        return propagator.propagate(query)

    return _parse_and_propagate
