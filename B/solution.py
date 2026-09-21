from __future__ import annotations

import sys
from collections import deque

INF = 10**30


def solve(warehouses: list[tuple[str, int, int, int]], q: int):
    """Return (k*, cost*, [(id, qty)...]) or None when q units cannot be shipped."""
    if sum(w[1] for w in warehouses) < q:
        return None  # every warehouse contributes at most its stock

    ws = sorted(warehouses, key=lambda w: w[0])  # lexicographic id order
    ids = [w[0] for w in ws]
    stock = [min(w[1], q) for w in ws]           # more than q is never useful
    fixed = [w[2] for w in ws]
    unit = [w[3] for w in ws]
    n = len(ws)
    k_max = min(n, q)                             # a used warehouse takes >= 1 unit

    # suf[i] is a (k_max+1) x (q+1) table for the suffix starting at i.
    suf: list[list[list[int]]] = [None] * (n + 1)  # type: ignore[list-item]
    last = [[INF] * (q + 1) for _ in range(k_max + 1)]
    last[0][0] = 0
    suf[n] = last

    for i in range(n - 1, -1, -1):
        nxt = suf[i + 1]
        cur = [[INF] * (q + 1) for _ in range(k_max + 1)]
        s, f, u = stock[i], fixed[i], unit[i]
        for k in range(k_max + 1):
            row = cur[k]
            base = nxt[k]                          # allocate 0 here
            # copy x=0 option
            for qq in range(q + 1):
                row[qq] = base[qq]
            if k == 0 or s == 0:
                continue
            prev = nxt[k - 1]                      # allocate x>=1 here
            # cost(q) = f + q*u + min_{y in [q-s, q-1]} (prev[y] - y*u)
            dq: deque[int] = deque()
            for qq in range(q + 1):
                y_new = qq - 1
                if y_new >= 0 and prev[y_new] < INF:
                    v = prev[y_new] - y_new * u
                    while dq and prev[dq[-1]] - dq[-1] * u >= v:
                        dq.pop()
                    dq.append(y_new)
                limit = qq - s
                while dq and dq[0] < limit:
                    dq.popleft()
                if dq:
                    y0 = dq[0]
                    cand = f + qq * u + prev[y0] - y0 * u
                    if cand < row[qq]:
                        row[qq] = cand
        suf[i] = cur

    k_star = next((k for k in range(1, k_max + 1) if suf[0][k][q] < INF), None)
    if k_star is None:
        return None
    cost_star = suf[0][k_star][q]

    # Greedy reconstruction for the lexicographically smallest plan.
    alloc: list[tuple[str, int]] = []
    used_k, used_cost, remaining = 0, 0, q
    for i in range(n):
        chosen = 0
        for x in range(1, min(stock[i], remaining) + 1):
            k_rem = k_star - used_k - 1
            if k_rem < 0:
                break
            rest = suf[i + 1][k_rem][remaining - x]
            if rest < INF and used_cost + fixed[i] + x * unit[i] + rest == cost_star:
                chosen = x
                break
        if chosen == 0:
            k_rem = k_star - used_k
            if not (0 <= k_rem <= k_max and suf[i + 1][k_rem][remaining] < INF
                    and used_cost + suf[i + 1][k_rem][remaining] == cost_star):
                raise AssertionError("reconstruction failed - DP bug")
        if chosen:
            alloc.append((ids[i], chosen))
            used_k += 1
            used_cost += fixed[i] + chosen * unit[i]
            remaining -= chosen
    return k_star, cost_star, alloc


def main() -> int:
    data = sys.stdin.read().split()
    if len(data) < 2:
        print("missing W Q header", file=sys.stderr)
        return 2
    w_count, q = int(data[0]), int(data[1])
    # The DP is O(W*Q*min(W,Q)); the spec bounds keep it tractable.
    if not (1 <= w_count <= 30 and 1 <= q <= 2000):
        print("W/Q out of supported range (1<=W<=30, 1<=Q<=2000)", file=sys.stderr)
        return 2
    if len(data) < 2 + 4 * w_count:
        print(f"expected {w_count} warehouse lines", file=sys.stderr)
        return 2
    warehouses = []
    idx = 2
    for _ in range(w_count):
        wid = data[idx]
        st, fc, uc = int(data[idx + 1]), int(data[idx + 2]), int(data[idx + 3])
        warehouses.append((wid, st, fc, uc))
        idx += 4
    result = solve(warehouses, q)
    if result is None:
        print(-1)
    else:
        k, cost, alloc = result
        print(k, cost)
        for wid, qty in alloc:
            print(wid, qty)
    return 0


if __name__ == "__main__":
    sys.exit(main())
