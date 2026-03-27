"""Unit tests for BaseRunner."""

from __future__ import annotations

from datetime import date

import pytest

from findpapers.core.paper import Paper, PaperType
from findpapers.exceptions import InvalidParameterError
from findpapers.runners.base_runner import BaseRunner

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_paper(
    publication_date: date | None = date(2022, 1, 1),
    paper_type: PaperType | None = PaperType.ARTICLE,
) -> Paper:
    """Return a minimal Paper suitable for filter tests."""
    return Paper(
        title="Test",
        abstract="",
        authors=[],
        source=None,
        publication_date=publication_date,
        paper_type=paper_type,
    )


# ---------------------------------------------------------------------------
# _parse_paper_types
# ---------------------------------------------------------------------------


class TestParsePaperTypes:
    """Tests for BaseRunner._parse_paper_types."""

    def test_none_returns_none(self):
        """None input returns None without error."""
        assert BaseRunner._parse_paper_types(None) is None

    def test_valid_single_value(self):
        """A single valid string is converted to a singleton list."""
        result = BaseRunner._parse_paper_types(["article"])
        assert result == [PaperType.ARTICLE]

    def test_valid_multiple_values(self):
        """Multiple valid strings are converted in order."""
        result = BaseRunner._parse_paper_types(["article", "book", "phdthesis"])
        assert result == [PaperType.ARTICLE, PaperType.BOOK, PaperType.PHDTHESIS]

    def test_all_valid_types_accepted(self):
        """All 10 PaperType values are accepted without raising."""
        all_values = [pt.value for pt in PaperType]
        result = BaseRunner._parse_paper_types(all_values)
        assert result == list(PaperType)

    def test_invalid_value_raises(self):
        """An unrecognised string raises InvalidParameterError."""
        with pytest.raises(InvalidParameterError, match="Unknown paper_type"):
            BaseRunner._parse_paper_types(["not_a_type"])

    def test_invalid_value_error_lists_accepted_values(self):
        """The error message includes the list of accepted values."""
        with pytest.raises(InvalidParameterError, match="article"):
            BaseRunner._parse_paper_types(["bad_value"])

    def test_empty_list_returns_empty_list(self):
        """An empty list returns an empty list (not None)."""
        result = BaseRunner._parse_paper_types([])
        assert result == []


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
        assert runner._paper_types is None

    def test_stores_since_and_until(self):
        """since and until are stored as-is."""
        runner = BaseRunner(since=date(2020, 1, 1), until=date(2023, 12, 31))
        assert runner._since == date(2020, 1, 1)
        assert runner._until == date(2023, 12, 31)

    def test_paper_types_converted_to_enum(self):
        """paper_types strings are converted to PaperType values."""
        runner = BaseRunner(paper_types=["article", "book"])
        assert runner._paper_types == [PaperType.ARTICLE, PaperType.BOOK]

    def test_invalid_paper_type_raises_on_init(self):
        """An invalid paper_type string raises during __init__."""
        with pytest.raises(InvalidParameterError, match="Unknown paper_type"):
            BaseRunner(paper_types=["invalid_type"])


# ---------------------------------------------------------------------------
# _matches_filters
# ---------------------------------------------------------------------------


class TestMatchesFilters:
    """Tests for BaseRunner._matches_filters."""

    def test_no_filters_accepts_all(self):
        """With no filters set every paper passes."""
        runner = BaseRunner()
        assert runner._matches_filters(_make_paper(date(2020, 1, 1), PaperType.ARTICLE))
        assert runner._matches_filters(_make_paper(date(2015, 6, 15), PaperType.BOOK))
        assert runner._matches_filters(_make_paper(None, None))

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

    def test_paper_types_filter_rejects_wrong_type(self):
        """A paper whose type is not in the allow-list is rejected."""
        runner = BaseRunner(paper_types=["article"])
        assert not runner._matches_filters(_make_paper(paper_type=PaperType.BOOK))

    def test_paper_types_filter_accepts_matching_type(self):
        """A paper whose type is in the allow-list is accepted."""
        runner = BaseRunner(paper_types=["article", "book"])
        assert runner._matches_filters(_make_paper(paper_type=PaperType.BOOK))

    def test_paper_types_filter_rejects_none_type(self):
        """A paper with type=None is rejected when a type filter is active."""
        runner = BaseRunner(paper_types=["article"])
        assert not runner._matches_filters(_make_paper(paper_type=None))

    def test_combined_filters_all_must_pass(self):
        """All active filters must pass for _matches_filters to return True."""
        runner = BaseRunner(
            since=date(2020, 1, 1),
            until=date(2023, 12, 31),
            paper_types=["article"],
        )
        # All conditions satisfied.
        assert runner._matches_filters(_make_paper(date(2021, 6, 1), PaperType.ARTICLE))
        # Wrong type.
        assert not runner._matches_filters(_make_paper(date(2021, 6, 1), PaperType.BOOK))
        # Too old.
        assert not runner._matches_filters(_make_paper(date(2019, 12, 31), PaperType.ARTICLE))
        # Too new.
        assert not runner._matches_filters(_make_paper(date(2024, 1, 1), PaperType.ARTICLE))
