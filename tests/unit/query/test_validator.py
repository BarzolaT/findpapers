"""Tests for Query validation logic."""

import pytest

from findpapers.core.query import QueryValidationError
from findpapers.query.validator import QueryValidator


class TestQueryValidator:
    """Test query validation."""

    @pytest.fixture
    def validator(self):
        """Return a QueryValidator instance."""
        return QueryValidator()

    def test_empty_query_raises_error(self, validator):
        """Test that empty query raises an error."""
        with pytest.raises(QueryValidationError, match="Query cannot be empty"):
            validator.validate("")

    def test_simple_valid_query(self, validator):
        """Test that a simple valid query passes validation."""
        validator.validate("[machine learning]")

    def test_two_terms_with_and(self, validator):
        """Test two terms with AND operator."""
        validator.validate("[term a] AND [term b]")

    def test_two_terms_with_or(self, validator):
        """Test two terms with OR operator."""
        validator.validate("[term a] OR [term b]")

    def test_and_not_operator(self, validator):
        """Test AND NOT operator."""
        validator.validate("[term a] AND NOT [term b]")

    def test_grouped_query(self, validator):
        """Test grouped query with parentheses."""
        validator.validate("([term a] OR [term b])")

    def test_unbalanced_brackets_raises_error(self, validator):
        """Test that unbalanced brackets raise an error."""
        with pytest.raises(QueryValidationError, match="Unbalanced square brackets"):
            validator.validate("[term a")

    def test_unbalanced_parentheses_raises_error(self, validator):
        """Test that unbalanced parentheses raise an error."""
        with pytest.raises(QueryValidationError, match="Unbalanced parentheses"):
            validator.validate("([term a]")

    def test_empty_term_raises_error(self, validator):
        """Test that empty terms raise an error."""
        with pytest.raises(QueryValidationError, match="Terms cannot be empty"):
            validator.validate("[]")

    def test_consecutive_terms_without_operator_raises_error(self, validator):
        """Test that consecutive terms without operator raise an error."""
        with pytest.raises(
            QueryValidationError, match="Terms must be separated by boolean operators"
        ):
            validator.validate("[term a] [term b]")

    def test_wildcard_at_start_raises_error(self, validator):
        """Test that wildcard at start raises an error."""
        with pytest.raises(
            QueryValidationError, match="Wildcards cannot be used at the start of a search term"
        ):
            validator.validate("[?term]")

    def test_wildcard_asterisk_valid(self, validator):
        """Test that asterisk wildcard is valid when used correctly."""
        validator.validate("[mac*]")

    def test_wildcard_question_valid(self, validator):
        """Test that question mark wildcard is valid."""
        validator.validate("[wom?n]")

    def test_multiple_wildcards_raises_error(self, validator):
        """Test that multiple wildcards raise an error."""
        with pytest.raises(
            QueryValidationError, match="Only one wildcard can be included in a search term"
        ):
            validator.validate("[m*c?]")

    def test_asterisk_requires_3_chars_before(self, validator):
        """Test that asterisk requires 3 characters before."""
        with pytest.raises(
            QueryValidationError, match="A minimum of 3 characters preceding the asterisk wildcard"
        ):
            validator.validate("[ma*]")

    def test_asterisk_only_at_end(self, validator):
        """Test that asterisk can only be at the end."""
        with pytest.raises(
            QueryValidationError,
            match="The asterisk wildcard can only be used at the end of a search term",
        ):
            validator.validate("[m*c]")

    def test_valid_filter_codes(self, validator):
        """Test that valid filter codes are accepted."""
        validator.validate("ti[title term]")
        validator.validate("abs[abstract term]")
        validator.validate("key[keyword term]")
        validator.validate("au[author name]")
        validator.validate("src[publication name]")
        validator.validate("af[affiliation name]")
        validator.validate("tiabs[term]")
        validator.validate("tiabskey[term]")

    def test_invalid_filter_code_raises_error(self, validator):
        """Test that invalid filter codes raise an error."""
        with pytest.raises(QueryValidationError, match="Invalid filter code"):
            validator.validate("invalid[term]")

    def test_filter_code_case_insensitive(self, validator):
        """Test that filter codes are case insensitive."""
        validator.validate("TI[term]")
        validator.validate("ABS[term]")
        validator.validate("TIABS[term]")

    def test_not_without_and_raises_error(self, validator):
        """Test that NOT without AND raises an error."""
        with pytest.raises(QueryValidationError, match="NOT operator must be preceded by AND"):
            validator.validate("[term a] NOT [term b]")

    def test_operators_require_whitespace(self, validator):
        """Test that operators require whitespace."""
        with pytest.raises(QueryValidationError, match="Operators must have whitespace"):
            validator.validate("[term a]AND[term b]")
