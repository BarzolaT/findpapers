"""Tests for filter propagation logic."""

import pytest

from findpapers.core.query import NodeType
from findpapers.query.parser import QueryParser
from findpapers.query.propagator import FilterPropagator
from findpapers.query.validator import QueryValidator


class TestFilterPropagator:
    """Test filter propagation."""

    @pytest.fixture
    def parser(self):
        """Return a QueryParser instance."""
        return QueryParser()

    @pytest.fixture
    def validator(self):
        """Return a QueryValidator instance."""
        return QueryValidator()

    @pytest.fixture
    def propagator(self):
        """Return a FilterPropagator instance."""
        return FilterPropagator()

    def parse_and_propagate(self, query_string, parser, validator, propagator):
        """Helper to validate, parse, and propagate a query."""
        validator.validate(query_string)
        query = parser.parse(query_string)
        return propagator.propagate(query)

    def test_simple_term_without_filter_inherits_none(self, parser, validator, propagator):
        """Test that a simple term without filter has inherited_filter_code as None."""
        query = self.parse_and_propagate("[term]", parser, validator, propagator)
        term = query.root.children[0]
        assert term.filter_code is None
        assert term.inherited_filter_code is None

    def test_term_with_explicit_filter(self, parser, validator, propagator):
        """Test that a term with explicit filter uses it."""
        query = self.parse_and_propagate("ti[term]", parser, validator, propagator)
        term = query.root.children[0]
        assert term.filter_code == "ti"
        assert term.inherited_filter_code == "ti"

    def test_group_filter_propagates_to_children(self, parser, validator, propagator):
        """Test that group filter propagates to child terms."""
        query = self.parse_and_propagate("ti([a] OR [b])", parser, validator, propagator)
        group = query.root.children[0]
        assert group.filter_code == "ti"
        assert group.inherited_filter_code == "ti"

        # Children should inherit
        term_a = group.children[0]
        term_b = group.children[2]
        assert term_a.filter_code is None
        assert term_a.inherited_filter_code == "ti"
        assert term_b.filter_code is None
        assert term_b.inherited_filter_code == "ti"

    def test_innermost_filter_wins(self, parser, validator, propagator):
        """Test that innermost filter overrides parent filter."""
        query = self.parse_and_propagate("ti([a] OR abs[b])", parser, validator, propagator)
        group = query.root.children[0]

        term_a = group.children[0]
        term_b = group.children[2]

        # term_a inherits from group
        assert term_a.inherited_filter_code == "ti"

        # term_b has explicit filter that wins
        assert term_b.filter_code == "abs"
        assert term_b.inherited_filter_code == "abs"

    def test_nested_groups_propagate_correctly(self, parser, validator, propagator):
        """Test that nested groups propagate filters correctly."""
        query = self.parse_and_propagate(
            "ti([a] AND abs([b] OR [c]))", parser, validator, propagator
        )
        outer_group = query.root.children[0]
        assert outer_group.filter_code == "ti"

        term_a = outer_group.children[0]
        assert term_a.inherited_filter_code == "ti"

        inner_group = outer_group.children[2]
        assert inner_group.filter_code == "abs"
        assert inner_group.inherited_filter_code == "abs"  # overrides parent

        term_b = inner_group.children[0]
        term_c = inner_group.children[2]
        assert term_b.inherited_filter_code == "abs"  # from inner group
        assert term_c.inherited_filter_code == "abs"  # from inner group

    def test_children_match_filter_all_same(self, parser, validator, propagator):
        """Test children_match_filter when all children use same filter."""
        query = self.parse_and_propagate("ti([a] OR [b])", parser, validator, propagator)
        group = query.root.children[0]
        assert group.children_match_filter is True

    def test_children_match_filter_different(self, parser, validator, propagator):
        """Test children_match_filter when children use different filters."""
        query = self.parse_and_propagate("ti([a] OR abs[b])", parser, validator, propagator)
        group = query.root.children[0]
        assert group.children_match_filter is False

    def test_children_match_filter_nested(self, parser, validator, propagator):
        """Test children_match_filter with nested groups."""
        # All children (including nested) use ti
        query = self.parse_and_propagate("ti([a] AND ([b] OR [c]))", parser, validator, propagator)
        outer_group = query.root.children[0]
        assert outer_group.children_match_filter is True

        # Nested group has different filter
        query = self.parse_and_propagate(
            "ti([a] AND abs([b] OR [c]))", parser, validator, propagator
        )
        outer_group = query.root.children[0]
        assert outer_group.children_match_filter is False

    def test_mixed_filters_in_query(self, parser, validator, propagator):
        """Test query with mixed filter codes."""
        query = self.parse_and_propagate(
            "ti[title] AND abs[abstract] AND key[keyword]",
            parser,
            validator,
            propagator,
        )
        terms = [child for child in query.root.children if child.node_type == NodeType.TERM]
        assert terms[0].inherited_filter_code == "ti"
        assert terms[1].inherited_filter_code == "abs"
        assert terms[2].inherited_filter_code == "key"

    def test_no_filter_defaults_to_none(self, parser, validator, propagator):
        """Test that queries without filters have None as inherited filter."""
        query = self.parse_and_propagate("[a] AND [b]", parser, validator, propagator)
        terms = [child for child in query.root.children if child.node_type == NodeType.TERM]
        assert terms[0].inherited_filter_code is None
        assert terms[1].inherited_filter_code is None
