# Variant PDP — full-stack app

FastAPI backend (in-memory storage) + Next.js/TypeScript frontend.

## Run

Two terminals, both from the repo root:

```bash
# 1. backend on :8000  (Python 3.11+)
cd app/backend
pip install -r requirements.txt
uvicorn app.main:app --port 8000

# 2. frontend on :3000 (Node 18+)
cd app/frontend
npm install
npm run dev
```

Open http://localhost:3000. The frontend proxies `/api/*` to the backend via
`next.config.ts` rewrites, so no CORS setup is needed. Point the proxy
elsewhere with `BACKEND_URL=...` when starting `npm run dev`.

## Tests

```bash
# backend (success, validation, idempotency, stock race)
python -m pytest app/backend/tests -q

# frontend (variant resolution, disabled combos, double-click, error UX)
cd app/frontend && npm test

# frontend type check (strict, no any)
cd app/frontend && npm run typecheck
```

## API contract

### `GET /api/products/{id}`

`200`:
```json
{
  "product": { "id": "aurora-trail", "name": "Aurora Trail Runner",
               "description": "...", "currency": "USD" },
  "dimensions": [ { "id": "colour", "label": "Colour",
                    "values": ["Cobalt", "Sand", "Slate"] }, ... ],
  "skus": [ { "id": "aurora-cobalt-8", "options": {"colour":"Cobalt","size":"8"},
              "priceCents": 14900, "currency": "USD",
              "image": "/api/images/aurora-cobalt-8.svg",
              "availableQuantity": 8, "inStock": true }, ... ]
}
```
`404` unknown product: `{ "error": { "code": "product_not_found", "message": "..." } }`

An **unavailable combination** (Slate 7) has *no SKU row at all*; the client
derives disabled states from the option matrix. An **out-of-stock SKU**
(Cobalt 11) appears with `availableQuantity: 0, inStock: false`.

### `POST /api/cart/items`

Requires header `Idempotency-Key: <client-generated uuid>`.
Body accepts **only** `{ "skuId": "...", "quantity": 2 }` (and optional
`cartId`). Price and stock are server-side truth — sending them fails.

`201`:
```json
{ "item": { "skuId": "aurora-cobalt-8", "quantity": 2, "unitPriceCents": 14900 },
  "sku": { "id": "aurora-cobalt-8", "availableQuantity": 6 },
  "cart": { "cartId": "default", "totalItems": 2 },
  "idempotentReplay": false }
```

| Status | `error.code` | Meaning |
|---|---|---|
| 400 | `missing_idempotency_key` | Header absent/blank |
| 400 | `unexpected_fields` | Client sent price/stock/unknown fields |
| 404 | `sku_not_found` | Unknown SKU id |
| 409 | `insufficient_stock` | Requested > available (`details` carries both) |
| 422 | `invalid_sku` / `invalid_quantity` / `quantity_too_large` / `invalid_cart` | Shape validation |
| 422 | `idempotency_key_reuse` | Same key, different body |
| 500 | `internal_error` | Unexpected failure; nothing was applied |

Replaying the same key + body returns the **stored outcome verbatim**
(`201` or `4xx`) with `idempotentReplay: true` — no second cart line, no
second stock decrement.

### `GET /api/cart?cartId=default`

`200`: `{ "cart": { "cartId", "items": [...], "totalItems", "subtotalCents" } }`

## Preventing overselling (the concurrency answer)

Storage is a single in-process store guarded by one `threading.Lock`
(`app/store.py`). FastAPI runs sync endpoints on a threadpool, so the whole
critical section — idempotency replay check → conditional stock decrement →
cart append → outcome recorded for replay — runs inside that lock
(`app/main.py:add_to_cart`). Two concurrent adds for the final unit are
serialised: the loser sees `available_qty < qty` and gets `409` with zero
side effects. The regression test `TestStockRace` fires exactly this race
with a barrier and asserts one `201` + one `409`.

**Trade-off:** one-process deployment and no persistence across restarts
(catalogue re-seeds at boot so the app is instantly usable). The same
pattern ports to Postgres as `UPDATE skus SET available_qty = available_qty - :q
WHERE id = :id AND available_qty >= :q` inside a transaction — the
`WHERE` carries the check, so there is no read-modify-write window.

## Frontend behaviour notes

- Variant selection is resolved by a pure function (`src/lib/variants.ts`)
  that computes the selected SKU, per-value availability (impossible combos
  are disabled + struck through), and out-of-stock state.
- Quantity is clamped to `[1, available]` and re-clamped whenever the
  selected SKU or its stock changes.
- Add-to-cart disables the button while pending (double-click cannot fire a
  second request) and announces success/failure through `aria-live` regions.
- Product load failures show a retryable error state; a failed request never
  requires a full page refresh.
