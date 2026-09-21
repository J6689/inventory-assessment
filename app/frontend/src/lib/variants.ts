/** Pure domain logic for variant resolution.
 *
 *  Deliberately free of React and fetch so it can be unit-tested directly —
 *  this is the layer that answers "given what the user selected, which SKU
 *  is it, is it buyable, and what may they still click?". */

import type { OptionDimension, Sku } from "./types";

export type Selection = Record<string, string>;

export interface VariantResolution {
  /** SKU matching the full selection, or null when incomplete/invalid. */
  sku: Sku | null;
  /** True when every dimension has a chosen value. */
  complete: boolean;
  /** True when the selection maps to a SKU row that exists but has qty 0. */
  outOfStock: boolean;
  /** For each dimension value: is there ANY SKU matching the current
   *  selection if that value were chosen? Values without a match are the
   *  "impossible combinations" the UI must disable. */
  availability: Record<string, Record<string, boolean>>;
}

function matchesPartial(sku: Sku, selection: Selection, dimensionId: string): boolean {
  for (const [dim, value] of Object.entries(selection)) {
    if (dim === dimensionId) continue;
    if (sku.options[dim] !== value) return false;
  }
  return true;
}

export function resolveVariant(
  dimensions: OptionDimension[],
  skus: Sku[],
  selection: Selection,
): VariantResolution {
  const byId = new Map(skus.map((s) => [s.id, s]));

  // A SKU exists only when every dimension has a value and one row matches.
  const complete = dimensions.every((d) => selection[d.id] !== undefined);
  let sku: Sku | null = null;
  if (complete) {
    for (const candidate of skus) {
      const allMatch = dimensions.every((d) => candidate.options[d.id] === selection[d.id]);
      if (allMatch) {
        sku = byId.get(candidate.id) ?? null;
        break;
      }
    }
  }

  // Availability per value: a value stays clickable when at least one SKU
  // row exists for (selection + that value). "Discontinued" combinations
  // have no row at all, so they fall out naturally.
  const availability: Record<string, Record<string, boolean>> = {};
  for (const dim of dimensions) {
    availability[dim.id] = {};
    for (const value of dim.values) {
      availability[dim.id]![value] = skus.some(
        (s) => s.options[dim.id] === value && matchesPartial(s, selection, dim.id),
      );
    }
  }

  return {
    sku,
    complete,
    outOfStock: sku !== null && sku.availableQuantity === 0,
    availability,
  };
}

/** Clamp a typed quantity to [1, available]. Non-integers and NaN fall back
 *  to 1 so the UI can never submit something the server would reject. */
export function boundQuantity(raw: number | string, available: number): number {
  const n = typeof raw === "string" ? Number(raw) : raw;
  if (!Number.isInteger(n) || n < 1) return 1;
  return Math.min(n, Math.max(available, 1));
}

export function formatPrice(cents: number, currency: string): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(cents / 100);
}
