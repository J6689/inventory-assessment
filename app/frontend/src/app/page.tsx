import ProductDetail from "@/components/ProductDetail";

// Server component shell. The product id is fixed for this exercise; the
// interactive variant/cart logic lives in the client component below.
export default function Page() {
  return (
    <main className="page">
      <ProductDetail productId="aurora-trail" />
    </main>
  );
}
