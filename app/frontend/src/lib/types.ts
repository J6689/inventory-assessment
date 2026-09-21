/** API contract types — mirror app/backend responses exactly.
 *  Kept in one place so UI code never handles untyped fetch results. */

export interface ProductInfo {
  id: string;
  name: string;
  description: string;
  currency: string;
}

export interface OptionDimension {
  id: string; // "colour" | "size"
  label: string;
  values: string[];
}

export interface Sku {
  id: string;
  options: Record<string, string>;
  priceCents: number;
  currency: string;
  image: string;
  availableQuantity: number;
  inStock: boolean;
}

export interface ProductResponse {
  product: ProductInfo;
  dimensions: OptionDimension[];
  skus: Sku[];
}

export interface AddToCartRequest {
  skuId: string;
  quantity: number;
  cartId?: string;
}

export interface AddToCartResponse {
  item: { skuId: string; quantity: number; unitPriceCents: number };
  sku: { id: string; availableQuantity: number };
  cart: { cartId: string; totalItems: number };
  idempotentReplay: boolean;
}

export interface CartItem {
  skuId: string;
  quantity: number;
  unitPriceCents: number;
  options: Record<string, string>;
}

export interface CartResponse {
  cart: {
    cartId: string;
    items: CartItem[];
    totalItems: number;
    subtotalCents: number;
  };
}

/** Structured error envelope returned by the backend for every failure. */
export interface ApiErrorBody {
  error: {
    code: string; // "insufficient_stock" | "sku_not_found" | ...
    message: string;
    details?: Record<string, unknown>;
  };
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
