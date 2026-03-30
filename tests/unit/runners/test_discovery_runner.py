"""Unit tests for DiscoveryRunner."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from findpapers.core.paper import Paper
from findpapers.exceptions import InvalidParameterError
from findpapers.runners.discovery_runner import DEFAULT_ENRICHMENT_DATABASES, DiscoveryRunner

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_paper(
    publication_date: date | None = date(2022, 1, 1),
) -> Paper:
    """Return a minimal Paper suitable for filter tests."""
    return Paper(
        title="Test",
        abstract="",
        authors=[],
        source=None,
        publication_date=publication_date,
    )


# ---------------------------------------------------------------------------
# __init__ (attribute storage)
# ---------------------------------------------------------------------------


class TestDiscoveryRunnerInit:
    """Tests for DiscoveryRunner.__init__."""

    def test_defaults_are_none(self):
        """All filter attributes default to None."""
        runner = DiscoveryRunner()
        assert runner._since is None
        assert runner._until is None

    def test_stores_since_and_until(self):
        """since and until are stored as-is."""
        runner = DiscoveryRunner(since=date(2020, 1, 1), until=date(2023, 12, 31))
        assert runner._since == date(2020, 1, 1)
        assert runner._until == date(2023, 12, 31)


# ---------------------------------------------------------------------------
# _matches_filters
# ---------------------------------------------------------------------------


class TestMatchesFilters:
    """Tests for DiscoveryRunner._matches_filters."""

    def test_no_filters_accepts_all(self):
        """With no filters set every paper passes."""
        runner = DiscoveryRunner()
        assert runner._matches_filters(_make_paper(date(2020, 1, 1)))
        assert runner._matches_filters(_make_paper(date(2015, 6, 15)))
        assert runner._matches_filters(_make_paper(None))

    def test_since_excludes_older_paper(self):
        """A paper published before `since` is rejected."""
        runner = DiscoveryRunner(since=date(2022, 1, 1))
        assert not runner._matches_filters(_make_paper(date(2021, 12, 31)))

    def test_since_accepts_paper_on_boundary(self):
        """A paper published exactly on `since` is accepted."""
        runner = DiscoveryRunner(since=date(2022, 1, 1))
        assert runner._matches_filters(_make_paper(date(2022, 1, 1)))

    def test_since_accepts_later_paper(self):
        """A paper published after `since` is accepted."""
        runner = DiscoveryRunner(since=date(2022, 1, 1))
        assert runner._matches_filters(_make_paper(date(2023, 6, 1)))

    def test_until_excludes_newer_paper(self):
        """A paper published after `until` is rejected."""
        runner = DiscoveryRunner(until=date(2023, 12, 31))
        assert not runner._matches_filters(_make_paper(date(2024, 1, 1)))

    def test_until_accepts_paper_on_boundary(self):
        """A paper published exactly on `until` is accepted."""
        runner = DiscoveryRunner(until=date(2023, 12, 31))
        assert runner._matches_filters(_make_paper(date(2023, 12, 31)))

    def test_since_and_until_accept_in_range(self):
        """A paper within [since, until] is accepted."""
        runner = DiscoveryRunner(since=date(2020, 1, 1), until=date(2023, 12, 31))
        assert runner._matches_filters(_make_paper(date(2021, 6, 15)))

    def test_since_excludes_no_date_paper(self):
        """A paper without a publication date is rejected when `since` is set."""
        runner = DiscoveryRunner(since=date(2020, 1, 1))
        assert not runner._matches_filters(_make_paper(publication_date=None))

    def test_until_excludes_no_date_paper(self):
        """A paper without a publication date is rejected when `until` is set."""
        runner = DiscoveryRunner(until=date(2023, 12, 31))
        assert not runner._matches_filters(_make_paper(publication_date=None))

    def test_combined_filters_all_must_pass(self):
        """All active filters must pass for _matches_filters to return True."""
        runner = DiscoveryRunner(
            since=date(2020, 1, 1),
            until=date(2023, 12, 31),
        )
        # All conditions satisfied.
        assert runner._matches_filters(_make_paper(date(2021, 6, 1)))
        # Too old.
        assert not runner._matches_filters(_make_paper(date(2019, 12, 31)))
        # Too new.
        assert not runner._matches_filters(_make_paper(date(2024, 1, 1)))


# ---------------------------------------------------------------------------
# Enrichment databases default
# ---------------------------------------------------------------------------


class TestEnrichmentDatabasesDefault:
    """Tests for the enrichment_databases default behaviour."""

    def test_default_enrichment_databases_constant(self):
        """DEFAULT_ENRICHMENT_DATABASES contains only crossref and web_scraping."""
        assert set(DEFAULT_ENRICHMENT_DATABASES) == {"crossref", "web_scraping"}

    def test_none_stores_none_internally(self):
        """enrichment_databases=None is stored as None (resolved lazily in _enrich_papers)."""
        runner = DiscoveryRunner()
        assert runner._enrichment_databases is None

    def test_explicit_list_stored_normalised(self):
        """An explicit list is lower-cased and stored."""
        runner = DiscoveryRunner(enrichment_databases=["CrossRef", "OPENALEX"])
        assert runner._enrichment_databases == ["crossref", "openalex"]

    def test_empty_list_stored_as_empty(self):
        """enrichment_databases=[] is stored as-is (signals 'no enrichment')."""
        runner = DiscoveryRunner(enrichment_databases=[])
        assert runner._enrichment_databases == []

    def test_unknown_database_raises(self):
        """An unrecognised database name raises InvalidParameterError."""
        with pytest.raises(InvalidParameterError, match="Unknown enrichment database"):
            DiscoveryRunner(enrichment_databases=["not_a_db"])

    def test_enrich_papers_uses_default_when_none(self):
        """When enrichment_databases is None, _enrich_papers uses only crossref and web_scraping."""
        runner = DiscoveryRunner()

        import datetime

        from findpapers.core.author import Author
        from findpapers.core.source import Source

        paper = Paper(
            title="Test Paper",
            abstract="",
            authors=[Author(name="A. Author")],
            source=Source(title="Fake Journal"),
            publication_date=datetime.date(2023, 1, 1),
            doi="10.1234/test",
            databases={"arxiv"},
        )

        captured_databases: list[list[str]] = []

        def _fake_get_runner(**kwargs):
            captured_databases.append(sorted(kwargs.get("databases", [])))
            mock = MagicMock()
            mock.run.return_value = None
            mock.close = MagicMock()
            return mock

        with patch("findpapers.runners.discovery_runner.GetRunner", side_effect=_fake_get_runner):
            runner._enrich_papers([paper], verbose=False, show_progress=False)

        assert len(captured_databases) == 1
        assert set(captured_databases[0]) == {"crossref", "web_scraping"}

    def test_enrich_papers_uses_explicit_databases(self):
        """When enrichment_databases is explicit, _enrich_papers uses exactly those."""
        runner = DiscoveryRunner(enrichment_databases=["openalex"])

        import datetime

        from findpapers.core.author import Author
        from findpapers.core.source import Source

        paper = Paper(
            title="Test Paper",
            abstract="",
            authors=[Author(name="A. Author")],
            source=Source(title="Fake Journal"),
            publication_date=datetime.date(2023, 1, 1),
            doi="10.1234/test",
            databases=set(),
        )

        captured_databases: list[list[str]] = []

        def _fake_get_runner(**kwargs):
            captured_databases.append(sorted(kwargs.get("databases", [])))
            mock = MagicMock()
            mock.run.return_value = None
            mock.close = MagicMock()
            return mock

        with patch("findpapers.runners.discovery_runner.GetRunner", side_effect=_fake_get_runner):
            runner._enrich_papers([paper], verbose=False, show_progress=False)

        assert len(captured_databases) == 1
        assert captured_databases[0] == ["openalex"]
