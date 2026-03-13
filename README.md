<p align="center">
  <img src="https://raw.githubusercontent.com/jonatasgrosman/findpapers/main/logo.png" alt="Findpapers Logo" width="400">
</p>

<p align="center">
  <a href="https://github.com/jonatasgrosman/findpapers/blob/master/LICENSE"><img src="https://img.shields.io/pypi/l/findpapers" alt="PyPI - License"></a>
  <a href="https://pypi.org/project/findpapers"><img src="https://img.shields.io/pypi/v/findpapers" alt="PyPI"></a>
</p>

Findpapers is a Python library that gives researchers unified access to **hundreds of millions of academic papers** from different databases - all through a single query. Instead of searching the databases one by one, each with its own interface and query language, Findpapers lets you write one boolean expression and run it everywhere at once, automatically merging and deduplicating the results.

Findpapers searches for papers through **arXiv**, **IEEE Xplore**, **OpenAlex**, **PubMed**, **Scopus**, and **Semantic Scholar** - together covering virtually every peer-reviewed paper, preprint, and conference proceeding published across all fields of science. It also supports paper enrichment, PDF downloading, citation graph building (snowballing), and export to multiple formats.

## Key Features

- **Massive coverage** - access hundreds of millions of papers across six databases that together span every scientific discipline
- **Multi-database search** - query all databases in parallel with one boolean search expression - no need to learn six different query syntaxes
- **Smart deduplication** - automatically merges duplicate papers found across different databases
- **Paper enrichment** - fetch additional metadata (abstracts, keywords, citations) via CrossRef and web scraping
- **PDF downloading** - download PDFs with automatic URL resolution for major publishers
- **Citation snowballing** - build citation graphs by traversing references and citations (forward and backward)
- **Flexible export** - save results as JSON, BibTeX, or CSV
- **Filter codes** - restrict search terms to specific fields (title, abstract, keywords, author, source, affiliation)
- **Parallel execution** - speed up searches and downloads using multiple worker threads

## Requirements

- Python 3.11+

## Installation

```bash
pip install git+https://github.com/jonatasgrosman/findpapers.git
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

# Enrich papers with additional metadata (abstracts, keywords, citations)
engine.enrich(result.papers)

# Download PDFs
engine.download(result.papers, "./pdfs")

# Build a citation graph from the top results
graph = engine.snowball(result.papers[:5], max_depth=1, direction="both")

# Save results
findpapers.save_to_json(result, "results.json")
findpapers.save_to_bibtex(result.papers, "references.bib")
findpapers.save_to_json(graph, "citation_graph.json")
```

## Supported Databases

The table below summarizes each supported database - for full details on authentication, rate limits, and per-database quirks, see the [Databases](https://github.com/jonatasgrosman/findpapers/blob/main/docs/databases.md) documentation.

| Database | Size (papers) | API Key | Coverage |
|----------|------------|---------|----------|
| [arXiv](https://arxiv.org) | 3M+ [¹](https://arxiv.org/stats/monthly_submissions) | Not required | Open-access preprints in physics, math, CS, biology, economics, and more |
| [IEEE Xplore](https://ieeexplore.ieee.org) | 7M+ [²](https://innovate.ieee.org/about-the-ieee-xplore-digital-library) | Required | Journals, conferences, and standards in electrical engineering and CS |
| [OpenAlex](https://openalex.org) | 243M+ [³](https://openalex.org/about) | Optional | The largest open catalog of scholarly works across all disciplines |
| [PubMed](https://pubmed.ncbi.nlm.nih.gov) | 40M+ [⁴](https://pubmed.ncbi.nlm.nih.gov/about/) | Optional | Biomedical and life sciences literature (MEDLINE, PMC, and more) |
| [Scopus](https://www.scopus.com) | 100M+ [⁵](https://www.elsevier.com/products/scopus) | Required | Peer-reviewed literature in science, technology, medicine, social sciences, and humanities |
| [Semantic Scholar](https://www.semanticscholar.org) | 214M+ [⁶](https://www.semanticscholar.org/product/api) | Optional | AI-powered academic graph covering all fields of science |

*Estimated paper counts were consulted in March 2026 from each database's official website. Click the superscript links for the original sources. These numbers grow continuously.*

> **Every API key from the databases listed above can be obtained at no cost** - just create an account on each provider’s website. We strongly recommend getting all of them before using Findpapers, as they unlock additional databases (IEEE, Scopus) and dramatically improve rate limits and reliability on the others (OpenAlex, PubMed, Semantic Scholar). See [Databases](https://github.com/jonatasgrosman/findpapers/blob/main/docs/databases.md) for more details on how to get these API keys, and [Configuration](https://github.com/jonatasgrosman/findpapers/blob/main/docs/configuration.md) for how to set them up.

## Documentation

| Document | Description |
|----------|-------------|
| [Getting Started](https://github.com/jonatasgrosman/findpapers/blob/main/docs/getting-started.md) | Installation, configuration, and first search |
| [Databases](https://github.com/jonatasgrosman/findpapers/blob/main/docs/databases.md) | Supported databases, authentication, and per-database details |
| [Query Syntax](https://github.com/jonatasgrosman/findpapers/blob/main/docs/query-syntax.md) | How to write search queries, boolean operators, wildcards, and filter codes |
| [Configuration](https://github.com/jonatasgrosman/findpapers/blob/main/docs/configuration.md) | Environment variables, proxy, SSL, and API keys |
| [Search](https://github.com/jonatasgrosman/findpapers/blob/main/docs/search.md) | Multi-database search with boolean queries |
| [Enrich](https://github.com/jonatasgrosman/findpapers/blob/main/docs/enrich.md) | Enrich papers with additional metadata from CrossRef and web scraping |
| [Download](https://github.com/jonatasgrosman/findpapers/blob/main/docs/download.md) | Download PDFs for papers |
| [Snowball](https://github.com/jonatasgrosman/findpapers/blob/main/docs/snowball.md) | Build citation graphs via forward and backward snowballing |
| [Fetch by DOI](https://github.com/jonatasgrosman/findpapers/blob/main/docs/fetch-by-doi.md) | Look up a single paper by DOI |
| [Save/Load](https://github.com/jonatasgrosman/findpapers/blob/main/docs/save-load.md) | JSON, BibTeX, and CSV persistence details |
| [API Reference](https://github.com/jonatasgrosman/findpapers/blob/main/docs/api-reference.md) | Public classes, functions, enums, and exceptions |

## Want to help?

See the [contribution guidelines](https://github.com/jonatasgrosman/findpapers/blob/main/CONTRIBUTING.md) if you'd like to contribute to the project.
Please follow our [Code of Conduct](https://github.com/jonatasgrosman/findpapers/blob/main/CODE_OF_CONDUCT.md). You don't need to know how to code to contribute, even improving documentation is a valuable contribution.

If this project has been useful for you, please share it with your friends and give us a star on GitHub to help others discover it. You can also [sponsor me](https://github.com/sponsors/jonatasgrosman) to support the development of Findpapers.

![Support the project by starring and sponsoring](https://raw.githubusercontent.com/jonatasgrosman/findpapers/main/support.gif)

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
