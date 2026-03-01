# docsoup

**Code knowledge-base search for AI coding agents.**

docsoup reads a Node.js project's dependencies, parses their TypeScript type
definitions (`.d.ts` files), and builds a local full-text search index. An AI
agent can then query that index to understand how any installed library works —
without leaving the project or hitting the network.

---

## How it works

```
package.json + node_modules/
        │
        ▼
  DependencyDiscoverer      ← resolves installed packages
        │
        ▼
  SymbolExtractor           ← Tree-sitter parses .d.ts files
        │
        ▼
  Index (SQLite FTS5)       ← BM25-ranked full-text search
        │
        ▼
  docsoup search …          ← CLI used by the agent skill
```

The index is stored in `.docsoup/index.db` inside the project directory and
persists across sessions. Only changed library versions are re-indexed on
subsequent runs.

---

## Requirements

- Python 3.11+
- A Node.js project with a `package.json` and populated `node_modules/`

---

## Installation

### From source (recommended during development)

```bash
git clone https://github.com/your-org/docsoup
cd docsoup
pip install -e .
```

### Into a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

Verify:

```bash
docsoup --help
```

---

## Usage

### 1. Index a project

Point docsoup at the root of any Node.js project (the directory that contains
`package.json`):

```bash
docsoup index /path/to/my-app
```

```
✓ Indexed (47 symbols):
  • chalk
  • lodash
↷ Skipped (already indexed or no .d.ts):
  • typescript
```

Packages that are already indexed at the same version are skipped
automatically. Force a full re-index with `--force`:

```bash
docsoup index /path/to/my-app --force
```

### 2. Search

```bash
docsoup search /path/to/my-app "<query>"
```

```
────────────────────────────────────────────────────────────
1. [FUNCTION] lodash:chunk  (score: 4.1823)
   lodash@4.17.21  index.d.ts:1

   function chunk<T>(array: T[], size?: number): T[][]
   // Creates an array of elements split into groups of size.

────────────────────────────────────────────────────────────

1 result(s) for 'chunk'.
```

**Filter flags:**

| Flag | Description |
|------|-------------|
| `-l, --library <name>` | Restrict to a specific package, e.g. `--library react` |
| `-k, --kind <type>` | Filter by symbol kind: `function` `class` `interface` `type` `enum` `variable` |
| `-n, --limit <n>` | Maximum number of results (default: `10`) |
| `--json` | Machine-readable JSON output |

**Examples:**

```bash
# Find how to create a router in express
docsoup search . "create router" --library express

# Look up React state hooks
docsoup search . "state hook" --library react --kind function

# Find all interfaces in axios
docsoup search . "config options" --library axios --kind interface

# Get JSON output for programmatic use
docsoup search . "middleware" --library express --json

# Find type aliases
docsoup search . "Promise response" --kind type
```

### 3. Check index status

```bash
docsoup status /path/to/my-app
```

```
Library                        Version          Symbols  Indexed at
───────────────────────────────────────────────────────────────────────────
chalk                          5.3.0                  3  2026-03-01 15:42:11
lodash                         4.17.21                3  2026-03-01 15:42:11
───────────────────────────────────────────────────────────────────────────
Total                                                 6
```

---

## JSON output

All commands accept `--json` for structured output.

**`docsoup search … --json`** returns a JSON array:

```json
[
  {
    "fqn": "lodash:chunk",
    "name": "chunk",
    "library": "lodash",
    "library_version": "4.17.21",
    "kind": "function",
    "signature": "function chunk<T>(array: T[], size?: number): T[][]",
    "docstring": "Creates an array of elements split into groups of size.",
    "file_path": "index.d.ts",
    "line_number": 1,
    "score": 4.1823
  }
]
```

**`docsoup index … --json`** returns a summary object:

```json
{
  "indexed": ["chalk", "lodash"],
  "skipped": ["typescript"],
  "failed": [],
  "total_symbols": 6
}
```

**`docsoup status … --json`** returns an array of library objects:

```json
[
  {
    "name": "chalk",
    "version": "5.3.0",
    "symbol_count": 3,
    "indexed_at": "2026-03-01 15:42:11"
  }
]
```

---

## Global options

```
docsoup [--verbose] COMMAND …
```

| Option | Description |
|--------|-------------|
| `-v, --verbose` | Print debug logs to stderr (useful for diagnosing indexing issues) |

---

## Using as an agent skill

docsoup ships with a [pi](https://github.com/badlogic/pi) agent skill at
`.pi/skills/docsoup/SKILL.md`. Once docsoup is installed, an AI agent using pi
will automatically pick up the skill and know how and when to use the CLI.

**Typical agent workflow:**

```bash
# Agent indexes dependencies once
docsoup index /path/to/project

# Agent searches whenever it needs to understand a library
docsoup search /path/to/project "how to set response headers" --library express --json
```

---

## Architecture & extensibility

docsoup is built around three abstract interfaces that make it easy to add
support for new ecosystems, parsers, or storage backends:

| Interface | MVP implementation | How to extend |
|---|---|---|
| `DependencyDiscoverer` | `NodeDiscoverer` (reads `package.json`) | Implement `discover(project_root)` for Python, Rust, Go, etc. |
| `SymbolExtractor` | `TypeScriptExtractor` (parses `.d.ts`) | Implement `can_extract()` + `extract()` for new languages |
| `Index` | `SqliteIndex` (SQLite FTS5 / BM25) | Implement the 5-method interface to swap in vector embeddings, hybrid search, etc. |

The `SearchEngine` wires them together via dependency injection and never
imports concrete implementations directly:

```python
from docsoup.search.engine import SearchEngine
from docsoup.discovery.node import NodeDiscoverer
from docsoup.parsing.typescript import TypeScriptExtractor
from docsoup.indexing.sqlite_index import SqliteIndex

engine = SearchEngine(
    discoverer=NodeDiscoverer(),
    extractors=[TypeScriptExtractor()],   # first match wins
    index=SqliteIndex(db_path=".docsoup/index.db"),
)

report = engine.index_project(Path("/path/to/project"))
results = engine.search("create middleware", library="express", limit=5)
```

---

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov
```

---

## What gets indexed

- Only packages that have TypeScript type definitions (`.d.ts` files) are
  indexed. The entry point is resolved in order: `types` field in
  `package.json` → `typings` field → `index.d.ts`.
- Extracted symbol kinds: `function`, `class` (+ methods), `interface`,
  `type` alias, `enum`, `variable`/`const`.
- JSDoc comments and single-line `//` comments are captured as `docstring`
  and included in the search index.
- The index covers: symbol name, fully-qualified name, signature, docstring,
  and full source text.
