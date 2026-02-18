"""Unit tests for web download helper utilities."""

from __future__ import annotations

from findpapers.utils.download import build_filename, build_proxies, resolve_pdf_url

# ---------------------------------------------------------------------------
# resolve_pdf_url
# ---------------------------------------------------------------------------


class TestResolvePdfUrl:
    """Tests for resolve_pdf_url()."""

    # ACM Digital Library
    def test_acm_doi_embedded_in_path(self) -> None:
        """ACM URL with DOI in path resolves to /doi/pdf/ variant."""
        url = "https://dl.acm.org/doi/10.1145/1234567.1234568"
        result = resolve_pdf_url(url)
        assert result == "https://dl.acm.org/doi/pdf/10.1145/1234567.1234568"

    def test_acm_uses_explicit_doi(self) -> None:
        """ACM URL without embedded DOI uses the doi parameter."""
        url = "https://dl.acm.org/doi/abs/short"
        result = resolve_pdf_url(url, doi="10.9999/test")
        assert result == "https://dl.acm.org/doi/pdf/10.9999/test"

    def test_acm_no_doi_returns_none(self) -> None:
        """ACM URL with no extractable DOI returns None."""
        result = resolve_pdf_url("https://dl.acm.org/", doi=None)
        assert result is None

    def test_acm_already_pdf_path_uses_doi(self) -> None:
        """ACM /doi/pdf/ path with doi param still resolves correctly."""
        result = resolve_pdf_url(
            "https://dl.acm.org/doi/pdf/10.1145/1234567.1234568",
            doi="10.1145/1234567.1234568",
        )
        assert result == "https://dl.acm.org/doi/pdf/10.1145/1234567.1234568"

    # IEEE Xplore
    def test_ieee_document_path(self) -> None:
        """IEEE document path is converted to stampPDF URL."""
        url = "https://ieeexplore.ieee.org/document/9999999"
        result = resolve_pdf_url(url)
        assert result == "https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber=9999999"

    def test_ieee_arnumber_querystring(self) -> None:
        """IEEE URL with arnumber query param is converted."""
        url = "https://ieeexplore.ieee.org/xpls/abs_all.jsp?arnumber=8888888"
        result = resolve_pdf_url(url)
        assert result is not None
        assert "arnumber=8888888" in result

    def test_ieee_unknown_path_returns_none(self) -> None:
        """IEEE URL without document path or arnumber returns None."""
        url = "https://ieeexplore.ieee.org/search/searchresult.jsp"
        result = resolve_pdf_url(url)
        assert result is None

    # ScienceDirect / Elsevier
    def test_sciencedirect_url(self) -> None:
        """ScienceDirect URL is converted to pdfft download URL."""
        url = "https://www.sciencedirect.com/science/article/pii/S0004370221000060"
        result = resolve_pdf_url(url)
        assert result is not None
        assert "pdfft?isDTMRedir=true&download=true" in result
        assert "S0004370221000060" in result

    def test_linkinghub_elsevier_url(self) -> None:
        """linkinghub.elsevier.com URL is handled like ScienceDirect."""
        url = "https://linkinghub.elsevier.com/retrieve/pii/S0004370221000060"
        result = resolve_pdf_url(url)
        assert result is not None
        assert "sciencedirect.com" in result

    # RSC
    def test_rsc_articlelanding(self) -> None:
        """RSC articlelanding URL becomes articlepdf URL."""
        url = "https://pubs.rsc.org/en/content/articlelanding/2021/sc/d1sc01234a"
        result = resolve_pdf_url(url)
        assert result is not None
        assert "/articlepdf/" in result

    # Tandfonline / Frontiers
    def test_tandfonline_full_to_pdf(self) -> None:
        """Tandfonline /full URL becomes /pdf URL."""
        url = "https://www.tandfonline.com/doi/full/10.1080/00000000.2021.123456"
        result = resolve_pdf_url(url)
        assert result is not None
        assert "/pdf" in result
        assert "/full" not in result

    def test_frontiersin_full_to_pdf(self) -> None:
        """Frontiers /full URL becomes /pdf URL."""
        url = "https://www.frontiersin.org/articles/10.3389/fpsyg.2021.123456/full"
        result = resolve_pdf_url(url)
        assert result is not None
        assert "/pdf" in result

    # ACS / SAGE / Royal Society
    def test_pubs_acs_doi_to_doi_pdf(self) -> None:
        """ACS /doi URL becomes /doi/pdf URL."""
        url = "https://pubs.acs.org/doi/10.1021/acs.jcim.1c00000"
        result = resolve_pdf_url(url)
        assert result is not None
        assert "/doi/pdf/" in result

    def test_sagepub_doi_to_doi_pdf(self) -> None:
        """SAGE /doi URL becomes /doi/pdf URL."""
        url = "https://journals.sagepub.com/doi/10.1177/00000000000000"
        result = resolve_pdf_url(url)
        assert result is not None
        assert "/doi/pdf/" in result

    # Springer
    def test_springer_article_to_content_pdf(self) -> None:
        """Springer /article/ URL is converted to /content/pdf/ + .pdf."""
        url = "https://link.springer.com/article/10.1007/s00000-021-00000-0"
        result = resolve_pdf_url(url)
        assert result is not None
        assert "/content/pdf/" in result
        assert result.endswith(".pdf")

    # ISCA
    def test_isca_abstracts_to_pdfs(self) -> None:
        """ISCA /abstracts/*.html URL becomes /pdfs/*.pdf."""
        url = "https://www.isca-speech.org/archive/abstracts/interspeech_2021/paper.html"
        result = resolve_pdf_url(url)
        assert result is not None
        assert "/pdfs/" in result
        assert result.endswith(".pdf")

    # Wiley
    def test_wiley_full_to_pdfdirect(self) -> None:
        """Wiley /full/ URL becomes /pdfdirect/."""
        url = "https://onlinelibrary.wiley.com/doi/full/10.1002/joc.0001"
        result = resolve_pdf_url(url)
        assert result is not None
        assert "/pdfdirect/" in result

    def test_wiley_abs_to_pdfdirect(self) -> None:
        """Wiley /abs/ URL becomes /pdfdirect/."""
        url = "https://onlinelibrary.wiley.com/doi/abs/10.1002/joc.0001"
        result = resolve_pdf_url(url)
        assert result is not None
        assert "/pdfdirect/" in result

    # JMIR / MDPI
    def test_jmir_appends_pdf(self) -> None:
        """JMIR URL gets /pdf appended."""
        url = "https://www.jmir.org/2021/1/e12345"
        result = resolve_pdf_url(url)
        assert result == f"{url}/pdf"

    def test_mdpi_appends_pdf(self) -> None:
        """MDPI URL gets /pdf appended."""
        url = "https://www.mdpi.com/1234-5678/12/3/45"
        result = resolve_pdf_url(url)
        assert result == f"{url}/pdf"

    # PNAS / JNeurosci
    def test_pnas_adds_full_pdf_suffix(self) -> None:
        """PNAS /content/ URL gets /content/pnas/ and .full.pdf suffix."""
        url = "https://www.pnas.org/content/118/1/e2015816118"
        result = resolve_pdf_url(url)
        assert result is not None
        assert "/content/pnas/" in result
        assert result.endswith(".full.pdf")

    def test_jneurosci_adds_full_pdf_suffix(self) -> None:
        """JNeurosci /content/ URL gets /content/jneuro/ and .full.pdf suffix."""
        url = "https://www.jneurosci.org/content/41/1/1"
        result = resolve_pdf_url(url)
        assert result is not None
        assert "/content/jneuro/" in result
        assert result.endswith(".full.pdf")

    # IJCAI
    def test_ijcai_paper_id_padding(self) -> None:
        """IJCAI paper ID is zero-padded to 4 digits."""
        url = "https://www.ijcai.org/proceedings/2021/42"
        result = resolve_pdf_url(url)
        assert result is not None
        assert result.endswith("0042.pdf")

    def test_ijcai_already_4_digit_id(self) -> None:
        """IJCAI paper ID already 4 digits is preserved."""
        url = "https://www.ijcai.org/proceedings/2021/1234"
        result = resolve_pdf_url(url)
        assert result is not None
        assert result.endswith("1234.pdf")

    # ASMP / EuRASIP
    def test_asmp_springeropen(self) -> None:
        """ASMP Springer Open /articles/ URL becomes /track/pdf/."""
        url = "https://asmp-eurasipjournals.springeropen.com/articles/10.1186/s13636-021-00000-0"
        result = resolve_pdf_url(url)
        assert result is not None
        assert "/track/pdf/" in result

    # Unknown publisher
    def test_unknown_publisher_returns_none(self) -> None:
        """Unrecognised publisher returns None."""
        url = "https://www.unknown-publisher.edu/paper/123"
        result = resolve_pdf_url(url)
        assert result is None

    def test_doi_param_ignored_for_non_acm(self) -> None:
        """doi parameter is ignored for non-ACM publishers."""
        url = "https://www.unknown-publisher.edu/paper/123"
        result = resolve_pdf_url(url, doi="10.9999/test")
        assert result is None


