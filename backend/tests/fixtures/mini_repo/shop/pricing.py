import json

from shop.models import Item


def parse_items(raw: str) -> list[Item]:
    return [Item(**row) for row in json.loads(raw)]


def order_total(items: list[Item]) -> float:
    return sum(i.total() for i in items)


def apply(fn, items):
    return fn(items)
