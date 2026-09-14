from fastapi import FastAPI

from shop.pricing import order_total, parse_items

app = FastAPI()


@app.post("/total")
def total_endpoint(body: str) -> float:
    return order_total(parse_items(body))
