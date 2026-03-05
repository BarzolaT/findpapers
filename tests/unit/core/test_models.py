"""Tests for Paper, Publication, and SearchResult models."""

import datetime

import pytest

from findpapers.core.author import Author
from findpapers.core.paper import _MAX_FUTURE_DAYS, Paper, PaperType, _is_preprint_doi, _merge_doi
from findpapers.core.search_result import SearchResult
from findpapers.core.source import Source


def test_publication_merge():
    """Test merging two publications."""
    base = Source(title="A", publisher=None)
    incoming = Source(title="Longer", publisher="Pub")
    base.merge(incoming)
    assert base.title == "Longer"
    assert base.publisher == "Pub"


def test_publication_to_from_dict():
    """Test source serialization and deserialization."""
    data = {
        "title": "T",
        "isbn": "1",
        "issn": "2",
        "publisher": "Pub",
    }
    source = Source.from_dict(data)
    assert source.to_dict()["title"] == "T"


def test_paper_requires_title():
    """Test that paper requires a title."""
    with pytest.raises(ValueError):
        Paper(
            title="",
            abstract="",
            authors=[],
            source=None,
            publication_date=datetime.date.today(),
        )


def test_paper_sanitize_date_nullifies_far_future():
    """Publication dates more than _MAX_FUTURE_DAYS in the future are set to None."""
    far_future = datetime.date.today() + datetime.timedelta(days=_MAX_FUTURE_DAYS + 100)
    paper = Paper(
        title="Future Paper",
        abstract="",
        authors=[],
        source=None,
        publication_date=far_future,
    )
    assert paper.publication_date is None


def test_paper_sanitize_date_keeps_near_future():
    """Dates within the grace window are preserved."""
    near_future = datetime.date.today() + datetime.timedelta(days=30)
    paper = Paper(
        title="Near Future Paper",
        abstract="",
        authors=[],
        source=None,
        publication_date=near_future,
    )
    assert paper.publication_date == near_future


def test_paper_sanitize_date_keeps_past():
    """Past dates are preserved."""
    past = datetime.date(2020, 6, 15)
    paper = Paper(
        title="Past Paper",
        abstract="",
        authors=[],
        source=None,
        publication_date=past,
    )
    assert paper.publication_date == past


def test_paper_sanitize_date_keeps_none():
    """None publication date stays None."""
    paper = Paper(
        title="No Date Paper",
        abstract="",
        authors=[],
        source=None,
        publication_date=None,
    )
    assert paper.publication_date is None


