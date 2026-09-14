"""Data types."""
from dataclasses import dataclass

TAX_RATE = 0.2


@dataclass
class Item:
    name: str
    price: float

    def total(self) -> float:
        return self.price * (1 + TAX_RATE)


class Unused:
    pass
