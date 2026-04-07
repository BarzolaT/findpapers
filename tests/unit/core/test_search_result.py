"""Dedicated tests for :class:`SearchResult`."""

from __future__ import annotations

import datetime

import pytest

from findpapers.core.author import Author
from findpapers.core.paper import Database, Paper
from findpapers.core.search_result import SearchResult
from findpapers.core.source import Source

# ---------------------------------------------------------------------------
# Database enum
# ---------------------------------------------------------------------------


class TestDatabase:
    """Tests for the Database enum."""

    def test_members_match_string_values(self) -> None:
        """Each enum member is equal to its raw string value."""
        assert Database.ARXIV == "arxiv"
        assert Database.CROSSREF == "crossref"
        assert Database.IEEE == "ieee"
        assert Database.OPENALEX == "openalex"
        assert Database.PUBMED == "pubmed"
        assert Database.SCOPUS == "scopus"
        assert Database.SEMANTIC_SCHOLAR == "semantic_scholar"

    def test_all_members_present(self) -> None:
        """Eight databases are defined."""
        assert len(Database) == 8


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestSearchResultInit:
    """Tests for SearchResult construction defaults."""

    def test_defaults(self) -> None:
        """Minimal construction populates defaults correctly."""
        sr = SearchResult(query="[test]")
        assert sr.query == "[test]"
        assert sr.since is None
        assert sr.until is None
        assert sr.max_papers_per_database is None
        assert sr.databases is None
        assert sr.papers == []
        assert sr.runtime_seconds is None
        assert sr.runtime_seconds_per_database == {}

    def test_processed_at_auto_utc(self) -> None:
        """When processed_at is omitted, a UTC timestamp is generated."""
        sr = SearchResult(query="[q]")
        assert sr.processed_at.tzinfo is not None

    def test_naive_processed_at_gets_utc(self) -> None:
        """A naive datetime is upgraded to UTC."""
        naive = datetime.datetime(2024, 6, 15, 12, 0, 0)
        sr = SearchResult(query="[q]", processed_at=naive)
        assert sr.processed_at.tzinfo == datetime.timezone.utc

    def test_aware_processed_at_kept(self) -> None:
        """An already-aware datetime is left unchanged."""
        aware = datetime.datetime(2024, 6, 15, 12, 0, 0, tzinfo=datetime.timezone.utc)
        sr = SearchResult(query="[q]", processed_at=aware)
        assert sr.processed_at == aware

    def test_initial_papers(self, make_paper) -> None:
        """Papers passed at construction are stored."""
        p = make_paper(title="Init Paper")
        sr = SearchResult(query="[q]", papers=[p])
        assert len(sr.papers) == 1
        assert sr.papers[0].title == "Init Paper"


# ---------------------------------------------------------------------------
# add_paper / remove_paper
# ---------------------------------------------------------------------------


class TestAddRemovePaper:
    """Tests for add_paper and remove_paper."""

    def test_add_paper(self, make_paper) -> None:
        """add_paper appends to the list."""
        sr = SearchResult(query="[q]")
        p = make_paper()
        sr.add_paper(p)
        assert len(sr.papers) == 1

    def test_remove_paper(self, make_paper) -> None:
        """remove_paper deletes a paper that is present."""
        sr = SearchResult(query="[q]")
        p = make_paper()
        sr.add_paper(p)
        sr.remove_paper(p)
        assert len(sr.papers) == 0

    def test_remove_paper_not_present(self, make_paper) -> None:
        """remove_paper on a missing paper is a no-op."""
        sr = SearchResult(query="[q]")
        p = make_paper()
        sr.remove_paper(p)  # should not raise
        assert len(sr.papers) == 0


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------


