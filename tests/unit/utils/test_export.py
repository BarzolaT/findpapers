"""Unit tests for export utilities."""

from __future__ import annotations

import datetime
import json
import tempfile
from pathlib import Path

import pytest

from findpapers.core.author import Author
from findpapers.core.citation_graph import CitationGraph
from findpapers.core.paper import Paper, PaperType
from findpapers.core.search_result import SearchResult
from findpapers.core.source import Source, SourceType
from findpapers.exceptions import ExportError
from findpapers.utils.export import (
    _extract_papers,
    _serialize_to_dict,
    bibtex_how_published,
    bibtex_note,
    citation_key_for,
    export_to_bibtex,
    export_to_json,
    load_from_json,
    paper_to_bibtex,
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
        page_count=42,
        page_range="1-42",
        databases={"arxiv", "semantic_scholar"},
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
    )


@pytest.fixture()
def sample_search(full_paper: Paper, minimal_paper: Paper) -> SearchResult:
    """Return a SearchResult with two papers."""
    search = SearchResult(query="[deep learning]", databases=["arxiv"])
    search.add_paper(full_paper)
    search.add_paper(minimal_paper)
    return search


@pytest.fixture()
def sample_graph(full_paper: Paper, minimal_paper: Paper) -> CitationGraph:
    """Return a CitationGraph with two papers and one edge."""
    full_paper.doi = "10.1000/full"
    minimal_paper.doi = "10.1000/minimal"
    graph = CitationGraph(seed_papers=[full_paper], depth=1, direction="backward")
    graph.add_paper(minimal_paper, depth=1)
    graph.add_edge(full_paper, minimal_paper)
    return graph


# ---------------------------------------------------------------------------
# _extract_papers
# ---------------------------------------------------------------------------


class TestExtractPapers:
    """Tests for _extract_papers()."""

    def test_from_list(self, full_paper: Paper, minimal_paper: Paper) -> None:
        """Extracts papers from a plain list."""
        papers = [full_paper, minimal_paper]
        assert _extract_papers(papers) is papers

    def test_from_search_result(self, sample_search: SearchResult) -> None:
        """Extracts papers from a SearchResult."""
        papers = _extract_papers(sample_search)
        assert len(papers) == 2

    def test_from_citation_graph(self, sample_graph: CitationGraph) -> None:
        """Extracts papers from a CitationGraph."""
        papers = _extract_papers(sample_graph)
        assert len(papers) == 2

    def test_raises_for_unsupported_type(self) -> None:
        """Raises ExportError for unsupported input."""
        with pytest.raises(ExportError, match="Expected"):
            _extract_papers("not a valid input")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _serialize_to_dict
# ---------------------------------------------------------------------------


