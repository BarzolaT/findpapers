"""Unit tests for BaseRunner."""

from __future__ import annotations

from datetime import date

from findpapers.core.paper import Paper
from findpapers.runners.base_runner import BaseRunner

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


class TestBaseRunnerInit:
    """Tests for BaseRunner.__init__."""

    def test_defaults_are_none(self):
        """All filter attributes default to None."""
        runner = BaseRunner()
        assert runner._since is None
        assert runner._until is None

    def test_stores_since_and_until(self):
        """since and until are stored as-is."""
        runner = BaseRunner(since=date(2020, 1, 1), until=date(2023, 12, 31))
        assert runner._since == date(2020, 1, 1)
        assert runner._until == date(2023, 12, 31)


# ---------------------------------------------------------------------------
# _matches_filters
# ---------------------------------------------------------------------------


class TestMatchesFilters:
    """Tests for BaseRunner._matches_filters."""

    def test_no_filters_accepts_all(self):
        """With no filters set every paper passes."""
        runner = BaseRunner()
        assert runner._matches_filters(_make_paper(date(2020, 1, 1)))
        assert runner._matches_filters(_make_paper(date(2015, 6, 15)))
        assert runner._matches_filters(_make_paper(None))

    def test_since_excludes_older_paper(self):
        """A paper published before `since` is rejected."""
        runner = BaseRunner(since=date(2022, 1, 1))
        assert not runner._matches_filters(_make_paper(date(2021, 12, 31)))

    def test_since_accepts_paper_on_boundary(self):
        """A paper published exactly on `since` is accepted."""
        runner = BaseRunner(since=date(2022, 1, 1))
        assert runner._matches_filters(_make_paper(date(2022, 1, 1)))

    def test_since_accepts_later_paper(self):
        """A paper published after `since` is accepted."""
        runner = BaseRunner(since=date(2022, 1, 1))
        assert runner._matches_filters(_make_paper(date(2023, 6, 1)))

    def test_until_excludes_newer_paper(self):
        """A paper published after `until` is rejected."""
        runner = BaseRunner(until=date(2023, 12, 31))
        assert not runner._matches_filters(_make_paper(date(2024, 1, 1)))

    def test_until_accepts_paper_on_boundary(self):
        """A paper published exactly on `until` is accepted."""
        runner = BaseRunner(until=date(2023, 12, 31))
        assert runner._matches_filters(_make_paper(date(2023, 12, 31)))

    def test_since_and_until_accept_in_range(self):
        """A paper within [since, until] is accepted."""
        runner = BaseRunner(since=date(2020, 1, 1), until=date(2023, 12, 31))
        assert runner._matches_filters(_make_paper(date(2021, 6, 15)))

    def test_since_excludes_no_date_paper(self):
        """A paper without a publication date is rejected when `since` is set."""
        runner = BaseRunner(since=date(2020, 1, 1))
        assert not runner._matches_filters(_make_paper(publication_date=None))

    def test_until_excludes_no_date_paper(self):
        """A paper without a publication date is rejected when `until` is set."""
        runner = BaseRunner(until=date(2023, 12, 31))
        assert not runner._matches_filters(_make_paper(publication_date=None))

    def test_combined_filters_all_must_pass(self):
        """All active filters must pass for _matches_filters to return True."""
        runner = BaseRunner(
            since=date(2020, 1, 1),
            until=date(2023, 12, 31),
        )
        # All conditions satisfied.
        assert runner._matches_filters(_make_paper(date(2021, 6, 1)))
        # Too old.
        assert not runner._matches_filters(_make_paper(date(2019, 12, 31)))
        # Too new.
        assert not runner._matches_filters(_make_paper(date(2024, 1, 1)))
