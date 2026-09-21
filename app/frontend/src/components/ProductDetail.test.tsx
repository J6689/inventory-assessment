// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ProductDetail from "@/components/ProductDetail";
import type { ProductResponse } from "@/lib/types";

const productFixture: ProductResponse = {
  product: { id: "aurora-trail", name: "Aurora Trail Runner", description: "d", currency: "USD" },
  dimensions: [
    { id: "colour", label: "Colour", values: ["Cobalt", "Sand"] },
    { id: "size", label: "Size", values: ["8", "11"] },
  ],
  skus: [
    { id: "aurora-cobalt-8", options: { colour: "Cobalt", size: "8" }, priceCents: 14900, currency: "USD", image: "/api/images/a.svg", availableQuantity: 8, inStock: true },
    { id: "aurora-cobalt-11", options: { colour: "Cobalt", size: "11" }, priceCents: 15100, currency: "USD", image: "/api/images/b.svg", availableQuantity: 0, inStock: false },
    { id: "aurora-sand-8", options: { colour: "Sand", size: "8" }, priceCents: 14900, currency: "USD", image: "/api/images/c.svg", availableQuantity: 8, inStock: true },
    { id: "aurora-sand-11", options: { colour: "Sand", size: "11" }, priceCents: 15100, currency: "USD", image: "/api/images/d.svg", availableQuantity: 8, inStock: true },
  ],
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("ProductDetail", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.startsWith("/api/products/")) return jsonResponse(productFixture);
        if (url === "/api/cart/items" && init?.method === "POST") {
          return jsonResponse(
            {
              item: { skuId: "aurora-cobalt-8", quantity: 1, unitPriceCents: 14900 },
              sku: { id: "aurora-cobalt-8", availableQuantity: 7 },
              cart: { cartId: "default", totalItems: 1 },
              idempotentReplay: false,
            },
            201,
          );
        }
        return jsonResponse({ error: { code: "not_found", message: "n" } }, 404);
      }),
    );
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  async function selectVariantAndAdd() {
    const cobalt = await screen.findByRole("radio", { name: "Cobalt" });
    fireEvent.click(cobalt);
    fireEvent.click(screen.getByRole("radio", { name: "8" }));
    const addBtn = await screen.findByRole("button", { name: /add to cart/i });
    fireEvent.click(addBtn);
    return addBtn;
  }

  it("renders loading then product content", async () => {
    render(<ProductDetail productId="aurora-trail" />);
    expect(screen.getByRole("status")).toHaveTextContent(/loading/i);
    await screen.findByRole("heading", { name: "Aurora Trail Runner" });
  });

  it("disables the unavailable variant and keeps valid ones enabled", async () => {
    render(<ProductDetail productId="aurora-trail" />);
    const cobalt = await screen.findByRole("radio", { name: "Cobalt" });
    fireEvent.click(cobalt);
    // size 11 exists for Cobalt but is out of stock -> still selectable, shows "Out of stock"
    const size11 = screen.getByRole("radio", { name: "11" });
    expect(size11).not.toBeDisabled();
    fireEvent.click(size11);
    await screen.findByText(/out of stock/i);
    expect(screen.getByRole("button", { name: /add to cart/i })).toBeDisabled();
  });

  it("sends one request per double-click with a stable Idempotency-Key", async () => {
    render(<ProductDetail productId="aurora-trail" />);
    const addBtn = await selectVariantAndAdd();

    // Immediately click again while the first request is in flight.
    fireEvent.click(addBtn);
    fireEvent.click(addBtn);

    await waitFor(() => {
      expect(screen.getByText(/added 1 to cart/i)).toBeInTheDocument();
    });

    const calls = vi
      .mocked(fetch)
      .mock.calls.filter(([u, i]) => String(u) === "/api/cart/items" && i?.method === "POST");
    expect(calls.length).toBe(1); // button disabled while pending -> no duplicate submit

    const headers = calls[0]![1]!.headers as Record<string, string>;
    expect(headers["Idempotency-Key"]).toBeTruthy();
  });

  it("shows accessible error feedback when the server rejects the add", async () => {
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith("/api/products/")) return jsonResponse(productFixture);
      if (url === "/api/cart/items" && init?.method === "POST") {
        return jsonResponse(
          { error: { code: "insufficient_stock", message: "gone", details: {} } },
          409,
        );
      }
      return jsonResponse({}, 200);
    });

    render(<ProductDetail productId="aurora-trail" />);
    await selectVariantAndAdd();
    const err = await screen.findByText(/no longer available/i);
    expect(err.closest('[aria-live="polite"]')).not.toBeNull();
  });
});