class TestSerializeToDict:
    """Tests for _serialize_to_dict()."""

    def test_search_result_has_type(self, sample_search: SearchResult) -> None:
        """SearchResult serialization includes type discriminator."""
        result = _serialize_to_dict(sample_search)
        assert result["type"] == "search_result"
        assert "papers" in result

    def test_citation_graph_has_type(self, sample_graph: CitationGraph) -> None:
        """CitationGraph serialization includes type discriminator."""
        result = _serialize_to_dict(sample_graph)
        assert result["type"] == "citation_graph"
        assert "nodes" in result

    def test_paper_list_has_type(self, full_paper: Paper) -> None:
        """Paper list serialization includes type discriminator."""
        result = _serialize_to_dict([full_paper])
        assert result["type"] == "paper_list"
        assert len(result["papers"]) == 1

    def test_raises_for_unsupported_type(self) -> None:
        """Raises ExportError for unsupported input."""
        with pytest.raises(ExportError, match="Expected"):
            _serialize_to_dict("not valid")  # type: ignore[arg-type]


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

    def test_article_type_from_journal_source_without_paper_type(self) -> None:
        """Paper with JOURNAL source but no paper_type falls back to @misc."""
        pub = Source(title="Nature", source_type=SourceType.JOURNAL)
        paper = Paper(
            title="T",
            abstract="",
            authors=[Author(name="X, Y.")],
            source=pub,
            publication_date=datetime.date(2021, 1, 1),
        )
        entry = paper_to_bibtex(paper)
        assert entry.startswith("@misc{")

    def test_inproceedings_type_from_conference_source_without_paper_type(self) -> None:
        """Paper with CONFERENCE source but no paper_type falls back to @misc."""
        pub = Source(title="NeurIPS", source_type=SourceType.CONFERENCE)
        paper = Paper(
            title="T",
            abstract="",
            authors=[Author(name="X, Y.")],
            source=pub,
            publication_date=datetime.date(2021, 1, 1),
        )
        entry = paper_to_bibtex(paper)
        assert entry.startswith("@misc{")

    def test_inbook_type_from_book_source_without_paper_type(self) -> None:
        """Paper with BOOK source but no paper_type falls back to @misc."""
        pub = Source(title="Advances", source_type=SourceType.BOOK)
        paper = Paper(
            title="T",
            abstract="",
            authors=[Author(name="X, Y.")],
            source=pub,
            publication_date=datetime.date(2021, 1, 1),
        )
        entry = paper_to_bibtex(paper)
        assert entry.startswith("@misc{")

    def test_misc_type_without_source_type(self, full_paper: Paper) -> None:
        """Paper without source_type still produces @misc entry."""
        assert full_paper.source is not None
        full_paper.source.source_type = None
        entry = paper_to_bibtex(full_paper)
        assert entry.startswith("@misc{")

    def test_misc_type_without_source(self, minimal_paper: Paper) -> None:
        """Paper without source produces @misc entry."""
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

    def test_contains_publisher(self, full_paper: Paper) -> None:
        """Entry contains publisher field when available."""
        entry = paper_to_bibtex(full_paper)
        assert "publisher = {Springer Nature}" in entry

    def test_contains_howpublished(self, conference_paper: Paper) -> None:
        """Entry contains howpublished field when URL and date are present."""
        entry = paper_to_bibtex(conference_paper)
        assert "howpublished" in entry

    def test_repository_source_type_falls_back_to_misc(self) -> None:
        """A paper with REPOSITORY source_type falls back to @misc."""
        pub = Source(title="arXiv", source_type=SourceType.REPOSITORY)
        paper = Paper(
            title="W Paper",
            abstract="",
            authors=[Author(name="X, Y.")],
            source=pub,
            publication_date=datetime.date(2021, 1, 1),
        )
        entry = paper_to_bibtex(paper)
        assert entry.startswith("@misc{")

    def test_entry_ends_with_closing_brace(self, full_paper: Paper) -> None:
        """BibTeX entry ends with closing brace."""
        entry = paper_to_bibtex(full_paper)
        assert entry.rstrip().endswith("}")

    def test_paper_type_overrides_source_type(self) -> None:
        """paper_type takes precedence over source_type for BibTeX entry type."""
        pub = Source(title="Nature", source_type=SourceType.JOURNAL)
        paper = Paper(
            title="T",
            abstract="",
            authors=[Author(name="X, Y.")],
            source=pub,
            publication_date=datetime.date(2021, 1, 1),
            paper_type=PaperType.TECHREPORT,
        )
        entry = paper_to_bibtex(paper)
        assert entry.startswith("@techreport{")

    def test_paper_type_article_produces_at_article(self) -> None:
        """Paper with ARTICLE paper_type produces @article entry."""
        paper = Paper(
            title="T",
            abstract="",
            authors=[Author(name="X, Y.")],
            source=None,
            publication_date=datetime.date(2021, 1, 1),
            paper_type=PaperType.ARTICLE,
        )
        entry = paper_to_bibtex(paper)
        assert entry.startswith("@article{")

    def test_paper_type_unpublished_produces_at_unpublished(self) -> None:
        """Paper with UNPUBLISHED paper_type produces @unpublished entry."""
        paper = Paper(
            title="T",
            abstract="",
            authors=[Author(name="X, Y.")],
            source=None,
            publication_date=datetime.date(2021, 1, 1),
            paper_type=PaperType.UNPUBLISHED,
        )
        entry = paper_to_bibtex(paper)
        assert entry.startswith("@unpublished{")

    def test_paper_type_none_falls_back_to_misc(self) -> None:
        """Without paper_type, BibTeX type defaults to @misc."""
        pub = Source(title="NeurIPS", source_type=SourceType.CONFERENCE)
        paper = Paper(
            title="T",
            abstract="",
            authors=[Author(name="X, Y.")],
            source=pub,
            publication_date=datetime.date(2021, 1, 1),
        )
        entry = paper_to_bibtex(paper)
        assert entry.startswith("@misc{")


# ---------------------------------------------------------------------------
# export_to_json
# ---------------------------------------------------------------------------


