# API Reference

This page documents the main public classes and methods exported by Findpapers.

## Engine

The central facade for all Findpapers operations. Manages configuration (API keys, proxy, SSL) and provides high-level methods for the complete workflow.

```python
import findpapers

engine = findpapers.Engine(
    ieee_api_key=None,              # Falls back to FINDPAPERS_IEEE_API_TOKEN
    scopus_api_key=None,            # Falls back to FINDPAPERS_SCOPUS_API_TOKEN
    pubmed_api_key=None,            # Falls back to FINDPAPERS_PUBMED_API_TOKEN
    openalex_api_key=None,          # Falls back to FINDPAPERS_OPENALEX_API_TOKEN
    email=None,                     # Falls back to FINDPAPERS_EMAIL
    semantic_scholar_api_key=None,  # Falls back to FINDPAPERS_SEMANTIC_SCHOLAR_API_TOKEN
    proxy=None,                     # Falls back to FINDPAPERS_PROXY
    ssl_verify=True,                # Falls back to FINDPAPERS_SSL_VERIFY
)
```

### engine.search()

Search multiple databases with a boolean query.

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

**Returns:** `SearchResult`

**Raises:** `QueryValidationError` if the query is invalid, `ValueError` if parameters are invalid.

### engine.download()

Download PDFs for a list of papers.

```python
metrics = engine.download(
    papers,                         # list[Paper] - papers to download
    output_directory,               # str - directory to save PDFs
    num_workers=1,                  # int - number of parallel workers
    timeout=10.0,                   # float | None - per-download timeout in seconds
    verbose=False,                  # bool - enable detailed logging
    show_progress=True,             # bool - show progress bars
)
```

**Returns:** `dict` with keys `total_papers`, `downloaded_papers`, `runtime_in_seconds`.

### engine.enrich()

Enrich papers with additional metadata from CrossRef and web scraping. Papers are modified in place.

```python
metrics = engine.enrich(
    papers,                         # list[Paper] - papers to enrich
    num_workers=1,                  # int - number of parallel workers
    timeout=10.0,                   # float | None - per-request timeout in seconds
    verbose=False,                  # bool - enable detailed logging
    show_progress=True,             # bool - show progress bars
)
```

**Returns:** `dict` with keys `enriched_papers`, `doi_enriched_papers`, `fetch_error_papers`, `no_metadata_papers`, `no_change_papers`, `no_urls_papers`, `runtime_in_seconds`.

### engine.fetch_paper_by_doi()

Fetch a single paper from CrossRef by DOI.

```python
paper = engine.fetch_paper_by_doi(
    doi,                            # str - the DOI to look up
    timeout=10.0,                   # float | None - request timeout
    verbose=False,                  # bool - enable detailed logging
)
```

**Returns:** `Paper | None`

**Raises:** `ValueError` if DOI is empty.

### engine.snowball()

Build a citation graph from seed papers via breadth-first traversal.

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

**Returns:** `CitationGraph`

### Export/Import Functions

Export and import functions are available as top-level functions in the `findpapers` package:

```python
import findpapers

# Export
findpapers.export_to_json(data, path)              # data: SearchResult | CitationGraph | list[Paper]
findpapers.export_papers_to_bibtex(papers, path)   # papers: list[Paper]
findpapers.export_papers_to_csv(papers, path)      # papers: list[Paper]

# Import
data = findpapers.load_from_json(path)             # Returns SearchResult | CitationGraph | list[Paper]
papers = findpapers.load_papers_from_bibtex(path)  # Returns list[Paper]
papers = findpapers.load_papers_from_csv(path)     # Returns list[Paper]
```

---

## Data Models

### Paper

Represents an academic publication.

| Attribute | Type | Description |
|-----------|------|-------------|
| `title` | `str` | Paper title (required) |
| `abstract` | `str` | Paper abstract |
| `authors` | `list[Author]` | List of authors |
| `source` | `Source \| None` | Publication source (journal, conference, etc.) |
| `publication_date` | `datetime.date \| None` | Publication date |
| `url` | `str \| None` | Paper URL |
| `pdf_url` | `str \| None` | Direct PDF URL |
| `doi` | `str \| None` | Digital Object Identifier |
| `citations` | `int \| None` | Citation count |
| `keywords` | `set[str] \| None` | Keywords |
| `comments` | `str \| None` | Free-text comments |
| `page_count` | `int \| None` | Number of pages |
| `page_range` | `str \| None` | Page range (e.g., "223-230") |
| `databases` | `set[str] \| None` | Databases where the paper was found |
| `paper_type` | `PaperType \| None` | BibTeX publication type |
| `fields_of_study` | `set[str] \| None` | Fields of study (e.g., "Computer Science") |
| `subjects` | `set[str] \| None` | Subject classifications |

**Key methods:**

- `paper.merge(other)` - merge metadata from another `Paper` into this one
- `paper.to_dict()` - serialize to dictionary
- `Paper.from_dict(data)` - deserialize from dictionary
- `str(paper)` - returns `"Author et al. (Year). Title."`

Two papers are considered equal if they share the same DOI (case-insensitive) or the same normalized title.

### Author

Represents a paper author.

| Attribute | Type | Description |
|-----------|------|-------------|
| `name` | `str` | Author name (required) |
| `affiliation` | `str \| None` | Institutional affiliation |

### Source

Represents a publication venue.

