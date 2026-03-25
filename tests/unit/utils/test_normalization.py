"""Unit tests for normalization utilities."""

from __future__ import annotations

from datetime import date

from findpapers.connectors.web_scraping import _arxiv_doi_from_url
from findpapers.utils.normalization import normalize_doi, normalize_language, parse_date


class TestNormalizeLanguage:
    """Tests for normalize_language()."""

    # --- passthrough of already-valid ISO 639-1 codes ---

    def test_two_letter_code_passthrough(self) -> None:
        """A valid 2-letter ISO 639-1 code is returned as-is (lowercased)."""
        assert normalize_language("en") == "en"

    def test_two_letter_code_uppercase(self) -> None:
        """Uppercase 2-letter code is lowercased on return."""
        assert normalize_language("EN") == "en"

    def test_two_letter_code_mixed_case(self) -> None:
        """Mixed-case 2-letter code is lowercased."""
        assert normalize_language("Pt") == "pt"

    def test_two_letter_code_with_whitespace(self) -> None:
        """Leading/trailing whitespace is stripped."""
        assert normalize_language("  fr  ") == "fr"

    # --- ISO 639-2 3-letter terminological codes ---

    def test_eng_maps_to_en(self) -> None:
        """'eng' (PubMed default) maps to 'en'."""
        assert normalize_language("eng") == "en"

    def test_por_maps_to_pt(self) -> None:
        """'por' maps to 'pt'."""
        assert normalize_language("por") == "pt"

    def test_deu_maps_to_de(self) -> None:
        """'deu' maps to 'de'."""
        assert normalize_language("deu") == "de"

    def test_zho_maps_to_zh(self) -> None:
        """'zho' maps to 'zh'."""
        assert normalize_language("zho") == "zh"

    def test_hun_maps_to_hu(self) -> None:
        """'hun' maps to 'hu'."""
        assert normalize_language("hun") == "hu"

    def test_three_letter_uppercase(self) -> None:
        """3-letter codes are case-insensitive."""
        assert normalize_language("ENG") == "en"

    # --- ISO 639-2 bibliographic variants ---

    def test_fre_bibliographic_maps_to_fr(self) -> None:
        """Bibliographic variant 'fre' maps to 'fr'."""
        assert normalize_language("fre") == "fr"

    def test_ger_bibliographic_maps_to_de(self) -> None:
        """Bibliographic variant 'ger' maps to 'de'."""
        assert normalize_language("ger") == "de"

    def test_chi_bibliographic_maps_to_zh(self) -> None:
        """Bibliographic variant 'chi' maps to 'zh'."""
        assert normalize_language("chi") == "zh"

    # --- full language names ---

    def test_full_name_english(self) -> None:
        """Full English name 'english' maps to 'en'."""
        assert normalize_language("english") == "en"

    def test_full_name_uppercase(self) -> None:
        """Full name matching is case-insensitive."""
        assert normalize_language("English") == "en"
        assert normalize_language("FRENCH") == "fr"

    def test_full_name_portuguese(self) -> None:
        """'portuguese' maps to 'pt'."""
        assert normalize_language("portuguese") == "pt"

    def test_full_name_german(self) -> None:
        """'german' maps to 'de'."""
        assert normalize_language("german") == "de"

    def test_full_name_spanish(self) -> None:
        """'spanish' maps to 'es'."""
        assert normalize_language("spanish") == "es"

    def test_full_name_chinese(self) -> None:
        """'chinese' maps to 'zh'."""
        assert normalize_language("chinese") == "zh"

    # --- unrecognised values ---

    def test_unknown_three_letter_returns_none(self) -> None:
        """Unknown 3-letter code returns None."""
        assert normalize_language("xyz") is None

    def test_unknown_full_name_returns_none(self) -> None:
        """Unrecognised full name returns None."""
        assert normalize_language("klingon") is None

    def test_empty_string_returns_none(self) -> None:
        """Empty string returns None."""
        assert normalize_language("") is None

    def test_whitespace_only_returns_none(self) -> None:
        """Whitespace-only string returns None."""
        assert normalize_language("   ") is None

    def test_none_returns_none(self) -> None:
        """None input returns None."""
        assert normalize_language(None) is None


