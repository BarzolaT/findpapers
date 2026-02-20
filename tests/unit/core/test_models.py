"""Tests for Paper, Publication, and Search models."""

import csv
import datetime
import json

import pytest

from findpapers.core.paper import Paper, PaperType, _is_preprint_doi, _merge_doi
from findpapers.core.publication import Publication
from findpapers.core.search import Search


def test_paper_type_normalization():
    """Test that paper_type is normalized correctly from a string value."""
    paper = Paper(
        title="A Paper",
        abstract="",
        authors=[],
        publication=None,
        publication_date=datetime.date.today(),
    )
    paper.paper_type = "ARTICLE"  # mixed-case string
    assert paper.paper_type == PaperType.ARTICLE

    paper.paper_type = "unknown_type"
    assert paper.paper_type is None


def test_publication_merge():
    """Test merging two publications."""
    base = Publication(title="A", publisher=None)
    incoming = Publication(title="Longer", publisher="Pub")
    base.merge(incoming)
    assert base.title == "Longer"
    assert base.publisher == "Pub"


def test_publication_to_from_dict():
    """Test publication serialization and deserialization."""
    data = {
        "title": "T",
        "isbn": "1",
        "issn": "2",
        "publisher": "Pub",
        "is_potentially_predatory": True,
    }
    publication = Publication.from_dict(data)
    assert Publication.to_dict(publication)["title"] == "T"


def test_paper_requires_title():
    """Test that paper requires a title."""
    with pytest.raises(ValueError):
        Paper(
            title="",
            abstract="",
            authors=[],
            publication=None,
            publication_date=datetime.date.today(),
        )


def test_paper_url_and_pdf_url():
    """Test that paper accepts url and pdf_url."""
    paper = Paper(
        title="Title",
        abstract="Abstract",
        authors=["A"],
        publication=None,
        publication_date=None,
        url="https://example.com/paper",
        pdf_url="https://example.com/paper.pdf",
        doi="10.123/abc",
    )
    assert paper.url == "https://example.com/paper"
    assert paper.pdf_url == "https://example.com/paper.pdf"
    assert paper.doi == "10.123/abc"


def test_paper_add_and_merge():
    """Test adding metadata and merging papers."""
    publication = Publication(title="Journal")
    paper = Paper(
        title="Title",
        abstract="",
        authors=["A"],
        publication=publication,
        publication_date=datetime.date(2020, 1, 1),
        url="https://example.com",
    )
    paper.add_database("arxiv")
    assert "arxiv" in paper.databases
    assert paper.url == "https://example.com"

    incoming = Paper(
        title="Longer Title",
        abstract="Abstract",
        authors=["A", "B"],
        publication=Publication(title="Journal", publisher="Pub"),
        publication_date=datetime.date(2020, 1, 1),
        url="https://longer-example.com",
        pdf_url="https://example.com/paper.pdf",
        citations=5,
    )
    paper.merge(incoming)
    assert paper.title == "Longer Title"
    assert paper.abstract == "Abstract"
    assert paper.citations == 5
    assert paper.url == "https://longer-example.com"
    assert paper.pdf_url == "https://example.com/paper.pdf"


class TestIsPreprintDoi:
    """Unit tests for the _is_preprint_doi helper."""

    def test_arxiv_doi_recognised_as_preprint(self):
        assert _is_preprint_doi("10.48550/arxiv.1706.03762") is True

    def test_biorxiv_doi_recognised_as_preprint(self):
        assert _is_preprint_doi("10.1101/2021.05.01.442244") is True

    def test_ssrn_doi_recognised_as_preprint(self):
        assert _is_preprint_doi("10.2139/ssrn.3844763") is True

    def test_publisher_doi_not_preprint(self):
        assert _is_preprint_doi("10.5555/3295222.3295349") is False

    def test_nature_doi_not_preprint(self):
        assert _is_preprint_doi("10.1038/s41586-021-03819-2") is False

    def test_case_insensitive(self):
        assert _is_preprint_doi("10.48550/ARXIV.1706.03762") is True


