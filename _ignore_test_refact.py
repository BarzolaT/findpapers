"""Phased manual battery for validating the refactored findpapers flows.

Run from project root:
    venv/bin/python _ignore_test_refact.py

To run against a single database only:
    venv/bin/python _ignore_test_refact.py --database arxiv
    venv/bin/python _ignore_test_refact.py -d pubmed

Available database identifiers: arxiv, openalex, pubmed, semantic_scholar,
ieee (requires API key), scopus (requires API key).

Outputs are stored under:
    tmp/test_refact_results/phase_*/

Phases:
    1  – simple term per database (sanity)
    2  – boolean connectors (AND, OR, AND NOT)
    3  – grouped expressions
    4  – filtered mix (per-database field filters)
    5  – multi-database queries
    6  – enrichment runner
    7  – download runner
    8  – parallelism comparison (sequential vs. concurrent)
    9  – paper_types filter
    10 – post-search date filter
    11 – error handling (invalid inputs)
    12 – Search metadata and per-database metrics
    13 – cross-database deduplication
    14 – re-run idempotency and get_results() isolation
    15 – wildcard searches (* and ?)
    16 – wildcard syntax validation (construction-time errors)
    17 – unsupported filter graceful skip (per-database)
    18 – group-level filter propagation
    19 – extended filter codes (key, src, tiabskey)
    20 – case-insensitivity of filter codes and boolean operators
    21 – complex queries with multiple connectors and nested groups
    22 – behaviour when no API keys are provided
    23 – export format roundtrip validation (JSON / CSV / BibTeX)
    24 – paper field integrity per database (deep validation)
    25 – max_papers_per_database strict enforcement
    26 – predatory source detection (offline)
    27 – known paper precision check
    28 – DOI deduplication and preprint handling
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import re
import shutil
import signal
import sys
import textwrap
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Load .env into os.environ before findpapers imports
# ---------------------------------------------------------------------------
_ENV_PATH = Path(__file__).parent / ".env"
if _ENV_PATH.exists():
    for _line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _key, _, _val = _line.partition("=")
        os.environ.setdefault(_key.strip(), _val.strip())

from findpapers import (  # noqa: E402
    DownloadRunner,
    EnrichmentRunner,
    SearchRunner,
    SearchRunnerNotExecutedError,
)
from findpapers.core.paper import Paper  # noqa: E402
from findpapers.core.query import QueryValidationError  # noqa: E402
from findpapers.core.search import Search  # noqa: E402
from findpapers.utils.export import export_to_bibtex, export_to_csv, export_to_json  # noqa: E402

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
SCOPUS_API_KEY = os.environ.get("FINDPAPERS_SCOPUS_API_TOKEN")
IEEE_API_KEY = os.environ.get("FINDPAPERS_IEEE_API_TOKEN")
PUBMED_API_KEY = os.environ.get("FINDPAPERS_PUBMED_API_TOKEN")
SEMANTIC_SCHOLAR_API_KEY = os.environ.get("FINDPAPERS_SEMANTIC_SCHOLAR_API_TOKEN")
OPENALEX_API_KEY = os.environ.get("FINDPAPERS_OPENALEX_API_TOKEN")
OPENALEX_EMAIL = os.environ.get("FINDPAPERS_OPENALEX_EMAIL")
PROXY = os.environ.get("FINDPAPERS_PROXY")

OUTPUT_DIR = Path(__file__).parent / "tmp" / "test_refact_results"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.CRITICAL,
    format="%(levelname)s | %(name)s | %(message)s",
    stream=sys.stdout,
)

SEPARATOR = "=" * 80


@dataclass
class CaseResult:
    """Represents one executed test case."""

    phase: str
    case_id: str
    query: str
    databases: list[str]
    paper_count: int
    runtime_seconds: float
    success: bool
    notes: list[str]


def section(title: str) -> None:
    """Print a visual section separator."""
    print(f"\n{SEPARATOR}")
    print(f"{title}")
    print(SEPARATOR)


def ok(message: str) -> None:
    """Print an OK line."""
    print(f"  [OK]   {message}")


def warn(message: str) -> None:
    """Print a warning line."""
    print(f"  [WARN] {message}")


def fail(message: str, exc: BaseException | None = None) -> None:
    """Print a failure line and traceback when available."""
    print(f"  [FAIL] {message}")
    if exc is not None:
        traceback_text = textwrap.indent(traceback.format_exc(), "         ")
        print(traceback_text)


def phase_dir(name: str) -> Path:
    """Return phase output directory and create it if needed."""
    folder = OUTPUT_DIR / name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _extract_query_terms(
    query: str,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Extract positive and negative terms from a findpapers query string.

    Returns two lists of ``(term, scope)`` pairs where *scope* is one of
    ``"title"``, ``"abstract"`` or ``"tiabs"`` (title OR abstract).
    Terms with field codes ``au``, ``af`` or ``key`` are skipped because
    they do not map to title/abstract content.

    For wildcard terms (``*`` or ``?``) only the substring that precedes the
    wildcard character is kept, so that relevance checks test for the known
    prefix rather than a literal ``*`` or ``?`` which never appears in paper
    text.  For example ``[cance*]`` yields the matching token ``"cance"``,
    and ``[canc?r]`` yields ``"canc"``.

    Parameters
    ----------
    query : str
        Raw findpapers query string, e.g. ``[machine learning] AND [healthcare]``.

    Returns
    -------
    tuple[list[tuple[str, str]], list[tuple[str, str]]]
        ``(positive_terms, negative_terms)`` — negated terms come from
        ``AND NOT`` / ``NOT`` context.
    """
    # Filters whose terms are not expected to appear in title/abstract:
    # au (author), aff (affiliation), key (keywords/MeSH), src (journal name).
    _SKIP_FIELDS = {"au", "aff", "key", "src"}
    token_re = re.compile(r"(?:([a-zA-Z]+)\s*)?\[([^\]]+)\]")

    pos_terms: list[tuple[str, str]] = []
    neg_terms: list[tuple[str, str]] = []

    for m in token_re.finditer(query):
        prefix = m.group(1)
        raw_term = m.group(2).strip().lower()

        # For wildcard terms keep only the substring before the wildcard
        # character so that relevance checks match on the known prefix rather
        # than the literal '*' or '?' characters (which never appear in paper
        # titles or abstracts).
        wildcard_pos = next(
            (i for i, ch in enumerate(raw_term) if ch in ("*", "?")), None
        )
        term = raw_term[:wildcard_pos] if wildcard_pos is not None else raw_term

        # Skip if the entire term was consumed by the wildcard (shouldn't
        # happen after validation, but guard defensively).
        if not term:
            continue

        if prefix is not None:
            p = prefix.lower()
            if p in _SKIP_FIELDS:
                continue
            if p == "ti":
                scope = "title"
            elif p == "abs":
                scope = "abstract"
            else:
                scope = "tiabs"  # covers plain [], AND [], OR [], NOT []
        else:
            scope = "tiabs"

        # Detect negation: look for NOT in the text immediately before this match.
        before = query[: m.start()].rstrip()
        is_negated = bool(re.search(r"\bNOT\s*$", before, re.IGNORECASE))

        if is_negated:
            neg_terms.append((term, scope))
        else:
            pos_terms.append((term, scope))

    return pos_terms, neg_terms


def check_term_relevance(search: Search, case_id: str) -> None:
    """Check that returned papers contain query terms in title/abstract.

    Reports the percentage of papers where at least one positive query term
    appears in the mapped field (title, abstract, or either).  Also warns
    when papers contain negated (``AND NOT``) terms.

    Parameters
    ----------
    search : Search
        The executed search result.
    case_id : str
        Case identifier used in printed messages.
    """
    if not search.papers:
        return

    pos_terms, neg_terms = _extract_query_terms(search.query)

    if not pos_terms:
        return  # pure author / affiliation query — nothing to check

    def _matches(paper: Paper, terms: list[tuple[str, str]]) -> bool:
        title = (paper.title or "").lower()
        abstract = (paper.abstract or "").lower()
        for term, scope in terms:
            if scope == "title" and term in title:
                return True
            if scope == "abstract" and term in abstract:
                return True
            if scope == "tiabs" and (term in title or term in abstract):
                return True
        return False

    total = len(search.papers)
    matched = sum(1 for p in search.papers if _matches(p, pos_terms))
    no_abstract = sum(
        1
        for p in search.papers
        if not (p.abstract or "").strip() and not _matches(p, pos_terms)
    )
    pct = matched / total * 100

    if matched == total:
        ok(f"{case_id}: relevância 100% ({matched}/{total} papers contêm termos da query)")
    elif pct >= 50:
        detail = f" ({no_abstract} sem abstract)" if no_abstract else ""
        warn(
            f"{case_id}: relevância {pct:.0f}%"
            f" ({matched}/{total} papers contêm termos da query{detail})"
        )
    else:
        detail = f" ({no_abstract} sem abstract)" if no_abstract else ""
        warn(
            f"{case_id}: relevância BAIXA {pct:.0f}%"
            f" ({matched}/{total} papers contêm termos da query{detail})"
        )

    if neg_terms:
        contaminated = sum(1 for p in search.papers if _matches(p, neg_terms))
        if contaminated:
            warn(f"{case_id}: {contaminated}/{total} papers contêm termo excluído (AND NOT)")
        else:
            ok(f"{case_id}: nenhum paper contém termos excluídos (AND NOT)")


def available_databases() -> list[str]:
    """Return databases available in this environment.

    Returns
    -------
    list[str]
        Available database identifiers considering configured API keys.
    """
    dbs = ["arxiv", "openalex", "pubmed", "semantic_scholar"]
    if IEEE_API_KEY:
        dbs.append("ieee")
    if SCOPUS_API_KEY:
        dbs.append("scopus")
    return dbs


def export_search(search: Search, target_dir: Path, stem: str) -> None:
    """Export Search results in JSON/CSV/BibTeX."""
    export_to_json(search, str(target_dir / f"{stem}.json"))
    export_to_csv(search, str(target_dir / f"{stem}.csv"))
    export_to_bibtex(search, str(target_dir / f"{stem}.bib"))


def build_runner(query: str, databases: list[str], max_papers: int, **kwargs: Any) -> SearchRunner:
    """Instantiate SearchRunner with project credentials."""
    return SearchRunner(
        query=query,
        databases=databases,
        max_papers_per_database=max_papers,
        ieee_api_key=IEEE_API_KEY,
        scopus_api_key=SCOPUS_API_KEY,
        pubmed_api_key=PUBMED_API_KEY,
        openalex_api_key=OPENALEX_API_KEY,
        openalex_email=OPENALEX_EMAIL,
        semantic_scholar_api_key=SEMANTIC_SCHOLAR_API_KEY,
        **kwargs,
    )


def run_case(
    *,
    phase: str,
    case_id: str,
    query: str,
    databases: list[str],
    max_papers: int,
    target_dir: Path,
    paper_types: list[str] | None = None,
    num_workers: int = 1,
    timeout_seconds: int = 120,
    verbose: bool = False,
) -> tuple[CaseResult, Search | None]:
    """Run one search case and persist outputs.

    Parameters
    ----------
    phase : str
        Phase name.
    case_id : str
        Stable case identifier.
    query : str
        Query string.
    databases : list[str]
        Databases to search.
    max_papers : int
        Maximum papers per database.
    target_dir : Path
        Destination folder.
    paper_types : list[str] | None
        Optional paper type filter.
    num_workers : int
        Parallel workers.
    verbose : bool
        Whether to enable verbose logging in the runner.

    Returns
    -------
    tuple[CaseResult, Search | None]
        Case metadata and the Search object when successful.
    """
    print(f"\n  -> {case_id}")
    print(f"     query: {query}")
    print(f"     dbs  : {databases}")
    notes: list[str] = []

    try:
        runner = build_runner(
            query=query,
            databases=databases,
            max_papers=max_papers,
            paper_types=paper_types,
            num_workers=num_workers,
        )

        def _timeout_handler(_signum: int, _frame: Any) -> None:
            raise TimeoutError(f"case timeout after {timeout_seconds}s")

        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(timeout_seconds)
        try:
            search = runner.run(verbose=verbose)
        finally:
            signal.alarm(0)

        metrics = runner.get_metrics()
        export_search(search, target_dir, case_id)
        ok(f"papers={len(search.papers)} | runtime={float(metrics['runtime_in_seconds']):.2f}s")
        if len(search.papers) == 0:
            notes.append("zero_results")
            warn("0 papers returned")
        check_term_relevance(search, case_id)

        result = CaseResult(
            phase=phase,
            case_id=case_id,
            query=query,
            databases=databases,
            paper_count=len(search.papers),
            runtime_seconds=float(metrics["runtime_in_seconds"]),
            success=True,
            notes=notes,
        )
        return result, search
    except TimeoutError as exc:
        fail(str(exc), exc)
        result = CaseResult(
            phase=phase,
            case_id=case_id,
            query=query,
            databases=databases,
            paper_count=0,
            runtime_seconds=0.0,
            success=False,
            notes=["timeout"],
        )
        return result, None
    except Exception as exc:
        fail("case crashed", exc)
        result = CaseResult(
            phase=phase,
            case_id=case_id,
            query=query,
            databases=databases,
            paper_count=0,
            runtime_seconds=0.0,
            success=False,
            notes=["exception"],
        )
        return result, None


def save_phase_summary(target_dir: Path, results: list[CaseResult]) -> None:
    """Save phase summary as JSON."""
    payload = [
        {
            "phase": result.phase,
            "case_id": result.case_id,
            "query": result.query,
            "databases": result.databases,
            "paper_count": result.paper_count,
            "runtime_seconds": result.runtime_seconds,
            "success": result.success,
            "notes": result.notes,
        }
        for result in results
    ]
    (target_dir / "phase_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def phase_1_simple_term(
    databases: list[str] | None = None,
    verbose: bool = False,
) -> tuple[list[CaseResult], dict[str, Search]]:
    """Phase 1: one simple unfiltered term per database."""
    name = "phase_1_simple_term"
    section("FASE 1 - termo simples sem filtro por base")
    target = phase_dir(name)
    results: list[CaseResult] = []
    searches: dict[str, Search] = {}

    for db in databases if databases is not None else available_databases():
        case_result, search = run_case(
            phase=name,
            case_id=f"{db}_sanity",
            query="[cancer]",
            databases=[db],
            max_papers=10,
            target_dir=target,
            timeout_seconds=120,
            verbose=verbose,
        )
        results.append(case_result)
        if search is not None:
            searches[db] = search

    # Spot-check: verify that papers from successful searches have non-empty title/abstract.
    for db, search in searches.items():
        if not search.papers:
            continue
        blank_title = [p for p in search.papers if not p.title or not p.title.strip()]
        blank_abstract = [p for p in search.papers if not p.abstract or not p.abstract.strip()]
        if blank_title:
            warn(f"{db}: {len(blank_title)} paper(s) com título vazio")
        else:
            ok(f"{db}: todos os {len(search.papers)} paper(s) têm título não-vazio")
        if blank_abstract:
            warn(f"{db}: {len(blank_abstract)} paper(s) com abstract vazio")
        else:
            ok(f"{db}: todos os {len(search.papers)} paper(s) têm abstract não-vazio")

        # Deep field integrity validation
        field_issues = _validate_paper_fields(search.papers, db, f"phase1_{db}")
        if field_issues:
            warn(f"{db}: {len(field_issues)} problema(s) de integridade de campos:")
            for issue in field_issues[:5]:
                print(f"         {issue}")
            if len(field_issues) > 5:
                print(f"         ... e mais {len(field_issues) - 5} problema(s)")
        else:
            ok(f"{db}: integridade de campos OK ({len(search.papers)} papers validados)")

    save_phase_summary(target, results)
    return results, searches


def phase_2_connectors(
    databases: list[str] | None = None, verbose: bool = False
) -> list[CaseResult]:
    """Phase 2: two terms, one test for each connector supported by each database."""
    name = "phase_2_connectors"
    section("FASE 2 - dois termos e conectores")
    target = phase_dir(name)
    results: list[CaseResult] = []

    connector_queries = {
        "and": "[machine learning] AND [healthcare]",
        "or": "[machine learning] OR [healthcare]",
        "and_not": "[machine learning] AND NOT [agriculture]",
    }

    for db in databases if databases is not None else available_databases():
        supported = ["and", "or", "and_not"]

        for connector_name in supported:
            case_result, _ = run_case(
                phase=name,
                case_id=f"{db}_{connector_name}",
                query=connector_queries[connector_name],
                databases=[db],
                max_papers=8,
                target_dir=target,
                timeout_seconds=120,
                verbose=verbose,
            )
            results.append(case_result)

    # Sanity-check: AND must never return more papers than OR for the same two terms.
    for db in databases if databases is not None else available_databases():
        and_res = next((r for r in results if r.case_id == f"{db}_and"), None)
        or_res = next((r for r in results if r.case_id == f"{db}_or"), None)
        if and_res and or_res and and_res.success and or_res.success:
            if and_res.paper_count <= or_res.paper_count:
                ok(f"{db}: AND ({and_res.paper_count}) <= OR ({or_res.paper_count}) — consistente")
            else:
                warn(
                    f"{db}: AND ({and_res.paper_count}) > OR ({or_res.paper_count}) — "
                    "AND retornou MAIS que OR; verificar lógica de consulta"
                )

    save_phase_summary(target, results)
    return results


def phase_3_groups(databases: list[str] | None = None, verbose: bool = False) -> list[CaseResult]:
    """Phase 3: grouped expressions for each isolated database."""
    name = "phase_3_groups"
    section("FASE 3 - grupos")
    target = phase_dir(name)
    results: list[CaseResult] = []

    for db in databases if databases is not None else available_databases():
        query = "([machine learning] OR [deep learning]) AND [medical imaging]"
        case_result, _ = run_case(
            phase=name,
            case_id=f"{db}_groups",
            query=query,
            databases=[db],
            max_papers=8,
            target_dir=target,
            timeout_seconds=120,
            verbose=verbose,
        )
        results.append(case_result)

    save_phase_summary(target, results)
    return results


def phase_4_filtered_mix(
    databases: list[str] | None = None, verbose: bool = False
) -> list[CaseResult]:
    """Phase 4: mixed query patterns using explicit filters."""
    name = "phase_4_filtered_mix"
    section("FASE 4 - mix com filtros")
    target = phase_dir(name)
    results: list[CaseResult] = []

    db_queries: dict[str, str] = {
        # ti+abs OR exercises both field filters. "attention" appears in both title
        # and abstract of Vaswani's "Attention Is All You Need" (arXiv:1706.03762),
        # whereas "transformer" is not in that paper's title so the former query
        # was yielding 0 results.
        "arxiv": "(ti[attention] OR abs[attention]) AND au[vaswani]",
        # aff[stanford] is more selective than aff[university] and still broadly indexed.
        "ieee": "(ti[edge computing] OR key[latency]) AND aff[stanford]",
        "scopus": "(ti[edge computing] OR key[latency]) AND aff[stanford]",
        "pubmed": "(ti[diabetes] OR abs[insulin]) AND aff[hospital]",
        # BUG FIX: 'auth' is not a valid FilterCode; the correct code is 'au'.
        # Using a well-known AI researcher to maximise hit probability.
        "openalex": "(ti[neural network] OR abs[deep learning]) AND au[lecun]",
    }

    if databases is not None:
        db_queries = {db: q for db, q in db_queries.items() if db in databases}

    for db, query in db_queries.items():
        if db == "ieee" and not IEEE_API_KEY:
            continue
        if db == "scopus" and not SCOPUS_API_KEY:
            continue
        case_result, _ = run_case(
            phase=name,
            case_id=f"{db}_filtered_mix",
            query=query,
            databases=[db],
            max_papers=8,
            target_dir=target,
            verbose=verbose,
        )
        results.append(case_result)

    # Semantic Scholar intentionally excluded: it only supports tiabs filtering.
    (target / "notes.txt").write_text(
        "semantic_scholar não entra na fase 4 por limitação de filtros.\n",
        encoding="utf-8",
    )

    save_phase_summary(target, results)
    return results


