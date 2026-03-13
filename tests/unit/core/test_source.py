"""Tests for the Source model."""

import pytest

from findpapers.core.source import Source, SourceType
from findpapers.exceptions import ModelValidationError


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


# ---------------------------------------------------------------------------
# Source.__init__ validation
# ---------------------------------------------------------------------------


class TestSourceInit:
    """Tests for Source.__init__ ValueError."""

    def test_none_title_raises(self) -> None:
        """Passing None as title raises ModelValidationError."""
        with pytest.raises(ModelValidationError, match="title"):
            Source(title=None)  # type: ignore[arg-type]

    def test_empty_title_raises(self) -> None:
        """Passing empty string as title raises ModelValidationError."""
        with pytest.raises(ModelValidationError, match="title"):
            Source(title="")

    def test_valid_title_stores_attributes(self) -> None:
        """A valid title with all optional params stores them correctly."""
        s = Source(
            title="Nature",
            isbn="978-0-123",
            issn="0028-0836",
            publisher="Springer",
            source_type=SourceType.JOURNAL,
        )
        assert s.title == "Nature"
        assert s.isbn == "978-0-123"
        assert s.issn == "0028-0836"
        assert s.publisher == "Springer"
        assert s.source_type == SourceType.JOURNAL


# ---------------------------------------------------------------------------
# Source.from_dict validation
# ---------------------------------------------------------------------------


class TestSourceFromDict:
    """Tests for Source.from_dict edge cases."""

    def test_missing_title_raises(self) -> None:
        """from_dict without title key raises ModelValidationError."""
        with pytest.raises(ModelValidationError, match="title"):
            Source.from_dict({})

    def test_none_title_raises(self) -> None:
        """from_dict with None title raises ModelValidationError."""
        with pytest.raises(ModelValidationError, match="title"):
            Source.from_dict({"title": None})

    def test_non_string_title_raises(self) -> None:
        """from_dict with non-string title raises ModelValidationError."""
        with pytest.raises(ModelValidationError, match="title"):
            Source.from_dict({"title": 123})

    def test_valid_source_type_parsed(self) -> None:
        """from_dict correctly parses a known source_type string."""
        s = Source.from_dict({"title": "T", "source_type": "journal"})
        assert s.source_type == SourceType.JOURNAL

    def test_unknown_source_type_ignored(self) -> None:
        """from_dict silently ignores an unrecognised source_type string."""
        s = Source.from_dict({"title": "T", "source_type": "unknown_type"})
        assert s.source_type is None

    def test_no_source_type_is_none(self) -> None:
        """from_dict with no source_type leaves it as None."""
        s = Source.from_dict({"title": "T"})
        assert s.source_type is None


# ---------------------------------------------------------------------------
# SourceType enum
# ---------------------------------------------------------------------------


class TestSourceType:
    """Tests for SourceType enum values."""

    def test_all_expected_values_exist(self) -> None:
        """All expected SourceType members are present."""
        expected = {"journal", "conference", "book", "repository", "other"}
        actual = {st.value for st in SourceType}
        assert actual == expected

    def test_string_equality(self) -> None:
        """SourceType members compare equal to their string values (StrEnum)."""
        assert SourceType.JOURNAL == "journal"
        assert SourceType.CONFERENCE == "conference"
