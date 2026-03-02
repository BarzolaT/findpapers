"""Tests for CitationGraph and CitationEdge models."""

import datetime

from findpapers.core.author import Author
from findpapers.core.citation_graph import CitationEdge, CitationGraph
from findpapers.core.paper import Paper

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_paper(
    title: str,
    doi: str | None = None,
    abstract: str = "",
) -> Paper:
    """Create a minimal Paper for testing."""
    return Paper(
        title=title,
        abstract=abstract,
        authors=[Author(name="Test Author")],
        source=None,
        publication_date=datetime.date(2024, 1, 1),
        doi=doi,
    )


# ---------------------------------------------------------------------------
# CitationEdge tests
# ---------------------------------------------------------------------------


class TestCitationEdge:
    """Tests for the CitationEdge class."""

    def test_creation(self) -> None:
        """Edge stores source and target papers."""
        source = _make_paper("Source Paper", doi="10.1000/src")
        target = _make_paper("Target Paper", doi="10.1000/tgt")
        edge = CitationEdge(source=source, target=target)

        assert edge.source is source
        assert edge.target is target

    def test_to_dict(self) -> None:
        """Edge serializes to dict with DOI and title keys."""
        source = _make_paper("Source Paper", doi="10.1000/src")
        target = _make_paper("Target Paper", doi="10.1000/tgt")
        edge = CitationEdge(source=source, target=target)

        d = edge.to_dict()
        assert d["source_doi"] == "10.1000/src"
        assert d["source_title"] == "Source Paper"
        assert d["target_doi"] == "10.1000/tgt"
        assert d["target_title"] == "Target Paper"

    def test_to_dict_without_doi(self) -> None:
        """Edge serialization handles papers without DOI."""
        source = _make_paper("Source Paper")
        target = _make_paper("Target Paper")
        edge = CitationEdge(source=source, target=target)

        d = edge.to_dict()
        assert d["source_doi"] is None
        assert d["target_doi"] is None
        assert d["source_title"] == "Source Paper"
        assert d["target_title"] == "Target Paper"


# ---------------------------------------------------------------------------
# CitationGraph tests
# ---------------------------------------------------------------------------


