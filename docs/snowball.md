# Snowball

The `engine.snowball()` method builds a citation graph from seed papers via breadth-first traversal. Starting from one or more papers, it iteratively fetches their references (backward) and/or citing papers (forward) to map the citation network around them.

## Basic Usage

```python
import findpapers

engine = findpapers.Engine()

# Start from a paper found by DOI
seed = engine.get("10.1038/nature12373")

graph = engine.snowball(seed, max_depth=1, direction="both")

print(f"{len(graph.nodes)} nodes, {len(graph.edges)} edges")
```

## Parameters

```python
graph = engine.snowball(
    papers,                         # list[Paper] | Paper - seed papers
    max_depth=1,                    # int - maximum traversal depth
    direction="both",               # "both" | "backward" | "forward"
    top_n_per_level=None,           # int | None - keep only top N papers per level
    since=None,                     # datetime.date | None - exclude papers before this date
    until=None,                     # datetime.date | None - exclude papers after this date
    paper_types=None,               # list[str] | None - restrict to specific paper types
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
| `top_n_per_level` | `int \| None` | `None` | Keep only the N most-cited papers per level in the graph; the rest are discarded. Seed papers are always expanded. `None` means no limit |
| `since` | `datetime.date \| None` | `None` | Only add discovered papers published on or after this date. Seed papers are never filtered |
| `until` | `datetime.date \| None` | `None` | Only add discovered papers published on or before this date. Seed papers are never filtered |
| `paper_types` | `list[str] \| None` | `None` | Only add discovered papers whose type is in this list. Accepted values: `"article"`, `"inproceedings"`, `"inbook"`, `"incollection"`, `"book"`, `"phdthesis"`, `"mastersthesis"`, `"techreport"`, `"unpublished"`, `"misc"`. Seed papers are never filtered. `None` disables the filter |
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
| `nodes` | `list[Paper]` | All paper nodes in the graph (property) |
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

## Controlling Cost with `top_n_per_level`

At each snowball level the number of discovered papers can grow explosively, making deep snowballs (e.g. `max_depth=3`) very expensive in terms of API calls. The `top_n_per_level` parameter addresses this by only adding the **N most-cited** papers found at each level to the graph. Papers that do not make the cut are discarded entirely — they are not added to the graph and are never expanded.

Seed papers passed to `engine.snowball()` are always fully expanded regardless of this limit.

```python
# Deep snowball but limit to the 10 most-cited papers at each level
graph = engine.snowball(
    seed_papers,
    max_depth=3,
    direction="forward",
    top_n_per_level=10,
)
```

When `top_n_per_level` is `None` (the default) all discovered papers are added to the graph and expanded.

> **Tip:** Papers with an unknown citation count (`citations=None`) are ranked below papers with a known count, so well-indexed papers are always preferred.

## Date and Type Filtering

Use `since`, `until`, and `paper_types` to narrow which *discovered* papers are added to the graph. Seed papers are **never** filtered.

### Date range

```python
import datetime

# Only papers published between 2018 and 2023
graph = engine.snowball(
    seed,
    max_depth=2,
    since=datetime.date(2018, 1, 1),
    until=datetime.date(2023, 12, 31),
)
```

Papers with an unknown publication date are excluded when either `since` or `until` is active.

### Paper type

```python
# Only journal articles and conference papers
graph = engine.snowball(
    seed,
    max_depth=2,
    paper_types=["article", "inproceedings"],
)
```

Accepted values: `"article"`, `"inproceedings"`, `"inbook"`, `"incollection"`, `"book"`, `"phdthesis"`, `"mastersthesis"`, `"techreport"`, `"unpublished"`, `"misc"`.

Papers with an unknown type (`paper_type=None`) are excluded when this filter is active. An `InvalidParameterError` is raised if an unrecognised type string is provided.

### Combining filters

```python
import datetime

# Focused snowball: recent journal articles only
graph = engine.snowball(
    seed,
    max_depth=2,
    direction="backward",
    since=datetime.date(2020, 1, 1),
    paper_types=["article"],
)
```

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

print(f"Found {len(graph.nodes)} papers in the citation network")

# Save the graph
findpapers.save_to_json(graph, "citation_graph.json")
```

## Snowballing from a Single Paper

You can pass a single `Paper` object directly:

```python
seed = engine.get("10.1038/nature12373")
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
