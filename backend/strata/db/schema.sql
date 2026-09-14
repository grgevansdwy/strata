-- One row per indexed .py file.
CREATE TABLE IF NOT EXISTS files (
    path   TEXT PRIMARY KEY,      -- repo-relative, '/' separated
    sha256 TEXT NOT NULL,
    mtime  REAL NOT NULL
);

-- Directories, modules, classes, functions. `id` is the stable semantic path.
CREATE TABLE IF NOT EXISTS nodes (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL CHECK (kind IN ('dir', 'module', 'class', 'function')),
    parent_id  TEXT,
    name       TEXT NOT NULL,
    file       TEXT,                -- NULL for dirs
    start_byte INTEGER,
    end_byte   INTEGER,
    start_line INTEGER,
    end_line   INTEGER,
    indent     TEXT,                -- literal leading whitespace of the def line
    ast_hash   TEXT NOT NULL,       -- structure hash: keys summaries
    src_hash   TEXT,                -- byte hash of the span: guards write-back
    loc        INTEGER NOT NULL DEFAULT 0,
    signature  TEXT,
    docstring  TEXT,
    ordinal    INTEGER NOT NULL DEFAULT 0  -- source order among siblings
);
CREATE INDEX IF NOT EXISTS nodes_parent ON nodes(parent_id);
CREATE INDEX IF NOT EXISTS nodes_file ON nodes(file);

CREATE TABLE IF NOT EXISTS edges (
    src      TEXT NOT NULL,
    dst      TEXT NOT NULL,
    kind     TEXT NOT NULL CHECK (kind IN ('import', 'call')),
    tier     TEXT NOT NULL CHECK (tier IN ('inferred', 'resolved')),
    src_file TEXT NOT NULL,
    PRIMARY KEY (src, dst, kind, tier)
);
CREATE INDEX IF NOT EXISTS edges_dst ON edges(dst);
CREATE INDEX IF NOT EXISTS edges_src_file ON edges(src_file);

-- Summaries are never deleted on change; a hash mismatch renders them stale.
CREATE TABLE IF NOT EXISTS summaries (
    node_id    TEXT PRIMARY KEY,
    ast_hash   TEXT NOT NULL,
    title      TEXT,
    summary    TEXT NOT NULL,
    entry_points TEXT,              -- JSON list of names, branches only
    model      TEXT NOT NULL,
    created_at REAL NOT NULL
);