class TestSearchResultSerialization:
    """Tests for to_dict / from_dict."""

    @pytest.fixture
    def full_search(self, make_paper) -> SearchResult:
        """A SearchResult with representative field values."""
        p = make_paper(
            title="Serialize Me",
            doi="10.1234/test",
            source=Source(title="Journal"),
        )
        return SearchResult(
            query="[serialize]",
            since=datetime.date(2022, 1, 1),
            until=datetime.date(2023, 12, 31),
            max_papers_per_database=100,
            databases=["arxiv", "scopus"],
            papers=[p],
            runtime_seconds=12.5,
            runtime_seconds_per_database={"arxiv": 7.0, "scopus": 5.5},
        )

    def test_to_dict_structure(self, full_search: SearchResult) -> None:
        """to_dict returns metadata + papers keys."""
        d = full_search.to_dict()
        assert "metadata" in d
        assert "papers" in d
        assert isinstance(d["papers"], list)

    def test_round_trip_preserves_query(self, full_search: SearchResult) -> None:
        """query survives serialization round-trip."""
        restored = SearchResult.from_dict(full_search.to_dict())
        assert restored.query == "[serialize]"

    def test_round_trip_preserves_dates(self, full_search: SearchResult) -> None:
        """since / until survive serialization round-trip."""
        restored = SearchResult.from_dict(full_search.to_dict())
        assert restored.since == datetime.date(2022, 1, 1)
        assert restored.until == datetime.date(2023, 12, 31)

    def test_round_trip_preserves_papers(self, full_search: SearchResult) -> None:
        """Papers survive serialization round-trip."""
        restored = SearchResult.from_dict(full_search.to_dict())
        assert len(restored.papers) == 1
        assert restored.papers[0].title == "Serialize Me"

    def test_round_trip_preserves_databases(self, full_search: SearchResult) -> None:
        """databases list survives serialization round-trip."""
        restored = SearchResult.from_dict(full_search.to_dict())
        assert restored.databases == ["arxiv", "scopus"]

    def test_round_trip_preserves_runtime(self, full_search: SearchResult) -> None:
        """Runtime fields survive serialization round-trip."""
        restored = SearchResult.from_dict(full_search.to_dict())
        assert restored.runtime_seconds == 12.5
        assert restored.runtime_seconds_per_database == {"arxiv": 7.0, "scopus": 5.5}

    def test_none_dates_serialized(self) -> None:
        """None since/until serialize as None in metadata."""
        sr = SearchResult(query="[q]")
        d = sr.to_dict()
        metadata = d["metadata"]
        assert isinstance(metadata, dict)
        assert metadata["since"] is None
        assert metadata["until"] is None

    def test_from_dict_with_empty_data(self) -> None:
        """from_dict with minimal data does not raise."""
        sr = SearchResult.from_dict({"metadata": {}, "papers": []})
        assert sr.query == ""
        assert sr.papers == []

    def test_from_dict_bad_timestamp_ignored(self) -> None:
        """An unparseable timestamp is silently ignored."""
        sr = SearchResult.from_dict({"metadata": {"timestamp": "not-a-date"}, "papers": []})
        # processed_at gets a fresh UTC timestamp when parsing fails
        assert sr.processed_at is not None


# ---------------------------------------------------------------------------
# failed_databases tracking
# ---------------------------------------------------------------------------


