"""Tests for the arXiv taxonomy mapping utilities."""

from findpapers.utils.arxiv_taxonomy import arxiv_category_to_field, arxiv_category_to_subject


class TestArxivCategoryToField:
    """Tests for arxiv_category_to_field."""

    def test_cs_prefix(self):
        """cs.* categories map to Computer Science."""
        assert arxiv_category_to_field("cs.AI") == "Computer Science"
        assert arxiv_category_to_field("cs.LG") == "Computer Science"

    def test_math_prefix(self):
        """math.* categories map to Mathematics."""
        assert arxiv_category_to_field("math.OC") == "Mathematics"

    def test_single_level_category(self):
        """Single-level categories like gr-qc are mapped correctly."""
        assert arxiv_category_to_field("gr-qc") == "General Relativity and Quantum Cosmology"
        assert arxiv_category_to_field("quant-ph") == "Quantum Physics"

    def test_unknown_prefix_returns_none(self):
        """Unknown prefix returns None."""
        assert arxiv_category_to_field("unknown.XY") is None

    def test_hep_prefix(self):
        """hep-* categories map to High Energy Physics."""
        assert arxiv_category_to_field("hep-th") == "High Energy Physics"

    def test_stat_prefix(self):
        """stat.* categories map to Statistics."""
        assert arxiv_category_to_field("stat.ML") == "Statistics"


class TestArxivCategoryToSubject:
    """Tests for arxiv_category_to_subject."""

    def test_cs_ai(self):
        """cs.AI maps to Artificial Intelligence."""
        assert arxiv_category_to_subject("cs.AI") == "Artificial Intelligence"

    def test_cs_lg(self):
        """cs.LG maps to Machine Learning."""
        assert arxiv_category_to_subject("cs.LG") == "Machine Learning"

    def test_math_oc(self):
        """math.OC maps to Optimization and Control."""
        assert arxiv_category_to_subject("math.OC") == "Optimization and Control"

    def test_q_fin_rm(self):
        """q-fin.RM maps to Risk Management."""
        assert arxiv_category_to_subject("q-fin.RM") == "Risk Management"

    def test_single_level_category(self):
        """Single-level categories like gr-qc have subject mappings."""
        assert arxiv_category_to_subject("gr-qc") == "General Relativity and Quantum Cosmology"

    def test_unknown_category_returns_none(self):
        """Unknown category returns None."""
        assert arxiv_category_to_subject("unknown.XY") is None

    def test_stat_ml(self):
        """stat.ML maps to Machine Learning."""
        assert arxiv_category_to_subject("stat.ML") == "Machine Learning"