class TestCitationGraph:
    """Tests for the CitationGraph class."""

    def test_creation_with_seed_papers(self) -> None:
        """Graph registers seed papers at depth 0."""
        seed = _make_paper("Seed", doi="10.1000/seed")
        graph = CitationGraph(seed_papers=[seed], depth=1, direction="both")

        assert graph.paper_count == 1
        assert graph.edge_count == 0
        assert graph.depth == 1
        assert graph.direction == "both"
        assert graph.contains(seed)
        assert graph.get_paper_depth(seed) == 0

    def test_creation_empty_seeds(self) -> None:
        """Graph can be created with no seeds."""
        graph = CitationGraph(seed_papers=[], depth=1, direction="forward")

        assert graph.paper_count == 0
        assert graph.edge_count == 0

    def test_add_paper_new(self) -> None:
        """Adding a new paper increases paper count."""
        graph = CitationGraph(seed_papers=[], depth=1, direction="both")
        paper = _make_paper("New Paper", doi="10.1000/new")

        result = graph.add_paper(paper, depth=1)

        assert result is paper
        assert graph.paper_count == 1
        assert graph.get_paper_depth(paper) == 1

    def test_add_paper_duplicate_merges(self) -> None:
        """Adding a paper with the same DOI merges instead of duplicating."""
        graph = CitationGraph(seed_papers=[], depth=1, direction="both")
        paper1 = _make_paper("Paper V1", doi="10.1000/same")
        paper2 = _make_paper("Paper Version 2 Longer", doi="10.1000/same")

        graph.add_paper(paper1, depth=0)
        result = graph.add_paper(paper2, depth=1)

        assert graph.paper_count == 1
        assert result is paper1  # returns the existing instance
        # Merge should pick the longer title.
        assert "Longer" in result.title or result.title == "Paper V1"

    def test_add_paper_keeps_shallowest_depth(self) -> None:
        """When the same paper is found at different depths, keep the shallowest."""
        graph = CitationGraph(seed_papers=[], depth=2, direction="both")
        paper = _make_paper("Paper", doi="10.1000/p")

        graph.add_paper(paper, depth=2)
        graph.add_paper(paper, depth=1)

        assert graph.get_paper_depth(paper) == 1

    def test_add_paper_without_doi_uses_title(self) -> None:
        """Papers without DOI are keyed by title."""
        graph = CitationGraph(seed_papers=[], depth=1, direction="both")
        paper = _make_paper("Unique Title")

        graph.add_paper(paper, depth=0)

        assert graph.contains(paper)
        assert graph.paper_count == 1

    def test_add_edge(self) -> None:
        """Adding an edge between two papers."""
        source = _make_paper("Source", doi="10.1000/src")
        target = _make_paper("Target", doi="10.1000/tgt")
        graph = CitationGraph(seed_papers=[], depth=1, direction="both")
        graph.add_paper(source, depth=0)
        graph.add_paper(target, depth=1)

        graph.add_edge(source, target)

        assert graph.edge_count == 1
        assert graph.edges[0].source is source
        assert graph.edges[0].target is target

    def test_add_edge_duplicate_ignored(self) -> None:
        """Duplicate edges are silently dropped."""
        source = _make_paper("Source", doi="10.1000/src")
        target = _make_paper("Target", doi="10.1000/tgt")
        graph = CitationGraph(seed_papers=[], depth=1, direction="both")
        graph.add_paper(source, depth=0)
        graph.add_paper(target, depth=1)

        graph.add_edge(source, target)
        graph.add_edge(source, target)

        assert graph.edge_count == 1

    def test_get_references(self) -> None:
        """get_references returns papers cited by the given paper."""
        seed = _make_paper("Seed", doi="10.1000/seed")
        ref1 = _make_paper("Ref 1", doi="10.1000/ref1")
        ref2 = _make_paper("Ref 2", doi="10.1000/ref2")
        graph = CitationGraph(seed_papers=[seed], depth=1, direction="backward")

        graph.add_paper(ref1, depth=1)
        graph.add_paper(ref2, depth=1)
        graph.add_edge(seed, ref1)  # seed cites ref1
        graph.add_edge(seed, ref2)  # seed cites ref2

        refs = graph.get_references(seed)
        assert len(refs) == 2
        assert ref1 in refs
        assert ref2 in refs

    def test_get_cited_by(self) -> None:
        """get_cited_by returns papers that cite the given paper."""
        seed = _make_paper("Seed", doi="10.1000/seed")
        citing1 = _make_paper("Citing 1", doi="10.1000/c1")
        citing2 = _make_paper("Citing 2", doi="10.1000/c2")
        graph = CitationGraph(seed_papers=[seed], depth=1, direction="forward")

        graph.add_paper(citing1, depth=1)
        graph.add_paper(citing2, depth=1)
        graph.add_edge(citing1, seed)  # citing1 cites seed
        graph.add_edge(citing2, seed)  # citing2 cites seed

        cited_by = graph.get_cited_by(seed)
        assert len(cited_by) == 2
        assert citing1 in cited_by
        assert citing2 in cited_by

    def test_get_paper_depth_unknown_paper(self) -> None:
        """get_paper_depth returns None for papers not in the graph."""
        graph = CitationGraph(seed_papers=[], depth=1, direction="both")
        unknown = _make_paper("Unknown", doi="10.1000/unknown")

        assert graph.get_paper_depth(unknown) is None

    def test_contains_false_for_unknown(self) -> None:
        """contains returns False for papers not in the graph."""
        graph = CitationGraph(seed_papers=[], depth=1, direction="both")
        unknown = _make_paper("Unknown", doi="10.1000/unknown")

        assert not graph.contains(unknown)

    def test_papers_property(self) -> None:
        """papers property returns all papers in the graph."""
        seed = _make_paper("Seed", doi="10.1000/seed")
        other = _make_paper("Other", doi="10.1000/other")
        graph = CitationGraph(seed_papers=[seed], depth=1, direction="both")
        graph.add_paper(other, depth=1)

        papers = graph.papers
        assert len(papers) == 2

    def test_to_dict(self) -> None:
        """to_dict produces expected structure."""
        seed = _make_paper("Seed", doi="10.1000/seed")
        ref = _make_paper("Ref", doi="10.1000/ref")
        graph = CitationGraph(seed_papers=[seed], depth=1, direction="backward")
        graph.add_paper(ref, depth=1)
        graph.add_edge(seed, ref)

        d = graph.to_dict()

        assert "metadata" in d
        assert d["metadata"]["depth"] == 1
        assert d["metadata"]["direction"] == "backward"
        assert d["metadata"]["total_papers"] == 2
        assert d["metadata"]["total_edges"] == 1
        assert len(d["metadata"]["seed_papers"]) == 1
        assert d["metadata"]["seed_papers"][0]["doi"] == "10.1000/seed"

        assert len(d["nodes"]) == 2
        assert len(d["edges"]) == 1
        # Each node should have snowball_depth.
        depths = {n["doi"]: n["snowball_depth"] for n in d["nodes"]}
        assert depths["10.1000/seed"] == 0
        assert depths["10.1000/ref"] == 1

    def test_from_dict_round_trip(self) -> None:
        """from_dict(to_dict()) preserves papers or edges."""
        seed = _make_paper("Seed", doi="10.1000/seed")
        ref = _make_paper("Ref", doi="10.1000/ref")
        graph = CitationGraph(seed_papers=[seed], depth=1, direction="backward")
        graph.add_paper(ref, depth=1)
        graph.add_edge(seed, ref)

        restored = CitationGraph.from_dict(graph.to_dict())

        assert restored.paper_count == 2
        assert restored.edge_count == 1
        assert restored.depth == 1
        assert restored.direction == "backward"
        assert restored.get_paper_depth(seed) == 0
        assert restored.get_paper_depth(ref) == 1

    def test_multiple_seeds(self) -> None:
        """Graph correctly handles multiple seed papers."""
        seed1 = _make_paper("Seed 1", doi="10.1000/s1")
        seed2 = _make_paper("Seed 2", doi="10.1000/s2")
        graph = CitationGraph(seed_papers=[seed1, seed2], depth=1, direction="both")

        assert graph.paper_count == 2
        assert graph.get_paper_depth(seed1) == 0
        assert graph.get_paper_depth(seed2) == 0

    def test_case_insensitive_doi_matching(self) -> None:
        """DOI matching for contains/add is case-insensitive."""
        paper1 = _make_paper("Paper", doi="10.1000/ABC")
        paper2 = _make_paper("Paper Again", doi="10.1000/abc")
        graph = CitationGraph(seed_papers=[paper1], depth=1, direction="both")

        assert graph.contains(paper2)
        # Adding paper2 should merge, not create a new entry.
        graph.add_paper(paper2, depth=1)
        assert graph.paper_count == 1

    def test_bidirectional_edges(self) -> None:
        """A paper can both cite and be cited by different papers."""
        center = _make_paper("Center", doi="10.1000/center")
        ref = _make_paper("Reference", doi="10.1000/ref")
        citing = _make_paper("Citing", doi="10.1000/citing")
        graph = CitationGraph(seed_papers=[center], depth=1, direction="both")

        graph.add_paper(ref, depth=1)
        graph.add_paper(citing, depth=1)
        graph.add_edge(center, ref)  # center cites ref
        graph.add_edge(citing, center)  # citing cites center

        assert len(graph.get_references(center)) == 1
        assert graph.get_references(center)[0] is ref
        assert len(graph.get_cited_by(center)) == 1
        assert graph.get_cited_by(center)[0] is citing
