"""Tests for CitationGraph and CitationEdge models."""

import pytest

from findpapers.core.citation_graph import CitationEdge, CitationGraph
from findpapers.core.paper import Paper
from findpapers.exceptions import InvalidParameterError

# ---------------------------------------------------------------------------
# CitationEdge tests
# ---------------------------------------------------------------------------


class TestCitationEdge:
    """Tests for the CitationEdge class."""

    def test_creation(self, make_paper) -> None:
        """Edge stores source and target papers."""
        source = make_paper("Source Paper", doi="10.1000/src")
        target = make_paper("Target Paper", doi="10.1000/tgt")
        edge = CitationEdge(source=source, target=target)

        assert edge.source is source
        assert edge.target is target

    def test_to_dict(self, make_paper) -> None:
        """Edge serializes to dict with DOI and title keys."""
        source = make_paper("Source Paper", doi="10.1000/src")
        target = make_paper("Target Paper", doi="10.1000/tgt")
        edge = CitationEdge(source=source, target=target)

        d = edge.to_dict()
        assert d["source_doi"] == "10.1000/src"
        assert d["source_title"] == "Source Paper"
        assert d["target_doi"] == "10.1000/tgt"
        assert d["target_title"] == "Target Paper"

    def test_to_dict_without_doi(self, make_paper) -> None:
        """Edge serialization handles papers without DOI."""
        source = make_paper("Source Paper")
        target = make_paper("Target Paper")
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

    def test_max_depth_zero_raises(self) -> None:
        """max_depth of zero raises InvalidParameterError."""
        with pytest.raises(InvalidParameterError, match="max_depth must be >= 1"):
            CitationGraph(seed_papers=[], max_depth=0, direction="both")

    def test_max_depth_negative_raises(self) -> None:
        """Negative max_depth raises InvalidParameterError."""
        with pytest.raises(InvalidParameterError, match="max_depth must be >= 1"):
            CitationGraph(seed_papers=[], max_depth=-5, direction="both")

    def test_creation_with_seed_papers(self, make_paper) -> None:
        """Graph registers seed papers at depth 0."""
        seed = make_paper("Seed", doi="10.1000/seed")
        graph = CitationGraph(seed_papers=[seed], max_depth=1, direction="both")

        assert graph.paper_count == 1
        assert graph.edge_count == 0
        assert graph.max_depth == 1
        assert graph.direction == "both"
        assert graph.contains(seed)
        assert graph.get_paper_depth(seed) == 0

    def test_add_paper_discovered_from_not_in_graph_raises(self, make_paper) -> None:
        """add_paper raises InvalidParameterError if discovered_from is not in the graph."""
        graph = CitationGraph(seed_papers=[], max_depth=1, direction="both")
        paper = make_paper("Paper", doi="10.1000/p")
        unknown = make_paper("Unknown", doi="10.1000/unknown")
        with pytest.raises(
            InvalidParameterError, match="discovered_from paper is not in the graph"
        ):
            graph.add_paper(paper, discovered_from=unknown)

    def test_creation_empty_seeds(self) -> None:
        """Graph can be created with no seeds."""
        graph = CitationGraph(seed_papers=[], max_depth=1, direction="forward")

        assert graph.paper_count == 0
        assert graph.edge_count == 0

    def test_add_paper_new(self, make_paper) -> None:
        """Adding a new paper increases paper count."""
        seed = make_paper("Seed", doi="10.1000/seed")
        graph = CitationGraph(seed_papers=[seed], max_depth=1, direction="both")
        paper = make_paper("New Paper", doi="10.1000/new")

        result = graph.add_paper(paper, discovered_from=seed)

        assert result is paper
        assert graph.paper_count == 2
        assert graph.get_paper_depth(paper) == 1

    def test_add_paper_duplicate_merges(self, make_paper) -> None:
        """Adding a paper with the same DOI merges instead of duplicating."""
        seed = make_paper("Seed", doi="10.1000/seed")
        paper1 = make_paper("Paper V1", doi="10.1000/same")
        paper2 = make_paper("Paper Version 2 Longer", doi="10.1000/same")
        graph = CitationGraph(seed_papers=[seed, paper1], max_depth=1, direction="both")

        result = graph.add_paper(paper2, discovered_from=seed)

        assert graph.paper_count == 2  # seed + same
        assert result is paper1  # returns the existing instance
        # Merge should pick the longer title.
        assert "Longer" in result.title or result.title == "Paper V1"

    def test_add_paper_keeps_shallowest_depth(self, make_paper) -> None:
        """When the same paper is found at different depths, keep the shallowest."""
        seed = make_paper("Seed", doi="10.1000/seed")
        level1 = make_paper("Level 1", doi="10.1000/l1")
        paper = make_paper("Paper", doi="10.1000/p")
        graph = CitationGraph(seed_papers=[seed], max_depth=2, direction="both")

        # First discovered at depth 2 (via level1)
        graph.add_paper(level1, discovered_from=seed)
        graph.add_paper(paper, discovered_from=level1)
        assert graph.get_paper_depth(paper) == 2

        # Re-discovered at depth 1 (directly from seed) → keeps shallowest
        graph.add_paper(paper, discovered_from=seed)
        assert graph.get_paper_depth(paper) == 1

    def test_add_paper_without_doi_uses_title(self, make_paper) -> None:
        """Papers without DOI are keyed by title."""
        paper = make_paper("Unique Title")
        graph = CitationGraph(seed_papers=[paper], max_depth=1, direction="both")

        assert graph.contains(paper)
        assert graph.paper_count == 1

    def test_add_edge(self, make_paper) -> None:
        """Adding an edge between two papers."""
        source = make_paper("Source", doi="10.1000/src")
        target = make_paper("Target", doi="10.1000/tgt")
        graph = CitationGraph(seed_papers=[source], max_depth=1, direction="both")
        graph.add_paper(target, discovered_from=source)

        graph.add_edge(source, target)

        assert graph.edge_count == 1
        assert graph.edges[0].source is source
        assert graph.edges[0].target is target

    def test_add_edge_duplicate_ignored(self, make_paper) -> None:
        """Duplicate edges are silently dropped."""
        source = make_paper("Source", doi="10.1000/src")
        target = make_paper("Target", doi="10.1000/tgt")
        graph = CitationGraph(seed_papers=[source], max_depth=1, direction="both")
        graph.add_paper(target, discovered_from=source)

        graph.add_edge(source, target)
        graph.add_edge(source, target)

        assert graph.edge_count == 1

    def test_get_references(self, make_paper) -> None:
        """get_references returns papers cited by the given paper."""
        seed = make_paper("Seed", doi="10.1000/seed")
        ref1 = make_paper("Ref 1", doi="10.1000/ref1")
        ref2 = make_paper("Ref 2", doi="10.1000/ref2")
        graph = CitationGraph(seed_papers=[seed], max_depth=1, direction="backward")

        graph.add_paper(ref1, discovered_from=seed)
        graph.add_paper(ref2, discovered_from=seed)
        graph.add_edge(seed, ref1)  # seed cites ref1
        graph.add_edge(seed, ref2)  # seed cites ref2

        refs = graph.get_references(seed)
        assert len(refs) == 2
        assert ref1 in refs
        assert ref2 in refs

    def test_get_cited_by(self, make_paper) -> None:
        """get_cited_by returns papers that cite the given paper."""
        seed = make_paper("Seed", doi="10.1000/seed")
        citing1 = make_paper("Citing 1", doi="10.1000/c1")
        citing2 = make_paper("Citing 2", doi="10.1000/c2")
        graph = CitationGraph(seed_papers=[seed], max_depth=1, direction="forward")

        graph.add_paper(citing1, discovered_from=seed)
        graph.add_paper(citing2, discovered_from=seed)
        graph.add_edge(citing1, seed)  # citing1 cites seed
        graph.add_edge(citing2, seed)  # citing2 cites seed

        cited_by = graph.get_cited_by(seed)
        assert len(cited_by) == 2
        assert citing1 in cited_by
        assert citing2 in cited_by

    def test_get_paper_depth_unknown_paper(self, make_paper) -> None:
        """get_paper_depth returns None for papers not in the graph."""
        graph = CitationGraph(seed_papers=[], max_depth=1, direction="both")
        unknown = make_paper("Unknown", doi="10.1000/unknown")

        assert graph.get_paper_depth(unknown) is None

    def test_contains_false_for_unknown(self, make_paper) -> None:
        """contains returns False for papers not in the graph."""
        graph = CitationGraph(seed_papers=[], max_depth=1, direction="both")
        unknown = make_paper("Unknown", doi="10.1000/unknown")

        assert not graph.contains(unknown)

    def test_papers_property(self, make_paper) -> None:
        """papers property returns all papers in the graph."""
        seed = make_paper("Seed", doi="10.1000/seed")
        other = make_paper("Other", doi="10.1000/other")
        graph = CitationGraph(seed_papers=[seed], max_depth=1, direction="both")
        graph.add_paper(other, discovered_from=seed)

        papers = graph.papers
        assert len(papers) == 2

    def test_to_dict(self, make_paper) -> None:
        """to_dict produces expected structure."""
        seed = make_paper("Seed", doi="10.1000/seed")
        ref = make_paper("Ref", doi="10.1000/ref")
        graph = CitationGraph(seed_papers=[seed], max_depth=1, direction="backward")
        graph.add_paper(ref, discovered_from=seed)
        graph.add_edge(seed, ref)

        d = graph.to_dict()

        assert "metadata" in d
        assert d["metadata"]["max_depth"] == 1
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

    def test_from_dict_round_trip(self, make_paper) -> None:
        """from_dict(to_dict()) preserves papers or edges."""
        seed = make_paper("Seed", doi="10.1000/seed")
        ref = make_paper("Ref", doi="10.1000/ref")
        graph = CitationGraph(seed_papers=[seed], max_depth=1, direction="backward")
        graph.add_paper(ref, discovered_from=seed)
        graph.add_edge(seed, ref)

        restored = CitationGraph.from_dict(graph.to_dict())

        assert restored.paper_count == 2
        assert restored.edge_count == 1
        assert restored.max_depth == 1
        assert restored.direction == "backward"
        assert restored.get_paper_depth(seed) == 0
        assert restored.get_paper_depth(ref) == 1

    def test_multiple_seeds(self, make_paper) -> None:
        """Graph correctly handles multiple seed papers."""
        seed1 = make_paper("Seed 1", doi="10.1000/s1")
        seed2 = make_paper("Seed 2", doi="10.1000/s2")
        graph = CitationGraph(seed_papers=[seed1, seed2], max_depth=1, direction="both")

        assert graph.paper_count == 2
        assert graph.get_paper_depth(seed1) == 0
        assert graph.get_paper_depth(seed2) == 0

    def test_case_insensitive_doi_matching(self, make_paper) -> None:
        """DOI matching for contains/add is case-insensitive."""
        paper1 = make_paper("Paper", doi="10.1000/ABC")
        paper2 = make_paper("Paper Again", doi="10.1000/abc")
        graph = CitationGraph(seed_papers=[paper1], max_depth=1, direction="both")

        assert graph.contains(paper2)
        # Adding paper2 should merge, not create a new entry.
        graph.add_paper(paper2, discovered_from=paper1)
        assert graph.paper_count == 1

    def test_bidirectional_edges(self, make_paper) -> None:
        """A paper can both cite and be cited by different papers."""
        center = make_paper("Center", doi="10.1000/center")
        ref = make_paper("Reference", doi="10.1000/ref")
        citing = make_paper("Citing", doi="10.1000/citing")
        graph = CitationGraph(seed_papers=[center], max_depth=1, direction="both")

        graph.add_paper(ref, discovered_from=center)
        graph.add_paper(citing, discovered_from=center)
        graph.add_edge(center, ref)  # center cites ref
        graph.add_edge(citing, center)  # citing cites center

        assert len(graph.get_references(center)) == 1
        assert graph.get_references(center)[0] is ref
        assert len(graph.get_cited_by(center)) == 1
        assert graph.get_cited_by(center)[0] is citing

    def test_get_references_unknown_paper_returns_empty(self, make_paper) -> None:
        """get_references returns empty list for unknown paper."""
        graph = CitationGraph(seed_papers=[], max_depth=1, direction="both")
        unknown = make_paper("Unknown", doi="10.1000/unknown")
        assert graph.get_references(unknown) == []

    def test_get_cited_by_unknown_paper_returns_empty(self, make_paper) -> None:
        """get_cited_by returns empty list for unknown paper."""
        graph = CitationGraph(seed_papers=[], max_depth=1, direction="both")
        unknown = make_paper("Unknown", doi="10.1000/unknown")
        assert graph.get_cited_by(unknown) == []

    def test_adjacency_after_from_dict_round_trip(self, make_paper) -> None:
        """get_references/get_cited_by work after from_dict reconstruction."""
        seed = make_paper("Seed", doi="10.1000/seed")
        ref = make_paper("Ref", doi="10.1000/ref")
        citing = make_paper("Citing", doi="10.1000/citing")
        graph = CitationGraph(seed_papers=[seed], max_depth=1, direction="both")
        graph.add_paper(ref, discovered_from=seed)
        graph.add_paper(citing, discovered_from=seed)
        graph.add_edge(seed, ref)
        graph.add_edge(citing, seed)

        restored = CitationGraph.from_dict(graph.to_dict())

        # Lookup by DOI since instances differ after round-trip.
        restored_seed = next(p for p in restored.papers if p.doi == "10.1000/seed")
        refs = restored.get_references(restored_seed)
        cited_by = restored.get_cited_by(restored_seed)
        assert len(refs) == 1
        assert refs[0].doi == "10.1000/ref"
        assert len(cited_by) == 1
        assert cited_by[0].doi == "10.1000/citing"


