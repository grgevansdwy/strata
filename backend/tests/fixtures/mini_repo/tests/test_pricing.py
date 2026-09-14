from shop.pricing import order_total


def test_empty():
    assert order_total([]) == 0
