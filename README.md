# Findpapers

[![PyPI - License](https://img.shields.io/pypi/l/findpapers)](https://github.com/jonatasgrosman/findpapers/blob/master/LICENSE)
[![PyPI](https://img.shields.io/pypi/v/findpapers)](https://pypi.org/project/findpapers)

Findpapers is a Python library that helps researchers search for academic papers across multiple databases from a single query. It provides a unified interface for **arXiv**, **IEEE Xplore**, **OpenAlex**, **PubMed**, **Scopus**, and **Semantic Scholar**, with built-in support for paper enrichment, PDF downloading, citation graph building (snowballing), and export to multiple formats.

## Key Features

- **Multi-database search** - query six academic databases in parallel with a single boolean search expression
- **Smart deduplication** - automatically merges duplicate papers found across different databases
- **Paper enrichment** - fetch additional metadata (abstracts, keywords, citations) via CrossRef and web scraping
- **PDF downloading** - download PDFs with automatic URL resolution for major publishers (ACM, IEEE, Elsevier, Springer, and more)
- **Citation snowballing** - build citation graphs by traversing references and citations (forward and backward)
- **Flexible export** - save results as JSON, BibTeX, or CSV; reload them later for further processing
- **Filter codes** - restrict search terms to specific fields (title, abstract, keywords, author, source, affiliation)
- **Parallel execution** - speed up searches and downloads using multiple worker threads

## Requirements

- Python 3.11+

## Installation

```bash
pip install findpapers
```

## Quick Start

```python
import findpapers
import datetime

engine = findpapers.Engine()

# Search for papers across all databases
result = engine.search(
    "[machine learning] AND [healthcare]",
    since=datetime.date(2022, 1, 1),
)

# Download PDFs
engine.download(result.papers, "./pdfs")

# Export results
findpapers.export_to_json(result, "results.json")
findpapers.export_papers_to_bibtex(result.papers, "references.bib")
```

## Documentation

| Document | Description |
|----------|-------------|
| [Getting Started](docs/getting-started.md) | Installation, configuration, and first search |
| [Query Syntax](docs/query-syntax.md) | How to write search queries, boolean operators, wildcards, and filter codes |
| [Search Databases](docs/search-databases.md) | Supported databases, authentication, and per-database details |
| [API Reference](docs/api-reference.md) | Complete reference for the `Engine` class and data models |
| [Export Formats](docs/export-formats.md) | JSON, BibTeX, and CSV export/import details |
| [Configuration](docs/configuration.md) | Environment variables, proxy, SSL, and API keys |

## Want to help?

See the [contribution guidelines](CONTRIBUTING.md) if you'd like to contribute to the project.
Please follow the [Code of Conduct](CODE_OF_CONDUCT.md). You don't need to know how to code to contribute, even improving documentation is a valuable contribution.

If this project has been useful for you, please share it with your friends and give us a star on GitHub to help others discover it. You can also [sponsor me](https://github.com/sponsors/jonatasgrosman) to support the development of Findpapers.

![Support the project by starring and sponsoring](support.gif)

## Citation

If you use Findpapers in your research, please cite it:

```bibtex
@misc{grosman2020findpapers,
  title={{Findpapers: A tool for helping researchers who are looking for related works}},
  author={Grosman, Jonatas},
  howpublished={\url{https://github.com/jonatasgrosman/findpapers}},
  year={2020}
}
```
