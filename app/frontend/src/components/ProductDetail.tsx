"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { addToCart, fetchProduct, newIdempotencyKey } from "@/lib/api";
import { ApiError, type ProductResponse } from "@/lib/types";
import { boundQuantity, formatPrice, resolveVariant, type Selection } from "@/lib/variants";

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; retryable: true }
  | { kind: "ready"; data: ProductResponse };

type CartState =
  | { kind: "idle" }
  | { kind: "pending" }
  | { kind: "success"; message: string }
  | { kind: "error"; message: string };

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

export default function ProductDetail({ productId }: { productId: string }) {
  const [load, setLoad] = useState<LoadState>({ kind: "loading" });
  const [selection, setSelection] = useState<Selection>({});
  const [quantity, setQuantity] = useState(1);
  const [cart, setCart] = useState<CartState>({ kind: "idle" });
  const [cartCount, setCartCount] = useState(0);

  // Abort the in-flight fetch when we re-fetch (retry) or unmount.
  const abortRef = useRef<AbortController | null>(null);

  const loadProduct = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoad({ kind: "loading" });
    try {
      const data = await fetchProduct(productId, controller.signal);
      if (!controller.signal.aborted) setLoad({ kind: "ready", data });
    } catch {
      if (!controller.signal.aborted) setLoad({ kind: "error", retryable: true });
    }
  }, [productId]);

  useEffect(() => {
    void loadProduct();
    return () => abortRef.current?.abort();
  }, [loadProduct]);

  const resolution = useMemo(() => {
    if (load.kind !== "ready") return null;
    return resolveVariant(load.data.dimensions, load.data.skus, selection);
  }, [load, selection]);

  const available = resolution?.sku?.availableQuantity ?? 0;

  // When the selected SKU changes (or stock refreshes), re-clamp the quantity
  // so the UI can never be left showing a count the server would reject.
  useEffect(() => {
    setQuantity((q) => (resolution?.sku ? boundQuantity(q, available) : 1));
  }, [resolution?.sku?.id, available, resolution]);

  function choose(dimensionId: string, value: string) {
    setSelection((prev) => ({ ...prev, [dimensionId]: value }));
    // Changing variant invalidates a prior add-to-cart message.
    setCart({ kind: "idle" });
  }

  async function handleAdd() {
    if (!resolution?.sku || !resolution.complete || resolution.outOfStock) return;
    setCart({ kind: "pending" });
    const key = newIdempotencyKey(); // one key per click -> double-click safe
    try {
      const res = await addToCart({ skuId: resolution.sku.id, quantity }, key);
      setCartCount(res.cart.totalItems);
      // Reflect the freshly reserved stock without a full reload.
      setLoad((prev) =>
        prev.kind === "ready"
          ? {
              kind: "ready",
              data: {
                ...prev.data,
                skus: prev.data.skus.map((s) =>
                  s.id === res.sku.id
                    ? { ...s, availableQuantity: res.sku.availableQuantity, inStock: res.sku.availableQuantity > 0 }
                    : s,
                ),
              },
            }
          : prev,
      );
      setCart({ kind: "success", message: `Added ${quantity} to cart.` });
    } catch (e) {
      const msg =
        e instanceof ApiError && e.code === "insufficient_stock"
          ? "Sorry, that quantity is no longer available."
          : e instanceof ApiError
            ? e.message
            : "Something went wrong. Please try again.";
      setCart({ kind: "error", message: msg });
    }
  }

  if (load.kind === "loading") {
    return <div className="state" role="status">Loading product…</div>;
  }
  if (load.kind === "error") {
    return (
      <div className="state" role="alert">
        <p>We couldn't load this product.</p>
        <button type="button" className="btn" onClick={() => void loadProduct()}>
          Try again
        </button>
      </div>
    );
  }

  const { product, dimensions, skus } = load.data;
  const sku = resolution?.sku ?? null;
  const canAdd = Boolean(sku && resolution?.complete && !resolution?.outOfStock && quantity >= 1);

  return (
    <article className="pdp">
      <div className="gallery">
        {sku ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={`${BASE}${sku.image}`} alt={`${product.name} in ${sku.options.colour}, size ${sku.options.size}`} width={400} height={300} />
        ) : (
          <div className="img-placeholder" aria-hidden="true">Select options</div>
        )}
      </div>

      <div className="details">
        <header>
          <h1>{product.name}</h1>
          <p className="desc">{product.description}</p>
        </header>

        {dimensions.map((dim) => (
          <fieldset className="optgroup" key={dim.id}>
            <legend>{dim.label}</legend>
            <div className="opts" role="radiogroup" aria-label={dim.label}>
              {dim.values.map((value) => {
                const selectable = resolution?.availability[dim.id]?.[value] ?? false;
                const selected = selection[dim.id] === value;
                return (
                  <button
                    key={value}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    aria-disabled={!selectable}
                    disabled={!selectable}
                    className={selected ? "opt selected" : "opt"}
                    onClick={() => choose(dim.id, value)}
                  >
                    {value}
                  </button>
                );
              })}
            </div>
          </fieldset>
        ))}

        <div className="buy">
          {sku ? (
            <>
              <p className="price" aria-live="polite">
                {formatPrice(sku.priceCents, product.currency)}
              </p>
              <p className="stock" aria-live="polite">
                {resolution?.outOfStock ? "Out of stock" : `${available} in stock`}
              </p>
              <label className="qty-label" htmlFor="qty">
                Quantity
                <input
                  id="qty"
                  type="number"
                  inputMode="numeric"
                  min={1}
                  max={Math.max(available, 1)}
                  value={quantity}
                  disabled={resolution?.outOfStock}
                  onChange={(e) => setQuantity(boundQuantity(e.target.value, available))}
                />
              </label>
            </>
          ) : (
            <p className="hint" aria-live="polite">
              {resolution && !resolution.complete
                ? "Choose all options to continue."
                : "This combination isn't available."}
            </p>
          )}

          <button
            type="button"
            className="btn primary"
            onClick={() => void handleAdd()}
            disabled={!canAdd || cart.kind === "pending"}
            aria-busy={cart.kind === "pending"}
          >
            {cart.kind === "pending" ? "Adding…" : "Add to cart"}
          </button>

          <div className="feedback" aria-live="polite" role="status">
            {cart.kind === "success" && <span className="ok">{cart.message}</span>}
            {cart.kind === "error" && <span className="err">{cart.message}</span>}
          </div>
        </div>

        <p className="cart-count" aria-live="polite">Cart: {cartCount} item{cartCount === 1 ? "" : "s"}</p>
      </div>
    </article>
  );
}
