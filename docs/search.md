# Search

The `engine.search()` method queries multiple academic databases with a single boolean query, automatically deduplicating and merging results. It is the primary entry point for discovering papers.

## Basic Usage

```python
import findpapers
import datetime

engine = findpapers.Engine()

result = engine.search(
    "[deep learning] AND [medical imaging]",
    since=datetime.date(2023, 1, 1),
    until=datetime.date(2024, 12, 31),
)

print(f"Found {len(result.papers)} papers")
for paper in result.papers[:5]:
    print(paper)
```

## Parameters

```python
result = engine.search(
    query,                          # str - boolean query string
    databases=None,                 # list[str] | None - restrict to specific databases
    max_papers_per_database=None,   # int | None - limit results per database
    since=None,                     # datetime.date | None - start date filter
    until=None,                     # datetime.date | None - end date filter
    num_workers=1,                  # int - number of parallel workers
    verbose=False,                  # bool - enable detailed logging
    show_progress=True,             # bool - show progress bars
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | `str` | *(required)* | Boolean query string following the [Query Syntax](https://github.com/jonatasgrosman/findpapers/blob/main/docs/query-syntax.md) |
| `databases` | `list[str] \| None` | `None` | Database identifiers to query. `None` selects all databases whose required API keys are available |
| `max_papers_per_database` | `int \| None` | `None` | Cap on the number of papers retrieved from each database. `None` means no limit |
| `since` | `datetime.date \| None` | `None` | Only return papers published on or after this date |
| `until` | `datetime.date \| None` | `None` | Only return papers published on or before this date |
| `num_workers` | `int` | `1` | Number of parallel workers used to query databases concurrently |
| `verbose` | `bool` | `False` | Enable detailed DEBUG-level log messages |
| `show_progress` | `bool` | `True` | Display tqdm progress bars while papers are being fetched |

## Return Value

Returns a `SearchResult` object containing:

| Attribute | Type | Description |
|-----------|------|-------------|
| `query` | `str` | The search query used |
| `papers` | `list[Paper]` | Deduplicated results |
| `databases` | `list[str] \| None` | Databases that were queried |
| `failed_databases` | `list[str] \| None` | Databases that failed during search |
| `since` | `datetime.date \| None` | Start date filter applied |
| `until` | `datetime.date \| None` | End date filter applied |
| `max_papers_per_database` | `int \| None` | Per-database paper limit applied |
| `runtime_seconds` | `float \| None` | Total runtime |
| `runtime_seconds_per_database` | `dict[str, float] \| None` | Per-database runtime |

## Exceptions

| Exception | When |
|-----------|------|
| `QueryValidationError` | The query has syntax errors (unbalanced brackets, invalid filter codes, etc.) |
| `ValueError` | An unknown database name is passed in `databases` |

## Selecting Databases

When `databases=None` (default), Findpapers queries every database that does not require a missing API key. You can restrict to specific databases:

```python
# Only search arXiv and OpenAlex
result = engine.search("[transformers]", databases=["arxiv", "openalex"])

# Search all databases (requires IEEE and Scopus API keys)
engine = findpapers.Engine(
    ieee_api_key="your-key",
    scopus_api_key="your-key",
)
result = engine.search("[transformers]")
```

Available database identifiers: `"arxiv"`, `"ieee"`, `"openalex"`, `"pubmed"`, `"scopus"`, `"semantic_scholar"`. See [Databases](https://github.com/jonatasgrosman/findpapers/blob/main/docs/databases.md) for details on each.

## Limiting Results

Use `max_papers_per_database` to cap the number of papers retrieved from each database. This is useful for exploratory searches or when you want a manageable set:

```python
# Get at most 50 papers from each database
result = engine.search("[machine learning]", max_papers_per_database=50)
```

## Date Filtering

Restrict results to a publication date range with `since` and `until`:

```python
import datetime

result = engine.search(
    "[covid-19] AND [vaccine]",
    since=datetime.date(2020, 1, 1),
    until=datetime.date(2023, 12, 31),
)
```

Both parameters are optional - you can use either one alone or combine them.

## Parallel Execution

Speed up searches by querying databases in parallel:

```python
result = engine.search("[deep learning]", num_workers=4)
```

When `num_workers=1` (default), databases are queried sequentially. The optimal number depends on your network and the configured API rate limits.

## Deduplication

Findpapers automatically deduplicates papers found across multiple databases. Two papers are considered the same when they share:

- The same DOI (case-insensitive), or
- The same normalized title

When duplicates are found, their metadata is merged - keeping the richest information from each source.

## Working with Results

```python
result = engine.search("[machine learning] AND [healthcare]")

# Iterate over papers
for paper in result.papers:
    print(f"{paper.title} ({paper.publication_date})")
    print(f"  DOI: {paper.doi}")
    print(f"  Databases: {paper.databases}")

# Save results for later
import findpapers
findpapers.save_to_json(result, "results.json")
findpapers.save_to_bibtex(result.papers, "references.bib")

# Reload a previous search
result = findpapers.load_from_json("results.json")
```
