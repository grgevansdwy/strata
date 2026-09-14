# Strata — a semantic dashboard IDE

*(working name; drill down through layers of a codebase)*

## Context

Reading a codebase as a pile of text files is a bad interface for *understanding* it. Every competent engineer builds a mental model that looks like a tree of capabilities — "this part handles auth, it talks to that part" — and the IDE gives zero help building or maintaining that model. You re-derive it by hand, every time, for every repo.

The proposal: make that model the primary surface. The top level is a set of capability branches. Drill into a branch and it decomposes into modules, then symbols, then the actual code — which you can edit in place, right there in the dashboard. Files still exist; they're just no longer the thing you navigate by.

Goal of this document: an architecture worth starting from, plus an honest read on where this idea has killed previous attempts.

---

## Thoughts before architecture

### The differentiator is the editing, not the map

"Auto-generate a map of your codebase" is a well-populated graveyard — CodeSee, Structure101, Lattix, Sourcegraph's early code-intel, and going back further, Code Bubbles and the Smalltalk class browser. They all failed the same way: **the map is a read-only artifact, so it goes stale, so people look at it once during onboarding and never again.**

The one thing in this concept that dodges that failure is direct snippet editing. If you *work* through the dashboard, it cannot go stale, because you're looking at it while you change things. That single feature is what turns it from a diagram into an IDE.

So the design principle to anchor everything to: **the dashboard must be where work happens, not where you go to look at work.** Test every feature against "would I spend a Tuesday afternoon in this?" A feature that only helps on day one of a new repo is a feature that kills the product.

### A wrong summary is worse than no summary

The LLM-written "what does this do" labels are the magic *and* the biggest risk. A confidently wrong label teaches a false mental model, and you can't detect it without reading the code — which is exactly what the product exists to spare you. Two non-negotiables fall out:

- Every summary is one click from the source that produced it. Never hide the code.
- Summaries are keyed to a content hash. When the code changes, the old summary renders visibly stale — dimmed, flagged, queued for refresh. Never silently show a stale summary as current.

### The hardest engineering problem is write-back, not parsing

Parsing Python is solved. Rendering a tree is easy. The part that will actually hurt: edit a snippet → splice it into the right byte range of a file that may have changed underneath you (git pull, formatter, another editor) → re-index incrementally without corrupting anything. Get this wrong once and you've eaten someone's code, which is unrecoverable for an IDE's reputation. It gets designed on day one, not bolted on at step 4.

### Don't try to replace the text editor

Every node keeps an "open in VS Code" escape hatch. Fighting for 100% of the workflow on day one loses. Being the best *understanding and small-edit* surface, and handing off for heavy refactors, wins — and it's how you get people to try it at all.

---

## Architecture

Three layers. Python backend (FastAPI), SQLite, React frontend, all running locally.

```
  repo on disk
       │  watchdog
       ▼
┌──────────────────┐
│  INDEX LAYER     │  ast → nodes + edges          ← deterministic, fast, always correct
│  (Python)        │  jedi/pyright → resolved refs
└────────┬─────────┘
         │ SQLite (nodes, edges, summaries, files)
┌────────▼─────────┐
│  SEMANTIC LAYER  │  bottom-up LLM summaries      ← lazy, cached by ast_hash
│  (worker pool)   │  branch capability naming
└────────┬─────────┘
         │ REST + WebSocket
┌────────▼─────────┐
│  SURFACE LAYER   │  drill-down cards             ← the product
│  (React)         │  relationship rail
│                  │  CodeMirror snippet editing ──┐
└──────────────────┘                               │
         ▲                                         │
         └────── write-back w/ hash check ─────────┘
```

### 1. Index layer

- **Parser**: stdlib `ast`. Extract modules, classes, functions, imports, decorators, top-level statements. No tree-sitter needed for a Python-only v1.
- **Stable node IDs** — the single most important data decision. *Not* line numbers; they drift on every edit. Use a semantic path plus a disambiguating ordinal:
  ```
  repo://services/billing/webhooks.py#StripeHandler.on_invoice_paid
  ```
  Every other subsystem — cached summaries, UI state, edit targets, the edge table — keys off this. Retrofitting stable IDs later is miserable; do it first.
- **Relationships, in two tiers** (be honest in the UI about which tier an edge came from):
  - *Inferred* — import graph + intra-file call edges straight from the AST. Instant, always available.
  - *Resolved* — real cross-file references via Jedi or pyright. Runs in the background and upgrades inferred edges in place.
  - Python is dynamic; decorators, `getattr`, and DI containers mean the static graph is never complete. Showing an incomplete graph labeled honestly beats showing a confident wrong one.
- **Store**: SQLite. `nodes`, `edges`, `summaries`, `files`. Zero setup, handles 100k nodes comfortably, and SQL covers every traversal the UI needs. A graph database is the wrong cost/benefit at this scale.
- **Watcher**: `watchdog` on the repo root → re-parse only the changed file → emit a WebSocket delta. Watching the dashboard update as a file changes on disk is the demo that proves it isn't a stale map.

