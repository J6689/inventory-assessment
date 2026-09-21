import { describe, expect, it } from "vitest";
import type { OptionDimension, Sku } from "./types";
import { boundQuantity, resolveVariant } from "./variants";

/** Fixture mirrors the backend seed: colour x size, with one discontinued
 *  combination (Slate 7 -> no SKU row) and one sold-out SKU (Cobalt 11). */
const dimensions: OptionDimension[] = [
  { id: "colour", label: "Colour", values: ["Cobalt", "Sand", "Slate"] },
  { id: "size", label: "Size (US)", values: ["7", "8", "9", "10", "11"] },
];

function mkSku(colour: string, size: string, qty: number): Sku {
  return {
    id: `aurora-${colour.toLowerCase()}-${size}`,
    options: { colour, size },
    priceCents: 14900,
    currency: "USD",
    image: `/api/images/aurora-${colour.toLowerCase()}-${size}.svg`,
    availableQuantity: qty,
    inStock: qty > 0,
  };
}

const skus: Sku[] = [];
for (const colour of ["Cobalt", "Sand", "Slate"]) {
  for (const size of ["7", "8", "9", "10", "11"]) {
    if (colour === "Slate" && size === "7") continue; // discontinued combo
    const qty = colour === "Cobalt" && size === "11" ? 0 : 8;
    skus.push(mkSku(colour, size, qty));
  }
}

describe("resolveVariant", () => {
  it("returns no SKU until every dimension is chosen", () => {
    const r = resolveVariant(dimensions, skus, { colour: "Cobalt" });
    expect(r.complete).toBe(false);
    expect(r.sku).toBeNull();
  });

  it("resolves a fully specified, in-stock selection", () => {
    const r = resolveVariant(dimensions, skus, { colour: "Cobalt", size: "8" });
    expect(r.complete).toBe(true);
    expect(r.sku?.id).toBe("aurora-cobalt-8");
    expect(r.outOfStock).toBe(false);
  });

  it("flags the sold-out SKU as out of stock, not unavailable", () => {
    const r = resolveVariant(dimensions, skus, { colour: "Cobalt", size: "11" });
    expect(r.sku).not.toBeNull(); // row exists
    expect(r.outOfStock).toBe(true);
  });

  it("disables the discontinued combination and its dependent values", () => {
    // With Slate chosen, size 7 has no matching SKU -> must be disabled.
    const r = resolveVariant(dimensions, skus, { colour: "Slate" });
    expect(r.availability.size?.["7"]).toBe(false);
    expect(r.availability.size?.["8"]).toBe(true);
    // And with size 7 chosen, Slate is disabled (no Slate-7 row).
    const r2 = resolveVariant(dimensions, skus, { size: "7" });
    expect(r2.availability.colour?.["Slate"]).toBe(false);
    expect(r2.availability.colour?.["Cobalt"]).toBe(true);
  });
});

describe("boundQuantity", () => {
  it("clamps to available stock and floors at 1", () => {
    expect(boundQuantity(50, 8)).toBe(8);
    expect(boundQuantity(3, 8)).toBe(3);
    expect(boundQuantity(0, 8)).toBe(1);
    expect(boundQuantity(-4, 8)).toBe(1);
  });
  it("treats non-integer / NaN input as 1", () => {
    expect(boundQuantity("abc", 8)).toBe(1);
    expect(boundQuantity(2.5, 8)).toBe(1);
    expect(boundQuantity("6", 8)).toBe(6);
  });
});
