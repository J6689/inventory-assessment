from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import solution as sol  # noqa: E402

SPEC_INPUT = (
    "10 6\n"
    "RESERVE e1 o100 4\n"
    "RESERVE e2 o200 7\n"
    "SHIP e3 o100 2\n"
    "RELEASE e4 o100 2\n"
    "RESTOCK e5 3\n"
    "RESERVE e2 o999 1\n"
)
SPEC_OUTPUT = [
    "OK 10 4",
    "REJECTED 10 4",
    "OK 8 2",
    "OK 8 0",
    "OK 11 0",
    "DUPLICATE 11 0",
    "OPEN 0",
]


def run(stock: int, cmds: list[str]) -> list[str]:
    return sol.process(stock, cmds)


class TestSpecExample(unittest.TestCase):
    def test_process_matches_example(self):
        cmds = SPEC_INPUT.splitlines()[1:]
        self.assertEqual(run(10, cmds), SPEC_OUTPUT)

    def test_cli_end_to_end(self):
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "solution.py")],
            input=SPEC_INPUT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.splitlines(), SPEC_OUTPUT)

    def test_cli_rejects_bad_header(self):
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "solution.py")],
            input="ten 6\n",
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, "")


class TestStateTransitions(unittest.TestCase):
    def test_reserve_requires_available_stock(self):
        out = run(5, ["RESERVE a o1 5", "RESERVE b o2 1"])
        self.assertEqual(out[0], "OK 5 5")
        self.assertEqual(out[1], "REJECTED 5 5")

    def test_ship_reduces_both_on_hand_and_reserved(self):
        out = run(10, ["RESERVE a o1 6", "SHIP b o1 6"])
        self.assertEqual(out[1], "OK 4 0")

    def test_release_returns_stock_to_available(self):
        out = run(4, ["RESERVE a o1 4", "RELEASE b o1 4", "RESERVE c o2 4"])
        self.assertEqual(out[0], "OK 4 4")
        self.assertEqual(out[1], "OK 4 0")
        self.assertEqual(out[2], "OK 4 4")

    def test_release_cannot_exceed_order_reservation(self):
        out = run(10, ["RESERVE a o1 4", "RELEASE b o1 5"])
        self.assertEqual(out[1], "REJECTED 10 4")

    def test_ship_cannot_exceed_order_reservation(self):
        out = run(10, ["RESERVE a o1 4", "SHIP b o1 5"])
        self.assertEqual(out[1], "REJECTED 10 4")

    def test_release_of_unknown_order_rejected(self):
        self.assertEqual(run(10, ["RELEASE a ghost 1"])[0], "REJECTED 10 0")

    def test_partial_release_and_ship(self):
        out = run(10, ["RESERVE a o1 8", "SHIP b o1 3", "RELEASE c o1 5"])
        self.assertEqual(out[1], "OK 7 5")
        self.assertEqual(out[2], "OK 7 0")

    def test_multiple_orders_accumulate(self):
        out = run(10, ["RESERVE a o1 3", "RESERVE b o2 4"])
        self.assertEqual(out[1], "OK 10 7")


class TestIdempotency(unittest.TestCase):
    def test_replay_of_ok_event_is_duplicate_without_state_change(self):
        out = run(10, ["RESERVE a o1 4", "RESERVE a o1 4"])
        self.assertEqual(out[1], "DUPLICATE 10 4")

    def test_rejected_event_is_still_processed(self):
        out = run(5, ["RESERVE a o1 9", "RESERVE a o1 1"])
        self.assertEqual(out[0], "REJECTED 5 0")
        self.assertEqual(out[1], "DUPLICATE 5 0")

    def test_duplicate_ignores_different_arguments(self):
        # Mirrors the spec example: same event_id, different order/qty.
        out = run(10, ["RESERVE e2 o200 7", "RESERVE e2 o999 1"])
        self.assertEqual(out[1], "DUPLICATE 10 7")

    def test_duplicate_across_command_types(self):
        out = run(10, ["RESERVE x o1 2", "SHIP x o1 2"])
        self.assertEqual(out[1], "DUPLICATE 10 2")

    def test_restock_duplicate(self):
        out = run(1, ["RESTOCK r 5", "RESTOCK r 5"])
        self.assertEqual(out, ["OK 6 0", "DUPLICATE 6 0", "OPEN 0"][:2] + ["OPEN 0"])


class TestMalformedInput(unittest.TestCase):
    BAD = [
        "RESERVE a o1",          # missing qty
        "RESERVE a o1 0",        # qty not positive
        "RESERVE a o1 -3",       # negative
        "RESERVE a o1 1.5",      # not an integer
        "RESERVE a o1 abc",      # not numeric
        "RESTOCK a",             # missing qty
        "RESTOCK a o1 2",        # wrong arity
        "TRANSFER a o1 2",       # unknown verb
        "reserve a o1 2",        # verbs are case-sensitive per spec tokens
        "",                      # blank line
        "RESERVE a o1 2 9",      # extra token
    ]

    def test_each_malformed_line_rejected_without_state_change(self):
        for line in self.BAD:
            with self.subTest(line=line):
                out = run(7, [line])
                self.assertEqual(out[0], "REJECTED 7 0")

    def test_malformed_line_does_not_consume_event_id(self):
        # A line we could not parse must not poison the idempotency ledger:
        # the well-formed retry with the same event id still executes.
        out = run(10, ["RESERVE a o1 x", "RESERVE a o1 2"])
        self.assertEqual(out[0], "REJECTED 10 0")
        self.assertEqual(out[1], "OK 10 2")

    def test_non_ascii_event_token_rejected(self):
        out = run(10, ["RESERVE \u00e9vent o1 2"])
        self.assertEqual(out[0], "REJECTED 10 0")


class TestOpenTrailer(unittest.TestCase):
    def test_open_lists_orders_sorted_and_drops_zero(self):
        out = run(10, [
            "RESERVE a o2 3",
            "RESERVE b o1 2",
            "SHIP c o1 2",
            "RESERVE d o10 1",
        ])
        self.assertEqual(out[-3:], ["OPEN 2", "o10 1", "o2 3"])

    def test_open_zero_when_nothing_reserved(self):
        self.assertEqual(run(0, [])[-1], "OPEN 0")


class TestLargeValues(unittest.TestCase):
    def test_10_pow_12_arithmetic(self):
        big = 10**12
        out = run(big, [
            f"RESERVE a o1 {big}",
            f"SHIP b o1 {big}",
            f"RESTOCK c {big}",
        ])
        self.assertEqual(out[0], f"OK {big} {big}")
        self.assertEqual(out[1], f"OK 0 0")
        self.assertEqual(out[2], f"OK {big} 0")


if __name__ == "__main__":
    unittest.main()
