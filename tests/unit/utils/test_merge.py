"""Tests for merge utilities."""

from findpapers.core.author import Author
from findpapers.utils.merge import merge_authors, merge_value


def _a(name: str) -> Author:
    """Shortcut to create an Author with the given name."""
    return Author(name=name)


def test_merge_value_prefers_non_null():
    """Test that merge_value prefers non-null values."""
    assert merge_value(None, "value") == "value"
    assert merge_value("value", None) == "value"


def test_merge_value_prefers_longer_strings():
    """Test that merge_value prefers longer strings."""
    assert merge_value("short", "longer string") == "longer string"
    assert merge_value("longer string", "short") == "longer string"


def test_merge_value_prefers_larger_numbers():
    """Test that merge_value prefers larger numbers."""
    assert merge_value(5, 10) == 10
    assert merge_value(10, 5) == 10
    assert merge_value(3.5, 7.2) == 7.2


def test_merge_value_combines_sets():
    """Test that merge_value combines sets."""
    result = merge_value({1, 2}, {3, 4})
    assert result == {1, 2, 3, 4}


def test_merge_value_combines_lists():
    """Test that merge_value combines lists."""
    result = merge_value([1, 2], [3, 4])
    assert set(result) == {1, 2, 3, 4}


def test_merge_value_combines_dicts():
    """Test that merge_value recursively merges dicts."""
    base = {"a": 1, "b": 2}
    incoming = {"b": 3, "c": 4}
    result = merge_value(base, incoming)
    assert result["a"] == 1
    assert result["b"] == 3  # larger value wins
    assert result["c"] == 4


class TestMergeAuthors:
    """Unit tests for the merge_authors helper."""

    def test_returns_incoming_when_larger(self):
        """Incoming list is returned when it has more authors than base."""
        base = [_a("Alice Smith")]
        incoming = [_a("Bob Jones"), _a("Charlie Brown"), _a("Diana Prince")]
        assert merge_authors(base, incoming) == incoming

    def test_returns_base_when_larger(self):
        """Base list is returned when it has more authors than incoming."""
        base = [_a("Alice Smith"), _a("Bob Jones"), _a("Charlie Brown")]
        incoming = [_a("Diana Prince")]
        assert merge_authors(base, incoming) == base

    def test_returns_base_on_tie(self):
        """Base list is returned when both lists have the same length."""
        base = [_a("Alice Smith"), _a("Bob Jones")]
        incoming = [_a("Charlie Brown"), _a("Diana Prince")]
        assert merge_authors(base, incoming) == base

    def test_empty_base_returns_incoming(self):
        """Empty base returns the incoming list."""
        result = merge_authors([], [_a("Alice Smith")])
        assert result == [_a("Alice Smith")]

    def test_empty_incoming_returns_base(self):
        """Empty incoming returns the base list."""
        result = merge_authors([_a("Alice Smith")], [])
        assert result == [_a("Alice Smith")]

    def test_both_empty(self):
        """Both empty returns empty list."""
        result = merge_authors([], [])
        assert result == []

    def test_returns_copy_not_same_object(self):
        """Returned list is a copy, not the original object."""
        base = [_a("Alice Smith"), _a("Bob Jones")]
        incoming = [_a("Charlie Brown")]
        result = merge_authors(base, incoming)
        assert result is not base
        result.append(_a("extra"))
        assert _a("extra") not in base