class TestParseDate:
    """Tests for parse_date()."""

    # --- numeric formats ---

    def test_iso_full_date(self) -> None:
        """YYYY-MM-DD is parsed correctly."""
        assert parse_date("2021-07-15") == date(2021, 7, 15)

    def test_slash_full_date(self) -> None:
        """YYYY/MM/DD is parsed correctly."""
        assert parse_date("2017/06/12") == date(2017, 6, 12)

    def test_iso_year_month(self) -> None:
        """YYYY-MM is parsed to the first day of the month."""
        assert parse_date("2021-08") == date(2021, 8, 1)

    def test_slash_year_month(self) -> None:
        """YYYY/MM is parsed to the first day of the month (Nature style)."""
        assert parse_date("2021/08") == date(2021, 8, 1)

    def test_year_only(self) -> None:
        """YYYY is parsed to Jan 1st of that year."""
        assert parse_date("1998") == date(1998, 1, 1)

    def test_iso_with_trailing_time(self) -> None:
        """Trailing time component is ignored via the [:10] slice."""
        assert parse_date("2021-07-15T11:00:00Z") == date(2021, 7, 15)

    # --- written month-name formats ---

    def test_full_month_year(self) -> None:
        """'November 1998' (IEEE style) is parsed correctly."""
        assert parse_date("November 1998") == date(1998, 11, 1)

    def test_abbreviated_month_day_year(self) -> None:
        """'Oct 4, 2017' (PLOS ONE style) is parsed correctly."""
        assert parse_date("Oct 4, 2017") == date(2017, 10, 4)

    def test_full_month_day_year(self) -> None:
        """'October 4, 2017' is parsed correctly."""
        assert parse_date("October 4, 2017") == date(2017, 10, 4)

    def test_abbreviated_month_year(self) -> None:
        """'Jan 2024' is parsed to Jan 1st of that year."""
        assert parse_date("Jan 2024") == date(2024, 1, 1)

    def test_day_full_month_year(self) -> None:
        """'15 July 2021' (European style) is parsed correctly."""
        assert parse_date("15 July 2021") == date(2021, 7, 15)

    def test_day_abbreviated_month_year(self) -> None:
        """'15 Jul 2021' (European abbreviated) is parsed correctly."""
        assert parse_date("15 Jul 2021") == date(2021, 7, 15)

    # --- edge cases ---

    def test_none_returns_none(self) -> None:
        """None input returns None."""
        assert parse_date(None) is None

    def test_empty_string_returns_none(self) -> None:
        """Empty string returns None."""
        assert parse_date("") is None

    def test_whitespace_only_returns_none(self) -> None:
        """Whitespace-only string returns None."""
        assert parse_date("   ") is None

    def test_unrecognised_format_returns_none(self) -> None:
        """Completely unrecognised string returns None."""
        assert parse_date("not a date") is None

    def test_whitespace_stripped(self) -> None:
        """Leading/trailing whitespace is stripped before parsing."""
        assert parse_date("  2021-07-15  ") == date(2021, 7, 15)

    # --- PubMed / YYYY Mon(th) formats ---

    def test_year_abbreviated_month(self) -> None:
        """'2023 Dec' (PubMed citation_date style) is parsed correctly."""
        assert parse_date("2023 Dec") == date(2023, 12, 1)

    def test_year_full_month(self) -> None:
        """'2023 December' is parsed correctly."""
        assert parse_date("2023 December") == date(2023, 12, 1)

    def test_year_abbreviated_month_january(self) -> None:
        """'2020 Jan' is parsed to Jan 1st of that year."""
        assert parse_date("2020 Jan") == date(2020, 1, 1)


class TestNormalizeDoi:
    """Tests for normalize_doi()."""

    def test_plain_doi(self) -> None:
        """A plain '10.xxx/...' string is returned unchanged."""
        assert normalize_doi("10.1000/xyz123") == "10.1000/xyz123"

    def test_https_url(self) -> None:
        """'https://doi.org/10.xxx/...' prefix is stripped."""
        assert normalize_doi("https://doi.org/10.1000/xyz123") == "10.1000/xyz123"

    def test_http_url(self) -> None:
        """'http://doi.org/10.xxx/...' prefix is stripped."""
        assert normalize_doi("http://doi.org/10.1000/xyz123") == "10.1000/xyz123"

    def test_doi_colon_prefix(self) -> None:
        """'doi:10.xxx/...' protocol prefix is stripped."""
        assert normalize_doi("doi:10.56578/ataiml010201") == "10.56578/ataiml010201"

    def test_doi_colon_prefix_uppercase(self) -> None:
        """'DOI:10.xxx/...' is case-insensitive for the protocol part."""
        assert normalize_doi("DOI:10.56578/ataiml010201") == "10.56578/ataiml010201"

    def test_invalid_returns_none(self) -> None:
        """A string that cannot be normalised to a valid DOI returns None."""
        assert normalize_doi("not-a-doi") is None

    def test_empty_returns_none(self) -> None:
        """Empty string returns None."""
        assert normalize_doi("") is None

    def test_whitespace_stripped(self) -> None:
        """Leading/trailing whitespace is stripped."""
        assert normalize_doi("  10.1000/xyz123  ") == "10.1000/xyz123"

    """Tests for _arxiv_doi_from_url()."""

    def test_abs_url(self) -> None:
        """Standard arxiv.org/abs/ URL returns the canonical DOI."""
        assert (
            _arxiv_doi_from_url("https://arxiv.org/abs/1706.03762") == "10.48550/arXiv.1706.03762"
        )

    def test_versioned_url(self) -> None:
        """Versioned URL (e.g. v2) is handled; version suffix is stripped."""
        assert (
            _arxiv_doi_from_url("https://arxiv.org/abs/1706.03762v2") == "10.48550/arXiv.1706.03762"
        )

    def test_pdf_url(self) -> None:
        """PDF URL also yields the correct DOI."""
        assert (
            _arxiv_doi_from_url("https://arxiv.org/pdf/1706.03762") == "10.48550/arXiv.1706.03762"
        )

    def test_five_digit_id(self) -> None:
        """5-digit fractional part (new arXiv IDs) is recognised."""
        assert (
            _arxiv_doi_from_url("https://arxiv.org/abs/2310.12345") == "10.48550/arXiv.2310.12345"
        )

    def test_non_arxiv_url_returns_none(self) -> None:
        """Non-arXiv URL returns None."""
        assert _arxiv_doi_from_url("https://www.nature.com/articles/s41586-021-03819-2") is None

    def test_empty_string_returns_none(self) -> None:
        """Empty string returns None."""
        assert _arxiv_doi_from_url("") is None
