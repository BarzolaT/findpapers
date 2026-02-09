# Cleanup Notes - Histórico de Versões

**Data:** 8 de fevereiro de 2026  
**Motivo:** Desempilhar 3 refactorings incompletos e criar plano unificado

---

## 📂 Versões Encontradas

### findpapers_0/ ✅ BASE VÁLIDA
**Status:** Código funcional com 184 testes passando (97% coverage em query module)

**Conteúdo:**
- `models/`
  - `query.py` - Query system completo com árvore (QueryNode)
    - NodeType, ConnectorType enums
    - QueryNode com filter_code, inherited_filter_code, children_match_filter
    - Query class com parsing, validação, propagação
    - Serialização to_dict/from_dict
  - `paper.py` - Modelo Paper
  - `publication.py` - Modelo Publication
  - `search.py` - Modelo Search

- `searchers/` (7 implementados)
  - `base.py` - Interface SearcherBase (ABC)
  - `arxiv.py` - ArXiv searcher (contém lógica de conversão de query)
  - `pubmed.py` - PubMed searcher (contém lógica de conversão de query)
  - `ieee.py` - IEEE searcher (contém lógica de conversão de query)
  - `scopus.py` - Scopus searcher (contém lógica de conversão de query)
  - `biorxiv.py` - bioRxiv searcher (contém lógica de conversão de query)
  - `medrxiv.py` - medRxiv searcher (contém lógica de conversão de query)
  - `rxiv.py` - Base interna para bioRxiv/medRxiv
  - `database.py` - Busca local em JSON

- `runners/`
  - `search_runner.py` - SearchRunner OO com pipeline
    - Pipeline: fetch → filter → deduplicate → flag_predatory
    - Exports: to_json(), to_csv(), to_bibtex()
  - `enrichment_runner.py` - EnrichmentRunner
  - `download_runner.py` - DownloadRunner

- `utils/`
  - `merge_util.py` - Lógica de merge "most complete"
  - `parallel_util.py` - Paralelização
  - `predatory_util.py` - Flagging de predatory journals
  - `predatory_data.py` - Dados de predatory journals
  - `enrichment_util.py` - Enriquecimento via APIs
  - `search_export_util.py` - Utilitários de export
  - `version_util.py` - Versionamento

- `exceptions.py` - SearchRunnerNotExecutedError

**Testes:** tests_0/ (184 passando, 83% coverage geral)

**Decisão:** ✅ MANTER como base para migração

---

### findpapers/ ⚠️ ESTRUTURA VAZIA (refactoring incompleto)
**Status:** Diretórios criados mas vazios (apenas __init__.py)

**Estrutura encontrada:**
```
findpapers/
├── __init__.py
├── cli/
│   └── __init__.py
├── core/
│   └── __init__.py
├── download/
│   └── downloaders/
│       └── __init__.py
│   └── __init__.py
├── enrichment/
│   └── enrichers/
│       └── __init__.py
│   └── __init__.py
├── export/
│   └── exporters/
│       └── __init__.py
│   └── __init__.py
├── models/
│   └── query.py (cópia de findpapers_0)
├── query/
│   └── builders/
│       └── __init__.py
│   └── __init__.py
├── search/
│   └── engines/
│       └── __init__.py
│   └── __init__.py
├── services/
│   └── __init__.py
└── utils/
    └── __init__.py
```

**Observações:**
- Estrutura de diretórios criada seguindo algum plano anterior
- Apenas `models/query.py` tem conteúdo (cópia de findpapers_0)
- Demais arquivos são apenas __init__.py vazios
- Estrutura profunda (nested) - não segue SOLID simplificado do plano v2

**Decisão:** ❌ APAGAR e reconstruir seguindo REFACTORING_PLAN_v2.md

---

### tests/ ⚠️ ESTRUTURA VAZIA (refactoring incompleto)
**Status:** Diretórios criados mas vazios (apenas __init__.py)

