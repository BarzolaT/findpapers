"""Shared fixtures for searcher unit tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from findpapers.query.parser import QueryParser
from findpapers.query.propagator import FilterPropagator

DATA_DIR = Path(__file__).parent.parent.parent / "data"

_parser = QueryParser()
_propagator = FilterPropagator()


def _parse(query_str: str):
    """Parse and propagate a query string."""
    q = _parser.parse(query_str)
    return _propagator.propagate(q)


@pytest.fixture
def simple_query():
    """Simple AND query using default filter."""
    return _parse("[machine learning] AND [deep learning]")


@pytest.fixture
def tiabs_query():
    """Query with explicit tiabs filter."""
    return _parse("tiabs[machine learning] AND tiabs[deep learning]")


@pytest.fixture
def or_query():
    """Simple OR query."""
    return _parse("[machine learning] OR [deep learning]")


@pytest.fixture
def and_not_query():
    """Query with AND NOT connector."""
    return _parse("[machine learning] AND NOT [reinforcement learning]")


@pytest.fixture
def ti_query():
    """Query using title-only filter."""
    return _parse("ti[machine learning] AND ti[deep learning]")


@pytest.fixture
def key_query():
    """Query using keywords filter (key)."""
    return _parse("key[machine learning]")


@pytest.fixture
def wildcard_query():
    """Query with wildcard term."""
    return _parse("[machine*]")


@pytest.fixture
def mock_response():
    """Factory for creating mock HTTP responses."""

    def _make(json_data=None, text=None, status_code=200):
        mock = MagicMock()
        mock.status_code = status_code
        mock.text = text or ""
        if json_data is not None:
            mock.json.return_value = json_data
        return mock

    return _make


@pytest.fixture
def arxiv_sample_xml():
    """Read arXiv sample XML response from test data."""
    return (DATA_DIR / "arxiv" / "sample_response.xml").read_text(encoding="utf-8")


@pytest.fixture
def pubmed_esearch_json():
    """Read PubMed esearch sample JSON response."""
    return json.loads((DATA_DIR / "pubmed" / "esearch_response.json").read_text())


@pytest.fixture
def pubmed_efetch_xml():
    """Read PubMed efetch sample XML response."""
    return (DATA_DIR / "pubmed" / "efetch_response.xml").read_text(encoding="utf-8")


@pytest.fixture
def ieee_sample_json():
    """Read IEEE sample JSON response."""
    return json.loads((DATA_DIR / "ieee" / "sample_response.json").read_text())


@pytest.fixture
def scopus_sample_json():
    """Read Scopus sample JSON response."""
    return json.loads((DATA_DIR / "scopus" / "sample_response.json").read_text())


@pytest.fixture
def openalex_sample_json():
    """Read OpenAlex sample JSON response."""
    return json.loads((DATA_DIR / "openalex" / "sample_response.json").read_text())


@pytest.fixture
def crossref_sample_json():
    """Read CrossRef sample responses (dict keyed by DOI)."""
    return json.loads((DATA_DIR / "crossref" / "sample_responses.json").read_text(encoding="utf-8"))


@pytest.fixture
def semantic_scholar_sample_json():
    """Read Semantic Scholar bulk search sample JSON response."""
    return json.loads((DATA_DIR / "semanticscholar" / "bulk_search_response.json").read_text())
