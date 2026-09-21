/** API layer — the only place that talks to the backend.
 *  UI components never call fetch themselves (separation of concerns). */

import {
  ApiError,
  type AddToCartRequest,
  type AddToCartResponse,
  type CartResponse,
  type ProductResponse,
} from "./types";

// Same-origin by default; reviewers running `next dev` proxy /api via
// next.config, and the README documents BACKEND_URL for other setups.
const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, init);
  } catch {
    // Network-level failure (offline, backend down, CORS): surface as a
    // retryable error the UI can show a "Try again" affordance for.
    throw new ApiError(0, "network_error", "Could not reach the server.");
  }
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON error page */
  }
  if (!res.ok) {
    const err = (body as { error?: { code?: string; message?: string; details?: Record<string, unknown> } })?.error;
    throw new ApiError(
      res.status,
      err?.code ?? "unexpected",
      err?.message ?? `Request failed (${res.status}).`,
      err?.details,
    );
  }
  return body as T;
}

export function fetchProduct(productId: string, signal?: AbortSignal): Promise<ProductResponse> {
  return request<ProductResponse>(`/api/products/${encodeURIComponent(productId)}`, { signal });
}

export function fetchCart(cartId = "default"): Promise<CartResponse> {
  return request<CartResponse>(`/api/cart?cartId=${encodeURIComponent(cartId)}`);
}

/** Generate an Idempotency-Key per *intent* (one click = one key).
 *  crypto.randomUUID exists in every modern browser and in Node 19+. */
export function newIdempotencyKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `k-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function addToCart(
  req: AddToCartRequest,
  idempotencyKey: string,
): Promise<AddToCartResponse> {
  return request<AddToCartResponse>("/api/cart/items", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify({ cartId: req.cartId ?? "default", skuId: req.skuId, quantity: req.quantity }),
  });
}
