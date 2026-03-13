# Enrich

The `engine.enrich()` method fetches additional metadata for papers from CrossRef and web scraping. It can fill in missing abstracts, keywords, citation counts, PDF URLs, and source details. Papers are modified **in place**.

## Basic Usage

```python
import findpapers

engine = findpapers.Engine()

result = engine.search("[deep learning] AND [medical imaging]")

# Enrich papers with additional metadata
metrics = engine.enrich(result.papers)

print(f"Enriched {metrics['enriched_papers']} of {metrics['total_papers']} papers")
```

## Parameters

```python
metrics = engine.enrich(
    papers,                         # list[Paper] - papers to enrich
    num_workers=1,                  # int - number of parallel workers
    timeout=10.0,                   # float | None - per-request timeout in seconds
    verbose=False,                  # bool - enable detailed logging
    show_progress=True,             # bool - show progress bars
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `papers` | `list[Paper]` | *(required)* | Papers to enrich - typically obtained from `engine.search(...).papers` |
| `num_workers` | `int` | `1` | Number of parallel workers for concurrent enrichment |
| `timeout` | `float \| None` | `10.0` | Per-request HTTP timeout in seconds. `None` disables the timeout |
| `verbose` | `bool` | `False` | Enable detailed DEBUG-level log messages |
| `show_progress` | `bool` | `True` | Display a tqdm progress bar while papers are being enriched |

## Return Value

Returns a `dict` with the following keys:

| Key | Type | Description |
|-----|------|-------------|
| `total_papers` | `int` | Number of papers processed |
| `enriched_papers` | `int` | Number of papers that gained new metadata |
| `unchanged_papers` | `int` | Papers already up-to-date (no new data found) |
| `failed_papers` | `int` | Papers where metadata fetch failed |
| `runtime_in_seconds` | `float` | Wall-clock time of the enrichment process |

## How Enrichment Works

For each paper, Findpapers tries two enrichment strategies:

1. **CrossRef lookup** - if the paper has a DOI, the CrossRef API is queried for metadata (title, authors, abstract, source, publication date, etc.)
2. **Web scraping** - the paper's known URLs are fetched and parsed for additional metadata (keywords, abstracts, PDF links, citation counts)

Found data is merged into the existing paper objects. Fields that already have values are not overwritten - enrichment only fills in missing information.

## In-Place Modification

Papers are modified in place. After calling `enrich()`, the same paper objects you passed in will contain the updated metadata:

```python
paper = result.papers[0]
print(paper.abstract)  # might be None before enrichment

engine.enrich(result.papers)

print(paper.abstract)  # now populated (if metadata was found)
```

This means you don't need to reassign the papers - your existing references stay valid.

## Parallel Execution

Speed up enrichment by processing papers in parallel:

```python
metrics = engine.enrich(result.papers, num_workers=4)
```

The optimal number of workers depends on your network and the upstream rate limits.

## Timeout

The `timeout` parameter controls the HTTP timeout for each individual request (CrossRef API call or web page fetch):

```python
# Increase timeout for slow connections
metrics = engine.enrich(result.papers, timeout=30.0)

# Disable timeout (not recommended)
metrics = engine.enrich(result.papers, timeout=None)
```

## Typical Workflow

Enrichment usually comes right after a search, before downloading or exporting:

```python
import findpapers

engine = findpapers.Engine()

# 1. Search
result = engine.search("[machine learning] AND [healthcare]")

# 2. Enrich
engine.enrich(result.papers, num_workers=4)

# 3. Download PDFs (enrichment may have found new PDF URLs)
engine.download(result.papers, "./pdfs")

# 4. Save enriched results
findpapers.save_to_json(result, "enriched_results.json")
```
