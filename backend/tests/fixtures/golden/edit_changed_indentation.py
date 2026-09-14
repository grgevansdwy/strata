"""Fixture module for write-back golden tests."""
import functools


def retry(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)

    return wrapper


class Invoice:
    """An invoice."""

    def __init__(self, amount):
      self.amount = amount
      if amount < 0:
          raise ValueError(amount)

    def total(self, tax=0.1):
        note = """
multi-line string
    keeps its own indentation
"""
        return self.amount * (1 + tax)

    @property
    def cents(self):
        # comment at method indentation
        return int(self.amount * 100)


@retry
def charge(invoice):
    def log(msg):
        print(msg)

    log("charging")
    return invoice.total()
