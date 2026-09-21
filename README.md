# Full-Stack Developer Coding Assessment

Repository layout required by the brief:

```
/A      Python solution + tests        (Task A - Inventory Reservation Ledger)
/B      Python solution + tests        (Task B - Fulfilment Split Optimiser)
/C      Written answers                (Task C - Xero Integration Review)
/app    FastAPI backend + Next.js/TS frontend (Variant PDP)
README.md (this file)
```

## Prerequisites

- Python **3.11+** (developed on 3.14) — Tasks A, B and the backend.
- Node **18+** (developed on 22) — the frontend.

## Setup & commands

```bash
# ---- Task A (stdlib only) ----
python A/solution.py < input.txt
python -m pytest A -q

# ---- Task B (stdlib only) ----
python B/solution.py < input.txt
python -m pytest B -q

# ---- Task C ----
# No code: read C/answers.md (Markdown).

# ---- App: backend ----
cd app/backend
pip install -r requirements.txt
uvicorn app.main:app --port 8000
python -m pytest app/backend/tests -q   # from repo root

# ---- App: frontend ----
cd app/frontend
npm install
npm run dev                              # http://localhost:3000, proxies /api to :8000
npm test                                 # vitest
npm run typecheck                        # strict tsc, no any
```

Full API contract, request/response examples and status codes are documented
in [`app/README.md`](app/README.md) (FastAPI's `/docs` supplements it).

## What each part does

| Part | Deliverable | Where |
|---|---|---|
| A | Deterministic, idempotent command processor for one SKU; O(N) | `A/solution.py`, `A/test_solution.py`, `A/README.md` |
| B | Multi-warehouse split optimiser (fewest warehouses → min cost → lexicographic), suffix DP + monotone deque, O(W·K·Q) | `B/solution.py`, `B/test_solution.py`, `B/README.md` |
| C | Xero sync design answers C1–C6 with official-doc references | `C/answers.md` |
| App | Variant product detail page: two option dimensions, 14 SKUs (one discontinued combo, one sold out, one single-unit for the race), idempotent add-to-cart, server-authoritative price/stock, concurrency-safe reservation | `app/backend`, `app/frontend` |

## Key assumptions

- **A** — malformed lines print `REJECTED` and do *not* consume their event id
  (id extraction from unparseable input is untrustworthy); structural
  validation precedes the duplicate check; the `OPEN` trailer is a count line
  plus `<order_id> <qty>` rows sorted by ASCII order id. Details: `A/README.md`.
- **B** — a "used" warehouse takes ≥ 1 unit; impossible orders print `-1`;
  input bounds are validated (out-of-range exits 2 rather than exhausting
  memory). Details: `B/README.md`.
- **App** — auth/checkout/payment are out of scope per the brief, so there is
  one demo cart (`cartId=default`); per-line quantity is capped at 100;
  images are generated SVGs (no binary assets committed).

## Architecture notes (app)

- **Server is the source of truth.** The add-to-cart body accepts only
  `{cartId, skuId, quantity}`; client-sent price/stock is rejected with
  `400 unexpected_fields`.
- **Idempotency.** `POST /api/cart/items` requires an `Idempotency-Key`.
  The first call stores the outcome (success *or* business rejection); a
  replay of the same key + body returns the stored response with
  `idempotentReplay: true`. Same key + different body → `422`.
- **Oversell prevention.** Storage is in-memory behind one lock; the whole
  replay-check → decrement → append → record sequence is one critical
  section, so two threads racing for the final unit yield exactly one 201
  and one 409 (covered by `TestStockRace`). Chosen trade-off: single process,
  no restart persistence. The Postgres equivalent is documented in
  `app/README.md`.
- **Frontend layering.** `src/lib/api.ts` (transport) / `src/lib/variants.ts`
  (pure domain logic, unit-tested) / `src/components` (React UI). Strict
  TypeScript, no `any`.

## Known limitations

- In-memory store: restarting the backend resets stock and carts (seed
  re-applied so the app is usable immediately).
- The stock-race test uses `TestClient` threads — it proves the lock
  serialises the critical section but cannot model multi-process races (which
  the single-process assumption rules out).
- Frontend tests mock the network with `fetch` stubs rather than a live
  server; the backend contract tests run against the real ASGI app.
- `C/answers.md` reflects Xero's public docs at authoring time; API behaviour
  can change (links listed at the bottom of that file).

## AI assistance disclosure

AI-assisted tooling (Qwen Work Assistant) was used to draft and review code,
tests and documentation across A, B, C and the app, under the candidate's
direction: design choices (DP state shape, idempotency envelope, lock
strategy, test seams) were specified and every file was executed and verified
locally (all suites green, strict typecheck clean, production build clean).
Any decision below can be explained and modified live.

## No secrets

No credentials, tokens or customer data are committed. The backend needs no
environment variables to run; `BACKEND_URL` (frontend proxy) is optional.
