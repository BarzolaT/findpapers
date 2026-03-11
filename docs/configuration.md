# Configuration

Findpapers can be configured via constructor parameters or environment variables. Environment variables are used as fallbacks when no explicit value is passed.

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `FINDPAPERS_IEEE_API_TOKEN` | IEEE Xplore API key | Required for IEEE searches |
| `FINDPAPERS_SCOPUS_API_TOKEN` | Elsevier Scopus API key | Required for Scopus searches |
| `FINDPAPERS_PUBMED_API_TOKEN` | NCBI PubMed API key | Optional (improves rate limit) |
| `FINDPAPERS_OPENALEX_API_TOKEN` | OpenAlex API key | Optional (improves quota) |
| `FINDPAPERS_SEMANTIC_SCHOLAR_API_TOKEN` | Semantic Scholar API key | Optional (improves rate limit) |
| `FINDPAPERS_EMAIL` | Your email address | Optional (enables polite pool for OpenAlex and CrossRef) |
| `FINDPAPERS_PROXY` | HTTP/HTTPS proxy URL | Optional |
| `FINDPAPERS_SSL_VERIFY` | SSL certificate verification (`true`/`false`) | Optional (default: `true`) |

### Example `.env` File

```bash
FINDPAPERS_IEEE_API_TOKEN=your-ieee-key-here
FINDPAPERS_SCOPUS_API_TOKEN=your-scopus-key-here
FINDPAPERS_PUBMED_API_TOKEN=your-pubmed-key-here
FINDPAPERS_EMAIL=researcher@university.edu
```

> **Note:** Findpapers does not load `.env` files automatically. Use a tool like [python-dotenv](https://pypi.org/project/python-dotenv/) or export the variables in your shell.

## Passing Configuration Directly

All environment variables can be overridden by passing values to the `Engine` constructor:

```python
import findpapers

engine = findpapers.Engine(
    ieee_api_key="your-ieee-key",
    scopus_api_key="your-scopus-key",
    pubmed_api_key="your-pubmed-key",
    openalex_api_key="your-openalex-key",
    email="researcher@university.edu",
    semantic_scholar_api_key="your-s2-key",
    proxy="http://proxy.example.com:8080",
    ssl_verify=True,
)
```

Constructor parameters take precedence over environment variables.

## Proxy Configuration

To route all HTTP requests through a proxy:

```python
engine = findpapers.Engine(proxy="http://proxy.example.com:8080")
```

Or via environment variable:

```bash
export FINDPAPERS_PROXY="http://proxy.example.com:8080"
```

The proxy URL is applied to both HTTP and HTTPS requests.

## SSL Verification

SSL certificate verification is enabled by default. To disable it (e.g., behind a corporate proxy with a custom CA):

```python
engine = findpapers.Engine(ssl_verify=False)
```

Or via environment variable:

```bash
export FINDPAPERS_SSL_VERIFY=false
```

Accepted values for `FINDPAPERS_SSL_VERIFY`: `false`, `0`, `no` (case-insensitive) to disable. Any other value keeps verification enabled.

> **Warning:** Disabling SSL verification makes requests vulnerable to man-in-the-middle attacks. Only use this in trusted network environments.

## Parallel Execution

Several methods support parallel execution via the `num_workers` parameter:

```python
# Search databases in parallel
result = engine.search("[machine learning]", num_workers=4)

# Download PDFs in parallel
engine.download(result.papers, "./pdfs", num_workers=8)

# Enrich in parallel
engine.enrich(result.papers, num_workers=4)
```

When `num_workers=1` (default), operations run sequentially. When greater than 1, a thread pool is used. The optimal number depends on your network and the API rate limits.

## Verbose Logging

Enable detailed logging for debugging:

```python
result = engine.search("[machine learning]", verbose=True)
```

When `verbose=True`, Findpapers logs HTTP requests, responses, rate limiting events, and processing details to the console.

## Progress Bars

Progress bars are shown by default using [tqdm](https://tqdm.github.io/). Disable them with:

```python
result = engine.search("[machine learning]", show_progress=False)
```

## Timeouts

Download and enrichment operations accept a `timeout` parameter (in seconds) for individual HTTP requests:

```python
engine.download(result.papers, "./pdfs", timeout=30.0)
engine.enrich(result.papers, timeout=15.0)
```

Set to `None` to disable timeouts (not recommended).

## Rate Limiting

Findpapers automatically respects each database's rate limits. The built-in intervals are:

| Database | Interval |
|----------|----------|
| arXiv | 3.0 s |
| IEEE | 0.5 s |
| OpenAlex | 0.15 s |
| PubMed (no key) | 0.34 s |
| PubMed (with key) | 0.11 s |
| Scopus | 0.5 s |
| Semantic Scholar | 1.1 s |
| CrossRef | 0.1 s |

These intervals are enforced automatically. Responses with status codes 429 (Too Many Requests) and 5xx are retried with exponential backoff.
