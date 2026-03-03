# API Sample Data Collectors

This directory contains standalone scripts to collect fresh API response samples from each database
and to fetch the landing pages of the collected papers.
These samples are used for testing the searcher, enrichment, and download runner implementations.

## Directory Structure

```
tests/data/
├── collect_all_samples.py    # Master script: runs all collectors + page collector
├── README.md                  # This file
├── arxiv/
│   ├── collect_sample.py     # arXiv API collector
│   ├── sample_response.xml   # Raw XML response (after running)
│   └── collection_metadata.json
├── crossref/
│   ├── collect_sample.py     # CrossRef API collector
│   ├── sample_responses.json # Raw JSON responses (after running)
│   └── collection_metadata.json
├── ieee/
│   ├── collect_sample.py     # IEEE Xplore API collector
│   ├── sample_response.json  # Raw JSON response (after running)
│   └── collection_metadata.json
├── pubmed/
│   ├── collect_sample.py     # PubMed API collector
│   ├── esearch_response.json # Search response with IDs
│   ├── efetch_response.xml   # Full article records
│   └── collection_metadata.json
├── scopus/
│   ├── collect_sample.py     # Scopus API collector
│   ├── sample_response.json  # Raw JSON response (after running)
│   └── collection_metadata.json
├── openalex/
│   ├── collect_sample.py     # OpenAlex API collector
│   ├── sample_response.json  # Raw JSON response (after running)
│   └── collection_metadata.json
├── semanticscholar/
│   ├── collect_sample.py     # Semantic Scholar API collector
│   ├── bulk_search_response.json       # Bulk search response
│   └── collection_metadata.json
└── pages/
    ├── collect_pages.py      # Landing-page collector (uses DOIs from samples above)
    ├── collection_metadata.json
    ├── arxiv/
    │   ├── <doi>.html            # HTML landing page
    │   ├── <doi>.meta.json       # URL, DOI, status metadata
    │   └── index.json            # Per-database summary
    ├── ieee/      (same layout)
    ├── pubmed/    (same layout)
    ├── scopus/    (same layout)
    ├── openalex/  (same layout)
    └── semanticscholar/ (same layout)
```

## Usage

### Run all collectors (API samples + landing pages)

```bash
python tests/data/collect_all_samples.py
```

`collect_all_samples.py` runs every database-specific collector and then automatically
calls `pages/collect_pages.py` to fetch up to 5 landing pages per database.

### Run specific database collectors + their pages

```bash
python tests/data/collect_all_samples.py arxiv pubmed
```

### Run individual API collector

```bash
python tests/data/arxiv/collect_sample.py
```

### Run only the page collector

```bash
# Collect pages for all databases that already have sample data
python tests/data/pages/collect_pages.py

# Collect pages for specific databases
python tests/data/pages/collect_pages.py arxiv ieee pubmed
```

The page collector reads existing `sample_response.*` files, extracts DOIs / URLs,
fetches each landing page with a courteous ~1 s delay, and saves:

| File | Content |
|------|---------|
| `<db>/<doi>.html` | Full HTML of the landing page |
| `<db>/<doi>.meta.json` | `url`, `final_url`, `doi`, `status`, `content_type`, `size_bytes` |
| `<db>/index.json` | List of all metadata objects for that database |
| `collection_metadata.json` | Overall run summary |

## API Keys

Some APIs require authentication:

| Database         | API Key Required | Environment Variable                    |
|------------------|------------------|-----------------------------------------|
| arXiv            | No               | -                                       |
| CrossRef         | No               | -                                       |
| IEEE             | **Yes**          | `FINDPAPERS_IEEE_API_TOKEN`             |
| PubMed           | No*              | `FINDPAPERS_PUBMED_API_TOKEN`           |
| Scopus           | **Yes**          | `FINDPAPERS_SCOPUS_API_TOKEN`           |
| OpenAlex         | **Yes**          | `FINDPAPERS_OPENALEX_API_TOKEN`         |
| Semantic Scholar | No*              | `FINDPAPERS_SEMANTIC_SCHOLAR_API_TOKEN` |

*PubMed and Semantic Scholar work without authentication but recommend using an API key for higher rate limits.

**Note**: As of February 2026, OpenAlex requires an API key (free tier: 100k credits/day).

### Setting up API keys

1. **IEEE Xplore**: Register at https://developer.ieee.org/
2. **Scopus/Elsevier**: Register at https://dev.elsevier.com/
3. **PubMed**: Register at https://www.ncbi.nlm.nih.gov/account/ (optional, 10 req/sec vs 3 req/sec)
4. **OpenAlex**: Request at https://docs.openalex.org/how-to-use-the-api/api-key (optional)
5. **Semantic Scholar**: Request at https://www.semanticscholar.org/product/api#api-key (optional)

Add keys to the `.env` file in the project root (see `.env.sample` for detailed instructions on how to obtain each key):

```
FINDPAPERS_IEEE_API_TOKEN=your_ieee_key_here
FINDPAPERS_SCOPUS_API_TOKEN=your_scopus_key_here
FINDPAPERS_PUBMED_API_TOKEN=your_pubmed_key_here
FINDPAPERS_OPENALEX_API_TOKEN=your_openalex_key_here
FINDPAPERS_SEMANTIC_SCHOLAR_API_TOKEN=your_semanticscholar_key_here
```

## Query Parameters

All collectors use the same search concepts and date range:

- **Search terms**: machine learning, deep learning, NLP, natural language processing
- **Date range**: 2020-01-01 to 2022-12-31
- **Limit**: 50 papers per database

> **Note**: Each API uses different query syntax. The collectors adapt the search terms
> to each API's specific format (Boolean operators, field specifiers, etc.).

## API Documentation

- **arXiv**: https://info.arxiv.org/help/api/user-manual.html
- **CrossRef**: https://www.crossref.org/documentation/
- **IEEE Xplore**: https://developer.ieee.org/docs
- **PubMed**: https://www.ncbi.nlm.nih.gov/books/NBK25500/
- **Scopus**: https://dev.elsevier.com/documentation/ScopusSearchAPI.wadl
- **OpenAlex**: https://docs.openalex.org/
- **Semantic Scholar**: https://api.semanticscholar.org/api-docs

## Output Files

### API sample collectors

Each database collector creates:

1. **`sample_response.{xml,json,html}`**: Raw API response
2. **`collection_metadata.json`**: Metadata including timestamp, API URL, query, status, result count

### Page collector (`pages/collect_pages.py`)

For each paper URL fetched:

1. **`<doi>.html`** (or **`<doi>.pdf.bin`** for direct PDF responses): Page content
2. **`<doi>.meta.json`**: Request metadata (url, final_url, doi, status, content_type, size_bytes)
3. **`index.json`**: Per-database index of all collected pages
4. **`collection_metadata.json`**: Overall collection summary

## Notes

- API collector scripts are standalone and don't use any findpapers code
- The page collector (`collect_pages.py`) also does not import findpapers
- Responses are saved as-is for test fixtures; re-running will overwrite existing files
- Pages are fetched with a ~1 s delay per request to avoid overloading servers
- The collected HTML pages are used as mock fixtures in `tests/unit/utils/` and
  `tests/unit/runners/` to test `EnrichmentRunner` without hitting the network