# ---------------------------------------------------------------------------
# build_filename
# ---------------------------------------------------------------------------


class TestBuildFilename:
    """Tests for build_filename()."""

    def test_basic_filename(self) -> None:
        """Standard year and title produce sanitised filename."""
        name = build_filename(2024, "Deep Learning Survey")
        assert name.endswith(".pdf")
        assert "2024" in name
        assert "Deep" in name

    def test_special_chars_replaced(self) -> None:
        """Special characters in title are replaced with underscores."""
        name = build_filename(2020, "Title: A & B (2020)")
        assert ".pdf" in name
        # Only word chars, digits, hyphens and underscores
        stem = name[:-4]  # strip .pdf
        for ch in stem:
            assert ch.isalnum() or ch in "_-"

    def test_none_year_uses_unknown(self) -> None:
        """None year produces 'unknown' in filename."""
        name = build_filename(None, "Some Paper")
        assert "unknown" in name

    def test_none_title_uses_paper(self) -> None:
        """None title produces 'paper' in filename."""
        name = build_filename(2021, None)
        assert "paper" in name

    def test_empty_title_uses_paper(self) -> None:
        """Empty string title produces 'paper' in filename."""
        name = build_filename(2021, "")
        assert "paper" in name

    def test_always_ends_with_pdf(self) -> None:
        """Filename always ends with .pdf."""
        assert build_filename(2022, "My Paper").endswith(".pdf")
        assert build_filename(None, None).endswith(".pdf")

    def test_hyphen_preserved(self) -> None:
        """Hyphens in title are preserved in the filename."""
        name = build_filename(2023, "State-of-the-Art")
        assert "-" in name


