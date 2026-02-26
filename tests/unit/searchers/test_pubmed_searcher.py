"""Unit tests for PubmedSearcher."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from xml.etree import ElementTree as ET

import pytest

from findpapers.core.author import Author
from findpapers.core.paper import PaperType
from findpapers.core.search import Database
from findpapers.core.source import SourceType
from findpapers.exceptions import UnsupportedQueryError
from findpapers.query.builders.pubmed import PubmedQueryBuilder
from findpapers.searchers.pubmed import PubmedSearcher, _normalize_month


class TestNormalizeMonth:
    """Tests for _normalize_month helper."""

    def test_numeric_month_padded(self):
        """Numeric month string is zero-padded."""
        assert _normalize_month("3") == "03"
        assert _normalize_month("12") == "12"

    def test_abbreviated_name_jan(self):
        """'Jan' maps to '01'."""
        assert _normalize_month("Jan") == "01"

    def test_abbreviated_name_dec(self):
        """'Dec' maps to '12'."""
        assert _normalize_month("Dec") == "12"

    def test_case_insensitive(self):
        """Month names are case-insensitive."""
        assert _normalize_month("JAN") == "01"
        assert _normalize_month("jan") == "01"

    def test_invalid_returns_01(self):
        """Non-numeric, non-abbreviated input returns '01'."""
        assert _normalize_month("Spring") == "01"


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
        assert PubmedSearcher().name == Database.PUBMED

    def test_rate_interval_without_key(self):
        """Default rate interval is used when no API key provided."""
        from findpapers.searchers.pubmed import _MIN_REQUEST_INTERVAL_DEFAULT

        searcher = PubmedSearcher()
        assert searcher._request_interval == _MIN_REQUEST_INTERVAL_DEFAULT

    def test_rate_interval_with_key(self):
        """Faster rate interval used when API key is provided."""
        from findpapers.searchers.pubmed import (
            _MIN_REQUEST_INTERVAL_DEFAULT,
            _MIN_REQUEST_INTERVAL_WITH_KEY,
        )

        searcher = PubmedSearcher(api_key="key")
        assert searcher._request_interval == _MIN_REQUEST_INTERVAL_WITH_KEY
        assert searcher._request_interval < _MIN_REQUEST_INTERVAL_DEFAULT


class TestPubmedSearcherParsePaper:
    """Tests for _parse_paper using real efetch XML data."""

    def test_parse_sample_xml(self, pubmed_efetch_xml):
        """Parsing sample efetch XML returns at least one valid paper."""
        tree = ET.fromstring(pubmed_efetch_xml)
        articles = tree.findall(".//PubmedArticle")
        assert len(articles) > 0

        papers = [PubmedSearcher()._parse_paper(a) for a in articles]
        valid = [p for p in papers if p is not None]
        assert len(valid) > 0

    def test_paper_has_database_tag(self, pubmed_efetch_xml):
        """Parsed paper has 'PubMed' in databases set."""
        tree = ET.fromstring(pubmed_efetch_xml)
        articles = tree.findall(".//PubmedArticle")
        paper = PubmedSearcher()._parse_paper(articles[0])
        assert paper is not None
        assert Database.PUBMED in paper.databases

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
        assert PubmedSearcher()._parse_paper(el) is None

    def test_missing_medline_citation_returns_none(self):
        """Element without MedlineCitation returns None."""
        xml_str = "<PubmedArticle></PubmedArticle>"
        el = ET.fromstring(xml_str)
        assert PubmedSearcher()._parse_paper(el) is None

    def test_author_with_initials_only(self):
        """Author with LastName + Initials (no ForeName) is parsed."""
        xml_str = """
        <PubmedArticle>
            <MedlineCitation>
                <PMID>12345</PMID>
                <Article>
                    <ArticleTitle>A Paper</ArticleTitle>
                    <AuthorList>
                        <Author>
                            <LastName>Smith</LastName>
                            <Initials>J</Initials>
                        </Author>
                    </AuthorList>
                </Article>
            </MedlineCitation>
        </PubmedArticle>
        """
        el = ET.fromstring(xml_str)
        paper = PubmedSearcher()._parse_paper(el)
        assert paper is not None
        assert paper.authors == [Author(name="J Smith")]

    def test_keywords_extracted(self):
        """Keywords and MeSH descriptors are collected."""
        xml_str = """
        <PubmedArticle>
            <MedlineCitation>
                <PMID>99</PMID>
                <Article>
                    <ArticleTitle>Test Paper</ArticleTitle>
                </Article>
                <KeywordList>
                    <Keyword>Deep Learning</Keyword>
                </KeywordList>
                <MeshHeadingList>
                    <MeshHeading>
                        <DescriptorName>Neural Networks, Computer</DescriptorName>
                    </MeshHeading>
                </MeshHeadingList>
            </MedlineCitation>
        </PubmedArticle>
        """
        el = ET.fromstring(xml_str)
        paper = PubmedSearcher()._parse_paper(el)
        assert paper is not None
        assert paper.keywords is not None
        assert "Deep Learning" in paper.keywords
        assert "Neural Networks, Computer" in paper.keywords

    def test_doi_extracted(self):
        """DOI from ArticleId is extracted."""
        xml_str = """
        <PubmedArticle>
            <MedlineCitation>
                <PMID>55</PMID>
                <Article>
                    <ArticleTitle>DOI Paper</ArticleTitle>
                </Article>
            </MedlineCitation>
            <PubmedData>
                <ArticleIdList>
                    <ArticleId IdType="doi">10.1234/test</ArticleId>
                </ArticleIdList>
            </PubmedData>
        </PubmedArticle>
        """
        el = ET.fromstring(xml_str)
        paper = PubmedSearcher()._parse_paper(el)
        assert paper is not None
        assert paper.doi == "10.1234/test"

    def test_url_from_pmid(self):
        """URL is built from the PMID."""
        xml_str = """
        <PubmedArticle>
            <MedlineCitation>
                <PMID>12345</PMID>
                <Article>
                    <ArticleTitle>URL Paper</ArticleTitle>
                </Article>
            </MedlineCitation>
        </PubmedArticle>
        """
        el = ET.fromstring(xml_str)
        paper = PubmedSearcher()._parse_paper(el)
        assert paper is not None
        assert paper.url == "https://pubmed.ncbi.nlm.nih.gov/12345/"

    def test_source_from_journal(self):
        """Source is built from Journal title and ISSN."""
        xml_str = """
        <PubmedArticle>
            <MedlineCitation>
                <PMID>1</PMID>
                <Article>
                    <ArticleTitle>Journal Paper</ArticleTitle>
                    <Journal>
                        <ISSN>1234-5678</ISSN>
                        <Title>Nature</Title>
                        <ISOAbbreviation>Nature</ISOAbbreviation>
                    </Journal>
                </Article>
            </MedlineCitation>
        </PubmedArticle>
        """
        el = ET.fromstring(xml_str)
        paper = PubmedSearcher()._parse_paper(el)
        assert paper is not None
        assert paper.source is not None
        assert paper.source.title == "Nature"
        assert paper.source.issn == "1234-5678"

    def test_source_type_is_always_journal(self):
        """PubMed sources always have source_type=JOURNAL."""
        xml_str = """
        <PubmedArticle>
            <MedlineCitation>
                <PMID>1</PMID>
                <Article>
                    <ArticleTitle>Journal Paper</ArticleTitle>
                    <Journal>
                        <Title>Some Journal</Title>
                    </Journal>
                </Article>
            </MedlineCitation>
        </PubmedArticle>
        """
        el = ET.fromstring(xml_str)
        paper = PubmedSearcher()._parse_paper(el)
        assert paper is not None
        assert paper.source is not None
        assert paper.source.source_type == SourceType.JOURNAL

    def test_pages_from_medline_pgn(self):
        """Pages are extracted from MedlinePgn in Pagination element."""
        xml_str = """
        <PubmedArticle>
            <MedlineCitation>
                <PMID>1</PMID>
                <Article>
                    <ArticleTitle>Test</ArticleTitle>
                    <Pagination>
                        <StartPage>100</StartPage>
                        <EndPage>115</EndPage>
                        <MedlinePgn>100-115</MedlinePgn>
                    </Pagination>
                </Article>
            </MedlineCitation>
        </PubmedArticle>
        """
        el = ET.fromstring(xml_str)
        paper = PubmedSearcher()._parse_paper(el)
        assert paper is not None
        assert paper.page_range == "100-115"

    def test_pages_from_start_end_when_no_medline_pgn(self):
        """Pages are built from StartPage\u2013EndPage when MedlinePgn is absent."""
        xml_str = """
        <PubmedArticle>
            <MedlineCitation>
                <PMID>1</PMID>
                <Article>
                    <ArticleTitle>Test</ArticleTitle>
                    <Pagination>
                        <StartPage>200</StartPage>
                        <EndPage>210</EndPage>
                    </Pagination>
                </Article>
            </MedlineCitation>
        </PubmedArticle>
        """
        el = ET.fromstring(xml_str)
        paper = PubmedSearcher()._parse_paper(el)
        assert paper is not None
        assert paper.page_range == "200\u2013210"

    def test_pages_from_sample_data(self, pubmed_efetch_xml):
        """Pages are extracted from the real PubMed sample data."""
        tree = ET.fromstring(pubmed_efetch_xml)
        articles = tree.findall(".//PubmedArticle")
        paper = PubmedSearcher()._parse_paper(articles[0])
        assert paper is not None
        assert paper.page_range is not None
        assert "1148" in paper.page_range

    def test_paper_type_journal_article(self):
        """Journal Article publication type maps to PaperType.ARTICLE."""
        xml_str = """
        <PubmedArticle>
            <MedlineCitation>
                <Article>
                    <ArticleTitle>T</ArticleTitle>
                    <PublicationTypeList>
                        <PublicationType>Journal Article</PublicationType>
                    </PublicationTypeList>
                </Article>
            </MedlineCitation>
        </PubmedArticle>
        """
        el = ET.fromstring(xml_str)
        paper = PubmedSearcher()._parse_paper(el)
        assert paper is not None
        assert paper.paper_type is PaperType.ARTICLE

    def test_paper_type_congress(self):
        """Congress publication type maps to PaperType.INPROCEEDINGS."""
        xml_str = """
        <PubmedArticle>
            <MedlineCitation>
                <Article>
                    <ArticleTitle>T</ArticleTitle>
                    <PublicationTypeList>
                        <PublicationType>Congress</PublicationType>
                    </PublicationTypeList>
                </Article>
            </MedlineCitation>
        </PubmedArticle>
        """
        el = ET.fromstring(xml_str)
        paper = PubmedSearcher()._parse_paper(el)
        assert paper is not None
        assert paper.paper_type is PaperType.INPROCEEDINGS

    def test_paper_type_meeting_abstract(self):
        """Meeting Abstract publication type maps to PaperType.INPROCEEDINGS."""
        xml_str = """
        <PubmedArticle>
            <MedlineCitation>
                <Article>
                    <ArticleTitle>T</ArticleTitle>
                    <PublicationTypeList>
                        <PublicationType>Meeting Abstract</PublicationType>
                    </PublicationTypeList>
                </Article>
            </MedlineCitation>
        </PubmedArticle>
        """
        el = ET.fromstring(xml_str)
        paper = PubmedSearcher()._parse_paper(el)
        assert paper is not None
        assert paper.paper_type is PaperType.INPROCEEDINGS

    def test_paper_type_academic_dissertation(self):
        """Academic Dissertation maps to PaperType.PHDTHESIS."""
        xml_str = """
        <PubmedArticle>
            <MedlineCitation>
                <Article>
                    <ArticleTitle>T</ArticleTitle>
                    <PublicationTypeList>
                        <PublicationType>Academic Dissertation</PublicationType>
                    </PublicationTypeList>
                </Article>
            </MedlineCitation>
        </PubmedArticle>
        """
        el = ET.fromstring(xml_str)
        paper = PubmedSearcher()._parse_paper(el)
        assert paper is not None
        assert paper.paper_type is PaperType.PHDTHESIS

    def test_paper_type_technical_report(self):
        """Technical Report maps to PaperType.TECHREPORT."""
        xml_str = """
        <PubmedArticle>
            <MedlineCitation>
                <Article>
                    <ArticleTitle>T</ArticleTitle>
                    <PublicationTypeList>
                        <PublicationType>Technical Report</PublicationType>
                    </PublicationTypeList>
                </Article>
            </MedlineCitation>
        </PubmedArticle>
        """
        el = ET.fromstring(xml_str)
        paper = PubmedSearcher()._parse_paper(el)
        assert paper is not None
        assert paper.paper_type is PaperType.TECHREPORT

    def test_paper_type_preprint(self):
        """Preprint publication type maps to PaperType.UNPUBLISHED."""
        xml_str = """
        <PubmedArticle>
            <MedlineCitation>
                <Article>
                    <ArticleTitle>T</ArticleTitle>
                    <PublicationTypeList>
                        <PublicationType>Preprint</PublicationType>
                    </PublicationTypeList>
                </Article>
            </MedlineCitation>
        </PubmedArticle>
        """
        el = ET.fromstring(xml_str)
        paper = PubmedSearcher()._parse_paper(el)
        assert paper is not None
        assert paper.paper_type is PaperType.UNPUBLISHED

    def test_paper_type_review_maps_to_article(self):
        """Review publication type maps to PaperType.ARTICLE."""
        xml_str = """
        <PubmedArticle>
            <MedlineCitation>
                <Article>
                    <ArticleTitle>T</ArticleTitle>
                    <PublicationTypeList>
                        <PublicationType>Review</PublicationType>
                    </PublicationTypeList>
                </Article>
            </MedlineCitation>
        </PubmedArticle>
        """
        el = ET.fromstring(xml_str)
        paper = PubmedSearcher()._parse_paper(el)
        assert paper is not None
        assert paper.paper_type is PaperType.ARTICLE

    def test_paper_type_congress_takes_priority_over_journal_article(self):
        """When multiple pub types, more specific type wins by priority order."""
        xml_str = """
        <PubmedArticle>
            <MedlineCitation>
                <Article>
                    <ArticleTitle>T</ArticleTitle>
                    <PublicationTypeList>
                        <PublicationType>Journal Article</PublicationType>
                        <PublicationType>Congress</PublicationType>
                    </PublicationTypeList>
                </Article>
            </MedlineCitation>
        </PubmedArticle>
        """
        el = ET.fromstring(xml_str)
        paper = PubmedSearcher()._parse_paper(el)
        assert paper is not None
        assert paper.paper_type is PaperType.INPROCEEDINGS

    def test_paper_type_none_when_no_publication_type(self):
        """No PublicationTypeList results in paper_type being None."""
        xml_str = """
        <PubmedArticle>
            <MedlineCitation>
                <Article>
                    <ArticleTitle>T</ArticleTitle>
                </Article>
            </MedlineCitation>
        </PubmedArticle>
        """
        el = ET.fromstring(xml_str)
        paper = PubmedSearcher()._parse_paper(el)
        assert paper is not None
        assert paper.paper_type is None

    def test_paper_type_none_for_unrecognised_type(self):
        """Unrecognised publication type results in paper_type being None."""
        xml_str = """
        <PubmedArticle>
            <MedlineCitation>
                <Article>
                    <ArticleTitle>T</ArticleTitle>
                    <PublicationTypeList>
                        <PublicationType>Letter</PublicationType>
                    </PublicationTypeList>
                </Article>
            </MedlineCitation>
        </PubmedArticle>
        """
        el = ET.fromstring(xml_str)
        paper = PubmedSearcher()._parse_paper(el)
        assert paper is not None
        assert paper.paper_type is None


class TestPubmedSearcherSearch:
    """Tests for search() with mocked HTTP calls."""

    def test_search_raises_for_question_mark_wildcard(self, wildcard_query):
        """Search raises UnsupportedQueryError for '?' wildcard (not supported by PubMed)."""
        # The wildcard_query uses 'machine*' which is valid (>= 4 chars).
        # Override with '?' test via a custom query.
        from findpapers.query.parser import QueryParser
        from findpapers.query.propagator import FilterPropagator

        parser = QueryParser()
        propagator = FilterPropagator()
        q = propagator.propagate(parser.parse("[mac?]"))
        searcher = PubmedSearcher()
        with pytest.raises(UnsupportedQueryError):
            searcher.search(q)

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
            "findpapers.searchers.base.requests.get", side_effect=side_effects
        ), patch.object(searcher, "_rate_limit"):
            papers = searcher.search(simple_query)

        assert len(papers) > 0
        assert all(Database.PUBMED in p.databases for p in papers)

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
            "findpapers.searchers.base.requests.get",
            side_effect=[esearch_mock, efetch_mock],
        ), patch.object(searcher, "_rate_limit"):
            papers = searcher.search(simple_query, max_papers=2)

        assert len(papers) <= 2

    def test_esearch_error_breaks_loop(self, simple_query):
        """Exception in _search_ids breaks the loop and returns empty list."""
        searcher = PubmedSearcher()

        with patch.object(searcher, "_search_ids", side_effect=Exception("network error")):
            papers = searcher.search(simple_query)

        assert papers == []

    def test_efetch_error_breaks_loop(self, simple_query, pubmed_esearch_json, mock_response):
        """Exception in _fetch_details breaks the loop."""
        searcher = PubmedSearcher()
        esearch_mock = mock_response(json_data=pubmed_esearch_json)
        esearch_mock.raise_for_status = MagicMock()

        with patch(
            "findpapers.searchers.base.requests.get", return_value=esearch_mock
        ), patch.object(
            searcher, "_fetch_details", side_effect=Exception("fetch error")
        ), patch.object(
            searcher, "_rate_limit"
        ):
            papers = searcher.search(simple_query)

        assert papers == []

    def test_progress_callback_called(
        self,
        simple_query,
        pubmed_esearch_json,
        pubmed_efetch_xml,
        mock_response,
    ):
        """Progress callback is invoked after each page."""
        searcher = PubmedSearcher()
        esearch_mock = mock_response(json_data=pubmed_esearch_json)
        esearch_mock.raise_for_status = MagicMock()
        efetch_mock = mock_response(text=pubmed_efetch_xml)
        efetch_mock.raise_for_status = MagicMock()
        callback = MagicMock()

        with patch(
            "findpapers.searchers.base.requests.get",
            side_effect=[esearch_mock, efetch_mock],
        ), patch.object(searcher, "_rate_limit"):
            searcher.search(simple_query, progress_callback=callback)

        callback.assert_called()

    def test_search_raises_surfaces_via_base(self, simple_query):
        """Unexpected exception in _fetch_papers returns an empty list."""
        searcher = PubmedSearcher()

        with patch.object(searcher, "_fetch_papers", side_effect=RuntimeError("boom")):
            papers = searcher.search(simple_query)

        assert papers == []
