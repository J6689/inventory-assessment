from __future__ import annotations

import itertools
import random
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import solution as sol  # noqa: E402


def brute(warehouses, q):
    """Reference: enumerate all subsets and all allocations; apply the 3-tier order."""
    best = None
    ids_sorted = sorted(range(len(warehouses)), key=lambda i: warehouses[i][0])
    for r in range(1, len(warehouses) + 1):
        for subset in itertools.combinations(ids_sorted, r):
            stocks = [min(warehouses[i][1], q) for i in subset]
            if sum(stocks) < q:
                continue
            # enumerate compositions of q over the subset with per-cap bounds
            def rec(idx, remaining, acc):
                if idx == len(subset):
                    if remaining == 0:
                        yield list(acc)
                    return
                cap = min(stocks[idx], remaining)
                for x in range(1, cap + 1):
                    acc.append(x)
                    yield from rec(idx + 1, remaining - x, acc)
                    acc.pop()
            for alloc in rec(0, q, []):
                cost = sum(warehouses[i][2] + alloc[t] * warehouses[i][3]
                           for t, i in enumerate(subset))
                plan = [(warehouses[i][0], alloc[t]) for t, i in enumerate(subset)]
                key = (r, cost, plan)
                if best is None or key < best:
                    best = key
    if best is None:
        return None
    return best[0], best[1], best[2]


class TestSpecExample(unittest.TestCase):
    def test_example(self):
        ws = [("AU", 5, 8, 2), ("CN", 7, 20, 1), ("US", 4, 3, 4)]
        self.assertEqual(sol.solve(ws, 7), (1, 27, [("CN", 7)]))

    def test_cli(self):
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "solution.py")],
            input="3 7\nAU 5 8 2\nCN 7 20 1\nUS 4 3 4\n",
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.splitlines(), ["1 27", "CN 7"])


class TestImpossible(unittest.TestCase):
    def test_insufficient_total_stock(self):
        self.assertIsNone(sol.solve([("A", 3, 1, 1), ("B", 2, 1, 1)], 10))

    def test_zero_stock_warehouses_ignored(self):
        self.assertIsNone(sol.solve([("A", 0, 1, 1)], 1))
        self.assertEqual(sol.solve([("A", 0, 1, 1), ("B", 5, 2, 1)], 4),
                         (1, 6, [("B", 4)]))

    def test_cli_impossible_prints_minus_one(self):
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "solution.py")],
            input="2 10\nA 3 1 1\nB 2 1 1\n", capture_output=True, text=True)
        self.assertEqual(proc.stdout.strip(), "-1")


class TestObjectiveOrder(unittest.TestCase):
    def test_fewest_warehouses_beats_cost(self):
        # one warehouse (B) can do it for 100; two cheap ones cost 10 total.
        ws = [("A", 3, 1, 1), ("B", 10, 50, 5)]
        self.assertEqual(sol.solve(ws, 6), (1, 80, [("B", 6)]))

    def test_cost_beats_lexicographic(self):
        # both single-warehouse options valid; cheaper one wins even with larger id
        ws = [("A", 5, 100, 0), ("B", 5, 1, 0)]
        self.assertEqual(sol.solve(ws, 5), (1, 1, [("B", 5)]))

    def test_lexicographic_breaks_equal_cost_ties(self):
        ws = [("B", 5, 5, 0), ("A", 5, 5, 0)]
        self.assertEqual(sol.solve(ws, 5), (1, 5, [("A", 5)]))

    def test_smallest_allocation_at_earliest_id(self):
        # two warehouses needed; A can take 1..4. Lexicographic picks A=1.
        ws = [("A", 4, 0, 0), ("B", 4, 0, 0)]
        self.assertEqual(sol.solve(ws, 6), (2, 0, [("A", 2), ("B", 4)]))

    def test_split_prefers_more_at_earlier_when_equal(self):
        # A stock 5, B stock 5, Q=8, equal cost: (A,3)(B,5) vs (A,4)(B,4)... 
        # smallest first element wins -> A=3
        ws = [("A", 5, 0, 1), ("B", 5, 0, 1)]
        self.assertEqual(sol.solve(ws, 8), (2, 8, [("A", 3), ("B", 5)]))


class TestBruteForceCrossCheck(unittest.TestCase):
    def test_random_small_cases(self):
        rng = random.Random(42)
        for _ in range(60):
            n = rng.randint(1, 5)
            q = rng.randint(1, 8)
            ids = rng.sample(
                ["AU", "CN", "DE", "FR", "GB", "JP", "US"], n)
            ws = [(wid, rng.randint(0, 6), rng.randint(0, 15), rng.randint(0, 6))
                  for wid in ids]
            got = sol.solve(ws, q)
            want = brute(ws, q)
            self.assertEqual(got, want, msg=f"ws={ws} q={q}")


class TestScale(unittest.TestCase):
    def test_max_size_input_runs_fast(self):
        rng = random.Random(7)
        ws = [(f"W{i:04d}", rng.randint(0, 2000), rng.randint(0, 10**6),
               rng.randint(0, 10**6)) for i in range(30)]
        start = time.perf_counter()
        result = sol.solve(ws, 2000)
        elapsed = time.perf_counter() - start
        self.assertIsNotNone(result)
        k, cost, alloc = result
        self.assertLessEqual(k, 30)
        self.assertEqual(sum(a[1] for a in alloc), 2000)
        self.assertLess(elapsed, 10.0, f"too slow: {elapsed:.1f}s")

    def test_large_costs_exact(self):
        # Q is bounded by 2000 per spec; costs may reach 10^6 * 2000 + 10^6.
        ws = [("A", 2000, 10**6, 10**6), ("B", 2000, 10**6, 999_999)]
        self.assertEqual(sol.solve(ws, 2000), (1, 10**6 + 2000 * 999_999, [("B", 2000)]))


class TestAllocationValidity(unittest.TestCase):
    def test_allocations_respect_stock_and_sum(self):
        ws = [("A", 5, 1, 1), ("B", 7, 2, 1), ("C", 3, 1, 2)]
        k, cost, alloc = sol.solve(ws, 12)
        self.assertEqual(sum(x for _, x in alloc), 12)
        stock = dict((w[0], w[1]) for w in ws)
        for wid, x in alloc:
            self.assertLessEqual(x, stock[wid])
        self.assertEqual(k, len(alloc))
        recomputed = sum(next(w[2] for w in ws if w[0] == wid) + x *
                         next(w[3] for w in ws if w[0] == wid)
                         for wid, x in alloc)
        self.assertEqual(recomputed, cost)


if __name__ == "__main__":
    unittest.main()
