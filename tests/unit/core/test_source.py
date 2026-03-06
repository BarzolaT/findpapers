"""Tests for the Source model."""

from findpapers.core.source import Source


def test_source_merge():
    """Test merging two sources."""
    base = Source(title="A", publisher=None)
    incoming = Source(title="Longer", publisher="Pub")
    base.merge(incoming)
    assert base.title == "Longer"
    assert base.publisher == "Pub"


def test_source_to_from_dict():
    """Test source serialization and deserialization."""
    data = {
        "title": "T",
        "isbn": "1",
        "issn": "2",
        "publisher": "Pub",
    }
    source = Source.from_dict(data)
    assert source.to_dict()["title"] == "T"


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