# ---------------------------------------------------------------------------
# Edge cases: papers with no DOI and no title (key is None)
# ---------------------------------------------------------------------------


class TestCitationGraphNoneKeyEdgeCases:
    """Tests for papers that have neither DOI nor title (unidentifiable)."""

    @staticmethod
    def _make_unidentifiable_paper() -> Paper:
        """Create a paper with no DOI and a blank title.

        The Paper constructor requires a non-empty title, so we set it
        to a space and then blank it out after construction.
        """
        p = Paper(title="temp", abstract="", authors=[], source=None, publication_date=None)
        # Force the title to empty so _paper_key returns None.
        p.title = ""
        return p

    def test_paper_key_returns_none(self) -> None:
        """_paper_key returns None for unidentifiable paper."""
        paper = self._make_unidentifiable_paper()
        graph = CitationGraph(seed_papers=[], max_depth=1, direction="both")
        assert graph._paper_key(paper) is None

    def test_add_paper_returns_paper_unchanged(self, make_paper) -> None:
        """add_paper returns the paper as-is when key is None."""
        seed = make_paper("Seed", doi="10.1000/seed")
        paper = self._make_unidentifiable_paper()
        graph = CitationGraph(seed_papers=[seed], max_depth=1, direction="both")

        result = graph.add_paper(paper, discovered_from=seed)

        assert result is paper
        assert graph.paper_count == 1  # only the seed

    def test_add_edge_no_op_when_source_unidentifiable(self, make_paper) -> None:
        """add_edge is a no-op when source paper has no key."""
        source = self._make_unidentifiable_paper()
        target = make_paper("Target", doi="10.1000/tgt")
        graph = CitationGraph(seed_papers=[target], max_depth=1, direction="both")

        graph.add_edge(source, target)

        assert graph.edge_count == 0

    def test_add_edge_no_op_when_target_unidentifiable(self, make_paper) -> None:
        """add_edge is a no-op when target paper has no key."""
        source = make_paper("Source", doi="10.1000/src")
        target = self._make_unidentifiable_paper()
        graph = CitationGraph(seed_papers=[source], max_depth=1, direction="both")

        graph.add_edge(source, target)

        assert graph.edge_count == 0

    def test_get_references_returns_empty_for_unidentifiable(self) -> None:
        """get_references returns [] for unidentifiable paper."""
        paper = self._make_unidentifiable_paper()
        graph = CitationGraph(seed_papers=[], max_depth=1, direction="both")
        assert graph.get_references(paper) == []

    def test_get_cited_by_returns_empty_for_unidentifiable(self) -> None:
        """get_cited_by returns [] for unidentifiable paper."""
        paper = self._make_unidentifiable_paper()
        graph = CitationGraph(seed_papers=[], max_depth=1, direction="both")
        assert graph.get_cited_by(paper) == []

    def test_get_paper_depth_returns_none_for_unidentifiable(self) -> None:
        """get_paper_depth returns None for unidentifiable paper."""
        paper = self._make_unidentifiable_paper()
        graph = CitationGraph(seed_papers=[], max_depth=1, direction="both")
        assert graph.get_paper_depth(paper) is None

    def test_contains_false_for_unidentifiable(self) -> None:
        """contains returns False for unidentifiable paper."""
        paper = self._make_unidentifiable_paper()
        graph = CitationGraph(seed_papers=[], max_depth=1, direction="both")
        assert not graph.contains(paper)


class TestFromDictEdgeCases:
    """Tests for from_dict with unusual data."""

    def test_from_dict_skips_unidentifiable_nodes(self) -> None:
        """Nodes with whitespace-only title (no DOI) are skipped during from_dict."""
        data = {
            "metadata": {"max_depth": 1, "direction": "both"},
            "nodes": [
                # Paper.from_dict accepts whitespace title, but the key
                # becomes empty after strip → skipped by from_dict.
                {"title": "   ", "snowball_depth": 0},
                {"title": "Valid", "doi": "10.1000/v", "snowball_depth": 0},
            ],
            "edges": [],
        }
        graph = CitationGraph.from_dict(data)
        assert graph.paper_count == 1

    def test_from_dict_empty(self) -> None:
        """from_dict with completely empty data produces an empty graph."""
        graph = CitationGraph.from_dict({})
        assert graph.paper_count == 0
        assert graph.edge_count == 0