### 2. Semantic layer

- **Bottom-up summarization.** Leaf functions summarize from source. Classes summarize from their method summaries plus the class body. Modules from their symbols. Directory branches from their modules. Each level reads its children's summaries, not raw code — cheap, and it produces genuinely architectural language at the top.
- **Branch naming** is what makes this feel like a dashboard rather than a labeled file tree. At package level, ask for: a short capability name ("Payment webhooks"), one sentence of purpose, and the key entry points.
- **Lazy by default.** Summarize a branch when it's first expanded, not the whole repo upfront. First run is instant, and cost is proportional to what you actually look at rather than to repo size.
- **Cache table**: `(node_id, ast_hash, summary, model, created_at)`. Hash mismatch → render stale, queue refresh. This table *is* the staleness solution.
- **Model tiering**: Haiku for leaves (high volume, low stakes), Opus for branch rollups (low volume, and these are the labels people actually read). Concurrency-capped worker pool.

### 3. Surface layer

Navigation model matters more than visual design here. **Zoomable drill-down, not a tree sidebar** — a tree sidebar is a file explorer with extra words, and it recreates exactly the thing you're replacing.

- **Center**: the current branch rendered as cards, one per child. Each card shows name, the one-line what-it-does, and badges that make it scannable: LOC, number of callers, changed-this-week, test coverage if available.
- **Breadcrumb**: grows as you zoom in; the whole path is clickable. This is the user's sense of place.
- **Right rail — relationships of the current node**: called-by, calls, reads/writes these models. Every entry jumps you there. *This is what makes it a graph browser instead of a tree browser*, and it's the highest-value panel on the screen. Don't cut it to ship faster.
- **Leaf = editable code.** Drill past the last symbol level and the card expands into CodeMirror 6 with the real source.

**Write-back protocol** (the part that must be right):

1. `PATCH /node/{id}` carries `expected_ast_hash` + new source.
2. Hash mismatch → `409`, show the user a diff, never overwrite.
3. Parse the new snippet standalone — reject syntax errors *before* touching the file.
4. Re-indent: snippets are dedented for display, so re-apply the original indentation on write. Small, and a real correctness trap.
5. Splice by byte range, run the repo's formatter if it has one (black/ruff), re-parse the file, re-queue summaries for touched nodes, push a WebSocket delta.

---

## Build order

Sequenced by risk. The riskiest assumption isn't "can we parse Python" — it's **"is drilling a semantic tree actually faster to understand than reading files?"** Everything below is arranged to answer that as early as possible.

| # | Milestone | Proves |
|---|---|---|
| 1 | Indexer → SQLite → JSON tree for one repo. No LLM, structural names only. | The graph is extractable and accurate |
| 2 | Drill-down UI + breadcrumb + **relationship rail** | The core navigation thesis |
| 3 | Bottom-up LLM summaries, lazy on expand | It reads like a dashboard, not a file tree |
| 4 | Snippet editing with the full write-back protocol | It's an IDE, not a map |
| 5 | Live re-index on disk change | It never goes stale |

Ship 1–3 before starting 4 — but design the node-ID scheme for 4 at step 1.

**Test repo**: `~/Documents/digital-twin` or `~/Documents/job-agent` — real, Python, and small enough to iterate on.

## Explicitly out of scope for v1

- Multi-language. Cross-file resolution is the value, and it's per-language work; breadth here buys a worse product.
- Git branches. The word "branch" is overloaded in this concept — the *tree* branches are the product, and mixing in VCS branching muddies the model.
- Collaboration / multiplayer.
- Replacing the text editor outright. Keep the VS Code escape hatch.

## Proposed layout

```
~/Documents/strata/
├── backend/
│   ├── indexer/      ast_parser.py, node_ids.py, edges.py, watcher.py
│   ├── semantic/     summarizer.py, cache.py, prompts.py
│   ├── writeback/    patch.py          ← the dangerous one; test it hardest
│   ├── db/           schema.sql, queries.py
│   └── api.py        FastAPI + WebSocket
└── frontend/
    └── src/          CanvasView, BranchCard, Breadcrumb, RelationRail, SnippetEditor
```

## Verification

- **Index correctness**: run the indexer over `digital-twin`; assert every `def`/`class` in the repo appears exactly once, and that node IDs survive an unrelated edit elsewhere in the file.
- **Write-back safety** — the one that needs real tests, not a manual click-through: golden-file tests for edit-a-method / edit-a-decorated-function / edit-a-nested-function / edit-with-changed-indentation. Plus a deliberate conflict test: modify the file on disk mid-edit and confirm a 409, not a clobber.
- **Staleness**: edit a file externally; confirm the affected summaries visibly flip to stale and refresh, and that the WebSocket delta lands without a page reload.
- **The actual product question**: take a repo you don't know, give yourself 10 minutes in the dashboard and 10 minutes in VS Code, and see which one leaves you able to explain the architecture. If the answer isn't obviously the dashboard by milestone 3, the navigation model needs rethinking before any more is built on it.
