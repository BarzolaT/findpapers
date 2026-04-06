"""Unit tests for utils.dedup"""

from findpapers.utils.dedup import _are_years_compatible, _is_preprint_doi

# ---------------------------------------------------------------------------
# _are_years_compatible
# ---------------------------------------------------------------------------


class TestAreYearsCompatible:
    """Tests for the extracted _are_years_compatible helper."""

    def test_same_year_compatible(self) -> None:
        """Identical years are always compatible."""
        assert _are_years_compatible(2025, 2025, None, None) is True

    def test_none_year_a_compatible(self) -> None:
        """Unknown year_a makes pair compatible."""
        assert _are_years_compatible(None, 2025, None, None) is True

    def test_none_year_b_compatible(self) -> None:
        """Unknown year_b makes pair compatible."""
        assert _are_years_compatible(2025, None, None, None) is True

    def test_both_none_compatible(self) -> None:
        """Both years unknown is compatible."""
        assert _are_years_compatible(None, None, None, None) is True

    def test_different_years_no_doi_incompatible(self) -> None:
        """Different years without DOIs are not compatible."""
        assert _are_years_compatible(2024, 2025, None, None) is False

    def test_different_years_non_preprint_doi_incompatible(self) -> None:
        """Different years with non-preprint DOIs are not compatible."""
        assert _are_years_compatible(2024, 2025, "10.1038/x", "10.1016/y") is False

    def test_adjacent_year_preprint_doi_compatible(self) -> None:
        """Adjacent years with a preprint DOI (arXiv) are compatible."""
        assert _are_years_compatible(2025, 2026, "10.48550/arXiv.123", "10.1038/x") is True

    def test_two_year_gap_preprint_incompatible(self) -> None:
        """Years separated by >1 are not compatible even with preprint DOI."""
        assert _are_years_compatible(2024, 2026, "10.48550/arXiv.123", "10.1038/x") is False


class TestIsPreprintDoi:
    """Unit tests for the _is_preprint_doi helper."""

    def test_arxiv_doi_recognised_as_preprint(self):
        assert _is_preprint_doi("10.48550/arxiv.1706.03762") is True

    def test_biorxiv_doi_recognised_as_preprint(self):
        assert _is_preprint_doi("10.1101/2021.05.01.442244") is True

    def test_ssrn_doi_recognised_as_preprint(self):
        assert _is_preprint_doi("10.2139/ssrn.3844763") is True

    def test_zenodo_doi_recognised_as_preprint(self):
        assert _is_preprint_doi("10.5281/zenodo.18056028") is True

    def test_publisher_doi_not_preprint(self):
        assert _is_preprint_doi("10.5555/3295222.3295349") is False

    def test_nature_doi_not_preprint(self):
        assert _is_preprint_doi("10.1038/s41586-021-03819-2") is False

    def test_case_insensitive(self):
        assert _is_preprint_doi("10.48550/ARXIV.1706.03762") is True
