"""Unit tests for metadata_parser utilities."""

from __future__ import annotations

from findpapers.utils.metadata_parser import normalize_language


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