| Attribute | Type | Description |
|-----------|------|-------------|
| `title` | `str` | Source title (required) |
| `isbn` | `str \| None` | International Standard Book Number |
| `issn` | `str \| None` | International Standard Serial Number |
| `publisher` | `str \| None` | Publisher name |
| `source_type` | `SourceType \| None` | Type of source |

### SearchResult

Container for search configuration and results.

| Attribute | Type | Description |
|-----------|------|-------------|
| `query` | `str` | The search query used |
| `since` | `datetime.date \| None` | Start date filter |
| `until` | `datetime.date \| None` | End date filter |
| `max_papers_per_database` | `int \| None` | Per-database paper limit |
| `processed_at` | `datetime.datetime \| None` | When the search was executed |
| `databases` | `list[str] \| None` | Databases that were queried |
| `papers` | `list[Paper]` | Deduplicated results |
| `runtime_seconds` | `float \| None` | Total runtime |
| `runtime_seconds_per_database` | `dict[str, float] \| None` | Per-database runtime |
| `failed_databases` | `list[str] \| None` | Databases that failed during search |

**Key methods:**

- `result.add_paper(paper)` - add a paper to the result
- `result.remove_paper(paper)` - remove a paper
- `result.to_dict()` / `SearchResult.from_dict(data)` - serialization

### CitationGraph

Directed citation graph built from snowballing.

| Attribute | Type | Description |
|-----------|------|-------------|
| `seed_papers` | `list[Paper]` | Starting papers |
| `max_depth` | `int` | Maximum traversal depth |
| `direction` | `str` | `"both"`, `"backward"`, or `"forward"` |
| `papers` | `list[Paper]` | All papers in the graph (property) |
| `edges` | `list[CitationEdge]` | Directed edges (property) |

### CitationEdge

A directed edge in the citation graph.

| Attribute | Type | Description |
|-----------|------|-------------|
| `source` | `Paper` | The citing paper |
| `target` | `Paper` | The cited paper |

---

## Enums

### PaperType

BibTeX-compatible publication types.

| Value | Description |
|-------|-------------|
| `ARTICLE` | Journal article |
| `INPROCEEDINGS` | Conference paper |
| `INBOOK` | Book chapter |
| `INCOLLECTION` | Part of a collection |
| `BOOK` | Complete book |
| `PHDTHESIS` | PhD thesis |
| `MASTERSTHESIS` | Master's thesis |
| `TECHREPORT` | Technical report |
| `UNPUBLISHED` | Unpublished work |
| `MISC` | Miscellaneous |

### SourceType

Types of publication venues.

| Value | Description |
|-------|-------------|
| `JOURNAL` | Academic journal |
| `CONFERENCE` | Conference proceedings |
| `BOOK` | Book |
| `REPOSITORY` | Preprint repository |
| `OTHER` | Other |

### FilterCode

Query filter codes for restricting search fields.

| Value | Code | Field |
|-------|------|-------|
| `TITLE` | `ti` | Title |
| `ABSTRACT` | `abs` | Abstract |
| `KEYWORDS` | `key` | Keywords |
| `AUTHOR` | `au` | Author |
| `SOURCE` | `src` | Source |
| `AFFILIATION` | `aff` | Affiliation |
| `TITLE_ABSTRACT` | `tiabs` | Title + Abstract (default) |
| `TITLE_ABSTRACT_KEYWORDS` | `tiabskey` | Title + Abstract + Keywords |

### ConnectorType

Boolean connector types.

| Value | Syntax |
|-------|--------|
| `AND` | `AND` |
| `OR` | `OR` |
| `AND_NOT` | `AND NOT` |

### Database

Supported database identifiers (StrEnum - compares equal to its string value).

| Value | String |
|-------|--------|
| `ARXIV` | `"arxiv"` |
| `IEEE` | `"ieee"` |
| `OPENALEX` | `"openalex"` |
| `PUBMED` | `"pubmed"` |
| `SCOPUS` | `"scopus"` |
| `SEMANTIC_SCHOLAR` | `"semantic_scholar"` |

---

## Exceptions

All Findpapers exceptions inherit from `FindpapersError`.

| Exception | Parent | Description |
|-----------|--------|-------------|
| `FindpapersError` | `Exception` | Base exception for all library errors |
| `QueryValidationError` | `FindpapersError`, `ValueError` | Invalid query syntax |
| `UnsupportedQueryError` | `FindpapersError`, `ValueError` | Database doesn't support the query |
| `ConnectorError` | `FindpapersError` | Unrecoverable API error |
| `ExportError` | `FindpapersError` | Export format or data error |

---

## Runners (Advanced)

For more control over individual operations, you can use the runner classes directly instead of the `Engine` facade.

| Runner | Purpose |
|--------|---------|
| `SearchRunner` | Execute multi-database searches |
| `DownloadRunner` | Download PDFs |
| `EnrichmentRunner` | Enrich papers with metadata |
| `DOILookupRunner` | Fetch a paper by DOI |
| `SnowballRunner` | Build citation graphs |

Each runner accepts configuration in its constructor and exposes a `run()` method. See the source code for full constructor signatures.

```python
from findpapers import SearchRunner

runner = SearchRunner(
    query="[machine learning]",
    databases=["arxiv", "openalex"],
    max_papers_per_database=100,
)
result = runner.run(verbose=True)
```