class TestFailedDatabases:
    """Tests for the failed_databases field."""

    def test_default_is_empty_list(self) -> None:
        """When omitted, failed_databases defaults to an empty list."""
        sr = SearchResult(query="[q]")
        assert sr.failed_databases == []

    def test_explicit_none_gives_empty_list(self) -> None:
        """Passing None explicitly still yields an empty list internally."""
        sr = SearchResult(query="[q]", failed_databases=None)
        assert sr.failed_databases == []

    def test_stores_provided_values(self) -> None:
        """Provided database names are stored."""
        sr = SearchResult(query="[q]", failed_databases=["arxiv", "ieee"])
        assert sr.failed_databases == ["arxiv", "ieee"]

    def test_to_dict_includes_failed_databases(self) -> None:
        """to_dict serializes failed_databases into metadata."""
        sr = SearchResult(query="[q]", failed_databases=["scopus"])
        d = sr.to_dict()
        assert d["metadata"]["failed_databases"] == ["scopus"]

    def test_to_dict_empty_list_when_no_failures(self) -> None:
        """to_dict serializes empty list as [] to distinguish from missing data."""
        sr = SearchResult(query="[q]")
        d = sr.to_dict()
        assert d["metadata"]["failed_databases"] == []

    def test_round_trip_with_failures(self) -> None:
        """failed_databases survives a to_dict / from_dict round-trip."""
        sr = SearchResult(query="[q]", failed_databases=["ieee", "pubmed"])
        restored = SearchResult.from_dict(sr.to_dict())
        assert restored.failed_databases == ["ieee", "pubmed"]

    def test_round_trip_without_failures(self) -> None:
        """An empty failed_databases round-trips without error."""
        sr = SearchResult(query="[q]")
        restored = SearchResult.from_dict(sr.to_dict())
        assert restored.failed_databases == []

    def test_from_dict_missing_key(self) -> None:
        """Older saves without the key produce an empty list."""
        sr = SearchResult.from_dict({"metadata": {}, "papers": []})
        assert sr.failed_databases == []


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    """Test for deduplication"""

    def test_deduplication_merges_same_doi(self, make_paper):
        """Two papers with the same DOI are merged into one."""
        sr = SearchResult(query="[q]")
        p1 = make_paper(title="Paper A", doi="10.1234/test")
        sr.add_paper(p1)
        p2 = make_paper(title="Paper B", doi="10.1234/test")
        sr.add_paper(p2)
        sr._deduplicate_and_merge(metrics={})
        assert len(sr.papers) == 1

    def test_deduplication_keeps_different_dois(self, make_paper):
        """Papers with different DOIs *and* different titles are kept separately."""
        sr = SearchResult(query="[q]")
        p1 = make_paper(title="Paper A", doi="10.1234/aaa")
        sr.add_paper(p1)
        p2 = make_paper(title="Paper B", doi="10.1234/bbb")
        sr.add_paper(p2)
        sr._deduplicate_and_merge(metrics={})
        assert len(sr.papers) == 2

    def test_deduplication_second_pass_merges_same_title_different_doi(self, make_paper):
        """Pass 2 merges papers with the same title even when DOIs differ.

        This covers the common cross-database case where the same work is
        indexed with an arXiv DOI in one database and the publisher DOI in
        another (e.g. ``10.48550/arxiv.1706.03762`` vs ``10.5555/3295222.3295349``
        for "Attention is All You Need").
        """
        sr = SearchResult(query="[q]")
        p1 = make_paper(title="Attention is All You Need", doi="10.48550/arxiv.1706.03762")
        sr.add_paper(p1)
        p2 = make_paper(title="Attention is All You Need", doi="10.5555/3295222.3295349")
        sr.add_paper(p2)
        sr._deduplicate_and_merge(metrics={})
        assert len(sr.papers) == 1

    def test_deduplication_second_pass_merges_same_title_one_without_year(self):
        """Pass 2 merges same-title papers when one lacks a publication date.

        This is the canonical cross-database case: a preprint indexed by
        arXiv may carry a publication date while the same work indexed by
        OpenAlex (or another database) has no publication_date in its record.
        The two copies must be merged rather than kept as separate duplicates.
        """
        sr = SearchResult(query="[q]")
        p1 = Paper(
            title="Attention is All You Need",
            abstract="abstract with year",
            authors=[Author(name="Vaswani et al.")],
            source=Source(title="arXiv"),
            publication_date=datetime.date(2017, 6, 12),
            url="http://arxiv.org/abs/1706.03762",
            doi="10.48550/arxiv.1706.03762",
        )
        sr.add_paper(p1)
        p2 = Paper(
            title="Attention is All You Need",
            abstract="abstract without year",
            authors=[Author(name="Vaswani et al.")],
            source=Source(title="OpenAlex Source"),
            publication_date=None,  # intentionally missing
            url="http://openalex.org/W2963403868",
            doi="10.5555/3295222.3295349",
        )
        sr.add_paper(p2)
        sr._deduplicate_and_merge(metrics={})
        assert len(sr.papers) == 1

    def test_deduplication_second_pass_keeps_same_title_different_year(self):
        """Papers with the same title but different publication years are kept separate."""
        sr = SearchResult(query="[q]")
        p1 = Paper(
            title="Annual Report on AI",
            abstract="abstract",
            authors=[Author(name="A")],
            source=Source(title="Journal"),
            publication_date=datetime.date(2022, 1, 1),
            url="http://example.com/2022",
            doi="10.1234/ai-2022",
        )
        sr.add_paper(p1)
        p2 = Paper(
            title="Annual Report on AI",
            abstract="abstract",
            authors=[Author(name="A")],
            source=Source(title="Journal"),
            publication_date=datetime.date(2023, 1, 1),
            url="http://example.com/2023",
            doi="10.1234/ai-2023",
        )
        sr.add_paper(p2)
        sr._deduplicate_and_merge(metrics={})
        assert len(sr.papers) == 2

    def test_deduplication_second_pass_merges_preprints_across_year_boundary(self):
        """Same preprint on two servers across Dec/Jan boundary is merged into one.

        This is the canonical Zenodo+SSRN cross-year scenario: a preprint
        deposited to Zenodo on 2025-12-25 and mirrored to SSRN on 2026-01-01
        receives different DOIs from each platform.  After pass 1 both entries
        survive (different DOIs).  Pass 2 must detect that (a) both DOIs are
        preprint DOIs and (b) the years differ by exactly 1, and therefore
        merge them rather than reporting a duplicate title.
        """
        sr = SearchResult(query="[q]")
        p1 = Paper(
            title="Attention is All You Need... Unless You Are a CISO",
            abstract="abstract from zenodo",
            authors=[Author(name="Author A")],
            source=Source(title="Zenodo"),
            publication_date=datetime.date(2025, 12, 25),
            url="https://zenodo.org/records/18056028",
            doi="10.5281/zenodo.18056028",
        )
        sr.add_paper(p1)
        p2 = Paper(
            title="Attention is All You Need... Unless You Are a CISO",
            abstract="abstract from ssrn",
            authors=[Author(name="Author A")],
            source=Source(title="SSRN"),
            publication_date=datetime.date(2026, 1, 1),
            url="https://ssrn.com/abstract=5967774",
            doi="10.2139/ssrn.5967774",
        )
        sr.add_paper(p2)
        sr._deduplicate_and_merge(metrics={})
        assert len(sr.papers) == 1

    def test_deduplication_second_pass_merges_preprint_with_published_version(self):
        """Preprint DOI + publisher DOI with adjacent years are merged into one.

        The common "preprint-to-published" case: a Zenodo deposit from 2026
        and a book chapter from 2025 share the same title.  Only the Zenodo
        record is a preprint, but that is sufficient for the year-adjacent rule
        to fire — the old ``both_preprints`` requirement was too strict and
        left such pairs as false duplicates.
        """
        sr = SearchResult(query="[q]")
        p1 = Paper(
            title="Attention is All You Need",
            abstract="preprint version",
            authors=[Author(name="Vaswani et al.")],
            source=Source(title="Zenodo"),
            publication_date=datetime.date(2026, 1, 17),
            url="https://zenodo.org/records/18289747",
            doi="10.5281/zenodo.18289747",
        )
        sr.add_paper(p1)
        p2 = Paper(
            title="Attention Is All You Need",
            abstract="book chapter version",
            authors=[Author(name="Vaswani et al.")],
            source=Source(title="Deep Learning Book"),
            publication_date=datetime.date(2025, 10, 31),
            url="https://doi.org/10.1201/9781003561460-19",
            doi="10.1201/9781003561460-19",
        )
        sr.add_paper(p2)
        sr._deduplicate_and_merge(metrics={})
        assert len(sr.papers) == 1

    def test_deduplication_second_pass_keeps_non_preprint_adjacent_years(self):
        """Two non-preprint papers with same title and adjacent years are kept separate.

        If neither DOI is a preprint, the year-adjacent rule must NOT fire —
        annual reports and series papers with consecutive-year DOIs are
        intentionally distinct entries.
        """
        sr = SearchResult(query="[q]")
        p1 = Paper(
            title="Annual Report on AI",
            abstract="abstract",
            authors=[Author(name="A")],
            source=Source(title="Journal"),
            publication_date=datetime.date(2022, 1, 1),
            url="http://example.com/2022",
            doi="10.1234/ai-2022",
        )
        sr.add_paper(p1)
        p2 = Paper(
            title="Annual Report on AI",
            abstract="abstract",
            authors=[Author(name="A")],
            source=Source(title="Journal"),
            publication_date=datetime.date(2023, 1, 1),
            url="http://example.com/2023",
            doi="10.1234/ai-2023",
        )
        sr.add_paper(p2)
        sr._deduplicate_and_merge(metrics={})
        assert len(sr.papers) == 2

    def test_deduplication_second_pass_keeps_preprints_with_large_year_gap(self):
        """Preprints with the same title but years >1 apart are kept separate."""
        sr = SearchResult(query="[q]")
        p1 = Paper(
            title="Survey of Transformers",
            abstract="abstract 2022",
            authors=[Author(name="Author A")],
            source=Source(title="Zenodo"),
            publication_date=datetime.date(2022, 1, 1),
            url="https://zenodo.org/records/1",
            doi="10.5281/zenodo.1",
        )
        sr.add_paper(p1)
        p2 = Paper(
            title="Survey of Transformers",
            abstract="abstract 2024",
            authors=[Author(name="Author B")],
            source=Source(title="arXiv"),
            publication_date=datetime.date(2024, 6, 1),
            url="https://arxiv.org/abs/2406.00001",
            doi="10.48550/arxiv.2406.00001",
        )
        sr.add_paper(p2)
        sr._deduplicate_and_merge(metrics={})
        assert len(sr.papers) == 2


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestMerge:
    """Test for merge"""

    def test_merge_paper_same_doi(self, make_paper):
        """Two papers with the same DOI are merged into one."""
        sr1 = SearchResult(query="[q]")
        p1 = make_paper(title="Paper A", doi="10.1234/test")
        sr1.add_paper(p1)
        p2 = make_paper(title="Paper B", doi="10.1234/test")
        result = sr1.merge_with(p2)
        assert len(result.papers) == 1

    def test_merge_searchresult_keeps_different_dois(self, make_paper):
        """Papers with different DOIs *and* different titles are kept separately."""
        sr1 = SearchResult(query="[q]")
        p1 = make_paper(title="Paper A", doi="10.1234/aaa")
        sr1.add_paper(p1)
        sr2 = SearchResult(query="[q]")
        p2 = make_paper(title="Paper B", doi="10.1234/bbb")
        sr2.add_paper(p2)
        result = sr1.merge_with(sr2)
        assert len(result.papers) == 2

    def test_merge_paperlist_same_title_different_doi_different_year(self, make_paper):
        """Pass 2 merges papers with the same title even when DOIs differ.

        This covers the common cross-database case where the same work is
        indexed with an arXiv DOI in one database and the publisher DOI in
        another (e.g. ``10.48550/arxiv.1706.03762`` vs ``10.5555/3295222.3295349``
        for "Attention is All You Need").
        """
        sr = SearchResult(query="[q]")
        p1 = make_paper(title="Attention is All You Need", doi="10.48550/arxiv.1706.03762")
        sr.add_paper(p1)
        p2 = make_paper(title="Attention is All You Need", doi="10.5555/3295222.3295349")
        p3 = make_paper(title="Annual Report on AI", doi="10.1234/ai-2022")
        result = sr.merge_with([p2, p3])
        assert len(result.papers) == 2

    def test_databases_merged(self):
        """Databases of the result is the merge of all the databases"""
        sr = SearchResult(query="[q]", databases=['Zenodo'])
        p1 = Paper(
            title="Paper 1",
            abstract="abstract 2022",
            authors=[Author(name="Author A")],
            source=Source(title="Zenodo"),
            databases={'Zenodo'},
            publication_date=datetime.date(2022, 1, 1),
            url="https://zenodo.org/records/1",
            doi="10.1234/zenodo.1",
        )
        sr.add_paper(p1)
        p2 = Paper(
            title="Paper 2",
            abstract="abstract 2024",
            authors=[Author(name="Author B")],
            source=Source(title="arXiv"),
            databases={'arXiv'},
            publication_date=datetime.date(2024, 6, 1),
            url="https://arxiv.org/abs/2406.00001",
            doi="10.1234/arxiv.2406.00001",
        )
        result = sr.merge_with(p2)
        assert result.databases is not None
        assert set(result.databases) == {"arXiv", "Zenodo"}

    def test_max_papers_per_database_mismatch(self):
        """max_papers_per_database does not match will be set to None"""
        sr1 = SearchResult(query="[q]", max_papers_per_database=10)
        p1 = Paper(
            title="Paper 1",
            abstract="abstract 2022",
            authors=[Author(name="Author A")],
            source=Source(title="arXiv"),
            publication_date=datetime.date(2022, 1, 1),
            url="https://zenodo.org/records/1",
            doi="10.1234/zenodo.1",
        )
        sr1.add_paper(p1)
        sr2 = SearchResult(query="[q]", max_papers_per_database=5)
        p2 = Paper(
            title="Paper 1",
            abstract="abstract 2022",
            authors=[Author(name="Author A")],
            source=Source(title="arXiv"),
            publication_date=datetime.date(2022, 1, 1),
            url="https://zenodo.org/records/1",
            doi="10.1234/zenodo.1",
        )
        sr2.add_paper(p2)
        result = sr1.merge_with(sr2)
        assert result.max_papers_per_database is None

    def test_max_papers_per_database_match(self):
        """max_papers_per_database does  match will be kept"""
        sr1 = SearchResult(query="[q]", max_papers_per_database=10)
        p1 = Paper(
            title="Paper 1",
            abstract="abstract 2022",
            authors=[Author(name="Author A")],
            source=Source(title="arXiv"),
            publication_date=datetime.date(2022, 1, 1),
            url="https://zenodo.org/records/1",
            doi="10.1234/zenodo.1",
        )
        sr1.add_paper(p1)
        sr2 = SearchResult(query="[q]", max_papers_per_database=10)
        p2 = Paper(
            title="Paper 1",
            abstract="abstract 2022",
            authors=[Author(name="Author A")],
            source=Source(title="arXiv"),
            publication_date=datetime.date(2022, 1, 1),
            url="https://zenodo.org/records/1",
            doi="10.1234/zenodo.1",
        )
        sr2.add_paper(p2)
        result = sr1.merge_with(sr2)
        assert result.max_papers_per_database == 10

    def test_failed_databases_filtered(self):
        """failed_databases is updated because a paper was added"""
        sr = SearchResult(
            query="[q]",
            databases=["arXiv", "Pubmed", "wos"],
            failed_databases=["arXiv", "Pubmed", "wos"],
        )
        p1 = Paper(
            title="Paper 1",
            abstract="abstract 2022",
            authors=[Author(name="Author A")],
            source=Source(title="arXiv"),
            databases={'arXiv'},
            publication_date=datetime.date(2022, 1, 1),
            url="https://zenodo.org/records/1",
            doi="10.1234/zenodo.1",
        )
        result = sr.merge_with(p1)
        assert result.failed_databases == ["Pubmed", "wos"]

    def test_runtime_and_processed_at_updated(self, make_paper):
        """Test metadata automatic update"""
        sr1 = SearchResult(query="[q]")
        p1 = make_paper(title="Paper A", doi="10.1234/aaa")
        sr1.add_paper(p1)
        sr2 = SearchResult(query="[q]")
        p2 = make_paper(title="Paper B", doi="10.1234/bbb")
        sr2.add_paper(p2)
        result = sr1.merge_with(sr2)
        assert result.runtime_seconds_per_database == {}
        assert result.processed_at is not None
