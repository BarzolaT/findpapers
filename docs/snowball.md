# Snowball

The `engine.snowball()` method builds a citation graph from seed papers via breadth-first traversal. Starting from one or more papers, it iteratively fetches their references (backward) and/or citing papers (forward) to map the citation network around them.

## Basic Usage

```python
import findpapers

engine = findpapers.Engine()

# Start from a paper found by DOI
seed = engine.fetch_paper_by_doi("10.1038/nature12373")

graph = engine.snowball(seed, max_depth=1, direction="both")

print(f"{len(graph.papers)} papers, {len(graph.edges)} edges")
```

## Parameters

```python
graph = engine.snowball(
    papers,                         # list[Paper] | Paper - seed papers
    max_depth=1,                    # int - maximum traversal depth
    direction="both",               # "both" | "backward" | "forward"
    num_workers=1,                  # int - number of parallel workers
    verbose=False,                  # bool - enable detailed logging
    show_progress=True,             # bool - show progress bars
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `papers` | `list[Paper] \| Paper` | *(required)* | One or more seed papers from which the snowball starts |
| `max_depth` | `int` | `1` | Maximum number of snowball iterations |
| `direction` | `"both" \| "backward" \| "forward"` | `"both"` | Direction of citation traversal |
| `num_workers` | `int` | `1` | Number of parallel workers used to query connectors |
| `verbose` | `bool` | `False` | Enable detailed DEBUG-level log messages |
| `show_progress` | `bool` | `True` | Display tqdm progress bars while papers are being expanded |

## Return Value

Returns a `CitationGraph` object containing:

| Attribute | Type | Description |
|-----------|------|-------------|
| `seed_papers` | `list[Paper]` | Starting papers |
| `max_depth` | `int` | Maximum traversal depth used |
| `direction` | `str` | Direction used (`"both"`, `"backward"`, or `"forward"`) |
| `papers` | `list[Paper]` | All papers in the graph (property) |
| `edges` | `list[CitationEdge]` | Directed edges where each edge means "source cites target" (property) |

Each `CitationEdge` has a `source` (the citing paper) and a `target` (the cited paper).

## Direction

The `direction` parameter controls which citation relationships are followed:

- **`"backward"`** - fetches references (papers cited *by* the seed). Answers: "What did this paper build on?"
- **`"forward"`** - fetches citing papers (papers that cite the seed). Answers: "What was built on top of this paper?"
- **`"both"`** - follows both directions. Gives the most complete picture of the citation neighborhood.

```python
# Only find what the seed papers cite
graph = engine.snowball(papers, direction="backward")

# Only find papers that cite the seeds
graph = engine.snowball(papers, direction="forward")

# Both directions (default)
graph = engine.snowball(papers, direction="both")
```

## Depth

The `max_depth` parameter controls how many iterations the snowball runs:

- **`max_depth=1`** (default) - retrieves only the immediate neighbours of the seed papers
- **`max_depth=2`** - also expands papers found at level 1
- Higher values expand further, but the number of papers grows rapidly

```python
# Immediate neighbours only
graph = engine.snowball(papers, max_depth=1)

# Two levels deep
graph = engine.snowball(papers, max_depth=2)
```

> **Note:** Higher depths can result in very large graphs. Start with `max_depth=1` and increase gradually.

## Data Sources

Snowballing uses citation-capable connectors to fetch references and citing papers:

- **OpenAlex** - large open catalog with citation data
- **Semantic Scholar** - AI-powered academic graph with citation data
- **CrossRef** - backward citations (references) via DOI lookup

Papers without a DOI are silently skipped since they cannot be resolved by the upstream APIs.

## Snowballing from Search Results

A common workflow is to search for papers and then snowball from the most relevant ones:

```python
import findpapers

engine = findpapers.Engine()

# Search for key papers
result = engine.search("[attention mechanism] AND [transformer]")

# Snowball from the top 5 results
graph = engine.snowball(result.papers[:5], max_depth=1, direction="both")

print(f"Found {len(graph.papers)} papers in the citation network")

# Save the graph
findpapers.save_to_json(graph, "citation_graph.json")
```

## Snowballing from a Single Paper

You can pass a single `Paper` object directly:

```python
seed = engine.fetch_paper_by_doi("10.1038/nature12373")
graph = engine.snowball(seed)
```

## Saving the Graph

```python
import findpapers

# Save as JSON (preserves the full graph structure)
findpapers.save_to_json(graph, "citation_graph.json")

# Reload later
graph = findpapers.load_from_json("citation_graph.json")
```
