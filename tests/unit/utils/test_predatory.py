"""Unit tests for predatory publication detection utilities."""

from __future__ import annotations

import pytest

from findpapers.utils.predatory import is_predatory_publication


class _FakePub:
    """Minimal publication-like object for testing."""

    def __init__(
        self,
        title: str | None = None,
        publisher: str | None = None,
        publisher_host: str | None = None,
    ) -> None:
        self.title = title
        self.publisher = publisher
        self.publisher_host = publisher_host


class TestIsPredatoryPublication:
    """Tests for is_predatory_publication."""

    def test_none_returns_false(self):
        """None input is not predatory."""
        assert is_predatory_publication(None) is False

    def test_unknown_journal_returns_false(self):
        """Unknown publication name is not flagged."""
        pub = _FakePub(title="Nature", publisher="Springer Nature")
        assert is_predatory_publication(pub) is False

    def test_predatory_journal_by_name(self):
        """A journal on the predatory list is flagged."""
        # Use a name from the predatory journals list (normalised lowercase match).
        from findpapers.utils.predatory import PREDATORY_JOURNAL_NAMES

        if not PREDATORY_JOURNAL_NAMES:
            pytest.skip("No predatory journal names loaded")
        sample_name = next(iter(PREDATORY_JOURNAL_NAMES))
        pub = _FakePub(title=sample_name)
        assert is_predatory_publication(pub) is True

    def test_predatory_publisher_by_name(self):
        """A publisher on the predatory list is flagged."""
        from findpapers.utils.predatory import PREDATORY_PUBLISHER_NAMES

        if not PREDATORY_PUBLISHER_NAMES:
            pytest.skip("No predatory publisher names loaded")
        sample_name = next(iter(PREDATORY_PUBLISHER_NAMES))
        pub = _FakePub(publisher=sample_name)
        assert is_predatory_publication(pub) is True

    def test_dict_publication_supported(self):
        """Dict-style publication objects are supported."""
        # A completely unknown publication should not be flagged.
        result = is_predatory_publication(
            {"title": "Totally Legit Journal of Science", "publisher": "Oxford University Press"}
        )
        assert result is False

    def test_empty_title_and_publisher(self):
        """Publication with empty title and publisher is not flagged."""
        pub = _FakePub(title="", publisher="", publisher_host="")
        assert is_predatory_publication(pub) is False

    def test_whitespace_only_values(self):
        """Whitespace-only values are treated as empty (not matched)."""
        pub = _FakePub(title="   ", publisher="  ")
        assert is_predatory_publication(pub) is False
