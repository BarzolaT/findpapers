"""Unit tests for search-result export utilities."""

from __future__ import annotations

import csv
import datetime
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from findpapers.core.author import Author
from findpapers.core.paper import Paper, PaperType
from findpapers.core.source import Source
from findpapers.utils.export import (
    bibtex_how_published,
    bibtex_note,
    citation_key_for,
    csv_columns,
    export_to_bibtex,
    export_to_csv,
    export_to_json,
    paper_to_bibtex,
    paper_to_csv_row,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def journal_publication() -> Source:
    """Return a journal publication."""
    return Source(
        title="Nature Machine Intelligence",
        issn="2522-5839",
        publisher="Springer Nature",
    )


@pytest.fixture()
def conference_publication() -> Source:
    """Return a conference proceedings publication."""
    return Source(
        title="NeurIPS 2023",
        isbn="978-0-000-00000-0",
        publisher="Curran Associates",
    )


@pytest.fixture()
def minimal_paper() -> Paper:
    """Return a paper with the minimum required fields."""
    return Paper(
        title="Minimal Paper",
        abstract="An abstract.",
        authors=[Author(name="Alice, A.")],
        source=None,
        publication_date=None,
    )


@pytest.fixture()
def full_paper(journal_publication: Source) -> Paper:
    """Return a paper with all fields populated."""
    return Paper(
        title="Deep Learning Survey",
        abstract="A survey on deep learning techniques.",
        authors=[Author(name="LeCun, Y."), Author(name="Bengio, Y."), Author(name="Hinton, G.")],
        source=journal_publication,
        publication_date=datetime.date(2022, 6, 15),
        url="https://example.com/paper",
        pdf_url="https://example.com/paper.pdf",
        doi="10.1234/example.doi",
        citations=500,
        keywords={"neural networks", "deep learning", "AI"},
        comments="Highly cited review.",
        number_of_pages=42,
        pages="1-42",
        databases={"arxiv", "semantic_scholar"},
        paper_type=PaperType.ARTICLE,
    )


@pytest.fixture()
def conference_paper(conference_publication: Source) -> Paper:
    """Return a paper in a conference proceedings."""
    return Paper(
        title="Attention is All You Need",
        abstract="Transformers intro.",
        authors=[Author(name="Vaswani, A.")],
        source=conference_publication,
        publication_date=datetime.date(2017, 12, 1),
        url="https://arxiv.org/abs/1706.03762",
        doi="10.48550/arXiv.1706.03762",
        databases={"arxiv"},
        paper_type=PaperType.INPROCEEDINGS,
    )


@pytest.fixture()
def mock_search(full_paper: Paper, minimal_paper: Paper) -> MagicMock:
    """Return a mock Search with two papers."""
    search = MagicMock()
    search.papers = [full_paper, minimal_paper]
    search.to_dict.return_value = {"papers": [{"title": "Deep Learning Survey"}]}
    return search


# ---------------------------------------------------------------------------
# csv_columns
# ---------------------------------------------------------------------------


class TestCsvColumns:
    """Tests for csv_columns()."""

    def test_returns_list_of_strings(self) -> None:
        """Result is a list of non-empty strings."""
        cols = csv_columns()
        assert isinstance(cols, list)
        assert all(isinstance(c, str) and c for c in cols)

    def test_contains_key_paper_fields(self) -> None:
        """Key paper fields are present."""
        cols = csv_columns()
        for field in ("title", "abstract", "authors", "doi", "databases"):
            assert field in cols

    def test_contains_source_fields(self) -> None:
        """Source-prefixed fields are present."""
        cols = csv_columns()
        for field in ("source_title", "source_issn", "source_publisher"):
            assert field in cols

    def test_no_duplicates(self) -> None:
        """Column list has no duplicate names."""
        cols = csv_columns()
        assert len(cols) == len(set(cols))


# ---------------------------------------------------------------------------
# paper_to_csv_row
# ---------------------------------------------------------------------------


class TestPaperToCsvRow:
    """Tests for paper_to_csv_row()."""

    def test_full_paper_row_keys_match_columns(self, full_paper: Paper) -> None:
        """Row keys match csv_columns output."""
        row = paper_to_csv_row(full_paper)
        assert set(row.keys()) == set(csv_columns())

    def test_full_paper_values(self, full_paper: Paper) -> None:
        """Core values are correctly serialised."""
        row = paper_to_csv_row(full_paper)
        assert row["title"] == "Deep Learning Survey"
        assert row["doi"] == "10.1234/example.doi"
        assert row["citations"] == 500
        # Authors joined with '; '
        authors_str = str(row["authors"])
        assert "LeCun, Y." in authors_str
        assert "; " in authors_str
        # Keywords are sorted and ; separated
        assert row["keywords"] == "AI; deep learning; neural networks"
        # Databases sorted
        assert row["databases"] == "arxiv; semantic_scholar"
        # Date serialised as ISO
        assert row["publication_date"] == "2022-06-15"

    def test_source_fields_present(self, full_paper: Paper) -> None:
        """Source-prefixed fields carry the source data."""
        row = paper_to_csv_row(full_paper)
        assert row["source_title"] == "Nature Machine Intelligence"
        assert row["source_issn"] == "2522-5839"
        assert row["source_publisher"] == "Springer Nature"

    def test_minimal_paper_nulls(self, minimal_paper: Paper) -> None:
        """Minimal paper produces None for optional fields."""
        row = paper_to_csv_row(minimal_paper)
        assert row["doi"] is None
        assert row["publication_date"] is None
        assert row["source_title"] is None

    def test_no_source(self, minimal_paper: Paper) -> None:
        """Paper without source has None for all source_* fields."""
        row = paper_to_csv_row(minimal_paper)
        source_fields = [k for k in row if k.startswith("source_")]
        assert all(row[f] is None for f in source_fields)


# ---------------------------------------------------------------------------
# citation_key_for
# ---------------------------------------------------------------------------


class TestCitationKeyFor:
    """Tests for citation_key_for()."""

    def test_basic_key(self, full_paper: Paper) -> None:
        """Key includes first author, year, and first title word."""
        key = citation_key_for(full_paper)
        assert "lecun" in key.lower()
        assert "2022" in key
        assert "deep" in key.lower()

    def test_no_author_fallback(self) -> None:
        """Paper with no authors uses 'unknown' as author part."""
        paper = Paper(
            title="Some Title",
            abstract="",
            authors=[],
            source=None,
            publication_date=datetime.date(2020, 1, 1),
        )
        key = citation_key_for(paper)
        assert "unknown" in key

    def test_no_date_fallback(self) -> None:
        """Paper with no date uses 'XXXX' as year part."""
        paper = Paper(
            title="Some Title",
            abstract="",
            authors=[Author(name="Smith, J.")],
            source=None,
            publication_date=None,
        )
        key = citation_key_for(paper)
        assert "XXXX" in key

    def test_only_alphanumeric(self) -> None:
        """Key contains only alphanumeric characters."""
        paper = Paper(
            title="A-Title: With, Punctuation!",
            abstract="",
            authors=[Author(name="O'Brien, T.")],
            source=None,
            publication_date=datetime.date(2021, 3, 10),
        )
        key = citation_key_for(paper)
        assert key.isalnum()


# ---------------------------------------------------------------------------
# bibtex_note
# ---------------------------------------------------------------------------


class TestBibtexNote:
    """Tests for bibtex_note()."""

    def test_with_all_fields(self, full_paper: Paper) -> None:
        """Note contains URL, date, and comments when all are present."""
        note = bibtex_note(full_paper)
        assert "https://example.com/paper" in note
        assert "2022" in note
        assert "Highly cited review." in note

    def test_without_url(self) -> None:
        """Note omits URL part when paper.url is None."""
        paper = Paper(
            title="T",
            abstract="",
            authors=[],
            source=None,
            publication_date=datetime.date(2020, 1, 1),
            url=None,
        )
        note = bibtex_note(paper)
        assert "Available at" not in note

    def test_empty_for_no_content(self) -> None:
        """Note is empty string when URL and date are both absent."""
        paper = Paper(
            title="T",
            abstract="",
            authors=[],
            source=None,
            publication_date=None,
            url=None,
        )
        assert bibtex_note(paper) == ""


# ---------------------------------------------------------------------------
# bibtex_how_published
# ---------------------------------------------------------------------------


class TestBibtexHowPublished:
    """Tests for bibtex_how_published()."""

    def test_with_url_and_date(self) -> None:
        """howPublished contains URL and formatted date."""
        paper = Paper(
            title="T",
            abstract="",
            authors=[],
            source=None,
            publication_date=datetime.date(2023, 5, 20),
            url="https://example.org",
        )
        result = bibtex_how_published(paper)
        assert "https://example.org" in result
        assert "2023/05/20" in result

    def test_returns_empty_without_url(self) -> None:
        """Returns empty string when URL is missing."""
        paper = Paper(
            title="T",
            abstract="",
            authors=[],
            source=None,
            publication_date=datetime.date(2023, 1, 1),
            url=None,
        )
        assert bibtex_how_published(paper) == ""

    def test_returns_empty_without_date(self) -> None:
        """Returns empty string when date is missing."""
        paper = Paper(
            title="T",
            abstract="",
            authors=[],
            source=None,
            publication_date=None,
            url="https://example.org",
        )
        assert bibtex_how_published(paper) == ""


# ---------------------------------------------------------------------------
# paper_to_bibtex
# ---------------------------------------------------------------------------


class TestPaperToBibtex:
    """Tests for paper_to_bibtex()."""

    def test_article_type(self, full_paper: Paper) -> None:
        """Journal paper produces @article entry."""
        entry = paper_to_bibtex(full_paper)
        assert entry.startswith("@article{")

    def test_inproceedings_type(self, conference_paper: Paper) -> None:
        """Conference paper produces @inproceedings entry."""
        entry = paper_to_bibtex(conference_paper)
        assert entry.startswith("@inproceedings{")

    def test_unpublished_type(self, minimal_paper: Paper) -> None:
        """Paper without a paper_type produces @misc entry."""
        entry = paper_to_bibtex(minimal_paper)
        assert entry.startswith("@misc{")

    def test_contains_title(self, full_paper: Paper) -> None:
        """Entry contains the paper title."""
        entry = paper_to_bibtex(full_paper)
        assert "Deep Learning Survey" in entry

    def test_contains_authors(self, full_paper: Paper) -> None:
        """Entry contains authors joined with ' and '."""
        entry = paper_to_bibtex(full_paper)
        assert "LeCun, Y. and Bengio, Y. and Hinton, G." in entry

    def test_contains_year(self, full_paper: Paper) -> None:
        """Entry contains the publication year."""
        entry = paper_to_bibtex(full_paper)
        assert "year = {2022}" in entry

    def test_contains_journal(self, full_paper: Paper) -> None:
        """Journal entry contains journal field."""
        entry = paper_to_bibtex(full_paper)
        assert "journal = {Nature Machine Intelligence}" in entry

    def test_contains_booktitle(self, conference_paper: Paper) -> None:
        """Conference entry contains booktitle field."""
        entry = paper_to_bibtex(conference_paper)
        assert "booktitle = {NeurIPS 2023}" in entry

    def test_unpublished_for_none_paper_type(self) -> None:
        """A paper with no paper_type falls back to @misc."""
        pub = Source(title="Workshop")
        paper = Paper(
            title="W Paper",
            abstract="",
            authors=[Author(name="X, Y.")],
            source=pub,
            publication_date=datetime.date(2021, 1, 1),
            paper_type=None,
        )
        entry = paper_to_bibtex(paper)
        assert entry.startswith("@misc{")

    def test_entry_ends_with_closing_brace(self, full_paper: Paper) -> None:
        """BibTeX entry ends with closing brace."""
        entry = paper_to_bibtex(full_paper)
        assert entry.rstrip().endswith("}")


# ---------------------------------------------------------------------------
# export_to_json
# ---------------------------------------------------------------------------


class TestExportToJson:
    """Tests for export_to_json()."""

    def test_creates_file(self, mock_search: MagicMock) -> None:
        """File is created at the specified path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "out.json")
            export_to_json(mock_search, path)
            assert Path(path).exists()

    def test_valid_json(self, mock_search: MagicMock) -> None:
        """Created file contains valid JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "out.json")
            export_to_json(mock_search, path)
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            assert isinstance(data, dict)

    def test_delegates_to_search_to_dict(self, mock_search: MagicMock) -> None:
        """search.to_dict() is called to serialise the search."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "out.json")
            export_to_json(mock_search, path)
            mock_search.to_dict.assert_called_once()


# ---------------------------------------------------------------------------
# export_to_csv
# ---------------------------------------------------------------------------


class TestExportToCsv:
    """Tests for export_to_csv()."""

    def test_creates_file(self, mock_search: MagicMock) -> None:
        """File is created at the specified path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "out.csv")
            export_to_csv(mock_search, path)
            assert Path(path).exists()

    def test_header_matches_columns(self, mock_search: MagicMock) -> None:
        """CSV header matches csv_columns() output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "out.csv")
            export_to_csv(mock_search, path)
            with open(path, encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                assert list(reader.fieldnames or []) == csv_columns()

    def test_row_count(self, mock_search: MagicMock) -> None:
        """CSV has one data row per paper."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "out.csv")
            export_to_csv(mock_search, path)
            with open(path, encoding="utf-8", newline="") as fh:
                rows = list(csv.DictReader(fh))
            assert len(rows) == len(mock_search.papers)

    def test_empty_paper_list(self) -> None:
        """Empty paper list produces only header row."""
        search = MagicMock()
        search.papers = []
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "out.csv")
            export_to_csv(search, path)
            with open(path, encoding="utf-8", newline="") as fh:
                rows = list(csv.DictReader(fh))
            assert rows == []


# ---------------------------------------------------------------------------
# export_to_bibtex
# ---------------------------------------------------------------------------


class TestExportToBibtex:
    """Tests for export_to_bibtex()."""

    def test_creates_file(self, mock_search: MagicMock) -> None:
        """File is created at the specified path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "out.bib")
            export_to_bibtex(mock_search, path)
            assert Path(path).exists()

    def test_file_contains_bibtex_entries(self, mock_search: MagicMock) -> None:
        """File starts with a BibTeX entry marker."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "out.bib")
            export_to_bibtex(mock_search, path)
            content = Path(path).read_text(encoding="utf-8")
            assert "@" in content

    def test_entry_count(self, mock_search: MagicMock) -> None:
        """Number of '@' entry markers equals the number of papers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "out.bib")
            export_to_bibtex(mock_search, path)
            content = Path(path).read_text(encoding="utf-8")
            entries = [line for line in content.splitlines() if line.startswith("@")]
            assert len(entries) == len(mock_search.papers)

    def test_empty_paper_list(self) -> None:
        """Empty paper list produces an empty file."""
        search = MagicMock()
        search.papers = []
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "out.bib")
            export_to_bibtex(search, path)
            content = Path(path).read_text(encoding="utf-8")
            assert content == ""
