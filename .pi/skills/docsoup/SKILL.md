---
name: docsoup
description: Index and search TypeScript/JavaScript dependency documentation and API surfaces for Node.js projects. Use when you need to understand how a library works, find a function signature, explore available APIs, or look up type definitions for any installed npm package.
---

# docsoup

Search the indexed API surface and type definitions of a project's npm dependencies.

## Setup

Install docsoup into the active Python environment (run once per machine):

```bash
pip install -e /path/to/docsoup
```

Or if working inside the docsoup repo:

```bash
cd /Users/aerlaut/Projects/docsoup && pip install -e .
```

Verify installation:

```bash
docsoup --help
```

## Workflow

### Step 1 — Index the project

Run this once (or when dependencies change). It reads `package.json`, parses
`.d.ts` files from `node_modules/`, and stores symbols in
`.docsoup/index.db` inside the project directory.

```bash
docsoup index <project_root>
```

Subsequent calls skip already-indexed libraries automatically. Use `--force`
to re-index everything:

```bash
docsoup index <project_root> --force
```

### Step 2 — Search

```bash
docsoup search <project_root> "<query>"
```

**Useful flags:**

| Flag | Description |
|------|-------------|
| `--library <name>` | Restrict to a specific package (e.g. `--library react`) |
| `--kind <type>` | Filter by symbol kind: `function`, `class`, `interface`, `type`, `enum`, `variable` |
| `--limit <n>` | Return at most N results (default 10) |
| `--json` | Machine-readable JSON output (preferred for programmatic use) |

### Step 3 — Check status

```bash
docsoup status <project_root>
```

Shows which libraries are indexed and how many symbols each has.

---

## Example Queries

```bash
# Find how to create a router in express
docsoup search . "create router" --library express

# Look up React hooks — functions only
docsoup search . "state hook" --library react --kind function

# Find all interfaces in a library
docsoup search . "config options" --library axios --kind interface

# Get JSON output for programmatic use
docsoup search . "middleware" --library express --json

# Find type definitions for a specific concept
docsoup search . "Promise response" --kind type
```

---

## JSON Output Format

When `--json` is passed, `search` returns a JSON array. Each element:

```json
{
  "fqn": "express:Router.use",
  "name": "use",
  "library": "express",
  "library_version": "4.18.2",
  "kind": "function",
  "signature": "use(path: string, ...handlers: RequestHandler[]): this",
  "docstring": "Mount middleware at the given path.",
  "file_path": "index.d.ts",
  "line_number": 42,
  "score": 3.7182
}
```

The `index` command with `--json` returns:

```json
{
  "indexed": ["react", "express"],
  "skipped": ["typescript"],
  "failed": [],
  "total_symbols": 312
}
```

---

## When to Use

- **Before using an unfamiliar library**: `docsoup index .` then search for the concept you need.
- **To find the right function name**: search with a description like `"sort array by key"`.
- **To understand types/interfaces**: use `--kind interface` or `--kind type`.
- **To explore a class's methods**: search for the class name with `--kind class`, then search `"ClassName."` to see member FQNs.
- **When TypeScript errors mention unknown types**: search the type name directly.

## Notes

- Only packages with `.d.ts` type definition files are indexed.
- The index persists between sessions in `.docsoup/index.db` — no need to re-index unless dependencies change.
- The `--verbose` flag (on the `docsoup` root command) prints debug logs to stderr if you need to diagnose indexing issues.
