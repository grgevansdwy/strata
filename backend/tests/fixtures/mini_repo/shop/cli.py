import sys

from shop import pricing


def main():
    items = pricing.parse_items(sys.stdin.read())
    print(pricing.apply(pricing.order_total, items))


def orphan_helper():
    return 1


if __name__ == "__main__":
    main()