# ---------------------------------------------------------------------------
# build_proxies
# ---------------------------------------------------------------------------


class TestBuildProxies:
    """Tests for build_proxies()."""

    def test_explicit_proxy(self) -> None:
        """Explicit proxy URL produces http and https entries."""
        proxies = build_proxies("http://proxy.example.com:8080")
        assert proxies == {
            "http": "http://proxy.example.com:8080",
            "https": "http://proxy.example.com:8080",
        }

    def test_no_proxy_returns_none(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """No proxy and no env var returns None."""
        monkeypatch.delenv("FINDPAPERS_PROXY", raising=False)
        result = build_proxies(None)
        assert result is None

    def test_env_var_used_when_no_explicit(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """FINDPAPERS_PROXY env var is used when proxy param is None."""
        monkeypatch.setenv("FINDPAPERS_PROXY", "http://env-proxy:3128")
        proxies = build_proxies(None)
        assert proxies is not None
        assert proxies["http"] == "http://env-proxy:3128"
        assert proxies["https"] == "http://env-proxy:3128"

    def test_explicit_proxy_takes_precedence(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """Explicit proxy overrides FINDPAPERS_PROXY env var."""
        monkeypatch.setenv("FINDPAPERS_PROXY", "http://env-proxy:3128")
        proxies = build_proxies("http://explicit-proxy:9090")
        assert proxies is not None
        assert proxies["http"] == "http://explicit-proxy:9090"

    def test_empty_string_proxy_treated_as_none(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """Empty proxy string with no env var returns None."""
        monkeypatch.delenv("FINDPAPERS_PROXY", raising=False)
        # empty string is falsy, so treated as None
        result = build_proxies("")
        assert result is None
