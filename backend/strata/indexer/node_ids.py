"""Stable node IDs: semantic path, never line numbers.

    repo://                                   repo root
    repo://services/billing/                  directory
    repo://services/billing/webhooks.py       module
    repo://services/billing/webhooks.py#StripeHandler.on_invoice_paid
    repo://pkg/mod.py#prop@2                  second same-named sibling (e.g. a property setter)
"""

PREFIX = "repo://"
ROOT_ID = PREFIX


def dir_id(relpath: str) -> str:
    return PREFIX + (relpath.strip("/") + "/" if relpath.strip("/") else "")


def module_id(relpath: str) -> str:
    return PREFIX + relpath


def symbol_id(relpath: str, qualname: str) -> str:
    return f"{PREFIX}{relpath}#{qualname}"


def parent_dir_id(relpath: str) -> str:
    """ID of the directory containing a file or directory path."""
    head, _, _ = relpath.strip("/").rpartition("/")
    return dir_id(head)