def test_paper_url_and_pdf_url():
    """Test that paper accepts url and pdf_url."""
    paper = Paper(
        title="Title",
        abstract="Abstract",
        authors=[Author(name="A")],
        source=None,
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
    publication = Source(title="Journal")
    paper = Paper(
        title="Title",
        abstract="",
        authors=[Author(name="A")],
        source=publication,
        publication_date=datetime.date(2020, 1, 1),
        url="https://example.com",
    )
    paper.add_database("arxiv")
    assert "arxiv" in paper.databases
    assert paper.url == "https://example.com"

    incoming = Paper(
        title="Longer Title",
        abstract="Abstract",
        authors=[Author(name="A"), Author(name="B")],
        source=Source(title="Journal", publisher="Pub"),
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


def test_paper_merge_keeps_larger_author_list():
    """Paper.merge keeps whichever author list is longer.

    This covers the enrichment scenario where different sources return
    different numbers of authors (e.g. one source lists all co-authors while
    another lists only the first few).
    """
    # base has fewer authors than incoming → incoming wins
    base = Paper(
        title="Test Paper",
        abstract="Abstract",
        authors=[Author(name="Alice Smith"), Author(name="Bob Jones")],
        source=None,
        publication_date=None,
    )
    incoming = Paper(
        title="Test Paper",
        abstract="Abstract",
        authors=[
            Author(name="Alice Smith"),
            Author(name="Bob Jones"),
            Author(name="Charlie Brown"),
            Author(name="Diana Prince"),
        ],
        source=None,
        publication_date=None,
    )
    base.merge(incoming)
    assert base.authors == [
        Author(name="Alice Smith"),
        Author(name="Bob Jones"),
        Author(name="Charlie Brown"),
        Author(name="Diana Prince"),
    ]

    # base has more authors than incoming → base wins
    base2 = Paper(
        title="Test Paper",
        abstract="Abstract",
        authors=[
            Author(name="Alice Smith"),
            Author(name="Bob Jones"),
            Author(name="Charlie Brown"),
        ],
        source=None,
        publication_date=None,
    )
    incoming2 = Paper(
        title="Test Paper",
        abstract="Abstract",
        authors=[Author(name="Alice Smith")],
        source=None,
        publication_date=None,
    )
    base2.merge(incoming2)
    assert base2.authors == [
        Author(name="Alice Smith"),
        Author(name="Bob Jones"),
        Author(name="Charlie Brown"),
    ]


class TestIsPreprintDoi:
    """Unit tests for the _is_preprint_doi helper."""

    def test_arxiv_doi_recognised_as_preprint(self):
        assert _is_preprint_doi("10.48550/arxiv.1706.03762") is True

    def test_biorxiv_doi_recognised_as_preprint(self):
        assert _is_preprint_doi("10.1101/2021.05.01.442244") is True

    def test_ssrn_doi_recognised_as_preprint(self):
        assert _is_preprint_doi("10.2139/ssrn.3844763") is True

    def test_zenodo_doi_recognised_as_preprint(self):
        assert _is_preprint_doi("10.5281/zenodo.18056028") is True

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
        authors=[Author(name="Vaswani")],
        source=None,
        publication_date=datetime.date(2017, 6, 12),
        doi="10.48550/arxiv.1706.03762",
    )
    incoming = Paper(
        title="Attention is All You Need",
        abstract="The dominant sequence...",
        authors=[Author(name="Vaswani")],
        source=None,
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
        authors=[Author(name="Vaswani")],
        source=None,
        publication_date=datetime.date(2017, 6, 12),
        doi="10.5555/3295222.3295349",
    )
    incoming = Paper(
        title="Attention is All You Need",
        abstract="",
        authors=[Author(name="Vaswani")],
        source=None,
        publication_date=datetime.date(2017, 6, 12),
        doi="10.48550/arxiv.1706.03762",
    )
    base.merge(incoming)
    assert base.doi == "10.5555/3295222.3295349"


def test_search_add_paper():
    """Test adding paper to search results."""
    search = SearchResult(query="q", databases=["arxiv"])
    paper = Paper(
        title="Title",
        abstract="Abstract",
        authors=[Author(name="Author")],
        source=None,
        publication_date=None,
    )
    search.add_paper(paper)
    assert len(search.papers) == 1
    assert search.papers[0].title == "Title"


def _make_search_with_paper() -> SearchResult:
    """Return a SearchResult with one Article paper for export tests."""
    paper = Paper(
        title="Export Test Paper",
        abstract="Abstract text.",
        authors=[Author(name="Author One")],
        source=Source(title="Test Journal"),
        publication_date=datetime.date(2023, 1, 1),
    )
    search = SearchResult(
        query="[export]",
        databases=["arxiv"],
        since=datetime.date(2022, 1, 1),
        until=datetime.date(2023, 12, 31),
    )
    search.add_paper(paper)
    return search


def test_search_to_dict_contains_papers():
    """SearchResult.to_dict() returns a dict with 'papers' key."""
    data = _make_search_with_paper().to_dict()
    assert "papers" in data
    assert len(data["papers"]) == 1


def test_search_to_dict_contains_since_until():
    """SearchResult.to_dict() serializes since/until in metadata."""
    data = _make_search_with_paper().to_dict()
    assert data["metadata"]["since"] == "2022-01-01"
    assert data["metadata"]["until"] == "2023-12-31"


def test_search_to_dict_since_until_none():
    """SearchResult.to_dict() serializes None when since/until not set."""
    search = SearchResult(query="[test]", databases=["arxiv"])
    data = search.to_dict()
    assert data["metadata"]["since"] is None
    assert data["metadata"]["until"] is None


def test_search_from_dict_round_trip():
    """SearchResult.from_dict(to_dict()) preserves all fields."""
    original = _make_search_with_paper()
    data = original.to_dict()
    restored = SearchResult.from_dict(data)
    assert len(restored.papers) == 1
    assert restored.papers[0].title == "Export Test Paper"
    assert restored.query == "[export]"
    assert restored.since == datetime.date(2022, 1, 1)
    assert restored.until == datetime.date(2023, 12, 31)
    assert restored.databases == ["arxiv"]


# ---------------------------------------------------------------------------
# PaperType on Paper
# ---------------------------------------------------------------------------


class TestPaperType:
    """Tests for the paper_type attribute on Paper."""

    def test_paper_type_defaults_to_none(self) -> None:
        """Paper without explicit paper_type has None."""
        paper = Paper(
            title="T",
            abstract="",
            authors=[],
            source=None,
            publication_date=None,
        )
        assert paper.paper_type is None

    def test_paper_type_set_at_construction(self) -> None:
        """Paper can be constructed with a paper_type."""
        paper = Paper(
            title="T",
            abstract="",
            authors=[],
            source=None,
            publication_date=None,
            paper_type=PaperType.ARTICLE,
        )
        assert paper.paper_type is PaperType.ARTICLE

    def test_paper_type_serialized_in_to_dict(self) -> None:
        """to_dict includes paper_type when set."""
        paper = Paper(
            title="T",
            abstract="",
            authors=[],
            source=None,
            publication_date=None,
            paper_type=PaperType.INPROCEEDINGS,
        )
        d = paper.to_dict()
        assert d["paper_type"] == "inproceedings"

    def test_paper_type_none_serialized_as_none(self) -> None:
        """to_dict serializes missing paper_type as None."""
        paper = Paper(
            title="T",
            abstract="",
            authors=[],
            source=None,
            publication_date=None,
        )
        d = paper.to_dict()
        assert d["paper_type"] is None

    def test_paper_type_deserialized_from_dict(self) -> None:
        """from_dict restores paper_type from string value."""
        d = {"title": "T", "paper_type": "phdthesis"}
        paper = Paper.from_dict(d)
        assert paper.paper_type is PaperType.PHDTHESIS

    def test_paper_type_invalid_string_ignored(self) -> None:
        """from_dict ignores invalid paper_type strings."""
        d = {"title": "T", "paper_type": "not_a_type"}
        paper = Paper.from_dict(d)
        assert paper.paper_type is None

    def test_paper_type_none_in_dict(self) -> None:
        """from_dict handles paper_type being None."""
        d = {"title": "T", "paper_type": None}
        paper = Paper.from_dict(d)
        assert paper.paper_type is None

    def test_paper_type_missing_from_dict(self) -> None:
        """from_dict handles paper_type key missing."""
        d = {"title": "T"}
        paper = Paper.from_dict(d)
        assert paper.paper_type is None

    def test_paper_type_merge_fills_none(self) -> None:
        """Merge fills paper_type when base is None."""
        base = Paper(title="T", abstract="", authors=[], source=None, publication_date=None)
        incoming = Paper(
            title="T",
            abstract="",
            authors=[],
            source=None,
            publication_date=None,
            paper_type=PaperType.ARTICLE,
        )
        base.merge(incoming)
        assert base.paper_type is PaperType.ARTICLE

    def test_paper_type_merge_keeps_existing(self) -> None:
        """Merge preserves existing paper_type when incoming also has one."""
        base = Paper(
            title="T",
            abstract="",
            authors=[],
            source=None,
            publication_date=None,
            paper_type=PaperType.INPROCEEDINGS,
        )
        incoming = Paper(
            title="T",
            abstract="",
            authors=[],
            source=None,
            publication_date=None,
            paper_type=PaperType.ARTICLE,
        )
        base.merge(incoming)
        assert base.paper_type is PaperType.INPROCEEDINGS

    def test_all_bibtex_types_present(self) -> None:
        """PaperType enum covers the agreed BibTeX entry types."""
        expected = {
            "article",
            "inproceedings",
            "inbook",
            "incollection",
            "book",
            "phdthesis",
            "mastersthesis",
            "techreport",
            "unpublished",
            "misc",
        }
        actual = {pt.value for pt in PaperType}
        assert actual == expected

    def test_paper_type_round_trip(self) -> None:
        """to_dict → from_dict preserves paper_type."""
        paper = Paper(
            title="T",
            abstract="",
            authors=[],
            source=None,
            publication_date=None,
            paper_type=PaperType.TECHREPORT,
        )
        restored = Paper.from_dict(paper.to_dict())
        assert restored.paper_type is PaperType.TECHREPORT


class TestInferPageCount:
    """Tests for Paper._infer_page_count and its integration."""

    def test_simple_range(self) -> None:
        """A valid page range like '223-230' yields 8 pages."""
        assert Paper._infer_page_count("223-230") == 8

    def test_single_page(self) -> None:
        """When start equals end (e.g. '5-5'), the result is 1."""
        assert Paper._infer_page_count("5-5") == 1

    def test_none_input(self) -> None:
        """None page_range returns None."""
        assert Paper._infer_page_count(None) is None

    def test_empty_string(self) -> None:
        """Empty string returns None."""
        assert Paper._infer_page_count("") is None

    def test_non_numeric(self) -> None:
        """Non-numeric page_range (e.g. 'e123') return None."""
        assert Paper._infer_page_count("e123") is None

    def test_non_numeric_range(self) -> None:
        """Non-numeric range (e.g. 'A1-B2') returns None."""
        assert Paper._infer_page_count("A1-B2") is None

    def test_reversed_range(self) -> None:
        """Reversed range (end < start) returns None."""
        assert Paper._infer_page_count("230-223") is None

    def test_single_number_no_hyphen(self) -> None:
        """A single number without hyphen returns None (not a range)."""
        assert Paper._infer_page_count("56") is None

    def test_multiple_hyphens(self) -> None:
        """More than one hyphen returns None."""
        assert Paper._infer_page_count("1-2-3") is None

    def test_spaces_around_numbers(self) -> None:
        """Spaces around numbers are trimmed correctly."""
        assert Paper._infer_page_count(" 10 - 20 ") == 11

    def test_init_infers_when_absent(self) -> None:
        """Paper.__init__ auto-fills page_count from page_range when absent."""
        paper = Paper(
            title="T",
            abstract="",
            authors=[],
            source=None,
            publication_date=None,
            page_range="100-110",
        )
        assert paper.page_count == 11

    def test_init_preserves_explicit_value(self) -> None:
        """Explicit page_count is never overridden by inference."""
        paper = Paper(
            title="T",
            abstract="",
            authors=[],
            source=None,
            publication_date=None,
            page_count=5,
            page_range="100-110",
        )
        assert paper.page_count == 5

    def test_merge_infers_after_page_range_acquired(self) -> None:
        """Merging fills page_count if page_range becomes available."""
        paper_a = Paper(
            title="T",
            abstract="",
            authors=[],
            source=None,
            publication_date=None,
        )
        paper_b = Paper(
            title="T",
            abstract="",
            authors=[],
            source=None,
            publication_date=None,
            page_range="50-60",
        )
        # paper_b already has inferred page_count, but test merge path
        # by resetting it to None to force inference in merge.
        paper_b.page_count = None
        paper_a.merge(paper_b)
        assert paper_a.page_count == 11

    def test_from_dict_infers(self) -> None:
        """from_dict auto-fills page_count when absent."""
        data = Paper(
            title="T",
            abstract="",
            authors=[],
            source=None,
            publication_date=None,
            page_range="1-15",
        ).to_dict()
        # Force page_count to None to test inference via from_dict.
        data["page_count"] = None
        restored = Paper.from_dict(data)
        assert restored.page_count == 15


# ------------------------------------------------------------------
# Paper.__eq__ / __hash__
# ------------------------------------------------------------------


class TestPaperEquality:
    """Tests for Paper.__eq__ and __hash__."""

    def test_same_doi_means_equal(self) -> None:
        """Papers with matching DOIs are equal regardless of title."""
        a = Paper(
            title="A", abstract="", authors=[], source=None, publication_date=None, doi="10.1/x"
        )
        b = Paper(
            title="B", abstract="", authors=[], source=None, publication_date=None, doi="10.1/x"
        )
        assert a == b
        assert hash(a) == hash(b)

    def test_doi_case_insensitive(self) -> None:
        """DOI comparison is case-insensitive."""
        a = Paper(
            title="A", abstract="", authors=[], source=None, publication_date=None, doi="10.1/X"
        )
        b = Paper(
            title="B", abstract="", authors=[], source=None, publication_date=None, doi="10.1/x"
        )
        assert a == b

    def test_same_title_no_doi_means_equal(self) -> None:
        """Papers without DOI but with the same title are equal."""
        a = Paper(title="Same", abstract="a", authors=[], source=None, publication_date=None)
        b = Paper(title="Same", abstract="b", authors=[], source=None, publication_date=None)
        assert a == b
        assert hash(a) == hash(b)

    def test_title_case_insensitive(self) -> None:
        """Title comparison is case-insensitive when no DOI is present."""
        a = Paper(title="HELLO", abstract="", authors=[], source=None, publication_date=None)
        b = Paper(title="hello", abstract="", authors=[], source=None, publication_date=None)
        assert a == b

    def test_different_doi_not_equal(self) -> None:
        """Papers with different DOIs are not equal."""
        a = Paper(
            title="A", abstract="", authors=[], source=None, publication_date=None, doi="10.1/x"
        )
        b = Paper(
            title="A", abstract="", authors=[], source=None, publication_date=None, doi="10.2/y"
        )
        assert a != b

    def test_different_title_no_doi_not_equal(self) -> None:
        """Papers without DOI and different titles are not equal."""
        a = Paper(title="Alpha", abstract="", authors=[], source=None, publication_date=None)
        b = Paper(title="Beta", abstract="", authors=[], source=None, publication_date=None)
        assert a != b

    def test_not_equal_to_non_paper(self) -> None:
        """Comparison with non-Paper returns NotImplemented."""
        p = Paper(title="A", abstract="", authors=[], source=None, publication_date=None)
        assert p != "not a paper"

    def test_paper_usable_in_set(self) -> None:
        """Papers with same identity can be deduplicated in a set."""
        a = Paper(
            title="X", abstract="", authors=[], source=None, publication_date=None, doi="10.1/z"
        )
        b = Paper(
            title="Y", abstract="", authors=[], source=None, publication_date=None, doi="10.1/z"
        )
        assert len({a, b}) == 1

    def test_paper_in_list_after_deserialization(self) -> None:
        """Paper created from dict is found via 'in' operator on a list."""
        original = Paper(
            title="T", abstract="", authors=[], source=None, publication_date=None, doi="10.1/abc"
        )
        data = original.to_dict()
        restored = Paper.from_dict(data)
        assert restored in [original]


# ------------------------------------------------------------------
# Source.__eq__ / __hash__
# ------------------------------------------------------------------


class TestSourceEquality:
    """Tests for Source.__eq__ and __hash__."""

    def test_same_title_means_equal(self) -> None:
        """Sources with the same title are equal."""
        a = Source(title="Nature")
        b = Source(title="Nature")
        assert a == b
        assert hash(a) == hash(b)

    def test_title_case_insensitive(self) -> None:
        """Source equality is case-insensitive."""
        a = Source(title="NATURE")
        b = Source(title="nature")
        assert a == b

    def test_different_title_not_equal(self) -> None:
        """Sources with different titles are not equal."""
        a = Source(title="Nature")
        b = Source(title="Science")
        assert a != b

    def test_not_equal_to_non_source(self) -> None:
        """Comparison with non-Source returns NotImplemented."""
        s = Source(title="Nature")
        assert s != "not a source"

    def test_source_usable_in_set(self) -> None:
        """Sources with the same title can be deduplicated in a set."""
        a = Source(title="Nature")
        b = Source(title="nature")
        assert len({a, b}) == 1


# ---------------------------------------------------------------------------
# Source.__str__
# ---------------------------------------------------------------------------


class TestSourceStr:
    """Tests for Source.__str__."""

    def test_str_with_publisher(self) -> None:
        """str(source) includes publisher in parentheses."""
        s = Source(title="Nature", publisher="Springer")
        assert str(s) == "Nature (Springer)"

    def test_str_without_publisher(self) -> None:
        """str(source) returns just the title when there is no publisher."""
        s = Source(title="Nature")
        assert str(s) == "Nature"

    def test_str_differs_from_repr(self) -> None:
        """__str__ and __repr__ produce different output."""
        s = Source(title="Nature", publisher="Springer")
        assert str(s) != repr(s)


# ---------------------------------------------------------------------------
# Paper.__str__
# ---------------------------------------------------------------------------


class TestPaperStr:
    """Tests for Paper.__str__."""

    def test_str_full(self) -> None:
        """str(paper) with authors and date looks like a citation."""
        paper = Paper(
            title="Deep Learning",
            abstract="",
            authors=[Author(name="LeCun, Y."), Author(name="Bengio, Y.")],
            source=None,
            publication_date=datetime.date(2015, 5, 1),
        )
        assert str(paper) == "LeCun, Y. et al. (2015) Deep Learning."

    def test_str_single_author(self) -> None:
        """str(paper) with a single author omits 'et al.'."""
        paper = Paper(
            title="A Survey",
            abstract="",
            authors=[Author(name="Smith, J.")],
            source=None,
            publication_date=datetime.date(2020, 1, 1),
        )
        assert str(paper) == "Smith, J. (2020) A Survey."

    def test_str_no_authors(self) -> None:
        """str(paper) without authors starts with year."""
        paper = Paper(
            title="Anonymous Work",
            abstract="",
            authors=[],
            source=None,
            publication_date=datetime.date(2021, 6, 1),
        )
        assert str(paper) == "(2021) Anonymous Work."

    def test_str_no_date(self) -> None:
        """str(paper) without date omits year."""
        paper = Paper(
            title="Timeless",
            abstract="",
            authors=[Author(name="Doe, J.")],
            source=None,
            publication_date=None,
        )
        assert str(paper) == "Doe, J. Timeless."

    def test_str_minimal(self) -> None:
        """str(paper) with no authors and no date returns just the title."""
        paper = Paper(
            title="Only Title",
            abstract="",
            authors=[],
            source=None,
            publication_date=None,
        )
        assert str(paper) == "Only Title."

    def test_str_title_trailing_dot_not_duplicated(self) -> None:
        """A title already ending with '.' does not get a double period."""
        paper = Paper(
            title="Ends with dot.",
            abstract="",
            authors=[],
            source=None,
            publication_date=None,
        )
        assert str(paper) == "Ends with dot."

    def test_str_differs_from_repr(self) -> None:
        """__str__ and __repr__ produce different output."""
        paper = Paper(
            title="T",
            abstract="",
            authors=[Author(name="A, B.")],
            source=None,
            publication_date=datetime.date(2021, 1, 1),
        )
        assert str(paper) != repr(paper)
