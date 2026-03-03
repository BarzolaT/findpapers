"""Dedicated tests for :class:`Query` and :class:`QueryNode` data models."""

from __future__ import annotations

import pytest

from findpapers.core.query import (
    VALID_FILTER_CODES,
    ConnectorType,
    FilterCode,
    NodeType,
    Query,
    QueryNode,
    QueryValidationError,
)

# ---------------------------------------------------------------------------
# FilterCode enum
# ---------------------------------------------------------------------------


class TestFilterCode:
    """Tests for the FilterCode enum."""

    def test_all_codes_present(self) -> None:
        """Expected filter codes exist."""
        expected = {"ti", "abs", "key", "au", "src", "aff", "tiabs", "tiabskey"}
        assert {fc.value for fc in FilterCode} == expected

    def test_string_equality(self) -> None:
        """FilterCode members compare equal to their string value."""
        assert FilterCode.TITLE == "ti"
        assert FilterCode.ABSTRACT == "abs"


class TestValidFilterCodes:
    """Tests for the VALID_FILTER_CODES constant."""

    def test_is_frozenset(self) -> None:
        """VALID_FILTER_CODES is a frozenset."""
        assert isinstance(VALID_FILTER_CODES, frozenset)

    def test_contains_all_filter_code_values(self) -> None:
        """Every FilterCode value is present in VALID_FILTER_CODES."""
        for fc in FilterCode:
            assert fc.value in VALID_FILTER_CODES


# ---------------------------------------------------------------------------
# ConnectorType enum
# ---------------------------------------------------------------------------


class TestConnectorType:
    """Tests for the ConnectorType enum."""

    def test_values(self) -> None:
        """Connectors have expected string values."""
        assert ConnectorType.AND == "and"
        assert ConnectorType.OR == "or"
        assert ConnectorType.AND_NOT == "and not"


# ---------------------------------------------------------------------------
# QueryValidationError
# ---------------------------------------------------------------------------


class TestQueryValidationError:
    """Tests for QueryValidationError."""

    def test_is_value_error_subclass(self) -> None:
        """QueryValidationError is a ValueError subclass."""
        assert issubclass(QueryValidationError, ValueError)

    def test_message_preserved(self) -> None:
        """The error message can be retrieved."""
        err = QueryValidationError("bad query")
        assert str(err) == "bad query"


# ---------------------------------------------------------------------------
# QueryNode
# ---------------------------------------------------------------------------


