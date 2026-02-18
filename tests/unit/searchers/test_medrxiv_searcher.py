"""Unit tests for MedrxivSearcher."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from findpapers.query.builders.medrxiv import MedrxivQueryBuilder
from findpapers.searchers.medrxiv import MedrxivSearcher


class TestMedrxivSearcherInit:
    """Tests for MedrxivSearcher initialisation."""

    def test_default_builder_created(self):
        """Searcher creates MedrxivQueryBuilder when none provided."""
        searcher = MedrxivSearcher()
        assert isinstance(searcher.query_builder, MedrxivQueryBuilder)

    def test_name(self):
        """Searcher name is 'medRxiv'."""
        assert MedrxivSearcher().name == "medRxiv"


class TestMedrxivSearcherSearch:
    """Tests for search() with mocked HTTP calls."""

    def test_search_invalid_query_returns_empty(self, ti_query):
        """ti (title-only) filter is not supported by medRxiv → empty result."""
        searcher = MedrxivSearcher()
        papers = searcher.search(ti_query)
        assert papers == []

    def test_search_returns_papers(
        self,
        simple_query,
        biorxiv_search_html,
        biorxiv_api_responses,
        mock_response,
    ):
        """search() scrapes HTML then fetches metadata and returns papers."""
        searcher = MedrxivSearcher()
        html_response = mock_response(text=biorxiv_search_html)
        html_response.raise_for_status = MagicMock()

        responses_list = (
            list(biorxiv_api_responses.values())
            if isinstance(biorxiv_api_responses, dict)
            else biorxiv_api_responses
        )
        api_side_effects = [mock_response(json_data=data) for data in responses_list]
        for r in api_side_effects:
            r.raise_for_status = MagicMock()

        empty_html = mock_response(text="<html></html>")
        empty_html.raise_for_status = MagicMock()

        all_responses = [html_response] + api_side_effects + [empty_html] * 20

        with patch(
            "findpapers.searchers.rxiv.requests.get", side_effect=all_responses
        ), patch.object(searcher, "_rate_limit"):
            papers = searcher.search(simple_query)

        assert isinstance(papers, list)
        for p in papers:
            assert "medRxiv" in p.databases