class TestMergeDoi:
    """Unit tests for the _merge_doi helper."""

    def test_preprint_base_publisher_incoming_returns_publisher(self):
        result = _merge_doi("10.48550/arxiv.1706.03762", "10.5555/3295222.3295349")
        assert result == "10.5555/3295222.3295349"

    def test_publisher_base_preprint_incoming_returns_base(self):
        result = _merge_doi("10.5555/3295222.3295349", "10.48550/arxiv.1706.03762")
        assert result == "10.5555/3295222.3295349"

    def test_both_preprint_returns_longer(self):
        a = "10.48550/arxiv.1706.03762"
        b = "10.1101/2021.05.01.442244"
        result = _merge_doi(a, b)
        # falls back to merge_value → the longer string
        assert result == max(a, b, key=len)

    def test_both_publisher_returns_longer(self):
        a = "10.1038/s41586-021-03819-2"
        b = "10.5555/3295222.3295349"
        result = _merge_doi(a, b)
        assert result == max(a, b, key=len)

    def test_base_none_returns_incoming(self):
        assert _merge_doi(None, "10.5555/x") == "10.5555/x"

    def test_incoming_none_returns_base(self):
        assert _merge_doi("10.5555/x", None) == "10.5555/x"

    def test_both_none_returns_none(self):
        assert _merge_doi(None, None) is None


def test_paper_merge_prefers_publisher_doi_over_preprint_doi():
    """Paper.merge keeps the publisher DOI when one copy has an arXiv DOI."""
    base = Paper(
        title="Attention is All You Need",
        abstract="",
        authors=["Vaswani"],
        publication=None,
        publication_date=datetime.date(2017, 6, 12),
        doi="10.48550/arxiv.1706.03762",
    )
    incoming = Paper(
        title="Attention is All You Need",
        abstract="The dominant sequence...",
        authors=["Vaswani"],
        publication=None,
        publication_date=datetime.date(2017, 6, 12),
        doi="10.5555/3295222.3295349",
    )
    base.merge(incoming)
    assert base.doi == "10.5555/3295222.3295349"


def test_paper_merge_prefers_publisher_doi_when_preprint_is_incoming():
    """Publisher DOI on base is preserved even when the incoming has a preprint DOI."""
    base = Paper(
        title="Attention is All You Need",
        abstract="The dominant sequence...",
        authors=["Vaswani"],
        publication=None,
        publication_date=datetime.date(2017, 6, 12),
        doi="10.5555/3295222.3295349",
    )
    incoming = Paper(
        title="Attention is All You Need",
        abstract="",
        authors=["Vaswani"],
        publication=None,
        publication_date=datetime.date(2017, 6, 12),
        doi="10.48550/arxiv.1706.03762",
    )
    base.merge(incoming)
    assert base.doi == "10.5555/3295222.3295349"


def test_search_add_paper():
    """Test adding paper to search results."""
    search = Search(query="q", databases=["arxiv"])
    paper = Paper(
        title="Title",
        abstract="Abstract",
        authors=["Author"],
        publication=None,
        publication_date=None,
    )
    search.add_paper(paper)
    assert len(search.papers) == 1
    assert search.papers[0].title == "Title"


def _make_search_with_paper() -> Search:
    """Return a Search with one Article paper for export tests."""
    paper = Paper(
        title="Export Test Paper",
        abstract="Abstract text.",
        authors=["Author One"],
        publication=Publication(title="Test Journal"),
        publication_date=datetime.date(2023, 1, 1),
    )
    paper.paper_type = PaperType.ARTICLE
    search = Search(query="[export]", databases=["arxiv"])
    search.add_paper(paper)
    return search


def test_search_to_json_creates_file(tmp_path):
    """Search.to_json() writes a valid JSON file with a 'papers' key."""
    path = str(tmp_path / "out.json")
    _make_search_with_paper().to_json(path)
    with open(path) as f:
        data = json.load(f)
    assert "papers" in data
    assert len(data["papers"]) == 1


def test_search_to_csv_creates_file(tmp_path):
    """Search.to_csv() writes a CSV file with at least one data row."""
    path = str(tmp_path / "out.csv")
    _make_search_with_paper().to_csv(path)
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) >= 1


def test_search_to_bibtex_creates_file(tmp_path):
    """Search.to_bibtex() writes a BibTeX file containing at least one entry."""
    path = str(tmp_path / "out.bib")
    _make_search_with_paper().to_bibtex(path)
    content = open(path).read()
    assert "@" in content
