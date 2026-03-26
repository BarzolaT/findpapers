# Fetch by DOI

The `engine.get()` method looks up a single paper from CrossRef using its DOI. This is useful when you already know the DOI of a paper and want to retrieve its metadata without running a full search.

## Basic Usage

```python
import findpapers

engine = findpapers.Engine()

paper = engine.get("10.1038/nature12373")

if paper:
    print(paper.title)
    print(paper.authors)
    print(paper.publication_date)
```

## Parameters

```python
paper = engine.get(
    doi,                            # str - the DOI to look up
    timeout=10.0,                   # float | None - request timeout in seconds
    verbose=False,                  # bool - enable detailed logging
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `doi` | `str` | *(required)* | DOI identifier or DOI URL of the paper to look up |
| `timeout` | `float \| None` | `10.0` | HTTP request timeout in seconds. `None` disables the timeout |
| `verbose` | `bool` | `False` | Enable detailed DEBUG-level log messages |

## Return Value

Returns a `Paper` object with CrossRef metadata, or `None` when the DOI is not found or the response cannot be parsed into a valid paper.

## Exceptions

| Exception | When |
|-----------|------|
| `InvalidParameterError` | The DOI is empty or blank after stripping whitespace and URL prefixes |

## DOI Formats

The DOI can be provided as a bare identifier or as a full URL - the URL prefix is stripped automatically:

```python
# Bare DOI
paper = engine.get("10.1038/nature12373")

# Full DOI URL
paper = engine.get("https://doi.org/10.1038/nature12373")
```

## Using as a Snowball Seed

A common use case is to fetch a paper by DOI and then use it as a seed for citation snowballing:

```python
import findpapers

engine = findpapers.Engine()

# Fetch the seed paper
seed = engine.get("10.1038/nature12373")

if seed:
    # Build a citation graph around it
    graph = engine.snowball(seed, max_depth=1, direction="both")
    print(f"{len(graph.papers)} papers in the citation network")

    findpapers.save_to_json(graph, "citation_graph.json")
```

## Fetching Multiple Papers by DOI

To look up multiple DOIs, call `get()` in a loop:

```python
dois = [
    "10.1038/nature12373",
    "10.1145/3292500.3330919",
    "10.1109/CVPR.2016.90",
]

papers = []
for doi in dois:
    paper = engine.get(doi)
    if paper:
        papers.append(paper)

print(f"Fetched {len(papers)} of {len(dois)} papers")
```