class TestQueryNode:
    """Tests for QueryNode dataclass."""

    def test_term_node(self) -> None:
        """A TERM node stores its value."""
        node = QueryNode(node_type=NodeType.TERM, value="machine learning")
        assert node.value == "machine learning"
        assert node.children == []

    def test_connector_node(self) -> None:
        """A CONNECTOR node accepts ConnectorType as value."""
        node = QueryNode(node_type=NodeType.CONNECTOR, value=ConnectorType.AND)
        assert node.value == ConnectorType.AND

    def test_group_node_with_children(self) -> None:
        """A GROUP node holds child nodes."""
        child = QueryNode(node_type=NodeType.TERM, value="deep learning")
        group = QueryNode(node_type=NodeType.GROUP, children=[child])
        assert len(group.children) == 1

    def test_get_all_terms(self) -> None:
        """get_all_terms collects terms across nested children."""
        root = QueryNode(
            node_type=NodeType.ROOT,
            children=[
                QueryNode(node_type=NodeType.TERM, value="a"),
                QueryNode(node_type=NodeType.CONNECTOR, value=ConnectorType.AND),
                QueryNode(
                    node_type=NodeType.GROUP,
                    children=[
                        QueryNode(node_type=NodeType.TERM, value="b"),
                        QueryNode(node_type=NodeType.CONNECTOR, value=ConnectorType.OR),
                        QueryNode(node_type=NodeType.TERM, value="c"),
                    ],
                ),
            ],
        )
        assert root.get_all_terms() == ["a", "b", "c"]

    def test_get_all_filters(self) -> None:
        """get_all_filters returns unique filter codes across all nodes."""
        root = QueryNode(
            node_type=NodeType.ROOT,
            children=[
                QueryNode(
                    node_type=NodeType.TERM,
                    value="x",
                    filter_code=FilterCode.TITLE,
                ),
                QueryNode(
                    node_type=NodeType.TERM,
                    value="y",
                    filter_code=FilterCode.ABSTRACT,
                ),
                QueryNode(
                    node_type=NodeType.TERM,
                    value="z",
                    filter_code=FilterCode.TITLE,
                ),
            ],
        )
        filters = root.get_all_filters()
        assert set(filters) == {FilterCode.TITLE, FilterCode.ABSTRACT}

    def test_get_all_filters_empty_when_none(self) -> None:
        """get_all_filters returns empty list when no filters set."""
        node = QueryNode(node_type=NodeType.TERM, value="x")
        assert node.get_all_filters() == []

    # -- Serialization -------------------------------------------------------

    def test_to_dict_term(self) -> None:
        """to_dict for a TERM node includes node_type and value."""
        node = QueryNode(node_type=NodeType.TERM, value="test")
        d = node.to_dict()
        assert d["node_type"] == "term"
        assert d["value"] == "test"
        assert "children" not in d

    def test_to_dict_connector_uses_string_value(self) -> None:
        """to_dict serialises ConnectorType to its string form."""
        node = QueryNode(node_type=NodeType.CONNECTOR, value=ConnectorType.AND_NOT)
        d = node.to_dict()
        assert d["value"] == "and not"

    def test_to_dict_includes_filter_codes(self) -> None:
        """to_dict includes filter_code and inherited_filter_code when set."""
        node = QueryNode(
            node_type=NodeType.TERM,
            value="a",
            filter_code=FilterCode.TITLE,
            inherited_filter_code=FilterCode.ABSTRACT,
        )
        d = node.to_dict()
        assert d["filter_code"] == "ti"
        assert d["inherited_filter_code"] == "abs"

    def test_to_dict_includes_children_match_filter(self) -> None:
        """to_dict includes children_match_filter when set."""
        node = QueryNode(
            node_type=NodeType.GROUP,
            children_match_filter=True,
        )
        d = node.to_dict()
        assert d["children_match_filter"] is True

    def test_from_dict_round_trip(self) -> None:
        """from_dict(to_dict()) yields an equivalent node."""
        original = QueryNode(
            node_type=NodeType.ROOT,
            children=[
                QueryNode(
                    node_type=NodeType.TERM,
                    value="term",
                    filter_code=FilterCode.KEYWORDS,
                    inherited_filter_code=FilterCode.KEYWORDS,
                ),
                QueryNode(
                    node_type=NodeType.CONNECTOR,
                    value=ConnectorType.OR,
                ),
                QueryNode(
                    node_type=NodeType.GROUP,
                    filter_code=FilterCode.TITLE,
                    children_match_filter=False,
                    children=[
                        QueryNode(node_type=NodeType.TERM, value="nested"),
                    ],
                ),
            ],
        )
        restored = QueryNode.from_dict(original.to_dict())
        assert restored.node_type == original.node_type
        assert len(restored.children) == 3
        assert restored.children[0].value == "term"
        assert restored.children[0].filter_code == FilterCode.KEYWORDS
        assert restored.children[1].value == ConnectorType.OR
        assert restored.children[2].children_match_filter is False
        assert restored.children[2].children[0].value == "nested"


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


class TestQuery:
    """Tests for the Query dataclass."""

    @pytest.fixture()
    def simple_query(self) -> Query:
        """A simple Query with two terms joined by AND."""
        return Query(
            raw_query="[a] AND [b]",
            root=QueryNode(
                node_type=NodeType.ROOT,
                children=[
                    QueryNode(node_type=NodeType.TERM, value="a"),
                    QueryNode(
                        node_type=NodeType.CONNECTOR,
                        value=ConnectorType.AND,
                    ),
                    QueryNode(node_type=NodeType.TERM, value="b"),
                ],
            ),
        )

    def test_get_all_terms(self, simple_query: Query) -> None:
        """Query.get_all_terms delegates to root."""
        assert simple_query.get_all_terms() == ["a", "b"]

    def test_get_all_filters_empty(self, simple_query: Query) -> None:
        """Query with no filters returns empty list."""
        assert simple_query.get_all_filters() == []

    def test_get_all_filters_with_filters(self) -> None:
        """Query.get_all_filters reflects filter codes on terms."""
        q = Query(
            raw_query="ti[x]",
            root=QueryNode(
                node_type=NodeType.ROOT,
                children=[
                    QueryNode(
                        node_type=NodeType.TERM,
                        value="x",
                        filter_code=FilterCode.TITLE,
                    ),
                ],
            ),
        )
        assert q.get_all_filters() == [FilterCode.TITLE]

    def test_to_dict(self, simple_query: Query) -> None:
        """to_dict includes raw_query and tree."""
        d = simple_query.to_dict()
        assert d["raw_query"] == "[a] AND [b]"
        assert "tree" in d

    def test_from_dict_round_trip(self, simple_query: Query) -> None:
        """from_dict(to_dict()) yields an equivalent Query."""
        restored = Query.from_dict(simple_query.to_dict())
        assert restored.raw_query == simple_query.raw_query
        assert restored.get_all_terms() == ["a", "b"]
