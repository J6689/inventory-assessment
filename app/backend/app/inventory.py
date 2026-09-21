"""Stock reservation and idempotent cart helpers for the in-memory store.

Every function here assumes the caller already holds ``store.lock``: main.py
keeps the whole read-check-write (replay check -> stock reservation -> cart
mutation -> record the replayable outcome) inside one critical section.
That is what makes the last-unit reservation race-free — two concurrent
adds for the final unit cannot both succeed.
"""
from __future__ import annotations

import hashlib
import json

from .store import IdempotentRecord, Store


class InsufficientStock(Exception):
    def __init__(self, sku_id: str, requested: int, available: int):
        super().__init__(f"sku {sku_id}: requested {requested}, available {available}")
        self.sku_id, self.requested, self.available = sku_id, requested, available


def request_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def begin_idempotent(store: Store, key: str, payload: dict):
    """Return (replayed_status, replayed_body) if the key was seen before.

    (None, None) means this caller owns the key and must run the operation,
    then call finish_idempotent to store the outcome for future replays.
    Re-using a key with a *different* body is a client bug: raise so the
    caller can surface a 422 instead of silently mixing two requests.
    """
    h = request_hash(payload)
    rec = store.idempotency.get(key)
    if rec is not None:
        if rec.request_hash != h:
            raise ValueError("idempotency key reused with a different request body")
        return rec.status_code, json.loads(rec.response_body)
    return None, None


def finish_idempotent(store: Store, key: str, payload: dict,
                      status: int, body: dict) -> None:
    """Record the outcome (success *or* business rejection) for replay.

    Recording rejections too matches the Task A rule we apply repo-wide: a
    rejected business operation is still considered processed, so a retry of
    the same key replays the same 409/404 instead of re-attempting.
    """
    store.idempotency[key] = IdempotentRecord(request_hash(payload), status, json.dumps(body))


def reserve_stock(store: Store, sku_id: str, qty: int) -> int:
    """Atomically decrement stock; returns the post-reservation quantity.

    The availability check happens *before* the mutation, so a failure never
    leaves partial state (no compensating rollback needed on this path).
    """
    sku = store.skus.get(sku_id)
    if sku is None:
        raise InsufficientStock(sku_id, qty, 0)
    if sku.available_qty < qty:
        raise InsufficientStock(sku_id, qty, sku.available_qty)
    sku.available_qty -= qty
    return sku.available_qty
