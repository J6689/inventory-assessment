"""In-memory domain store for the Variant PDP demo.

The assessment allows in-memory or SQLite storage; we use a single
process-wide store guarded by one lock.

Why a lock and not just plain dicts: FastAPI dispatches sync endpoints onto
a threadpool, so two concurrent requests really do run in parallel threads.
Every mutation in main.py runs its whole read-check-write section under
``store.lock``, which is the in-memory equivalent of SQLite's
``BEGIN IMMEDIATE`` / Postgres ``SELECT ... FOR UPDATE``: the final-unit
stock reservation cannot be won twice.

Trade-offs (documented in the root README): no persistence across restarts
(the catalogue is re-seeded at boot so the app is usable immediately), and
all workers must share one process. For a multi-process deployment the same
critical section would move to a transactional
``UPDATE ... WHERE available_qty >= :qty`` on a real database.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class Sku:
    id: str
    product_id: str
    options: dict[str, str]
    price_cents: int
    image: str
    available_qty: int


@dataclass
class Dimension:
    id: str        # e.g. "colour"
    label: str     # display label, e.g. "Colour"
    values: list[str]


@dataclass
class Product:
    id: str
    name: str
    description: str
    currency: str
    dimensions: list[Dimension] = field(default_factory=list)
    skus: list[Sku] = field(default_factory=list)


@dataclass
class CartLine:
    sku_id: str
    quantity: int
    unit_price_cents: int  # snapshot of the server price at add time


@dataclass
class IdempotentRecord:
    request_hash: str      # detects same-key / different-body reuse
    status_code: int
    response_body: str     # JSON text, replayed verbatim


class Store:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.products: dict[str, Product] = {}
        self.skus: dict[str, Sku] = {}            # sku_id -> Sku (shared objects)
        self.carts: dict[str, list[CartLine]] = {}
        self.idempotency: dict[str, IdempotentRecord] = {}


def colour_svg(colour: str, size: str) -> str:
    """Generate a deterministic product image per variant (no binary assets)."""
    palette = {
        "Cobalt": ("#1e3a8a", "#3b82f6"),
        "Sand": ("#78591f", "#d6b16a"),
        "Slate": ("#1f2937", "#64748b"),
    }
    dark, light = palette.get(colour, ("#334155", "#94a3b8"))
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">'
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{dark}"/><stop offset="1" stop-color="{light}"/>'
        "</linearGradient></defs>"
        '<rect width="400" height="300" fill="url(#g)"/>'
        '<path d="M60 210 C120 150 180 130 250 150 C300 163 340 180 350 205 '
        'L350 220 L70 220 Z" fill="#f8fafc" opacity="0.92"/>'
        '<path d="M70 220 L350 220 L345 236 L75 236 Z" fill="#0f172a" opacity="0.85"/>'
        f'<text x="24" y="44" font-family="Arial" font-size="22" fill="#f8fafc">{colour} · {size}</text>'
        "</svg>"
    )


def create_store() -> Store:
    """Build and seed the catalogue.

    Seed data satisfies the brief: >= 6 SKUs across two option dimensions,
    one *unavailable combination* (Slate 7 — no SKU row at all), one
    *out-of-stock SKU* (Cobalt 11 — qty 0), and one single-unit SKU
    (Sand 9) that makes the oversell race observable in the demo.
    """
    store = Store()
    product = Product(
        id="aurora-trail",
        name="Aurora Trail Runner",
        description=(
            "All-mountain trail shoe with a carbon-infused midsole plate, "
            "water-repellent ripstop upper and a 4 mm lugged outsole for wet rock."
        ),
        currency="USD",
        dimensions=[
            Dimension(id="colour", label="Colour", values=["Cobalt", "Sand", "Slate"]),
            Dimension(id="size", label="Size (US)", values=["7", "8", "9", "10", "11"]),
        ],
    )
    base_price = 14900
    for colour in ("Cobalt", "Sand", "Slate"):
        for size in ("7", "8", "9", "10", "11"):
            # Unavailable combination: Slate 7 was discontinued and simply
            # has no SKU row — the frontend must render it as impossible.
            if colour == "Slate" and size == "7":
                continue
            qty = 0 if (colour == "Cobalt" and size == "11") else 8
            if colour == "Sand" and size == "9":  # single unit for the race demo
                qty = 1
            sku_id = f"aurora-{colour.lower()}-{size}"
            price = base_price + (200 if size in ("10", "11") else 0)
            sku = Sku(
                id=sku_id,
                product_id=product.id,
                options={"colour": colour, "size": size},
                price_cents=price,
                image=f"/api/images/{sku_id}.svg",
                available_qty=qty,
            )
            product.skus.append(sku)
            store.skus[sku_id] = sku
    store.products[product.id] = product
    return store
