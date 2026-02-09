# Refactoring Plan v2 - Plano Unificado

## 🎯 Objetivo

Desempilhar os 3 refactorings incompletos e criar uma implementação única que:

1. ✅ **Query System como árvore** (QueryNode) - já implementado em `findpapers_0/`
2. ✅ **API OO com Runners** - já implementado em `findpapers_0/`
3. 🔄 **Estrutura SOLID simplificada** - extrair QueryBuilders, organizar pastas
4. 🔄 **Implementar todos searchers** do query-build-plan.md (8 databases: arXiv, PubMed, IEEE, Scopus, bioRxiv, medRxiv, OpenAlex, Semantic Scholar)
5. 🔄 **Código 100% OO** - dependency injection, classes bem definidas

**Importante:** NÃO precisa ser retrocompatível. É uma reconstrução completa.

---

## 📂 Estado Atual

### Código Base (findpapers_0/)
**✅ Implementado e funcionando (184 testes passando):**
- `models/query.py` - Query system completo com árvore (QueryNode)
  - `filter_code`, `inherited_filter_code`, `children_match_filter`
  - Parsing de queries: `ti[termo]`, `abs(termo OR outro)`, etc.
  - Propagação de filtros na árvore
  - Serialização to_dict/from_dict
- `runners/search_runner.py` - SearchRunner OO com pipeline
- `runners/enrichment_runner.py` - EnrichmentRunner
- `runners/download_runner.py` - DownloadRunner
- `searchers/` - 7 searchers implementados:
  - arxiv.py, pubmed.py, ieee.py, scopus.py
  - biorxiv.py, medrxiv.py, rxiv.py (base interna)
- `utils/` - merge, parallel, predatory, version, enrichment

**❌ Faltando:**
- QueryBuilders separados (arquivos em findpapers_0/searchers são placeholders)
- Estrutura SOLID (pastas organizadas)
- Implementação completa de builders seguindo query-build-plan.md
- Implementação completa de searchers seguindo query-build-plan.md
- OpenAlex searcher + builder
- Semantic Scholar searcher + builder
- Dependency injection nos searchers

**⚠️ IMPORTANTE:** Os arquivos em `findpapers_0/searchers/*.py` são apenas **placeholders**. Toda a lógica de **builders** e **searchers** deve ser **implementada do zero** seguindo as especificações do [query-build-plan.md](query-build-plan.md). NÃO extrair código de findpapers_0/.

### Lixo a Limpar
- `findpapers/` - estrutura vazia iniciada
- `findpapers_old/` - código funcional antigo
- `tests/` - vazio
- `tests_old/` - testes antigos

---

## 📋 Plano Unificado (6 Fases)

### Fase 0: Limpeza e Preparação ✅ CONCLUÍDA

**Objetivo:** Limpar a bagunça e preparar terreno limpo

**Ações:**
1. ✅ Confirmado que `findpapers_0/` é a base (184 testes passando)
2. ✅ Apagado `findpapers/` (estrutura vazia incompleta removida)
3. ✅ Apagado `tests/` (estrutura vazia incompleta removida)
4. ✅ Documentado em `_cleanup_notes.md` o que tinha em cada versão
5. ✅ Criado estrutura de diretórios limpa seguindo SOLID simplificado

**Estrutura de diretórios final:**
```
findpapers/
├── __init__.py              # API pública: SearchRunner, EnrichmentRunner, DownloadRunner
├── exceptions.py            # Exceções customizadas
├── core/
│   ├── __init__.py
│   ├── paper.py            # from findpapers_0/models/paper.py
│   ├── publication.py      # from findpapers_0/models/publication.py
│   ├── search.py           # from findpapers_0/models/search.py
│   └── query.py            # Query, QueryNode, enums (estruturas apenas)
├── query/
│   ├── __init__.py
│   ├── validator.py        # Extrair validação de findpapers_0/models/query.py
│   ├── parser.py           # Extrair parsing de findpapers_0/models/query.py
│   ├── propagator.py       # Extrair propagate_filters() de QueryNode
│   ├── builder.py          # Interface ABC para QueryBuilders
│   └── builders/           # QueryBuilders (nested em query/) - IMPLEMENTAR DO ZERO seguindo query-build-plan.md
│       ├── __init__.py
│       ├── arxiv.py            # 🆕 Implementar (query-build-plan.md)
│       ├── pubmed.py           # 🆕 Implementar (query-build-plan.md)
│       ├── ieee.py             # 🆕 Implementar (query-build-plan.md)
│       ├── scopus.py           # 🆕 Implementar (query-build-plan.md)
│       ├── biorxiv.py          # 🆕 Implementar (query-build-plan.md)
│       ├── medrxiv.py          # 🆕 Implementar (query-build-plan.md)
│       ├── openalex.py         # 🆕 Implementar (query-build-plan.md)
│       └── semantic_scholar.py # 🆕 Implementar (query-build-plan.md)
├── searchers/               # Searchers (FLAT, não nested) - IMPLEMENTAR DO ZERO seguindo query-build-plan.md
│   ├── __init__.py
│   ├── base.py             # from findpapers_0/searchers/base.py (apenas interface ABC)
│   ├── arxiv.py            # 🆕 Implementar (query-build-plan.md)
│   ├── pubmed.py           # 🆕 Implementar (query-build-plan.md)
│   ├── ieee.py             # 🆕 Implementar (query-build-plan.md)
│   ├── scopus.py           # 🆕 Implementar (query-build-plan.md)
│   ├── biorxiv.py          # 🆕 Implementar (query-build-plan.md)
│   ├── medrxiv.py          # 🆕 Implementar (query-build-plan.md)
│   ├── rxiv.py             # 🆕 Implementar (base interna para bioRxiv/medRxiv)
│   ├── openalex.py         # 🆕 Implementar (query-build-plan.md)
│   └── semantic_scholar.py # 🆕 Implementar (query-build-plan.md)
├── runners/
│   ├── __init__.py
│   ├── search_runner.py    # Refatorar com DI de Parser, Validator
│   ├── enrichment_runner.py
│   └── download_runner.py
└── utils/
    ├── __init__.py
    ├── export.py           # Funções: to_json_format(), to_csv_format(), to_bibtex_format()
    ├── merge.py            # from findpapers_0/utils/merge_util.py
    ├── parallel.py         # from findpapers_0/utils/parallel_util.py
    ├── predatory.py        # from findpapers_0/utils/predatory_*.py
    ├── download.py         # Web scraping helpers
    └── version.py          # from findpapers_0/utils/version_util.py

tests/
├── __init__.py
├── conftest.py
├── data/                   # from tests_0/data/ (samples de respostas)
├── unit/
│   ├── core/
│   ├── query/
│   │   └── builders/
│   ├── searchers/
│   ├── runners/
│   └── utils/
└── integration/
```

