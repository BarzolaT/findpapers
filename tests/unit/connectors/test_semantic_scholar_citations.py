"""Unit tests for SemanticScholarConnector citation methods."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from findpapers.connectors.semantic_scholar import SemanticScholarConnector
from tests.conftest import make_paper


def _make_ss_paper_record(
    paper_id: str = "abc123",
    doi: str = "10.1000/ref",
    title: str = "Referenced Paper",
) -> dict:
    """Create a minimal Semantic Scholar paper record for mocking."""
    return {
        "paperId": paper_id,
        "externalIds": {"DOI": doi},
        "title": title,
        "abstract": "An abstract.",
        "authors": [{"name": "Author One", "authorId": "111"}],
        "year": 2024,
        "publicationDate": "2024-01-15",
        "journal": {"name": "Test Journal"},
        "venue": "",
        "citationCount": 10,
        "openAccessPdf": None,
        "url": f"https://semanticscholar.org/paper/{paper_id}",
        "fieldsOfStudy": [],
        "publicationTypes": ["JournalArticle"],
        "publicationVenue": None,
    }


# ---------------------------------------------------------------------------
# Tests: fetch_references
# ---------------------------------------------------------------------------


class TestSemanticScholarFetchReferences:
    """Tests for SemanticScholarConnector.fetch_references."""

    def test_returns_empty_for_paper_without_doi(self) -> None:
        """Papers without DOI return empty list."""
        connector = SemanticScholarConnector()
        paper = make_paper(doi=None)

        result = connector.fetch_references(paper)

        assert result == []

    @patch.object(SemanticScholarConnector, "_get")
    def test_fetches_references(self, mock_get: MagicMock) -> None:
        """Fetches references using the /paper/{id}/references endpoint."""
        connector = SemanticScholarConnector()
        paper = make_paper(doi="10.1000/seed")

        response = MagicMock()
        response.json.return_value = {
            "data": [
                {"citedPaper": _make_ss_paper_record("r1", "10.1000/r1", "Ref 1")},
                {"citedPaper": _make_ss_paper_record("r2", "10.1000/r2", "Ref 2")},
            ],
            "next": None,
        }
        mock_get.return_value = response

        refs = connector.fetch_references(paper)

        assert len(refs) == 2
        assert refs[0].title == "Ref 1"
        assert refs[1].title == "Ref 2"
        # Verify the URL contains "references" endpoint.
        call_url = mock_get.call_args[0][0]
        assert "references" in call_url
        assert "DOI:10.1000/seed" in call_url

    @patch.object(SemanticScholarConnector, "_get")
    def test_handles_empty_response(self, mock_get: MagicMock) -> None:
        """Returns empty list when API returns no data."""
        connector = SemanticScholarConnector()
        paper = make_paper(doi="10.1000/empty")

        response = MagicMock()
        response.json.return_value = {"data": [], "next": None}
        mock_get.return_value = response

        refs = connector.fetch_references(paper)

        assert refs == []

    @patch.object(SemanticScholarConnector, "_get")
    def test_handles_api_error(self, mock_get: MagicMock) -> None:
        """Returns empty list on API error."""
        connector = SemanticScholarConnector()
        paper = make_paper(doi="10.1000/error")

        mock_get.side_effect = Exception("API error")

        refs = connector.fetch_references(paper)

        assert refs == []


# ---------------------------------------------------------------------------
# Tests: fetch_cited_by
# ---------------------------------------------------------------------------


class TestSemanticScholarFetchCitedBy:
    """Tests for SemanticScholarConnector.fetch_cited_by."""

    def test_returns_empty_for_paper_without_doi(self) -> None:
        """Papers without DOI return empty list."""
        connector = SemanticScholarConnector()
        paper = make_paper(doi=None)

        result = connector.fetch_cited_by(paper)

        assert result == []

    @patch.object(SemanticScholarConnector, "_get")
    def test_fetches_citing_papers(self, mock_get: MagicMock) -> None:
        """Fetches citations using the /paper/{id}/citations endpoint."""
        connector = SemanticScholarConnector()
        paper = make_paper(doi="10.1000/cited")

        response = MagicMock()
        response.json.return_value = {
            "data": [
                {"citingPaper": _make_ss_paper_record("c1", "10.1000/c1", "Citing 1")},
            ],
            "next": None,
        }
        mock_get.return_value = response

        cited_by = connector.fetch_cited_by(paper)

        assert len(cited_by) == 1
        assert cited_by[0].title == "Citing 1"
        call_url = mock_get.call_args[0][0]
        assert "citations" in call_url

    @patch.object(SemanticScholarConnector, "_get")
    def test_paginates_through_multiple_pages(self, mock_get: MagicMock) -> None:
        """Follows offset-based pagination until exhausted."""
        connector = SemanticScholarConnector()
        paper = make_paper(doi="10.1000/popular")

        # Page 1: returns 1000 items (full page) with next offset
        page1 = MagicMock()
        page1.json.return_value = {
            "data": [
                {"citingPaper": _make_ss_paper_record(f"p{i}", f"10.1000/p{i}", f"Paper {i}")}
                for i in range(1000)
            ],
            "next": 1000,
        }

        # Page 2: returns fewer items (last page)
        page2 = MagicMock()
        page2.json.return_value = {
            "data": [
                {"citingPaper": _make_ss_paper_record("last", "10.1000/last", "Last Paper")},
            ],
            "next": None,
        }

        mock_get.side_effect = [page1, page2]

        cited_by = connector.fetch_cited_by(paper)

        assert len(cited_by) == 1001
        assert mock_get.call_count == 2

    @patch.object(SemanticScholarConnector, "_get")
    def test_handles_api_error(self, mock_get: MagicMock) -> None:
        """Returns empty list on API error."""
        connector = SemanticScholarConnector()
        paper = make_paper(doi="10.1000/error")

        mock_get.side_effect = Exception("Network error")

        cited_by = connector.fetch_cited_by(paper)

        assert cited_by == []

    @patch.object(SemanticScholarConnector, "_get")
    def test_skips_unparseable_entries(self, mock_get: MagicMock) -> None:
        """Entries without a title are skipped silently."""
        connector = SemanticScholarConnector()
        paper = make_paper(doi="10.1000/mixed")

        bad_record = _make_ss_paper_record("bad", "10.1000/bad", "")
        good_record = _make_ss_paper_record("good", "10.1000/good", "Good Paper")

        response = MagicMock()
        response.json.return_value = {
            "data": [
                {"citingPaper": bad_record},
                {"citingPaper": good_record},
            ],
            "next": None,
        }
        mock_get.return_value = response

        cited_by = connector.fetch_cited_by(paper)

        assert len(cited_by) == 1
        assert cited_by[0].title == "Good Paper"
