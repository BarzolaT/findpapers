"""Unit tests for the Engine facade."""

from __future__ import annotations

import os
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from findpapers.core.author import Author
from findpapers.core.paper import Paper
from findpapers.core.search_result import SearchResult
from findpapers.core.source import Source
from findpapers.engine import Engine


def _make_paper(
    title: str = "Test Paper",
    doi: str | None = None,
    url: str = "http://example.com/paper",
) -> Paper:
    """Create a minimal Paper for testing."""
    return Paper(
        title=title,
        abstract="An abstract.",
        authors=[Author(name="Author One")],
        source=Source(title="Test Journal"),
        publication_date=date(2023, 1, 1),
        url=url,
        doi=doi,
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestEngineInit:
    """Tests for Engine initialisation and stored configuration."""

    def test_default_values(self):
        """Engine defaults all API keys to None, ssl_verify to True."""
        # Ensure no FINDPAPERS_* env vars leak from other tests.
        env_clear = {
            "FINDPAPERS_IEEE_API_TOKEN": "",
            "FINDPAPERS_SCOPUS_API_TOKEN": "",
            "FINDPAPERS_PUBMED_API_TOKEN": "",
            "FINDPAPERS_OPENALEX_API_TOKEN": "",
            "FINDPAPERS_EMAIL": "",
            "FINDPAPERS_SEMANTIC_SCHOLAR_API_TOKEN": "",
            "FINDPAPERS_PROXY": "",
            "FINDPAPERS_SSL_VERIFY": "",
        }
        with patch.dict(os.environ, env_clear, clear=False):
            engine = Engine()

        assert engine._ieee_api_key is None
        assert engine._scopus_api_key is None
        assert engine._pubmed_api_key is None
        assert engine._openalex_api_key is None
        assert engine._email is None
        assert engine._semantic_scholar_api_key is None
        assert engine._proxy is None
        assert engine._ssl_verify is True

    def test_custom_values(self):
        """Engine stores the supplied configuration values."""
        engine = Engine(
            ieee_api_key="ieee-k",
            scopus_api_key="scopus-k",
            pubmed_api_key="pubmed-k",
            openalex_api_key="oalex-k",
            email="me@example.com",
            semantic_scholar_api_key="s2-k",
            proxy="http://proxy:8080",
            ssl_verify=False,
        )

        assert engine._ieee_api_key == "ieee-k"
        assert engine._scopus_api_key == "scopus-k"
        assert engine._pubmed_api_key == "pubmed-k"
        assert engine._openalex_api_key == "oalex-k"
        assert engine._email == "me@example.com"
        assert engine._semantic_scholar_api_key == "s2-k"
        assert engine._proxy == "http://proxy:8080"
        assert engine._ssl_verify is False

    def test_keyword_only_arguments(self):
        """Engine constructor only accepts keyword arguments."""
        with pytest.raises(TypeError):
            Engine("ieee-key")  # type: ignore[misc]

    def test_env_var_fallbacks(self):
        """Engine reads missing values from FINDPAPERS_* env vars."""
        env = {
            "FINDPAPERS_IEEE_API_TOKEN": "env-ieee",
            "FINDPAPERS_SCOPUS_API_TOKEN": "env-scopus",
            "FINDPAPERS_PUBMED_API_TOKEN": "env-pubmed",
            "FINDPAPERS_OPENALEX_API_TOKEN": "env-oalex",
            "FINDPAPERS_EMAIL": "env@example.com",
            "FINDPAPERS_SEMANTIC_SCHOLAR_API_TOKEN": "env-s2",
            "FINDPAPERS_PROXY": "http://env-proxy:8080",
        }
        with patch.dict(os.environ, env, clear=False):
            engine = Engine()

        assert engine._ieee_api_key == "env-ieee"
        assert engine._scopus_api_key == "env-scopus"
        assert engine._pubmed_api_key == "env-pubmed"
        assert engine._openalex_api_key == "env-oalex"
        assert engine._email == "env@example.com"
        assert engine._semantic_scholar_api_key == "env-s2"
        assert engine._proxy == "http://env-proxy:8080"

    def test_explicit_values_override_env(self):
        """Explicit arguments take precedence over environment variables."""
        env = {
            "FINDPAPERS_IEEE_API_TOKEN": "env-ieee",
            "FINDPAPERS_EMAIL": "env@example.com",
        }
        with patch.dict(os.environ, env, clear=False):
            engine = Engine(ieee_api_key="explicit-ieee", email="explicit@example.com")

        assert engine._ieee_api_key == "explicit-ieee"
        assert engine._email == "explicit@example.com"

    def test_ssl_verify_env_false(self):
        """FINDPAPERS_SSL_VERIFY=false disables SSL verification."""
        for val in ("false", "0", "no", "False", "NO"):
            with patch.dict(os.environ, {"FINDPAPERS_SSL_VERIFY": val}, clear=False):
                engine = Engine()
            assert engine._ssl_verify is False, f"Expected False for SSL_VERIFY={val!r}"

    def test_ssl_verify_env_true(self):
        """FINDPAPERS_SSL_VERIFY=true keeps SSL verification enabled."""
        with patch.dict(os.environ, {"FINDPAPERS_SSL_VERIFY": "true"}, clear=False):
            engine = Engine()
        assert engine._ssl_verify is True

    def test_ssl_verify_explicit_overrides_env(self):
        """Explicit ssl_verify=False overrides the environment variable."""
        with patch.dict(os.environ, {"FINDPAPERS_SSL_VERIFY": "true"}, clear=False):
            engine = Engine(ssl_verify=False)
        assert engine._ssl_verify is False


# ---------------------------------------------------------------------------
# search()
# ---------------------------------------------------------------------------


class TestEngineSearch:
    """Tests for Engine.search()."""

    def test_search_delegates_to_runner_with_engine_keys(self):
        """search() passes engine API keys and per-call params to SearchRunner."""
        engine = Engine(
            ieee_api_key="ieee-k",
            scopus_api_key="scopus-k",
            pubmed_api_key="pubmed-k",
            openalex_api_key="oalex-k",
            email="me@example.com",
            semantic_scholar_api_key="s2-k",
        )
        fake_search = MagicMock(spec=SearchResult)
        with patch("findpapers.engine.SearchRunner") as mock_cls:
            mock_runner = MagicMock()
            mock_runner.run.return_value = fake_search
            mock_cls.return_value = mock_runner

            result = engine.search(
                "ti[ml]",
                databases=["arxiv"],
                max_papers_per_database=50,
                num_workers=3,
                verbose=True,
            )

        mock_cls.assert_called_once_with(
            query="ti[ml]",
            databases=["arxiv"],
            max_papers_per_database=50,
            ieee_api_key="ieee-k",
            scopus_api_key="scopus-k",
            pubmed_api_key="pubmed-k",
            openalex_api_key="oalex-k",
            email="me@example.com",
            semantic_scholar_api_key="s2-k",
            num_workers=3,
        )
        mock_runner.run.assert_called_once_with(verbose=True, show_progress=True)
        assert result is fake_search

    def test_search_default_per_call_params(self):
        """num_workers defaults to 1, verbose to False."""
        engine = Engine()
        with patch("findpapers.engine.SearchRunner") as mock_cls:
            mock_runner = MagicMock()
            mock_runner.run.return_value = MagicMock(spec=SearchResult)
            mock_cls.return_value = mock_runner

            engine.search("[ml]")

        _, kwargs = mock_cls.call_args
        assert kwargs["num_workers"] == 1
        mock_runner.run.assert_called_once_with(verbose=False, show_progress=True)

    def test_search_show_progress_false(self):
        """show_progress=False is forwarded to SearchRunner.run()."""
        engine = Engine()
        with patch("findpapers.engine.SearchRunner") as mock_cls:
            mock_runner = MagicMock()
            mock_runner.run.return_value = MagicMock(spec=SearchResult)
            mock_cls.return_value = mock_runner

            engine.search("[ml]", show_progress=False)

        mock_runner.run.assert_called_once_with(verbose=False, show_progress=False)


# ---------------------------------------------------------------------------
# download()
# ---------------------------------------------------------------------------


class TestEngineDownload:
    """Tests for Engine.download()."""

    def test_download_uses_engine_proxy_and_ssl(self):
        """download() forwards engine proxy and ssl_verify to DownloadRunner."""
        engine = Engine(
            proxy="http://proxy:8080",
            ssl_verify=False,
        )
        fake_metrics = {"total_papers": 1, "downloaded_papers": 1}
        with patch("findpapers.engine.DownloadRunner") as mock_cls:
            mock_runner = MagicMock()
            mock_runner.run.return_value = fake_metrics
            mock_cls.return_value = mock_runner

            papers = [_make_paper()]
            result = engine.download(
                papers,
                "/tmp/pdfs",
                num_workers=2,
                timeout=20.0,
                verbose=True,
            )

        mock_cls.assert_called_once_with(
            papers=papers,
            output_directory="/tmp/pdfs",
            num_workers=2,
            timeout=20.0,
            proxy="http://proxy:8080",
            ssl_verify=False,
        )
        mock_runner.run.assert_called_once_with(verbose=True, show_progress=True)
        assert result == fake_metrics

    def test_download_default_per_call_params(self):
        """num_workers defaults to 1, verbose to False, timeout to 10.0."""
        engine = Engine()
        with patch("findpapers.engine.DownloadRunner") as mock_cls:
            mock_runner = MagicMock()
            mock_runner.run.return_value = {}
            mock_cls.return_value = mock_runner

            engine.download([], "/tmp/out")

        _, kwargs = mock_cls.call_args
        assert kwargs["num_workers"] == 1
        assert kwargs["timeout"] == 10.0
        mock_runner.run.assert_called_once_with(verbose=False, show_progress=True)

    def test_download_show_progress_false(self):
        """show_progress=False is forwarded to DownloadRunner.run()."""
        engine = Engine()
        with patch("findpapers.engine.DownloadRunner") as mock_cls:
            mock_runner = MagicMock()
            mock_runner.run.return_value = {}
            mock_cls.return_value = mock_runner

            engine.download([], "/tmp/out", show_progress=False)

        mock_runner.run.assert_called_once_with(verbose=False, show_progress=False)


# ---------------------------------------------------------------------------
# enrich()
# ---------------------------------------------------------------------------


class TestEngineEnrich:
    """Tests for Engine.enrich()."""

    def test_enrich_forwards_timeout(self):
        """enrich() forwards per-call timeout to EnrichmentRunner."""
        engine = Engine()
        fake_metrics = {"total_papers": 2, "enriched_papers": 1}
        with patch("findpapers.engine.EnrichmentRunner") as mock_cls:
            mock_runner = MagicMock()
            mock_runner.run.return_value = fake_metrics
            mock_cls.return_value = mock_runner

            papers = [_make_paper(), _make_paper(title="P2")]
            result = engine.enrich(papers, num_workers=4, timeout=25.0, verbose=True)

        mock_cls.assert_called_once_with(
            papers=papers,
            email=None,
            num_workers=4,
            timeout=25.0,
        )
        mock_runner.run.assert_called_once_with(verbose=True, show_progress=True)
        assert result == fake_metrics

    def test_enrich_default_per_call_params(self):
        """num_workers defaults to 1, verbose to False, timeout to 10.0."""
        engine = Engine()
        with patch("findpapers.engine.EnrichmentRunner") as mock_cls:
            mock_runner = MagicMock()
            mock_runner.run.return_value = {}
            mock_cls.return_value = mock_runner

            engine.enrich([])

        _, kwargs = mock_cls.call_args
        assert kwargs["num_workers"] == 1
        assert kwargs["timeout"] == 10.0
        mock_runner.run.assert_called_once_with(verbose=False, show_progress=True)

    def test_enrich_show_progress_false(self):
        """show_progress=False is forwarded to EnrichmentRunner.run()."""
        engine = Engine()
        with patch("findpapers.engine.EnrichmentRunner") as mock_cls:
            mock_runner = MagicMock()
            mock_runner.run.return_value = {}
            mock_cls.return_value = mock_runner

            engine.enrich([], show_progress=False)

        mock_runner.run.assert_called_once_with(verbose=False, show_progress=False)


# ---------------------------------------------------------------------------
# fetch_paper_by_doi()
# ---------------------------------------------------------------------------


class TestEngineFetchPaperByDoi:
    """Tests for Engine.fetch_paper_by_doi()."""

    def test_fetch_forwards_timeout(self):
        """fetch_paper_by_doi() forwards per-call timeout to DOILookupRunner."""
        engine = Engine()
        fake_paper = MagicMock(spec=Paper)
        with patch("findpapers.engine.DOILookupRunner") as mock_cls:
            mock_runner = MagicMock()
            mock_runner.run.return_value = fake_paper
            mock_cls.return_value = mock_runner

            result = engine.fetch_paper_by_doi("10.1234/test", timeout=30.0, verbose=True)

        mock_cls.assert_called_once_with(
            doi="10.1234/test",
            email=None,
            timeout=30.0,
        )
        mock_runner.run.assert_called_once_with(verbose=True)
        assert result is fake_paper

    def test_fetch_returns_none_when_not_found(self):
        """fetch_paper_by_doi() returns None when DOI is not found."""
        engine = Engine()
        with patch("findpapers.engine.DOILookupRunner") as mock_cls:
            mock_runner = MagicMock()
            mock_runner.run.return_value = None
            mock_cls.return_value = mock_runner

            result = engine.fetch_paper_by_doi("10.9999/nonexistent")

        assert result is None

    def test_fetch_default_per_call_params(self):
        """verbose defaults to False, timeout to 10.0."""
        engine = Engine()
        with patch("findpapers.engine.DOILookupRunner") as mock_cls:
            mock_runner = MagicMock()
            mock_runner.run.return_value = None
            mock_cls.return_value = mock_runner

            engine.fetch_paper_by_doi("10.1234/test")

        _, kwargs = mock_cls.call_args
        assert kwargs["timeout"] == 10.0
        mock_runner.run.assert_called_once_with(verbose=False)


# ---------------------------------------------------------------------------
# Top-level import
# ---------------------------------------------------------------------------


class TestEngineImport:
    """Verify that Engine is accessible from the findpapers namespace."""

    def test_engine_importable(self):
        """findpapers.Engine is the Engine class."""
        import findpapers

        assert findpapers.Engine is Engine


# ---------------------------------------------------------------------------
# Snowball
# ---------------------------------------------------------------------------


class TestEngineSnowball:
    """Tests for Engine.snowball()."""

    def test_snowball_delegates_to_runner(self):
        """snowball() creates a SnowballRunner and calls run()."""
        engine = Engine()
        seed = _make_paper("Seed", doi="10.1000/seed")

        with patch("findpapers.engine.SnowballRunner") as mock_cls:
            mock_runner = MagicMock()
            mock_graph = MagicMock()
            mock_runner.run.return_value = mock_graph
            mock_cls.return_value = mock_runner

            result = engine.snowball(seed)

        mock_cls.assert_called_once()
        mock_runner.run.assert_called_once_with(verbose=False, show_progress=True)
        assert result is mock_graph

    def test_snowball_passes_parameters(self):
        """snowball() passes configuration to SnowballRunner."""
        engine = Engine(openalex_api_key="oakey", email="me@test.com")
        seed = _make_paper("Seed", doi="10.1000/seed")

        with patch("findpapers.engine.SnowballRunner") as mock_cls:
            mock_runner = MagicMock()
            mock_runner.run.return_value = MagicMock()
            mock_cls.return_value = mock_runner

            engine.snowball(
                seed,
                depth=2,
                direction="backward",
                num_workers=3,
                verbose=True,
            )

        _, kwargs = mock_cls.call_args
        assert kwargs["depth"] == 2
        assert kwargs["direction"] == "backward"
        assert kwargs["num_workers"] == 3
        assert kwargs["openalex_api_key"] == "oakey"
        assert kwargs["email"] == "me@test.com"
        mock_runner.run.assert_called_once_with(verbose=True, show_progress=True)

    def test_snowball_accepts_list_of_papers(self):
        """snowball() accepts a list of papers."""
        engine = Engine()
        seeds = [
            _make_paper("Seed 1", doi="10.1000/s1"),
            _make_paper("Seed 2", doi="10.1000/s2"),
        ]

        with patch("findpapers.engine.SnowballRunner") as mock_cls:
            mock_runner = MagicMock()
            mock_runner.run.return_value = MagicMock()
            mock_cls.return_value = mock_runner

            engine.snowball(seeds)

        call_args = mock_cls.call_args
        assert call_args[1]["seed_papers"] is seeds

    def test_snowball_show_progress_false(self):
        """show_progress=False is forwarded to SnowballRunner.run()."""
        engine = Engine()
        seed = _make_paper("Seed", doi="10.1000/seed")

        with patch("findpapers.engine.SnowballRunner") as mock_cls:
            mock_runner = MagicMock()
            mock_runner.run.return_value = MagicMock()
            mock_cls.return_value = mock_runner

            engine.snowball(seed, show_progress=False)

        mock_runner.run.assert_called_once_with(verbose=False, show_progress=False)


class TestSnowballImport:
    """Verify snowball-related classes are accessible from findpapers namespace."""

    def test_citation_graph_importable(self):
        """findpapers.CitationGraph is accessible."""
        import findpapers
        from findpapers.core.citation_graph import CitationGraph

        assert findpapers.CitationGraph is CitationGraph

    def test_snowball_runner_importable(self):
        """findpapers.SnowballRunner is accessible."""
        import findpapers
        from findpapers.runners.snowball_runner import SnowballRunner

        assert findpapers.SnowballRunner is SnowballRunner


# ---------------------------------------------------------------------------
# Export / Load
# ---------------------------------------------------------------------------


class TestEngineExportJson:
    """Tests for Engine.export_to_json static method."""

    def test_export_search_result(self, tmp_path):
        """SearchResult is exported to a JSON file."""
        search = SearchResult(query="[test]", databases=["arxiv"])
        search.add_paper(_make_paper(doi="10.1/a"))
        path = str(tmp_path / "search.json")
        Engine.export_to_json(search, path)
        assert os.path.exists(path)

    def test_export_paper_list(self, tmp_path):
        """A plain list of papers is exported to a JSON file."""
        papers = [_make_paper(doi="10.1/a"), _make_paper(title="Paper B", doi="10.1/b")]
        path = str(tmp_path / "papers.json")
        Engine.export_to_json(papers, path)
        assert os.path.exists(path)

    def test_export_citation_graph(self, tmp_path):
        """A CitationGraph is exported to a JSON file."""
        from findpapers.core.citation_graph import CitationGraph

        seed = _make_paper(doi="10.1/seed")
        graph = CitationGraph(seed_papers=[seed], depth=1, direction="backward")
        path = str(tmp_path / "graph.json")
        Engine.export_to_json(graph, path)
        assert os.path.exists(path)


class TestEngineExportBibtex:
    """Tests for Engine.export_to_bibtex static method."""

    def test_export_search_result(self, tmp_path):
        """SearchResult is exported to a BibTeX file."""
        search = SearchResult(query="[test]", databases=["arxiv"])
        search.add_paper(_make_paper(doi="10.1/a"))
        path = str(tmp_path / "refs.bib")
        Engine.export_to_bibtex(search, path)
        content = open(path, encoding="utf-8").read()
        assert "@" in content

    def test_export_paper_list(self, tmp_path):
        """A plain list of papers is exported to a BibTeX file."""
        papers = [_make_paper(doi="10.1/a")]
        path = str(tmp_path / "refs.bib")
        Engine.export_to_bibtex(papers, path)
        content = open(path, encoding="utf-8").read()
        assert "@" in content

    def test_empty_list_produces_empty_file(self, tmp_path):
        """An empty paper list creates an empty file."""
        path = str(tmp_path / "empty.bib")
        Engine.export_to_bibtex([], path)
        content = open(path, encoding="utf-8").read()
        assert content == ""


class TestEngineLoadFromJson:
    """Tests for Engine.load_from_json static method."""

    def test_round_trip_search_result(self, tmp_path):
        """SearchResult survives export -> load round-trip via Engine."""
        search = SearchResult(query="[test]", databases=["arxiv"])
        search.add_paper(_make_paper(doi="10.1/a"))
        path = str(tmp_path / "search.json")
        Engine.export_to_json(search, path)

        loaded = Engine.load_from_json(path)
        assert isinstance(loaded, SearchResult)
        assert len(loaded.papers) == 1

    def test_round_trip_paper_list(self, tmp_path):
        """Paper list survives export -> load round-trip via Engine."""
        papers = [_make_paper(doi="10.1/a")]
        path = str(tmp_path / "papers.json")
        Engine.export_to_json(papers, path)

        loaded = Engine.load_from_json(path)
        assert isinstance(loaded, list)
        assert len(loaded) == 1
        assert loaded[0].title == "Test Paper"

    def test_round_trip_citation_graph(self, tmp_path):
        """CitationGraph survives export -> load round-trip via Engine."""
        from findpapers.core.citation_graph import CitationGraph

        seed = _make_paper(doi="10.1/seed")
        graph = CitationGraph(seed_papers=[seed], depth=1, direction="backward")
        path = str(tmp_path / "graph.json")
        Engine.export_to_json(graph, path)

        loaded = Engine.load_from_json(path)
        assert isinstance(loaded, CitationGraph)
        assert loaded.paper_count == 1