**Critérios de conclusão:**
- [✅] Estrutura de diretórios criada
- [✅] findpapers/, tests/ limpos e vazios com __init__.py
- [✅] _cleanup_notes.md documentado

**Estrutura criada:**
```
findpapers/
├── __init__.py
├── core/
│   └── __init__.py
├── query/
│   ├── __init__.py
│   └── builders/
│       └── __init__.py
├── runners/
│   └── __init__.py
├── searchers/
│   └── __init__.py
└── utils/
    └── __init__.py

tests/
├── __init__.py
├── data/
├── integration/
│   └── __init__.py
└── unit/
    ├── __init__.py
    ├── core/
    │   └── __init__.py
    ├── query/
    │   ├── __init__.py
    │   └── builders/
    │       └── __init__.py
    ├── runners/
    │   └── __init__.py
    ├── searchers/
    │   └── __init__.py
    └── utils/
        └── __init__.py
```

---

### Fase 1: Core + Query System ✅ CONCLUÍDA

**Objetivo:** Migrar entidades e separar responsabilidades do Query system

#### 1.1. Core Entities ✅

**Migração literal (copiar e colar):**
- [✅] `findpapers_0/exceptions.py` → `findpapers/exceptions.py`
- [✅] `findpapers_0/models/paper.py` → `findpapers/core/paper.py`
- [✅] `findpapers_0/models/publication.py` → `findpapers/core/publication.py`
- [✅] `findpapers_0/models/search.py` → `findpapers/core/search.py`

**Criar testes:**
- [✅] `tests/unit/core/test_models.py` (migrado e adaptado de tests_0/)

**Utils migradas:**
- [✅] `findpapers/utils/merge.py`
- [✅] `findpapers/utils/export.py`
- [✅] `findpapers/utils/version.py`

#### 1.2. Query Structures ✅

**Criar `findpapers/core/query.py` com apenas estruturas:**
- [✅] Extrair `NodeType`, `ConnectorType` enums
- [✅] Extrair `QueryNode` dataclass (campos + to_dict/from_dict)
  - `node_type`, `value`, `children`, `filter_code`, `inherited_filter_code`, `children_match_filter`
- [✅] Extrair `Query` dataclass (root + raw_query)
- [✅] Extrair `QueryValidationError` exception

**NÃO incluir:**
- ❌ Lógica de validação (vai para query/validator.py)
- ❌ Lógica de parsing (vai para query/parser.py)
- ❌ Lógica de propagação (vai para query/propagator.py)

#### 1.3. Query Components (Separar Responsabilidades) ✅

**Criar `findpapers/query/validator.py`:**
- [✅] Classe `QueryValidator`
- [✅] Extrair toda validação de `findpapers_0/models/query.py`
  - `_validate_brackets()`
  - `_validate_wildcards()`
  - `_validate_connectors()`
  - Outros métodos de validação
- [✅] Método público: `validate(query_str: str) -> None` (raises QueryValidationError)

**Criar `findpapers/query/parser.py`:**
- [✅] Classe `QueryParser`
- [✅] Extrair parsing de `findpapers_0/models/query.py`
  - `_parse_query()`, parsing recursivo
  - Lógica de identificar termos, conectores, grupos, filtros
- [✅] Método público: `parse(query_str: str) -> Query`

**Criar `findpapers/query/propagator.py`:**
- [✅] Classe `FilterPropagator`
- [✅] Extrair `propagate_filters()` de QueryNode
- [✅] Método público: `propagate(query: Query) -> Query`

**Criar testes:**
- [✅] `tests/unit/query/test_validator.py`
- [✅] `tests/unit/query/test_parser.py`
- [✅] `tests/unit/query/test_propagator.py`
- [✅] `tests/unit/utils/test_merge.py`

**Critério de conclusão Fase 1:**
```bash
make test PYTEST_ARGS='tests/unit/'  # ✅ 59 testes passando, coverage 74%
```

---

### Fase 2: Query Builders (Implementar do Zero) 🔧

**Objetivo:** Implementar lógica de conversão de queries seguindo query-build-plan.md

**🚨 AVISO IMPORTANTE:** Os arquivos em `findpapers_0/searchers/*.py` são apenas **placeholders sem lógica real**. **NÃO extrair código** deles. Toda a lógica de **builders** e **searchers** deve ser **implementada do zero** seguindo as especificações detalhadas no [query-build-plan.md](query-build-plan.md).

**Referência:** Especificações completas no [query-build-plan.md](query-build-plan.md)

#### 2.1. Interface QueryBuilder ⏳

