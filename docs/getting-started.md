# Getting Started

This guide walks you through installing Findpapers, configuring API keys, and running your first search.

## Requirements

- Python 3.11+

## Installation

```bash
pip install git+https://github.com/jonatasgrosman/findpapers.git
```

For development, clone the repository and run:

```bash
make setup
```

This creates a virtual environment in `.venv` and installs all dependencies via Poetry.

## API Keys

Some databases require API keys. Findpapers works without any keys (using arXiv, OpenAlex, PubMed, and Semantic Scholar), but to unlock IEEE and Scopus you need to configure credentials.

Set them as environment variables or pass them directly to the `Engine` constructor:

```bash
export FINDPAPERS_IEEE_API_TOKEN="your-ieee-key"
export FINDPAPERS_SCOPUS_API_TOKEN="your-scopus-key"
```

See [Configuration](https://github.com/jonatasgrosman/findpapers/blob/main/docs/configuration.md) for the full list of environment variables.

## Your First Search

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

The `search` method queries all available databases (those for which you have valid credentials), deduplicates results, and returns a `SearchResult` object.

## Downloading PDFs

```python
metrics = engine.download(result.papers, "./pdfs")
print(f"Downloaded {metrics['downloaded_papers']} of {metrics['total_papers']} papers")
```

PDFs are saved as `YEAR-title.pdf`. A `download_log.txt` file is created in the output directory with the status of each download.

## Enriching Papers

Enrich papers with additional metadata from CrossRef and web scraping:

```python
metrics = engine.enrich(result.papers)
print(f"Enriched {metrics['enriched_papers']} papers")
```

Enrichment can fill in missing abstracts, keywords, citation counts, PDF URLs, and source details. Papers are modified in place.

## Saving Results

```python
# JSON (preserves all metadata, can be reloaded later)
findpapers.save_to_json(result, "results.json")

# BibTeX (for LaTeX references)
findpapers.save_to_bibtex(result.papers, "references.bib")

# CSV (for spreadsheets)
findpapers.save_to_csv(result.papers, "papers.csv")
```

See [Save/Load](https://github.com/jonatasgrosman/findpapers/blob/main/docs/save-load.md) for details on each format.

## Reloading Results

```python
# Reload a previously saved search
result = findpapers.load_from_json("results.json")

# Reload papers from BibTeX or CSV
papers = findpapers.load_from_bibtex("references.bib")
papers = findpapers.load_from_csv("papers.csv")
```

## Citation Snowballing

Build a citation graph starting from seed papers:

```python
graph = engine.snowball(
    result.papers[:10],
    max_depth=1,
    direction="both",
)

print(f"Graph has {len(graph.papers)} papers and {len(graph.edges)} citation edges")

# Save the citation graph
findpapers.save_to_json(graph, "citation_graph.json")
```

Snowballing uses OpenAlex, Semantic Scholar, and CrossRef to traverse citations. Papers must have a DOI to be included.

## Lookup by DOI

Fetch a single paper by its DOI:

```python
paper = engine.get("10.1038/s41586-021-03819-2")
if paper:
    print(paper)
```