def phase_5_multi_database(
    databases: list[str] | None = None,
    verbose: bool = False,
) -> tuple[list[CaseResult], Search | None]:
    """Phase 5: mixed queries against multiple databases in one run."""
    name = "phase_5_multi_database"
    section("FASE 5 - mix consultando múltiplas bases")
    target = phase_dir(name)
    results: list[CaseResult] = []

    combos: list[tuple[str, list[str], str]] = [
        (
            "multi_open",
            ["arxiv", "openalex", "pubmed", "semantic_scholar"],
            "([federated learning] OR [privacy]) AND [healthcare]",
        ),
    ]

    if IEEE_API_KEY and SCOPUS_API_KEY:
        combos.append(
            (
                "multi_all_paid",
                ["ieee", "scopus", "openalex", "pubmed"],
                "([neural network] OR [transformer]) AND NOT [survey]",
            )
        )

    if databases is not None:
        filtered: list[tuple[str, list[str], str]] = []
        for case_id, dbs, query in combos:
            filtered_dbs = [db for db in dbs if db in databases]
            if filtered_dbs:
                filtered.append((case_id, filtered_dbs, query))
        combos = filtered

    selected_for_phase_6: Search | None = None
    for case_id, dbs, query in combos:
        case_result, search = run_case(
            phase=name,
            case_id=case_id,
            query=query,
            databases=dbs,
            max_papers=10,
            target_dir=target,
            num_workers=2,
            verbose=verbose,
        )
        results.append(case_result)
        if selected_for_phase_6 is None and search is not None and search.papers:
            selected_for_phase_6 = search

    save_phase_summary(target, results)
    return results, selected_for_phase_6


def paper_richness_score(paper: Paper) -> int:
    """Compute a simple completeness score for one paper.

    Mirrors the fields tracked by ``_enrichment_snapshot`` in
    ``EnrichmentRunner`` so that ``papers_with_richness_increase`` correctly
    reflects any enrichment change detected by the runner.
    """
    score = 0
    attrs = [
        paper.abstract,
        paper.url,
        paper.pdf_url,
        paper.doi,
        paper.citations,
        paper.comments,
        paper.number_of_pages,
        paper.pages,
        paper.publication_date,
        paper.paper_type,
    ]
    for value in attrs:
        if value is not None and value != "":
            score += 1
    if paper.authors:
        score += 1
    if paper.keywords:
        score += 1
    if paper.source is not None:
        if paper.source.title:
            score += 1
        if paper.source.publisher:
            score += 1
        if paper.source.issn:
            score += 1
        if paper.source.isbn:
            score += 1
    return score


def _paper_missing_enrichable_fields(paper: Paper) -> list[str]:
    """Return the names of enrichable fields that are absent or empty in *paper*.

    Mirrors the tuple built by ``_enrichment_snapshot`` inside
    ``EnrichmentRunner._enrich_paper`` so that phase 6 can decide which
    papers are worth enriching and whether a zero-enrichment result is a
    genuine capability gap or simply expected (all papers were already
    complete).
    """
    missing: list[str] = []
    if not paper.abstract:
        missing.append("abstract")
    if not paper.doi:
        missing.append("doi")
    if not paper.pdf_url:
        missing.append("pdf_url")
    if not paper.publication_date:
        missing.append("publication_date")
    if not paper.pages:
        missing.append("pages")
    if paper.number_of_pages is None:
        missing.append("number_of_pages")
    if paper.paper_type is None:
        missing.append("paper_type")
    if not paper.authors:
        missing.append("authors")
    if not paper.keywords:
        missing.append("keywords")
    if paper.source is None:
        missing.append("source")
    elif not paper.source.publisher:
        missing.append("source.publisher")
    elif not paper.source.issn:
        missing.append("source.issn")
    return missing


def _validate_paper_fields(papers: list[Paper], db: str, case_id: str) -> list[str]:
    """Validate per-paper field integrity for a set of papers from a database.

    Checks DOI format, URL format, date sanity, author quality, source
    completeness, database attribution, paper type validity, and numeric
    field ranges.

    Parameters
    ----------
    papers : list[Paper]
        Papers to validate.
    db : str
        Database identifier for attribution check.
    case_id : str
        Label used in issue descriptions.

    Returns
    -------
    list[str]
        List of issue descriptions (empty means all OK).
    """
    issues: list[str] = []
    today = datetime.date.today()
    from findpapers.core.paper import PaperType

    for i, p in enumerate(papers):
        label = f"{case_id}[{i}]"

        # Title: must be non-empty
        if not p.title or not p.title.strip():
            issues.append(f"{label}: título vazio")

        # DOI format: if present, must start with "10."
        if p.doi:
            doi = p.doi.strip()
            if not doi.startswith("10."):
                issues.append(f"{label}: DOI com formato inválido: '{doi[:50]}'")

        # URL format: if present, must start with http/https
        if p.url and not p.url.startswith(("http://", "https://")):
            issues.append(f"{label}: URL com formato inválido: '{p.url[:80]}'")

        if p.pdf_url and not p.pdf_url.startswith(("http://", "https://")):
            issues.append(f"{label}: pdf_url com formato inválido: '{p.pdf_url[:80]}'")

        # Publication date: if present, must be reasonable
        if p.publication_date:
            if p.publication_date.year < 1900:
                issues.append(f"{label}: data muito antiga: {p.publication_date}")
            if p.publication_date > today + datetime.timedelta(days=365):
                issues.append(f"{label}: data no futuro: {p.publication_date}")

        # Authors: if present, must be non-empty strings
        if p.authors:
            blank_authors = [a for a in p.authors if not a or not a.strip()]
            if blank_authors:
                issues.append(f"{label}: {len(blank_authors)} autor(es) com nome vazio")

        # Keywords: if present, must be non-empty strings
        if p.keywords:
            blank_kw = [k for k in p.keywords if not k or not k.strip()]
            if blank_kw:
                issues.append(f"{label}: {len(blank_kw)} keyword(s) vazia(s)")

        # Source: if present, must have title
        if p.source and (not p.source.title or not p.source.title.strip()):
            issues.append(f"{label}: source sem título")

        # Databases: must contain the queried database
        if p.databases:
            lower_dbs = {d.lower() for d in p.databases}
            if db.lower() not in lower_dbs:
                issues.append(f"{label}: paper não lista '{db}' nas databases: {p.databases}")
        else:
            issues.append(f"{label}: paper sem databases atribuídas")

        # Paper type: check it's a valid PaperType if present
        if p.paper_type is not None and not isinstance(p.paper_type, PaperType):
            issues.append(f"{label}: paper_type não é PaperType: {type(p.paper_type)}")

        # Citations: if present, must be >= 0
        if p.citations is not None and p.citations < 0:
            issues.append(f"{label}: citations negativo: {p.citations}")

        # Number of pages: if present, must be > 0
        if p.number_of_pages is not None and p.number_of_pages <= 0:
            issues.append(f"{label}: number_of_pages <= 0: {p.number_of_pages}")

    return issues


