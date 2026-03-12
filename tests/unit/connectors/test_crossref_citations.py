"""Unit tests for CrossRefConnector citation methods."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests

from findpapers.connectors.crossref import CrossRefConnector


def _make_crossref_work(
    doi: str = "10.1000/ref",
    title: str = "Referenced Paper",
    references: list[dict] | None = None,
) -> dict:
    """Create a minimal CrossRef work record for mocking."""
    work: dict = {
        "DOI": doi,
        "title": [title],
        "abstract": "<jats:p>An abstract.</jats:p>",
        "author": [{"given": "Author", "family": "One", "affiliation": []}],
        "issued": {"date-parts": [[2024, 1, 15]]},
        "container-title": ["Test Journal"],
        "type": "journal-article",
        "is-referenced-by-count": 5,
        "URL": f"https://doi.org/{doi}",
    }
    if references is not None:
        work["reference"] = references
    return work


# ---------------------------------------------------------------------------
# Tests: fetch_references
# ---------------------------------------------------------------------------


class TestCrossRefFetchReferences:
    """Tests for CrossRefConnector.fetch_references."""

    def test_returns_empty_for_paper_without_doi(self, make_paper) -> None:
        """Papers without DOI return empty list."""
        connector = CrossRefConnector()
        paper = make_paper(doi=None)

        result = connector.fetch_references(paper)

        assert result == []

    @patch.object(CrossRefConnector, "fetch_work")
    def test_fetches_references_from_reference_list(
        self, mock_fetch: MagicMock, make_paper
    ) -> None:
        """Parses DOIs from the reference list and fetches each one."""
        connector = CrossRefConnector()
        paper = make_paper(doi="10.1000/seed")

        seed_work = _make_crossref_work(
            doi="10.1000/seed",
            title="Seed",
            references=[
                {"key": "ref1", "DOI": "10.1000/r1"},
                {"key": "ref2", "DOI": "10.1000/r2"},
                {"key": "ref3"},  # no DOI — should be skipped
            ],
        )
        ref1_work = _make_crossref_work(doi="10.1000/r1", title="Ref 1")
        ref2_work = _make_crossref_work(doi="10.1000/r2", title="Ref 2")

        mock_fetch.side_effect = [seed_work, ref1_work, ref2_work]

        refs = connector.fetch_references(paper)

        assert len(refs) == 2
        assert refs[0].title == "Ref 1"
        assert refs[1].title == "Ref 2"
        # 1 call for seed work + 2 calls for references
        assert mock_fetch.call_count == 3

    @patch.object(CrossRefConnector, "fetch_work")
    def test_handles_work_not_found(self, mock_fetch: MagicMock, make_paper) -> None:
        """Returns empty list when the seed work is not found (None)."""
        connector = CrossRefConnector()
        paper = make_paper(doi="10.1000/missing")

        mock_fetch.return_value = None

        refs = connector.fetch_references(paper)

        assert refs == []

    @patch.object(CrossRefConnector, "fetch_work")
    def test_handles_work_without_reference_field(self, mock_fetch: MagicMock, make_paper) -> None:
        """Returns empty list when the work has no reference field."""
        connector = CrossRefConnector()
        paper = make_paper(doi="10.1000/norefs")

        work = _make_crossref_work(doi="10.1000/norefs", title="No Refs")
        # No "reference" key at all
        mock_fetch.return_value = work

        refs = connector.fetch_references(paper)

        assert refs == []

    @patch.object(CrossRefConnector, "fetch_work")
    def test_skips_references_that_fail_to_resolve(self, mock_fetch: MagicMock, make_paper) -> None:
        """References whose fetch_work call raises are silently skipped."""
        connector = CrossRefConnector()
        paper = make_paper(doi="10.1000/seed")

        seed_work = _make_crossref_work(
            doi="10.1000/seed",
            title="Seed",
            references=[
                {"key": "ref1", "DOI": "10.1000/r1"},
                {"key": "ref2", "DOI": "10.1000/r2"},
            ],
        )
        ref2_work = _make_crossref_work(doi="10.1000/r2", title="Ref 2")

        # seed_work succeeds, ref1 raises, ref2 succeeds
        mock_fetch.side_effect = [seed_work, requests.RequestException("404"), ref2_work]

        refs = connector.fetch_references(paper)

        assert len(refs) == 1
        assert refs[0].title == "Ref 2"

    @patch.object(CrossRefConnector, "fetch_work")
    def test_handles_fetch_work_error_for_seed(self, mock_fetch: MagicMock, make_paper) -> None:
        """Returns empty list when fetching the seed work raises."""
        connector = CrossRefConnector()
        paper = make_paper(doi="10.1000/error")

        mock_fetch.side_effect = requests.RequestException("Network error")

        refs = connector.fetch_references(paper)

        assert refs == []

    @patch.object(CrossRefConnector, "fetch_work")
    def test_skips_references_without_title(self, mock_fetch: MagicMock, make_paper) -> None:
        """References that build_paper returns None for are skipped."""
        connector = CrossRefConnector()
        paper = make_paper(doi="10.1000/seed")

        seed_work = _make_crossref_work(
            doi="10.1000/seed",
            title="Seed",
            references=[{"key": "ref1", "DOI": "10.1000/r1"}],
        )
        # Work with no title → build_paper returns None
        bad_work = {"DOI": "10.1000/r1", "title": []}

        mock_fetch.side_effect = [seed_work, bad_work]

        refs = connector.fetch_references(paper)

        assert refs == []


# ---------------------------------------------------------------------------
# Tests: fetch_cited_by
# ---------------------------------------------------------------------------


class TestCrossRefFetchCitedBy:
    """Tests for CrossRefConnector.fetch_cited_by."""

    def test_always_returns_empty_list(self, make_paper) -> None:
        """CrossRef does not support forward citation lookups."""
        connector = CrossRefConnector()
        paper = make_paper(doi="10.1000/popular")

        result = connector.fetch_cited_by(paper)

        assert result == []

    def test_returns_empty_for_paper_without_doi(self, make_paper) -> None:
        """Even without DOI, returns empty list gracefully."""
        connector = CrossRefConnector()
        paper = make_paper(doi=None)

        result = connector.fetch_cited_by(paper)

        assert result == []


# ---------------------------------------------------------------------------
# Tests with real API response data
# ---------------------------------------------------------------------------

_NATURE_DOI = "10.1038/nature12373"


class TestCrossRefRealDataParsing:
    """Tests using real CrossRef API responses from sample_responses.json."""

    def test_real_work_has_references(self, crossref_sample_json: dict) -> None:
        """Verify real CrossRef work contains a non-empty reference array."""
        work = crossref_sample_json[_NATURE_DOI]
        refs = work.get("reference", [])

        assert len(refs) == 30
        # Most references in this paper have DOIs.
        with_doi = [r for r in refs if r.get("DOI")]
        assert len(with_doi) == 29

    @patch.object(CrossRefConnector, "fetch_work")
    def test_fetch_references_with_real_seed_work(
        self,
        mock_fetch: MagicMock,
        make_paper,
        crossref_sample_json: dict,
    ) -> None:
        """Use real CrossRef work as the seed and build_paper for each ref DOI."""
        connector = CrossRefConnector()
        paper = make_paper(doi=_NATURE_DOI)

        seed_work = crossref_sample_json[_NATURE_DOI]
        ref_dois = [r["DOI"] for r in seed_work.get("reference", []) if r.get("DOI")]

        # First call returns the real seed work; subsequent calls return
        # the seed work as a stand-in (CrossRef works are structurally
        # identical so this validates parsing).
        mock_fetch.side_effect = [seed_work] + [seed_work] * len(ref_dois)

        refs = connector.fetch_references(paper)

        # Each ref DOI gets a fetch_work call; the seed work has a title
        # so build_paper should succeed for all of them.
        assert len(refs) == len(ref_dois)
        assert len(refs) == 29
        for ref in refs:
            assert ref.title

    def test_build_paper_with_real_work(self, crossref_sample_json: dict) -> None:
        """build_paper converts a real CrossRef work record to a Paper."""
        connector = CrossRefConnector()
        work = crossref_sample_json[_NATURE_DOI]

        paper = connector.build_paper(work)

        assert paper is not None
        assert paper.title
        assert paper.doi == _NATURE_DOI
        assert paper.authors
