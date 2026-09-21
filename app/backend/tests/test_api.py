"""API tests: success, validation, idempotency, and the stock race.

Each test gets a freshly seeded in-memory store, so tests are independent
and the race test really exercises two threads against one lock.

Run:  python -m pytest app/backend/tests -q     (from repo root)
"""
from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402
from app.store import create_store  # noqa: E402


def make_client() -> TestClient:
    return TestClient(create_app(create_store()))


class TestProduct(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = make_client()

    def test_product_payload_shape(self):
        res = self.client.get("/api/products/aurora-trail")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["product"]["id"], "aurora-trail")
        self.assertEqual({d["id"] for d in data["dimensions"]},
                         {"colour", "size"})
        skus = {s["id"]: s for s in data["skus"]}
        # >= 6 SKUs incl. one out-of-stock (Cobalt 11)
        self.assertGreaterEqual(len(skus), 6)
        self.assertEqual(skus["aurora-cobalt-11"]["availableQuantity"], 0)
        self.assertFalse(skus["aurora-cobalt-11"]["inStock"])
        # unavailable combination: Slate 7 has no SKU row at all
        self.assertNotIn("aurora-slate-7", skus)

    def test_unknown_product_404(self):
        res = self.client.get("/api/products/nope")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["error"]["code"], "product_not_found")


class TestAddToCart(unittest.TestCase):
    def setUp(self):
        self.client = make_client()

    def _add(self, sku="aurora-cobalt-8", qty=2, key=None, **extra):
        payload = {"skuId": sku, "quantity": qty, **extra}
        headers = {"Idempotency-Key": key or f"k-{threading.get_ident()}-{qty}"}
        return self.client.post("/api/cart/items", json=payload, headers=headers)

    def test_success(self):
        res = self._add(qty=2, key="ok-1")
        self.assertEqual(res.status_code, 201)
        body = res.json()
        self.assertEqual(body["item"]["unitPriceCents"], 14900)  # server price
        self.assertEqual(body["sku"]["availableQuantity"], 6)
        self.assertEqual(body["cart"]["totalItems"], 2)
        cart = self.client.get("/api/cart").json()["cart"]
        self.assertEqual(cart["totalItems"], 2)
        self.assertEqual(cart["subtotalCents"], 2 * 14900)

    def test_quantity_bounded_by_stock(self):
        res = self._add(sku="aurora-cobalt-11", qty=1, key="oos-1")
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["error"]["code"], "insufficient_stock")
        self.assertEqual(res.json()["error"]["details"]["available"], 0)

    def test_validation_errors(self):
        cases = [
            ({"skuId": "ghost", "quantity": 1}, "missing-ok", 404),
            ({"skuId": "", "quantity": 1}, "missing-ok", 422),
            ({"skuId": "aurora-cobalt-8", "quantity": 0}, "missing-ok", 422),
            ({"skuId": "aurora-cobalt-8", "quantity": "2"}, "missing-ok", 422),
            ({"skuId": "aurora-cobalt-8", "quantity": 1, "priceCents": 1},
             "missing-ok", 400),  # client-sent price rejected outright
        ]
        for payload, key, status in cases:
            with self.subTest(payload=payload):
                res = self.client.post(
                    "/api/cart/items", json=payload,
                    headers={"Idempotency-Key": key})
                self.assertEqual(res.status_code, status)
                self.assertIn("error", res.json())

    def test_idempotency_key_required(self):
        res = self.client.post("/api/cart/items",
                               json={"skuId": "aurora-cobalt-8", "quantity": 1})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["error"]["code"], "missing_idempotency_key")

    def test_duplicate_key_replays_without_double_add(self):
        first = self._add(qty=3, key="dup-1")
        second = self._add(qty=3, key="dup-1")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        replay = second.json()
        self.assertTrue(replay["idempotentReplay"])
        self.assertEqual(replay, {**first.json(), "idempotentReplay": True})
        cart = self.client.get("/api/cart").json()["cart"]
        self.assertEqual(cart["totalItems"], 3)  # not 6

    def test_duplicate_key_replays_error_response(self):
        first = self._add(sku="aurora-cobalt-11", qty=1, key="dup-err")
        second = self._add(sku="aurora-cobalt-11", qty=1, key="dup-err")
        self.assertEqual(first.status_code, 409)
        self.assertEqual(second.status_code, 409)  # recorded outcome is replayed

    def test_key_reuse_with_different_body_rejected(self):
        self._add(qty=1, key="reuse-1")
        res = self._add(qty=2, key="reuse-1")
        self.assertEqual(res.status_code, 422)
        self.assertEqual(res.json()["error"]["code"], "idempotency_key_reuse")


class TestStockRace(unittest.TestCase):
    def test_last_unit_not_oversold(self):
        """Two concurrent adds for the final unit: exactly one wins."""
        client = make_client()
        sku = "aurora-sand-9"  # seeded with availableQuantity = 1
        results = {}
        barrier = threading.Barrier(2)

        def worker(name):
            barrier.wait()
            res = client.post(
                "/api/cart/items",
                json={"skuId": sku, "quantity": 1},
                headers={"Idempotency-Key": f"race-{name}"})
            results[name] = (res.status_code, res.json())

        threads = [threading.Thread(target=worker, args=(n,))
                   for n in ("a", "b")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        codes = sorted(c for c, _ in results.values())
        self.assertEqual(codes, [201, 409],
                         f"expected one success and one rejection, got {codes}")
        loser = next(b for c, b in results.values() if c == 409)
        self.assertEqual(loser["error"]["code"], "insufficient_stock")
        # stock is exactly zero now, cart holds exactly one unit
        product = client.get("/api/products/aurora-trail").json()
        stock = {s["id"]: s["availableQuantity"] for s in product["skus"]}
        self.assertEqual(stock[sku], 0)
        cart = client.get("/api/cart").json()["cart"]
        self.assertEqual(
            sum(i["quantity"] for i in cart["items"] if i["skuId"] == sku), 1)


if __name__ == "__main__":
    unittest.main()