**Estrutura encontrada:**
```
tests/
├── __init__.py
├── integration/
│   └── __init__.py
└── unit/
    ├── __init__.py
    ├── core/
    │   └── __init__.py
    ├── query/
    │   └── builders/
    │       └── __init__.py
    │   └── __init__.py
    └── search/
        └── engines/
            └── __init__.py
        └── __init__.py
```

**Observações:**
- Estrutura de testes criada mas sem testes reais
- Apenas __init__.py vazios

**Decisão:** ❌ APAGAR e reconstruir seguindo REFACTORING_PLAN_v2.md

---

### tests_0/ ✅ TESTES FUNCIONAIS
**Status:** 184 testes passando (83% coverage geral, 97% em query)

**Testes principais:**
- `unit/test_query.py` - Query system completo
- `unit/test_models.py` - Paper, Publication, Search
- `unit/test_search_runner_*.py` - SearchRunner várias funcionalidades
- `unit/test_enrichment_util.py` - Enrichment
- `unit/test_download_runner.py` - Download
- `unit/test_merge_util.py` - Merge
- `unit/test_predatory_util.py` - Predatory flagging
- `data/` - Samples de respostas das APIs

**Decisão:** ✅ MANTER temporariamente até migração completa, então apagar

---

### findpapers_old/ 🗑️ CÓDIGO FUNCIONAL ANTIGO
**Status:** API funcional antiga (antes de OO)

**Conteúdo:**
- `searchers/` - Searchers antigos (funcional, não OO)
- `tools/` - search_runner_tool.py, downloader_tool.py, bibtex_generator_tool.py
- `utils/` - Utilitários antigos
- `models/` - Modelos antigos

**Decisão:** ❌ APAGAR após migração completa (Fase 6)

---

### tests_old/ 🗑️ TESTES ANTIGOS
**Status:** Testes da API funcional antiga

**Decisão:** ❌ APAGAR após migração completa (Fase 6)

---

## 🎯 Plano de Ação (REFACTORING_PLAN_v2.md)

### Fase 0: Limpeza e Preparação (EM PROGRESSO)
- [x] Documentar estado atual (este arquivo)
- [ ] Apagar findpapers/ (estrutura vazia incompleta)
- [ ] Apagar tests/ (estrutura vazia incompleta)
- [ ] Criar estrutura SOLID simplificada (flat, não nested)
- [ ] Preparar para Fase 1

### Fase 1-5: Migração
- Usar findpapers_0/ como base
- Migrar para nova estrutura SOLID
- Extrair QueryBuilders dos searchers
- Implementar OpenAlex e Semantic Scholar
- Testes integrados

### Fase 6: Limpeza Final
- Apagar findpapers_0/ (após migração completa)
- Apagar tests_0/ (após testes migrados)
- Apagar findpapers_old/ (código legado)
- Apagar tests_old/ (testes legados)

---

## 📊 Comparação de Estruturas

### Estrutura Antiga (findpapers/)
```
findpapers/
├── cli/
├── download/
│   └── downloaders/
├── enrichment/
│   └── enrichers/
├── export/
│   └── exporters/
├── query/
│   └── builders/
└── search/
    └── engines/
```
**Problema:** Muito nested, complexo, disperso

### Estrutura Nova (REFACTORING_PLAN_v2.md)
```
findpapers/
├── core/          # Entidades
├── query/         # Parser, Validator, Propagator, Builder interface
├── builders/      # FLAT - um arquivo por database
├── searchers/     # FLAT - um arquivo por database
├── runners/       # SearchRunner, EnrichmentRunner, DownloadRunner
└── utils/         # Helpers (export, merge, predatory, etc.)
```
**Benefício:** Flat, simples, direto

---

## 🔍 Lições Aprendidas

1. **Não empilhar refactorings** - Terminar um antes de começar outro
2. **Estrutura flat é melhor** - Evitar nested directories sem necessidade
3. **SOLID pragmático** - Aplicar onde faz sentido, não everywhere
4. **Base sólida** - findpapers_0/ tinha query system funcionando, usar como base
5. **Plano único** - Um REFACTORING_PLAN_v2.md linear é melhor que 3 planos parciais

---

**Fim das notas de limpeza**
