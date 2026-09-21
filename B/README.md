# Task B — Fulfilment Split Optimiser

## Run

```bash
python B/solution.py < input.txt
```

## Test

```bash
python -m unittest discover -s B -p "test_*.py" -v
```

(Standard library only. The suite includes 60 randomised cross-checks against
a brute-force reference and a full W=30, Q=2000 benchmark that finishes in
well under a second.)

## State representation

Warehouses are first sorted by `warehouse_id` (this makes every later
lexicographic comparison trivial). Then a suffix DP:

```
suf[i][k][q] = minimum cost to ship exactly q units using exactly k
               warehouses chosen from the suffix i..W-1
```

A "used" warehouse must receive **at least 1 unit**, so `k <= min(W, Q)` and
per-warehouse allocation `x` ranges over `1..min(stock_i, q)`.

Transition:

```
suf[i][k][q] = min( suf[i+1][k][q],                                  # skip i
                    min over x in 1..min(s_i,q) of
                        fixed_i + x*unit_i + suf[i+1][k-1][q-x] )    # use i
```

The inner minimisation is a sliding-window minimum of
`suf[i+1][k-1][y] - y*unit_i` over `y ∈ [q-s_i, q-1]`, evaluated with a
monotone deque, so each `(i,k)` row costs O(Q) instead of O(Q·s_i).

## Optimisation order & tie-breaking

1. `k*` = smallest `k ≥ 1` with `suf[0][k][Q] < INF`.
2. `C*` = `suf[0][k*][Q]` (minimum cost among k*-warehouse plans).
3. **Lexicographic plan**: rebuild greedily over warehouses in id order. At
   warehouse `i`, try `x = 1, 2, …` and take the first positive `x` for which a
   completion with exactly `k*-used_k-1` warehouses and total cost `C*` still
   exists (checked against the DP table); `x = 0` is only accepted when no
   positive `x` works. Because entries are compared by `(id, qty)` pairs in id
   order, putting the *smallest* positive quantity at the *earliest* id is
   always lexicographically better than skipping that warehouse entirely
   (a shorter plan must have a larger first differing id), so this greedy is
   optimal for tier 3.

## Complexity

- Time: **O(W · K · Q)** with `K = min(W, Q)` — W·K DP cells, O(Q) work per
   cell-row via the deque. At the spec limits (W=30, Q=2000): ≈ 30·30·2000 =
   1.8M cell updates plus reconstruction O(W·Q) — measured < 1 s in pure
   Python.
- Space: O(W · K · Q) integers (kept in full because reconstruction walks the
   table backwards). Only the k-dimension ≤ min(i, K) rows are materialised
   per suffix; pruning `x ≥ 1` keeps K ≤ 30.
- A subset brute force is O(2^W · poly) and fails at W=30; the DP replaces the
   subset dimension with the (k, q) state.

## Decisions & assumptions

- Impossible order (total stock < Q, or no k exists) prints `-1`.
- Zero-stock warehouses are never "used" (they cannot take ≥1 unit); they are
  still valid inputs.
- Input is validated against the declared bounds (1 ≤ W ≤ 30, 1 ≤ Q ≤ 2000);
  out-of-range headers exit 2 with a message instead of exhausting memory.
- Allocations are integers; `stock_i` is capped at Q for DP purposes since
  more than Q at one warehouse is never useful.
- Output plan lines are sorted by `warehouse_id` (ASCII), matching the input
  order used for the lexicographic tie-break.
