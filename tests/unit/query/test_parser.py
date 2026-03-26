"""Tests for Query parsing logic."""

import pytest

from findpapers.core.query import NodeType, Query
from findpapers.query.parser import QueryParser
from findpapers.query.validator import QueryValidator


class TestQueryParser:
    """Test query parsing."""

    @pytest.fixture
    def parser(self):
        """Return a QueryParser instance."""
        return QueryParser()

    @pytest.fixture
    def validator(self):
        """Return a QueryValidator instance."""
        return QueryValidator()

    def parse_validated(self, query_string, parser, validator):
        """Helper to validate and parse a query."""
        validator.validate(query_string)
        return parser.parse(query_string)

    def test_simple_term(self, parser, validator):
        """Test parsing a single term."""
        query = self.parse_validated("[term a]", parser, validator)
        assert query.raw_query == "[term a]"
        assert len(query.root.children) == 1
        assert query.root.children[0].node_type == NodeType.TERM
        assert query.root.children[0].value == "term a"

    def test_two_terms_with_or(self, parser, validator):
        """Test parsing two terms with OR."""
        query = self.parse_validated("[term a] OR [term b]", parser, validator)
        assert len(query.root.children) == 3
        assert query.root.children[0].value == "term a"
        assert query.root.children[1].node_type == NodeType.CONNECTOR
        assert query.root.children[1].value == "or"
        assert query.root.children[2].value == "term b"

    def test_two_terms_with_and(self, parser, validator):
        """Test parsing two terms with AND."""
        query = self.parse_validated("[term a] AND [term b]", parser, validator)
        assert len(query.root.children) == 3
        assert query.root.children[0].value == "term a"
        assert query.root.children[1].value == "and"
        assert query.root.children[2].value == "term b"

    def test_and_not_operator(self, parser, validator):
        """Test parsing AND NOT operator."""
        query = self.parse_validated("[term a] AND NOT [term b]", parser, validator)
        assert len(query.root.children) == 3
        assert query.root.children[0].value == "term a"
        assert query.root.children[1].node_type == NodeType.CONNECTOR
        assert query.root.children[1].value == "and not"
        assert query.root.children[2].value == "term b"

    def test_grouped_query(self, parser, validator):
        """Test parsing grouped query."""
        query = self.parse_validated("([term a] OR [term b])", parser, validator)
        assert len(query.root.children) == 1
        assert query.root.children[0].node_type == NodeType.GROUP
        group = query.root.children[0]
        assert len(group.children) == 3
        assert group.children[0].value == "term a"
        assert group.children[1].value == "or"
        assert group.children[2].value == "term b"

    def test_nested_groups(self, parser, validator):
        """Test parsing nested groups."""
        query = self.parse_validated("[a] AND ([b] OR ([c] AND [d]))", parser, validator)
        assert len(query.root.children) == 3  # term, connector, group
        assert query.root.children[0].value == "a"
        assert query.root.children[1].value == "and"

        outer_group = query.root.children[2]
        assert outer_group.node_type == NodeType.GROUP
        # [b] OR ([c] AND [d])
        assert len(outer_group.children) == 3
        assert outer_group.children[0].value == "b"
        assert outer_group.children[1].value == "or"

        inner_group = outer_group.children[2]
        assert inner_group.node_type == NodeType.GROUP
        assert len(inner_group.children) == 3
        assert inner_group.children[0].value == "c"
        assert inner_group.children[1].value == "and"
        assert inner_group.children[2].value == "d"

    def test_complex_query_from_readme(self, parser, validator):
        """Test parsing complex query from README."""
        query = self.parse_validated(
            "[happiness] AND ([joy] OR [peace of mind]) AND NOT [stressful]", parser, validator
        )
        assert len(query.root.children) == 5  # term, AND, group, AND NOT, term
        assert query.root.children[0].value == "happiness"
        assert query.root.children[1].value == "and"
        assert query.root.children[2].node_type == NodeType.GROUP
        assert query.root.children[3].value == "and not"
        assert query.root.children[4].value == "stressful"

    def test_filter_code_extracted(self, parser, validator):
        """Test that filter codes are extracted correctly."""
        query = self.parse_validated("ti[title term]", parser, validator)
        assert query.root.children[0].filter_code == "ti"
        assert query.root.children[0].value == "title term"

    def test_filter_code_on_group(self, parser, validator):
        """Test that filter codes on groups are extracted."""
        query = self.parse_validated("tiabs([term a] OR [term b])", parser, validator)
        assert query.root.children[0].node_type == NodeType.GROUP
        assert query.root.children[0].filter_code == "tiabs"

    def test_multiple_filter_codes(self, parser, validator):
        """Test query with multiple different filter codes."""
        query = self.parse_validated("ti[title] AND abs[abstract]", parser, validator)
        assert query.root.children[0].filter_code == "ti"
        assert query.root.children[2].filter_code == "abs"

    def test_case_insensitive_operators(self, parser, validator):
        """Test that operators are case insensitive."""
        query = self.parse_validated("[term a] and [term b]", parser, validator)
        assert query.root.children[1].value == "and"

        query = self.parse_validated("[term a] Or [term b]", parser, validator)
        assert query.root.children[1].value == "or"

    def test_case_insensitive_filter_codes(self, parser, validator):
        """Test that filter codes are case insensitive."""
        query = self.parse_validated("TI[term]", parser, validator)
        assert query.root.children[0].filter_code == "ti"

        query = self.parse_validated("TIABS[term]", parser, validator)
        assert query.root.children[0].filter_code == "tiabs"

    def test_to_dict_and_from_dict(self, parser, validator):
        """Test query serialization and deserialization."""
        original = self.parse_validated("[term a] AND [term b]", parser, validator)
        data = original.to_dict()

        restored = Query.from_dict(data)
        assert restored.raw_query == original.raw_query
        assert len(restored.root.children) == len(original.root.children)

    def test_get_all_terms(self, parser, validator):
        """Test getting all terms from query."""
        query = self.parse_validated("[a] AND ([b] OR [c])", parser, validator)
        terms = query.get_all_terms()
        assert set(terms) == {"a", "b", "c"}

    def test_get_all_filters(self, parser, validator):
        """Test getting all filter codes from query."""
        query = self.parse_validated("ti[a] AND abs[b] AND key[c]", parser, validator)
        filters = query.get_all_filters()
        assert set(filters) == {"ti", "abs", "key"}
