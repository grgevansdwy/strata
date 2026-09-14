"""The summaries table is the staleness mechanism: a summary is current only for the ast_hash it was made from."""

import json

from strata.db.queries import DB


def view(node: dict, row: dict | None) -> dict:
    """What the UI gets for a node's summary. Stale summaries are returned, flagged, never hidden."""
    if row is None:
        return {"title": None, "summary": None, "entry_points": [], "stale": False, "has_summary": False}
    return {
        "title": row["title"],
        "summary": row["summary"],
        "entry_points": json.loads(row["entry_points"] or "[]"),
        "model": row["model"],
        "stale": row["ast_hash"] != node["ast_hash"],
        "has_summary": True,
    }


def is_current(db: DB, node: dict) -> bool:
    row = db.summary(node["id"])
    return row is not None and row["ast_hash"] == node["ast_hash"]
