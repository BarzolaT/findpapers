"""Citation graph model for snowballing operations.

A :class:`CitationGraph` captures the directed citation relationships between
academic papers discovered during a snowballing process.  Each node is a
:class:`~findpapers.core.paper.Paper` and each directed edge indicates that
one paper cites another.
"""

from __future__ import annotations

from typing import Literal

from findpapers.core.paper import Paper
from findpapers.utils.version import package_version


class CitationEdge:
    """A directed citation relationship: *source* cites *target*.

    Parameters
    ----------
    source : Paper
        The citing paper.
    target : Paper
        The cited paper.
    """

    def __init__(self, source: Paper, target: Paper) -> None:
        """Create a CitationEdge.

        Parameters
        ----------
        source : Paper
            The citing paper.
        target : Paper
            The cited paper.
        """
        self.source = source
        self.target = target

    def to_dict(self) -> dict:
        """Serialize the edge to a dictionary.

        Returns
        -------
        dict
            Dictionary with ``source_doi``, ``source_title``,
            ``target_doi`` and ``target_title`` keys.
        """
        return {
            "source_doi": self.source.doi,
            "source_title": self.source.title,
            "target_doi": self.target.doi,
            "target_title": self.target.title,
        }


class CitationGraph:
    """A directed citation graph built by snowballing from seed papers.

    The graph contains a set of :class:`~findpapers.core.paper.Paper` nodes
    and :class:`CitationEdge` directed edges (``source`` → ``target`` means
    *source cites target*).

    Parameters
    ----------
    seed_papers : list[Paper]
        The initial papers from which the snowball started.
    depth : int
        Maximum traversal depth used during construction.
    direction : Literal["both", "backward", "forward"]
        The snowball direction(s) used during construction.
    """

    def __init__(
        self,
        seed_papers: list[Paper],
        depth: int,
        direction: Literal["both", "backward", "forward"],
    ) -> None:
        """Create a CitationGraph.

        Parameters
        ----------
        seed_papers : list[Paper]
            Initial seed papers.
        depth : int
            Maximum traversal depth.
        direction : Literal["both", "backward", "forward"]
            Snowball direction(s).
        """
        self.seed_papers: list[Paper] = list(seed_papers)
        self.depth = depth
        self.direction = direction
        # All papers in the graph, keyed by a unique identifier (DOI preferred,
        # falling back to title).
        self._papers: dict[str, Paper] = {}
        self._edges: list[CitationEdge] = []
        # Track the depth at which each paper was first discovered.
        self._paper_depths: dict[str, int] = {}

        # Register seed papers at depth 0.
        for paper in self.seed_papers:
            key = self._paper_key(paper)
            if key:
                self._papers[key] = paper
                self._paper_depths[key] = 0

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def papers(self) -> list[Paper]:
        """Return all papers in the graph.

        Returns
        -------
        list[Paper]
            All paper nodes.
        """
        return list(self._papers.values())

    @property
    def edges(self) -> list[CitationEdge]:
        """Return all citation edges.

        Returns
        -------
        list[CitationEdge]
            Directed citation edges.
        """
        return list(self._edges)

    # ------------------------------------------------------------------
    # Graph construction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _paper_key(paper: Paper) -> str | None:
        """Return a unique key for a paper, or ``None`` if not identifiable.

        Prefers DOI; falls back to lowercased title.

        Parameters
        ----------
        paper : Paper
            The paper to key.

        Returns
        -------
        str | None
            A unique string key, or ``None``.
        """
        if paper.doi:
            return paper.doi.strip().lower()
        if paper.title:
            return paper.title.strip().lower()
        return None

    def contains(self, paper: Paper) -> bool:
        """Check whether the graph already contains a paper.

        Parameters
        ----------
        paper : Paper
            Paper to check.

        Returns
        -------
        bool
            ``True`` if the paper (by DOI or title) is already in the graph.
        """
        key = self._paper_key(paper)
        return key is not None and key in self._papers

    def add_paper(self, paper: Paper, depth: int) -> Paper:
        """Add a paper to the graph (or merge with an existing entry).

        If the paper already exists it is merged and the existing instance
        is returned.  Otherwise the new paper is stored and returned.

        Parameters
        ----------
        paper : Paper
            Paper to add.
        depth : int
            The traversal depth at which this paper was discovered.

        Returns
        -------
        Paper
            The canonical paper instance in the graph.
        """
        key = self._paper_key(paper)
        if key is None:
            return paper

        if key in self._papers:
            self._papers[key].merge(paper)
            # Keep the shallowest depth.
            if depth < self._paper_depths.get(key, depth + 1):
                self._paper_depths[key] = depth
            return self._papers[key]

        self._papers[key] = paper
        self._paper_depths[key] = depth
        return paper

    def add_edge(self, source: Paper, target: Paper) -> None:
        """Record a citation edge (``source`` cites ``target``).

        Both papers must already be present in the graph (via
        :meth:`add_paper`).  Duplicate edges are silently ignored.

        Parameters
        ----------
        source : Paper
            The citing paper.
        target : Paper
            The cited paper.
        """
        # Resolve to canonical instances.
        source_key = self._paper_key(source)
        target_key = self._paper_key(target)
        if source_key is None or target_key is None:
            return

        canonical_source = self._papers.get(source_key, source)
        canonical_target = self._papers.get(target_key, target)

        # Prevent duplicate edges.
        for edge in self._edges:
            existing_src = self._paper_key(edge.source)
            existing_tgt = self._paper_key(edge.target)
            if existing_src == source_key and existing_tgt == target_key:
                return

        self._edges.append(CitationEdge(source=canonical_source, target=canonical_target))

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_references(self, paper: Paper) -> list[Paper]:
        """Return papers cited *by* the given paper (backward direction).

        Parameters
        ----------
        paper : Paper
            The citing paper.

        Returns
        -------
        list[Paper]
            Papers that *paper* cites.
        """
        key = self._paper_key(paper)
        return [edge.target for edge in self._edges if self._paper_key(edge.source) == key]

    def get_cited_by(self, paper: Paper) -> list[Paper]:
        """Return papers that cite the given paper (forward direction).

        Parameters
        ----------
        paper : Paper
            The cited paper.

        Returns
        -------
        list[Paper]
            Papers that cite *paper*.
        """
        key = self._paper_key(paper)
        return [edge.source for edge in self._edges if self._paper_key(edge.target) == key]

    def get_paper_depth(self, paper: Paper) -> int | None:
        """Return the traversal depth at which a paper was first discovered.

        Seed papers have depth 0.

        Parameters
        ----------
        paper : Paper
            Paper to query.

        Returns
        -------
        int | None
            Depth, or ``None`` if the paper is not in the graph.
        """
        key = self._paper_key(paper)
        if key is None:
            return None
        return self._paper_depths.get(key)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialize the citation graph to a dictionary.

        Returns
        -------
        dict
            Dictionary with ``metadata``, ``nodes`` and ``edges`` keys.
        """
        return {
            "metadata": {
                "seed_papers": [{"doi": p.doi, "title": p.title} for p in self.seed_papers],
                "depth": self.depth,
                "direction": self.direction,
                "total_papers": len(self._papers),
                "total_edges": len(self._edges),
                "version": package_version(),
            },
            "nodes": [
                {
                    **Paper.to_dict(paper),
                    "snowball_depth": self._paper_depths.get(
                        self._paper_key(paper), -1  # type: ignore[arg-type]
                    ),
                }
                for paper in self._papers.values()
            ],
            "edges": [edge.to_dict() for edge in self._edges],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CitationGraph":
        """Reconstruct a CitationGraph from a dictionary.

        Accepts the format produced by :meth:`to_dict` (and by
        :func:`~findpapers.utils.export.export_to_json`).

        Parameters
        ----------
        data : dict
            Dictionary with ``"metadata"``, ``"nodes"`` and ``"edges"``
            keys.

        Returns
        -------
        CitationGraph
            Reconstructed instance.
        """
        metadata = data.get("metadata", {})
        direction = metadata.get("direction", "both")
        depth = metadata.get("depth", 0)

        # Rebuild papers keyed by DOI / title.
        papers: dict[str, Paper] = {}
        paper_depths: dict[str, int] = {}
        for node in data.get("nodes", []):
            paper = Paper.from_dict(node)
            key = (paper.doi or "").strip().lower() or (paper.title or "").strip().lower()
            if not key:
                continue
            papers[key] = paper
            paper_depths[key] = node.get("snowball_depth", -1)

        # Identify seeds (depth == 0).
        seed_papers = [p for k, p in papers.items() if paper_depths.get(k) == 0]

        graph = cls(seed_papers=[], depth=depth, direction=direction)
        graph._papers = papers
        graph._paper_depths = paper_depths
        graph.seed_papers = seed_papers

        # Rebuild edges.
        for edge_dict in data.get("edges", []):
            src_doi = (edge_dict.get("source_doi") or "").strip().lower()
            src_title = (edge_dict.get("source_title") or "").strip().lower()
            tgt_doi = (edge_dict.get("target_doi") or "").strip().lower()
            tgt_title = (edge_dict.get("target_title") or "").strip().lower()

            src_key = src_doi or src_title
            tgt_key = tgt_doi or tgt_title
            if src_key in papers and tgt_key in papers:
                graph._edges.append(CitationEdge(source=papers[src_key], target=papers[tgt_key]))

        return graph

    @property
    def paper_count(self) -> int:
        """Return the number of unique papers in the graph.

        Returns
        -------
        int
            Number of paper nodes.
        """
        return len(self._papers)

    @property
    def edge_count(self) -> int:
        """Return the number of citation edges.

        Returns
        -------
        int
            Number of directed edges.
        """
        return len(self._edges)
