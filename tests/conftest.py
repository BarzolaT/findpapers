"""Pytest configuration and shared fixtures for tests."""

from __future__ import annotations

import datetime
from collections.abc import Callable

import pytest

from findpapers.core.author import Author
from findpapers.core.paper import Paper, PaperType
from findpapers.core.source import Source

# Type alias for the paper factory callable.
PaperFactory = Callable[..., Paper]


@pytest.fixture
def sample_query_string() -> str:
    """Return a simple query string for testing."""
    return "[machine learning] AND [deep learning]"


@pytest.fixture
def complex_query_string() -> str:
    """Return a complex query string for testing."""
    return "[happiness] AND ([joy] OR [peace of mind]) AND NOT [stressful]"


def _create_paper(
    title: str = "Test Paper",
    abstract: str = "An abstract.",
    doi: str | None = None,
    url: str | None = "http://example.com/paper",
    pdf_url: str | None = None,
    source: Source | None = None,
    authors: list[Author] | None = None,
    publication_date: datetime.date | None = None,
    paper_type: PaperType | None = None,
    keywords: set[str] | None = None,
    citations: int | None = None,
) -> Paper:
    """Create a minimal :class:`Paper` for testing.

    Parameters
    ----------
    title : str
        Paper title.
    abstract : str
        Paper abstract text.
    doi : str | None
        Paper DOI.
    url : str | None
        URL linking to the paper.
    pdf_url : str | None
        Direct PDF URL.
    source : Source | None
        Publication source (journal, conference, etc.).
    authors : list[Author] | None
        List of authors; defaults to a single "Test Author".
    publication_date : datetime.date | None
        Publication date; defaults to 2024-01-01.
    paper_type : PaperType | None
        Paper type classification.
    keywords : set[str] | None
        Paper keywords.
    citations : int | None
        Citation count.

    Returns
    -------
    Paper
        A paper instance with sensible test defaults.
    """
    return Paper(
        title=title,
        abstract=abstract,
        authors=authors if authors is not None else [Author(name="Test Author")],
        source=source,
        publication_date=publication_date or datetime.date(2024, 1, 1),
        url=url,
        pdf_url=pdf_url,
        doi=doi,
        paper_type=paper_type,
        keywords=keywords,
        citations=citations,
    )


@pytest.fixture
def make_paper() -> PaperFactory:
    """Fixture providing a factory to create :class:`Paper` instances.

    Returns
    -------
    PaperFactory
        A callable with the same signature as :func:`_create_paper`.

    Examples
    --------
    >>> def test_something(make_paper):
    ...     paper = make_paper("My Title", doi="10.1000/test")
    """
    return _create_paper
