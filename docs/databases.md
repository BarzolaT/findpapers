# Databases

One of the biggest advantages of Findpapers is that it connects you to **hundreds of millions of academic papers** from six major databases through a single query. Instead of visiting each portal separately and learning its query syntax, you write one search expression and Findpapers handles the rest - translating your query, running parallel searches, and merging all results with automatic deduplication.

Findpapers searches for papers through **arXiv**, **IEEE Xplore**, **OpenAlex**, **PubMed**, **Scopus**, and **Semantic Scholar** - together covering virtually every peer-reviewed paper, preprint, and conference proceeding published across all fields of science. In addition, **CrossRef** is used internally for DOI-based metadata enrichment and backward snowballing.

## Overview

The table below shows a quick databases comparison.

| Database | Size (papers) | API Key | Search | Snowballing | Rate Limit |
|----------|------------|---------|--------|-------------|------------|
| arXiv | 3M+ [¹](https://arxiv.org/stats/monthly_submissions) | Not required | Yes | No | ~3 s between requests |
| IEEE Xplore | 7M+ [²](https://innovate.ieee.org/about-the-ieee-xplore-digital-library) | Required | Yes | No | ~200 req/day |
| OpenAlex | 243M+ [³](https://openalex.org/about) | Optional | Yes | Yes (both) | ~10 req/s with email |
| PubMed | 40M+ [⁴](https://pubmed.ncbi.nlm.nih.gov/about/) | Optional | Yes | No | 3 req/s (10 with key) |
| Scopus | 100M+ [⁵](https://www.elsevier.com/products/scopus) | Required | Yes | No | 20k req/week |
| Semantic Scholar | 214M+ [⁶](https://www.semanticscholar.org/product/api) | Optional | Yes | Yes (both) | ~1 req/s with key |
| CrossRef | 180M+ [⁷](https://www.crossref.org/about) | Not required | No | Backward only | ~10 req/s |

> **Every API key from the databases listed above can be obtained at no cost** - just create an account on each provider’s website. We strongly recommend getting all of them before using Findpapers, as they unlock additional databases (IEEE, Scopus) and dramatically improve rate limits and reliability on the others (OpenAlex, PubMed, Semantic Scholar). See the **Databases** section for more details on how to get these API keys, and [Configuration](https://github.com/jonatasgrosman/findpapers/blob/main/docs/configuration.md) for how to set them up.

---

## Selecting Databases to Search

By default, `Engine.search()` queries all databases. To restrict to specific databases:

```python
result = engine.search(
    "[machine learning]",
    databases=["arxiv", "openalex", "semantic_scholar"],
)
```

Valid database identifiers: `arxiv`, `ieee`, `openalex`, `pubmed`, `scopus`, `semantic_scholar`.

## Rate Limiting

Findpapers automatically respects each database's rate limits. When a rate limit is hit, it waits for the required cooldown period before retrying. Responses with status codes 429 (Too Many Requests) and 5xx are retried with exponential backoff.

## Supported Databases

### arXiv

- **URL:** https://arxiv.org
- **API:** Atom Feed API
- **Authentication:** Not required
- **Estimated papers:** 3 million+ ([source](https://arxiv.org/stats/monthly_submissions))
- **Coverage:** Preprints in physics, mathematics, computer science, quantitative biology, quantitative finance, statistics, electrical engineering, systems science, and economics

arXiv is one of the most important open-access repositories in science. Founded in 1991, it hosts preprints - papers that have not yet undergone formal peer review - making it the fastest way to access cutting-edge research. It is especially dominant in physics, mathematics, and computer science, where sharing preprints on arXiv before journal publication is standard practice. Because papers appear here weeks or months before they are published in journals, arXiv is essential for researchers who need to stay ahead of the latest developments.

> **Note:** arXiv's API enforces a minimum interval of 3 seconds between requests. No API key is available - this limit applies to all users equally.

#### Features

- Full boolean query support
- Extracts title, abstract, authors (with affiliations), publication date, DOI, URLs, comments, and source/journal info
- Papers are typed as repository source

#### Limitations

- No citation count data
- No keywords
- Wildcards are not supported
- **Stemming:** arXiv uses Lucene-based stemming, so `ti[transformer]` also matches "transformers" and "transforming". Keep this in mind when looking for exact terms
- **Hyphens:** Hyphens are treated as spaces (`ti[self-attention]` is equivalent to `ti[self attention]`). Findpapers normalizes hyphens automatically

---

### IEEE Xplore

- **URL:** https://ieeexplore.ieee.org
- **API:** IEEE Xplore API v1
- **Authentication:** API key **required** - free, just register
- **Estimated papers:** 7 million+ ([source](https://innovate.ieee.org/about-the-ieee-xplore-digital-library))
- **Coverage:** Journals, conferences, standards, books, and early access articles in electrical engineering, computer science, and related fields

IEEE Xplore is the digital library of the Institute of Electrical and Electronics Engineers (IEEE), one of the world's largest technical professional organizations. It is the primary source for peer-reviewed content in electrical engineering, computer science, telecommunications, and related disciplines. Its collection includes top-tier conference proceedings (such as CVPR, ICCV, and INFOCOM), highly cited journals (like IEEE Transactions), and technical standards that define industry practices. If your research touches hardware, networking, signal processing, robotics, or AI, IEEE Xplore is likely indispensable.

> **Note:** Register at the [IEEE Developer Portal](https://developer.ieee.org/) to obtain a free API key. No payment or subscription is required. The API is limited to approximately 200 calls per day.

#### Features

- Extracts title, abstract, authors (with affiliations), DOI, URLs, keywords (IEEE terms, author terms, MeSH terms), citation count, source, paper type, page range, and open access status
- Supports boolean queries with `*` wildcard

#### Limitations

- Publication date has year-level granularity only
- Only `*` wildcard supported (not `?`)
- **Title-only filter disabled:** The `ti[]` filter is disabled for IEEE because the API's `"Article Title"` field silently returns zero results in `querytext` mode (used for boolean expressions).

---

### OpenAlex

- **URL:** https://openalex.org
- **API:** OpenAlex REST API
- **Authentication:** Optional but **highly recommended** - free, just register
- **Estimated papers:** 243 million+ ([source](https://openalex.org/about))
- **Coverage:** Over 243 million scholarly works across all disciplines

OpenAlex is the largest fully open index of scholarly works in the world. It was built as the open-source successor to Microsoft Academic Graph and is maintained by the nonprofit OurResearch. OpenAlex indexes papers, authors, institutions, and concepts across every academic discipline - from engineering and medicine to social sciences and humanities. Because it is completely open (no paywall, no subscription), it is an ideal backbone for large-scale bibliometric analysis and systematic reviews. It also provides rich citation links, making it one of the best sources for forward and backward snowballing in Findpapers.

> **Note:** Without an API key, OpenAlex allows only ~10 requests per day ($0.01 budget), which is too low for practical use. A free API key raises this to ~10,000 requests per day - no payment needed, just a free account. We strongly recommend obtaining one at [openalex.org/settings/api](https://openalex.org/settings/api).

#### Features

- Extracts title, abstract, authors (with institutional affiliations), publication date, DOI, URLs, PDF URLs, citation count, keywords, source, paper type, page range, language (ISO 639-1 code), and open access status
- **Citation-capable:** supports both forward (cited-by) and backward (references) snowballing
- Best source selection (prefers journals/conferences over repositories)

#### Limitations

- Abstract reconstruction from inverted index may occasionally differ from the original

---

### PubMed

- **URL:** https://pubmed.ncbi.nlm.nih.gov
- **API:** NCBI E-utilities (esearch + efetch)
- **Authentication:** Optional - free, just register
- **Estimated papers:** 40 million+ ([source](https://pubmed.ncbi.nlm.nih.gov/about/))
- **Coverage:** Biomedical and life sciences literature

PubMed is the world's most important database for biomedical and life sciences research. Maintained by the U.S. National Library of Medicine (NLM) at the National Institutes of Health (NIH), it indexes content from MEDLINE, PubMed Central (PMC), and other life sciences journals. What sets PubMed apart is its use of MeSH (Medical Subject Headings) - a curated, hierarchical vocabulary that human indexers assign to each article, enabling highly precise topical searches that keyword-based systems cannot match. If your research involves medicine, biology, pharmacology, public health, or any health-related field, PubMed is almost certainly your primary database.

> **Note:** Register at the [NCBI website](https://www.ncbi.nlm.nih.gov/account/) and generate an API key from your account settings. It's completely free. Without a key, PubMed allows 3 requests per second; with a key, this increases to 10 requests per second.

#### Features

- Extracts title, abstract, authors (with affiliations), publication date, DOI, URL, keywords (MeSH terms and author keywords), page range, source (journal with ISSN), paper type, and language (ISO 639-1 code)
- Supports `*` wildcard

#### Limitations

- Only `*` wildcard supported (not `?`)
- **Author name format:** PubMed indexes authors as "LastName Initials" (e.g., `Doudna JA`). When using the `au` filter, provide the name in this format for reliable results: `au[Doudna JA]`. Full first names (e.g., `au[Jennifer Doudna]`) may return no results
- **Phrase length limit:** PubMed's phrase index only supports exact-match phrases up to approximately 3 words. Queries like `ti[deep learning]` (2 words) work, but `ti[deep learning for image recognition]` (5 words) returns zero results. Keep `ti[]`, `abs[]`, and `tiabs[]` terms short (1–3 words) for best results. To search for longer concepts, combine shorter phrases with AND: `ti[deep learning] AND ti[image recognition]`

---

### Scopus

- **URL:** https://www.scopus.com
- **API:** Elsevier Scopus Search API
- **Authentication:** API key **required** - free, just register
- **Estimated papers:** 100 million+ ([source](https://www.elsevier.com/products/scopus))
- **Coverage:** Over 100 million records across science, technology, medicine, social sciences, and arts & humanities

Scopus is Elsevier's flagship abstract and citation database, and one of the two largest curated indexes of peer-reviewed literature in the world (alongside Web of Science). It covers over 27,000 journals, 130,000 books, and 13 million conference papers across virtually every scientific discipline. Scopus is the go-to database for many universities and funding agencies when performing bibliometric analysis, rankings, and research evaluation (e.g., h-index calculations). Its broad, multidisciplinary coverage makes it especially valuable for systematic reviews that need to span multiple fields.

> **Note:** Register at the [Elsevier Developer Portal](https://dev.elsevier.com/) and create an API key - it's free. Scopus has a rate limit of 20,000 requests per week, which should be sufficient for most users.

#### Features

- Extracts title, publication date, DOI, URL, citation count, source (with ISSN, eISSN, ISBN, publisher), paper type, page range, and open access status
- Supports boolean queries with wildcards

#### Limitations

- Only the first author is returned per result
- No keywords
- No abstracts are returned by the API; enrichment is recommended to fill in missing metadata
- Date filtering has year-level granularity only

---

### Semantic Scholar

- **URL:** https://www.semanticscholar.org
- **API:** Semantic Scholar Academic Graph API (bulk search + paper details)
- **Authentication:** Optional but **highly recommended** - free, just register
- **Estimated papers:** 214 million+ ([source](https://www.semanticscholar.org/product/api))
- **Coverage:** Over 214 million papers across all fields, powered by AI-based metadata extraction

Semantic Scholar is a free, AI-powered academic search engine developed by the Allen Institute for AI (AI2). Unlike traditional databases that rely on publisher-submitted metadata, Semantic Scholar uses machine learning models to automatically extract titles, authors, abstracts, citations, and topics from the full text of papers. This allows it to index a vast number of sources, including papers from smaller publishers and open-access repositories that other databases may miss. It is particularly strong in computer science and biomedical research, and its citation graph - with both forward and backward links - makes it one of the best sources for snowballing.

> **Note:** Without an API key, Semantic Scholar’s rate limit of 1,000 requests/second is shared among all unauthenticated users, which can lead to throttling during peak times. With a free API key you get a dedicated rate limit, making searches much more reliable. No payment needed - request one at [semanticscholar.org/product/api](https://www.semanticscholar.org/product/api). With an API key, rate limit is 1 request/second (introductory tier).

#### Features

- Extracts title, abstract, authors (with affiliations), publication date, DOI, URLs, PDF URL, citation count, fields of study, source (journal or venue), paper type, page range, and open access status
- Supports both forward (cited-by) and backward (references) snowballing

#### Limitations

- No keywords
- When exact publication date is unavailable, falls back to year only (January 1)
- Only `tiabs` (title + abstract) filter is supported

---

### CrossRef

- **URL:** https://www.crossref.org
- **API:** CrossRef REST API
- **Authentication:** Not required
- **Estimated DOIs:** 180 million+ ([source](https://www.crossref.org/about))
- **Coverage:** Metadata for scholarly works with DOIs across all disciplines

CrossRef is a nonprofit organization that serves as the official DOI (Digital Object Identifier) registration agency for scholarly content. It provides authoritative, structured metadata for millions of DOIs, including publisher information, reference lists, licensing data, and funding details. While Findpapers does not use CrossRef as a search database, it plays a critical role behind the scenes: it enriches papers found in other databases with additional metadata (abstracts, keywords, citation counts) and enables backward snowballing by following the reference lists attached to each DOI.

> **Note:** No API key is needed. Providing your email enables the CrossRef "polite pool", which offers faster and more reliable responses (~50 requests/s instead of ~10 requests/s for anonymous users).

#### Features

- Extracts title, abstract, authors (with affiliations), DOI, URLs, PDF URL, citation count, keywords (from subject field), source (with ISSN, ISBN, publisher), and page range
- Backward snowballing

#### Limitations

- Not available as a search database. Used only for DOI lookups, enrichment, and backward snowballing
- Forward snowballing (cited-by) is not supported by the CrossRef API
- Reference lists may be incomplete - only references with DOIs can be followed
