# Strata

A semantic dashboard IDE for Python repos. You drill down from capability branches to modules, then symbols, then code you edit in place. See [strata-semantic-ide-plan.md](strata-semantic-ide-plan.md) for the design.

## Run

```bash
# once
cd backend && uv sync && cp .env.example .env   # add ANTHROPIC_API_KEY for summaries
cd ../frontend && npm install && npm run build

# serve a repo (dashboard + API on http://127.0.0.1:8765)
cd backend && uv run strata serve --repo ~/Documents/effigov
```

For frontend development, run `npm run dev` in `frontend/` (http://localhost:5173, which proxies `/api` and `/ws` to :8765).

The index lives in `~/.strata/<repo>-<hash>.db`. Nothing is written into the target repo except your own edits.

## How it works

| Layer | Where | Notes |
|---|---|---|
| Index | `backend/strata/indexer/` | `ast` → nodes with byte spans. IDs look like `repo://path.py#Class.method` (no line numbers). Edges are *inferred* from the AST, then upgraded to *resolved* by Jedi in the background. |
| Semantic | `backend/strata/semantic/` | Bottom-up summaries: Haiku 4.5 for functions, Opus 5 for classes, modules and dirs. Cached by `ast_hash`; a mismatch renders the summary **stale** and queues a refresh. |
| Write-back | `backend/strata/writeback/patch.py` | Checks the node's `src_hash` (409 on mismatch, file untouched), parses the snippet, re-indents it (skipping lines inside multi-line strings), splices the bytes, re-parses the file, optionally formats (only if the repo's `pyproject.toml` configures black/ruff), and writes atomically. |
| Live | `backend/strata/indexer/watcher.py` | watchdog → re-index only the changed file → WebSocket delta. |
| Surface | `frontend/src/` | Card canvas, breadcrumb, relationship rail, CodeMirror editor with a conflict diff. `Esc` zooms out, `⌘S` saves. |

## Test

```bash
cd backend && uv run pytest
```

Tests run against a temporary copy of `~/Documents/effigov` (override with `STRATA_TEST_REPO`) plus golden fixtures in `tests/fixtures/`.