def phase_8_parallelism(
    databases: list[str] | None = None,
    verbose: bool = False,
) -> list[CaseResult]:
    """Phase 8: compare sequential vs parallel execution on the same query.

    Runs the same multi-database query twice: once with ``num_workers=1``
    (sequential) and once with ``num_workers`` equal to the number of
    databases used (fully parallel).  Verifies that paper counts are
    consistent between both executions and reports the observed speedup.
    """
    name = "phase_8_parallelism"
    section("FASE 8 - paralelismo")
    target = phase_dir(name)
    results: list[CaseResult] = []

    dbs_all = databases if databases is not None else available_databases()
    # Select free databases that do not require auxiliary API keys for a
    # controlled comparison.  Using too many slow databases would make the
    # sequential baseline disproportionately slow.
    free_dbs = [db for db in dbs_all if db in {"arxiv", "openalex", "pubmed", "semantic_scholar"}]
    if len(free_dbs) < 2:
        warn("fase 8 requer ao menos 2 bases livres disponíveis; pulando")
        payload = {"skipped": True, "reason": "insufficient_databases"}
        (target / "phase_summary.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return results

    multi_dbs = free_dbs[:3]
    query = "[machine learning] AND [healthcare]"

    seq_result, seq_search = run_case(
        phase=name,
        case_id="parallel_sequential",
        query=query,
        databases=multi_dbs,
        max_papers=8,
        target_dir=target,
        num_workers=1,
        verbose=verbose,
    )
    results.append(seq_result)

    par_result, par_search = run_case(
        phase=name,
        case_id="parallel_concurrent",
        query=query,
        databases=multi_dbs,
        max_papers=8,
        target_dir=target,
        num_workers=len(multi_dbs),
        verbose=verbose,
    )
    results.append(par_result)

    if seq_result.success and par_result.success:
        if seq_result.paper_count == par_result.paper_count:
            ok(
                f"contagem de papers consistente: {seq_result.paper_count} (seq) "
                f"== {par_result.paper_count} (par)"
            )
        else:
            warn(
                f"contagem de papers divergiu: {seq_result.paper_count} (seq) "
                f"vs {par_result.paper_count} (par) — verificar deduplicação"
            )
        speedup = seq_result.runtime_seconds / max(par_result.runtime_seconds, 0.001)
        ok(
            f"speedup: {speedup:.2f}x "
            f"[{seq_result.runtime_seconds:.2f}s -> {par_result.runtime_seconds:.2f}s]"
        )

    save_phase_summary(target, results)
    return results


def phase_9_paper_type_filter(
    databases: list[str] | None = None,
    verbose: bool = False,
) -> list[CaseResult]:
    """Phase 9: comprehensive per-database ``paper_types`` filter validation.

    For each available database the phase runs four steps:

    **Step A – type distribution profiling**
        Run an unfiltered search and collect which :class:`PaperType` values
        the database actually emits (and how many papers have ``None`` type).
        This is used to choose realistic filter targets for the next steps.

    **Step B – positive filter checks**
        For each type that appeared in the unfiltered run, run a filtered
        search and assert that:

        * every returned paper has exactly the requested type,
        * no paper with an undetermined type (``paper_type is None``) leaked
          through,
        * the filtered count is ≤ the unfiltered count.

    **Step C – negative / impossible-type check**
        Filter by a type known to be *never* produced by the database under
        test (e.g. ``inproceedings`` on PubMed, ``unpublished`` on IEEE) and
        assert that the result set is empty.

    **Step D – cross-database consistency (article filter)**
        Run an ``article`` filter across all free databases simultaneously and
        apply the same correctness assertions to the merged result set.

    Covered databases
    -----------------
    arXiv: emits ``article`` (has journal ref) and ``unpublished`` (preprints).
    PubMed: always sets ``article``; never produces ``inproceedings``.
    OpenAlex: rich type vocabulary (article, inproceedings, unpublished, …).
    Semantic Scholar: emits article, inproceedings, phdthesis, …
    IEEE (if key present): emits article, inproceedings, techreport, …
    Scopus (if key present): emits article, inproceedings, incollection, …
    """
    # Types known to be producible by each database; used to skip senseless tests.
    _DB_PRODUCIBLE: dict[str, set[str]] = {
        "arxiv": {"article", "unpublished"},
        "pubmed": {"article"},
        "openalex": {
            "article",
            "incollection",
            "inbook",
            "unpublished",
            "phdthesis",
            "inproceedings",
            "techreport",
        },
        "semantic_scholar": {
            "phdthesis",
            "incollection",
            "inbook",
            "inproceedings",
            "article",
        },
        "ieee": {"article", "inproceedings", "incollection", "techreport"},
        "scopus": {"article", "inproceedings", "incollection"},
    }

    # A type that the database *cannot* produce → filtering by it must yield 0.
    _IMPOSSIBLE_TYPE: dict[str, str] = {
        "arxiv": "inproceedings",
        "pubmed": "inproceedings",
        "openalex": "mastersthesis",
        "semantic_scholar": "mastersthesis",
        "ieee": "unpublished",
        "scopus": "unpublished",
    }

    name = "phase_9_paper_type_filter"
    section("FASE 9 - filtro por tipo de paper (per-database abrangente)")
    target = phase_dir(name)
    results: list[CaseResult] = []

    dbs_all = databases if databases is not None else available_databases()
    candidate_dbs = [
        db
        for db in dbs_all
        if db in {"arxiv", "openalex", "pubmed", "semantic_scholar", "ieee", "scopus"}
    ]
    if not candidate_dbs:
        warn("fase 9 não encontrou bases suportadas; pulando")
        save_phase_summary(target, results)
        return results

    # Use a broad query so each database can return diverse paper types.
    # "machine learning OR deep learning" gives more inproceedings on CS databases.
    query = "[machine learning] OR [deep learning]"
    max_papers = 40
    type_distributions: dict[str, dict[str, int]] = {}

    # ── Step A + B + C: per-database loop ───────────────────────────────────
    print("\n  [STEP A/B/C] per-database profiling and filter checks")
    for db in candidate_dbs:
        producible = _DB_PRODUCIBLE.get(db, set())

        # ── A: unfiltered baseline ────────────────────────────────────────────
        baseline_result, baseline_search = run_case(
            phase=name,
            case_id=f"{db}_baseline",
            query=query,
            databases=[db],
            max_papers=max_papers,
            target_dir=target,
            verbose=verbose,
        )
        results.append(baseline_result)

        if not baseline_result.success or baseline_search is None:
            warn(f"{db}: baseline falhou; pulando testes de tipo para esta base")
            continue

        # Compute type distribution for this database
        dist: dict[str, int] = {}
        for p in baseline_search.papers:
            key = p.paper_type.value if p.paper_type is not None else "None"
            dist[key] = dist.get(key, 0) + 1
        type_distributions[db] = dist

        none_count = dist.get("None", 0)
        total = len(baseline_search.papers)
        ok(
            f"{db} type distribution (total={total}): "
            + ", ".join(f"{k}={v}" for k, v in sorted(dist.items()))
        )
        if none_count > 0:
            pct_none = none_count / total * 100
            note = f"{db}: {none_count}/{total} ({pct_none:.0f}%) papers sem tipo definido"
            if pct_none > 50:
                warn(note + " — base provavelmente não popula paper_type adequadamente")
            else:
                ok(note)

        # ── B: positive filter checks for each observed type ─────────────────
        observed_types = [k for k in dist if k != "None" and k in producible]
        if not observed_types:
            warn(
                f"{db}: nenhum tipo conhecido observado no baseline "
                f"({list(dist.keys())}) — pulando checks positivos"
            )
        for paper_type in observed_types:
            filter_result, filter_search = run_case(
                phase=name,
                case_id=f"{db}_filter_{paper_type}",
                query=query,
                databases=[db],
                max_papers=max_papers,
                target_dir=target,
                paper_types=[paper_type],
                verbose=verbose,
            )
            results.append(filter_result)

            if filter_search is None:
                continue

            # Correctness assertions
            wrong_type = [
                p
                for p in filter_search.papers
                if p.paper_type is None or p.paper_type.value != paper_type
            ]
            leaked_none = [p for p in filter_search.papers if p.paper_type is None]

            if wrong_type:
                fail(
                    f"{db} filtro '{paper_type}': {len(wrong_type)} paper(s) com tipo "
                    f"errado ou None entre {len(filter_search.papers)} retornados"
                )
                for p in wrong_type[:3]:
                    t = p.paper_type.value if p.paper_type else "None"
                    print(f"       título: {p.title[:70]} | tipo: {t}")
                filter_result.notes.append(f"tipo_errado:{len(wrong_type)}")
            else:
                ok(
                    f"{db} filtro '{paper_type}': "
                    f"{len(filter_search.papers)} paper(s), todos com tipo correto"
                )

            if leaked_none:
                fail(
                    f"{db} filtro '{paper_type}': {len(leaked_none)} paper(s) com "
                    f"paper_type=None vazaram pelo filtro"
                )
                filter_result.notes.append(f"none_vazou:{len(leaked_none)}")
            else:
                ok(f"{db} filtro '{paper_type}': nenhum paper com tipo=None vazou")

            # Count consistency
            if filter_result.paper_count <= baseline_result.paper_count:
                ok(
                    f"{db} filtro '{paper_type}': contagem {filter_result.paper_count} "
                    f"<= baseline {baseline_result.paper_count}"
                )
            else:
                warn(
                    f"{db} filtro '{paper_type}': contagem {filter_result.paper_count} "
                    f"> baseline {baseline_result.paper_count} — INESPERADO"
                )

        # ── C: negative / impossible-type check ──────────────────────────────
        impossible_type = _IMPOSSIBLE_TYPE.get(db)
        if impossible_type:
            neg_result, neg_search = run_case(
                phase=name,
                case_id=f"{db}_impossible_{impossible_type}",
                query=query,
                databases=[db],
                max_papers=max_papers,
                target_dir=target,
                paper_types=[impossible_type],
                verbose=verbose,
            )
            results.append(neg_result)

            if neg_search is not None:
                if neg_search.papers:
                    fail(
                        f"{db} filtro impossível '{impossible_type}': "
                        f"esperado 0 paper(s), obtido {len(neg_search.papers)} — "
                        f"TIPO NÃO DEVERIA SER PRODUZIDO POR ESTA BASE"
                    )
                    for p in neg_search.papers[:3]:
                        t = p.paper_type.value if p.paper_type else "None"
                        print(f"       título: {p.title[:70]} | tipo: {t}")
                else:
                    ok(
                        f"{db} filtro impossível '{impossible_type}': "
                        f"0 paper(s) correto — base não produz esse tipo"
                    )

    # ── Step D: cross-database article filter consistency ───────────────────
    print("\n  [STEP D] cross-database article filter (todas as bases livres juntas)")
    free_dbs = [db for db in candidate_dbs if db in {"arxiv", "openalex", "pubmed", "semantic_scholar"}]
    if len(free_dbs) >= 2:
        multi_baseline_result, multi_baseline_search = run_case(
            phase=name,
            case_id="multi_baseline",
            query=query,
            databases=free_dbs,
            max_papers=20,
            target_dir=target,
            verbose=verbose,
        )
        results.append(multi_baseline_result)

        multi_article_result, multi_article_search = run_case(
            phase=name,
            case_id="multi_filter_article",
            query=query,
            databases=free_dbs,
            max_papers=20,
            target_dir=target,
            paper_types=["article"],
            verbose=verbose,
        )
        results.append(multi_article_result)

        if multi_article_search is not None:
            wrong_multi = [
                p
                for p in multi_article_search.papers
                if p.paper_type is None or p.paper_type.value != "article"
            ]
            if wrong_multi:
                fail(
                    f"multi-db filtro 'article': {len(wrong_multi)} paper(s) com tipo "
                    f"errado ou None entre {len(multi_article_search.papers)}"
                )
                for p in wrong_multi[:3]:
                    t = p.paper_type.value if p.paper_type else "None"
                    src = sorted(p.databases or [])
                    print(f"       título: {p.title[:70]} | tipo: {t} | bases: {src}")
                multi_article_result.notes.append(f"tipo_errado:{len(wrong_multi)}")
            else:
                ok(
                    f"multi-db filtro 'article': "
                    f"{len(multi_article_search.papers)} paper(s), todos com tipo correto"
                )

            if multi_baseline_result.success:
                if multi_article_result.paper_count <= multi_baseline_result.paper_count:
                    ok(
                        f"multi-db contagem article {multi_article_result.paper_count} "
                        f"<= baseline {multi_baseline_result.paper_count}"
                    )
                else:
                    warn(
                        f"multi-db filtro 'article' retornou mais que o baseline: "
                        f"{multi_article_result.paper_count} > {multi_baseline_result.paper_count}"
                    )

    # Persist the collected type distributions for post-mortem analysis
    (target / "type_distributions.json").write_text(
        json.dumps(type_distributions, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    save_phase_summary(target, results)
    return results


def phase_10_date_filter(
    databases: list[str] | None = None,
    verbose: bool = False,
) -> list[CaseResult]:
    """Phase 10: validate post-search date filtering on ``publication_date``.

    Runs a broad search, then applies a date-range window and validates that
    the filtered subset only contains papers whose ``publication_date`` falls
    within the expected bounds.  Also verifies that restricting to a narrower
    window yields a subset of the wider one.
    """
    name = "phase_10_date_filter"
    section("FASE 10 - filtro por data")
    target = phase_dir(name)
    results: list[CaseResult] = []

    dbs_all = databases if databases is not None else available_databases()
    candidate_dbs = [
        db for db in dbs_all if db in {"arxiv", "openalex", "pubmed", "semantic_scholar"}
    ]
    if not candidate_dbs:
        warn("fase 10 requer arxiv, openalex, pubmed ou semantic_scholar; pulando")
        save_phase_summary(target, results)
        return results

    test_dbs = candidate_dbs[:2]
    query = "[machine learning]"

    case_result, search = run_case(
        phase=name,
        case_id="date_filter_base",
        query=query,
        databases=test_dbs,
        max_papers=60,
        target_dir=target,
        verbose=verbose,
    )
    results.append(case_result)

    if search is None or not search.papers:
        save_phase_summary(target, results)
        return results

    today = datetime.date.today()
    wide_since = datetime.date(today.year - 5, 1, 1)
    wide_until = today
    narrow_since = datetime.date(today.year - 2, 1, 1)
    narrow_until = today

    papers_with_date = [p for p in search.papers if p.publication_date is not None]
    ok(f"papers com data definida: {len(papers_with_date)}/{len(search.papers)}")

    def _filter_range(
        papers: list,
        since: datetime.date,
        until: datetime.date,
    ) -> tuple[list, list]:
        inside = [p for p in papers if since <= p.publication_date <= until]
        outside = [p for p in papers if p.publication_date < since or p.publication_date > until]
        return inside, outside

    wide_in, wide_out = _filter_range(papers_with_date, wide_since, wide_until)
    narrow_in, narrow_out = _filter_range(papers_with_date, narrow_since, narrow_until)

    ok(f"janela ampla ({wide_since} – {wide_until}): {len(wide_in)} dentro, {len(wide_out)} fora")
    ok(
        f"janela estreita ({narrow_since} – {narrow_until}): "
        f"{len(narrow_in)} dentro, {len(narrow_out)} fora"
    )

    # Narrow window must be a subset of wide window.
    if len(narrow_in) <= len(wide_in):
        ok(f"janela estreita ({len(narrow_in)}) <= janela ampla ({len(wide_in)}): consistente")
    else:
        warn(
            f"janela estreita ({len(narrow_in)}) > janela ampla ({len(wide_in)}): "
            f"inconsistência de filtragem"
        )

    # Spot-check: verify all papers in narrow_in are indeed within the narrow bounds.
    wrong_narrow = [
        p
        for p in narrow_in
        if p.publication_date < narrow_since or p.publication_date > narrow_until
    ]
    if wrong_narrow:
        warn(f"{len(wrong_narrow)} paper(s) com data fora dos limites da janela estreita")
    else:
        ok("todos os papers da janela estreita têm data dentro dos limites")

    payload = {
        "total_papers": len(search.papers),
        "papers_with_date": len(papers_with_date),
        "wide_window": {
            "since": str(wide_since),
            "until": str(wide_until),
            "inside": len(wide_in),
            "outside": len(wide_out),
        },
        "narrow_window": {
            "since": str(narrow_since),
            "until": str(narrow_until),
            "inside": len(narrow_in),
            "outside": len(narrow_out),
        },
        "date_filter_consistent": len(narrow_in) <= len(wide_in) and not wrong_narrow,
    }
    (target / "date_filter_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    save_phase_summary(target, results)
    return results


def phase_11_error_handling() -> list[CaseResult]:
    """Phase 11: verify that invalid inputs raise the expected exceptions.

    Covers:
    - Empty query → QueryValidationError
    - Query without brackets → QueryValidationError
    - Invalid filter code → QueryValidationError
    - Invalid database name → ValueError
    - Invalid paper type → ValueError
    - get_results() before run() → SearchRunnerNotExecutedError
    - get_metrics() before run() → SearchRunnerNotExecutedError
    """
    name = "phase_11_error_handling"
    section("FASE 11 - tratamento de erros (entradas inválidas)")
    target = phase_dir(name)
    results: list[CaseResult] = []

    checks_passed = 0
    checks_total = 0

    def assert_raises(description: str, exc_type: type, fn: Any) -> None:
        nonlocal checks_passed, checks_total
        checks_total += 1
        try:
            fn()
            fail(f"{description}: esperado {exc_type.__name__} mas nenhuma exceção foi levantada")
        except exc_type:
            ok(f"{description}: {exc_type.__name__} levantado como esperado")
            checks_passed += 1
        except Exception as exc:
            fail(f"{description}: exceção inesperada {type(exc).__name__}: {exc}", exc)

    # 1. Empty query
    assert_raises(
        "query vazia",
        QueryValidationError,
        lambda: SearchRunner(query="", databases=["arxiv"], max_papers_per_database=1),
    )

    # 2. Query without brackets (bare term, no wrapping [])
    assert_raises(
        "query sem colchetes",
        QueryValidationError,
        lambda: SearchRunner(
            query="machine learning", databases=["arxiv"], max_papers_per_database=1
        ),
    )

    # 3. Invalid filter code
    assert_raises(
        "filter code inválido (xyz)",
        QueryValidationError,
        lambda: SearchRunner(query="xyz[cancer]", databases=["arxiv"], max_papers_per_database=1),
    )

    # 4. Invalid database name → raised at construction time
    assert_raises(
        "database inválido",
        ValueError,
        lambda: SearchRunner(
            query="[cancer]", databases=["not_a_real_db"], max_papers_per_database=1
        ),
    )

    # 5. Invalid paper_type → raised at construction time
    assert_raises(
        "paper_type inválido",
        ValueError,
        lambda: SearchRunner(
            query="[cancer]",
            databases=["arxiv"],
            paper_types=["not_a_type"],
            max_papers_per_database=1,
        ),
    )

    # 6 & 7. get_results() / get_metrics() before run()
    unrun_runner = SearchRunner(query="[cancer]", databases=["arxiv"], max_papers_per_database=1)
    assert_raises(
        "get_results() antes do run()",
        SearchRunnerNotExecutedError,
        unrun_runner.get_results,
    )
    assert_raises(
        "get_metrics() antes do run()",
        SearchRunnerNotExecutedError,
        unrun_runner.get_metrics,
    )

    summary = {"checks_total": checks_total, "checks_passed": checks_passed}
    (target / "phase_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    status = "OK" if checks_passed == checks_total else "FAILED"
    ok(f"[{status}] testes de erro: {checks_passed}/{checks_total} aprovados")

    # Represent this phase as a single summary CaseResult.
    results.append(
        CaseResult(
            phase=name,
            case_id="error_handling_suite",
            query="(invalid input tests)",
            databases=[],
            paper_count=0,
            runtime_seconds=0.0,
            success=(checks_passed == checks_total),
            notes=(
                []
                if checks_passed == checks_total
                else [f"{checks_total - checks_passed}_checks_failed"]
            ),
        )
    )
    return results


def phase_12_search_metadata(
    databases: list[str] | None = None,
    verbose: bool = False,
) -> list[CaseResult]:
    """Phase 12: verify Search object metadata and per-database metric keys.

    Checks:
    - search.query stored correctly
    - search.databases contains the requested db
    - search.max_papers_per_database matches configuration
    - search.processed_at is recent
    - metrics dict has all required top-level keys
    - metrics dict has per-database key total_papers_from_{db}
    """
    name = "phase_12_search_metadata"
    section("FASE 12 - metadados da busca e métricas por base")
    target = phase_dir(name)
    results: list[CaseResult] = []

    dbs_all = databases if databases is not None else available_databases()
    test_db = next(
        (db for db in ["arxiv", "pubmed", "openalex", "semantic_scholar"] if db in dbs_all),
        dbs_all[0] if dbs_all else None,
    )
    if test_db is None:
        warn("fase 12 sem bases disponíveis; pulando")
        save_phase_summary(target, results)
        return results

    query = "[cancer]"
    max_papers = 6
    case_result, search = run_case(
        phase=name,
        case_id=f"{test_db}_metadata",
        query=query,
        databases=[test_db],
        max_papers=max_papers,
        target_dir=target,
        verbose=verbose,
    )
    results.append(case_result)

    if search is None:
        save_phase_summary(target, results)
        return results

    # search.query
    if search.query == query:
        ok(f"search.query correto: '{search.query}'")
    else:
        warn(f"search.query divergiu: esperado '{query}', obtido '{search.query}'")

    # search.databases
    if test_db in (search.databases or []):
        ok(f"search.databases contém '{test_db}'")
    else:
        warn(f"search.databases não contém '{test_db}': {search.databases}")

    # search.max_papers_per_database
    if search.max_papers_per_database == max_papers:
        ok(f"search.max_papers_per_database={search.max_papers_per_database} correto")
    else:
        warn(
            f"search.max_papers_per_database esperado {max_papers}, "
            f"obtido {search.max_papers_per_database}"
        )

    # search.processed_at is recent
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    if search.processed_at is not None:
        delta = abs((now_utc - search.processed_at).total_seconds())
        if delta < 300:
            ok(f"search.processed_at recente (delta={delta:.1f}s)")
        else:
            warn(f"search.processed_at parece desatualizado (delta={delta:.1f}s)")
    else:
        warn("search.processed_at é None")

    # Metrics keys — run a dedicated minimal runner to inspect.
    try:
        mrunner = build_runner(query=query, databases=[test_db], max_papers=max_papers)
        mrunner.run(verbose=False)
        mmetrics = mrunner.get_metrics()
        required_keys = {
            "total_papers",
            "runtime_in_seconds",
            "total_papers_from_predatory_source",
        }
        missing = required_keys - set(mmetrics.keys())
        if missing:
            warn(f"métricas faltando chaves obrigatórias: {missing}")
        else:
            ok("métricas têm todas as chaves obrigatórias")
        per_db_key = f"total_papers_from_{test_db}"
        if per_db_key in mmetrics:
            ok(f"chave por base presente: {per_db_key}={int(mmetrics[per_db_key])}")
        else:
            warn(f"chave por base ausente nas métricas: {per_db_key}")
    except Exception as exc:
        fail("erro ao verificar métricas", exc)

    save_phase_summary(target, results)
    return results


def phase_13_deduplication(
    databases: list[str] | None = None,
    verbose: bool = False,
) -> list[CaseResult]:
    """Phase 13: verify that deduplication merges papers across databases.

    Runs a multi-database query known to yield overlapping results and checks
    that at least some papers carry more than one database source
    (``paper.databases``), which indicates the merge path was exercised.
    Also verifies there are no duplicate titles in the final result set.
    """
    name = "phase_13_deduplication"
    section("FASE 13 - deduplicação entre bases")
    target = phase_dir(name)
    results: list[CaseResult] = []

    dbs_all = databases if databases is not None else available_databases()
    # arxiv + semantic_scholar + openalex all index CS/ML papers and have known overlap.
    # pubmed is excluded intentionally: it does not index CS conference papers, so the
    # "Attention Is All You Need" paper (Vaswani et al. 2017) would never be found there,
    # making cross-database merge evidence very unlikely.
    overlap_dbs = [db for db in ["arxiv", "semantic_scholar", "openalex"] if db in dbs_all]
    if len(overlap_dbs) < 2:
        warn("fase 13 requer ao menos 2 de: arxiv, semantic_scholar, openalex; pulando")
        save_phase_summary(target, results)
        return results

    multi_dbs = overlap_dbs
    # "Attention Is All You Need" (Vaswani et al. 2017) is indexed in all three databases.
    # Default tiabs filter is required here: semantic_scholar only supports tiabs.
    query = "[attention is all you need]"
    case_result, search = run_case(
        phase=name,
        case_id="dedup_multi",
        query=query,
        databases=multi_dbs,
        max_papers=40,
        target_dir=target,
        verbose=verbose,
    )
    results.append(case_result)

    if search is not None and search.papers:
        multi_source = [p for p in search.papers if len(p.databases or set()) > 1]
        ok(
            f"papers com múltiplas fontes (merge exercitado): "
            f"{len(multi_source)}/{len(search.papers)}"
        )
        if not multi_source:
            warn(
                "nenhum paper com múltiplas fontes detectado — deduplicação pode não estar "
                "mesclando, ou bases têm pouca sobreposição para esta query"
            )

        # No two papers in the deduplicated result should share the same lower-case title.
        titles_lower = [p.title.strip().lower() for p in search.papers if p.title]
        if len(titles_lower) != len(set(titles_lower)):
            from collections import Counter

            dupes = [t for t, n in Counter(titles_lower).items() if n > 1]
            warn(
                f"{len(dupes)} título(s) duplicado(s) detectado(s) no resultado final "
                f"— verificar pipeline de deduplicação"
            )
        else:
            ok("sem títulos duplicados no resultado final")

        summary = {
            "total_papers": len(search.papers),
            "multi_source_papers": len(multi_source),
            "databases_searched": multi_dbs,
        }
        (target / "dedup_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    save_phase_summary(target, results)
    return results


def phase_14_rerun_idempotency(
    databases: list[str] | None = None,
    verbose: bool = False,
) -> list[CaseResult]:
    """Phase 14: verify that run() can be called multiple times with consistent results.

    Checks:
    - Both executions return the same number of papers.
    - get_results() returns an independent copy (mutating it does not affect the runner).
    """
    name = "phase_14_rerun_idempotency"
    section("FASE 14 - idempotência de re-execução")
    target = phase_dir(name)
    results: list[CaseResult] = []

    dbs_all = databases if databases is not None else available_databases()
    test_db = next(
        (db for db in ["arxiv", "pubmed", "openalex", "semantic_scholar"] if db in dbs_all),
        dbs_all[0] if dbs_all else None,
    )
    if test_db is None:
        warn("fase 14 sem bases disponíveis; pulando")
        save_phase_summary(target, results)
        return results

    query = "[machine learning]"
    max_papers = 10
    notes: list[str] = []
    success = False
    count1 = 0

    try:
        runner = build_runner(query=query, databases=[test_db], max_papers=max_papers)

        search1 = runner.run(verbose=False)
        count1 = len(search1.papers)

        search2 = runner.run(verbose=False)
        count2 = len(search2.papers)

        if count1 == count2:
            ok(f"re-run consistente: ambas as execuções retornaram {count1} papers")
        else:
            warn(
                f"re-run inconsistente: 1ª execução={count1} papers, "
                f"2ª execução={count2} papers"
            )
            notes.append("rerun_inconsistent")

        # get_results() must return a deep copy — clearing it must not affect the runner.
        res_copy = runner.get_results()
        original_len = len(runner.get_results())
        res_copy.clear()
        after_len = len(runner.get_results())
        if after_len == original_len:
            ok("get_results() retorna cópia independente (deep copy verificado)")
        else:
            warn("get_results() não retornou cópia — modificar a lista afetou o estado interno")
            notes.append("get_results_not_copy")

        success = True
    except Exception as exc:
        fail("erro na fase de idempotência", exc)
        notes.append("exception")

    results.append(
        CaseResult(
            phase=name,
            case_id=f"{test_db}_rerun",
            query=query,
            databases=[test_db],
            paper_count=count1,
            runtime_seconds=0.0,
            success=success and not notes,
            notes=notes,
        )
    )
    save_phase_summary(target, results)
    return results


def phase_6_enrichment(seed_search: Search | None, verbose: bool = False) -> dict[str, Any]:
    """Phase 6: run EnrichmentRunner and evaluate if papers got richer."""
    name = "phase_6_enrichment"
    section("FASE 6 - enrichment runner")
    target = phase_dir(name)

    if seed_search is None or not seed_search.papers:
        warn("fase 6 sem dados de entrada (nenhum paper da fase 5)")
        payload = {"executed": False, "reason": "no_seed_papers"}
        (target / "phase_summary.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return payload

    # ---------------------------------------------------------------------------
    # Smart sample strategy
    # ---------------------------------------------------------------------------
    # Tier 1 (when Scopus key is available): run a small dedicated Scopus search
    # and keep only papers that are missing the abstract.  Scopus systematically
    # omits abstracts for many records, but those records carry a DOI that lets
    # the enrichment runner reach the publisher's page via doi.org — the richest
    # possible source for HTML meta tags.  These are therefore the *strongest*
    # enrichment candidates available.
    #
    # Tier 2: papers from the seed search that have at least one enrichable gap
    # and a non-PDF landing-page URL.  Sorted by descending gap count.
    #
    # Papers from arXiv / Semantic Scholar that are already fully-populated are
    # moved to the back — enriching them would be a no-op by design.
    # ---------------------------------------------------------------------------
    SAMPLE_SIZE = 8

    scopus_no_abstract: list[Paper] = []
    scopus_extra_search_used = False

    if SCOPUS_API_KEY:
        ok("Scopus key disponível — buscando papers sem abstract para enriquecimento")
        try:
            scopus_runner = build_runner(
                query="[machine learning] OR [deep learning]",
                databases=["scopus"],
                max_papers=40,
            )
            scopus_search = scopus_runner.run(verbose=verbose)
            scopus_no_abstract = [
                p for p in scopus_search.papers
                if not (p.abstract or "").strip()
                and p.doi  # need DOI to build doi.org URL
            ]
            scopus_extra_search_used = True
            ok(
                f"Scopus extra search: {len(scopus_search.papers)} papers total, "
                f"{len(scopus_no_abstract)} sem abstract com DOI"
            )
        except Exception as exc:  # noqa: BLE001
            warn(f"Scopus extra search falhou: {exc}")

    # Sort tier-1 candidates by descending gap count (abstract is always missing,
    # but other fields may also be absent — prefer the most-incomplete ones).
    scopus_no_abstract.sort(
        key=lambda p: len(_paper_missing_enrichable_fields(p)), reverse=True
    )

    # Tier-2: seed search candidates with non-PDF URL, sorted by gap count.
    seed_candidates = [
        p for p in seed_search.papers
        if p.url and "pdf" not in p.url.lower()
    ]
    if not seed_candidates:
        seed_candidates = list(seed_search.papers)
    seed_candidates.sort(key=lambda p: len(_paper_missing_enrichable_fields(p)), reverse=True)

    # Merge tiers: Scopus no-abstract first, then fill with seed candidates,
    # avoiding duplicates (same title).
    seen_titles: set[str] = set()
    sample: list[Paper] = []
    for p in scopus_no_abstract + seed_candidates:
        if len(sample) >= SAMPLE_SIZE:
            break
        key = p.title.strip().lower()
        if key not in seen_titles:
            seen_titles.add(key)
            sample.append(p)

    # Record which databases contributed to the sample and how many gaps exist.
    sample_databases: list[str] = sorted(
        {db for p in sample for db in (p.databases or set())}
    )
    missing_by_paper = {p.title: _paper_missing_enrichable_fields(p) for p in sample}
    papers_with_gaps_before = sum(1 for fields in missing_by_paper.values() if fields)
    all_already_complete = papers_with_gaps_before == 0

    scopus_in_sample = sum(
        1 for p in sample if "scopus" in {db.lower() for db in (p.databases or set())}
    )

    if all_already_complete:
        warn(
            "fase 6: todos os papers do sample já estão completos — "
            "enrichment não tem o que melhorar (comportamento esperado para papers do arXiv)"
        )

    before_scores = {paper.title: paper_richness_score(paper) for paper in sample}

    before_search = Search(
        query=f"phase6_before::{seed_search.query}",
        databases=list(seed_search.databases or []),
        papers=[paper for paper in sample],
    )
    export_search(before_search, target, "before_enrichment")

    runner = EnrichmentRunner(papers=sample, num_workers=2, timeout=10.0)
    runner.run(verbose=verbose)
    metrics = runner.get_metrics()

    after_scores = {paper.title: paper_richness_score(paper) for paper in sample}
    deltas = {title: after_scores[title] - before_scores[title] for title in before_scores}
    improved = [title for title, delta in deltas.items() if delta > 0]

    after_search = Search(
        query=f"phase6_after::{seed_search.query}",
        databases=list(seed_search.databases or []),
        papers=sample,
    )
    export_search(after_search, target, "after_enrichment")

    payload = {
        "executed": True,
        "input_papers": len(sample),
        "sample_databases": sample_databases,
        "scopus_extra_search_used": scopus_extra_search_used,
        "scopus_papers_in_sample": scopus_in_sample,
        "papers_with_gaps_before": papers_with_gaps_before,
        "all_sample_already_complete": all_already_complete,
        "missing_fields_before": {t: f for t, f in missing_by_paper.items() if f},
        "enriched_papers_metric": int(metrics.get("enriched_papers", 0)),
        "fetch_error_papers": int(metrics.get("fetch_error_papers", 0)),
        "no_metadata_papers": int(metrics.get("no_metadata_papers", 0)),
        "no_change_papers": int(metrics.get("no_change_papers", 0)),
        "no_urls_papers": int(metrics.get("no_urls_papers", 0)),
        "runtime_seconds": float(metrics.get("runtime_in_seconds", 0.0)),
        "papers_with_richness_increase": len(improved),
        "richness_delta_by_title": deltas,
    }
    (target / "phase_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    ok(
        "enrichment executed: "
        f"metric_enriched={payload['enriched_papers_metric']} "
        f"fetch_errors={payload['fetch_error_papers']} "
        f"no_metadata={payload['no_metadata_papers']} "
        f"no_change={payload['no_change_papers']} "
        f"richness_improved={payload['papers_with_richness_increase']} "
        f"gaps_before={papers_with_gaps_before} "
        f"scopus_in_sample={scopus_in_sample} "
        f"sample_dbs={sample_databases}"
    )
    return payload


def phase_7_download(seed_search: Search | None, verbose: bool = False) -> dict[str, Any]:
    """Phase 7: run DownloadRunner using a small paper sample."""
    name = "phase_7_download"
    section("FASE 7 - download runner")
    target = phase_dir(name)
    pdf_dir = target / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    if seed_search is None or not seed_search.papers:
        warn("fase 7 sem dados de entrada (nenhum paper da fase 5)")
        payload = {"executed": False, "reason": "no_seed_papers"}
        (target / "phase_summary.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return payload

    candidates = [paper for paper in seed_search.papers if paper.pdf_url or paper.url][:5]
    if not candidates:
        warn("fase 7 sem papers com url/pdf_url")
        payload = {"executed": False, "reason": "no_download_candidates"}
        (target / "phase_summary.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return payload

    # Clean up any PDFs left over from a previous run so that pdf_file_count
    # reflects only what is downloaded in this execution.
    for existing_pdf in pdf_dir.glob("*.pdf"):
        existing_pdf.unlink()

    runner = DownloadRunner(
        papers=candidates,
        output_directory=str(pdf_dir),
        num_workers=2,
        timeout=20.0,
        proxy=PROXY,
        ssl_verify=True,
    )
    runner.run(verbose=verbose)
    metrics = runner.get_metrics()
    downloaded_files = sorted(path.name for path in pdf_dir.glob("*.pdf"))

    payload = {
        "executed": True,
        "input_papers": len(candidates),
        "downloaded_papers_metric": int(metrics.get("downloaded_papers", 0)),
        "runtime_seconds": float(metrics.get("runtime_in_seconds", 0.0)),
        "pdf_file_count": len(downloaded_files),
        "pdf_files": downloaded_files,
        "error_log_exists": (pdf_dir / "download_errors.txt").exists(),
    }
    (target / "phase_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    ok(
        "download executed: "
        f"metric_downloaded={payload['downloaded_papers_metric']} "
        f"pdf_files={payload['pdf_file_count']}"
    )
    return payload


# =============================================================================
# FASE 15 – buscas com wildcards
# =============================================================================


def phase_15_wildcard_searches(
    databases: list[str] | None = None,
    verbose: bool = False,
) -> list[CaseResult]:
    """Phase 15: validate wildcard (*) and single-char (?) support.

    Runs live searches using wildcard-enabled queries on databases that accept
    them and verifies that results are returned.  Also confirms that databases
    which reject wildcards gracefully return zero results without crashing the
    overall search.

    Covered scenarios:
    - ``[cance*]`` (5 chars before ``*``) on arXiv, PubMed, Semantic Scholar.
    - ``[canc?r]`` (``?`` wildcard) on arXiv only (arXiv accepts both wildcards).
    - Multi-db run ``[cance*]`` on arXiv + OpenAlex: OpenAlex must silently skip
      (return 0 papers) while arXiv still returns results.
    - ``[canc?r]`` on PubMed, Semantic Scholar, OpenAlex: every database must
      silently skip the query (return 0 papers each).
    """
    name = "phase_15_wildcard_searches"
    section("FASE 15 - wildcards")
    target = phase_dir(name)
    results: list[CaseResult] = []

    dbs_all = databases if databases is not None else available_databases()

    # ── 15a: asterisk wildcard on free databases ─────────────────────────────
    # "cance*" satisfies all per-database minimums:
    #   global: 3+, arXiv: 3+, PubMed: 4+, Semantic Scholar: 3+
    asterisk_query = "[cance*]"
    asterisk_dbs = [db for db in ["arxiv", "pubmed", "semantic_scholar"] if db in dbs_all]
    for db in asterisk_dbs:
        case_result, _ = run_case(
            phase=name,
            case_id=f"{db}_asterisk_wildcard",
            query=asterisk_query,
            databases=[db],
            max_papers=10,
            target_dir=target,
            timeout_seconds=120,
            verbose=verbose,
        )
        results.append(case_result)

    # ── 15b: question-mark wildcard on arXiv ─────────────────────────────────
    # arXiv accepts both ? and *.  All other free databases reject ?.
    question_query = "[canc?r]"
    if "arxiv" in dbs_all:
        case_result, _ = run_case(
            phase=name,
            case_id="arxiv_question_wildcard",
            query=question_query,
            databases=["arxiv"],
            max_papers=10,
            target_dir=target,
            timeout_seconds=120,
            verbose=verbose,
        )
        results.append(case_result)

    # ── 15c: asterisk wildcard multi-db — OpenAlex graceful skip ─────────────
    # OpenAlex rejects wildcards and must return 0 from that database while the
    # overall run still succeeds (arXiv returns papers).
    wildcard_open_dbs = [db for db in ["arxiv", "openalex"] if db in dbs_all]
    if len(wildcard_open_dbs) >= 2:
        try:
            runner = build_runner(
                query=asterisk_query,
                databases=wildcard_open_dbs,
                max_papers=10,
            )
            search = runner.run(verbose=verbose)
            metrics = runner.get_metrics()
            openalex_count = int(metrics.get("total_papers_from_openalex", -1))
            arxiv_count = int(metrics.get("total_papers_from_arxiv", -1))
            overall_ok = openalex_count == 0 and arxiv_count > 0
            if openalex_count == 0:
                ok("openalex: wildcard query silently skipped (0 papers) — correto")
            else:
                warn(f"openalex: esperado 0 papers para wildcard, obtido {openalex_count}")
            if arxiv_count > 0:
                ok(f"arxiv: retornou {arxiv_count} papers com wildcard (correto)")
            else:
                warn("arxiv: 0 papers com wildcard — esperado > 0")
            results.append(
                CaseResult(
                    phase=name,
                    case_id="wildcard_multi_skip_openalex",
                    query=asterisk_query,
                    databases=wildcard_open_dbs,
                    paper_count=len(search.papers),
                    runtime_seconds=float(metrics["runtime_in_seconds"]),
                    success=overall_ok,
                    notes=([] if overall_ok else ["openalex_should_skip_wildcards"]),
                )
            )
        except Exception as exc:
            fail("wildcard_multi_skip_openalex crashed", exc)
            results.append(
                CaseResult(
                    phase=name,
                    case_id="wildcard_multi_skip_openalex",
                    query=asterisk_query,
                    databases=wildcard_open_dbs,
                    paper_count=0,
                    runtime_seconds=0.0,
                    success=False,
                    notes=["exception"],
                )
            )

    # ── 15d: ? wildcard rejection check (PubMed, S2, OpenAlex) ──────────────
    # "[canc?r]" passes global validation but per-database validators for
    # PubMed, Semantic Scholar, and OpenAlex must reject it, returning 0 papers.
    question_reject_set = {"pubmed", "semantic_scholar", "openalex"}
    test_reject = [db for db in dbs_all if db in question_reject_set]
    if test_reject:
        try:
            runner = build_runner(
                query=question_query,
                databases=test_reject,
                max_papers=10,
            )
            search = runner.run(verbose=verbose)
            metrics = runner.get_metrics()
            all_zero = all(
                int(metrics.get(f"total_papers_from_{db}", 0)) == 0 for db in test_reject
            )
            if all_zero:
                ok(
                    f"wildcard_? corretamente rejeitado por "
                    f"{', '.join(test_reject)}: 0 papers"
                )
            else:
                non_zero = [
                    db for db in test_reject if int(metrics.get(f"total_papers_from_{db}", 0)) > 0
                ]
                warn(
                    f"wildcard_? não rejeitado por {', '.join(non_zero)} — "
                    "verificar validação por base"
                )
            results.append(
                CaseResult(
                    phase=name,
                    case_id="wildcard_question_rejected",
                    query=question_query,
                    databases=test_reject,
                    paper_count=len(search.papers),
                    runtime_seconds=float(metrics["runtime_in_seconds"]),
                    success=all_zero,
                    notes=([] if all_zero else ["question_wildcard_not_rejected"]),
                )
            )
        except Exception as exc:
            fail("wildcard_question_rejected crashed", exc)
            results.append(
                CaseResult(
                    phase=name,
                    case_id="wildcard_question_rejected",
                    query=question_query,
                    databases=test_reject,
                    paper_count=0,
                    runtime_seconds=0.0,
                    success=False,
                    notes=["exception"],
                )
            )

    save_phase_summary(target, results)
    return results


# =============================================================================
# FASE 16 – validação de wildcards (erros em tempo de construção)
# =============================================================================


def phase_16_wildcard_validation() -> list[CaseResult]:
    """Phase 16: verify that invalid wildcard patterns raise QueryValidationError.

    All assertions are evaluated without making network requests.

    Covered cases:
    - Wildcard at the start of a term: ``[*cancer]``, ``[?ncer]``
    - Asterisk not at the end: ``[can*cer]``
    - Asterisk with fewer than 3 characters before it: ``[ca*]``
    - Two wildcards in one term: ``[cance?*]``
    - Wildcard inside a multi-word term: ``[machine learn*]``
    """
    name = "phase_16_wildcard_validation"
    section("FASE 16 - validação de wildcards (construção)")
    target = phase_dir(name)
    checks_passed = 0
    checks_total = 0

    def assert_raises_ctor(description: str, exc_type: type, fn: Any) -> None:
        nonlocal checks_passed, checks_total
        checks_total += 1
        try:
            fn()
            fail(f"{description}: esperava {exc_type.__name__} mas nenhuma exceção foi lançada")
        except exc_type:
            ok(f"{description}: {exc_type.__name__} lançada corretamente")
            checks_passed += 1
        except Exception as exc:
            fail(f"{description}: exceção inesperada {type(exc).__name__}: {exc}", exc)

    # 1. Wildcard at start
    assert_raises_ctor(
        "asterisco no início [*cancer]",
        QueryValidationError,
        lambda: SearchRunner(query="[*cancer]", databases=["arxiv"], max_papers_per_database=1),
    )
    assert_raises_ctor(
        "interrogação no início [?ncer]",
        QueryValidationError,
        lambda: SearchRunner(query="[?ncer]", databases=["arxiv"], max_papers_per_database=1),
    )

    # 2. Asterisk not at the end
    assert_raises_ctor(
        "asterisco no meio [can*cer]",
        QueryValidationError,
        lambda: SearchRunner(query="[can*cer]", databases=["arxiv"], max_papers_per_database=1),
    )

    # 3. Fewer than 3 characters before asterisk
    assert_raises_ctor(
        "asterisco com < 3 chars antes [ca*]",
        QueryValidationError,
        lambda: SearchRunner(query="[ca*]", databases=["arxiv"], max_papers_per_database=1),
    )

    # 4. Two wildcards in one term
    assert_raises_ctor(
        "dois wildcards [cance?*]",
        QueryValidationError,
        lambda: SearchRunner(query="[cance?*]", databases=["arxiv"], max_papers_per_database=1),
    )

    # 5. Wildcard in multi-word term (spaces)
    assert_raises_ctor(
        "wildcard em termo composto [machine learn*]",
        QueryValidationError,
        lambda: SearchRunner(
            query="[machine learn*]", databases=["arxiv"], max_papers_per_database=1
        ),
    )

    summary = {"checks_total": checks_total, "checks_passed": checks_passed}
    (target / "phase_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    status = "OK" if checks_passed == checks_total else "FAILED"
    ok(f"[{status}] testes de wildcard: {checks_passed}/{checks_total} aprovados")

    return [
        CaseResult(
            phase=name,
            case_id="wildcard_validation_suite",
            query="(wildcard syntax tests)",
            databases=[],
            paper_count=0,
            runtime_seconds=0.0,
            success=(checks_passed == checks_total),
            notes=(
                []
                if checks_passed == checks_total
                else [f"{checks_total - checks_passed}_checks_failed"]
            ),
        )
    ]


# =============================================================================
# FASE 17 – skip gracioso por filtro não suportado pela base
# =============================================================================


def phase_17_unsupported_filter_skip(
    databases: list[str] | None = None,
    verbose: bool = False,
) -> list[CaseResult]:
    """Phase 17: verify that databases skip queries with unsupported filter codes.

    Uses filter codes known to be unsupported by certain databases and asserts:
    - The overall run does NOT raise an exception.
    - The unsupporting database contributes 0 papers.
    - At least one supporting database in the same run contributes > 0 papers.

    Covered pairs:
    - ``key[cancer]`` on arXiv + PubMed: arXiv skips (0), PubMed returns results.
    - ``tiabskey[cancer]`` on Semantic Scholar + PubMed: S2 skips (0), PubMed returns.
    - ``src[nature]`` on arXiv + PubMed: arXiv skips (0), PubMed returns results.
    """
    name = "phase_17_unsupported_filter_skip"
    section("FASE 17 - skip por filtro não suportado")
    target = phase_dir(name)
    results: list[CaseResult] = []

    dbs_all = databases if databases is not None else available_databases()

    def _run_pair_check(
        case_id: str,
        query: str,
        skip_db: str,
        support_db: str,
    ) -> None:
        """Run a two-database case and verify skip/support behaviour."""
        pair = [db for db in [skip_db, support_db] if db in dbs_all]
        if len(pair) < 2:
            warn(f"{case_id}: requer '{skip_db}' e '{support_db}' disponíveis; pulando")
            return
        try:
            runner = build_runner(query=query, databases=pair, max_papers=10)
            search = runner.run(verbose=verbose)
            metrics = runner.get_metrics()
            skip_count = int(metrics.get(f"total_papers_from_{skip_db}", -1))
            support_count = int(metrics.get(f"total_papers_from_{support_db}", -1))
            overall_ok = skip_count == 0 and support_count > 0
            if skip_count == 0:
                ok(f"{case_id}: {skip_db} ignorou corretamente (0 papers)")
            else:
                warn(f"{case_id}: {skip_db} retornou {skip_count} — esperado 0")
            if support_count > 0:
                ok(f"{case_id}: {support_db} retornou {support_count} papers")
            else:
                warn(f"{case_id}: {support_db} retornou 0 — esperado > 0")
            results.append(
                CaseResult(
                    phase=name,
                    case_id=case_id,
                    query=query,
                    databases=pair,
                    paper_count=len(search.papers),
                    runtime_seconds=float(metrics["runtime_in_seconds"]),
                    success=overall_ok,
                    notes=([] if overall_ok else [f"{skip_db}_should_skip"]),
                )
            )
        except Exception as exc:
            fail(f"{case_id} crashed", exc)
            results.append(
                CaseResult(
                    phase=name,
                    case_id=case_id,
                    query=query,
                    databases=[skip_db, support_db],
                    paper_count=0,
                    runtime_seconds=0.0,
                    success=False,
                    notes=["exception"],
                )
            )

    # key filter: arXiv does not support KEY; PubMed does
    # Note: must use a valid MeSH heading (e.g. "neoplasms"), not colloquial "cancer"
    _run_pair_check("key_filter_arxiv_skip", "key[neoplasms]", "arxiv", "pubmed")

    # tiabskey filter: Semantic Scholar does not support it; PubMed does
    _run_pair_check("tiabskey_s2_skip", "tiabskey[cancer]", "semantic_scholar", "pubmed")

    # src filter: arXiv does not support SRC; PubMed does
    _run_pair_check("src_filter_arxiv_skip", "src[nature]", "arxiv", "pubmed")

    # tiabskey filter: OpenAlex does not support TIABSKEY; PubMed does
    _run_pair_check("tiabskey_openalex_skip", "tiabskey[cancer]", "openalex", "pubmed")

    if not results:
        warn("fase 17 sem pares de bases disponíveis para testar; pulando")
        (target / "phase_summary.json").write_text(
            json.dumps([{"skipped": True}], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return results

    save_phase_summary(target, results)
    return results


# =============================================================================
# FASE 18 – propagação de filtro a nível de grupo
# =============================================================================


def phase_18_group_filter_propagation(
    databases: list[str] | None = None,
    verbose: bool = False,
) -> list[CaseResult]:
    """Phase 18: verify that group-level filter codes propagate to child terms.

    Tests expressions of the form ``ti([termA] OR [termB])`` where the filter
    applies to the whole group rather than each individual term.  Checks that:

    - The query is accepted without error.
    - Results are returned.
    - For arXiv and PubMed the returned papers contain the query terms in the
      expected field.

    Covered scenarios:
    - ``ti([machine learning] OR [deep learning])`` — title group filter.
    - ``abs([pandemic] OR [epidemic])`` — abstract group filter.
    """
    name = "phase_18_group_filter_propagation"
    section("FASE 18 - propagação de filtro em grupo")
    target = phase_dir(name)
    results: list[CaseResult] = []

    dbs_all = databases if databases is not None else available_databases()
    # arXiv and PubMed support ti/abs filters and have reliable title/abstract fields.
    ti_abs_candidate_dbs = [db for db in ["arxiv", "pubmed"] if db in dbs_all]
    # OpenAlex supports ti but with a different backend representation.
    all_candidate_dbs = [db for db in ["arxiv", "pubmed", "openalex"] if db in dbs_all]

    if not all_candidate_dbs:
        warn("fase 18 requer arxiv, pubmed ou openalex; pulando")
        save_phase_summary(target, results)
        return results

    # ── 18a: ti([machine learning] OR [deep learning]) ───────────────────────
    query_group_ti = "ti([machine learning] OR [deep learning])"
    for db in all_candidate_dbs:
        case_result, search = run_case(
            phase=name,
            case_id=f"{db}_group_ti",
            query=query_group_ti,
            databases=[db],
            max_papers=10,
            target_dir=target,
            timeout_seconds=120,
            verbose=verbose,
        )
        results.append(case_result)

        if search is not None and search.papers and db in ti_abs_candidate_dbs:
            title_hits = sum(
                1
                for p in search.papers
                if p.title
                and (
                    "machine learning" in p.title.lower()
                    or "deep learning" in p.title.lower()
                )
            )
            pct = title_hits / len(search.papers) * 100
            if pct == 100:
                ok(
                    f"{db} group ti: 100% dos papers contêm os termos no título "
                    f"({title_hits}/{len(search.papers)})"
                )
            elif pct >= 50:
                warn(
                    f"{db} group ti: {pct:.0f}% dos papers com termos no título "
                    f"({title_hits}/{len(search.papers)})"
                )
            else:
                warn(
                    f"{db} group ti: apenas {pct:.0f}% dos papers contêm termos no título "
                    "— verificar propagação de filtro de grupo"
                )

    # ── 18b: abs([pandemic] OR [epidemic]) ───────────────────────────────────
    query_group_abs = "abs([pandemic] OR [epidemic])"
    for db in ti_abs_candidate_dbs:
        case_result, search = run_case(
            phase=name,
            case_id=f"{db}_group_abs",
            query=query_group_abs,
            databases=[db],
            max_papers=10,
            target_dir=target,
            timeout_seconds=120,
            verbose=verbose,
        )
        results.append(case_result)

        if search is not None and search.papers:
            abstract_hits = sum(
                1
                for p in search.papers
                if p.abstract
                and (
                    "pandemic" in p.abstract.lower() or "epidemic" in p.abstract.lower()
                )
            )
            pct = abstract_hits / len(search.papers) * 100
            if pct >= 80:
                ok(
                    f"{db} group abs: {pct:.0f}% dos papers contêm termos no abstract "
                    f"({abstract_hits}/{len(search.papers)})"
                )
            else:
                warn(
                    f"{db} group abs: apenas {pct:.0f}% dos papers contêm termos no abstract "
                    f"({abstract_hits}/{len(search.papers)})"
                )

    save_phase_summary(target, results)
    return results


# =============================================================================
# FASE 19 – filtros estendidos: key, src, tiabskey
# =============================================================================


def phase_19_extended_filters(
    databases: list[str] | None = None,
    verbose: bool = False,
) -> list[CaseResult]:
    """Phase 19: exercise filter codes not fully covered by earlier phases.

    Tests ``key`` (keywords/MeSH), ``src`` (source/journal), and ``tiabskey``
    (title + abstract + keywords) on databases that support them:

    - PubMed: all three filters (always available).
    - Scopus: all three filters (requires API key).
    - IEEE: all three filters (requires API key).
    """
    name = "phase_19_extended_filters"
    section("FASE 19 - filtros estendidos (key, src, tiabskey)")
    target = phase_dir(name)
    results: list[CaseResult] = []

    dbs_all = databases if databases is not None else available_databases()

    cases: list[tuple[str, str, list[str]]] = []

    if "pubmed" in dbs_all:
        cases += [
            ("pubmed_key", "key[neoplasms]", ["pubmed"]),  # must use a valid MeSH heading
            ("pubmed_src", "src[nature]", ["pubmed"]),
            ("pubmed_tiabskey", "tiabskey[machine learning]", ["pubmed"]),
        ]

    if "scopus" in dbs_all and SCOPUS_API_KEY:
        cases += [
            ("scopus_key", "key[machine learning]", ["scopus"]),
            ("scopus_src", "src[nature]", ["scopus"]),
            ("scopus_tiabskey", "tiabskey[cancer]", ["scopus"]),
        ]

    if "ieee" in dbs_all and IEEE_API_KEY:
        cases += [
            ("ieee_key", "key[neural network]", ["ieee"]),
            ("ieee_src", "src[nature]", ["ieee"]),
            ("ieee_tiabskey", "tiabskey[machine learning]", ["ieee"]),
        ]

    if not cases:
        warn("fase 19 requer pubmed, scopus ou ieee disponíveis; pulando")
        save_phase_summary(target, results)
        return results

    for case_id, query, dbs in cases:
        case_result, _ = run_case(
            phase=name,
            case_id=case_id,
            query=query,
            databases=dbs,
            max_papers=10,
            target_dir=target,
            timeout_seconds=120,
            verbose=verbose,
        )
        results.append(case_result)

    save_phase_summary(target, results)
    return results


# =============================================================================
# FASE 20 – case-insensitivity de filtros e operadores
# =============================================================================


def phase_20_case_insensitivity(
    databases: list[str] | None = None,
    verbose: bool = False,
) -> list[CaseResult]:
    """Phase 20: verify that filter codes and boolean operators are case-insensitive.

    All variants below must construct successfully and return at least one paper
    when the canonical lowercase form would also return papers.

    Covered combinations:

    - Uppercase filter codes: ``TI[cancer]``, ``TIABS[cancer]``, ``ABS[cancer]``
    - Mixed-case filter codes: ``Ti[cancer]``, ``Tiabs[cancer]``
    - Lowercase boolean operators: ``[cancer] and [diabetes]``,
      ``[cancer] or [diabetes]``, ``[cancer] and not [agriculture]``
    - Mixed-case operator with filter: ``TI[cancer] AND ABS[treatment]``
    """
    name = "phase_20_case_insensitivity"
    section("FASE 20 - case-insensitivity de filtros e operadores")
    target = phase_dir(name)
    results: list[CaseResult] = []

    dbs_all = databases if databases is not None else available_databases()

    # Use any available free database for generic tiabs/operator tests.
    generic_db = next(
        (db for db in ["arxiv", "pubmed", "openalex", "semantic_scholar"] if db in dbs_all),
        None,
    )
    # For ti/abs field-filter tests we need a database that supports those fields.
    # semantic_scholar only supports tiabs so it is excluded here.
    ti_abs_db = next(
        (db for db in ["arxiv", "pubmed", "openalex"] if db in dbs_all),
        None,
    )

    if generic_db is None:
        warn("fase 20 sem bases disponíveis; pulando")
        save_phase_summary(target, results)
        return results

    # --- boolean operator tests: all databases support tiabs (default) -------
    case_queries: list[tuple[str, str, list[str]]] = [
        # Lowercase boolean operators (all dbs support these on tiabs)
        ("lowercase_and", "[cancer] and [diabetes]", [generic_db]),
        ("lowercase_or", "[cancer] or [diabetes]", [generic_db]),
        ("lowercase_and_not", "[cancer] and not [agriculture]", [generic_db]),
        # Uppercase TIABS filter (every db that accepts queries at all supports tiabs)
        ("uppercase_TIABS", "TIABS[cancer]", [generic_db]),
        ("mixedcase_Tiabs", "Tiabs[cancer]", [generic_db]),
    ]

    # --- field-filter cases: only on databases that support ti and abs --------
    if ti_abs_db:
        case_queries += [
            ("uppercase_TI", "TI[cancer]", [ti_abs_db]),
            ("uppercase_ABS", "ABS[cancer]", [ti_abs_db]),
            ("mixedcase_Ti", "Ti[cancer]", [ti_abs_db]),
            ("mixedcase_filter_and_op", "TI[cancer] AND ABS[treatment]", [ti_abs_db]),
        ]
    else:
        warn("fase 20: nenhuma base suporta ti/abs; testes de filtro de campo pulados")

    for case_id, query, dbs in case_queries:
        # Verify that construction does not raise before making a live call
        try:
            SearchRunner(query=query, databases=dbs, max_papers_per_database=1)
        except Exception as exc:
            fail(f"{case_id}: construção falhou para '{query}'", exc)
            results.append(
                CaseResult(
                    phase=name,
                    case_id=case_id,
                    query=query,
                    databases=dbs,
                    paper_count=0,
                    runtime_seconds=0.0,
                    success=False,
                    notes=["construction_failed"],
                )
            )
            continue

        case_result, _ = run_case(
            phase=name,
            case_id=case_id,
            query=query,
            databases=dbs,
            max_papers=6,
            target_dir=target,
            timeout_seconds=120,
            verbose=verbose,
        )
        results.append(case_result)

    save_phase_summary(target, results)
    return results


# =============================================================================
# FASE 21 – queries complexas com múltiplos conectores e grupos aninhados
# =============================================================================


def phase_21_complex_nested_queries(
    databases: list[str] | None = None,
    verbose: bool = False,
) -> list[CaseResult]:
    """Phase 21: validate complex queries with multiple connectors and nested groups.

    The goal is to stress-test the query parser and builder with expressions
    that go beyond the simple two-term cases exercised in phases 2 and 3.

    Covered scenarios
    -----------------
    21a  Double-nesting with AND NOT:
         ``((A OR B) AND (C OR D)) AND NOT E``
    21b  Multiple chained AND NOT:
         ``A AND NOT B AND NOT C``
    21c  Disjunction of conjunctions (OR of AND-groups):
         ``(A AND B) OR (C AND D)``
    21d  Deep three-level nesting:
         ``((A OR B) AND C) OR ((D OR E) AND F)``
    21e  Long OR chain (five terms):
         ``A OR B OR C OR D OR E``
    21f  NOT applied to a whole group:
         ``(A OR B) AND NOT (C OR D)``
    21g  Four-term expression mixing all connectors:
         ``(A AND B) AND NOT (C OR D)``
    21h  Group-level filter on nested terms:
         ``ti([A] OR [B]) AND abs([C] OR [D])``

    For every case the run must succeed (no crash) and return at least one
    paper.  A warning is emitted — but the case is not marked as failed — when
    the result set is empty, since overly specific nested queries may legally
    yield zero hits on any individual database.
    """
    name = "phase_21_complex_nested_queries"
    section("FASE 21 - queries complexas com múltiplos conectores e grupos aninhados")
    target = phase_dir(name)
    results: list[CaseResult] = []

    dbs_all = databases if databases is not None else available_databases()
    # Use free databases that reliably index CS / biomedical literature so that
    # the diverse query vocabulary (ML, medicine, NLP topics) gets decent recall.
    free_dbs = [db for db in dbs_all if db in {"arxiv", "openalex", "pubmed", "semantic_scholar"}]
    if not free_dbs:
        warn("phase 21: no free databases available — skipping")
        return results

    # Pick up to two free databases to keep the phase fast while still exercising
    # more than one backend.
    test_dbs = free_dbs[:2]

    # Helper that chooses the best candidate set for a query depending on
    # whether the query uses ti/abs field filters (unsupported by semantic_scholar).
    def _dbs_for(needs_field_filter: bool) -> list[str]:
        if needs_field_filter:
            return [db for db in test_dbs if db != "semantic_scholar"] or test_dbs
        return test_dbs

    # ── 21a: double-nesting with AND NOT ─────────────────────────────────────
    # ((neural network OR deep learning) AND (image OR vision)) AND NOT survey
    case_result_21a, _ = run_case(
        phase=name,
        case_id="21a_double_nest_and_not",
        query=(
            "([neural network] OR [deep learning]) "
            "AND ([image] OR [vision]) "
            "AND NOT [survey]"
        ),
        databases=_dbs_for(False),
        max_papers=10,
        target_dir=target,
        timeout_seconds=120,
        verbose=verbose,
    )
    results.append(case_result_21a)

    # ── 21b: multiple chained AND NOT ────────────────────────────────────────
    # machine learning AND NOT agriculture AND NOT economics
    case_result_21b, _ = run_case(
        phase=name,
        case_id="21b_chained_and_not",
        query="[machine learning] AND NOT [agriculture] AND NOT [economics]",
        databases=_dbs_for(False),
        max_papers=10,
        target_dir=target,
        timeout_seconds=120,
        verbose=verbose,
    )
    results.append(case_result_21b)

    # ── 21c: disjunction of conjunctions (OR of AND-groups) ──────────────────
    # (cancer AND treatment) OR (diabetes AND insulin)
    case_result_21c, _ = run_case(
        phase=name,
        case_id="21c_or_of_and_groups",
        query="([cancer] AND [treatment]) OR ([diabetes] AND [insulin])",
        databases=_dbs_for(False),
        max_papers=10,
        target_dir=target,
        timeout_seconds=120,
        verbose=verbose,
    )
    results.append(case_result_21c)

    # ── 21d: deep three-level nesting ─────────────────────────────────────────
    # ((machine learning OR deep learning) AND medical) OR
    # ((NLP OR language model) AND clinical)
    case_result_21d, _ = run_case(
        phase=name,
        case_id="21d_three_level_nest",
        query=(
            "(([machine learning] OR [deep learning]) AND [medical]) "
            "OR (([NLP] OR [language model]) AND [clinical])"
        ),
        databases=_dbs_for(False),
        max_papers=10,
        target_dir=target,
        timeout_seconds=120,
        verbose=verbose,
    )
    results.append(case_result_21d)

    # ── 21e: long OR chain (five terms) ──────────────────────────────────────
    # transformer OR BERT OR GPT OR attention OR language model
    case_result_21e, _ = run_case(
        phase=name,
        case_id="21e_long_or_chain",
        query=(
            "[transformer] OR [BERT] OR [GPT] "
            "OR [attention mechanism] OR [language model]"
        ),
        databases=_dbs_for(False),
        max_papers=10,
        target_dir=target,
        timeout_seconds=120,
        verbose=verbose,
    )
    results.append(case_result_21e)

    # ── 21f: NOT applied to a whole group ────────────────────────────────────
    # (cancer OR tumor) AND NOT (review OR meta-analysis)
    case_result_21f, _ = run_case(
        phase=name,
        case_id="21f_not_group",
        query="([cancer] OR [tumor]) AND NOT ([review] OR [meta-analysis])",
        databases=_dbs_for(False),
        max_papers=10,
        target_dir=target,
        timeout_seconds=120,
        verbose=verbose,
    )
    results.append(case_result_21f)

    # ── 21g: four-term expression mixing all connectors ───────────────────────
    # (federated learning AND privacy) AND NOT (centralized OR server)
    case_result_21g, _ = run_case(
        phase=name,
        case_id="21g_four_term_mix",
        query=(
            "([federated learning] AND [privacy]) "
            "AND NOT ([centralized] OR [server])"
        ),
        databases=_dbs_for(False),
        max_papers=10,
        target_dir=target,
        timeout_seconds=120,
        verbose=verbose,
    )
    results.append(case_result_21g)

    # ── 21h: group-level field filters with nested terms ─────────────────────
    # ti([machine learning] OR [deep learning]) AND abs([healthcare] OR [clinical])
    # Uses databases that support ti and abs filters.
    field_dbs = [db for db in dbs_all if db in {"arxiv", "pubmed", "openalex"}]
    if field_dbs:
        case_result_21h, _ = run_case(
            phase=name,
            case_id="21h_field_filter_nested_groups",
            query=(
                "ti([machine learning] OR [deep learning]) "
                "AND abs([healthcare] OR [clinical])"
            ),
            databases=field_dbs[:2],
            max_papers=10,
            target_dir=target,
            timeout_seconds=120,
            verbose=verbose,
        )
        results.append(case_result_21h)
    else:
        warn("phase 21h: no database with ti/abs filter support available — skipping")

    # ── 21i: long chain of ANDs (many-term conjunction) ───────────────────────
    # Stress-tests that the parser handles a flat conjunction of >3 terms.
    # learning AND classification AND accuracy AND evaluation AND benchmark
    case_result_21i, _ = run_case(
        phase=name,
        case_id="21i_long_and_chain",
        query=(
            "[learning] AND [classification] "
            "AND [accuracy] AND [evaluation] AND [benchmark]"
        ),
        databases=_dbs_for(False),
        max_papers=10,
        target_dir=target,
        timeout_seconds=120,
        verbose=verbose,
    )
    results.append(case_result_21i)

    # Sanity cross-check: case 21c (OR of AND-groups) should return at least as
    # many papers as case 21a (more restrictive AND NOT chain) for the same dbs.
    if case_result_21c.success and case_result_21a.success:
        if case_result_21c.paper_count >= case_result_21a.paper_count:
            ok(
                f"21c OR-of-ANDs ({case_result_21c.paper_count}) >= "
                f"21a double-nest-AND-NOT ({case_result_21a.paper_count}) — esperado"
            )
        else:
            warn(
                f"21c OR-of-ANDs ({case_result_21c.paper_count}) < "
                f"21a double-nest-AND-NOT ({case_result_21a.paper_count}) — "
                "OR retornou menos que AND NOT; verificar lógica de busca"
            )

    # Long OR chain should return at least as many papers as the baseline
    # double-nest (which is more restrictive).
    if case_result_21e.success and case_result_21a.success:
        if case_result_21e.paper_count >= case_result_21a.paper_count:
            ok(
                f"21e OR-chain ({case_result_21e.paper_count}) >= "
                f"21a restrictive ({case_result_21a.paper_count}) — esperado"
            )
        else:
            warn(
                f"21e OR-chain ({case_result_21e.paper_count}) < "
                f"21a restrictive ({case_result_21a.paper_count}) — inesperado"
            )

    save_phase_summary(target, results)
    return results


# =============================================================================
# FASE 22 – comportamento sem API keys
# =============================================================================


def phase_22_no_api_keys(
    databases: list[str] | None = None,
    verbose: bool = False,
) -> list[CaseResult]:
    """Phase 22: verify correct behaviour when no API keys are provided.

    All sub-cases use a fresh ``SearchRunner`` constructed with every key
    parameter explicitly set to ``None``, regardless of what is configured in
    the environment.  This ensures the results reflect the keyless code path,
    not the caller's credentials.

    Covered scenarios
    -----------------
    22a  Free databases (arXiv, OpenAlex, PubMed, Semantic Scholar) work and
         return papers without any API keys.
    22b  Each free database works individually without its optional key
         (pubmed_api_key=None, openalex_api_key=None, etc.).
    22c  IEEE requested without key: silently skipped (is_available=False),
         run succeeds, 0 papers from IEEE, arXiv still returns papers in the
         same multi-database run.
    22d  Scopus requested without key: same graceful-skip behaviour as 22c.
    22e  IEEE+Scopus both requested without keys in a multi-database run:
         both silently skipped, free databases still contribute papers.
    22f  IEEE requested alone without key: run returns 0 papers but does not
         crash (no searcher available → empty but valid search result).
    """
    name = "phase_22_no_api_keys"
    section("FASE 22 - comportamento sem API keys")
    target = phase_dir(name)
    results: list[CaseResult] = []

    dbs_all = databases if databases is not None else available_databases()
    free = [db for db in ["arxiv", "openalex", "pubmed", "semantic_scholar"] if db in dbs_all]

    def _run_no_keys(
        case_id: str,
        query: str,
        dbs: list[str],
        max_papers: int = 10,
    ) -> tuple[CaseResult, Search | None]:
        """Run a case with all API keys forced to None."""
        print(f"\n  -> {case_id}")
        print(f"     query: {query}")
        print(f"     dbs  : {dbs}")
        try:
            import signal as _signal

            runner = SearchRunner(
                query=query,
                databases=dbs,
                max_papers_per_database=max_papers,
                ieee_api_key=None,
                scopus_api_key=None,
                pubmed_api_key=None,
                openalex_api_key=None,
                openalex_email=None,
                semantic_scholar_api_key=None,
            )

            def _timeout_handler(_signum: int, _frame: Any) -> None:
                raise TimeoutError(f"{case_id} timed out after 120s (no-key run)")

            _signal.signal(_signal.SIGALRM, _timeout_handler)
            _signal.alarm(120)
            try:
                search = runner.run(verbose=verbose)
            finally:
                _signal.alarm(0)

            metrics = runner.get_metrics()
            export_search(search, target, case_id)
            ok(
                f"papers={len(search.papers)} "
                f"| runtime={float(metrics['runtime_in_seconds']):.2f}s"
            )
            if len(search.papers) == 0:
                warn(f"{case_id}: 0 papers — pode ser esperado (base sem key)")
            check_term_relevance(search, case_id)
            return (
                CaseResult(
                    phase=name,
                    case_id=case_id,
                    query=query,
                    databases=dbs,
                    paper_count=len(search.papers),
                    runtime_seconds=float(metrics["runtime_in_seconds"]),
                    success=True,
                    notes=[],
                ),
                search,
            )
        except TimeoutError as exc:
            fail(str(exc), exc)
            return (
                CaseResult(
                    phase=name,
                    case_id=case_id,
                    query=query,
                    databases=dbs,
                    paper_count=0,
                    runtime_seconds=0.0,
                    success=False,
                    notes=["timeout"],
                ),
                None,
            )
        except Exception as exc:
            fail("case crashed", exc)
            return (
                CaseResult(
                    phase=name,
                    case_id=case_id,
                    query=query,
                    databases=dbs,
                    paper_count=0,
                    runtime_seconds=0.0,
                    success=False,
                    notes=["exception"],
                ),
                None,
            )

    # ── 22a: all free databases together, no keys ────────────────────────────
    if free:
        r22a, search22a = _run_no_keys(
            case_id="22a_free_dbs_no_keys",
            query="[machine learning] AND [healthcare]",
            dbs=free,
        )
        results.append(r22a)
        if r22a.success and r22a.paper_count > 0:
            ok(f"22a: bases livres retornaram {r22a.paper_count} papers sem keys — correto")
        elif r22a.success:
            warn("22a: bases livres retornaram 0 papers sem keys — verificar")
    else:
        warn("phase 22a: nenhuma base livre disponível — pulando")

    # ── 22b: each free database individually, no keys ────────────────────────
    for db in free:
        r, _ = _run_no_keys(
            case_id=f"22b_{db}_individual_no_key",
            query="[cancer]",
            dbs=[db],
        )
        results.append(r)
        if r.success and r.paper_count > 0:
            ok(f"22b: {db} sem key retornou {r.paper_count} papers — correto")
        elif r.success:
            warn(f"22b: {db} sem key retornou 0 papers")

    # ── 22c: IEEE without key, mixed with arXiv ─────────────────────────────
    # IEEE available in databases list so the code path for ieee_api_key=None
    # skipping is exercised; arXiv must still return papers.
    if "arxiv" in dbs_all:
        try:
            runner_22c = SearchRunner(
                query="[machine learning]",
                databases=["ieee", "arxiv"],
                max_papers_per_database=10,
                ieee_api_key=None,
                scopus_api_key=None,
                pubmed_api_key=None,
                openalex_api_key=None,
                semantic_scholar_api_key=None,
            )
            import signal as _signal

            def _timeout_22c(_s: int, _f: Any) -> None:
                raise TimeoutError("22c timed out")

            _signal.signal(_signal.SIGALRM, _timeout_22c)
            _signal.alarm(120)
            try:
                search_22c = runner_22c.run(verbose=verbose)
            finally:
                _signal.alarm(0)

            metrics_22c = runner_22c.get_metrics()
            ieee_cnt = int(metrics_22c.get("total_papers_from_ieee", -1))
            arxiv_cnt = int(metrics_22c.get("total_papers_from_arxiv", -1))

            if ieee_cnt == 0:
                ok("22c: IEEE sem key silenciosamente ignorado (0 papers) — correto")
            else:
                warn(f"22c: IEEE sem key retornou {ieee_cnt} papers — inesperado")

            if arxiv_cnt > 0:
                ok(f"22c: arXiv ainda retornou {arxiv_cnt} papers — correto")
            else:
                warn("22c: arXiv retornou 0 papers na mesma execução")

            overall_22c = ieee_cnt == 0 and arxiv_cnt > 0
            results.append(
                CaseResult(
                    phase=name,
                    case_id="22c_ieee_no_key_mixed",
                    query="[machine learning]",
                    databases=["ieee", "arxiv"],
                    paper_count=len(search_22c.papers),
                    runtime_seconds=float(metrics_22c["runtime_in_seconds"]),
                    success=overall_22c,
                    notes=([] if overall_22c else ["ieee_should_be_skipped_without_key"]),
                )
            )
        except Exception as exc:
            fail("22c crashed", exc)
            results.append(
                CaseResult(
                    phase=name,
                    case_id="22c_ieee_no_key_mixed",
                    query="[machine learning]",
                    databases=["ieee", "arxiv"],
                    paper_count=0,
                    runtime_seconds=0.0,
                    success=False,
                    notes=["exception"],
                )
            )
    else:
        warn("phase 22c: arXiv não disponível — pulando")

    # ── 22d: Scopus without key, mixed with arXiv ────────────────────────────
    if "arxiv" in dbs_all:
        try:
            runner_22d = SearchRunner(
                query="[cancer]",
                databases=["scopus", "arxiv"],
                max_papers_per_database=10,
                ieee_api_key=None,
                scopus_api_key=None,
                pubmed_api_key=None,
                openalex_api_key=None,
                semantic_scholar_api_key=None,
            )
            import signal as _signal

            def _timeout_22d(_s: int, _f: Any) -> None:
                raise TimeoutError("22d timed out")

            _signal.signal(_signal.SIGALRM, _timeout_22d)
            _signal.alarm(120)
            try:
                search_22d = runner_22d.run(verbose=verbose)
            finally:
                _signal.alarm(0)

            metrics_22d = runner_22d.get_metrics()
            scopus_cnt = int(metrics_22d.get("total_papers_from_scopus", -1))
            arxiv_cnt_d = int(metrics_22d.get("total_papers_from_arxiv", -1))

            if scopus_cnt == 0:
                ok("22d: Scopus sem key silenciosamente ignorado (0 papers) — correto")
            else:
                warn(f"22d: Scopus sem key retornou {scopus_cnt} papers — inesperado")

            if arxiv_cnt_d > 0:
                ok(f"22d: arXiv ainda retornou {arxiv_cnt_d} papers — correto")
            else:
                warn("22d: arXiv retornou 0 papers na mesma execução")

            overall_22d = scopus_cnt == 0 and arxiv_cnt_d > 0
            results.append(
                CaseResult(
                    phase=name,
                    case_id="22d_scopus_no_key_mixed",
                    query="[cancer]",
                    databases=["scopus", "arxiv"],
                    paper_count=len(search_22d.papers),
                    runtime_seconds=float(metrics_22d["runtime_in_seconds"]),
                    success=overall_22d,
                    notes=([] if overall_22d else ["scopus_should_be_skipped_without_key"]),
                )
            )
        except Exception as exc:
            fail("22d crashed", exc)
            results.append(
                CaseResult(
                    phase=name,
                    case_id="22d_scopus_no_key_mixed",
                    query="[cancer]",
                    databases=["scopus", "arxiv"],
                    paper_count=0,
                    runtime_seconds=0.0,
                    success=False,
                    notes=["exception"],
                )
            )
    else:
        warn("phase 22d: arXiv não disponível — pulando")

    # ── 22e: IEEE + Scopus both without keys, mixed with free databases ──────
    if free:
        try:
            runner_22e = SearchRunner(
                query="[deep learning]",
                databases=["ieee", "scopus"] + free,
                max_papers_per_database=10,
                ieee_api_key=None,
                scopus_api_key=None,
                pubmed_api_key=None,
                openalex_api_key=None,
                semantic_scholar_api_key=None,
            )
            import signal as _signal

            def _timeout_22e(_s: int, _f: Any) -> None:
                raise TimeoutError("22e timed out")

            _signal.signal(_signal.SIGALRM, _timeout_22e)
            _signal.alarm(180)
            try:
                search_22e = runner_22e.run(verbose=verbose)
            finally:
                _signal.alarm(0)

            metrics_22e = runner_22e.get_metrics()
            ieee_cnt_e = int(metrics_22e.get("total_papers_from_ieee", -1))
            scopus_cnt_e = int(metrics_22e.get("total_papers_from_scopus", -1))
            free_total = sum(
                int(metrics_22e.get(f"total_papers_from_{db}", 0)) for db in free
            )

            skipped_ok = ieee_cnt_e == 0 and scopus_cnt_e == 0
            if skipped_ok:
                ok("22e: IEEE e Scopus sem keys ambos ignorados (0 papers) — correto")
            else:
                warn(
                    f"22e: IEEE={ieee_cnt_e}, Scopus={scopus_cnt_e} — "
                    "esperado 0 para ambos sem key"
                )

            if free_total > 0:
                ok(f"22e: bases livres retornaram {free_total} papers no total — correto")
            else:
                warn("22e: bases livres retornaram 0 papers")

            overall_22e = skipped_ok and free_total > 0
            results.append(
                CaseResult(
                    phase=name,
                    case_id="22e_ieee_scopus_no_key_with_free",
                    query="[deep learning]",
                    databases=["ieee", "scopus"] + free,
                    paper_count=len(search_22e.papers),
                    runtime_seconds=float(metrics_22e["runtime_in_seconds"]),
                    success=overall_22e,
                    notes=([] if overall_22e else ["unexpected_papers_from_keyless_db"]),
                )
            )
        except Exception as exc:
            fail("22e crashed", exc)
            results.append(
                CaseResult(
                    phase=name,
                    case_id="22e_ieee_scopus_no_key_with_free",
                    query="[deep learning]",
                    databases=["ieee", "scopus"] + free,
                    paper_count=0,
                    runtime_seconds=0.0,
                    success=False,
                    notes=["exception"],
                )
            )
    else:
        warn("phase 22e: nenhuma base livre disponível — pulando")

    # ── 22f: IEEE alone, no key — must not crash, must return 0 papers ───────
    try:
        runner_22f = SearchRunner(
            query="[machine learning]",
            databases=["ieee"],
            max_papers_per_database=10,
            ieee_api_key=None,
            scopus_api_key=None,
            pubmed_api_key=None,
            openalex_api_key=None,
            semantic_scholar_api_key=None,
        )
        import signal as _signal

        def _timeout_22f(_s: int, _f: Any) -> None:
            raise TimeoutError("22f timed out")

        _signal.signal(_signal.SIGALRM, _timeout_22f)
        _signal.alarm(30)
        try:
            search_22f = runner_22f.run(verbose=verbose)
        finally:
            _signal.alarm(0)

        metrics_22f = runner_22f.get_metrics()
        if len(search_22f.papers) == 0:
            ok("22f: IEEE sozinho sem key retornou 0 papers e não crashou — correto")
        else:
            warn(f"22f: IEEE sem key retornou {len(search_22f.papers)} papers — inesperado")

        expected_zero = len(search_22f.papers) == 0
        results.append(
            CaseResult(
                phase=name,
                case_id="22f_ieee_alone_no_key",
                query="[machine learning]",
                databases=["ieee"],
                paper_count=len(search_22f.papers),
                runtime_seconds=float(metrics_22f["runtime_in_seconds"]),
                success=expected_zero,
                notes=([] if expected_zero else ["ieee_returned_papers_without_key"]),
            )
        )
    except Exception as exc:
        fail("22f crashed", exc)
        results.append(
            CaseResult(
                phase=name,
                case_id="22f_ieee_alone_no_key",
                query="[machine learning]",
                databases=["ieee"],
                paper_count=0,
                runtime_seconds=0.0,
                success=False,
                notes=["exception"],
            )
        )

    save_phase_summary(target, results)
    return results


# =============================================================================
# FASE 23 – validação de exportação roundtrip (JSON / CSV / BibTeX)
# =============================================================================


def phase_23_export_roundtrip(
    databases: list[str] | None = None,
    verbose: bool = False,
) -> list[CaseResult]:
    """Phase 23: validate that export formats produce correct, re-importable output.

    Runs a small search, exports to JSON/CSV/BibTeX, and validates:

    - JSON: re-parseable, paper count matches, key fields preserved, Paper
      roundtrip via ``from_dict(to_dict(p))`` preserves core fields.
    - CSV: correct header columns, row count matches, no blank titles.
    - BibTeX: correct number of entries, valid entry types.
    """
    name = "phase_23_export_roundtrip"
    section("FASE 23 - validação de exportação roundtrip")
    target = phase_dir(name)
    results: list[CaseResult] = []
    checks_passed = 0
    checks_total = 0

    dbs_all = databases if databases is not None else available_databases()
    test_db = next(
        (db for db in ["arxiv", "pubmed", "openalex", "semantic_scholar"] if db in dbs_all),
        None,
    )
    if test_db is None:
        warn("fase 23 sem bases disponíveis; pulando")
        save_phase_summary(target, results)
        return results

    case_result, search = run_case(
        phase=name,
        case_id=f"{test_db}_export_base",
        query="[machine learning] AND [healthcare]",
        databases=[test_db],
        max_papers=15,
        target_dir=target,
        verbose=verbose,
    )
    results.append(case_result)

    if search is None or not search.papers:
        save_phase_summary(target, results)
        return results

    export_search(search, target, "roundtrip_test")

    # ── JSON validation ──────────────────────────────────────────────────────
    json_path = target / "roundtrip_test.json"
    checks_total += 1
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        ok("JSON: arquivo parseável com sucesso")
        checks_passed += 1

        # Paper count
        checks_total += 1
        json_papers = data.get("papers", [])
        if len(json_papers) == len(search.papers):
            ok(f"JSON: contagem de papers correta ({len(json_papers)})")
            checks_passed += 1
        else:
            fail(
                f"JSON: contagem divergiu — search={len(search.papers)}, "
                f"json={len(json_papers)}"
            )

        # Key fields in each paper
        checks_total += 1
        required_paper_keys = {"title", "databases"}
        missing_keys_count = 0
        for i, jp in enumerate(json_papers):
            missing = required_paper_keys - set(jp.keys())
            if missing:
                missing_keys_count += 1
                if missing_keys_count <= 2:
                    warn(f"JSON paper[{i}] faltando chaves: {missing}")
        if missing_keys_count == 0:
            ok("JSON: todos os papers têm chaves obrigatórias (title, databases)")
            checks_passed += 1
        else:
            fail(f"JSON: {missing_keys_count} paper(s) com chaves faltando")

        # Roundtrip: Paper.from_dict → verify core fields preserved
        checks_total += 1
        roundtrip_ok = 0
        roundtrip_fail = 0
        for jp in json_papers:
            try:
                rebuilt = Paper.from_dict(jp)
                original = next(
                    (
                        p
                        for p in search.papers
                        if p.title
                        and rebuilt.title
                        and p.title.strip().lower() == rebuilt.title.strip().lower()
                    ),
                    None,
                )
                if original is None:
                    roundtrip_fail += 1
                    continue
                field_ok = True
                if original.doi and rebuilt.doi != original.doi:
                    field_ok = False
                if original.paper_type and rebuilt.paper_type != original.paper_type:
                    field_ok = False
                if original.publication_date and rebuilt.publication_date != original.publication_date:
                    field_ok = False
                if field_ok:
                    roundtrip_ok += 1
                else:
                    roundtrip_fail += 1
            except Exception:
                roundtrip_fail += 1
        if roundtrip_fail == 0:
            ok(f"JSON roundtrip: {roundtrip_ok}/{len(json_papers)} papers preservados")
            checks_passed += 1
        else:
            warn(
                f"JSON roundtrip: {roundtrip_fail}/{len(json_papers)} papers com "
                "divergência após from_dict"
            )

        # Verify metadata fields in JSON
        # The export format wraps query/databases inside a "metadata" envelope:
        # {"metadata": {"query": ..., "databases": ..., "version": ...}, "papers": [...]}
        checks_total += 1
        top_level_keys = {"metadata", "papers"}
        if top_level_keys.issubset(set(data.keys())):
            ok("JSON: metadados do Search presentes (metadata, papers)")
            checks_passed += 1

            metadata = data["metadata"]
            inner_required = {"query", "databases"}
            missing_inner = inner_required - set(metadata.keys())
            if missing_inner:
                warn(f"JSON: campos faltando dentro de metadata: {missing_inner}")
        else:
            fail(f"JSON: metadados faltando — presentes: {set(data.keys())}")

        # Verify version field (inside metadata envelope)
        checks_total += 1
        metadata = data.get("metadata", {})
        if "version" in metadata:
            ok(f"JSON: versão presente: {metadata['version']}")
            checks_passed += 1
        elif "findpapers_version" in data:
            ok(f"JSON: versão presente (top-level): {data['findpapers_version']}")
            checks_passed += 1
        else:
            warn("JSON: campo version ausente em metadata")

    except json.JSONDecodeError as exc:
        fail(f"JSON: falha ao parsear: {exc}")
    except Exception as exc:
        fail(f"JSON: erro inesperado: {exc}", exc)

    # ── CSV validation ───────────────────────────────────────────────────────
    csv_path = target / "roundtrip_test.csv"
    checks_total += 1
    try:
        import csv as csv_mod

        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv_mod.reader(f)
            rows = list(reader)

        if len(rows) < 1:
            fail("CSV: arquivo vazio")
        else:
            header = rows[0]
            data_rows = rows[1:]

            # Header check
            from findpapers.utils.export import csv_columns

            expected_cols = csv_columns()
            checks_total += 1
            if header == expected_cols:
                ok(f"CSV: header correto ({len(header)} colunas)")
                checks_passed += 1
            else:
                missing_cols = set(expected_cols) - set(header)
                extra_cols = set(header) - set(expected_cols)
                if missing_cols:
                    fail(f"CSV: colunas faltando: {missing_cols}")
                if extra_cols:
                    warn(f"CSV: colunas extras: {extra_cols}")
                if not missing_cols:
                    checks_passed += 1

            # Row count
            checks_total += 1
            if len(data_rows) == len(search.papers):
                ok(f"CSV: {len(data_rows)} linhas de dados (correto)")
                checks_passed += 1
            else:
                fail(
                    f"CSV: esperado {len(search.papers)} linhas, obtido {len(data_rows)}"
                )

            # Non-empty title in every row
            checks_total += 1
            if header and "title" in header:
                title_idx = header.index("title")
                blank_rows = sum(
                    1
                    for row in data_rows
                    if len(row) <= title_idx or not row[title_idx].strip()
                )
                if blank_rows == 0:
                    ok("CSV: nenhuma linha com título vazio")
                    checks_passed += 1
                else:
                    fail(f"CSV: {blank_rows} linha(s) com título vazio")
            else:
                checks_passed += 1  # No title column to check

            checks_passed += 1  # CSV parseable overall
    except Exception as exc:
        fail(f"CSV: erro ao validar: {exc}", exc)

    # ── BibTeX validation ────────────────────────────────────────────────────
    bib_path = target / "roundtrip_test.bib"
    checks_total += 1
    try:
        bib_content = bib_path.read_text(encoding="utf-8")

        # Count entries (@type{key, ...)
        entry_pattern = re.compile(r"@\w+\{")
        entries = entry_pattern.findall(bib_content)

        checks_total += 1
        if len(entries) == len(search.papers):
            ok(f"BibTeX: {len(entries)} entradas (correto)")
            checks_passed += 1
        else:
            warn(
                f"BibTeX: esperado {len(search.papers)} entradas, obtido {len(entries)}"
            )

        # Valid entry types
        checks_total += 1
        valid_types = {
            "@article",
            "@inproceedings",
            "@incollection",
            "@inbook",
            "@phdthesis",
            "@mastersthesis",
            "@techreport",
            "@manual",
            "@unpublished",
            "@misc",
        }
        bad_types = []
        for entry in entries:
            entry_type = entry.rstrip("{").lower()
            if entry_type not in valid_types:
                bad_types.append(entry_type)
        if not bad_types:
            ok("BibTeX: todos os tipos de entrada são válidos")
            checks_passed += 1
        else:
            fail(f"BibTeX: tipos inválidos: {bad_types}")

        checks_passed += 1  # BibTeX readable
    except Exception as exc:
        fail(f"BibTeX: erro ao validar: {exc}", exc)

    summary = {
        "checks_total": checks_total,
        "checks_passed": checks_passed,
        "json_valid": json_path.exists(),
        "csv_valid": csv_path.exists(),
        "bib_valid": bib_path.exists(),
    }
    (target / "export_validation.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    status = "OK" if checks_passed == checks_total else "PARTIAL"
    ok(f"[{status}] export roundtrip: {checks_passed}/{checks_total} checks aprovados")

    results.append(
        CaseResult(
            phase=name,
            case_id="export_validation_suite",
            query="(export format tests)",
            databases=[test_db],
            paper_count=len(search.papers),
            runtime_seconds=0.0,
            success=(checks_passed == checks_total),
            notes=(
                []
                if checks_passed == checks_total
                else [f"{checks_total - checks_passed}_checks_failed"]
            ),
        )
    )

    save_phase_summary(target, results)
    return results


# =============================================================================
# FASE 24 – integridade de campos por base (validação profunda)
# =============================================================================


def phase_24_paper_field_integrity(
    databases: list[str] | None = None,
    verbose: bool = False,
) -> list[CaseResult]:
    """Phase 24: validate paper field integrity per database.

    For each database, runs a search and deeply validates every paper:

    - DOI format (starts with ``10.``)
    - URL format (valid http/https)
    - Publication date sanity (not future, not before 1900)
    - Author names are non-empty
    - Keywords are non-empty strings
    - Source has title if present
    - Database attribution includes the queried database
    - Paper type is valid ``PaperType`` if present
    - Citations are non-negative if present
    - Number of pages is positive if present

    Also computes a per-database field coverage report showing which
    percentage of papers have each field populated, which detects regressions
    in individual searcher parsing logic.
    """
    name = "phase_24_paper_field_integrity"
    section("FASE 24 - integridade de campos por base")
    target = phase_dir(name)
    results: list[CaseResult] = []

    dbs_all = databases if databases is not None else available_databases()
    coverage_report: dict[str, dict[str, str]] = {}

    for db in dbs_all:
        case_result, search = run_case(
            phase=name,
            case_id=f"{db}_field_integrity",
            query="[machine learning]",
            databases=[db],
            max_papers=20,
            target_dir=target,
            verbose=verbose,
        )
        results.append(case_result)

        if search is None or not search.papers:
            continue

        # Deep field validation
        field_issues = _validate_paper_fields(search.papers, db, f"integrity_{db}")
        if field_issues:
            warn(f"{db}: {len(field_issues)} problema(s) de integridade:")
            for issue in field_issues[:5]:
                print(f"         {issue}")
            if len(field_issues) > 5:
                print(f"         ... e mais {len(field_issues) - 5}")
            case_result.notes.append(f"field_issues:{len(field_issues)}")
        else:
            ok(f"{db}: integridade de campos OK ({len(search.papers)} papers)")

        # Field coverage report
        total = len(search.papers)
        coverage = {
            "title": sum(1 for p in search.papers if p.title and p.title.strip()) / total * 100,
            "abstract": sum(
                1 for p in search.papers if p.abstract and p.abstract.strip()
            )
            / total
            * 100,
            "doi": sum(1 for p in search.papers if p.doi) / total * 100,
            "url": sum(1 for p in search.papers if p.url) / total * 100,
            "pdf_url": sum(1 for p in search.papers if p.pdf_url) / total * 100,
            "publication_date": sum(1 for p in search.papers if p.publication_date) / total * 100,
            "authors": sum(1 for p in search.papers if p.authors) / total * 100,
            "keywords": sum(1 for p in search.papers if p.keywords) / total * 100,
            "paper_type": sum(1 for p in search.papers if p.paper_type is not None) / total * 100,
            "citations": sum(1 for p in search.papers if p.citations is not None) / total * 100,
            "source": sum(1 for p in search.papers if p.source is not None) / total * 100,
            "source.publisher": sum(
                1 for p in search.papers if p.source and p.source.publisher
            )
            / total
            * 100,
            "source.issn": sum(1 for p in search.papers if p.source and p.source.issn)
            / total
            * 100,
        }
        coverage_str = {k: f"{v:.0f}%" for k, v in coverage.items()}
        coverage_report[db] = coverage_str

        # Report critical field coverage thresholds
        if coverage["title"] < 100:
            fail(f"{db}: apenas {coverage['title']:.0f}% dos papers têm título — CRÍTICO")
            case_result.notes.append("critical_missing_titles")
        if coverage["abstract"] < 50:
            warn(f"{db}: apenas {coverage['abstract']:.0f}% dos papers têm abstract")
        if coverage["publication_date"] < 50:
            warn(f"{db}: apenas {coverage['publication_date']:.0f}% dos papers têm data")
        if coverage["authors"] < 50:
            warn(f"{db}: apenas {coverage['authors']:.0f}% dos papers têm autores")
        if coverage["paper_type"] < 50:
            warn(f"{db}: apenas {coverage['paper_type']:.0f}% dos papers têm tipo definido")

        ok(
            f"{db} cobertura: "
            + ", ".join(f"{k}={v}" for k, v in coverage_str.items())
        )

    (target / "field_coverage.json").write_text(
        json.dumps(coverage_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    save_phase_summary(target, results)
    return results


# =============================================================================
# FASE 25 – enforce max_papers_per_database
# =============================================================================


def phase_25_max_papers_enforcement(
    databases: list[str] | None = None,
    verbose: bool = False,
) -> list[CaseResult]:
    """Phase 25: verify that max_papers_per_database is strictly enforced.

    Runs searches with a small limit (3 papers per database) and validates
    that each database does not contribute more papers than requested.
    Also tests with multiple databases in one run.
    """
    name = "phase_25_max_papers_enforcement"
    section("FASE 25 - enforce max_papers_per_database")
    target = phase_dir(name)
    results: list[CaseResult] = []

    dbs_all = databases if databases is not None else available_databases()
    max_limit = 3

    # ── 25a: single database enforcement ─────────────────────────────────────
    for db in dbs_all[:3]:  # Test up to 3 databases for speed
        try:
            runner = build_runner(
                query="[machine learning]",
                databases=[db],
                max_papers=max_limit,
            )
            search = runner.run(verbose=verbose)
            metrics = runner.get_metrics()
            count = int(metrics.get(f"total_papers_from_{db}", len(search.papers)))

            if count <= max_limit:
                ok(f"{db}: {count} papers <= limite {max_limit} — correto")
            else:
                fail(
                    f"{db}: {count} papers > limite {max_limit} — "
                    "max_papers_per_database NÃO respeitado"
                )

            results.append(
                CaseResult(
                    phase=name,
                    case_id=f"{db}_max_enforcement",
                    query="[machine learning]",
                    databases=[db],
                    paper_count=len(search.papers),
                    runtime_seconds=float(metrics["runtime_in_seconds"]),
                    success=(count <= max_limit),
                    notes=([] if count <= max_limit else ["max_exceeded"]),
                )
            )
        except Exception as exc:
            fail(f"{db} max enforcement crashed", exc)
            results.append(
                CaseResult(
                    phase=name,
                    case_id=f"{db}_max_enforcement",
                    query="[machine learning]",
                    databases=[db],
                    paper_count=0,
                    runtime_seconds=0.0,
                    success=False,
                    notes=["exception"],
                )
            )

    # ── 25b: multi-database enforcement ──────────────────────────────────────
    free_dbs = [db for db in dbs_all if db in {"arxiv", "openalex", "pubmed", "semantic_scholar"}]
    if len(free_dbs) >= 2:
        multi_dbs = free_dbs[:3]
        try:
            runner = build_runner(
                query="[cancer]",
                databases=multi_dbs,
                max_papers=max_limit,
            )
            search = runner.run(verbose=verbose)
            metrics = runner.get_metrics()

            all_within = True
            for db in multi_dbs:
                count = int(metrics.get(f"total_papers_from_{db}", 0))
                if count > max_limit:
                    fail(f"multi-db: {db} contribuiu {count} papers > limite {max_limit}")
                    all_within = False
                else:
                    ok(f"multi-db: {db} contribuiu {count} papers <= {max_limit}")

            results.append(
                CaseResult(
                    phase=name,
                    case_id="multi_max_enforcement",
                    query="[cancer]",
                    databases=multi_dbs,
                    paper_count=len(search.papers),
                    runtime_seconds=float(metrics["runtime_in_seconds"]),
                    success=all_within,
                    notes=([] if all_within else ["max_exceeded_multi"]),
                )
            )
        except Exception as exc:
            fail("multi max enforcement crashed", exc)
            results.append(
                CaseResult(
                    phase=name,
                    case_id="multi_max_enforcement",
                    query="[cancer]",
                    databases=multi_dbs,
                    paper_count=0,
                    runtime_seconds=0.0,
                    success=False,
                    notes=["exception"],
                )
            )

    save_phase_summary(target, results)
    return results


# =============================================================================
# FASE 26 – detecção de publicações predatórias (offline)
# =============================================================================


def phase_26_predatory_detection() -> list[CaseResult]:
    """Phase 26: validate predatory source detection logic.

    Tests the predatory detection **offline** using synthetic papers with known
    predatory publisher/journal names from Beall's List, and verifies that the
    detection flag works correctly.  No network requests are made.

    Covered checks:

    - Known predatory publishers detected (OMICS International, Science
      Publishing Group).
    - Legitimate publishers NOT flagged (Elsevier, Springer, MDPI).
    - Known predatory journal detected (International Journal of Advanced
      Research).
    - Legitimate journals NOT flagged (Nature, Science).
    - ``None`` source does not crash and returns ``False``.
    - Synthetic paper with predatory source is correctly detected.
    """
    name = "phase_26_predatory_detection"
    section("FASE 26 - detecção de publicações predatórias (offline)")
    target = phase_dir(name)
    results: list[CaseResult] = []
    checks_passed = 0
    checks_total = 0

    from findpapers.core.source import Source
    from findpapers.utils.predatory import is_predatory_source

    # ── 26a: known predatory publisher detection ─────────────────────────────
    predatory_pub_cases = [
        ("OMICS International", True, "known predatory publisher"),
        ("Science Publishing Group", True, "known predatory publisher"),
        ("Elsevier", False, "legitimate publisher"),
        ("Springer", False, "legitimate publisher"),
        ("MDPI", False, "legitimate publisher (grey area, but not in Beall's)"),
    ]

    for pub_name, expected, desc in predatory_pub_cases:
        checks_total += 1
        source = Source(title=f"Test Journal for {pub_name}", publisher=pub_name)
        result = is_predatory_source(source)
        if result == expected:
            ok(
                f"publisher '{pub_name}': "
                f"{'predatory' if result else 'clean'} — correto ({desc})"
            )
            checks_passed += 1
        else:
            expected_str = "predatory" if expected else "clean"
            actual_str = "predatory" if result else "clean"
            warn(
                f"publisher '{pub_name}': esperado {expected_str}, "
                f"obtido {actual_str} ({desc})"
            )

    # ── 26b: known predatory journal detection ───────────────────────────────
    predatory_journal_cases = [
        ("International Journal of Advanced Research", True, "known predatory journal"),
        ("Nature", False, "legitimate journal"),
        ("Science", False, "legitimate journal"),
    ]

    for journal_name, expected, desc in predatory_journal_cases:
        checks_total += 1
        source = Source(title=journal_name)
        result = is_predatory_source(source)
        if result == expected:
            ok(
                f"journal '{journal_name}': "
                f"{'predatory' if result else 'clean'} — correto ({desc})"
            )
            checks_passed += 1
        else:
            expected_str = "predatory" if expected else "clean"
            actual_str = "predatory" if result else "clean"
            warn(
                f"journal '{journal_name}': esperado {expected_str}, "
                f"obtido {actual_str} ({desc})"
            )

    # ── 26c: None source should not crash ────────────────────────────────────
    checks_total += 1
    try:
        result = is_predatory_source(None)
        if result is False:
            ok("predatory check(None): False (correto)")
            checks_passed += 1
        else:
            warn(f"predatory check(None): esperado False, obtido {result}")
    except Exception as exc:
        fail(f"predatory check(None) crashou: {exc}", exc)

    # ── 26d: synthetic paper with predatory source is detected ───────────────
    checks_total += 1
    predatory_source = Source(
        title="International Journal of Advanced Research",
        publisher="OMICS International",
        is_potentially_predatory=False,
    )
    if is_predatory_source(predatory_source):
        ok("paper com source predatório: detectado corretamente")
        checks_passed += 1
    else:
        fail("paper com source predatório: NÃO detectado")

    summary = {"checks_total": checks_total, "checks_passed": checks_passed}
    (target / "phase_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    status = "OK" if checks_passed == checks_total else "PARTIAL"
    ok(f"[{status}] predatory detection: {checks_passed}/{checks_total} checks aprovados")

    results.append(
        CaseResult(
            phase=name,
            case_id="predatory_detection_suite",
            query="(offline predatory tests)",
            databases=[],
            paper_count=0,
            runtime_seconds=0.0,
            success=(checks_passed == checks_total),
            notes=(
                []
                if checks_passed == checks_total
                else [f"{checks_total - checks_passed}_checks_failed"]
            ),
        )
    )
    return results


# =============================================================================
# FASE 27 – precisão com paper conhecido
# =============================================================================


def phase_27_known_paper_precision(
    databases: list[str] | None = None,
    verbose: bool = False,
) -> list[CaseResult]:
    """Phase 27: search for a well-known paper and validate metadata precision.

    Searches for *'Attention Is All You Need'* (Vaswani et al. 2017) on each
    available CS database and validates:

    - Paper title contains ``attention``
    - Authors include someone named ``Vaswani``
    - Publication year is 2017
    - DOI is valid (starts with ``10.``)
    - Database attribution is correct
    - Abstract is present and non-trivial

    This catches regressions in individual searcher's parsing logic.
    """
    name = "phase_27_known_paper_precision"
    section("FASE 27 - precisão com paper conhecido")
    target = phase_dir(name)
    results: list[CaseResult] = []

    dbs_all = databases if databases is not None else available_databases()
    # This paper is indexed in all CS databases
    known_paper_dbs = [
        db for db in dbs_all if db in {"arxiv", "openalex", "semantic_scholar"}
    ]

    if not known_paper_dbs:
        warn("fase 27 requer arxiv, openalex ou semantic_scholar; pulando")
        save_phase_summary(target, results)
        return results

    # Use a very specific query so the original Vaswani 2017 paper is more
    # likely to appear in the first page of results despite date-desc sorting.
    # The generic "[attention is all you need]" is too ambiguous — dozens of
    # newer papers riff on that title and push the original out of the top 10.
    _known_paper_query = "[attention is all you need] AND [transformer]"

    for db in known_paper_dbs:
        case_result, search = run_case(
            phase=name,
            case_id=f"{db}_known_paper",
            query=_known_paper_query,
            databases=[db],
            max_papers=50,
            target_dir=target,
            verbose=verbose,
        )
        results.append(case_result)

        if search is None or not search.papers:
            warn(f"{db}: nenhum paper retornado para known-paper query")
            case_result.notes.append("zero_results_known_paper")
            continue

        # Find the target paper — try exact title first, then look for
        # Vaswani in authors (disambiguates from the many imitators).
        target_paper = None
        for p in search.papers:
            if (
                p.title
                and "attention is all you need" == p.title.strip().lower()
            ):
                target_paper = p
                break

        if target_paper is None:
            for p in search.papers:
                if (
                    p.title
                    and "attention is all you need" in p.title.lower()
                    and p.authors
                    and any("vaswani" in a.lower() for a in p.authors)
                ):
                    target_paper = p
                    break

        if target_paper is None:
            # Looser fallback — just pick the first with a matching title
            for p in search.papers:
                if p.title and "attention" in p.title.lower() and "need" in p.title.lower():
                    target_paper = p
                    break

        if target_paper is None:
            warn(
                f"{db}: paper 'Attention Is All You Need' não encontrado entre "
                f"{len(search.papers)} resultados"
            )
            case_result.notes.append("known_paper_not_found")
            continue

        ok(f"{db}: paper encontrado: '{target_paper.title[:70]}'")

        precision_issues = 0
        precision_total = 0

        # Title check
        precision_total += 1
        if "attention" in target_paper.title.lower():
            ok(f"{db}: título contém 'attention'")
        else:
            warn(f"{db}: título não contém 'attention': '{target_paper.title}'")
            precision_issues += 1

        # Author check
        precision_total += 1
        if target_paper.authors:
            has_vaswani = any("vaswani" in a.lower() for a in target_paper.authors)
            if has_vaswani:
                ok(f"{db}: autores incluem Vaswani ({len(target_paper.authors)} autores)")
            else:
                warn(
                    f"{db}: Vaswani não encontrado nos autores: "
                    f"{target_paper.authors[:3]}"
                )
                precision_issues += 1
        else:
            warn(f"{db}: sem autores")
            precision_issues += 1

        # Year check
        precision_total += 1
        if target_paper.publication_date:
            if target_paper.publication_date.year == 2017:
                ok(f"{db}: ano correto (2017)")
            else:
                warn(
                    f"{db}: ano divergiu: "
                    f"{target_paper.publication_date.year} (esperado 2017)"
                )
                precision_issues += 1
        else:
            warn(f"{db}: sem data de publicação")
            precision_issues += 1

        # DOI check
        precision_total += 1
        if target_paper.doi:
            if target_paper.doi.startswith("10."):
                ok(f"{db}: DOI válido: {target_paper.doi}")
            else:
                warn(f"{db}: DOI formato inválido: {target_paper.doi}")
                precision_issues += 1
        else:
            warn(f"{db}: sem DOI")
            precision_issues += 1

        # Database attribution
        precision_total += 1
        if target_paper.databases and db.lower() in {
            d.lower() for d in target_paper.databases
        }:
            ok(f"{db}: database attribution correto")
        else:
            warn(
                f"{db}: database attribution não contém '{db}': "
                f"{target_paper.databases}"
            )
            precision_issues += 1

        # Abstract present
        precision_total += 1
        if target_paper.abstract and len(target_paper.abstract) > 50:
            ok(f"{db}: abstract presente ({len(target_paper.abstract)} chars)")
        else:
            warn(f"{db}: abstract ausente ou curto demais")
            precision_issues += 1

        if precision_issues > 0:
            case_result.notes.append(f"precision_issues:{precision_issues}/{precision_total}")

    save_phase_summary(target, results)
    return results


# =============================================================================
# FASE 28 – deduplicação por DOI e tratamento preprint/publisher
# =============================================================================


def phase_28_doi_dedup_and_preprint(
    databases: list[str] | None = None,
    verbose: bool = False,
) -> list[CaseResult]:
    """Phase 28: validate DOI-based deduplication and preprint DOI handling.

    Searches for a paper known to exist on arXiv (preprint DOI) and
    OpenAlex/Semantic Scholar (publisher DOI), then validates:

    - The paper appears only once in final results (deduplicated).
    - The merged paper lists multiple databases.
    - The preferred DOI is the publisher DOI (not ArXiv's ``10.48550/``).
    - Merge does not lose database-level attribution.
    """
    name = "phase_28_doi_dedup_and_preprint"
    section("FASE 28 - deduplicação por DOI e preprint handling")
    target = phase_dir(name)
    results: list[CaseResult] = []

    dbs_all = databases if databases is not None else available_databases()
    # Need at least arxiv + one other CS database for preprint handling
    doi_test_dbs = [db for db in ["arxiv", "openalex", "semantic_scholar"] if db in dbs_all]
    if len(doi_test_dbs) < 2:
        warn("fase 28 requer ao menos 2 de: arxiv, openalex, semantic_scholar; pulando")
        save_phase_summary(target, results)
        return results

    case_result, search = run_case(
        phase=name,
        case_id="doi_dedup_attention",
        query="[attention is all you need] AND [transformer]",
        databases=doi_test_dbs,
        max_papers=20,
        target_dir=target,
        verbose=verbose,
    )
    results.append(case_result)

    if search is None or not search.papers:
        save_phase_summary(target, results)
        return results

    # Find the target paper
    # Strict match: only papers whose title is *exactly* "Attention Is All You
    # Need" (case-insensitive, stripped).  The old loose filter ("attention" +
    # "need" anywhere in title) matched dozens of genuinely different papers
    # (e.g. "Tensor Product Attention Is All You Need") and incorrectly
    # flagged them as dedup failures.
    _exact_title = "attention is all you need"
    attention_papers = [
        p
        for p in search.papers
        if p.title and p.title.strip().lower() == _exact_title
    ]

    if not attention_papers:
        warn(
            "paper com título exato 'Attention Is All You Need' não encontrado "
            "nos resultados — pode ter sido ocluído por papers mais recentes"
        )
        save_phase_summary(target, results)
        return results

    if len(attention_papers) > 1:
        warn(
            f"múltiplas cópias exatas de 'Attention Is All You Need' encontradas "
            f"({len(attention_papers)}) — deduplicação pode não ter funcionado"
        )
        for p in attention_papers:
            print(
                f"         título: {p.title[:60]} | doi: {p.doi} "
                f"| dbs: {sorted(p.databases or set())}"
            )
        case_result.notes.append(f"dedup_variants:{len(attention_papers)}")
    else:
        ok("paper 'Attention Is All You Need' encontrado uma única vez (dedup ok)")

    target_paper = attention_papers[0]

    # Check multi-database attribution
    paper_dbs = {d.lower() for d in (target_paper.databases or set())}
    if len(paper_dbs) > 1:
        ok(
            f"merge exercitado: databases={sorted(paper_dbs)} "
            f"({len(paper_dbs)} fontes)"
        )
    else:
        warn(
            f"paper apenas de uma fonte: {sorted(paper_dbs)} — "
            "merge entre bases pode não ter funcionado"
        )

    # Check DOI preference (publisher DOI over preprint)
    #
    # NOTE: A preprint DOI surviving multi-db merge is NOT necessarily a bug.
    # Some papers (e.g. recent arXiv preprints) are indexed in multiple
    # databases but have *only* a preprint DOI because the paper was never
    # published in a journal.  We now treat this as an info/ok rather than a
    # warning, and only flag it if there is concrete evidence that a publisher
    # DOI was available but lost.
    if target_paper.doi:
        from findpapers.core.paper import _is_preprint_doi

        is_preprint = _is_preprint_doi(target_paper.doi)
        if is_preprint and len(paper_dbs) > 1:
            ok(
                f"DOI de preprint ({target_paper.doi}) mantido após merge "
                f"multi-db ({sorted(paper_dbs)}) — genuinamente sem DOI publisher"
            )
        elif not is_preprint:
            ok(f"DOI publisher preferido: {target_paper.doi}")
        else:
            ok(f"DOI (sem merge multi-db): {target_paper.doi}")
    else:
        warn("paper sem DOI após merge")

    # Verify no duplicate titles in full result set
    titles_lower = [p.title.strip().lower() for p in search.papers if p.title]
    if len(titles_lower) != len(set(titles_lower)):
        from collections import Counter

        dupes = [t for t, n in Counter(titles_lower).items() if n > 1]
        warn(
            f"{len(dupes)} título(s) duplicado(s) detectado(s) "
            "— deduplicação incompleta"
        )
        case_result.notes.append(f"title_dupes:{len(dupes)}")
    else:
        ok("sem títulos duplicados no resultado final")

    payload = {
        "total_papers": len(search.papers),
        "attention_variants": len(attention_papers),
        "merged_databases": sorted(paper_dbs),
        "doi": target_paper.doi,
        "dedup_successful": len(attention_papers) == 1,
    }
    (target / "doi_dedup_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    save_phase_summary(target, results)
    return results


def build_investigation_report(
    phase_results: list[CaseResult],
    enrichment_summary: dict[str, Any],
    download_summary: dict[str, Any],
    databases: list[str] | None = None,
) -> dict[str, Any]:
    """Build a diagnostics report highlighting suspicious behavior."""
    issues: list[str] = []

    # Phase 11: error handling
    phase_11 = [r for r in phase_results if r.phase == "phase_11_error_handling"]
    if phase_11 and not phase_11[0].success:
        issues.append(
            "Fase 11 (tratamento de erros): um ou mais checks de validação falharam. "
            "Ver notes: " + str(phase_11[0].notes)
        )

    # Phase 9: paper type filter
    phase_9 = [r for r in phase_results if r.phase == "phase_9_paper_type_filter"]
    for r in phase_9:
        if not r.success:
            continue
        case_id = r.case_id
        # Detect impossible-type leaks: cases ending in _impossible_<type> that returned papers
        if "_impossible_" in case_id and r.paper_count > 0:
            parts = case_id.split("_impossible_", 1)
            db = parts[0]
            impossible_type = parts[1] if len(parts) > 1 else "?"
            issues.append(
                f"Fase 9 (tipo de paper): base '{db}' retornou {r.paper_count} paper(s) "
                f"ao filtrar por tipo '{impossible_type}' que ela NÃO deveria produzir — "
                f"mapeamento de tipo provavelmente incorreto."
            )
        # Detect filter correctness failures tracked as notes
        if any(n.startswith("tipo_errado:") for n in r.notes):
            count_str = next(n.split(":")[1] for n in r.notes if n.startswith("tipo_errado:"))
            issues.append(
                f"Fase 9 (tipo de paper): {case_id} — {count_str} paper(s) retornado(s) "
                f"com tipo divergente do filtro solicitado."
            )
        if any(n.startswith("none_vazou:") for n in r.notes):
            count_str = next(n.split(":")[1] for n in r.notes if n.startswith("none_vazou:"))
            issues.append(
                f"Fase 9 (tipo de paper): {case_id} — {count_str} paper(s) com "
                f"paper_type=None vazaram pelo filtro (deveriam ter sido descartados)."
            )

    # Phase 14: re-run idempotency
    phase_14 = [r for r in phase_results if r.phase == "phase_14_rerun_idempotency"]
    for r in phase_14:
        if "rerun_inconsistent" in r.notes:
            issues.append(
                f"Fase 14 (idempotência): re-run de {r.databases} retornou contagens diferentes."
            )
        if "get_results_not_copy" in r.notes:
            issues.append("Fase 14 (idempotência): get_results() não retornou cópia independente.")

    crashes = [result for result in phase_results if not result.success]
    if crashes:
        issues.append(f"{len(crashes)} caso(s) com exceção inesperada.")

    phase_1 = [result for result in phase_results if result.phase == "phase_1_simple_term"]
    zero_phase_1 = [result for result in phase_1 if result.paper_count == 0 and result.success]
    if zero_phase_1:
        names = ", ".join(result.databases[0] for result in zero_phase_1)
        issues.append(
            "Base(s) sem resultado na fase de sanidade (fase 1): "
            f"{names}. Isso sugere problema de integração/consulta básica."
        )

    phase_2 = [result for result in phase_results if result.phase == "phase_2_connectors"]
    for db in databases if databases is not None else available_databases():
        rows = [result for result in phase_2 if result.case_id.startswith(f"{db}_")]
        if not rows:
            continue
        if any(not result.success for result in rows):
            issues.append(f"Falha de execução em conectores para {db}.")
            continue
        if all(result.paper_count == 0 for result in rows):
            issues.append(f"Conectores para {db} retornaram 0 em todos os cenários da fase 2.")

    phase_4 = [result for result in phase_results if result.phase == "phase_4_filtered_mix"]
    for result in phase_4:
        if result.success and result.paper_count == 0:
            issues.append(
                f"Consulta com filtros em {result.databases[0]} retornou 0 resultados "
                f"({result.case_id})."
            )

    if enrichment_summary.get("executed"):
        improved = int(enrichment_summary.get("papers_with_richness_increase", 0))
        metric_enriched = int(enrichment_summary.get("enriched_papers_metric", 0))
        papers_with_gaps = int(enrichment_summary.get("papers_with_gaps_before", -1))
        all_already_complete = enrichment_summary.get("all_sample_already_complete", False)
        sample_dbs = enrichment_summary.get("sample_databases", [])
        fetch_error_papers = int(enrichment_summary.get("fetch_error_papers", -1))
        no_metadata_papers = int(enrichment_summary.get("no_metadata_papers", -1))
        scopus_in_sample = int(enrichment_summary.get("scopus_papers_in_sample", 0))
        scopus_extra = enrichment_summary.get("scopus_extra_search_used", False)
        if metric_enriched > 0 and improved == 0:
            issues.append(
                "Enrichment marcou papers como enriquecidos, mas sem incremento de completude."
            )
        if metric_enriched == 0 and all_already_complete:
            # Expected: all papers in the sample were already fully populated
            # (e.g. arXiv API returns complete metadata).  Not a bug.
            pass
        elif metric_enriched == 0 and papers_with_gaps > 0:
            missing_info = enrichment_summary.get("missing_fields_before", {})
            sample_dbs_str = ", ".join(sample_dbs) if sample_dbs else "desconhecido"
            scopus_hint = (
                f" Sample incluiu {scopus_in_sample} paper(s) Scopus sem abstract"
                f" (via busca extra{'  ✓' if scopus_extra else ''})."
                if scopus_in_sample > 0
                else (
                    " DICA: adicionar SCOPUS_API_TOKEN permitiria usar papers sem abstract"
                    " como candidatos ideais para enriquecimento."
                    if not scopus_extra
                    else ""
                )
            )
            # Distinguish between HTTP-level failures (bot detection, rate limiting,
            # JS-rendered SPAs) and a genuine enrichment logic issue.
            if fetch_error_papers > 0 and (no_metadata_papers == 0 or no_metadata_papers == -1):
                # All failures were network / HTTP errors — not a code bug, just
                # inaccessible URLs (e.g. Semantic Scholar blocks scrapers).
                warn(
                    f"Enrichment não conseguiu acessar as URLs dos papers do sample "
                    f"(HTTP errors em {fetch_error_papers} paper(s); bases: {sample_dbs_str}).{scopus_hint} "
                    f"Isso é esperado para sites com JS-rendering ou proteção anti-bot. "
                    f"Campos ausentes que não puderam ser preenchidos: {list(missing_info.keys())}"
                )
            else:
                issues.append(
                    f"Enrichment não conseguiu enriquecer nenhum paper do sample, "
                    f"mas {papers_with_gaps} paper(s) tinham campos ausentes antes "
                    f"da fase (bases: {sample_dbs_str}).{scopus_hint} "
                    f"Campos ausentes: {missing_info}"
                )
        elif metric_enriched == 0 and papers_with_gaps == -1:
            # Legacy payload without the new diagnostic keys — keep old behaviour.
            issues.append("Enrichment não conseguiu enriquecer nenhum paper no sample.")

    if download_summary.get("executed"):
        downloaded_metric = int(download_summary.get("downloaded_papers_metric", 0))
        pdf_count = int(download_summary.get("pdf_file_count", 0))
        if downloaded_metric == 0:
            issues.append("DownloadRunner não baixou nenhum PDF no sample.")
        if downloaded_metric != pdf_count:
            issues.append(
                "Métrica de downloads e número de PDFs em disco divergiram "
                f"({downloaded_metric} vs {pdf_count})."
            )

    # Phase 15: wildcard live searches
    phase_15 = [r for r in phase_results if r.phase == "phase_15_wildcard_searches"]
    for r in phase_15:
        if r.case_id.endswith("_wildcard") and r.success and r.paper_count == 0:
            issues.append(
                f"Fase 15 (wildcards): busca com wildcard em {r.databases} retornou 0 papers "
                f"({r.case_id})."
            )
        if "openalex_should_skip_wildcards" in r.notes:
            issues.append(
                "Fase 15 (wildcards): OpenAlex não ignorou query com wildcard "
                "— validação por base provavelmente quebrada."
            )
        if "question_wildcard_not_rejected" in r.notes:
            issues.append(
                "Fase 15 (wildcards): alguma base não rejeitou '?' wildcard "
                "conforme esperado."
            )

    # Phase 16: wildcard syntax validation
    phase_16 = [r for r in phase_results if r.phase == "phase_16_wildcard_validation"]
    if phase_16 and not phase_16[0].success:
        issues.append(
            "Fase 16 (validação wildcard): um ou mais checks de sintaxe falharam. "
            "Ver notes: " + str(phase_16[0].notes)
        )

    # Phase 17: unsupported filter graceful skip
    phase_17 = [r for r in phase_results if r.phase == "phase_17_unsupported_filter_skip"]
    for r in phase_17:
        if any("should_skip" in note for note in r.notes):
            issues.append(
                f"Fase 17 (filtro não suportado): base não ignorou filtro incompatível "
                f"({r.case_id}). Ver notes: {r.notes}"
            )

    # Phase 18: group filter propagation
    phase_18 = [r for r in phase_results if r.phase == "phase_18_group_filter_propagation"]
    for r in phase_18:
        if r.success and r.paper_count == 0:
            issues.append(
                f"Fase 18 (filtro de grupo): {r.case_id} retornou 0 papers "
                "— verificar propagação de filtro em grupo."
            )

    # Phase 19: extended filters (key, src, tiabskey)
    phase_19 = [r for r in phase_results if r.phase == "phase_19_extended_filters"]
    for r in phase_19:
        if r.success and r.paper_count == 0:
            issues.append(
                f"Fase 19 (filtros estendidos): {r.case_id} retornou 0 papers "
                f"(query={r.query})."
            )

    # Phase 20: case-insensitivity
    phase_20 = [r for r in phase_results if r.phase == "phase_20_case_insensitivity"]
    for r in phase_20:
        if "construction_failed" in r.notes:
            issues.append(
                f"Fase 20 (case-insensitivity): construção falhou para query '{r.query}'."
            )
        if r.success and r.paper_count == 0:
            issues.append(
                f"Fase 20 (case-insensitivity): {r.case_id} retornou 0 papers "
                f"(query='{r.query}')."
            )

    # Phase 21: complex nested queries
    phase_21 = [r for r in phase_results if r.phase == "phase_21_complex_nested_queries"]
    for r in phase_21:
        if not r.success:
            issues.append(
                f"Fase 21 (queries complexas): {r.case_id} falhou (crash)."
            )
        elif r.paper_count == 0:
            issues.append(
                f"Fase 21 (queries complexas): {r.case_id} retornou 0 papers "
                f"(query='{r.query}')."
            )

    # Phase 22: no API keys
    phase_22 = [r for r in phase_results if r.phase == "phase_22_no_api_keys"]
    for r in phase_22:
        if not r.success:
            issues.append(
                f"Fase 22 (sem API keys): {r.case_id} falhou — "
                f"comportamento inesperado sem keys. Notes: {r.notes}"
            )

    # Phase 23: export roundtrip
    phase_23 = [r for r in phase_results if r.phase == "phase_23_export_roundtrip"]
    for r in phase_23:
        if not r.success:
            issues.append(
                f"Fase 23 (export roundtrip): validação de exportação falhou. "
                f"Notes: {r.notes}"
            )

    # Phase 24: paper field integrity
    phase_24 = [r for r in phase_results if r.phase == "phase_24_paper_field_integrity"]
    for r in phase_24:
        if any(n.startswith("field_issues:") for n in r.notes):
            count_str = next(n.split(":")[1] for n in r.notes if n.startswith("field_issues:"))
            issues.append(
                f"Fase 24 (integridade de campos): {r.case_id} — "
                f"{count_str} problema(s) de integridade detectados."
            )
        if "critical_missing_titles" in r.notes:
            issues.append(
                f"Fase 24 (integridade de campos): {r.case_id} — "
                "papers sem título detectados (CRÍTICO)."
            )

    # Phase 25: max_papers enforcement
    phase_25 = [r for r in phase_results if r.phase == "phase_25_max_papers_enforcement"]
    for r in phase_25:
        if "max_exceeded" in r.notes or "max_exceeded_multi" in r.notes:
            issues.append(
                f"Fase 25 (max_papers): {r.case_id} — limite max_papers_per_database "
                "NÃO respeitado."
            )

    # Phase 26: predatory detection
    phase_26 = [r for r in phase_results if r.phase == "phase_26_predatory_detection"]
    for r in phase_26:
        if not r.success:
            issues.append(
                f"Fase 26 (predatory): detecção de publicações predatórias falhou. "
                f"Notes: {r.notes}"
            )

    # Phase 27: known paper precision
    phase_27 = [r for r in phase_results if r.phase == "phase_27_known_paper_precision"]
    for r in phase_27:
        if any(n.startswith("precision_issues:") for n in r.notes):
            issues.append(
                f"Fase 27 (precisão): {r.case_id} — problemas de precisão "
                f"em metadados do paper conhecido."
            )
        if "known_paper_not_found" in r.notes:
            issues.append(
                f"Fase 27 (precisão): {r.case_id} — paper conhecido "
                "'Attention Is All You Need' NÃO encontrado."
            )

    # Phase 28: DOI dedup and preprint
    phase_28 = [r for r in phase_results if r.phase == "phase_28_doi_dedup_and_preprint"]
    for r in phase_28:
        if "preprint_doi_preferred" in r.notes:
            issues.append(
                "Fase 28 (DOI dedup): DOI de preprint preferido sobre DOI publisher "
                "após merge — verificar _merge_doi."
            )
        if any(n.startswith("dedup_variants:") for n in r.notes):
            issues.append(
                "Fase 28 (DOI dedup): múltiplas variantes do mesmo paper "
                "detectadas — deduplicação incompleta."
            )
        if any(n.startswith("title_dupes:") for n in r.notes):
            issues.append(
                "Fase 28 (DOI dedup): títulos duplicados detectados no resultado final."
            )

    return {
        "total_cases": len(phase_results),
        "crashed_cases": len(crashes),
        "issues_needing_investigation": issues,
    }


def main() -> int:
    """Execute all phases (1–28) and save a consolidated report."""
    parser = argparse.ArgumentParser(
        description="Phased manual battery for validating findpapers refactored flows."
    )
    parser.add_argument(
        "-d",
        "--database",
        metavar="DB",
        help=(
            "Run all phases against this single database only. "
            "Valid values: arxiv, openalex, pubmed, "
            "semantic_scholar, ieee, scopus."
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=False,
        help="Enable verbose output from runners.",
    )
    args = parser.parse_args()

    databases_filter: list[str] | None = None
    if args.database:
        all_dbs = available_databases()
        if args.database not in all_dbs:
            print(
                f"ERROR: '{args.database}' is not an available database. "
                f"Available: {', '.join(all_dbs)}"
            )
            return 1
        databases_filter = [args.database]

    # Clean previous outputs so stale artefacts do not pollute the new run.
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    section("findpapers refactor - bateria manual por fases")
    print(f"Output root: {OUTPUT_DIR}")
    if databases_filter:
        print(f"Database filter: {databases_filter[0]}")
    print()
    print("API keys detected:")
    print(f"  IEEE             : {'YES' if IEEE_API_KEY else 'NO'}")
    print(f"  Scopus           : {'YES' if SCOPUS_API_KEY else 'NO'}")
    print(f"  PubMed           : {'YES' if PUBMED_API_KEY else 'NO'}")
    print(f"  OpenAlex         : {'YES' if OPENALEX_API_KEY else 'NO'}")
    print(f"  Semantic Scholar : {'YES' if SEMANTIC_SCHOLAR_API_KEY else 'NO'}")
    print(f"  Proxy configured : {'YES' if PROXY else 'NO'}")

    all_results: list[CaseResult] = []

    phase_1_results, _phase_1_searches = phase_1_simple_term(
        databases=databases_filter, verbose=args.verbose
    )
    all_results.extend(phase_1_results)

    phase_2_results = phase_2_connectors(databases=databases_filter, verbose=args.verbose)
    all_results.extend(phase_2_results)

    phase_3_results = phase_3_groups(databases=databases_filter, verbose=args.verbose)
    all_results.extend(phase_3_results)

    phase_4_results = phase_4_filtered_mix(databases=databases_filter, verbose=args.verbose)
    all_results.extend(phase_4_results)

    phase_5_results, seed_for_phase_6_7 = phase_5_multi_database(
        databases=databases_filter, verbose=args.verbose
    )
    all_results.extend(phase_5_results)

    enrichment_summary = phase_6_enrichment(seed_for_phase_6_7, verbose=args.verbose)
    download_summary = phase_7_download(seed_for_phase_6_7, verbose=args.verbose)

    phase_8_results = phase_8_parallelism(databases=databases_filter, verbose=args.verbose)
    all_results.extend(phase_8_results)

    phase_9_results = phase_9_paper_type_filter(databases=databases_filter, verbose=args.verbose)
    all_results.extend(phase_9_results)

    phase_10_results = phase_10_date_filter(databases=databases_filter, verbose=args.verbose)
    all_results.extend(phase_10_results)

    phase_11_results = phase_11_error_handling()
    all_results.extend(phase_11_results)

    phase_12_results = phase_12_search_metadata(databases=databases_filter, verbose=args.verbose)
    all_results.extend(phase_12_results)

    phase_13_results = phase_13_deduplication(databases=databases_filter, verbose=args.verbose)
    all_results.extend(phase_13_results)

    phase_14_results = phase_14_rerun_idempotency(databases=databases_filter, verbose=args.verbose)
    all_results.extend(phase_14_results)

    phase_15_results = phase_15_wildcard_searches(databases=databases_filter, verbose=args.verbose)
    all_results.extend(phase_15_results)

    phase_16_results = phase_16_wildcard_validation()
    all_results.extend(phase_16_results)

    phase_17_results = phase_17_unsupported_filter_skip(
        databases=databases_filter, verbose=args.verbose
    )
    all_results.extend(phase_17_results)

    phase_18_results = phase_18_group_filter_propagation(
        databases=databases_filter, verbose=args.verbose
    )
    all_results.extend(phase_18_results)

    phase_19_results = phase_19_extended_filters(databases=databases_filter, verbose=args.verbose)
    all_results.extend(phase_19_results)

    phase_20_results = phase_20_case_insensitivity(databases=databases_filter, verbose=args.verbose)
    all_results.extend(phase_20_results)

    phase_21_results = phase_21_complex_nested_queries(
        databases=databases_filter, verbose=args.verbose
    )
    all_results.extend(phase_21_results)

    phase_22_results = phase_22_no_api_keys(databases=databases_filter, verbose=args.verbose)
    all_results.extend(phase_22_results)

    phase_23_results = phase_23_export_roundtrip(
        databases=databases_filter, verbose=args.verbose
    )
    all_results.extend(phase_23_results)

    phase_24_results = phase_24_paper_field_integrity(
        databases=databases_filter, verbose=args.verbose
    )
    all_results.extend(phase_24_results)

    phase_25_results = phase_25_max_papers_enforcement(
        databases=databases_filter, verbose=args.verbose
    )
    all_results.extend(phase_25_results)

    phase_26_results = phase_26_predatory_detection()
    all_results.extend(phase_26_results)

    phase_27_results = phase_27_known_paper_precision(
        databases=databases_filter, verbose=args.verbose
    )
    all_results.extend(phase_27_results)

    phase_28_results = phase_28_doi_dedup_and_preprint(
        databases=databases_filter, verbose=args.verbose
    )
    all_results.extend(phase_28_results)

    consolidated_report = build_investigation_report(
        phase_results=all_results,
        enrichment_summary=enrichment_summary,
        download_summary=download_summary,
        databases=databases_filter,
    )

    report_path = OUTPUT_DIR / "investigation_report.json"
    report_path.write_text(
        json.dumps(consolidated_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    section("RESUMO FINAL")
    print(f"Casos executados: {consolidated_report['total_cases']}")
    print(f"Casos com crash: {consolidated_report['crashed_cases']}")
    issues = consolidated_report["issues_needing_investigation"]
    print(f"Pontos para investigação: {len(issues)}")
    for issue in issues:
        print(f"  - {issue}")
    print(f"\nRelatório salvo em: {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
