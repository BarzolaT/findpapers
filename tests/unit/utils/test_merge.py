"""Tests for merge utilities."""

from findpapers.utils.merge import merge_value


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
