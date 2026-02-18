"""Unit tests for PubmedSearcher."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from xml.etree import ElementTree as ET

from findpapers.query.builders.pubmed import PubmedQueryBuilder
from findpapers.searchers.pubmed import PubmedSearcher


class TestPubmedSearcherInit:
    """Tests for PubmedSearcher initialisation."""

    def test_default_builder_created(self):
        """Searcher creates PubmedQueryBuilder when none provided."""
        searcher = PubmedSearcher()
        assert isinstance(searcher.query_builder, PubmedQueryBuilder)

    def test_api_key_stored(self):
        """API key is stored on the instance."""
        searcher = PubmedSearcher(api_key="test_key")
        assert searcher._api_key == "test_key"

    def test_name(self):
        """Searcher name is 'PubMed'."""
        assert PubmedSearcher().name == "PubMed"


class TestPubmedSearcherParsePaper:
    """Tests for _parse_paper using real efetch XML data."""

    def test_parse_sample_xml(self, pubmed_efetch_xml):
        """Parsing sample efetch XML returns at least one valid paper."""
        tree = ET.fromstring(pubmed_efetch_xml)
        articles = tree.findall(".//PubmedArticle")
        assert len(articles) > 0

        papers = [PubmedSearcher._parse_paper(a) for a in articles]
        valid = [p for p in papers if p is not None]
        assert len(valid) > 0

    def test_paper_has_database_tag(self, pubmed_efetch_xml):
        """Parsed paper has 'PubMed' in databases set."""
        tree = ET.fromstring(pubmed_efetch_xml)
        articles = tree.findall(".//PubmedArticle")
        paper = PubmedSearcher._parse_paper(articles[0])
        assert paper is not None
        assert "PubMed" in paper.databases

    def test_missing_title_returns_none(self):
        """Article element without title returns None."""
        xml_str = """
        <PubmedArticle>
            <MedlineCitation>
                <Article>
                    <ArticleTitle>   </ArticleTitle>
                </Article>
            </MedlineCitation>
        </PubmedArticle>
        """
        el = ET.fromstring(xml_str)
        assert PubmedSearcher._parse_paper(el) is None


class TestPubmedSearcherSearch:
    """Tests for search() with mocked HTTP calls."""

    def test_search_skipped_for_question_mark_wildcard(self, wildcard_query):
        """Search is skipped when query contains '?' wildcard (not supported by PubMed)."""
        # The wildcard_query uses 'machine*' which is valid (>= 4 chars).
        # Override with '?' test via a custom query.
        from findpapers.query.parser import QueryParser
        from findpapers.query.propagator import FilterPropagator

        parser = QueryParser()
        propagator = FilterPropagator()
        q = propagator.propagate(parser.parse("[mac?]"))
        searcher = PubmedSearcher()
        papers = searcher.search(q)
        assert papers == []

    def test_search_returns_papers(
        self,
        simple_query,
        pubmed_esearch_json,
        pubmed_efetch_xml,
        mock_response,
    ):
        """search() returns papers parsed from esearch + efetch responses."""
        searcher = PubmedSearcher()
        esearch_mock = mock_response(json_data=pubmed_esearch_json)
        esearch_mock.raise_for_status = MagicMock()
        efetch_mock = mock_response(text=pubmed_efetch_xml)
        efetch_mock.raise_for_status = MagicMock()

        side_effects = [esearch_mock, efetch_mock]

        with patch(
            "findpapers.searchers.pubmed.requests.get", side_effect=side_effects
        ), patch.object(searcher, "_rate_limit"):
            papers = searcher.search(simple_query)

        assert len(papers) > 0
        assert all("PubMed" in p.databases for p in papers)

    def test_max_papers_respected(
        self,
        simple_query,
        pubmed_esearch_json,
        pubmed_efetch_xml,
        mock_response,
    ):
        """search() returns no more than max_papers papers."""
        searcher = PubmedSearcher()
        esearch_mock = mock_response(json_data=pubmed_esearch_json)
        esearch_mock.raise_for_status = MagicMock()
        efetch_mock = mock_response(text=pubmed_efetch_xml)
        efetch_mock.raise_for_status = MagicMock()

        with patch(
            "findpapers.searchers.pubmed.requests.get",
            side_effect=[esearch_mock, efetch_mock],
        ), patch.object(searcher, "_rate_limit"):
            papers = searcher.search(simple_query, max_papers=2)

        assert len(papers) <= 2