**Criar `findpapers/query/builder.py`:**
```python
from abc import ABC, abstractmethod
from typing import List, Union, Dict
from findpapers.core.query import Query

class QueryValidationResult:
    """Result of query validation."""
    is_valid: bool
    error_message: str | None = None

class QueryBuilder(ABC):
    """Abstract base class for database-specific query builders."""
    
    @abstractmethod
    def validate_query(self, query: Query) -> QueryValidationResult:
        """Validate if this builder supports the given query.
        
        Returns
        -------
        QueryValidationResult
            Whether the query is valid for this database.
        """
        pass
    
    @abstractmethod
    def convert_query(self, query: Query) -> Union[str, Dict]:
        """Convert Query to database-specific format.
        
        Returns
        -------
        str | Dict
            Query string for URL-based APIs or dict for REST APIs.
        """
        pass
    
    @abstractmethod
    def preprocess_terms(self, query: Query) -> Query:
        """Preprocess query terms (e.g., replace '-' with space for arXiv).
        
        Returns
        -------
        Query
            Query with preprocessed terms.
        """
        pass
    
    @abstractmethod
    def supports_filter(self, filter_code: str) -> bool:
        """Check if this builder supports a specific filter code.
        
        Parameters
        ----------
        filter_code : str
            Filter code (ti, abs, key, au, pu, af, tiabs, tiabskey).
        
        Returns
        -------
        bool
            True if supported, False otherwise.
        """
        pass
    
    @abstractmethod
    def expand_query(self, query: Query) -> List[Query]:
        """Expand query into multiple queries if needed (bioRxiv/medRxiv).
        
        Returns
        -------
        List[Query]
            List with original query, or multiple queries if expansion needed.
        """
        pass
```

#### 2.2. Implementar Builders (Do Zero) ⏳

**⚠️ IMPORTANTE:** Os arquivos em `findpapers_0/searchers/*.py` são apenas **placeholders**. NÃO extrair código deles. Toda a lógica de builders deve ser **implementada do zero** seguindo as especificações detalhadas no [query-build-plan.md](query-build-plan.md).

Para cada builder, seguir especificações completas em [query-build-plan.md](query-build-plan.md):

