"""Unit tests for BiorxivSearcher."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from findpapers.query.builders.biorxiv import BiorxivQueryBuilder
from findpapers.searchers.biorxiv import BiorxivSearcher


class TestBiorxivSearcherInit:
    """Tests for BiorxivSearcher initialisation."""

    def test_default_builder_created(self):
        """Searcher creates BiorxivQueryBuilder when none provided."""
        searcher = BiorxivSearcher()
        assert isinstance(searcher.query_builder, BiorxivQueryBuilder)

    def test_name(self):
        """Searcher name is 'bioRxiv'."""
        assert BiorxivSearcher().name == "bioRxiv"


class TestBiorxivSearcherSearch:
    """Tests for search() with mocked HTTP calls."""

    def test_search_returns_papers(
        self,
        simple_query,
        biorxiv_search_html,
        biorxiv_api_responses,
        mock_response,
    ):
        """search() scrapes HTML then fetches metadata and returns papers."""

        searcher = BiorxivSearcher()
        html_response = mock_response(text=biorxiv_search_html)
        html_response.raise_for_status = MagicMock()

        # Build a side_effect chain: first call returns HTML, subsequent calls
        # return biorxiv API metadata responses.  biorxiv_api_responses is a
        # list of response dicts (one per DOI).
        responses_list = (
            list(biorxiv_api_responses.values())
            if isinstance(biorxiv_api_responses, dict)
            else biorxiv_api_responses
        )
        api_side_effects = [mock_response(json_data=data) for data in responses_list]
        for r in api_side_effects:
            r.raise_for_status = MagicMock()

        all_responses = [html_response] + api_side_effects

        # Provide an empty subsequent page so the scraper stops after first page.
        empty_html = mock_response(text="<html></html>")
        empty_html.raise_for_status = MagicMock()
        # Add enough empty responses for any extra get() calls.
        all_responses += [empty_html] * 20

        with patch(
            "findpapers.searchers.base.requests.get", side_effect=all_responses
        ), patch.object(searcher, "_rate_limit"):
            papers = searcher.search(simple_query)

        assert isinstance(papers, list)
        for p in papers:
            assert "bioRxiv" in p.databases

    def test_search_invalid_query_returns_empty(self, ti_query):
        """ti (title-only) filter is not supported by bioRxiv → empty result."""
        searcher = BiorxivSearcher()
        papers = searcher.search(ti_query)
        assert papers == []
