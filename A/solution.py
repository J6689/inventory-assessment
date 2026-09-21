from __future__ import annotations

import re
import sys

QTY_RE = re.compile(r"^\d+$")
MAX_QTY = 10**12
MAX_STOCK = 10**12
MAX_COMMANDS = 200_000

_ORDER_COMMANDS = {"RESERVE", "RELEASE", "SHIP"}


def _ascii_token(tok: str) -> bool:
    """Non-empty printable ASCII with no whitespace (spec guarantee, validated anyway)."""
    return bool(tok) and all(33 <= ord(c) <= 126 for c in tok)


def _parse_qty(raw: str) -> int | None:
    """Quantities must be positive integers within the declared bound."""
    if not QTY_RE.match(raw):
        return None
    value = int(raw)
    if value < 1 or value > MAX_QTY:
        return None
    return value


def process(initial_stock: int, commands) -> list[str]:
    """Apply commands in order and return every output line (incl. OPEN trailer)."""
    on_hand = initial_stock
    reserved = 0
    order_reserved: dict[str, int] = {}
    processed: set[str] = set()
    lines: list[str] = []

    for raw in commands:
        parts = raw.split()
        cmd = parts[0] if parts else ""
        status = "REJECTED"

        # Structural validation happens BEFORE the duplicate check: a line we
        # cannot parse reliably must not consume or be consumed by the
        # idempotency ledger (see README assumptions).
        if cmd == "RESTOCK" and len(parts) == 3:
            _, event, qty_raw = parts
            qty = _parse_qty(qty_raw)
            if qty is not None and _ascii_token(event):
                if event in processed:
                    status = "DUPLICATE"
                else:
                    processed.add(event)
                    on_hand += qty
                    status = "OK"
        elif cmd in _ORDER_COMMANDS and len(parts) == 4:
            _, event, order, qty_raw = parts
            qty = _parse_qty(qty_raw)
            if qty is not None and _ascii_token(event) and _ascii_token(order):
                if event in processed:
                    status = "DUPLICATE"
                else:
                    # A rejected business operation is still "processed" for
                    # idempotency, so the event is recorded before evaluating.
                    processed.add(event)
                    if cmd == "RESERVE":
                        if on_hand - reserved >= qty:
                            reserved += qty
                            order_reserved[order] = order_reserved.get(order, 0) + qty
                            status = "OK"
                    else:  # RELEASE / SHIP
                        held = order_reserved.get(order, 0)
                        if held >= qty:
                            new_held = held - qty
                            if new_held:
                                order_reserved[order] = new_held
                            else:
                                del order_reserved[order]
                            reserved -= qty
                            if cmd == "SHIP":
                                # Shipping physically leaves the warehouse.
                                on_hand -= qty
                            status = "OK"
        lines.append(f"{status} {on_hand} {reserved}")

    open_res = sorted(order_reserved.items())
    lines.append(f"OPEN {len(open_res)}")
    lines.extend(f"{order} {qty}" for order, qty in open_res)
    return lines


def parse_header(line: str) -> tuple[int, int] | None:
    parts = line.split()
    if len(parts) != 2 or not all(QTY_RE.match(p) for p in parts):
        return None
    stock, count = int(parts[0]), int(parts[1])
    if stock > MAX_STOCK or count < 1 or count > MAX_COMMANDS:
        return None
    return stock, count


def main() -> int:
    data = sys.stdin.read().splitlines()
    if not data:
        print("missing header line", file=sys.stderr)
        return 2
    header = parse_header(data[0])
    if header is None:
        print("malformed header line", file=sys.stderr)
        return 2
    stock, count = header
    # Fewer than N command lines: process what exists (documented assumption).
    # More than N: extra lines are ignored.
    print("\n".join(process(stock, data[1 : 1 + count])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
