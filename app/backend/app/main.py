"""Variant PDP backend — FastAPI (in-memory storage).

Endpoints (contract documented in the root README.md):
  GET  /api/products/{id}     product, option dimensions, SKUs
  POST /api/cart/items        add SKU + qty (requires Idempotency-Key header)
  GET  /api/cart              current cart + total item count
  GET  /api/images/{name}     generated SVG product images
  GET  /api/health            liveness

Design decisions worth flagging:
  * The server is the source of truth for price and stock: the add-to-cart
    body carries ONLY {cartId, skuId, quantity}. Any price/stock sent by the
    client is rejected outright (unexpected_fields below).
  * The whole add-to-cart critical section runs under store.lock, so the
    replay check, the stock reservation and the cart mutation are one atomic
    unit. That is what prevents overselling the final unit under concurrency.
  * Business rejections (unknown SKU, insufficient stock) are recorded
    against the idempotency key and replayed verbatim, matching the repo-wide
    rule that a rejected operation is still "processed".
"""
from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from .inventory import (
    InsufficientStock,
    begin_idempotent,
    finish_idempotent,
    reserve_stock,
)
from .store import CartLine, Store, colour_svg, create_store

CART_ID = "default"  # auth is out of scope per brief; one demo cart
MAX_LINE_QTY = 100   # arbitrary per-line cap, documented in the README


def error(status: int, code: str, message: str, **details) -> JSONResponse:
    """Uniform error envelope so the frontend can branch on `code`."""
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return JSONResponse(status_code=status, content=body)


def create_app(store: Store | None = None) -> FastAPI:
    app = FastAPI(title="Variant PDP API", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # demo app; tighten in a real deployment
        allow_methods=["*"],
        allow_headers=["*"],
    )
    store = store or create_store()
    app.state.store = store

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/products/{product_id}")
    def get_product(product_id: str):
        # Snapshot under the lock, serialise outside it: the response is built
        # from plain ints/strings, so no torn reads are possible.
        with store.lock:
            product = store.products.get(product_id)
            if not product:
                return error(404, "product_not_found",
                             f"Unknown product '{product_id}'.")
            snapshot = {
                "product": {
                    "id": product.id,
                    "name": product.name,
                    "description": product.description,
                    "currency": product.currency,
                },
                "dimensions": [
                    {"id": d.id, "label": d.label, "values": list(d.values)}
                    for d in product.dimensions
                ],
                "skus": [
                    {
                        "id": s.id,
                        "options": dict(s.options),
                        "priceCents": s.price_cents,
                        "currency": product.currency,
                        "image": s.image,
                        "availableQuantity": s.available_qty,
                        "inStock": s.available_qty > 0,
                    }
                    for s in sorted(product.skus, key=lambda s: s.id)
                ],
            }
        return snapshot

    @app.post("/api/cart/items")
    def add_to_cart(
        payload: dict = Body(...),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        # --- validate shape before touching any state (fail explicitly) ---
        allowed = {"cartId", "skuId", "quantity"}
        extra = set(payload) - allowed
        if extra:
            # Rejecting client-sent price/stock is an explicit requirement.
            return error(400, "unexpected_fields",
                         "Only cartId, skuId and quantity are accepted.",
                         fields=sorted(extra))
        sku_id = payload.get("skuId")
        quantity = payload.get("quantity", 1)
        cart_id = payload.get("cartId", CART_ID)
        if not isinstance(sku_id, str) or not sku_id:
            return error(422, "invalid_sku", "skuId must be a non-empty string.")
        # bool is a subclass of int in Python — reject it explicitly.
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
            return error(422, "invalid_quantity",
                         "quantity must be an integer >= 1.", received=quantity)
        if quantity > MAX_LINE_QTY:
            return error(422, "quantity_too_large",
                         f"Single-line quantity is capped at {MAX_LINE_QTY}.",
                         max=MAX_LINE_QTY)
        if not isinstance(cart_id, str) or not cart_id:
            return error(422, "invalid_cart", "cartId must be a non-empty string.")
        if not idempotency_key or not idempotency_key.strip():
            return error(400, "missing_idempotency_key",
                         "Idempotency-Key header is required for cart writes.")
        key = idempotency_key.strip()
        normalized = {"cartId": cart_id, "skuId": sku_id, "quantity": quantity}

        def respond(status: int, body: dict) -> JSONResponse:
            """Record the outcome for replay, then return it."""
            finish_idempotent(store, key, normalized, status, body)

        with store.lock:
            replay = begin_idempotent(store, key, normalized)
            if replay[0] is not None:
                status, body = replay  # type: ignore[misc]
                if isinstance(body, dict) and "item" in body:
                    body = {**body, "idempotentReplay": True}
                return JSONResponse(status_code=status, content=body)

            sku = store.skus.get(sku_id)
            if sku is None:
                body = {"error": {"code": "sku_not_found",
                                  "message": f"Unknown SKU '{sku_id}'."}}
                respond(404, body)
                return JSONResponse(status_code=404, content=body)

            try:
                remaining = reserve_stock(store, sku_id, quantity)
            except InsufficientStock as exc:
                body = {"error": {"code": "insufficient_stock",
                                  "message": str(exc),
                                  "details": {"skuId": exc.sku_id,
                                              "requested": exc.requested,
                                              "available": exc.available}}}
                respond(409, body)
                return JSONResponse(status_code=409, content=body)

            try:
                lines = store.carts.setdefault(cart_id, [])
                lines.append(CartLine(sku_id, quantity, sku.price_cents))
                body = {
                    "item": {"skuId": sku_id, "quantity": quantity,
                             "unitPriceCents": sku.price_cents},
                    "sku": {"id": sku_id, "availableQuantity": remaining},
                    "cart": {"cartId": cart_id,
                             "totalItems": sum(l.quantity for l in lines)},
                    "idempotentReplay": False,
                }
                respond(201, body)
            except Exception:
                # Unexpected failure: undo both side effects so state stays
                # consistent and the key remains free for a genuine retry.
                sku.available_qty += quantity
                if lines and lines[-1].sku_id == sku_id:
                    lines.pop()
                raise
            return JSONResponse(status_code=201, content=body)

    @app.exception_handler(ValueError)
    def value_error_handler(_request, exc: ValueError):
        # Raised only by begin_idempotent: same key, different body.
        return error(422, "idempotency_key_reuse", str(exc))

    @app.get("/api/cart")
    def get_cart(cartId: str = CART_ID):
        with store.lock:
            lines = list(store.carts.get(cartId, ()))
            options = {s.id: dict(s.options) for s in store.skus.values()}
        items = [{
            "skuId": line.sku_id,
            "quantity": line.quantity,
            "unitPriceCents": line.unit_price_cents,
            "options": options.get(line.sku_id, {}),
        } for line in lines]
        return {"cart": {
            "cartId": cartId,
            "items": items,
            "totalItems": sum(i["quantity"] for i in items),
            "subtotalCents": sum(i["quantity"] * i["unitPriceCents"] for i in items),
        }}

    @app.get("/api/images/{image_name}")
    def get_image(image_name: str):
        sku_id = image_name.removesuffix(".svg")
        with store.lock:
            sku = store.skus.get(sku_id)
        if not sku:
            return error(404, "image_not_found", f"No image for '{image_name}'.")
        svg = colour_svg(sku.options["colour"], sku.options["size"])
        return Response(content=svg, media_type="image/svg+xml",
                        headers={"Cache-Control": "public, max-age=3600"})

    return app


app = create_app()
