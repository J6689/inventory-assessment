# Task A — Inventory Reservation Ledger

## Run

```bash
python A/solution.py < input.txt
```

## Test

```bash
python -m unittest discover -s A -p "test_*.py" -v
```

(Only the Python standard library is used.)

## Design

A single deterministic pass keeps four pieces of state:

| State | Meaning |
|---|---|
| `on_hand` | physical stock in the warehouse |
| `reserved` | total stock reserved across all orders |
| `order_reserved` | per-order reserved quantity (open reservations) |
| `processed` | set of event ids that have been evaluated |

Available stock is `on_hand - reserved`; the invariant `on_hand >= reserved >= 0`
is preserved by every transition (RESERVE requires availability, SHIP reduces
both sides, RELEASE reduces only `reserved`, RESTOCK increases `on_hand`).

**Complexity:** O(N) time, O(N) space. Each command does a constant number of
amortised-O(1) dict/set operations; the final `OPEN` listing is O(R log R) for
R open reservations, bounded by N.

## Decisions & assumptions

- **Idempotency ledger.** An event id is recorded as processed the first time it
  is *structurally valid*, whether the business outcome is OK or REJECTED
  (spec: "a rejected business operation is still considered processed").
  Replays print `DUPLICATE` with unchanged state, regardless of the replayed
  arguments.
- **Malformed lines are not events.** A line that fails structural validation
  (wrong arity, non-positive/non-integer quantity, unknown verb, non-ASCII
  token) prints `REJECTED` and does **not** consume its event id — we cannot
  trust id extraction from input we had to reject, and silently poisoning an
  id would make a later well-formed command with that id fail.
- **Structural validation precedes the duplicate check**, so a malformed replay
  of a processed id is reported `REJECTED`, not `DUPLICATE`.
- **`OPEN` trailer format.** The spec example ends with `OPEN 0` for a run with
  no open reservations, so the trailer is printed as a count line
  (`OPEN <count>`) followed by `<order_id> <qty>` lines sorted by order id
  (ASCII order).
- **Bounds are enforced** (`qty ≤ 10^12`, `S ≤ 10^12`, `N ≤ 200 000`);
  out-of-range values are treated as malformed.
- **Header errors exit 2** with a message on stderr and no stdout, so a caller
  can distinguish "bad script" from "processed commands".
- If fewer than N command lines are supplied, the available ones are processed;
  extra lines beyond N are ignored.

## Tests included

`test_solution.py` covers: the spec example (unit + CLI), availability
enforcement, SHIP/RELEASE cannot exceed an order's reservation, partial
release/ship, rejected-then-replayed events, duplicates across command types
and arguments, every malformed shape, event-id non-consumption on malformed
input, `OPEN` ordering/zeroing, and 10^12-scale arithmetic.