**Builders a implementar (do zero):**
- [ ] `query/builders/arxiv.py` - ArxivQueryBuilder
  - Implementar seguindo [query-build-plan.md - arXiv](query-build-plan.md#arxiv)
  - Conversão: `ti:`, `abs:`, `au:`, `all:`
  - Operadores: `AND`, `OR`, `ANDNOT`
  - Wildcards: `?` e `*`
  - Pré-processamento: substituir `-` por espaço
  - Parênteses: URL encode `%28` `%29`
  - Retorna: query string

- [ ] `query/builders/pubmed.py` - PubmedQueryBuilder
  - Implementar seguindo [query-build-plan.md - PubMed](query-build-plan.md#pubmed)
  - Conversão: `[ti]`, `[tiab]`, `[au]`, `[mh]`, `[journal]`, `[ad]`
  - Operadores: `AND`, `OR`, `NOT`
  - Wildcards: apenas `*` (não `?`)
  - Retorna: query string

- [ ] `query/builders/ieee.py` - IEEEQueryBuilder
  - Implementar seguindo [query-build-plan.md - IEEE](query-build-plan.md#ieee-xplore)
  - Conversão: `article_title`, `abstract`, `author`, `index_terms`
  - Operadores: `AND`, `OR`, `NOT`
  - Wildcards: `*` (mín 3 chars antes)
  - Retorna: dict de parâmetros

- [ ] `query/builders/scopus.py` - ScopusQueryBuilder
  - Implementar seguindo [query-build-plan.md - Scopus](query-build-plan.md#scopus)
  - Conversão: `TITLE()`, `ABS()`, `KEY()`, `AUTH()`, `AFFIL()`, `SRCTITLE()`, `TITLE-ABS-KEY()`
  - Operadores: `AND`, `OR`, `AND NOT`
  - Wildcards: `?` e `*`
  - Retorna: query string

- [ ] `query/builders/biorxiv.py` - BiorxivQueryBuilder
  - Implementar seguindo [query-build-plan.md - bioRxiv](query-build-plan.md#biorxiv)
  - Apenas `abstract_title` (nativo)
  - Operadores: `AND` via match-all, `OR` via match-any
  - Query expansion: converte queries complexas em múltiplas simples
  - Warning se >20 combinações
  - Retorna: lista de dicts de parâmetros

- [ ] `query/builders/medrxiv.py` - MedrxivQueryBuilder
  - Implementar seguindo [query-build-plan.md - medRxiv](query-build-plan.md#medrxiv)
  - Mesmas regras do bioRxiv (compartilham API)

- [ ] `query/builders/openalex.py` - OpenAlexQueryBuilder
  - Implementar seguindo [query-build-plan.md - OpenAlex](query-build-plan.md#openalex)
  - Conversão: `title.search`, `abstract.search`, `authorships.author.display_name.search`, etc.
  - Operadores: `,` (AND), `|` (OR), `!` (NOT)
  - Retorna: dict de parâmetros
  - Suporte a filtros: ti, abs, au, pu, af, tiabs, tiabskey

- [ ] `query/builders/semantic_scholar.py` - SemanticScholarQueryBuilder
  - Implementar seguindo [query-build-plan.md - Semantic Scholar](query-build-plan.md#semantic-scholar)
  - Conversão: `query` (tiabs nativo), filters para venue, author
  - Operadores: `+` (AND), `|` (OR), `-` (NOT) via bulk search
  - Retorna: dict ou str dependendo do endpoint
  - Suporte limitado: tiabs (nativo), pu e au (via filters)

**Criar testes:**
- [ ] `tests/unit/query/builders/test_arxiv_builder.py`
- [ ] `tests/unit/query/builders/test_pubmed_builder.py`
- [ ] `tests/unit/query/builders/test_ieee_builder.py`
- [ ] `tests/unit/query/builders/test_scopus_builder.py`
- [ ] `tests/unit/query/builders/test_biorxiv_builder.py`
- [ ] `tests/unit/query/builders/test_medrxiv_builder.py`
- [ ] `tests/unit/query/builders/test_openalex_builder.py` 🆕
- [ ] `tests/unit/query/builders/test_semantic_scholar_builder.py` 🆕

**Usar dados de `tests/data/` (copiar de tests_0/) para testes offline**

**Critério de conclusão Fase 2:**
```bash
make test PYTEST_ARGS='tests/unit/query/builders/'  # Todos passando
```

---

### Fase 3: Searchers (Implementar do Zero) 🔍

**Objetivo:** Implementar searchers usando QueryBuilders injetados seguindo query-build-plan.md

**🚨 AVISO IMPORTANTE:** Os arquivos em `findpapers_0/searchers/*.py` são apenas **placeholders sem lógica real**. **NÃO usar código** deles. Toda a lógica de **searchers** deve ser **implementada do zero** seguindo as especificações detalhadas no [query-build-plan.md](query-build-plan.md).

**⚠️ RATE LIMITING:** Cada searcher DEVE implementar rate limiting adequado consultando a documentação oficial da API correspondente. Isso evita bloqueios e garante uso responsável das APIs públicas.

#### 3.1. Base Searcher ⏳

- [ ] Migrar `findpapers_0/searchers/base.py` → `findpapers/searchers/base.py`
  - Manter interface ABC
  - Método `search(query: Query, max_papers: int | None = None, progress_callback: Callable | None = None) -> List[Paper]`
  - `progress_callback(current: int, total: int | None)` - chamado durante paginação

#### 3.2. Implementar Searchers (Do Zero) ⏳

**⚠️ IMPORTANTE:** Os arquivos em `findpapers_0/searchers/*.py` são apenas **placeholders**. NÃO usar código deles. Toda a lógica de searchers deve ser **implementada do zero** seguindo as especificações do [query-build-plan.md](query-build-plan.md).

**Para cada searcher:**
1. **Implementar** do zero seguindo query-build-plan.md
2. **Injetar** QueryBuilder via `__init__`
3. **Aceitar `api_key` opcional** no `__init__` (quando aplicável: IEEE, Scopus, PubMed, OpenAlex, Semantic Scholar)
4. **Usar** `self.query_builder.validate_query()` antes de buscar
5. **Usar** `self.query_builder.convert_query()` para obter query convertida
6. **Implementar rate limiting:**
   - Verificar documentação da API para limites de requisições
   - Implementar delay entre requisições quando necessário
   - Respeitar quotas (ex: PubMed 3 req/s, Semantic Scholar 100 req/5min)
7. **Aceitar parâmetro `max_papers`:**
   - Limitar quantidade de papers retornados
   - Vem do runner via `max_papers_per_database`
8. **Aceitar `progress_callback` opcional:**
   - Chamar `progress_callback(current, total)` durante paginação
   - Permite runner atualizar barra de progresso tqdm
9. **Ordenar por data (quando possível):**
   - Sempre que a API suportar, ordenar do mais recente para o mais antigo
   - Garante que `max_papers` retorne os papers mais recentes
10. **Focar** em: HTTP request → parse response → return Papers

**Padrão de implementação:**
```python
# findpapers/searchers/arxiv.py (IMPLEMENTAR DO ZERO)
import time
from typing import List, Callable

class ArxivSearcher(SearcherBase):
    # Rate limiting: arXiv não especifica limite, mas ser educado (1 req/s)
    MIN_REQUEST_INTERVAL = 1.0  # segundos entre requisições
    
    def __init__(self, query_builder: ArxivQueryBuilder, api_key: str | None = None):
        self.query_builder = query_builder
        self.api_key = api_key  # arXiv não usa, mas manter interface consistente
        self.last_request_time = 0
    
    def search(
        self,
        query: Query,
        max_papers: int | None = None,
        progress_callback: Callable[[int, int | None], None] | None = None
    ) -> List[Paper]:
        # Valida primeiro
        validation = self.query_builder.validate_query(query)
        if not validation.is_valid:
            logger.warning(f"arXiv: {validation.error_message}")
            return []  # Skip este searcher
        
        # Converte usando builder
        arxiv_query = self.query_builder.convert_query(query)
        
        # Busca com paginação e progress callback
        papers = []
        offset = 0
        page_size = 100  # arXiv max per request
        
        while True:
            # Rate limiting: delay se necessário
            elapsed = time.time() - self.last_request_time
            if elapsed < self.MIN_REQUEST_INTERVAL:
                time.sleep(self.MIN_REQUEST_INTERVAL - elapsed)
            
            # Faz requisição com ordenação por data
            response = self._make_request(
                arxiv_query,
                start=offset,
                max_results=min(page_size, max_papers - len(papers) if max_papers else page_size),
                sort_by='submittedDate',
                sort_order='descending'
            )
            self.last_request_time = time.time()
            
            # Parseia batch
            batch = self._parse_response(response)
            if not batch:
                break
            
            papers.extend(batch)
            
            # Atualiza progresso
            if progress_callback:
                total = response.get('total_results')  # Se API fornecer
                progress_callback(len(papers), total)
            
            # Verifica limites
            if max_papers and len(papers) >= max_papers:
                break
            if len(batch) < page_size:  # Última página
                break
            
            offset += len(batch)
        
        return papers[:max_papers] if max_papers else papers
```

**Searchers a implementar (do zero):**
- [ ] `searchers/arxiv.py`
  - Implementar seguindo [query-build-plan.md - arXiv](query-build-plan.md#arxiv)
  - Injetar `ArxivQueryBuilder` via DI
  - Sem API key necessária
  - Base URL: `http://export.arxiv.org/api/query`
  - Rate limit: ~1 req/s (não especificado oficialmente, ser educado)
  - Ordenação: `sortBy=submittedDate&sortOrder=descending`
  - Max results: `max_results` parameter
  
- [ ] `searchers/pubmed.py`
  - Implementar seguindo [query-build-plan.md - PubMed](query-build-plan.md#pubmed)
  - Injetar `PubmedQueryBuilder` via DI
  - **Aceitar `api_key` opcional** (aumenta rate limit de 3 para 10 req/s)
  - Base URL: `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/`
  - Rate limit: 3 req/s sem API key, 10 req/s com API key
  - Ordenação: `sort=pub_date` (mais recente primeiro)
  - Max results: `retmax` parameter
  
- [ ] `searchers/ieee.py`
  - Implementar seguindo [query-build-plan.md - IEEE](query-build-plan.md#ieee-xplore)
  - Injetar `IEEEQueryBuilder` via DI
  - **Aceitar `api_key` obrigatória** (IEEE requer API key)
  - Base URL: `https://ieeexploreapi.ieee.org/api/v1/search/articles`
  - Rate limit: 200 calls/day (gestão cuidadosa)
  - Ordenação: `sort_field=publication_year&sort_order=desc`
  - Max results: `max_records` parameter (max 200 por request)
  
- [ ] `searchers/scopus.py`
  - Implementar seguindo [query-build-plan.md - Scopus](query-build-plan.md#scopus)
  - Injetar `ScopusQueryBuilder` via DI
  - **Aceitar `api_key` obrigatória** (Scopus requer API key)
  - Base URL: `https://api.elsevier.com/content/search/scopus`
  - Rate limit: Varia por instituição (tipicamente 2-9 req/s)
  - Ordenação: `sort=-coverDate` (mais recente primeiro)
  - Max results: `count` parameter (max 25 por request, paginar se necessário)
  
- [ ] `searchers/biorxiv.py`
  - Implementar seguindo [query-build-plan.md - bioRxiv](query-build-plan.md#biorxiv)
  - Injetar `BiorxivQueryBuilder` via DI
  - Sem API key necessária
  - Base URL: `https://api.biorxiv.org/details/biorxiv/`
  - Rate limit: Não especificado, usar ~1 req/s
  - Ordenação: Já retorna por data (desc), sem parâmetro específico
  - Max results: Limitar após receber resposta (API retorna max 100 por request)
  
- [ ] `searchers/medrxiv.py`
  - Implementar seguindo [query-build-plan.md - medRxiv](query-build-plan.md#medrxiv)
  - Injetar `MedrxivQueryBuilder` via DI
  - Sem API key necessária
  - Base URL: `https://api.biorxiv.org/details/medrxiv/`
  - Rate limit: Não especificado, usar ~1 req/s
  - Ordenação: Já retorna por data (desc), sem parâmetro específico
  - Max results: Limitar após receber resposta (API retorna max 100 por request)
  
- [ ] `searchers/rxiv.py`
  - Base interna compartilhada por bioRxiv/medRxiv
  - Implementar lógica de HTTP request e parsing
  - Rate limiting compartilhado (~1 req/s para ambos)
  - Ordenação e max_papers delegados aos searchers específicos

- [ ] `searchers/openalex.py`
  - Implementar seguindo [query-build-plan.md - OpenAlex](query-build-plan.md#openalex)
  - Injetar `OpenAlexQueryBuilder` via DI
  - **Aceitar `api_key` opcional** (melhora rate limits e acesso premium)
  - Alternativamente: passar email no User-Agent para polite pool
  - Base URL: `https://api.openalex.org/works`
  - Rate limit: 100k req/day (polite pool com email), ~10 req/s
  - Ordenação: `sort=publication_date:desc`
  - Max results: `per-page` parameter (max 200 por request, paginar se necessário)

- [ ] `searchers/semantic_scholar.py`
  - Implementar seguindo [query-build-plan.md - Semantic Scholar](query-build-plan.md#semantic-scholar)
  - Injetar `SemanticScholarQueryBuilder` via DI
  - **Aceitar `api_key` opcional** (aumenta rate limit para 1 req/s)
  - Base URL: `https://api.semanticscholar.org/graph/v1/`
  - Rate limit: 100 req/5min (1 req/3s), 1 req/s com API key
  - Ordenação: `sort=publicationDate:desc` (disponível em alguns endpoints)
  - Max results: `limit` parameter (max 100 por request)
  - Usar bulk search se query complexa

**Criar testes:**
- [ ] `tests/unit/searchers/test_arxiv_searcher.py` (com mock de builder)
- [ ] `tests/unit/searchers/test_pubmed_searcher.py`
- [ ] `tests/unit/searchers/test_ieee_searcher.py`
- [ ] `tests/unit/searchers/test_scopus_searcher.py`
- [ ] `tests/unit/searchers/test_biorxiv_searcher.py`
- [ ] `tests/unit/searchers/test_medrxiv_searcher.py`
- [ ] `tests/unit/searchers/test_openalex_searcher.py` 🆕
- [ ] `tests/unit/searchers/test_semantic_scholar_searcher.py` 🆕

**Critério de conclusão Fase 3:**
```bash
make test PYTEST_ARGS='tests/unit/searchers/'  # Todos passando
```

---

### Fase 4: Runners + Utils 🏃

**Objetivo:** Atualizar Runners para usar novos componentes, organizar utils

#### 4.1. Atualizar SearchRunner ⏳

- [ ] Migrar e refatorar `findpapers_0/runners/search_runner.py` → `findpapers/runners/search_runner.py`
  - **Interface simples:** Usar apenas tipos nativos Python (str, int, list, bool, etc)
    - Usuário NÃO deve instanciar Query, QueryBuilder, Searcher, etc
    - Tudo configurado via parâmetros simples do `__init__`
  - **Injetar** `QueryParser`, `QueryValidator` no `__init__`
  - **Aceitar** `max_papers_per_database` no `__init__` (passar para searchers)
  - **Aceitar API keys opcionais:**
    - `ieee_api_key: str | None = None`
    - `scopus_api_key: str | None = None`
    - `pubmed_api_key: str | None = None`
    - `openalex_api_key: str | None = None`
    - `semantic_scholar_api_key: str | None = None`
    - Passar para searchers via constructor
  - **Aceitar** `parallel: bool = False` para busca paralela em databases
  - **Barra de progresso:**
    - Usar `tqdm` para mostrar progresso de coleta
    - Descrição: `{database_name}: {papers_coletados}/{papers_totais}`
    - Uma barra por database (ou barra única se parallel=True)
  - **Instanciar** searchers com builders injetados (importar de findpapers.query.builders)
  - **Pipeline como métodos privados:**
    - `_fetch()` - busca em múltiplos searchers (passando `max_papers_per_database`)
    - `_filter()` - filtra por publication type
    - `_deduplicate()` - dedupe + merge usando `utils.merge`
    - `_flag_predatory()` - marca predatory usando `utils.predatory`
  - **Exports usando helpers:**
    - `to_json()` → usa `utils.export.to_json_format()`
    - `to_csv()` → usa `utils.export.to_csv_format()`
    - `to_bibtex()` → usa `utils.export.to_bibtex_format()`
  - **Manter API pública do REFACTORING_PLAN.md**

**Instanciação de searchers (exemplo):**
```python
from findpapers.query.builders.arxiv import ArxivQueryBuilder
from findpapers.query.builders.pubmed import PubmedQueryBuilder
from tqdm import tqdm
import concurrent.futures
# ... outros imports

class SearchRunner:
    def __init__(
        self,
        query: str,
        databases: list[str] | None = None,
        max_papers_per_database: int | None = None,
        publication_types: list[str] | None = None,
        since: int | None = None,
        until: int | None = None,
        # API Keys opcionais
        ieee_api_key: str | None = None,
        scopus_api_key: str | None = None,
        pubmed_api_key: str | None = None,
        openalex_api_key: str | None = None,
        semantic_scholar_api_key: str | None = None,
        # Paralelização
        parallel: bool = False,
        **kwargs
    ):
        # Parse e valida query
        self.query_validator = QueryValidator()
        self.query_parser = QueryParser()
        self.query_validator.validate(query)
        self.query = self.query_parser.parse(query)
        
        # Armazena configurações
        self.max_papers_per_database = max_papers_per_database
        self.parallel = parallel
        
        # Instancia searchers com builders (passando API keys)
        searcher_map = {
            'arxiv': ArxivSearcher(ArxivQueryBuilder()),
            'pubmed': PubmedSearcher(PubmedQueryBuilder(), api_key=pubmed_api_key),
            'ieee': IEEESearcher(IEEEQueryBuilder(), api_key=ieee_api_key),
            'scopus': ScopusSearcher(ScopusQueryBuilder(), api_key=scopus_api_key),
            'biorxiv': BiorxivSearcher(BiorxivQueryBuilder()),
            'medrxiv': MedrxivSearcher(MedrxivQueryBuilder()),
            'openalex': OpenAlexSearcher(OpenAlexQueryBuilder(), api_key=openalex_api_key),
            'semantic_scholar': SemanticScholarSearcher(
                SemanticScholarQueryBuilder(),
                api_key=semantic_scholar_api_key
            ),
        }
        
        # Filtra databases solicitadas
        self.searchers = [
            searcher_map[db] for db in (databases or searcher_map.keys())
            if db in searcher_map
        ]
    
    def _fetch(self) -> list[Paper]:
        """Busca papers em todos os searchers."""
        all_papers = []
        
        if self.parallel:
            # Busca paralela com ThreadPoolExecutor
            with concurrent.futures.ThreadPoolExecutor() as executor:
                futures = {
                    executor.submit(
                        self._fetch_from_searcher,
                        searcher,
                        searcher.__class__.__name__.replace('Searcher', '').lower()
                    ): searcher
                    for searcher in self.searchers
                }
                for future in tqdm(
                    concurrent.futures.as_completed(futures),
                    total=len(self.searchers),
                    desc="Fetching papers"
                ):
                    papers = future.result()
                    all_papers.extend(papers)
        else:
            # Busca sequencial com tqdm por database
            for searcher in self.searchers:
                db_name = searcher.__class__.__name__.replace('Searcher', '')
                papers = self._fetch_from_searcher(searcher, db_name)
                all_papers.extend(papers)
        
        return all_papers
    
    def _fetch_from_searcher(self, searcher, db_name: str) -> list[Paper]:
        """Busca papers de um searcher com barra de progresso."""
        # Callback para atualizar tqdm durante paginação
        papers = []
        with tqdm(desc=f"{db_name}: 0/?", leave=True) as pbar:
            # Searcher deve chamar callback(current, total) durante fetch
            def progress_callback(current: int, total: int | None):
                pbar.set_description(f"{db_name}: {current}/{total or '?'}")
                pbar.update(1)
            
            papers = searcher.search(
                self.query,
                max_papers=self.max_papers_per_database,
                progress_callback=progress_callback
            )
        
        return papers
        
        # ...
```

#### 4.2. Atualizar Outros Runners ⏳

- [ ] Migrar `findpapers_0/runners/enrichment_runner.py` → `findpapers/runners/enrichment_runner.py`
  - Manter API pública
  - Usar helpers de `utils/` conforme necessário

- [ ] Migrar `findpapers_0/runners/download_runner.py` → `findpapers/runners/download_runner.py`
  - Manter API pública
  - Usar `utils.download` para web scraping

#### 4.3. Organizar Utils ⏳

- [ ] Criar `findpapers/utils/export.py`
  - Funções: `to_json_format()`, `to_csv_format()`, `to_bibtex_format()`
  - Extrair de `findpapers_0/runners/search_runner.py`
  - **NÃO são classes, apenas funções**

- [ ] Migrar `findpapers_0/utils/merge_util.py` → `findpapers/utils/merge.py`
  - Lógica de dedupe + "most complete" merge

- [ ] Criar `findpapers/utils/predatory.py`
  - Migrar de `findpapers_0/utils/predatory_data.py` + `predatory_util.py`
  - Consolidar em um arquivo

- [ ] Migrar `findpapers_0/utils/parallel_util.py` → `findpapers/utils/parallel.py`

- [ ] Migrar `findpapers_0/utils/version_util.py` → `findpapers/utils/version.py`

- [ ] Criar `findpapers/utils/download.py`
  - Web scraping helpers baseados em DOIs
  - Migrar lógica de download de `findpapers_0/`

- [ ] Migrar `findpapers_0/utils/enrichment_util.py` → `findpapers/utils/enrichment.py`

**Adicionar dependências:**
- [ ] Adicionar `tqdm` ao `pyproject.toml` (barra de progresso)
  - `venv/bin/poetry add tqdm`

**Criar testes:**
- [ ] `tests/unit/runners/test_search_runner.py`
- [ ] `tests/unit/runners/test_enrichment_runner.py`
- [ ] `tests/unit/runners/test_download_runner.py`
- [ ] `tests/unit/utils/test_export.py`
- [ ] `tests/unit/utils/test_merge.py`
- [ ] `tests/unit/utils/test_predatory.py`
- [ ] `tests/unit/utils/test_parallel.py`
- [ ] `tests/unit/utils/test_download.py`
- [ ] `tests/unit/utils/test_enrichment.py`

**Critério de conclusão Fase 4:**
```bash
make test PYTEST_ARGS='tests/unit/runners/ tests/unit/utils/'  # Todos passando
```

---

### Fase 5: Testes Integrados + API Pública 🧪

**Objetivo:** Garantir que tudo funciona end-to-end

#### 5.1. Atualizar API Pública ⏳

- [ ] Criar `findpapers/__init__.py`
```python
"""Findpapers - Academic paper search and management tool."""

from findpapers.runners.search_runner import SearchRunner
from findpapers.runners.enrichment_runner import EnrichmentRunner
from findpapers.runners.download_runner import DownloadRunner
from findpapers.exceptions import SearchRunnerNotExecutedError

__all__ = [
    'SearchRunner',
    'EnrichmentRunner',
    'DownloadRunner',
    'SearchRunnerNotExecutedError',
]
```

#### 5.2. Testes de Integração ⏳

- [ ] `tests/integration/test_search_flow.py`
  - Testar fluxo: parse → validate → search → filter → dedupe → flag → export
  - Usar mocks de HTTP responses (dados de tests/data/)
  - Testar com múltiplos databases
  - Testar exports (JSON, CSV, BibTeX)

- [ ] `tests/integration/test_enrichment_flow.py`
  - Testar enrichment completo
  - Parallelism e timeouts

- [ ] `tests/integration/test_download_flow.py`
  - Testar download completo
  - Parallelism e timeouts

- [ ] `tests/integration/test_api_public.py`
  - Testar API pública (import from findpapers)
  - Testar todos métodos públicos
  - Testar SearchRunnerNotExecutedError

#### 5.3. Migrar Dados de Teste ⏳

- [ ] Copiar `tests_0/data/` → `tests/data/`
  - Samples de respostas de cada database
  - arquiv/, pubmed/, ieee/, scopus/, biorxiv/, medrxiv/

- [ ] Adicionar dados para novos searchers:
  - `tests/data/openalex/` 🆕
  - `tests/data/semanticscholar/` 🆕

**Critério de conclusão Fase 5:**
```bash
make test  # TODOS os testes (unit + integration) passando
```

---

### Fase 6: Documentação + Limpeza Final 📚

**Objetivo:** Finalizar migração e remover código legado

#### 6.1. Documentação ⏳

- [ ] Atualizar `README.md`
  - Exemplos de uso com SearchRunner
  - **Interface simples:** Destacar que não é necessário instanciar objetos complexos
  - Lista completa de databases suportados (8 databases)
  - Exemplos de queries com filtros: `ti[machine learning]`, `abs(covid OR pandemic)`, etc.
  - Instruções de instalação e setup
  - **Documentar parâmetros:**
    - `max_papers_per_database`
    - `ieee_api_key`, `scopus_api_key`, `pubmed_api_key`, `openalex_api_key`, `semantic_scholar_api_key`
    - `parallel` para busca paralela
  - **Barra de progresso tqdm:** Explicar feedback visual durante coleta
  - Explicar rate limiting e boas práticas de uso das APIs

- [ ] Atualizar `CONTRIBUTING.md`
  - Mencionar estrutura SOLID
  - Explicar como adicionar novo database:
    1. Criar builder em `query/builders/nome.py`
    2. Criar searcher em `searchers/nome.py`
    3. Adicionar no `SearchRunner` searcher_map
    4. Escrever testes

- [ ] Criar `docs/architecture.md` 🆕
  - Explicar estrutura SOLID (searchers flat, builders nested em query/)
  - Diagrama de componentes
  - Fluxo de dados: Query → Parser → Validator → Searchers → Pipeline → Results
  - Dependency Injection: Searchers ← Builders
  - Como funciona query expansion (bioRxiv/medRxiv)
  - Rate limiting por database (tabela com limites de cada API)
  - Ordenação por data e max_papers
  - **Interface simples:** Design decision de usar apenas tipos nativos Python
  - **Paralelização:** Como funciona busca paralela vs sequencial
  - **Progress tracking:** Implementação com tqdm e callbacks

- [ ] Atualizar docstrings
  - Todos métodos públicos com type hints completos
  - Seguir Numpy Docstring Style Guide
  - Exemplos em docstrings quando útil

- [ ] Marcar REFACTORING_PLAN.md e query-build-plan.md como ✅ CONCLUÍDO
  - Adicionar nota no topo: "Este plano foi concluído. Veja REFACTORING_PLAN_v2.md para histórico."

- [ ] Criar `MIGRATION_NOTES.md` 🆕
  - Documentar mudanças breaking (API não é retrocompatível)
  - Guia de migração da API antiga para nova
  - Exemplos before/after

#### 6.2. Limpeza Final ⏳

- [ ] Verificar que não há imports de `findpapers_0`, `findpapers_old`, `tests_0`, `tests_old`
- [ ] Remover `findpapers_0/`
- [ ] Remover `findpapers_old/`
- [ ] Remover `tests_0/`
- [ ] Remover `tests_old/`
- [ ] Remover arquivos temporários:
  - `_ignore_*.md` (mover para `docs/planning/` se quiser preservar histórico)
  - `_ignore_*.py`, `_ignore_*.json`

#### 6.3. Validação Final ⏳

- [ ] `make lint` - 100% sem erros
- [ ] `make test` - 100% dos testes passando
- [ ] Coverage ≥ 90%
  ```bash
  make test PYTEST_ARGS='--cov=findpapers --cov-report=term-missing --cov-report=html'
  ```
- [ ] Testar instalação limpa:
  ```bash
  rm -rf venv/
  make setup
  venv/bin/poetry install
  make test
  ```
- [ ] Testar API pública com exemplos do README:
  ```python
  from findpapers import SearchRunner
  
  runner = SearchRunner(
      query="ti[machine learning] AND abs[deep learning]",
      databases=['arxiv', 'pubmed', 'ieee', 'scopus', 'openalex'],
      publication_types=['journal-article', 'conference-paper'],
      max_papers_per_database=10,  # Retorna 10 papers mais recentes de cada base
      since=2020,
      until=2024,
      # API Keys opcionais (aumentam rate limits)
      ieee_api_key='your_ieee_key',
      scopus_api_key='your_scopus_key',
      pubmed_api_key='your_pubmed_key',
      openalex_api_key='your_openalex_key',
      # Busca paralela (mais rápida, padrão False)
      parallel=True
  )
  
  runner.run(verbose=True)  # Mostra barras de progresso tqdm
  results = runner.get_results()
  runner.to_json('results.json')
  runner.to_csv('results.csv')
  runner.to_bibtex('results.bib')
  ```

**Critério de conclusão Fase 6:**
- Código limpo, documentado, testado
- API pública funcional
- Coverage ≥ 90%
- Todos diretórios legados removidos

---

## 📊 Tracking de Progresso

### Status Geral
- [✅] **Fase 0:** Limpeza e Preparação (100%) ✅ CONCLUÍDA
- [✅] **Fase 1:** Core + Query System (100%) ✅ CONCLUÍDA - 59 testes passando
- [ ] **Fase 2:** Query Builders (0%)
- [ ] **Fase 3:** Searchers com DI (0%)
- [ ] **Fase 4:** Runners + Utils (0%)
- [ ] **Fase 5:** Testes Integrados + API (0%)
- [ ] **Fase 6:** Documentação + Limpeza Final (0%)

**Progresso Total: ~29%** (2/7 fases completas)

**Fase 1 Resultados:**
- ✅ 59 testes unitários passando
- ✅ 74% de cobertura de código
- ✅ Core entities migradas (Paper, Publication, Search, exceptions)
- ✅ Query system separado (Validator, Parser, Propagator)
- ✅ Utils básicos migrados (merge, export, version)

---

## 🎯 Critérios de Sucesso Final

✅ **Funcionalidade:**
- [ ] SearchRunner, EnrichmentRunner, DownloadRunner funcionais
- [ ] 8 databases suportados: arXiv, PubMed, IEEE, Scopus, bioRxiv, medRxiv, OpenAlex, Semantic Scholar
- [ ] Query system com árvore (QueryNode) completo
- [ ] Pipeline: fetch → filter → dedupe → predatory → export
- [ ] Exports: JSON, CSV, BibTeX
- [ ] Rate limiting implementado em todos searchers
- [ ] max_papers_per_database funcionando com ordenação por data
- [ ] API keys opcionais (IEEE, Scopus, PubMed, OpenAlex, Semantic Scholar)
- [ ] Barra de progresso com tqdm (papers_coletados/papers_totais por database)
- [ ] Busca paralela opcional (parallel=True/False)

✅ **Qualidade:**
- [ ] 100% testes passando
- [ ] Coverage ≥ 90%
- [ ] Lint 100% limpo
- [ ] Type hints completos
- [ ] Docstrings com Numpy style

✅ **Arquitetura:**
- [ ] Estrutura SOLID simplificada
- [ ] QueryBuilders separados (1 por database)
- [ ] Searchers com DI dos builders
- [ ] Query components separados (Parser, Validator, Propagator)
- [ ] Utils organizados (export, merge, predatory, etc.)

✅ **Documentação:**
- [ ] README atualizado com exemplos
- [ ] CONTRIBUTING atualizado
- [ ] docs/architecture.md criado
- [ ] MIGRATION_NOTES.md criado

✅ **Limpeza:**
- [ ] Todos diretórios legados removidos
- [ ] Arquivos temporários removidos
- [ ] Sem imports quebrados

---

## 📝 Notas Importantes

### Por que este plano é diferente?

1. **Linear:** Não há refacts aninhados. Uma sequência clara de 6 fases.
2. **Unificado:** Combina query system + SOLID + novos searchers em um único fluxo.
3. **Base sólida:** Usa `findpapers_0/` como base (query system já implementado).
4. **Pragmático:** SOLID onde faz sentido (builders, searchers), simplicidade onde não faz (pipeline, exports).
5. **Completo:** Inclui OpenAlex e Semantic Scholar desde o início.
6. **Não retrocompatível:** Liberdade total para quebrar API e reconstruir.
7. **Interface simples:** Usuário trabalha apenas com tipos nativos Python (str, int, list, bool).
8. **Feedback visual:** Barra de progresso tqdm mostra coleta em tempo real.
9. **Flexível:** Busca sequencial (padrão) ou paralela (mais rápida).

### Ordem de execução

As fases **devem** ser executadas em ordem:
1. **Fase 0** primeiro (limpar terreno)
2. **Fase 1** antes de Fase 2 (estruturas antes de builders)
3. **Fase 2** antes de Fase 3 (builders antes de searchers)
4. **Fases 1-3** antes de Fase 4 (componentes antes de runners)
5. **Fases 1-4** antes de Fase 5 (código antes de testes integrados)
6. **Fase 6** por último (documentação e limpeza)

Dentro de cada fase, subtarefas podem ser feitas em paralelo ou em qualquer ordem.

### Como trackear progresso

Marcar checkboxes `- [ ]` → `- [✅]` conforme concluir tarefas.

Atualizar "Status Geral" no topo após concluir cada fase.

---

**Última atualização:** 8 de fevereiro de 2026  
**Status:** ✅ Fase 0 concluída, pronto para Fase 1  
**Próximo passo:** Executar Fase 1.1 - Migrar Core Entities

**Novos requisitos adicionados:**
- ✅ Interface simples (apenas tipos nativos Python)
- ✅ API keys opcionais (ieee_api_key, scopus_api_key, pubmed_api_key, semantic_scholar_api_key)
- ✅ Barra de progresso tqdm (papers_coletados/papers_totais)
- ✅ Busca paralela opcional (parallel=True/False)
