# Search Databases

Findpapers supports six academic databases for searching and three connectors for citation traversal (snowballing). This page details each one.

## Overview

| Database | API Key | Search | Snowballing | Rate Limit |
|----------|---------|--------|-------------|------------|
| arXiv | Not required | Yes | No | ~3 s between requests |
| IEEE Xplore | **Required** | Yes | No | ~200 calls/day |
| OpenAlex | Optional | Yes | Yes (both) | ~10 req/s with email |
| PubMed | Optional | Yes | No | 3 req/s (10 with key) |
| Scopus | **Required** | Yes | No | Institution-dependent |
| Semantic Scholar | Optional | Yes | Yes (both) | ~1 req/s with key |
| CrossRef | Not required | No | Backward only | ~10 req/s |

## arXiv

- **URL:** https://arxiv.org
- **API:** Atom Feed API
- **Authentication:** None required
- **Coverage:** Preprints in physics, mathematics, computer science, quantitative biology, quantitative finance, statistics, electrical engineering, systems science, and economics

### Features

- Full boolean query support with wildcards
- Extracts title, abstract, authors (with affiliations), publication date, DOI, URLs, comments, and source/journal info
- Papers are typed as repository source

### Limitations

- No citation count data
- No keyword extraction (arXiv categories are not currently mapped to keywords)
- Rate limited to 3 seconds between requests (as recommended by arXiv)

---

## IEEE Xplore

- **URL:** https://ieeexplore.ieee.org
- **API:** IEEE Xplore API v1
- **Authentication:** API key **required** (`FINDPAPERS_IEEE_API_TOKEN`)
- **Coverage:** Journals, conferences, standards, books, and early access articles in electrical engineering, computer science, and related fields

### Getting an API Key

Register at the [IEEE Developer Portal](https://developer.ieee.org/) to obtain a free API key.

### Features

- Extracts title, abstract, authors (with affiliations), publication date, DOI, URLs, keywords (IEEE terms, author terms, MeSH terms), citation count, source, paper type, and page range
- Supports boolean queries with `*` wildcard

### Limitations

- Limited to ~200 API calls per day
- Only `*` wildcard supported (not `?`)

---

## OpenAlex

- **URL:** https://openalex.org
- **API:** OpenAlex REST API
- **Authentication:** Optional (`FINDPAPERS_OPENALEX_API_TOKEN`); providing an email (`FINDPAPERS_EMAIL`) enables polite pool access with higher rate limits
- **Coverage:** Over 250 million scholarly works across all disciplines

### Features

- Extracts title, abstract (from inverted index), authors (with institutional affiliations), publication date, DOI, URLs, PDF URLs, citation count, keywords (from concepts and keywords), source, paper type, and page range
- **Citation-capable:** supports both forward (cited-by) and backward (references) snowballing
- Best source selection (prefers journals/conferences over repositories)

### Limitations

- Abstract reconstruction from inverted index may occasionally differ from the original

---

## PubMed

- **URL:** https://pubmed.ncbi.nlm.nih.gov
- **API:** NCBI E-utilities (esearch + efetch)
- **Authentication:** Optional (`FINDPAPERS_PUBMED_API_TOKEN`); improves rate limit from 3 to 10 requests per second
- **Coverage:** Biomedical and life sciences literature

### Getting an API Key

Register at the [NCBI website](https://www.ncbi.nlm.nih.gov/account/) and generate an API key from your account settings.

### Features

- Extracts title, abstract (with inline markup handled), authors (with affiliations), publication date, DOI, URL, keywords (MeSH terms and author keywords), page range, source (journal with ISSN), and paper type
- Supports `*` wildcard

### Limitations

- Only `*` wildcard supported (not `?`)
- Without an API key, limited to 3 requests per second

---

## Scopus

- **URL:** https://www.scopus.com
- **API:** Elsevier Scopus Search API
- **Authentication:** API key **required** (`FINDPAPERS_SCOPUS_API_TOKEN`)
- **Coverage:** Over 90 million records across science, technology, medicine, social sciences, and arts & humanities

### Getting an API Key

Register at the [Elsevier Developer Portal](https://dev.elsevier.com/) and create an API key. Access may be limited by your institution's subscription.

### Features

- Extracts title, abstract, publication date, DOI, URL, citation count, source (with ISSN, eISSN, ISBN, publisher), paper type, and page range
- Supports boolean queries with wildcards

### Limitations

- Only the first author is returned per result
- Most 
- Rate limits depend on institutional subscription

---

## Semantic Scholar

- **URL:** https://www.semanticscholar.org
- **API:** Semantic Scholar Academic Graph API (bulk search + paper details)
- **Authentication:** Optional (`FINDPAPERS_SEMANTIC_SCHOLAR_API_TOKEN`)
- **Coverage:** Over 200 million papers across all fields, powered by AI-based metadata extraction

### Getting an API Key

Request an API key at the [Semantic Scholar API page](https://www.semanticscholar.org/product/api).

### Features

- Extracts title, abstract, authors (with affiliations via batch request), publication date, DOI, URLs, PDF URL, citation count, fields of study, source (journal or venue), paper type, and page range
- **Citation-capable:** supports both forward (cited-by) and backward (references) snowballing

### Limitations

- With an API key, rate limit is 1 request/second (introductory tier)
- Author affiliations require a separate batch request

---

## CrossRef

- **URL:** https://www.crossref.org
- **API:** CrossRef REST API
- **Authentication:** None required; providing an email (`FINDPAPERS_EMAIL`) enables polite pool access
- **Usage:** DOI-based metadata lookup and paper enrichment; used internally for enrichment and backward snowballing (not directly searchable)

### Features

- Extracts title, abstract, authors (with affiliations), DOI, URLs, PDF URL, citation count, keywords (from subject field), source (with ISSN, ISBN, publisher), page range, and page count
- **Backward snowballing only** (references); forward citation traversal returns empty

### Limitations

- Not available as a search database. Used only for DOI lookups, enrichment, and backward snowballing
- Abstract may contain JATS/HTML tags that are stripped during parsing

---

## Selecting Databases

By default, `Engine.search()` queries all databases for which valid credentials are available. To restrict to specific databases:

```python
result = engine.search(
    "[machine learning]",
    databases=["arxiv", "openalex", "semantic_scholar"],
)
```

Valid database identifiers: `arxiv`, `ieee`, `openalex`, `pubmed`, `scopus`, `semantic_scholar`.

## Deduplication

Papers found in multiple databases are automatically deduplicated:

1. **By DOI** - papers sharing the same DOI (case-insensitive) are merged
2. **By title and year** - papers with matching normalized titles and publication year are merged

When merging, metadata from all sources is combined: the longer abstract is kept, keywords are unioned, affiliations are back-filled, and the higher citation count is retained.