class TestExportToJson:
    """Tests for export_to_json()."""

    def test_creates_file_from_search(self, sample_search: SearchResult) -> None:
        """File is created from a SearchResult."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "out.json")
            export_to_json(sample_search, path)
            assert Path(path).exists()

    def test_creates_file_from_graph(self, sample_graph: CitationGraph) -> None:
        """File is created from a CitationGraph."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "out.json")
            export_to_json(sample_graph, path)
            assert Path(path).exists()

    def test_creates_file_from_paper_list(self, full_paper: Paper) -> None:
        """File is created from a list of papers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "out.json")
            export_to_json([full_paper], path)
            assert Path(path).exists()

    def test_search_result_valid_json(self, sample_search: SearchResult) -> None:
        """SearchResult export creates valid JSON with type discriminator."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "out.json")
            export_to_json(sample_search, path)
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            assert data["type"] == "search_result"
            assert len(data["papers"]) == 2

    def test_paper_list_valid_json(self, full_paper: Paper, minimal_paper: Paper) -> None:
        """Paper list export creates valid JSON with type discriminator."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "out.json")
            export_to_json([full_paper, minimal_paper], path)
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            assert data["type"] == "paper_list"
            assert len(data["papers"]) == 2


# ---------------------------------------------------------------------------
# export_to_bibtex
# ---------------------------------------------------------------------------


class TestExportToBibtex:
    """Tests for export_to_bibtex()."""

    def test_creates_file_from_search(self, sample_search: SearchResult) -> None:
        """File is created from a SearchResult."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "out.bib")
            export_to_bibtex(sample_search, path)
            assert Path(path).exists()
            content = Path(path).read_text(encoding="utf-8")
            assert "@" in content

    def test_creates_file_from_paper_list(self, full_paper: Paper) -> None:
        """File is created from a list of papers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "out.bib")
            export_to_bibtex([full_paper], path)
            content = Path(path).read_text(encoding="utf-8")
            assert "@" in content

    def test_entry_count_from_search(self, sample_search: SearchResult) -> None:
        """Number of '@' entry markers equals the number of papers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "out.bib")
            export_to_bibtex(sample_search, path)
            content = Path(path).read_text(encoding="utf-8")
            entries = [line for line in content.splitlines() if line.startswith("@")]
            assert len(entries) == len(sample_search.papers)

    def test_empty_paper_list(self) -> None:
        """Empty paper list produces an empty file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "out.bib")
            export_to_bibtex([], path)
            content = Path(path).read_text(encoding="utf-8")
            assert content == ""


# ---------------------------------------------------------------------------
# load_from_json
# ---------------------------------------------------------------------------


class TestLoadFromJson:
    """Tests for load_from_json()."""

    def test_round_trip_search_result(self, sample_search: SearchResult) -> None:
        """SearchResult survives export -> load round-trip."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "search.json")
            export_to_json(sample_search, path)
            loaded = load_from_json(path)

        assert isinstance(loaded, SearchResult)
        assert len(loaded.papers) == 2
        assert loaded.query == "[deep learning]"

    def test_round_trip_citation_graph(self, sample_graph: CitationGraph) -> None:
        """CitationGraph survives export -> load round-trip."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "graph.json")
            export_to_json(sample_graph, path)
            loaded = load_from_json(path)

        assert isinstance(loaded, CitationGraph)
        assert loaded.paper_count == 2
        assert loaded.edge_count == 1

    def test_round_trip_paper_list(self, full_paper: Paper, minimal_paper: Paper) -> None:
        """Paper list survives export -> load round-trip."""
        papers = [full_paper, minimal_paper]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "papers.json")
            export_to_json(papers, path)
            loaded = load_from_json(path)

        assert isinstance(loaded, list)
        assert len(loaded) == 2
        assert loaded[0].title == full_paper.title

    def test_legacy_search_result_auto_detection(self, sample_search: SearchResult) -> None:
        """Files without 'type' but with 'papers' are loaded as SearchResult."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "legacy.json")
            # Write a payload without "type" key.
            payload = sample_search.to_dict()
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)

            loaded = load_from_json(path)

        assert isinstance(loaded, SearchResult)
        assert len(loaded.papers) == 2

    def test_legacy_citation_graph_auto_detection(self, sample_graph: CitationGraph) -> None:
        """Files without 'type' but with 'nodes'/'edges' are loaded as CitationGraph."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "legacy.json")
            payload = sample_graph.to_dict()
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)

            loaded = load_from_json(path)

        assert isinstance(loaded, CitationGraph)

    def test_unrecognised_format_raises(self) -> None:
        """Files with unrecognised structure cause ExportError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "bad.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"foo": "bar"}, fh)

            with pytest.raises(ExportError, match="Unrecognised"):
                load_from_json(path)
