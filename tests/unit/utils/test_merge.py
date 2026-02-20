"""Tests for merge utilities."""

from findpapers.utils.merge import merge_authors, merge_value


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

    def test_adds_genuinely_new_author(self):
        """Authors not present in base are appended."""
        result = merge_authors(["Alice Smith"], ["Bob Jones"])
        assert result == ["Alice Smith", "Bob Jones"]

    def test_deduplicates_last_first_vs_first_last(self):
        """'Last, First' and 'First Last' forms of the same name are not duplicated."""
        result = merge_authors(["Asif Hasan Chowdhury"], ["Chowdhury, Asif Hasan"])
        assert result == ["Asif Hasan Chowdhury"]

    def test_deduplicates_exact_match(self):
        """Exact duplicate names are not added again."""
        result = merge_authors(["Alice Smith", "Bob Jones"], ["Alice Smith"])
        assert result == ["Alice Smith", "Bob Jones"]

    def test_deduplicates_mixed_formats(self):
        """Mix of 'First Last' base and 'Last, First' incoming are merged correctly."""
        base = ["Alice Smith", "Bob Jones"]
        incoming = ["Smith, Alice", "Charlie Brown"]
        result = merge_authors(base, incoming)
        assert result == ["Alice Smith", "Bob Jones", "Charlie Brown"]

    def test_preserves_base_form_of_name(self):
        """When a duplicate is found the base form (First Last) is kept."""
        base = ["María García"]
        incoming = ["García, María"]
        result = merge_authors(base, incoming)
        assert result == ["María García"]

    def test_empty_base_returns_incoming(self):
        """Empty base returns the incoming list."""
        result = merge_authors([], ["Alice Smith"])
        assert result == ["Alice Smith"]

    def test_empty_incoming_returns_base(self):
        """Empty incoming returns the base list."""
        result = merge_authors(["Alice Smith"], [])
        assert result == ["Alice Smith"]

    def test_both_empty(self):
        """Both empty returns empty list."""
        result = merge_authors([], [])
        assert result == []

    def test_case_insensitive_token_matching(self):
        """Token comparison is case-insensitive."""
        result = merge_authors(["alice smith"], ["SMITH, ALICE"])
        assert result == ["alice smith"]
