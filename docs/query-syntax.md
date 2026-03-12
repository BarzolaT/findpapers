# Query Syntax

Findpapers uses a custom boolean query language that gets translated into the native syntax of each database. This page describes all the rules.

## Basic Structure

- Terms must be enclosed in **square brackets**: `[term]`
- Terms cannot be empty or contain double quotes
- Boolean connectors join terms or groups

```
[machine learning] AND [healthcare]
```

## Boolean Connectors

Three connectors are available (case-insensitive):

| Connector | Meaning |
|-----------|---------|
| `AND` | Both terms must be present |
| `OR` | At least one term must be present |
| `AND NOT` | First term present, second excluded |

Connectors must have at least one whitespace before and after them. `OR NOT` is **not** a valid connector - use `AND NOT` instead.

## Grouping

Use parentheses to group subqueries:

```
[deep learning] AND ([image classification] OR [object detection])
```

Groups can be nested:

```
[term a] OR ([term b] AND ([term c] OR [term d]))
```

## Filter Codes

Filter codes restrict where a term is searched. Add them before the opening bracket:

```
ti[neural network] AND abs[image segmentation]
```

| Code | Field | Description |
|------|-------|-------------|
| `ti` | Title | Search in paper title only |
| `abs` | Abstract | Search in abstract only |
| `key` | Keywords | Search in keywords only |
| `au` | Author | Search by author name |
| `src` | Source | Search by publication source (journal, conference) |
| `aff` | Affiliation | Search by author affiliation |
| `tiabs` | Title + Abstract | Search in title and abstract (default) |
| `tiabskey` | Title + Abstract + Keywords | Search in title, abstract, and keywords |

When no filter code is specified, the default behavior is `tiabs` (title and abstract).

### Filter Code Propagation

Filter codes propagate into groups. The innermost explicit filter always wins:

```
ti([neural network] OR abs[deep learning])
```

In this example, `[neural network]` inherits the `ti` filter from the group, but `[deep learning]` uses its own explicit `abs` filter.

> **Note:** Not all databases support every filter code. Findpapers validates the query against each database's capabilities and skips databases that cannot handle the query. See [Search Databases](https://github.com/jonatasgrosman/findpapers/blob/main/docs/search-databases.md) for per-database support.

## Wildcards

Two wildcards are available:

| Wildcard | Meaning | Example |
|----------|---------|---------|
| `?` | Exactly one character | `[son?]` matches "song", "sons" (not "son") |
| `*` | Zero or more characters | `[son*]` matches "son", "song", "sonic", ... |

### Wildcard Rules

- Cannot be placed at the **start** of a term
- `*` requires at least **3 characters** before it
- `*` can only be placed at the **end** of a term
- Only **one** wildcard per term
- Can only be used in **single-word** terms

> **Database support:** IEEE and PubMed support only `*`. Scopus supports both `?` and `*`. arXiv does **not** support wildcards. OpenAlex and Semantic Scholar have limited wildcard support.

## Examples

| Query | Valid? |
|-------|--------|
| `[term a]` | Yes |
| `([term a] OR [term b])` | Yes |
| `[term a] AND [term b]` | Yes |
| `[term a] AND NOT ([term b] OR [term c])` | Yes |
| `[term a] OR ([term b] AND ([term*] OR [t?rm]))` | Yes |
| `ti[neural nets] AND abs[vision]` | Yes |
| `[term a]OR[term b]` | **No** - missing whitespace around connector |
| `([term a] OR [term b]` | **No** - unbalanced parentheses |
| `term a OR [term b]` | **No** - missing square brackets |
| `[term a] [term b]` | **No** - missing connector |
| `[term a] XOR [term b]` | **No** - invalid connector |
| `[] AND [term b]` | **No** - empty term |
| `["term a"]` | **No** - double quotes not allowed |
| `[?erm]` | **No** - wildcard at start |
| `[te*]` | **No** - fewer than 3 chars before `*` |
| `[ter*s]` | **No** - `*` not at end |
| `[t?rm?]` | **No** - multiple wildcards |
| `[some term*]` | **No** - wildcard in multi-word term |

## Error Handling

Invalid queries raise `QueryValidationError` at search time:

```python
from findpapers import Engine
from findpapers.exceptions import QueryValidationError

engine = Engine()
try:
    result = engine.search("[term a] XOR [term b]")
except QueryValidationError as e:
    print(f"Invalid query: {e}")
```

If a query is valid but not supported by a specific database (e.g., uses a filter code the database doesn't handle), that database is silently skipped and the search proceeds with the remaining databases.
